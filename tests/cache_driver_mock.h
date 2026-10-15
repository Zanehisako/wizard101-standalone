#pragma once
// Compile the production cache against a controlled Vulkan dispatch table.
// Rendering/readback and concurrency are independently tested on the real driver.
#include "dxvk/dxvk_pipecache.h"
#include "util/util_cache_file.h"
#include <atomic>
#include <cassert>
#include <iostream>
#include <cstring>
using namespace dxvk;
namespace {
  VkPhysicalDeviceProperties props = {};
  std::atomic<int> active {0}, peak {0}, snapshots {0}, creates {0}, loaded {0}, nullCalls {0};
  std::atomic<bool> holdSnapshot {false}, snapshotEntered {false}, releaseSnapshot {false};
  std::atomic<bool> failSnapshot {false};
  bool rejectInitial = false, failCreate = false, failPipeline = false;
  VkResult VKAPI_CALL createCache(VkDevice, const VkPipelineCacheCreateInfo* info,
    const VkAllocationCallbacks*, VkPipelineCache* cache) {
    ++creates;
    if (info->initialDataSize) { ++loaded; if (rejectInitial) return VK_ERROR_INITIALIZATION_FAILED; }
    if (failCreate) return VK_ERROR_OUT_OF_HOST_MEMORY;
    *cache = (VkPipelineCache)(uintptr_t)1; return VK_SUCCESS;
  }
  void VKAPI_CALL destroyCache(VkDevice,VkPipelineCache,const VkAllocationCallbacks*) {}
  VkResult VKAPI_CALL getData(VkDevice,VkPipelineCache,size_t* size,void* data) {
    assert(active==0); ++snapshots;
    assert(GetThreadPriority(GetCurrentThread()) == THREAD_PRIORITY_BELOW_NORMAL);
    if (failSnapshot) return VK_INCOMPLETE;
    if (holdSnapshot) { snapshotEntered=true; while (!releaseSnapshot) Sleep(1); }
    VkPipelineCacheHeaderVersionOne header = {};
    header.headerSize=sizeof(header); header.headerVersion=VK_PIPELINE_CACHE_HEADER_VERSION_ONE;
    header.vendorID=props.vendorID; header.deviceID=props.deviceID;
    std::memcpy(header.pipelineCacheUUID,props.pipelineCacheUUID,VK_UUID_SIZE);
    if (data) std::memcpy(data,&header,sizeof(header)); *size=sizeof(header);
    return VK_SUCCESS;
  }
  VkResult VKAPI_CALL createPipelines(VkDevice,VkPipelineCache cache,uint32_t,
    const VkGraphicsPipelineCreateInfo*,const VkAllocationCallbacks*,VkPipeline* pipeline) {
    if (!cache) ++nullCalls;
    int n=cache ? ++active : 0; int old=peak; while (old<n && !peak.compare_exchange_weak(old,n)) {}
    Sleep(3); if (cache) --active;
    if (failPipeline && cache) return VK_ERROR_UNKNOWN;
    *pipeline=(VkPipeline)(uintptr_t)2; return VK_SUCCESS;
  }
  VkResult VKAPI_CALL createComputePipelines(VkDevice d,VkPipelineCache c,uint32_t n,
    const VkComputePipelineCreateInfo*,const VkAllocationCallbacks* a,VkPipeline* p) {
    return createPipelines(d,c,n,nullptr,a,p);
  }
  void VKAPI_CALL destroyPipeline(VkDevice,VkPipeline,const VkAllocationCallbacks*) {}
}
namespace dxvk { Logger Logger::s_instance("cache-fault-probe.log"); }
namespace dxvk {
  struct PipelineSnapshotProbe {
    static void expire(DxvkPipelineCache& c) {
      std::lock_guard<dxvk::mutex> lock(c.m_lock);
      c.m_last -= std::chrono::seconds(6); c.m_cond.notify_one();
    }
    static bool clean(DxvkPipelineCache& c) {
      std::lock_guard<dxvk::mutex> lock(c.m_lock);
      return c.m_generation == c.m_saved;
    }
    static void notify(DxvkPipelineCache& c) { c.m_cond.notify_one(); }
    static std::unique_lock<std::shared_mutex> hold(DxvkPipelineCache& c) {
      return std::unique_lock<std::shared_mutex>(c.m_gate);
    }
    static void failStorage(DxvkPipelineCache& c) {
      std::lock_guard<dxvk::mutex> lock(c.m_lock);
      c.m_path = "C:\\graphics-patch-tests\\cache-fault\\absent-directory\\test.vkcache";
    }
  };
}
namespace dxvk::vk {
  LibraryLoader::~LibraryLoader() {}
  DeviceLoader::DeviceLoader(const Rc<InstanceLoader>& lib,bool owned,VkDevice device)
    : m_library(lib),m_getDeviceProcAddr(nullptr),m_device(device),m_owned(owned) {}
  PFN_vkVoidFunction DeviceLoader::sym(const char* name) const {
    if (!strcmp(name,"vkCreatePipelineCache")) return (PFN_vkVoidFunction)createCache;
    if (!strcmp(name,"vkDestroyPipelineCache")) return (PFN_vkVoidFunction)destroyCache;
    if (!strcmp(name,"vkGetPipelineCacheData")) return (PFN_vkVoidFunction)getData;
    if (!strcmp(name,"vkCreateGraphicsPipelines")) return (PFN_vkVoidFunction)createPipelines;
    if (!strcmp(name,"vkCreateComputePipelines")) return (PFN_vkVoidFunction)createComputePipelines;
    if (!strcmp(name,"vkDestroyPipeline")) return (PFN_vkVoidFunction)destroyPipeline;
    return nullptr;
  }
  DeviceFn::DeviceFn(const Rc<InstanceLoader>& lib,bool owned,VkDevice device) : DeviceLoader(lib,owned,device) {}
  DeviceFn::~DeviceFn() {}
}
