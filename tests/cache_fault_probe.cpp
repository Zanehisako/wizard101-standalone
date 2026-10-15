#include "cache_driver_mock.h"
int main() {
  props.vendorID=1; props.deviceID=2; props.driverVersion=3;
  SetEnvironmentVariableA("DXVK_W101_CACHE_PATH","C:\\graphics-patch-tests\\cache-fault\\data");
  env::createDirectory("C:\\graphics-patch-tests\\cache-fault\\data");
  Rc<vk::DeviceFn> device = new vk::DeviceFn(nullptr,false,(VkDevice)(uintptr_t)1);
  VkGraphicsPipelineCreateInfo info = {}; VkPipeline pipeline = VK_NULL_HANDLE;
  { DxvkPipelineCache cache(device,props);
    std::vector<dxvk::thread> workers;
    for (int i=0;i<8;++i) workers.emplace_back([&] { for(int j=0;j<20;++j) {
      VkPipeline handle = VK_NULL_HANDLE; assert(cache.createGraphics(&info,&handle)==VK_SUCCESS);
    }});
    for(auto& worker:workers) worker.join();
    assert(peak>1); // Snapshot exclusion must not serialize compilation.
    // New compilation resets the real five-second deadline. Spurious clean
    // notifications must not snapshot; shutdown still persists new additions.
    assert(snapshots==0); Sleep(3000);
    assert(cache.createGraphics(&info,&pipeline)==VK_SUCCESS);
    Sleep(2500); assert(snapshots==0);
    for (int i=0; snapshots<2 && i<4000; ++i) Sleep(1);
    assert(snapshots==2);
    for (int i=0; !PipelineSnapshotProbe::clean(cache) && i<1000; ++i) Sleep(1);
    assert(PipelineSnapshotProbe::clean(cache));
    int prior=snapshots;
    for (int i=0;i<30;++i) { PipelineSnapshotProbe::notify(cache); Sleep(40); }
    assert(snapshots==prior);
    assert(cache.createGraphics(&info,&pipeline)==VK_SUCCESS); cache.stop();
  }
  std::cout << "PASS clean/dirty scheduling, extended five-second deadline, spurious notifications, low-priority snapshots, shutdown save\n";
  { DxvkPipelineCache cache(device,props);
    assert(cache.createGraphics(&info,&pipeline)==VK_SUCCESS);
    auto gate=PipelineSnapshotProbe::hold(cache); int prior=snapshots;
    PipelineSnapshotProbe::expire(cache); Sleep(200);
    assert(snapshots==prior); gate.unlock();
    for (int i=0; !PipelineSnapshotProbe::clean(cache) && i<2500; ++i) Sleep(1);
    assert(PipelineSnapshotProbe::clean(cache));
  }
  { DxvkPipelineCache cache(device,props);
    assert(cache.createGraphics(&info,&pipeline)==VK_SUCCESS);
    failSnapshot=true; int prior=snapshots;
    PipelineSnapshotProbe::expire(cache); Sleep(2200);
    assert(snapshots-prior>=2 && snapshots-prior<=3);
    assert(!PipelineSnapshotProbe::clean(cache)); failSnapshot=false;
    for (int i=0; !PipelineSnapshotProbe::clean(cache) && i<2500; ++i) Sleep(1);
    assert(PipelineSnapshotProbe::clean(cache));
  }
  { DxvkPipelineCache cache(device,props);
    assert(cache.createGraphics(&info,&pipeline)==VK_SUCCESS);
    PipelineSnapshotProbe::failStorage(cache); PipelineSnapshotProbe::expire(cache);
    int prior=snapshots;
    for (int i=0; snapshots<prior+2 && i<2500; ++i) Sleep(1);
    assert(snapshots==prior+2); Sleep(1200); assert(snapshots==prior+2);
    assert(cache.createGraphics(&info,&pipeline)==VK_SUCCESS);
    cache.stop(); assert(snapshots==prior+2);
  }
  std::cout << "PASS snapshot gate retry, bounded transient snapshot retries, permanent storage failure without retries\n";
  // Block inside the snapshot while holding the actual production gate.
  // Compilation must complete before the gate is released, for both types.
  { DxvkPipelineCache cache(device,props);
    assert(cache.createGraphics(&info,&pipeline)==VK_SUCCESS);
    holdSnapshot=true;
    dxvk::thread snapshot([&] { cache.stop(); });
    for (int i=0; !snapshotEntered && i<10000; ++i) Sleep(1);
    assert(snapshotEntered);
    int oldNull=nullCalls;
    std::atomic<bool> done {false};
    dxvk::thread compile([&] {
      assert(cache.createGraphics(&info,&pipeline)==VK_SUCCESS);
      VkComputePipelineCreateInfo compute = {};
      assert(cache.createCompute(&compute,&pipeline)==VK_SUCCESS); done=true;
    });
    for (int i=0; !done && i<2000; ++i) Sleep(1);
    bool completed=done; releaseSnapshot=true; compile.join(); snapshot.join();
    assert(completed && nullCalls==oldNull+2); holdSnapshot=false;
  }
  int oldLoaded=loaded;
  { DxvkPipelineCache cache(device,props); } assert(loaded==oldLoaded+1);
  rejectInitial=true; int oldCreates=creates;
  { DxvkPipelineCache cache(device,props); assert(cache.createGraphics(&info,&pipeline)==VK_SUCCESS); }
  assert(creates==oldCreates+2); rejectInitial=false;
  failCreate=true; int oldNull=nullCalls;
  { DxvkPipelineCache cache(device,props); assert(cache.createGraphics(&info,&pipeline)==VK_SUCCESS); }
  assert(nullCalls==oldNull+1); failCreate=false;
  failPipeline=true; oldNull=nullCalls;
  { DxvkPipelineCache cache(device,props); assert(cache.createGraphics(&info,&pipeline)==VK_SUCCESS); }
  assert(nullCalls==oldNull+1); failPipeline=false;
  ++props.driverVersion; oldLoaded=loaded;
  { DxvkPipelineCache cache(device,props); } assert(loaded==oldLoaded);
  SetEnvironmentVariableA("DXVK_W101_CACHE","0"); oldCreates=creates; oldNull=nullCalls;
  { DxvkPipelineCache cache(device,props); assert(cache.createGraphics(&info,&pipeline)==VK_SUCCESS); }
  assert(creates==oldCreates && nullCalls==oldNull+1);
  std::cout << "PASS production cache: parallel compiles, exclusive idle/shutdown snapshots, held snapshot uncached graphics/compute completion, reload, driver mismatch, initial-data retry, creation failure, pipeline fallback, disabled path\n";
}
