#include "d3d9/wizard101_draw_layout_cache.h"
#include <windows.h>
#include <cstdio>
#include <stdexcept>
#include <cstring>
#include <cstdlib>
#include <vector>
using namespace dxvk;
using namespace dxvk::wizard101;
static void require(bool ok,const char* message) {if(!ok)throw std::runtime_error(message);}
static volatile uint64_t sink;
static bool failNextAllocation=false;
static uint64_t allocations=0;
void* operator new(size_t n) {++allocations;if(failNextAllocation){failNextAllocation=false;throw std::bad_alloc();}if(auto p=malloc(n))return p;throw std::bad_alloc();}
void operator delete(void* p) noexcept {free(p);}
void operator delete(void* p,size_t) noexcept {free(p);}
static bool same(const DrawLayout& a,const DrawLayout& b) {
 return a.attributeCount==b.attributeCount && a.bindingCount==b.bindingCount && a.streamsUsed==b.streamsUsed && a.streamsInstanced==b.streamsInstanced &&
  !memcmp(a.attributes.data(),b.attributes.data(),a.attributeCount*sizeof(DxvkVertexAttribute)) && !memcmp(a.bindings.data(),b.bindings.data(),a.bindingCount*sizeof(DxvkVertexBinding));
}
static double cpu() {
 FILETIME a,b,k,u;GetThreadTimes(GetCurrentThread(),&a,&b,&k,&u);
 auto ticks=[](FILETIME f){return(uint64_t(f.dwHighDateTime)<<32)|f.dwLowDateTime;};return(ticks(k)+ticks(u))/10000.0;
}
struct Query {
 std::shared_ptr<const DrawDeclFingerprint> decl;
 std::shared_ptr<const DrawSemanticFingerprint> sem;
 std::array<uint32_t,caps::MaxStreams> frequencies;
 unsigned flags;bool programmable;
 DrawLayoutLookup view() const {DrawLayoutLookup v;require(DrawLayoutLookup::make(decl.get(),sem.get(),frequencies,flags,programmable,v),"borrowed lookup");return v;}
};
template<typename F> static void component(const char* name,F action) {
 uint64_t n=0;double start=cpu(),elapsed;
 do {for(unsigned j=0;j<65536;++j)action(n++);elapsed=cpu()-start;}while(elapsed<2100);
 printf("COST {\"component\":\"%s\",\"cpu_ms\":%.6f,\"operations\":%llu,\"ns_per_operation\":%.6f}\n",name,elapsed,(unsigned long long)n,elapsed*1e6/n);fflush(stdout);
}
int main() {
 setvbuf(stdout,nullptr,_IONBF,0);
 try {
 D3D9VertexElements elements;DxsoIsgn isgn;isgn.elemCount=16;
 std::array<uint32_t,caps::MaxStreams> freq;freq.fill(1);
 for(unsigned i=0;i<16;++i){elements.push_back({WORD(i%4),WORD(i*16),D3DDECLTYPE_FLOAT4,D3DDECLMETHOD_DEFAULT,D3DDECLUSAGE_TEXCOORD,BYTE(15-i)});isgn.elems[i].semantic={DxsoUsage::Texcoord,i};}
 DrawLayout baseline;buildDrawLayout(elements,isgn,freq,0,baseline);
 {
  auto budget=makeDrawBudget();DrawLayoutCache cache(budget,true);
  auto keyFor=[&](const D3D9VertexElements& d,const DxsoIsgn& s,const auto& f,unsigned flags=0,bool programmable=true){
   return Query{prepareDrawDeclaration(budget,d),prepareDrawSemantics(budget,s),f,flags,programmable};};
  auto key=keyFor(elements,isgn,freq);DrawLayoutKey value;value.assign(key.view());
  require(cache.available() && !cache.find(key.view()) && cache.publish(key.view(),baseline),"pool reservation and publication");
  require(same(*cache.find(key.view()),baseline),"cached layout");
  auto different=[&](const Query& b){auto v=b.view();v.hash=key.view().hash;require(!(value==v) && !cache.find(v),"complete equality after forced hash collision");};
  for(unsigned i=0;i<elements.size();++i)for(unsigned field=0;field<6;++field){auto d=elements;switch(field){case 0:d[i].Stream^=1;break;case 1:d[i].Offset^=4;break;case 2:d[i].Type=D3DDECLTYPE_FLOAT3;break;case 3:d[i].Method=1;break;case 4:d[i].Usage=D3DDECLUSAGE_COLOR;break;case 5:d[i].UsageIndex^=1;break;}different(keyFor(d,isgn,freq));}
  for(unsigned i=0;i<isgn.elemCount;++i){auto s=isgn;s.elems[i].semantic.usage=DxsoUsage::Color;different(keyFor(elements,s,freq));s=isgn;s.elems[i].semantic.usageIndex^=1;different(keyFor(elements,s,freq));}
  auto s=isgn;std::swap(s.elems[0],s.elems[1]);different(keyFor(elements,s,freq));s.elemCount--;different(keyFor(elements,s,freq));
  auto d=elements;d.pop_back();different(keyFor(d,isgn,freq));
  for(unsigned i=0;i<freq.size();++i)for(unsigned f:{2u,D3DSTREAMSOURCE_INSTANCEDATA|1u,D3DSTREAMSOURCE_INSTANCEDATA|3u,D3DSTREAMSOURCE_INDEXEDDATA|2u}){
   auto changed=freq;changed[i]=f;different(keyFor(elements,isgn,changed));DrawLayout a;buildDrawLayout(elements,isgn,changed,1u<<i,a);auto k=keyFor(elements,isgn,changed,1u<<i);cache.publish(k.view(),a);require(same(*cache.find(k.view()),a),"frequency and instancing masks");
  }
  different(keyFor(elements,isgn,freq,1));different(keyFor(elements,isgn,freq,0,false));
  const auto allocated=allocations;const auto retained=cache.bytes();
  for(unsigned i=0;i<600;++i){key.frequencies[15]=i+100;auto k=key.view();DrawLayout a;buildDrawLayout(elements,isgn,key.frequencies,0,a);cache.publish(k,a);require(same(*cache.find(k),a),"pool eviction reuse");}
  require(allocations==allocated && cache.bytes()==retained && cache.entries()==256 && cache.evictions>0,"publication and eviction allocate nothing");
  cache.clear();require(cache.entries()==0 && !cache.find(key.view()) && cache.bytes()==retained,"reset reuses charged pool");
  {auto transient=keyFor(elements,isgn,freq);cache.publish(transient.view(),baseline);}
  auto recreated=keyFor(elements,isgn,freq);require(same(*cache.find(recreated.view()),baseline),"value keys survive metadata destruction");
  const auto withoutMetadata=cache.bytes();
  std::vector<std::shared_ptr<const DrawDeclFingerprint>> metadata;
  while(auto m=prepareDrawDeclaration(budget,elements))metadata.push_back(std::move(m));
  require(budget->bytes<=DrawLayoutLimit && !prepareDrawDeclaration(budget,elements),"metadata shares per-device cap");
  metadata.clear();require(cache.bytes()==withoutMetadata,"metadata releases local and process budget");
  {AssetLease pressure(AssetLimit-assetBytes.load());require(pressure.size,"shared pressure");
   require(!prepareDrawDeclaration(budget,elements),"metadata shared budget failure");
   DrawLayoutCache denied(budget);require(!denied.available(),"pool shared budget failure");
   require(cache.publish(key.view(),baseline),"reserved pool works under shared pressure");}
  const auto before=cache.bytes();failNextAllocation=true;require(!prepareDrawDeclaration(budget,elements),"metadata allocator failure");require(cache.bytes()==before,"failed metadata lease released");
  failNextAllocation=true;DrawLayoutCache denied(budget);require(!denied.available() && !failNextAllocation,"pool allocator failure");
  require(denied.bytes()<=DrawLayoutLimit,"failed pool charge bound");
  d=elements;d.resize(65);require(!prepareDrawDeclaration(budget,d),"unsupported length");
  d=elements;d[0].Stream=16;require(!prepareDrawDeclaration(budget,d),"unsupported stream");
  d=elements;d[0].Type=D3DDECLTYPE_UNUSED;require(!prepareDrawDeclaration(budget,d),"unsupported type");
  s=isgn;s.elemCount=33;require(!prepareDrawSemantics(budget,s),"unsupported signature");
 }
 require(assetBytes.load()==0,"all reservations released");
 {
  auto budget=makeDrawBudget();auto metadata=prepareDrawDeclaration(budget,elements);std::weak_ptr<DrawBudget> lifetime=budget;
  {DrawLayoutCache cache(budget);require(cache.available(),"lifetime cache");}budget.reset();
  require(!lifetime.expired() && assetBytes.load()>0,"metadata owns detached budget state");metadata.reset();require(lifetime.expired() && assetBytes.load()==0,"final metadata releases detached state");
 }
 {AssetLease pressure(AssetLimit);require(!makeDrawBudget(),"shared state exhaustion fallback");}
 failNextAllocation=true;require(!makeDrawBudget() && assetBytes.load()==0,"budget state allocator failure");
 printf("PASS structural equality, collisions, instancing, pool reuse, eviction, metadata lifetime, 1MiB and shared budget, allocator failure, invalidation and shutdown\n");
 {
  auto budget=makeDrawBudget();DrawLayoutCache cache(budget);
  auto decl=prepareDrawDeclaration(budget,elements);auto sem=prepareDrawSemantics(budget,isgn);
  std::array<std::array<uint32_t,caps::MaxStreams>,512> frequencies;
  std::array<DrawLayoutLookup,512> views;
  for(unsigned i=0;i<512;++i){frequencies[i]=freq;frequencies[i][15]=i+100;DrawLayoutLookup::make(decl.get(),sem.get(),frequencies[i],0,true,views[i]);}
  component("hashing_borrowed_key",[&](uint64_t n){freq[15]=n+100;DrawLayoutLookup key;DrawLayoutLookup::make(decl.get(),sem.get(),freq,0,true,key);sink+=key.hash;});
  for(unsigned i=0;i<256;++i)cache.publish(views[i],baseline);
  component("lookup_hit",[&](uint64_t n){auto p=cache.find(views[n%256]);sink+=p?p->streamsUsed:0;});
  component("lookup_miss",[&](uint64_t n){sink+=cache.find(views[256+n%256])!=nullptr;});
  component("publication_and_eviction",[&](uint64_t n){sink+=cache.publish(views[n%512],baseline);});
  component("fresh_fingerprint_preparation",[&](uint64_t n){elements[0].Offset=n%16;auto d=prepareDrawDeclaration(budget,elements);auto s=prepareDrawSemantics(budget,isgn);sink+=d->hash+s->hash;});elements[0].Offset=0;
 }
 // Fixed operation counts within each pair. Calibrate against the faster mode,
 // then require every measured sample to consume at least two seconds of CPU.
 auto bench=[&](bool enabled,unsigned workload,uint64_t loops){
  auto budget=enabled?makeDrawBudget():std::shared_ptr<DrawBudget>{};
  std::unique_ptr<DrawLayoutCache> cache;if(enabled)cache=std::make_unique<DrawLayoutCache>(budget);
  auto d=prepareDrawDeclaration(budget,elements);auto s=prepareDrawSemantics(budget,isgn);
  DrawLayout layout;auto frequencies=freq;frequencies.fill(1);
  const auto start=cpu();
  auto draw=[&](const D3D9VertexElements& input,const DxsoIsgn& signature,
      const DrawDeclFingerprint* fd,const DrawSemanticFingerprint* fs,uint64_t n) {
   frequencies[15]=workload?n+100:1;
   DrawLayoutLookup key;const DrawLayout* found=nullptr;bool supported=false;
   if(enabled){supported=DrawLayoutLookup::make(fd,fs,frequencies,0,true,key);if(supported)found=cache->find(key);}
   if(!found){buildDrawLayout(input,signature,frequencies,0,layout);if(supported)cache->publish(key,layout);found=&layout;}
   sink+=found->attributes[n%found->attributeCount].offset+found->bindings[0].fetchRate+found->streamsUsed;
  };
  if(workload==2) {
   for(uint64_t n=0;n<loops;++n){
    D3D9VertexElements fresh=elements;DxsoIsgn freshIsgn=isgn;
    fresh[0].Offset=WORD(n%1024);freshIsgn.elems[0].semantic.usageIndex=n%16;
    auto fd=prepareDrawDeclaration(budget,fresh);auto fs=prepareDrawSemantics(budget,freshIsgn);
    draw(fresh,freshIsgn,fd.get(),fs.get(),n);
   }
  } else {
   for(uint64_t n=0;n<loops;++n) draw(elements,isgn,d.get(),s.get(),n);
  }
  return cpu()-start;
 };
 for(unsigned w=0;w<3;++w){
  uint64_t loops=1000000;
  while(true){auto off=bench(false,w,loops),on=bench(true,w,loops);auto fast=std::min(off,on);if(fast>=2200)break;loops=uint64_t(loops*std::max(1.3,2400/std::max(1.0,fast)));}
  for(unsigned pair=0;pair<5;++pair){double off,on;if(pair%2){on=bench(true,w,loops);off=bench(false,w,loops);}else{off=bench(false,w,loops);on=bench(true,w,loops);}
   require(off>=2000 && on>=2000,"two seconds of thread CPU per sample");
   printf("BENCH {\"pair\":%u,\"workload\":\"%s\",\"order\":\"%s\",\"off_cpu_ms\":%.6f,\"on_cpu_ms\":%.6f,\"operations\":%llu,\"fingerprint_preparation_timed\":%s}\n",pair,w==0?"reuse":w==1?"cold":"fresh",pair%2?"on/off":"off/on",off,on,(unsigned long long)loops,w==2?"true":"false");
  }
 }
 require(assetBytes.load()==0,"benchmark shutdown");return 0;
 }catch(const std::exception& e){printf("FAIL %s\n",e.what());return 1;}
}
