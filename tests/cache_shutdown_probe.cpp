#include "cache_driver_mock.h"
#include "d3d9/d3d9_warmup.h"
int main() {
  assert(w101StutterFix());
  props.vendorID=1; props.deviceID=2; props.driverVersion=3;
  SetEnvironmentVariableA("DXVK_W101_CACHE_PATH","C:\\graphics-patch-tests\\cache-fault\\data");
  env::createDirectory("C:\\graphics-patch-tests\\cache-fault\\data");
  Rc<vk::DeviceFn> device=new vk::DeviceFn(nullptr,false,(VkDevice)(uintptr_t)1);
  VkGraphicsPipelineCreateInfo info={}; VkPipeline pipeline=VK_NULL_HANDLE;
  const auto key=Sha1Hash::compute("catalog-shutdown",16);
  W101ShaderCatalog::Record shader {1,{0xfffe0300,0x0000ffff}};
  { DxvkPipelineCache cache(device,props);
    W101ShaderCatalog catalog("shutdown-catalog.test",key,false,[](const auto&) {},[] { return false; });
    Sleep(100); catalog.record(shader.stage,shader.words.data(),shader.words.size()*4);
    std::vector<dxvk::thread> requests;
    for (unsigned i=0;i<8;++i) requests.emplace_back([&] {
      for (unsigned j=0;j<20;++j) { VkPipeline handle; assert(cache.createGraphics(&info,&handle)==VK_SUCCESS); }
    });
    for (auto& request:requests) request.join();
    assert(peak>1); Sleep(6200);
    // This exceeds the previous idle maintenance deadline in both writers.
    assert(snapshots==0 && GetFileAttributesA("shutdown-catalog.test")==INVALID_FILE_ATTRIBUTES);
    cache.stop(); catalog.stop();
    assert(snapshots==2 && PipelineSnapshotProbe::clean(cache));
    cache.stop(); catalog.stop(); assert(snapshots==2);
  }
  std::vector<char> data; std::vector<W101ShaderCatalog::Record> records;
  assert(cachefile::read("shutdown-catalog.test",key,data));
  assert(W101ShaderCatalog::decode(data,records) && records.size()==1);
  unsigned restores=0;
  { W101ShaderCatalog catalog("shutdown-catalog.test",key,true,[&](const auto&) { ++restores; },[] { return false; });
    catalog.waitStartup(); catalog.stop();
  }
  assert(restores==1);
  int prior=snapshots, priorLoaded=loaded;
  { DxvkPipelineCache cache(device,props); cache.stop(); }
  assert(loaded==priorLoaded+1 && snapshots==prior); // Clean restart does not rewrite.
  { DxvkPipelineCache cache(device,props);
    assert(cache.createGraphics(&info,&pipeline)==VK_SUCCESS);
    holdSnapshot=true; snapshotEntered=false; releaseSnapshot=false;
    dxvk::thread stop([&] { cache.stop(); });
    for (unsigned i=0;!snapshotEntered && i<5000;++i) Sleep(1); assert(snapshotEntered);
    int oldNull=nullCalls;
    // Required compilation retains the established uncached fallback if a
    // final snapshot is held; snapshot exclusion and driver locks are retained.
    VkComputePipelineCreateInfo compute={};
    assert(cache.createGraphics(&info,&pipeline)==VK_SUCCESS);
    assert(cache.createCompute(&compute,&pipeline)==VK_SUCCESS);
    assert(nullCalls==oldNull+2); releaseSnapshot=true; stop.join(); holdSnapshot=false;
  }
  { DxvkPipelineCache cache(device,props);
    assert(cache.createGraphics(&info,&pipeline)==VK_SUCCESS); failSnapshot=true;
    prior=snapshots; cache.stop(); assert(snapshots==prior+1); failSnapshot=false;
    cache.stop(); assert(snapshots==prior+1);
  }
  { DxvkPipelineCache cache(device,props);
    assert(cache.createGraphics(&info,&pipeline)==VK_SUCCESS); PipelineSnapshotProbe::failStorage(cache);
    cache.stop(); prior=snapshots; cache.stop(); assert(snapshots==prior);
  }
  { W101ShaderCatalog catalog("absent-directory/catalog.test",key,false,[](const auto&) {},[] { return false; });
    Sleep(100); catalog.record(shader.stage,shader.words.data(),shader.words.size()*4); catalog.stop();
  }
  rejectInitial=true; int priorCreates=creates;
  { DxvkPipelineCache cache(device,props); assert(cache.createGraphics(&info,&pipeline)==VK_SUCCESS); }
  assert(creates==priorCreates+2); rejectInitial=false;
  failCreate=true; int priorNull=nullCalls;
  { DxvkPipelineCache cache(device,props); assert(cache.createGraphics(&info,&pipeline)==VK_SUCCESS); }
  assert(nullCalls==priorNull+1); failCreate=false;
  failPipeline=true; priorNull=nullCalls;
  { DxvkPipelineCache cache(device,props); assert(cache.createGraphics(&info,&pipeline)==VK_SUCCESS); }
  assert(nullCalls==priorNull+1); failPipeline=false;
  ++props.driverVersion; priorLoaded=loaded;
  { DxvkPipelineCache cache(device,props); } assert(loaded==priorLoaded);
  SetEnvironmentVariableA("DXVK_W101_CACHE","0"); priorCreates=creates; priorNull=nullCalls;
  { DxvkPipelineCache cache(device,props); assert(cache.createGraphics(&info,&pipeline)==VK_SUCCESS); }
  assert(creates==priorCreates && nullCalls==priorNull+1);
  std::cout<<"PASS shutdown-only maintenance: no snapshots/catalog writes during play, one final save, unchanged formats and reload, held-snapshot fallback, clean/repeated stop, driver/snapshot/storage failures, incompatible/disabled cache\n";
}
