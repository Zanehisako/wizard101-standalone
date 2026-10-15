#include "dxvk/dxvk_instance.h"
#include "dxvk/dxvk_device.h"
#include "dxvk/dxvk_state_cache.h"
#include <thread>
#include <memory>
#include <iostream>
#include <fstream>
#include <stdexcept>
#include <chrono>
using namespace dxvk;
namespace dxvk { Logger Logger::s_instance("pipeline-opt.log"); }
static void check(bool value, const char* message) { if (!value) throw std::runtime_error(message); }
namespace dxvk {
  struct PipelineOptimizationProbe {
    static void pause(DxvkStateCache& cache) { cache.m_workerThreads.emplace_back([] {}); }
    static size_t queued(DxvkStateCache& cache) { return cache.m_workerQueue.size(); }
    static size_t entries(DxvkStateCache& cache) { return cache.m_entries.size(); }
    static unsigned pending(DxvkStateCache& cache) { return cache.m_workerPending.load(); }
    static void drain(DxvkStateCache& cache) {
      while (!cache.m_workerQueue.empty()) {
        auto item = cache.m_workerQueue.front(); cache.m_workerQueue.pop();
        cache.compilePipelines(item); --cache.m_workerPending;
      }
    }
    static void addMapping(DxvkStateCache& cache, const DxvkStateCacheKey& key) {
      cache.mapShaderToPipeline(key.vs,key); cache.mapShaderToPipeline(key.tcs,key);
      cache.mapShaderToPipeline(key.tes,key); cache.mapShaderToPipeline(key.gs,key);
      cache.mapShaderToPipeline(key.fs,key); cache.mapShaderToPipeline(key.cs,key);
    }
  };
}
static void lookupChecks() {
  const auto pass = reinterpret_cast<const DxvkRenderPass*>(uintptr_t(0x1000));
  const auto otherPass = reinterpret_cast<const DxvkRenderPass*>(uintptr_t(0x2000));
  DxvkGraphicsPipelineStateInfo state;
  DxvkGraphicsPipelineInstance valid(state,pass,VkPipeline(uintptr_t(1)));
  DxvkGraphicsPipelineLookup index;
  check(index.find(state,pass)==nullptr,"empty lookup"); index.publish(&valid,state,pass);
  check(index.find(state,pass)==&valid,"last-match lookup");
  check(index.find(state,otherPass)==nullptr,"render-pass pointer mismatch");
  for (size_t byte=0;byte<sizeof(state);++byte) {
    auto different=state; reinterpret_cast<unsigned char*>(&different)[byte]^=0x80;
    check(index.find(different,pass)==nullptr,"complete state mismatch");
  }
  auto collision=state;
  for (uint32_t i=1;;++i) {
    collision.sc.specConstants[0]=i;
    if (index.bucket(collision,pass)==index.bucket(state,pass)) break;
  }
  DxvkGraphicsPipelineInstance failed(collision,pass,VK_NULL_HANDLE);
  index.publish(&failed,collision,pass);
  check(index.find(state,pass)==&valid && index.find(collision,pass)==&failed,"collision exact equality and failure handle");
  constexpr unsigned count=2048;
  std::vector<std::unique_ptr<DxvkGraphicsPipelineInstance>> instances;
  std::vector<DxvkGraphicsPipelineStateInfo> states(count);
  for (unsigned i=0;i<count;++i) {
    states[i].sc.specConstants[0]=i+100000;
    instances.emplace_back(new DxvkGraphicsPipelineInstance(states[i],pass,VkPipeline(uintptr_t(i+2))));
  }
  std::atomic<unsigned> published {0}; std::atomic<bool> stop {false}, bad {false};
  std::vector<std::thread> readers;
  for (unsigned reader=0;reader<8;++reader) readers.emplace_back([&,reader] {
    unsigned j=reader;
    while (!stop.load()) {
      unsigned n=published.load(std::memory_order_acquire); if (!n) continue;
      auto i=(j++*17)%n;
      auto found=index.find(states[i],pass);
      if (found!=instances[i].get() || found->pipeline()!=VkPipeline(uintptr_t(i+2))) bad=true;
    }
  });
  for (unsigned i=0;i<count;++i) { index.publish(instances[i].get(),states[i],pass); published.store(i+1,std::memory_order_release); }
  stop=true; for (auto& reader:readers) reader.join();
  check(!bad,"concurrent publication");
  for (unsigned i=0;i<count;++i) check(index.find(states[i],pass)==instances[i].get(),"complete bucket coverage");
  // Join all readers before their owning instance/index storage is destroyed.
  std::cout<<"PASS lookup: complete state bytes, pass pointers, collisions, null failures, 2048 publications and 8 readers\n";
}
static Rc<DxvkShader> shader(VkShaderStageFlagBits stage, const char* path, const char* name) {
  std::ifstream file(path,std::ios::binary); DxvkShaderCreateInfo info={}; info.stage=stage;
  Rc<DxvkShader> result=new DxvkShader(info,SpirvCodeBuffer(file));
  result->setShaderKey(DxvkShaderKey(stage,Sha1Hash::compute(name,strlen(name)))); return result;
}
int main() {
  try {
    check(parsePipelineOpt("")==W101PipelineOpt::Off && parsePipelineOpt("invalid")==W101PipelineOpt::Off,"mode fallback");
    check(parsePipelineOpt("replay")==W101PipelineOpt::Replay && parsePipelineOpt("lookup")==W101PipelineOpt::Lookup && parsePipelineOpt("both")==W101PipelineOpt::Both,"mode parser");
    lookupChecks();
    SetEnvironmentVariableA("DXVK_STATE_CACHE","0");
    Rc<DxvkInstance> instance=new DxvkInstance(); auto adapter=instance->enumAdapters(0);
    check(adapter!=nullptr,"Vulkan adapter"); auto device=adapter->createDevice(instance,DxvkDeviceFeatures{});
    DxvkRenderPassPool passes(device.ptr()); DxvkPipelineManager manager(device.ptr(),&passes);
    auto vs=shader(VK_SHADER_STAGE_VERTEX_BIT,"snapshot.vert.spv","vertex");
    auto fs=shader(VK_SHADER_STAGE_FRAGMENT_BIT,"snapshot.frag.spv","fragment");
    auto cs=shader(VK_SHADER_STAGE_COMPUTE_BIT,"replay.comp.spv","compute");
    DxvkStateCacheKey graphics, compute; graphics.vs=vs->getShaderKey(); graphics.fs=fs->getShaderKey(); compute.cs=cs->getShaderKey();
    DxvkRenderPassFormat format; format.color[0]={VK_FORMAT_R8G8B8A8_UNORM,VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL};
    SetEnvironmentVariableA("DXVK_STATE_CACHE_PATH","state"); env::createDirectory("state");
    constexpr unsigned states=96;
    { DxvkStateCache cache(device.ptr(),&manager,&passes);
      for (unsigned i=0;i<states;++i) {
        DxvkGraphicsPipelineStateInfo state;
        state.ia=DxvkIaInfo(VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST,false,0);
        state.rs=DxvkRsInfo(true,false,VK_POLYGON_MODE_FILL,VK_CULL_MODE_NONE,VK_FRONT_FACE_COUNTER_CLOCKWISE,1,VK_SAMPLE_COUNT_1_BIT,VK_CONSERVATIVE_RASTERIZATION_MODE_DISABLED_EXT);
        state.sc.specConstants[0]=i; cache.addGraphicsPipeline(graphics,state,format);
      }
      DxvkComputePipelineStateInfo state; cache.addComputePipeline(compute,state); cache.stopWorkerThreads();
    }
    for (unsigned order=0;order<2;++order) {
      DxvkStateCache cache(device.ptr(),&manager,&passes); PipelineOptimizationProbe::pause(cache);
      check(PipelineOptimizationProbe::entries(cache)==states+1,"all cached states retained");
      cache.registerShader(order ? fs : vs); check(PipelineOptimizationProbe::pending(cache)==0,"wait for complete shader key");
      cache.registerShader(order ? vs : fs); cache.registerShader(cs);
      std::vector<std::thread> registrars;
      for (unsigned i=0;i<8;++i) registrars.emplace_back([&] { for (unsigned n=0;n<20;++n) { cache.registerShader(vs); cache.registerShader(fs); cache.registerShader(cs); } });
      for (auto& registrar:registrars) registrar.join();
      auto queued=PipelineOptimizationProbe::queued(cache);
      check(queued==PipelineOptimizationProbe::pending(cache),"queued and running job accounting");
      check(replayOpt() ? queued==2 : queued>30000,"replay lifetime dedup or off baseline");
      if (replayOpt()) {
        PipelineOptimizationProbe::drain(cache);
        check(manager.getPipelineCount().numGraphicsPipelines==states && manager.getPipelineCount().numComputePipelines==1,"all states compiled once");
        cache.registerShader(vs); cache.registerShader(fs); cache.registerShader(cs);
        check(PipelineOptimizationProbe::pending(cache)==0,"completed jobs never requeued");
      }
      cache.stopWorkerThreads(); check(!cache.isCompilingShaders(),"shutdown clears cancelled pending jobs");
      cache.registerShader(vs); check(PipelineOptimizationProbe::pending(cache)==0,"registration after shutdown");
      std::cout<<"PASS replay order "<<order<<": "<<queued<<" queued jobs, "<<states+1<<" retained states\n";
    }
    DxvkGraphicsPipelineShaders shaders; shaders.vs=vs; shaders.fs=fs;
    auto pipeline=manager.createGraphicsPipeline(shaders); auto pass=passes.getRenderPass(format);
    unsigned prior=manager.getPipelineCount().numGraphicsPipelines;
    for (unsigned trial=0;trial<24;++trial) {
      DxvkGraphicsPipelineStateInfo state;
      state.ia=DxvkIaInfo(VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST,false,0);
      state.rs=DxvkRsInfo(true,false,VK_POLYGON_MODE_FILL,VK_CULL_MODE_NONE,VK_FRONT_FACE_COUNTER_CLOCKWISE,1,VK_SAMPLE_COUNT_1_BIT,VK_CONSERVATIVE_RASTERIZATION_MODE_DISABLED_EXT);
      state.sc.specConstants[0]=10000+trial;
      std::atomic<unsigned> ready{0}; std::atomic<bool> go{false}, bad{false}; std::vector<std::thread> requests;
      for (unsigned i=0;i<16;++i) requests.emplace_back([&,i] {
        ++ready; while (!go) std::this_thread::yield();
        if (i%2) pipeline->compilePipeline(state,pass);
        else if (!pipeline->getPipelineHandle(state,pass,false)) bad=true;
      });
      while (ready!=16) std::this_thread::yield(); go=true;
      for (auto& request:requests) request.join();
      auto handle=pipeline->getPipelineHandle(state,pass,false);
      check(!bad && handle && manager.getPipelineCount().numGraphicsPipelines==prior+trial+1,"one driver compile per concurrent state");
      for (unsigned n=0;n<100;++n) check(pipeline->getPipelineHandle(state,pass,false)==handle,"stable pipeline handle");
    }
    std::cout<<"PASS real driver: 24 states, 16 concurrent foreground/background requests each, one compile per state\n";
    // Every stage participates in key equality, including nullable stages.
    std::unordered_set<DxvkStateCacheKey,DxvkHash,DxvkEq> keys;
    keys.insert(graphics);
    DxvkShaderKey DxvkStateCacheKey::*members[] = {&DxvkStateCacheKey::vs,&DxvkStateCacheKey::tcs,&DxvkStateCacheKey::tes,&DxvkStateCacheKey::gs,&DxvkStateCacheKey::fs,&DxvkStateCacheKey::cs};
    for (unsigned stage=0;stage<6;++stage) {
      auto key=graphics; key.*members[stage]=DxvkShaderKey(VkShaderStageFlagBits(1u<<stage),Sha1Hash::compute("distinct",8));
      check(keys.insert(key).second,"complete six-stage shader key");
    }
    manager.stopWorkerThreads();
    std::cout<<"PASS all pipeline optimization checks\n"; return 0;
  } catch (const std::exception& error) { std::cout<<"FAIL "<<error.what()<<'\n'; return 1; }
}
