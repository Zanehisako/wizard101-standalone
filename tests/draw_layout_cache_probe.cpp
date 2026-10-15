#include "d3d9/wizard101_draw_layout_cache.h"
#include <windows.h>
#include <cstdio>
#include <stdexcept>
#include <chrono>
#include <cstring>
#include <cstdlib>
using namespace dxvk;
using namespace dxvk::wizard101;
static void require(bool ok, const char* message) { if (!ok) throw std::runtime_error(message); }
static volatile uint64_t sink;
static bool failNextAllocation = false;
void* operator new(size_t n) { if (failNextAllocation) { failNextAllocation=false; throw std::bad_alloc(); } if(auto p=malloc(n)) return p; throw std::bad_alloc(); }
void operator delete(void* p) noexcept { free(p); }
void operator delete(void* p, size_t) noexcept { free(p); }
static bool same(const DrawLayout& a, const DrawLayout& b) {
  return a.attributeCount==b.attributeCount && a.bindingCount==b.bindingCount && a.streamsUsed==b.streamsUsed && a.streamsInstanced==b.streamsInstanced &&
    !memcmp(a.attributes.data(),b.attributes.data(),a.attributeCount*sizeof(DxvkVertexAttribute)) && !memcmp(a.bindings.data(),b.bindings.data(),a.bindingCount*sizeof(DxvkVertexBinding));
}
int main() {
 try {
  D3D9VertexElements elements;
  DxsoIsgn isgn;
  isgn.elemCount=16;
  std::array<uint32_t,caps::MaxStreams> freq; freq.fill(1);
  for(unsigned i=0;i<16;++i) {
    elements.push_back({WORD(i%4),WORD(i*16),D3DDECLTYPE_FLOAT4,D3DDECLMETHOD_DEFAULT,D3DDECLUSAGE_TEXCOORD,BYTE(15-i)});
    isgn.elems[i].semantic={DxsoUsage::Texcoord,i};
  }
  auto keyFor=[&](const D3D9VertexElements& d, const DxsoIsgn& s, const auto& f, unsigned flags=0, bool programmable=true) {
    DrawLayoutKey key; require(DrawLayoutKey::make(d,s,f,flags,programmable,key),"key creation"); return key;
  };
  DrawLayout baseline; buildDrawLayout(elements,isgn,freq,0,baseline); auto key=keyFor(elements,isgn,freq);
  {
    DrawLayoutCache cache(true); require(cache.available(),"base reservation"); require(!cache.find(key),"first miss");
    require(cache.publish(key,baseline),"publication"); require(same(*cache.find(key),baseline),"cached layout");
    auto different=[&](const DrawLayoutKey& b) { require(!(b==key) && !cache.find(b),"collision must check full equality"); };
    for(unsigned i=0;i<elements.size();++i) {
      for(unsigned field=0;field<6;++field) {
        auto d=elements;
        switch(field) { case 0:d[i].Stream^=1;break; case 1:d[i].Offset^=4;break; case 2:d[i].Type=D3DDECLTYPE_FLOAT3;break; case 3:d[i].Method=1;break; case 4:d[i].Usage=D3DDECLUSAGE_COLOR;break; case 5:d[i].UsageIndex^=1;break; }
        different(keyFor(d,isgn,freq));
      }
    }
    for(unsigned i=0;i<isgn.elemCount;++i) {
      auto s=isgn; s.elems[i].semantic.usage=DxsoUsage::Color; different(keyFor(elements,s,freq));
      s=isgn; s.elems[i].semantic.usageIndex^=1; different(keyFor(elements,s,freq));
    }
    auto s=isgn; std::swap(s.elems[0],s.elems[1]); different(keyFor(elements,s,freq));
    s.elemCount--; different(keyFor(elements,s,freq));
    auto d=elements; d.pop_back(); different(keyFor(d,isgn,freq));
    for(unsigned i=0;i<freq.size();++i) {
      for(unsigned f:{2u, D3DSTREAMSOURCE_INSTANCEDATA|1u,D3DSTREAMSOURCE_INSTANCEDATA|3u,D3DSTREAMSOURCE_INDEXEDDATA|2u}) {
        auto changed=freq; changed[i]=f; different(keyFor(elements,isgn,changed));
        DrawLayout a; buildDrawLayout(elements,isgn,changed,1u<<i,a); auto k=keyFor(elements,isgn,changed,1u<<i);
        cache.publish(k,a); require(same(*cache.find(k),a),"frequency layout and stream masks");
      }
    }
    different(keyFor(elements,isgn,freq,1)); different(keyFor(elements,isgn,freq,0,false));
    for(unsigned i=0;i<600;++i) { auto f=freq; f[15]=i+100; auto k=keyFor(elements,isgn,f); DrawLayout a; buildDrawLayout(elements,isgn,f,0,a); cache.publish(k,a); require(same(*cache.find(k),a),"evicted layouts"); }
    require(cache.entries()==256 && cache.bytes()<=DrawLayoutLimit && cache.evictions>0,"entry and byte caps");
    cache.clear(); require(cache.entries()==0 && !cache.find(key),"clear invalidation");
    AssetLease pressure(AssetLimit-assetBytes.load()); require(pressure.size,"pressure reservation");
    require(!cache.publish(key,baseline),"shared budget admission fallback");
  }
  require(assetBytes.load()==0,"all reservations released");
  {
    DrawLayoutCache cache; failNextAllocation=true; require(!cache.publish(key,baseline),"real allocator failure fallback");
    require(cache.entries()==0 && assetBytes.load()==cache.bytes(),"failed publication lease released");
  }
  { AssetLease pressure(AssetLimit); DrawLayoutCache cache; require(!cache.available() && !cache.find(key) && !cache.publish(key,baseline),"base budget failure"); }
  {
    DrawLayoutKey unsupported; auto d=elements; d.resize(65); require(!DrawLayoutKey::make(d,isgn,freq,0,true,unsupported),"unsupported declaration");
    d=elements; d[0].Stream=16; require(!DrawLayoutKey::make(d,isgn,freq,0,true,unsupported),"unsupported stream");
    d=elements; d[0].Type=D3DDECLTYPE_UNUSED; require(!DrawLayoutKey::make(d,isgn,freq,0,true,unsupported),"unsupported type");
  }
  printf("PASS structural equality, forced collisions, instancing, 256-entry eviction, 1MiB cap, shared budget, allocator failure, invalidation and shutdown\n");
  auto cpu=[] { FILETIME a,b,k,u; GetThreadTimes(GetCurrentThread(),&a,&b,&k,&u); auto ticks=[](FILETIME f) {return (uint64_t(f.dwHighDateTime)<<32)|f.dwLowDateTime;};return (ticks(k)+ticks(u))/10000.0; };
  auto bench=[&](bool enabled,bool cold) {
    DrawLayoutCache cache; DrawLayout layout;
    const unsigned loops=1000000;
    const double start=cpu();
    for(unsigned n=0;n<loops;++n) {
      freq[15]=cold ? n+100 : 1;
      DrawLayoutKey k; const DrawLayout* found=nullptr; bool supported=false;
      if(enabled) { supported=DrawLayoutKey::make(elements,isgn,freq,0,true,k); if(supported) found=cache.find(k); }
      if(!found) { buildDrawLayout(elements,isgn,freq,0,layout); if(supported) cache.publish(k,layout); found=&layout; }
      sink += found->attributes[n%found->attributeCount].offset + found->bindings[0].fetchRate + found->streamsUsed;
    }
    return cpu()-start;
  };
  bench(false,false);bench(true,false);
  for(unsigned pair=0;pair<5;++pair) for(bool cold:{false,true}) {
    double off,on; if(pair%2) {on=bench(true,cold);off=bench(false,cold);} else {off=bench(false,cold);on=bench(true,cold);}
    printf("BENCH {\"pair\":%u,\"workload\":\"%s\",\"off_cpu_ms\":%.6f,\"on_cpu_ms\":%.6f,\"operations\":1000000}\n",pair,cold?"cold":"reuse",off,on);
  }
  require(assetBytes.load()==0,"benchmark shutdown releases budget");
  return 0;
 }catch(const std::exception& e) {printf("FAIL %s\n",e.what()); return 1;}
}
