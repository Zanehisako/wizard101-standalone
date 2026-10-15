#include "dxvk/dxvk_instance.h"
#include "dxvk/dxvk_device.h"
#include "dxvk/dxvk_state_cache.h"
#include "util/util_pipeline_compile.h"
#include <thread>
#include <future>
#include <fstream>
#include <iostream>
#include <chrono>
using namespace dxvk;
using namespace std::chrono_literals;
namespace dxvk { Logger Logger::s_instance("rendering-probe.log");
  struct RenderingProbe {
    static void pause(DxvkStateCache& cache) { cache.m_workerThreads.emplace_back([] {}); }
    static size_t queued(DxvkStateCache& cache) { return cache.m_workerQueue.size(); }
    static size_t entries(DxvkStateCache& cache) { return cache.m_entries.size(); }
  };
}
static void check(bool value, const char* message) { if (!value) throw std::runtime_error(message); }
static void coordination() {
  PipelineCompilation<DxvkGraphicsPipelineStateInfo, int> jobs;
  DxvkGraphicsPipelineStateInfo state;
  auto pass = reinterpret_cast<void*>(uintptr_t(1));
  std::atomic<unsigned> calls {0}, ready {0}, failures {0};
  std::atomic<bool> go {false};
  std::vector<std::thread> requests;
  for (unsigned i=0; i<16; ++i) requests.emplace_back([&] {
    ++ready; while (!go) std::this_thread::yield();
    try { jobs.get(state, pass, [&]() -> int { ++calls; Sleep(50); throw std::runtime_error("shared failure"); }); }
    catch (const std::runtime_error& e) { if (std::string(e.what()) == "shared failure") ++failures; }
  });
  while (ready!=16) std::this_thread::yield(); go=true;
  for (auto& t: requests) t.join();
  check(calls==1 && failures==16,"exceptions must complete all duplicate waiters once");
  try { jobs.get(state,pass,[&] { ++calls; return 9; }); } catch (...) {}
  check(calls==1,"terminal exception must not be recompiled");
  // Every byte and render-pass identity participates in the production key.
  for (size_t i=0; i<sizeof(state); ++i) {
    auto changed=state; reinterpret_cast<unsigned char*>(&changed)[i]^=0x80;
    check(jobs.get(changed,pass,[] { return 7; })==7,"complete state key equality");
  }
  check(jobs.get(state,nullptr,[] { return 0; })==0,"null result cached");
  check(jobs.get(state,nullptr,[] { return 9; })==0,"null result never retried");
  // Background work obtains permission before it claims a state. Foreground
  // can therefore claim that same queued state without waiting on the queue.
  WarmupGate gate(true); PipelineCompilation<DxvkComputePipelineStateInfo,int> queued;
  DxvkComputePipelineStateInfo compute;
  std::atomic<unsigned> compiles {0};
  std::future<int> background;
  {
    WarmupGate::Foreground required(gate);
    background=std::async(std::launch::async,[&] {
      WarmupGate::Background permit(gate); check(bool(permit),"background permission");
      return queued.get(compute,nullptr,[&] { ++compiles; return 42; });
    });
    check(background.wait_for(50ms)==std::future_status::timeout,"queued variants must yield to required work");
    check(queued.get(compute,nullptr,[&] { ++compiles; return 42; })==42,"foreground takeover of queued state");
  }
  check(background.get()==42 && compiles==1,"foreground/background share one compilation");
  {
    WarmupGate stopped(true); WarmupGate::Foreground required(stopped);
    auto pending=std::async(std::launch::async,[&] { WarmupGate::Background permit(stopped); return bool(permit); });
    stopped.stop(); check(!pending.get(),"shutdown cancels queued background permission");
  }
  std::cout<<"PASS coordination: exact state/pass keys, shared null and exception failures, foreground takeover, shutdown cancellation\n";
}
static PFN_vkCreateGraphicsPipelines graphicsOriginal;
static PFN_vkCreateComputePipelines computeOriginal;
static std::atomic<unsigned> driverCalls {0};
static std::atomic<bool> blockNext {false}, entered {false}, releaseCompile {false}, failAll {false};
static void beforeDriver() {
  ++driverCalls;
  if (blockNext.exchange(false)) { entered=true; while (!releaseCompile) Sleep(1); }
}
static VkResult VKAPI_CALL graphics(VkDevice d,VkPipelineCache c,uint32_t n,const VkGraphicsPipelineCreateInfo* i,const VkAllocationCallbacks* a,VkPipeline* p) {
  beforeDriver(); if (failAll) { *p=VK_NULL_HANDLE; return VK_ERROR_UNKNOWN; }
  return graphicsOriginal(d,c,n,i,a,p);
}
static VkResult VKAPI_CALL compute(VkDevice d,VkPipelineCache c,uint32_t n,const VkComputePipelineCreateInfo* i,const VkAllocationCallbacks* a,VkPipeline* p) {
  beforeDriver(); if (failAll) { *p=VK_NULL_HANDLE; return VK_ERROR_UNKNOWN; }
  return computeOriginal(d,c,n,i,a,p);
}
static Rc<DxvkShader> shader(VkShaderStageFlagBits stage,const char* file,const char* name) {
  std::ifstream input(file,std::ios::binary); DxvkShaderCreateInfo info={}; info.stage=stage;
  Rc<DxvkShader> result=new DxvkShader(info,SpirvCodeBuffer(input));
  result->setShaderKey(DxvkShaderKey(stage,Sha1Hash::compute(name,strlen(name)))); return result;
}
static DxvkGraphicsPipelineStateInfo graphicsState(unsigned id) {
  DxvkGraphicsPipelineStateInfo state;
  state.ia=DxvkIaInfo(VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST,false,0);
  state.rs=DxvkRsInfo(true,false,VK_POLYGON_MODE_FILL,VK_CULL_MODE_NONE,VK_FRONT_FACE_COUNTER_CLOCKWISE,1,VK_SAMPLE_COUNT_1_BIT,VK_CONSERVATIVE_RASTERIZATION_MODE_DISABLED_EXT);
  state.sc.specConstants[0]=id; return state;
}
template<typename Background,typename Foreground>
static void independent(Background background,Foreground foreground) {
  entered=false; releaseCompile=false; blockNext=true;
  auto a=std::async(std::launch::async,background);
  for (unsigned n=0; !entered && n<5000; ++n) Sleep(1);
  if (!entered) { releaseCompile=true; a.get(); throw std::runtime_error("driver interception did not execute"); }
  auto b=std::async(std::launch::async,foreground);
  bool completed=b.wait_for(w101StutterFix()?3s:200ms)==std::future_status::ready;
  releaseCompile=true; a.get(); check(b.get()!=VK_NULL_HANDLE,"required draw pipeline");
  check(completed==w101StutterFix(),"unrelated foreground compilation must avoid the broad lock when enabled");
}
int main() {
  try {
    coordination();
    SetEnvironmentVariableA("DXVK_STATE_CACHE","0");
    Rc<DxvkInstance> instance=new DxvkInstance(); auto adapter=instance->enumAdapters(0);
    check(adapter!=nullptr,"Vulkan adapter"); auto device=adapter->createDevice(instance,DxvkDeviceFeatures{});
    auto vk=device->vkd(); graphicsOriginal=vk->vkCreateGraphicsPipelines; computeOriginal=vk->vkCreateComputePipelines;
    vk->vkCreateGraphicsPipelines=graphics; vk->vkCreateComputePipelines=compute;
    DxvkRenderPassPool passes(device.ptr()); DxvkPipelineManager manager(device.ptr(),&passes);
    auto vs=shader(VK_SHADER_STAGE_VERTEX_BIT,"snapshot.vert.spv","vertex");
    auto fs=shader(VK_SHADER_STAGE_FRAGMENT_BIT,"snapshot.frag.spv","fragment");
    auto cs=shader(VK_SHADER_STAGE_COMPUTE_BIT,"replay.comp.spv","compute");
    DxvkGraphicsPipelineShaders gs; gs.vs=vs; gs.fs=fs; auto gp=manager.createGraphicsPipeline(gs);
    DxvkComputePipelineShaders cp; cp.cs=cs; auto computePipe=manager.createComputePipeline(cp);
    DxvkRenderPassFormat format; format.color[0]={VK_FORMAT_R8G8B8A8_UNORM,VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL};
    auto pass=passes.getRenderPass(format);
    independent([&] { gp->compilePipeline(graphicsState(1000),pass); },[&] { return gp->getPipelineHandle(graphicsState(1001),pass,false); });
    DxvkComputePipelineStateInfo a,b; a.sc.specConstants[0]=1000; b.sc.specConstants[0]=1001;
    independent([&] { computePipe->compilePipeline(a); },[&] { return computePipe->getPipelineHandle(b); });
    for (unsigned kind=0; kind<2; ++kind) for (unsigned trial=0; trial<24; ++trial) {
      unsigned prior=driverCalls; std::atomic<bool> failed {false}; std::vector<std::thread> requests;
      auto state=graphicsState(trial); DxvkComputePipelineStateInfo computeState; computeState.sc.specConstants[0]=trial;
      for (unsigned n=0; n<16; ++n) requests.emplace_back([&,n] {
        if (!kind) { if (n%2) gp->compilePipeline(state,pass); else if (!gp->getPipelineHandle(state,pass,false)) failed=true; }
        else { if (n%2) computePipe->compilePipeline(computeState); else if (!computePipe->getPipelineHandle(computeState)) failed=true; }
      });
      for (auto& request:requests) request.join();
      check(!failed && driverCalls==prior+1,"one driver compile per mixed foreground/background state");
    }
    failAll=true;
    for (unsigned kind=0; kind<2; ++kind) {
      unsigned prior=driverCalls; std::vector<std::thread> requests; std::atomic<bool> bad {false};
      auto state=graphicsState(2000); DxvkComputePipelineStateInfo c; c.sc.specConstants[0]=2000;
      for (unsigned n=0; n<16; ++n) requests.emplace_back([&] {
        auto handle=kind?computePipe->getPipelineHandle(c):gp->getPipelineHandle(state,pass,false);
        if (handle!=VK_NULL_HANDLE) bad=true;
      });
      for (auto& request:requests) request.join();
      check(!bad && driverCalls==prior+1,"one shared failed driver compilation");
    }
    failAll=false;
    std::cout<<"PASS real driver: unrelated graphics/compute progress, 48 states with 16 mixed requests, shared driver failures\n";
    SetEnvironmentVariableA("DXVK_STATE_CACHE_PATH","state"); env::createDirectory("state");
    DxvkStateCacheKey key; key.vs=vs->getShaderKey(); key.fs=fs->getShaderKey();
    { DxvkStateCache cache(device.ptr(),&manager,&passes);
      for (unsigned n=0; n<96; ++n) cache.addGraphicsPipeline(key,graphicsState(n),format);
      cache.stopWorkerThreads(); cache.stopWorkerThreads();
    }
    { DxvkStateCache cache(device.ptr(),&manager,&passes);
      check(RenderingProbe::entries(cache)==96,"state cache reload preserves every state");
      RenderingProbe::pause(cache); cache.registerShader(vs); cache.registerShader(fs);
      check(RenderingProbe::queued(cache)>0 && cache.isCompilingShaders(),"pending replay accounting");
      cache.stopWorkerThreads(); check(!cache.isCompilingShaders() && !RenderingProbe::queued(cache),"shutdown clears cancelled replay jobs");
      cache.registerShader(fs); check(!cache.isCompilingShaders(),"no registration after shutdown");
    }
    manager.stopWorkerThreads(); manager.stopWorkerThreads();
    vk->vkCreateGraphicsPipelines=graphicsOriginal; vk->vkCreateComputePipelines=computeOriginal;
    std::cout<<"PASS state reload, queued replay cancellation, repeated shutdown and post-shutdown registration\nPASS all rendering checks\n";
    return 0;
  } catch (const std::exception& error) { releaseCompile=true; std::cout<<"FAIL "<<error.what()<<'\n'; return 1; }
}
