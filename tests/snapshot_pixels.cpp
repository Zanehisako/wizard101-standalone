// Real-driver pixels with the production snapshot gate held. No test hook runs
// in the game DLL. The fault probe separately blocks inside vkGetPipelineCacheData.
#include "dxvk/dxvk_instance.h"
#include "dxvk/dxvk_device.h"
#include "dxvk/dxvk_pipecache.h"
#include <fstream>
#include <iostream>
#include <cassert>
using namespace dxvk;
namespace dxvk {
  Logger Logger::s_instance("snapshot-pixels.log");
  struct PipelineSnapshotProbe {
    static std::unique_lock<std::shared_mutex> hold(DxvkPipelineCache& cache) {
      return std::unique_lock<std::shared_mutex>(cache.m_gate);
    }
  };
}
static void check(VkResult r) { if(r!=VK_SUCCESS) throw std::runtime_error("Vulkan status "+std::to_string(r)); }
int main() {
  try {
    Rc<DxvkInstance> instance=new DxvkInstance(); auto adapter=instance->enumAdapters(0);
    auto dev=adapter->createDevice(instance,DxvkDeviceFeatures{}); auto vk=dev->vkd(); auto d=dev->handle();
    DxvkPipelineCache cache(vk,adapter->deviceProperties());
    auto shader=[&](const char* path) {
      std::ifstream f(path,std::ios::binary|std::ios::ate); auto size=f.tellg();
      if(size<=0) throw std::runtime_error("Missing shader");
      std::vector<uint32_t> words(size_t(size)/4); f.seekg(0); f.read((char*)words.data(),size);
      VkShaderModuleCreateInfo info={VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO}; info.codeSize=size_t(size); info.pCode=words.data();
      VkShaderModule m; check(vk->vkCreateShaderModule(d,&info,nullptr,&m)); return m;
    };
    auto vs=shader("snapshot.vert.spv"), fs=shader("snapshot.frag.spv");
    VkPipelineLayoutCreateInfo li={VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO}; VkPipelineLayout layout;
    check(vk->vkCreatePipelineLayout(d,&li,nullptr,&layout));
    VkAttachmentDescription attachment={}; attachment.format=VK_FORMAT_R8G8B8A8_UNORM; attachment.samples=VK_SAMPLE_COUNT_1_BIT;
    attachment.loadOp=VK_ATTACHMENT_LOAD_OP_CLEAR; attachment.storeOp=VK_ATTACHMENT_STORE_OP_STORE;
    attachment.initialLayout=VK_IMAGE_LAYOUT_UNDEFINED; attachment.finalLayout=VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL;
    VkAttachmentReference reference={0,VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL};
    VkSubpassDescription sub={}; sub.pipelineBindPoint=VK_PIPELINE_BIND_POINT_GRAPHICS; sub.colorAttachmentCount=1; sub.pColorAttachments=&reference;
    VkSubpassDependency dep={}; dep.srcSubpass=0; dep.dstSubpass=VK_SUBPASS_EXTERNAL;
    dep.srcStageMask=VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT; dep.dstStageMask=VK_PIPELINE_STAGE_TRANSFER_BIT;
    dep.srcAccessMask=VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT; dep.dstAccessMask=VK_ACCESS_TRANSFER_READ_BIT;
    VkRenderPassCreateInfo ri={VK_STRUCTURE_TYPE_RENDER_PASS_CREATE_INFO}; ri.attachmentCount=1; ri.pAttachments=&attachment; ri.subpassCount=1; ri.pSubpasses=&sub; ri.dependencyCount=1; ri.pDependencies=&dep;
    VkRenderPass pass; check(vk->vkCreateRenderPass(d,&ri,nullptr,&pass));
    DxvkImageCreateInfo ii={}; ii.type=VK_IMAGE_TYPE_2D; ii.format=attachment.format; ii.sampleCount=VK_SAMPLE_COUNT_1_BIT; ii.extent={16,16,1}; ii.numLayers=1; ii.mipLevels=1;
    ii.usage=VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT|VK_IMAGE_USAGE_TRANSFER_SRC_BIT; ii.stages=VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT|VK_PIPELINE_STAGE_TRANSFER_BIT; ii.access=VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT|VK_ACCESS_TRANSFER_READ_BIT; ii.tiling=VK_IMAGE_TILING_OPTIMAL; ii.layout=VK_IMAGE_LAYOUT_GENERAL;
    auto image=dev->createImage(ii,VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);
    DxvkImageViewCreateInfo vi={}; vi.format=ii.format; vi.usage=VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT; vi.aspect=VK_IMAGE_ASPECT_COLOR_BIT; vi.numLevels=1; vi.numLayers=1;
    auto view=dev->createImageView(image,vi); auto imageView=view->handle();
    VkFramebufferCreateInfo fi={VK_STRUCTURE_TYPE_FRAMEBUFFER_CREATE_INFO}; fi.renderPass=pass; fi.attachmentCount=1; fi.pAttachments=&imageView; fi.width=16; fi.height=16; fi.layers=1;
    VkFramebuffer framebuffer; check(vk->vkCreateFramebuffer(d,&fi,nullptr,&framebuffer));
    DxvkBufferCreateInfo bi={}; bi.size=16*16*4; bi.usage=VK_BUFFER_USAGE_TRANSFER_DST_BIT; bi.stages=VK_PIPELINE_STAGE_TRANSFER_BIT|VK_PIPELINE_STAGE_HOST_BIT; bi.access=VK_ACCESS_TRANSFER_WRITE_BIT|VK_ACCESS_HOST_READ_BIT;
    auto buffer=dev->createBuffer(bi,VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT|VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    VkPipelineShaderStageCreateInfo stages[2]={};
    for(int i=0;i<2;i++) { stages[i].sType=VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO; stages[i].stage=i?VK_SHADER_STAGE_FRAGMENT_BIT:VK_SHADER_STAGE_VERTEX_BIT; stages[i].module=i?fs:vs; stages[i].pName="main"; }
    VkPipelineVertexInputStateCreateInfo vertex={VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO};
    VkPipelineInputAssemblyStateCreateInfo ia={VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO}; ia.topology=VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST;
    VkViewport viewport={0,0,16,16,0,1}; VkRect2D scissor={{0,0},{16,16}};
    VkPipelineViewportStateCreateInfo vp={VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO}; vp.viewportCount=1; vp.pViewports=&viewport; vp.scissorCount=1; vp.pScissors=&scissor;
    VkPipelineRasterizationStateCreateInfo rs={VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO}; rs.polygonMode=VK_POLYGON_MODE_FILL; rs.lineWidth=1;
    VkPipelineMultisampleStateCreateInfo ms={VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO}; ms.rasterizationSamples=VK_SAMPLE_COUNT_1_BIT;
    VkPipelineColorBlendAttachmentState blend={}; blend.colorWriteMask=15;
    VkPipelineColorBlendStateCreateInfo cb={VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO}; cb.attachmentCount=1; cb.pAttachments=&blend;
    VkGraphicsPipelineCreateInfo pi={VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO}; pi.stageCount=2; pi.pStages=stages; pi.pVertexInputState=&vertex; pi.pInputAssemblyState=&ia; pi.pViewportState=&vp; pi.pRasterizationState=&rs; pi.pMultisampleState=&ms; pi.pColorBlendState=&cb; pi.layout=layout; pi.renderPass=pass;
    VkPipeline cached=VK_NULL_HANDLE, uncached=VK_NULL_HANDLE; check(cache.createGraphics(&pi,&cached));
    std::atomic<bool> held {false}, release {false};
    dxvk::thread snapshot([&] { auto gate=PipelineSnapshotProbe::hold(cache);
      held=true; while(!release) Sleep(1);
    });
    while(!held) Sleep(1);
    auto status=cache.createGraphics(&pi,&uncached);
    release=true; snapshot.join(); check(status);
    VkCommandPoolCreateInfo poolInfo={VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO}; poolInfo.queueFamilyIndex=dev->queues().graphics.queueFamily;
    VkCommandPool pool; check(vk->vkCreateCommandPool(d,&poolInfo,nullptr,&pool));
    auto render=[&](VkPipeline pipeline) {
      VkCommandBufferAllocateInfo ai={VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO}; ai.commandPool=pool; ai.level=VK_COMMAND_BUFFER_LEVEL_PRIMARY; ai.commandBufferCount=1;
      VkCommandBuffer cmd; check(vk->vkAllocateCommandBuffers(d,&ai,&cmd));
      VkCommandBufferBeginInfo begin={VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO}; check(vk->vkBeginCommandBuffer(cmd,&begin));
      VkClearValue clear={}; VkRenderPassBeginInfo rp={VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO}; rp.renderPass=pass; rp.framebuffer=framebuffer; rp.renderArea=scissor; rp.clearValueCount=1; rp.pClearValues=&clear;
      vk->vkCmdBeginRenderPass(cmd,&rp,VK_SUBPASS_CONTENTS_INLINE); vk->vkCmdBindPipeline(cmd,VK_PIPELINE_BIND_POINT_GRAPHICS,pipeline); vk->vkCmdDraw(cmd,3,1,0,0); vk->vkCmdEndRenderPass(cmd);
      VkBufferImageCopy copy={}; auto slice=buffer->getSliceHandle(); copy.bufferOffset=slice.offset; copy.imageSubresource={VK_IMAGE_ASPECT_COLOR_BIT,0,0,1}; copy.imageExtent=ii.extent;
      vk->vkCmdCopyImageToBuffer(cmd,image->handle(),VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,slice.handle,1,&copy);
      VkMemoryBarrier barrier={VK_STRUCTURE_TYPE_MEMORY_BARRIER}; barrier.srcAccessMask=VK_ACCESS_TRANSFER_WRITE_BIT; barrier.dstAccessMask=VK_ACCESS_HOST_READ_BIT;
      vk->vkCmdPipelineBarrier(cmd,VK_PIPELINE_STAGE_TRANSFER_BIT,VK_PIPELINE_STAGE_HOST_BIT,0,1,&barrier,0,nullptr,0,nullptr);
      check(vk->vkEndCommandBuffer(cmd)); VkSubmitInfo submit={VK_STRUCTURE_TYPE_SUBMIT_INFO}; submit.commandBufferCount=1; submit.pCommandBuffers=&cmd;
      dev->lockSubmission(); check(vk->vkQueueSubmit(dev->queues().graphics.queueHandle,1,&submit,VK_NULL_HANDLE)); check(vk->vkQueueWaitIdle(dev->queues().graphics.queueHandle)); dev->unlockSubmission();
      auto pixels=(uint32_t*)buffer->mapPtr(0); std::vector<uint32_t> result(pixels,pixels+256);
      vk->vkFreeCommandBuffers(d,pool,1,&cmd); return result;
    };
    auto a=render(cached), b=render(uncached); assert(a==b);
    for(auto pixel:b) assert(pixel==0xff00ff00u);
    vk->vkDestroyCommandPool(d,pool,nullptr); vk->vkDestroyPipeline(d,cached,nullptr); vk->vkDestroyPipeline(d,uncached,nullptr);
    vk->vkDestroyFramebuffer(d,framebuffer,nullptr); vk->vkDestroyRenderPass(d,pass,nullptr); vk->vkDestroyPipelineLayout(d,layout,nullptr); vk->vkDestroyShaderModule(d,vs,nullptr); vk->vkDestroyShaderModule(d,fs,nullptr);
    cache.stop(); std::cout << "PASS held snapshot: cached and uncached pipelines render identical 256 green pixels\n";
  } catch(const std::exception& e) { std::cerr << "FAIL " << e.what() << '\n'; return 1; }
}
