#pragma once
#include <emmintrin.h>
// Included after the device implementation. No game-private object layout or
// NiPixelData hook: every eligible managed upload reaches this renderer path.
namespace dxvk {
// SSE2 is part of the x64 ABI. Keep full validation inexpensive with unaligned
// vector loads and a bounded tail, comparing every canonical byte.
static bool equalScenePixels(const unsigned char* a,const unsigned char* b,size_t n) {
  while(n>=64) {
    auto same=_mm_cmpeq_epi8(_mm_loadu_si128((const __m128i*)a),_mm_loadu_si128((const __m128i*)b));
    for(size_t offset=16;offset<64;offset+=16)
      same=_mm_and_si128(same,_mm_cmpeq_epi8(_mm_loadu_si128((const __m128i*)(a+offset)),_mm_loadu_si128((const __m128i*)(b+offset))));
    if(_mm_movemask_epi8(same)!=0xffff) return false;
    a+=64;b+=64;n-=64;
  }
  while(n>=16) {
    if(_mm_movemask_epi8(_mm_cmpeq_epi8(_mm_loadu_si128((const __m128i*)a),_mm_loadu_si128((const __m128i*)b)))!=0xffff) return false;
    a+=16;b+=16;n-=16;
  }
  while(n--) if(*a++!=*b++) return false;
  return true;
}
bool D3D9DeviceEx::ReuseSceneUpload(D3D9CommonTexture* resource) {
  const auto& d=*resource->Desc();
  if(m_arrivalPreparing || !m_sceneTextures || resource->m_arrivalUploaded || resource->m_arrivalPartial
      || d.Pool!=D3DPOOL_MANAGED || d.Usage || d.ArraySize!=1 || d.Depth!=1
      || !d.MipLevels || d.MipLevels>15 || resource->GetType()!=D3DRTYPE_TEXTURE
      || resource->IsAnySubresourceLocked() || resource->GetImage()==nullptr
      || resource->m_arrivalWritten!=((1u<<d.MipLevels)-1)) return false;
  resource->m_arrivalUploaded=true;
  auto cache=wizard101::assetCache(this);if(!cache) return false;
  const DWORD error=GetLastError();
  struct PreserveError { DWORD error; ~PreserveError() {SetLastError(error);} } preserve{error};
  try {
    wizard101::AssetKey key{};key.parameters={3,d.Width,d.Height,d.MipLevels,uint32_t(d.Format),0,0,D3DPOOL_MANAGED,0,0,0,0};
    // An indexed sample fingerprint only selects a candidate. Full canonical
    // bytes below must match before any GPU copy, including on hash collisions.
    std::array<unsigned char,15*5*32> signature{};size_t signatureSize=0;
    size_t size=sizeof(wizard101::AssetEntry)+512+d.MipLevels*(sizeof(wizard101::AssetLevel)+64),pixels=0;
    std::vector<wizard101::AssetLevel> levels;
    for(UINT mip=0;mip<d.MipLevels;mip++) {
      wizard101::AssetLevel level{};level.width=std::max(1u,d.Width>>mip);level.height=std::max(1u,d.Height>>mip);
      if(!resource->NeedsUpload(mip) || !wizard101::layout(D3DFORMAT(d.Format),level.width,level.height,level.rowBytes,level.rows)) return false;
      pixels+=size_t(level.rowBytes)*level.rows;if(pixels>8u*1024u*1024u) return false;
      const auto* data=(const unsigned char*)resource->GetData(mip);if(!data) return false;
      const size_t pitch=align(level.rowBytes,4u);
      const size_t n=size_t(level.rowBytes)*level.rows;
      for(size_t fraction=0;fraction<5;fraction++) {
        const size_t count=std::min(size_t(32),n),offset=(n-count)*fraction/4;
        for(size_t j=0;j<count;j++) {
          size_t pos=offset+j;signature[signatureSize++]=data[(pos/level.rowBytes)*pitch+pos%level.rowBytes];
        }
      }
      levels.push_back(std::move(level));
    }
    if(!cache->key(signature.data(),signatureSize,key.parameters,key)) return false;
    ++m_sceneEligible;
    if(auto item=cache->sceneTemplate(key)) {
      auto src=static_cast<D3D9Texture2D*>(item->texture)->GetCommonTexture()->GetImage();
      auto dst=resource->GetImage();
      bool identical=item->entry->levels.size()==levels.size();
      for(UINT mip=0;identical && mip<levels.size();mip++) {
        const auto& expected=item->entry->levels[mip];const auto& current=levels[mip];
        if(expected.width!=current.width || expected.height!=current.height || expected.rowBytes!=current.rowBytes || expected.rows!=current.rows) {identical=false;break;}
        const auto* data=(const unsigned char*)resource->GetData(mip);size_t pitch=align(current.rowBytes,4u);
        if(pitch==current.rowBytes) identical=equalScenePixels(data,expected.pixels.data(),expected.pixels.size());
        else for(UINT row=0;identical && row<current.rows;row++) identical=equalScenePixels(data+row*pitch,expected.pixels.data()+row*current.rowBytes,current.rowBytes);
      }
      if(identical && src!=nullptr && src->info().format==dst->info().format && src->info().mipLevels==dst->info().mipLevels
          && src->info().layout==VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL
          && !wizard101::feature("W101_ARRIVAL_TEST","copy")) {
        EmitCs([src,dst](DxvkContext* ctx) { ctx->copySceneMipChain(dst,src); });
        resource->ClearDirtyBoxes();resource->ClearNeedsUpload();++m_sceneHits;
        UnmapTextures();ConsiderFlush(GpuFlushType::ImplicitWeakHint);return true;
      }
    }
    if(cache->find(key,false)) return false;
    // One-off arrivals retain the native path without a full snapshot allocation.
    // A second initialized occurrence qualifies the complete immutable record.
    if(!cache->recurring(key)) return false;
    auto lease=cache->reserve(size+pixels);
    if(!lease || !lease->size || wizard101::feature("W101_ARRIVAL_TEST","allocation")) return false;
    auto entry=std::make_shared<wizard101::AssetEntry>();entry->key=key;entry->format=D3DFORMAT(d.Format);
    entry->lease=lease;entry->levels=std::move(levels);
    for(UINT mip=0;mip<d.MipLevels;mip++) {
      auto& l=entry->levels[mip];l.pixels.resize(size_t(l.rowBytes)*l.rows);
      const auto* data=(const unsigned char*)resource->GetData(mip);size_t pitch=align(l.rowBytes,4u);
      for(UINT row=0;row<l.rows;row++) std::memcpy(l.pixels.data()+row*l.rowBytes,data+row*pitch,l.rowBytes);
    }
    cache->learnScene(entry);++m_sceneLearned;
  } catch(...) { }
  return false;
}
void D3D9DeviceEx::PrepareArrivalPipelines() {
  m_arrivalInputs.configure();
  if(!m_preparePipelines) return;
  m_arrivalInputs.restoring=true;
  try {
    DxsoModuleInfo info;info.options=m_dxsoOptions;
    for(const auto& r:m_arrivalInputs.records) {
      try {
        if(r.kind<=2) {
          // Explicit length bounds every DXSO iterator, including operands.
          DxsoReader reader(r.bytes.data(),r.bytes.size());DxsoModule module(reader);
          auto analysis=module.analyze();
          VkShaderStageFlagBits stage=r.kind==1?VK_SHADER_STAGE_VERTEX_BIT:VK_SHADER_STAGE_FRAGMENT_BIT;
          if(module.info().shaderStage()!=stage || module.info().majorVersion()>info.options.shaderModel
              || analysis.bytecodeByteLength!=r.bytes.size()) continue;
          D3D9CommonShader shader;uint32_t length;
          m_shaderModules->GetShaderModule(this,&shader,&length,stage,&info,r.bytes.data());
        } else if(r.kind==3 && r.bytes.size()==sizeof(D3D9FFShaderKeyVS)) {
          D3D9FFShaderKeyVS key;std::memcpy(&key,r.bytes.data(),sizeof(key));
          if(key.Data.Contents.LightCount>caps::MaxEnabledLights) continue;
          m_ffModules.GetShaderModule(this,key);
        } else if(r.kind==4 && r.bytes.size()==sizeof(D3D9FFShaderKeyFS)) {
          D3D9FFShaderKeyFS key;std::memcpy(&key,r.bytes.data(),sizeof(key));m_ffModules.GetShaderModule(this,key);
        } else continue;
        ++m_arrivalRestored;
      } catch(...) { }
    }
  } catch(...) { }
  // One state preparation worker drains and joins here. Its queues never run
  // during play; unseen pipeline states use synchronous foreground creation.
  m_dxvkDevice->finishArrivalPreparation();m_arrivalInputs.restoring=false;m_arrivalComplete=true;
}
// Correctness probes query existing counters explicitly. Ordinary launches do
// not emit counters, timing records or capture files.
extern "C" __declspec(dllexport) BOOL WINAPI W101ArrivalGetStats(IDirect3DDevice9* device,uint64_t* out) {
  if(!wizard101::feature("W101_PERFORMANCE_TEST") || !out) return FALSE;
  if(!device) {
    for(unsigned i=0;i<10;i++) out[i]=0;
    out[5]=wizard101::assetBytes.load();out[6]=wizard101::preparedAssetBytes.load();return TRUE;
  }
  auto* d=static_cast<D3D9DeviceEx*>(device);
  out[0]=d->m_sceneEligible;out[1]=d->m_sceneHits;out[2]=d->m_sceneLearned;
  out[3]=d->m_arrivalRestored;out[4]=d->m_arrivalComplete;
  out[5]=wizard101::assetBytes.load();out[6]=wizard101::preparedAssetBytes.load();
  auto cache=wizard101::assetCache(device);
  out[7]=cache?cache->preparedCount.load():0;
  auto stats=d->GetDXVKDevice()->getStatCounters();
  out[8]=stats.getCtr(DxvkStatCounter::PipeCountGraphics);
  out[9]=stats.getCtr(DxvkStatCounter::PipeCompilerBusy);
  return TRUE;
}
}
