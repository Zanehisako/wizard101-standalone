// Included only by verify_arrival_learning.py in its disposable renderer clone.
// Friendship adds no members or layout changes to the production classes.
#include "../dxvk/dxvk_state_cache.h"

namespace dxvk {
struct ArrivalPipelineVerificationProbe {
  static bool check(DxvkDevice* device, uint64_t* out) {
    auto& manager = device->m_objects.pipelineManager();
    auto* cache = manager.m_stateCache.ptr();
    if (!cache) return false;
    for (unsigned i = 0; i < 12; ++i) out[i] = 0;
    out[0] = cache->m_entries.size();
    out[7] = cache->m_pending.load();
    out[8] = cache->m_workerBusy.load();
    for (auto& worker : cache->m_workerThreads) out[9] += worker.joinable();
    out[10] = cache->m_workerQueue.size();
    out[11] = cache->m_stopThreads.load();
    const auto before = manager.getPipelineCount().numGraphicsPipelines;
    // Invoked before any draw, after CreateDevice returned. Never drain workers.
    if (out[7] || out[8] || out[9] || out[10]) return false;
    const DxvkShaderKey nullKey;
    for (const auto& entry : cache->m_entries) {
      if (!entry.shaders.cs.eq(nullKey)) continue;
      DxvkGraphicsPipelineShaders shaders;
      if (!cache->getShaderByKey(entry.shaders.vs, shaders.vs)
       || !cache->getShaderByKey(entry.shaders.tcs, shaders.tcs)
       || !cache->getShaderByKey(entry.shaders.tes, shaders.tes)
       || !cache->getShaderByKey(entry.shaders.gs, shaders.gs)
       || !cache->getShaderByKey(entry.shaders.fs, shaders.fs)
       || shaders.vs == nullptr) continue;
      ++out[1];
      auto* pipeline = manager.createGraphicsPipeline(shaders);
      auto* pass = cache->m_passManager->getRenderPass(entry.format);
      auto* instance = pipeline->findInstance(entry.gpState, pass);
      if (!instance) { ++out[4]; continue; }
      ++out[2];
      const auto existing = instance->pipeline();
      if (existing == VK_NULL_HANDLE) { ++out[5]; continue; }
      // Compare synchronous lookup with a non-null handle observed beforehand.
      if (pipeline->getPipelineHandle(entry.gpState, pass, false) == existing
       && pipeline->getPipelineHandle(entry.gpState, pass, false) == existing)
        ++out[3];
    }
    out[6] = manager.getPipelineCount().numGraphicsPipelines - before;
    return out[6] == 0;
  }
};
extern "C" __declspec(dllexport) BOOL WINAPI W101VerifyArrivalPipelineReuse(
    IDirect3DDevice9* device, uint64_t* out) {
  if (!device || !out || !wizard101::feature("W101_PERFORMANCE_TEST")) return FALSE;
  try {
    return ArrivalPipelineVerificationProbe::check(
      static_cast<D3D9DeviceEx*>(device)->GetDXVKDevice().ptr(), out);
  } catch (...) { return FALSE; }
}
}
