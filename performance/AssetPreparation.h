#pragma once
// Immutable native-D3DX results and one-use privately owned prepared textures. All D3D calls stay
// on the caller; workers below touch disjoint, caller-owned pixel regions.
#include <windows.h>
#include <d3d9.h>
#include <bcrypt.h>
#include <array>
#include <algorithm>
#include <atomic>
#include <condition_variable>
#include <cstring>
#include <deque>
#include <functional>
#include <list>
#include <memory>
#include <mutex>
#include <string>
#include <vector>
#include "../util/thread.h"
#include "../util/util_env.h"
#include "../util/log/log.h"

#include "wizard101_asset_budget.h"

namespace dxvk::wizard101 {
inline bool feature(const char* key, const char* value="1") { return env::getEnvVar(key)==value; }
struct ImageInfo { UINT Width,Height,Depth,MipLevels; D3DFORMAT Format; D3DRESOURCETYPE ResourceType; UINT ImageFileFormat; };
struct AssetKey {
  std::array<unsigned char,32> digest{};
  std::array<uint32_t,12> parameters{};
  bool operator==(const AssetKey& b) const { return digest==b.digest && parameters==b.parameters; }
};
struct AssetLevel { UINT width,height,rows,rowBytes; std::vector<unsigned char> pixels; };
struct AssetEntry {
  std::shared_ptr<AssetLease> lease;
  AssetKey key;
  D3DFORMAT format;
  std::vector<AssetLevel> levels;
  ImageInfo info{};
  bool hasInfo=false;
};
inline bool layout(D3DFORMAT f, UINT w, UINT h, UINT& bytes, UINT& rows) {
  rows=h;
  switch(f) {
    case D3DFMT_A8R8G8B8: case D3DFMT_X8R8G8B8: case D3DFMT_A8B8G8R8: case D3DFMT_X8B8G8R8: bytes=w*4; return true;
    case D3DFMT_A4R4G4B4: case D3DFMT_X4R4G4B4: case D3DFMT_A1R5G5B5: case D3DFMT_X1R5G5B5: case D3DFMT_R5G6B5: case D3DFMT_A8L8: bytes=w*2; return true;
    case D3DFMT_L8: case D3DFMT_A8: bytes=w; return true;
    case D3DFMT_DXT1: bytes=((w+3)/4)*8; rows=(h+3)/4; return true;
    case D3DFMT_DXT2: case D3DFMT_DXT3: case D3DFMT_DXT4: case D3DFMT_DXT5: bytes=((w+3)/4)*16; rows=(h+3)/4; return true;
    default: return false;
  }
}
#include "wizard101_asset_cache_impl.h"

// mode: A4, X4, A1, X1, R565. Output bytes are BGRA, matching the baseline.
inline uint32_t expand16(uint16_t p,uint32_t mode) {
  uint32_t a,r,g,b;
  if(mode<2) { a=mode==1?255:(p>>12)*17; r=((p>>8)&15)*17; g=((p>>4)&15)*17; b=(p&15)*17; }
  else if(mode<4) { a=(mode==3 || (p&32768))?255:0; r=(p>>10)&31; g=(p>>5)&31; b=p&31; r=(r<<3)|(r>>2); g=(g<<3)|(g>>2); b=(b<<3)|(b>>2); }
  else { a=255; r=(p>>11)&31; g=(p>>5)&63; b=p&31; r=(r<<3)|(r>>2); g=(g<<2)|(g>>4); b=(b<<3)|(b>>2); }
  return (a<<24)|(r<<16)|(g<<8)|b;
}
template<unsigned Mode> inline void convertRegion(const unsigned char* src,size_t srcPitch,unsigned char* dst,size_t dstPitch,UINT width,UINT first,UINT end) {
  for(UINT y=first;y<end;++y) {
    const uint16_t* __restrict input=(const uint16_t*)(src+size_t(y)*srcPitch);
    uint32_t* __restrict output=(uint32_t*)(dst+size_t(y)*dstPitch);
    for(UINT x=0;x<width;++x) output[x]=expand16(input[x],Mode);
  }
}
class PreparationWorkers {
  std::mutex lock;
  std::condition_variable ready;
  std::deque<std::function<void()>> jobs;
  std::array<dxvk::thread,2> workers;
  bool stopping=false;
public:
  PreparationWorkers() {
    try { for(auto& t:workers) t=dxvk::thread([this] {
      SetThreadPriority(GetCurrentThread(),THREAD_PRIORITY_BELOW_NORMAL);
      env::setThreadName("w101-asset-worker");
      for(;;) { std::function<void()> job;
        { std::unique_lock<std::mutex> guard(lock); ready.wait(guard,[this]{return stopping || !jobs.empty();});
          if(jobs.empty() && stopping) return;
          job=std::move(jobs.front()); jobs.pop_front(); }
        job();
      }
    }); } catch(...) { shutdown(); throw; }
  }
  ~PreparationWorkers() { shutdown(); }
  void shutdown() {
    { std::lock_guard<std::mutex> guard(lock); stopping=true; } ready.notify_all();
    for(auto& t:workers) if(t.joinable()) t.join();
  }
  void convert(const unsigned char* src,size_t srcPitch,unsigned char* dst,size_t dstPitch,UINT width,UINT rows,uint32_t mode) {
    using Kernel=void(*)(const unsigned char*,size_t,unsigned char*,size_t,UINT,UINT,UINT);
    static const Kernel kernels[]={convertRegion<0>,convertRegion<1>,convertRegion<2>,convertRegion<3>,convertRegion<4>};
    auto kernel=kernels[mode];
    auto stripe=[=](UINT first,UINT end) { kernel(src,srcPitch,dst,dstPitch,width,first,end); };
    if(size_t(width)*rows<131072 || rows<3) { stripe(0,rows); return; }
    struct Group { std::mutex lock; std::condition_variable done; UINT remaining=2; std::shared_ptr<AssetLease> lease; };
    auto lease=std::make_shared<AssetLease>(sizeof(Group)+256);
    if(!lease->size) { stripe(0,rows); return; }
    auto group=std::make_shared<Group>(); group->lease=lease;
    UINT one=rows/3,two=2*one;
    auto job=[stripe,group](UINT first,UINT end) { stripe(first,end); std::lock_guard<std::mutex> guard(group->lock); --group->remaining; group->done.notify_one(); };
    bool admitted=false;
    { std::lock_guard<std::mutex> guard(lock); if(!stopping && jobs.size()<=30) {
      const auto before=jobs.size();
      try { jobs.emplace_back([job,one]{job(0,one);}); jobs.emplace_back([job,one,two]{job(one,two);}); admitted=true; }
      catch(...) { while(jobs.size()>before) jobs.pop_back(); } } }
    if(!admitted) { stripe(0,rows); return; }
    ready.notify_all(); stripe(two,rows);
    std::unique_lock<std::mutex> guard(group->lock); group->done.wait(guard,[&]{return group->remaining==0;});
  }
};
}
