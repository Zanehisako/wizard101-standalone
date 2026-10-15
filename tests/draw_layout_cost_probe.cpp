#include "d3d9/wizard101_draw_layout_cache.h"
#include <windows.h>
#include <cstdio>
using namespace dxvk;
using namespace dxvk::wizard101;
static volatile uint64_t sink;
static double cpu() {
  FILETIME a,b,k,u; GetThreadTimes(GetCurrentThread(),&a,&b,&k,&u);
  auto ticks=[](FILETIME f) { return (uint64_t(f.dwHighDateTime)<<32)|f.dwLowDateTime; };
  return (ticks(k)+ticks(u))/10000.0;
}
template<typename F> static void measure(const char* name,F action) {
  uint64_t operations=0; double start=cpu(),elapsed;
  do { for(unsigned j=0;j<65536;++j) action(operations++); elapsed=cpu()-start; } while(elapsed<2100);
  printf("COST {\"component\":\"%s\",\"cpu_ms\":%.6f,\"operations\":%llu,\"ns_per_operation\":%.6f}\n",
    name,elapsed,(unsigned long long)operations,elapsed*1e6/operations); fflush(stdout);
}
int main() {
  D3D9VertexElements elements; DxsoIsgn isgn; isgn.elemCount=16;
  std::array<uint32_t,caps::MaxStreams> freq;freq.fill(1);
  for(unsigned i=0;i<16;++i) {
    elements.push_back({WORD(i%4),WORD(i*16),D3DDECLTYPE_FLOAT4,D3DDECLMETHOD_DEFAULT,D3DDECLUSAGE_TEXCOORD,BYTE(15-i)});
    isgn.elems[i].semantic={DxsoUsage::Texcoord,i};
  }
  DrawLayout layout;buildDrawLayout(elements,isgn,freq,0,layout);
  std::array<DrawLayoutKey,512> keys;
  for(unsigned i=0;i<keys.size();++i) {freq[15]=i+100;DrawLayoutKey::make(elements,isgn,freq,0,true,keys[i]);}
  measure("hashing_value_key",[&](uint64_t n) {freq[15]=n+100;DrawLayoutKey key;DrawLayoutKey::make(elements,isgn,freq,0,true,key);sink+=key.hash;});
  DrawLayoutCache cache;
  for(unsigned i=0;i<256;++i) cache.publish(keys[i],layout);
  measure("lookup_hit",[&](uint64_t n) {auto p=cache.find(keys[n%256]);sink+=p?p->streamsUsed:0;});
  measure("lookup_miss",[&](uint64_t n) {sink+=cache.find(keys[256+n%256])!=nullptr;});
  measure("publication_and_eviction",[&](uint64_t n) {sink+=cache.publish(keys[n%512],layout);});
  measure("original_construction",[&](uint64_t n) {buildDrawLayout(elements,isgn,freq,0,layout);sink+=layout.attributes[n%16].offset;});
}
