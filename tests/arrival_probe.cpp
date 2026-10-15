#define main prior_assets_main
#include "asset_preparation_probe.cpp"
#undef main
#include <thread>
#include <atomic>
#include <chrono>
using Stats=BOOL(WINAPI*)(IDirect3DDevice9*,uint64_t*);
static Stats stats;
static IDirect3DTexture9* scene(IDirect3DDevice9* d,UINT width=256,UINT height=128,UINT mips=4,D3DFORMAT format=D3DFMT_R5G6B5,unsigned seed=17,bool partial=false,bool missing=false) {
  IDirect3DTexture9* t=nullptr;check(d->CreateTexture(width,height,mips,0,format,D3DPOOL_MANAGED,&t,nullptr),"scene create");
  for(UINT mip=0;mip<mips-(missing?1:0);mip++) {
    UINT w=std::max(1u,width>>mip),h=std::max(1u,height>>mip);
    RECT region{0,0,LONG(w/2),LONG(h)};D3DLOCKED_RECT r{};
    check(t->LockRect(mip,&r,partial?&region:nullptr,0),"scene lock");
    unsigned bytes=(partial?w/2:w)*(format==D3DFMT_R5G6B5?2:4),rows=h;
    if(format==D3DFMT_DXT1 || format==D3DFMT_DXT3 || format==D3DFMT_DXT5) {
      rows=(h+3)/4;bytes=((partial?w/2:w)+3)/4*(format==D3DFMT_DXT1?8:16);
    }
    for(UINT y=0;y<rows;y++)for(UINT x=0;x<bytes;x++)((unsigned char*)r.pBits)[y*r.Pitch+x]=(x*7+y*13+mip*29+seed)&255;
    check(t->UnlockRect(mip),"scene unlock");
  }
  return t;
}
static uint64_t digest(const std::vector<unsigned char>& data) {uint64_t h=1469598103934665603ull;for(auto b:data)h=(h^b)*1099511628211ull;return h;}
int main(int argc,char** argv) {
  setvbuf(stdout,nullptr,_IONBF,0);
  try {
    const char* mode=argc>1?argv[1]:"verify";
    auto* api=Direct3DCreate9(D3D_SDK_VERSION);require(api,"api");
    stats=(Stats)GetProcAddress(GetModuleHandleA("d3d9.dll"),"W101ArrivalGetStats");require(stats,"probe interface");
    WNDCLASSA wc{};wc.lpfnWndProc=DefWindowProcA;wc.hInstance=GetModuleHandleA(nullptr);wc.lpszClassName="ArrivalProbe";RegisterClassA(&wc);
    HWND window=CreateWindowA(wc.lpszClassName,"Arrival correctness",WS_OVERLAPPEDWINDOW,0,0,640,480,nullptr,nullptr,wc.hInstance,nullptr);
    D3DPRESENT_PARAMETERS pp{};pp.Windowed=TRUE;pp.SwapEffect=D3DSWAPEFFECT_DISCARD;pp.BackBufferWidth=512;pp.BackBufferHeight=256;pp.BackBufferFormat=D3DFMT_A8R8G8B8;pp.hDeviceWindow=window;pp.PresentationInterval=D3DPRESENT_INTERVAL_IMMEDIATE;
    IDirect3DDevice9* d=nullptr;check(api->CreateDevice(0,D3DDEVTYPE_HAL,window,D3DCREATE_HARDWARE_VERTEXPROCESSING|D3DCREATE_MULTITHREADED,&pp,&d),"device");
    uint64_t before[10]{},after[10]{};require(stats(d,before),"startup stats");
    printf("START restored=%llu complete=%llu pipelines=%llu busy=%llu bytes=%llu speculative=%llu prepared=%llu\n",before[3],before[4],before[8],before[9],before[5],before[6],before[7]);
    if (GetEnvironmentVariableA("W101_VERIFY_PIPELINE_REUSE",nullptr,0)) {
      auto reuse=(Stats)GetProcAddress(GetModuleHandleA("d3d9.dll"),"W101VerifyArrivalPipelineReuse");
      require(reuse,"verification-only reuse interface");uint64_t handles[12]{};
      require(reuse(d,handles),"synchronous reuse and joined workers");
      printf("REUSE entries=%llu covered=%llu existing=%llu reused=%llu missing=%llu null=%llu created=%llu pending=%llu busy=%llu workers=%llu queued=%llu stopped=%llu\n",
        handles[0],handles[1],handles[2],handles[3],handles[4],handles[5],handles[6],handles[7],handles[8],handles[9],handles[10],handles[11]);
    }
    if(!strcmp(mode,"idle")) {require(d->Release()==0,"idle shutdown");api->Release();DestroyWindow(window);puts("PASS idle");return 0;}
    if(!strcmp(mode,"benchmark") || !strcmp(mode,"fallback-benchmark")) {
      const bool fallback=!strcmp(mode,"fallback-benchmark");const unsigned n=120;
      auto start=std::chrono::steady_clock::now();
      IDirect3DTexture9* last=nullptr;
      for(unsigned i=0;i<n;i++) {
        auto* t=scene(d,512,256,4,D3DFMT_R5G6B5,fallback?i+64:17);t->PreLoad();
        if(last)last->Release();last=t;
      }
      require(!sample(d,last,0).empty(),"batched upload GPU completion");last->Release();
      auto us=std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now()-start).count();
      stats(d,after);
      printf("BENCH us=%lld iterations=%u hits=%llu learned=%llu\n",(long long)us,n,after[1],after[2]);
    } else {
      for(D3DFORMAT format:{D3DFMT_R5G6B5,D3DFMT_A8R8G8B8,D3DFMT_DXT1,D3DFMT_DXT3,D3DFMT_DXT5}) {
        auto* a=scene(d,256,128,4,format);auto* b=scene(d,256,128,4,format);
        for(UINT mip=0;mip<4;mip++) {
          auto cpu=pixels(a,mip);auto gpu=sample(d,a,mip);
          require(cpu==pixels(b,mip),"canonical CPU pixels");require(gpu==sample(d,b,mip),"independent GPU mip pixels");
          printf("PIX format=%u mip=%u cpu=%llu gpu=%llu\n",unsigned(format),mip,digest(cpu),digest(gpu));
        }
        D3DLOCKED_RECT r{};check(a->LockRect(0,&r,nullptr,0),"mutation lock");((unsigned char*)r.pBits)[0]^=255;check(a->UnlockRect(0),"mutation unlock");
        require(pixels(a,0)!=pixels(b,0),"CPU mutation independence");require(sample(d,a,0)!=sample(d,b,0),"GPU mutation independence");
        a->Release();b->Release();
        if(format==D3DFMT_DXT1 || format==D3DFMT_DXT3 || format==D3DFMT_DXT5) continue;
        auto* oddA=scene(d,9,7,3,format);auto* oddB=scene(d,9,7,3,format);
        for(UINT mip=0;mip<3;mip++) {
          require(pixels(oddA,mip)==pixels(oddB,mip),"odd-sized canonical rows");
          auto gpu=sample(d,oddA,mip);require(gpu==sample(d,oddB,mip),"unaligned and tail GPU pixels");
          printf("PIX odd format=%u mip=%u gpu=%llu\n",unsigned(format),mip,digest(gpu));
        }
        oddA->Release();oddB->Release();
      }
      uint64_t collisionBefore[10]{},collisionAfter[10]{};stats(d,collisionBefore);
      auto* collision=scene(d);D3DLOCKED_RECT collisionLock{};
      check(collision->LockRect(0,&collisionLock,nullptr,0),"collision mutation");
      ((unsigned char*)collisionLock.pBits)[200]^=255;check(collision->UnlockRect(0),"collision unlock");
      auto collisionPixels=sample(d,collision,0);stats(d,collisionAfter);
      require(collisionAfter[1]==collisionBefore[1],"sample fingerprint collision must verify full bytes");
      printf("PIX collision gpu=%llu\n",digest(collisionPixels));collision->Release();
      uint64_t count[10]{};stats(d,count);
      auto* partial=scene(d,256,128,4,D3DFMT_R5G6B5,17,true);partial->PreLoad();
      for(UINT mip=0;mip<4;mip++)printf("PIX partial mip=%u gpu=%llu\n",mip,digest(sample(d,partial,mip)));
      partial->Release();
      auto* missing=scene(d,256,128,4,D3DFMT_R5G6B5,17,false,true);missing->PreLoad();
      for(UINT mip=0;mip<4;mip++)printf("PIX missing mip=%u gpu=%llu\n",mip,digest(sample(d,missing,mip)));
      missing->Release();
      IDirect3DTexture9* unwritten=nullptr;check(d->CreateTexture(32,16,3,0,D3DFMT_A8R8G8B8,D3DPOOL_MANAGED,&unwritten,nullptr),"unwritten create");
      for(UINT mip=0;mip<3;mip++)printf("PIX unwritten mip=%u gpu=%llu\n",mip,digest(sample(d,unwritten,mip)));
      unwritten->Release();
      uint64_t unchanged[10]{};stats(d,unchanged);require(unchanged[0]==count[0]&&unchanged[1]==count[1],"partial/uninitialized must bypass");
      std::atomic<bool> bad{false};std::vector<std::thread> workers;
      for(unsigned worker=0;worker<4;worker++)workers.emplace_back([&]{try{for(unsigned i=0;i<25;i++){auto* t=scene(d);t->PreLoad();t->Release();}}catch(...){bad=true;}});
      for(auto& worker:workers)worker.join();require(!bad,"concurrent upload correctness");
      if(!strcmp(mode,"pressure"))for(unsigned i=0;i<180;i++)for(unsigned repeat=0;repeat<2;repeat++){auto* t=scene(d,512,512,4,D3DFMT_A8R8G8B8,i+777);t->PreLoad();t->Release();}
      auto* invalid=(IDirect3DTexture9*)nullptr;
      require(FAILED(d->CreateTexture(0,0,1,0,D3DFMT_A8R8G8B8,D3DPOOL_MANAGED,&invalid,nullptr)),"invalid allocation semantics");
      stats(d,after);
      printf("RESULT eligible=%llu hits=%llu learned=%llu pipelines=%llu busy=%llu bytes=%llu speculative=%llu\n",after[0],after[1],after[2],after[8],after[9],after[5],after[6]);
      require(after[5]<=128u*1024u*1024u&&after[6]<=32u*1024u*1024u,"bounded storage");
      auto* inflight=scene(d);inflight->PreLoad();inflight->Release();
      uint64_t queued[10]{},evicted[10]{},reset[10]{};stats(d,queued);
      check(d->EvictManagedResources(),"eviction");stats(d,evicted);
      if(queued[1]>after[1])require(evicted[6]>0,"in-flight GPU storage must stay charged");
      check(d->Reset(&pp),"reset");stats(d,reset);
      require(reset[6]<=queued[6],"reset may retire but must not undercharge in-flight GPU storage");
      auto* post=scene(d);require(!sample(d,post,0).empty(),"post reset pixels");post->Release();
    }
    require(d->Release()==0,"no device reference cycle");api->Release();DestroyWindow(window);
    uint64_t retired[10]{};require(stats(nullptr,retired),"global retirement stats");
    require(retired[5]==0 && retired[6]==0,"GPU and CPU leases must retire at orderly shutdown");
    puts("PASS arrival correctness");return 0;
  } catch(const std::exception& e) {printf("ERROR %s\n",e.what());return 1;}
}
