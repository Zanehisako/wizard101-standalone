#include "d3d9/wizard101_draw_layout_direct.h"
#include "util/log/log.h"
#include <windows.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <stdexcept>
using namespace dxvk;
using namespace dxvk::wizard101;
namespace dxvk::wizard101 {
void originalDrawLayout(const D3D9VertexElements&, const DxsoIsgn&,
  const std::array<uint32_t,caps::MaxStreams>&, uint32_t, DirectDrawLayout&);
}
namespace dxvk { Logger Logger::s_instance("direct-unit.log"); }
static volatile uint64_t sink;
static uint64_t allocations = 0;
void* operator new(size_t n) { ++allocations; if(auto p=malloc(n)) return p; throw std::bad_alloc(); }
void operator delete(void* p) noexcept { free(p); }
void operator delete(void* p,size_t) noexcept { free(p); }
static void require(bool ok,const char* msg) { if(!ok) throw std::runtime_error(msg); }
static bool same(const DirectDrawLayout& a,const DirectDrawLayout& b) {
  return a.attributeCount==b.attributeCount && a.bindingCount==b.bindingCount &&
    a.streamsUsed==b.streamsUsed && a.streamsInstanced==b.streamsInstanced &&
    !memcmp(a.attributes.data(),b.attributes.data(),a.attributeCount*sizeof(DxvkVertexAttribute)) &&
    !memcmp(a.bindings.data(),b.bindings.data(),a.bindingCount*sizeof(DxvkVertexBinding));
}
static double cpu() {
  FILETIME a,b,k,u; require(GetThreadTimes(GetCurrentThread(),&a,&b,&k,&u),"thread CPU clock");
  auto ticks=[](FILETIME f){return(uint64_t(f.dwHighDateTime)<<32)|f.dwLowDateTime;};
  return(ticks(k)+ticks(u))/10000.0;
}
__attribute__((noinline)) static bool selected(bool enabled,const D3D9VertexElements& d,const DxsoIsgn& s,
    const std::array<uint32_t,caps::MaxStreams>& freq,uint32_t flags,DirectDrawLayout& out) {
  if(enabled && tryBuildDirectDrawLayout(d,s,freq,flags,out)) return true;
  originalDrawLayout(d,s,freq,flags,out); return false;
}
static void fixture(unsigned count,unsigned inputs,D3D9VertexElements& d,DxsoIsgn& s) {
  d.clear(); s.elemCount=inputs;
  for(unsigned j=0;j<count;++j) d.push_back({WORD(j%16),WORD(j*16),BYTE(j%17),BYTE(j%8),D3DDECLUSAGE_TEXCOORD,BYTE(count-1-j)});
  for(unsigned i=0;i<inputs;++i) s.elems[i].semantic={DxsoUsage::Texcoord,i};
}
static void structural() {
  std::array<uint32_t,caps::MaxStreams> freq; freq.fill(1);
  uint64_t cases=0,vectors=0; D3D9VertexElements d; DxsoIsgn s;
  auto compare=[&](bool expected) {
    DirectDrawLayout original,direct; memset(&direct,0xa5,sizeof(direct));
    auto untouched=direct; auto before=allocations;
    bool used=tryBuildDirectDrawLayout(d,s,freq,0xa55a,direct);
    require(allocations==before,"construction must not allocate");
    require(used==(expected && bool(W101_DIRECT_SSE2)),"vector eligibility");
    if(!used) {require(!memcmp(&direct,&untouched,sizeof(direct)),"fallback leaves output untouched");originalDrawLayout(d,s,freq,0xa55a,direct);}
    originalDrawLayout(d,s,freq,0xa55a,original);
    require(same(original,direct),"complete ordered attribute/binding/mask equality");
    ++cases; vectors+=used;
  };
  for(unsigned n=0;n<=65;++n) for(unsigned m=0;m<=32;++m) {
    fixture(n,m,d,s); bool eligible=n>=8 && n<=64 && m>=4;
    compare(eligible);
    if(n) {
      d[0].Usage=D3DDECLUSAGE_POSITIONT; s.elems[0].semantic={DxsoUsage::Position,0}; compare(eligible);
      s.elems[0].semantic={DxsoUsage::PositionT,0}; compare(eligible);
      if(n>1) {d[1]=d[0];d[1].Offset=999;d[1].Stream=15;s.elems[0].semantic={DxsoUsage::Position,0};compare(eligible);}
      for(unsigned j=0;j<freq.size();++j) freq[j]=D3DSTREAMSOURCE_INSTANCEDATA|(j+1);
      compare(eligible); freq.fill(1);
    }
  }
  // Every vector lane, block, scalar tail and first duplicate position.
  for(unsigned n=8;n<=64;++n) for(unsigned match=0;match<n;++match) {
    fixture(n,4,d,s); for(auto& e:d) {e.Usage=D3DDECLUSAGE_COLOR;e.UsageIndex=255;}
    d[match].Usage=D3DDECLUSAGE_TEXCOORD; d[match].UsageIndex=0;
    if(match+1<n) {d[match+1]=d[match];d[match+1].Offset=888;}
    compare(true);
  }
  fixture(16,16,d,s);
  for(unsigned j=0;j<freq.size();++j) for(uint32_t f:{0u,1u,2u,D3DSTREAMSOURCE_INSTANCEDATA|0x7fffffu,D3DSTREAMSOURCE_INDEXEDDATA|3u}) {
    freq[j]=f;compare(true);
  }
  fixture(16,16,d,s);d[0].Type=D3DDECLTYPE_UNUSED;compare(false);
  fixture(16,16,d,s);d[0].Usage=255;compare(false);
  fixture(16,16,d,s);s.elems[0].semantic.usageIndex=256;compare(false);
  fixture(16,16,d,s);s.elems[0].semantic.usage=DxsoUsage(256);compare(false);
  // Inputs for which the original builder itself is invalid are eligibility-only.
  DirectDrawLayout out;fixture(16,16,d,s);d[0].Stream=16;
  require(!tryBuildDirectDrawLayout(d,s,freq,0,out),"invalid stream fallback");
  fixture(16,16,d,s);s.elemCount=33;require(!tryBuildDirectDrawLayout(d,s,freq,0,out),"invalid shader length fallback");
  printf("PASS structural complete outputs, duplicates, missing, PositionT, formats, offsets, instancing, invalid inputs, tails, allocation-free cases=%llu vector_cases=%llu scalar_only=%d\n",
    (unsigned long long)cases,(unsigned long long)vectors,!W101_DIRECT_SSE2);
}
static double bench(unsigned mode,unsigned workload,uint64_t loops) {
  D3D9VertexElements d;DxsoIsgn s;fixture(workload==3?3:16,workload==3?3:16,d,s);
  std::array<uint32_t,caps::MaxStreams> freq;freq.fill(1);DirectDrawLayout layout;
  const auto start=cpu();
  for(uint64_t n=0;n<loops;++n) {
    freq[15]=workload==1?uint32_t(n+100):1;
    if(workload==2) {
      D3D9VertexElements fresh=d;DxsoIsgn signature=s;
      fresh[0].Offset=WORD(n%1024);signature.elems[0].semantic.usageIndex=n%16;
      if(mode==2) originalDrawLayout(fresh,signature,freq,0,layout);
      else selected(mode==1,fresh,signature,freq,0,layout);
    } else {
      if(mode==2) originalDrawLayout(d,s,freq,0,layout);
      else selected(mode==1,d,s,freq,0,layout);
    }
    sink+=layout.attributes[n%layout.attributeCount].offset+layout.bindings[0].fetchRate+layout.streamsUsed;
  }
  return cpu()-start;
}
static void benchmarks() {
  for(unsigned w=0;w<5;++w) {
    // Small uses on/fallback versus off. Disabled uses candidate/off versus baseline.
    unsigned workload=w==4?0:w;unsigned offMode=w==4?2:0,onMode=w==4?0:1;
    uint64_t loops=1000000;
    for(;;) {auto fast=std::min(bench(offMode,workload,loops),bench(onMode,workload,loops));if(fast>=2300)break;loops=uint64_t(loops*std::max(1.3,2600/std::max(1.0,fast)));}
    for(unsigned pair=0;pair<5;++pair) {
      double off,on;if(pair%2){on=bench(onMode,workload,loops);off=bench(offMode,workload,loops);}else{off=bench(offMode,workload,loops);on=bench(onMode,workload,loops);}
      require(off>=2000 && on>=2000,"two seconds of thread CPU per sample");
      printf("%s {\"pair\":%u,\"workload\":\"%s\",\"order\":\"%s\",\"off_cpu_ms\":%.6f,\"on_cpu_ms\":%.6f,\"operations\":%llu,\"stack_preparation_timed\":true,\"fresh_resource_creation_timed\":%s}\n",
        w<3?"BENCH":"FALLBACK",pair,w==0?"reuse":w==1?"cold":w==2?"fresh":w==3?"small":"disabled",pair%2?"on/off":"off/on",off,on,(unsigned long long)loops,w==2?"true":"false");
    }
  }
}
int main(int argc,char** argv) {
  setvbuf(stdout,nullptr,_IONBF,0);
  try { if(argc>1 && !strcmp(argv[1],"benchmark")) benchmarks();else structural();return 0; }
  catch(const std::exception& e) {printf("FAIL %s\n",e.what());return 1;}
}
