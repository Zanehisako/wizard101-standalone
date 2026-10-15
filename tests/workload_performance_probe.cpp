#include <windows.h>
#include <d3d9.h>
#include <d3dx9.h>
#include <cstdio>
#include <cstring>
#include <vector>
#include <fstream>
#include <chrono>
#include <stdexcept>
#include <functional>
static void check(HRESULT hr,const char* op) { if(FAILED(hr)) { printf("FAIL %s %08lx\n",op,(unsigned long)hr); throw std::runtime_error(op); } }
static uint32_t expected(uint16_t p,int mode) {
  // Independent integer scaling oracle, including the baseline's bit replication.
  unsigned a=255,r,g,b;
  if(mode<2) { if(mode==0)a=(p>>12)*17; r=((p>>8)&15)*17;g=((p>>4)&15)*17;b=(p&15)*17; }
  else { unsigned rv,gv,bv;
    if(mode<4) { if(mode==2)a=(p&32768)?255:0;rv=(p>>10)&31;gv=(p>>5)&31;bv=p&31; }
    else {rv=(p>>11)&31;gv=(p>>5)&63;bv=p&31;}
    r=rv*8+rv/4;g=mode==4?gv*4+gv/16:gv*8+gv/4;b=bv*8+bv/4;
  }
  return (a<<24)|(r<<16)|(g<<8)|b;
}
static std::vector<unsigned char> file(const char* name) { std::ifstream f(name,std::ios::binary); return {std::istreambuf_iterator<char>(f),{}}; }
static void verifyRegion(IDirect3DDevice9* dev,IDirect3DTexture9* texture,UINT width,UINT height,const std::function<uint32_t(UINT,UINT)>& oracle) {
  IDirect3DSurface9 *old=nullptr,*target=nullptr,*read=nullptr;check(dev->GetRenderTarget(0,&old),"save target");
  check(dev->CreateRenderTarget(width,height,D3DFMT_A8R8G8B8,D3DMULTISAMPLE_NONE,0,FALSE,&target,nullptr),"region target");check(dev->SetRenderTarget(0,target),"region bind target");
  D3DVIEWPORT9 viewport{0,0,width,height,0,1};check(dev->SetViewport(&viewport),"region viewport");
  struct V {float x,y,z,w,u,v;} quad[]={{-.5f,-.5f,0,1,0,0},{width-.5f,-.5f,0,1,1,0},{-.5f,height-.5f,0,1,0,1},{width-.5f,height-.5f,0,1,1,1}};
  check(dev->SetTexture(0,texture),"region texture");check(dev->BeginScene(),"region begin");check(dev->DrawPrimitiveUP(D3DPT_TRIANGLESTRIP,2,quad,sizeof(V)),"region sample");check(dev->EndScene(),"region end");
  check(dev->CreateOffscreenPlainSurface(width,height,D3DFMT_A8R8G8B8,D3DPOOL_SYSTEMMEM,&read,nullptr),"region readback");check(dev->GetRenderTargetData(target,read),"region copy");D3DLOCKED_RECT rect{};check(read->LockRect(&rect,nullptr,D3DLOCK_READONLY),"region pixels");
  for(UINT y=0;y<height;++y)for(UINT x=0;x<width;++x)if(((uint32_t*)((char*)rect.pBits+y*rect.Pitch))[x]!=oracle(x,y)){printf("REGION mismatch xy=%u,%u got=%08x want=%08x\n",x,y,((uint32_t*)((char*)rect.pBits+y*rect.Pitch))[x],oracle(x,y));throw std::runtime_error("region pixels");}
  read->UnlockRect();read->Release();dev->SetTexture(0,nullptr);dev->SetRenderTarget(0,old);old->Release();target->Release();
  viewport={0,0,512,256,0,1};dev->SetViewport(&viewport);
}
int main(int argc,char** argv) {
  setvbuf(stdout,nullptr,_IONBF,0);
  try {
    auto* api=Direct3DCreate9(D3D_SDK_VERSION); if(!api)throw std::runtime_error("api");
    WNDCLASSA wc{};wc.lpfnWndProc=DefWindowProcA;wc.hInstance=GetModuleHandleA(nullptr);wc.lpszClassName="W101PerformanceProbe";RegisterClassA(&wc);
    HWND window=CreateWindowA(wc.lpszClassName,"Wizard101 performance verification",WS_OVERLAPPEDWINDOW,0,0,640,480,nullptr,nullptr,wc.hInstance,nullptr);
    D3DPRESENT_PARAMETERS pp{};pp.Windowed=TRUE;pp.SwapEffect=D3DSWAPEFFECT_DISCARD;pp.BackBufferWidth=512;pp.BackBufferHeight=256;pp.BackBufferFormat=D3DFMT_A8R8G8B8;pp.hDeviceWindow=window;pp.PresentationInterval=D3DPRESENT_INTERVAL_IMMEDIATE;
    IDirect3DDevice9* dev=nullptr;check(api->CreateDevice(0,D3DDEVTYPE_HAL,window,D3DCREATE_HARDWARE_VERTEXPROCESSING,&pp,&dev),"device");
    const char* mode=argc>1?argv[1]:"pixels";
    if(!strcmp(mode,"cache-pressure")) {
      auto encoded=file("asset.jpg");if(encoded.empty())throw std::runtime_error("asset fixture");
      auto load=[&](unsigned key) {
        IDirect3DTexture9* texture=nullptr;
        check(D3DXCreateTextureFromFileInMemoryEx(dev,encoded.data(),encoded.size(),2048,2048,1,0,D3DFMT_A8R8G8B8,D3DPOOL_MANAGED,D3DX_FILTER_LINEAR,D3DX_FILTER_LINEAR,0xff000000u|key,nullptr,nullptr,&texture),"pressure native load");
        D3DSURFACE_DESC desc{};check(texture->GetLevelDesc(0,&desc),"pressure size");
        if(desc.Width!=2048 || desc.Height!=2048 || desc.Format!=D3DFMT_A8R8G8B8 || texture->GetLevelCount()!=1)throw std::runtime_error("pressure output size");
        texture->Release();
      };
      for(unsigned key=1;key<=16;++key)load(key);
      load(16);load(1); // Last entry hits; the first exceeds the 128 MiB budget and was evicted.
      check(dev->EvictManagedResources(),"clear managed cache");load(16);load(16);
      printf("PASS native cache pressure: 256 MiB requested, LRU eviction, managed-resource clear\n");
    } else if(!strcmp(mode,"cache")) {
      char loaded[MAX_PATH]{};GetModuleFileNameA(GetModuleHandleA("d3dx9_43.dll"),loaded,sizeof(loaded));printf("D3DX module=%s\n",loaded);
      auto encoded=file("asset.jpg");if(encoded.empty())throw std::runtime_error("asset fixture");
      IDirect3DTexture9 *first=nullptr,*second=nullptr;SetLastError(0x1357);
      check(D3DXCreateTextureFromFileInMemory(dev,encoded.data(),encoded.size(),&first),"native first load");DWORD originalError=GetLastError();
      check(D3DXCreateTextureFromFileInMemory(dev,encoded.data(),encoded.size(),&second),"native revisit");if(first==second || GetLastError()!=originalError)throw std::runtime_error("mutable texture/error contract");
      for(UINT mip=0;mip<first->GetLevelCount();++mip) {
        D3DSURFACE_DESC d{};first->GetLevelDesc(mip,&d);D3DLOCKED_RECT a{},b{};check(first->LockRect(mip,&a,nullptr,D3DLOCK_READONLY),"first pixels");check(second->LockRect(mip,&b,nullptr,D3DLOCK_READONLY),"revisit pixels");
        for(UINT y=0;y<d.Height;++y)if(memcmp((char*)a.pBits+y*a.Pitch,(char*)b.pBits+y*b.Pitch,d.Width*4))throw std::runtime_error("cached mip mismatch");
        first->UnlockRect(mip);second->UnlockRect(mip);
      }
      first->Release();second->Release();
      D3DXIMAGE_INFO info1{},info2{};
      for(int pass=0;pass<2;++pass) {
        IDirect3DTexture9* t=nullptr;auto* info=pass?&info2:&info1;
        check(D3DXCreateTextureFromFileInMemoryEx(dev,encoded.data(),encoded.size(),256,128,1,0,D3DFMT_A8R8G8B8,D3DPOOL_MANAGED,D3DX_FILTER_LINEAR,D3DX_FILTER_LINEAR,0,info,nullptr,&t),"native Ex");t->Release();
      }
      if(memcmp(&info1,&info2,sizeof(info1)))throw std::runtime_error("image info mismatch");
      IDirect3DTexture9* invalid=(IDirect3DTexture9*)uintptr_t(1);
      HRESULT bad=D3DXCreateTextureFromFileInMemory(dev,nullptr,0,&invalid);if(SUCCEEDED(bad))throw std::runtime_error("invalid source accepted");
      auto start=std::chrono::steady_clock::now();
      for(int i=0;i<32;++i) { IDirect3DTexture9* t=nullptr;check(D3DXCreateTextureFromFileInMemory(dev,encoded.data(),encoded.size(),&t),"cached benchmark");t->Release(); }
      printf("BENCH native_asset_32_loads_us=%lld\n",(long long)std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now()-start).count());
      auto changed=file("asset-changed.jpg");IDirect3DTexture9* changedTexture=nullptr;check(D3DXCreateTextureFromFileInMemory(dev,changed.data(),changed.size(),&changedTexture),"changed content");changedTexture->Release();
      check(dev->Reset(&pp),"reset");check(D3DXCreateTextureFromFileInMemory(dev,encoded.data(),encoded.size(),&changedTexture),"post-reset load");changedTexture->Release();
      printf("PASS native asset cache: independent textures, every mip, Ex parameters/info, invalid input, content change, reset\n");
    } else {
      dev->SetRenderState(D3DRS_LIGHTING,FALSE);dev->SetRenderState(D3DRS_ZENABLE,FALSE);dev->SetRenderState(D3DRS_CULLMODE,D3DCULL_NONE);dev->SetRenderState(D3DRS_ALPHABLENDENABLE,FALSE);
      dev->SetTextureStageState(0,D3DTSS_COLOROP,D3DTOP_SELECTARG1);dev->SetTextureStageState(0,D3DTSS_COLORARG1,D3DTA_TEXTURE);dev->SetTextureStageState(0,D3DTSS_ALPHAOP,D3DTOP_SELECTARG1);dev->SetTextureStageState(0,D3DTSS_ALPHAARG1,D3DTA_TEXTURE);dev->SetTextureStageState(1,D3DTSS_COLOROP,D3DTOP_DISABLE);
      dev->SetSamplerState(0,D3DSAMP_MINFILTER,D3DTEXF_POINT);dev->SetSamplerState(0,D3DSAMP_MAGFILTER,D3DTEXF_POINT);dev->SetSamplerState(0,D3DSAMP_MIPFILTER,D3DTEXF_NONE);
      dev->SetFVF(D3DFVF_XYZRHW|D3DFVF_TEX1);
      struct Vertex { float x,y,z,w,u,v; } quad[]={{-.5f,-.5f,0,1,0,0},{511.5f,-.5f,0,1,1,0},{-.5f,255.5f,0,1,0,1},{511.5f,255.5f,0,1,1,1}};
      const D3DFORMAT formats[]={D3DFMT_A4R4G4B4,D3DFMT_X4R4G4B4,D3DFMT_A1R5G5B5,D3DFMT_X1R5G5B5,D3DFMT_R5G6B5};
      for(int f=0;f<5;++f) {
        IDirect3DTexture9 *src=nullptr,*dst=nullptr;check(dev->CreateTexture(512,256,1,0,formats[f],D3DPOOL_SYSTEMMEM,&src,nullptr),"packed source");check(dev->CreateTexture(512,256,1,0,formats[f],D3DPOOL_DEFAULT,&dst,nullptr),"packed destination");
        for(int pass=0;pass<2;++pass) {
          D3DLOCKED_RECT rect{};check(src->LockRect(0,&rect,nullptr,0),"packed lock");for(UINT y=0;y<256;++y)for(UINT x=0;x<512;++x)((uint16_t*)((char*)rect.pBits+y*rect.Pitch))[x]=uint16_t(y*512+x+pass*37);check(src->UnlockRect(0),"packed unlock");
          check(dev->UpdateTexture(src,dst),"packed upload");
          // Rewriting the source before GPU consumption must not change queued data.
          check(src->LockRect(0,&rect,nullptr,0),"rewrite source");memset(rect.pBits,0,rect.Pitch*256);src->UnlockRect(0);
          check(dev->SetTexture(0,dst),"packed bind");check(dev->BeginScene(),"begin");check(dev->DrawPrimitiveUP(D3DPT_TRIANGLESTRIP,2,quad,sizeof(Vertex)),"sample");check(dev->EndScene(),"end");
          IDirect3DSurface9 *rt=nullptr,*read=nullptr;check(dev->GetRenderTarget(0,&rt),"target");check(dev->CreateOffscreenPlainSurface(512,256,D3DFMT_A8R8G8B8,D3DPOOL_SYSTEMMEM,&read,nullptr),"readback");check(dev->GetRenderTargetData(rt,read),"readback copy");check(read->LockRect(&rect,nullptr,D3DLOCK_READONLY),"readback lock");
          for(UINT y=0;y<256;++y)for(UINT x=0;x<512;++x) {auto got=((uint32_t*)((char*)rect.pBits+y*rect.Pitch))[x],want=expected(uint16_t(y*512+x+pass*37),f);if(got!=want){printf("MISMATCH format=%d pass=%d xy=%u,%u got=%08x want=%08x\n",f,pass,x,y,got,want);throw std::runtime_error("packed pixel mismatch");}}
          read->UnlockRect();read->Release();rt->Release();
        }
        if(!strcmp(mode,"bench")) {
          D3DLOCKED_RECT r{};src->LockRect(0,&r,nullptr,0);memset(r.pBits,0xff,r.Pitch*256);src->UnlockRect(0);
          auto start=std::chrono::steady_clock::now();for(int i=0;i<128;++i){check(src->AddDirtyRect(nullptr),"benchmark dirty region");check(dev->UpdateTexture(src,dst),"benchmark upload");}
          printf("BENCH packed_format_%d_128_uploads_us=%lld\n",f,(long long)std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now()-start).count());
        }
        dev->SetTexture(0,nullptr);src->Release();dst->Release();printf("PASS packed format=%d all 65536 values, alpha and rewrite ordering\n",f);
        if(!strcmp(mode,"edges")) {
          check(dev->CreateTexture(521,265,1,0,formats[f],D3DPOOL_SYSTEMMEM,&src,nullptr),"odd source");check(dev->CreateTexture(521,265,1,0,formats[f],D3DPOOL_DEFAULT,&dst,nullptr),"odd destination");
          D3DLOCKED_RECT rect{};src->LockRect(0,&rect,nullptr,0);for(UINT y=0;y<265;++y)for(UINT x=0;x<521;++x)((uint16_t*)((char*)rect.pBits+y*rect.Pitch))[x]=uint16_t(y*521+x);src->UnlockRect(0);check(dev->UpdateTexture(src,dst),"odd upload");
          src->LockRect(0,&rect,nullptr,0);for(UINT y=0;y<265;++y)for(UINT x=0;x<521;++x)((uint16_t*)((char*)rect.pBits+y*rect.Pitch))[x]=uint16_t(y*521+x+997);src->UnlockRect(0);
          IDirect3DSurface9 *a=nullptr,*b=nullptr;src->GetSurfaceLevel(0,&a);dst->GetSurfaceLevel(0,&b);RECT region{3,2,516,259};POINT point{4,3};check(dev->UpdateSurface(a,&region,b,&point),"partial packed upload");a->Release();b->Release();
          verifyRegion(dev,dst,521,265,[f](UINT x,UINT y){bool changed=x>=4&&x<517&&y>=3&&y<260;return expected(uint16_t(changed?(y-1)*521+(x-1)+997:y*521+x),f);});src->Release();dst->Release();
          check(dev->CreateTexture(512,256,2,0,formats[f],D3DPOOL_SYSTEMMEM,&src,nullptr),"mipped source");check(dev->CreateTexture(512,256,2,0,formats[f],D3DPOOL_DEFAULT,&dst,nullptr),"mipped destination");
          for(UINT mip=0;mip<2;++mip){src->LockRect(mip,&rect,nullptr,0);for(UINT y=0;y<(256u>>mip);++y)for(UINT x=0;x<(512u>>mip);++x)((uint16_t*)((char*)rect.pBits+y*rect.Pitch))[x]=uint16_t(y*(512u>>mip)+x+mip*83);src->UnlockRect(mip);}
          check(dev->UpdateTexture(src,dst),"mipped upload");dev->SetSamplerState(0,D3DSAMP_MIPFILTER,D3DTEXF_POINT);dev->SetSamplerState(0,D3DSAMP_MAXMIPLEVEL,1);verifyRegion(dev,dst,256,128,[f](UINT x,UINT y){return expected(uint16_t(y*256+x+83),f);});dev->SetSamplerState(0,D3DSAMP_MAXMIPLEVEL,0);dev->SetSamplerState(0,D3DSAMP_MIPFILTER,D3DTEXF_NONE);src->Release();dst->Release();
          printf("PASS packed edges format=%d: padded odd rows, partial offsets, mip fallback\n",f);
        }
      }
      check(dev->Reset(&pp),"packed reset");
    }
    dev->Release();api->Release();DestroyWindow(window);printf("PASS all workload performance checks\n");return 0;
  } catch(const std::exception& e) {printf("ERROR %s\n",e.what());return 1;}
}
