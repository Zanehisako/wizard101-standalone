#include <windows.h>
#include <d3d9.h>
#include <d3dx9.h>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <vector>
#include <stdexcept>
static void check(HRESULT hr,const char* op) { if(FAILED(hr)) { printf("FAIL %s %08lx\n",op,(unsigned long)hr); throw std::runtime_error(op); } }
static void require(bool yes,const char* op) { if(!yes) throw std::runtime_error(op); }
static std::vector<unsigned char> file(const char* name) { std::ifstream f(name,std::ios::binary); return {std::istreambuf_iterator<char>(f),{}}; }
static std::vector<unsigned char> pixels(IDirect3DTexture9* t,UINT mip) {
  D3DSURFACE_DESC d{};check(t->GetLevelDesc(mip,&d),"description");
  unsigned rows=d.Height,bytes=d.Width*4;
  if(d.Format==D3DFMT_R5G6B5) bytes=d.Width*2;
  if(d.Format==D3DFMT_DXT1) {rows=(d.Height+3)/4;bytes=((d.Width+3)/4)*8;}
  if(d.Format==D3DFMT_DXT3 || d.Format==D3DFMT_DXT5) {rows=(d.Height+3)/4;bytes=((d.Width+3)/4)*16;}
  D3DLOCKED_RECT r{};check(t->LockRect(mip,&r,nullptr,D3DLOCK_READONLY),"pixels");
  std::vector<unsigned char> result(rows*bytes);
  for(unsigned y=0;y<rows;++y) memcpy(result.data()+y*bytes,(char*)r.pBits+y*r.Pitch,bytes);
  check(t->UnlockRect(mip),"unlock");return result;
}
static std::vector<unsigned char> sample(IDirect3DDevice9* dev,IDirect3DTexture9* t,UINT mip) {
  D3DSURFACE_DESC d{}; t->GetLevelDesc(mip,&d);
  IDirect3DSurface9 *old=nullptr,*rt=nullptr,*read=nullptr;
  check(dev->GetRenderTarget(0,&old),"old target");
  check(dev->CreateRenderTarget(d.Width,d.Height,D3DFMT_A8R8G8B8,D3DMULTISAMPLE_NONE,0,FALSE,&rt,nullptr),"target");
  check(dev->SetRenderTarget(0,rt),"bind target");
  D3DVIEWPORT9 vp{0,0,d.Width,d.Height,0,1};dev->SetViewport(&vp);
  dev->SetRenderState(D3DRS_LIGHTING,FALSE);dev->SetRenderState(D3DRS_ZENABLE,FALSE);dev->SetRenderState(D3DRS_CULLMODE,D3DCULL_NONE);dev->SetRenderState(D3DRS_ALPHABLENDENABLE,FALSE);
  dev->SetTextureStageState(0,D3DTSS_COLOROP,D3DTOP_SELECTARG1);dev->SetTextureStageState(0,D3DTSS_COLORARG1,D3DTA_TEXTURE);
  dev->SetTextureStageState(0,D3DTSS_ALPHAOP,D3DTOP_SELECTARG1);dev->SetTextureStageState(0,D3DTSS_ALPHAARG1,D3DTA_TEXTURE);dev->SetTextureStageState(1,D3DTSS_COLOROP,D3DTOP_DISABLE);
  dev->SetSamplerState(0,D3DSAMP_MINFILTER,D3DTEXF_POINT);dev->SetSamplerState(0,D3DSAMP_MAGFILTER,D3DTEXF_POINT);dev->SetSamplerState(0,D3DSAMP_MIPFILTER,D3DTEXF_POINT);dev->SetSamplerState(0,D3DSAMP_MAXMIPLEVEL,mip);
  dev->SetFVF(D3DFVF_XYZRHW|D3DFVF_TEX1);
  struct V {float x,y,z,w,u,v;} q[]={{-.5f,-.5f,0,1,0,0},{d.Width-.5f,-.5f,0,1,1,0},{-.5f,d.Height-.5f,0,1,0,1},{d.Width-.5f,d.Height-.5f,0,1,1,1}};
  check(dev->SetTexture(0,t),"texture");check(dev->BeginScene(),"begin");check(dev->DrawPrimitiveUP(D3DPT_TRIANGLESTRIP,2,q,sizeof(V)),"draw");check(dev->EndScene(),"end");
  check(dev->CreateOffscreenPlainSurface(d.Width,d.Height,D3DFMT_A8R8G8B8,D3DPOOL_SYSTEMMEM,&read,nullptr),"readback");check(dev->GetRenderTargetData(rt,read),"GPU copy");
  D3DLOCKED_RECT r{};check(read->LockRect(&r,nullptr,D3DLOCK_READONLY),"GPU pixels");std::vector<unsigned char> result(d.Width*d.Height*4);
  for(UINT y=0;y<d.Height;++y)memcpy(result.data()+y*d.Width*4,(char*)r.pBits+y*r.Pitch,d.Width*4);
  read->UnlockRect();read->Release();dev->SetTexture(0,nullptr);dev->SetRenderTarget(0,old);old->Release();rt->Release();return result;
}
int main(int argc,char** argv) {
  setvbuf(stdout,nullptr,_IONBF,0);
  try {
    auto* api=Direct3DCreate9(D3D_SDK_VERSION);require(api,"api");
    WNDCLASSA wc{};wc.lpfnWndProc=DefWindowProcA;wc.hInstance=GetModuleHandleA(nullptr);wc.lpszClassName="W101AssetsProbe";RegisterClassA(&wc);
    HWND window=CreateWindowA(wc.lpszClassName,"Asset preparation verification",WS_OVERLAPPEDWINDOW,0,0,640,480,nullptr,nullptr,wc.hInstance,nullptr);
    D3DPRESENT_PARAMETERS pp{};pp.Windowed=TRUE;pp.SwapEffect=D3DSWAPEFFECT_DISCARD;pp.BackBufferWidth=512;pp.BackBufferHeight=256;pp.BackBufferFormat=D3DFMT_A8R8G8B8;pp.hDeviceWindow=window;pp.PresentationInterval=D3DPRESENT_INTERVAL_IMMEDIATE;
    IDirect3DDevice9* dev=nullptr;check(api->CreateDevice(0,D3DDEVTYPE_HAL,window,D3DCREATE_HARDWARE_VERTEXPROCESSING,&pp,&dev),"device");
    const char* mode=argc>1?argv[1]:"verify";
    auto memory=(decltype(&D3DXCreateTextureFromFileInMemory))GetProcAddress(GetModuleHandleA("d3dx9_43.dll"),"D3DXCreateTextureFromFileInMemory");
    auto memoryEx=(decltype(&D3DXCreateTextureFromFileInMemoryEx))GetProcAddress(GetModuleHandleA("d3dx9_43.dll"),"D3DXCreateTextureFromFileInMemoryEx");
    auto fileEx=(decltype(&D3DXCreateTextureFromFileExA))GetProcAddress(GetModuleHandleA("d3dx9_43.dll"),"D3DXCreateTextureFromFileExA");
    if(!strcmp(mode,"idle")) { require(dev->Release()==0,"unconsumed prepared textures kept device alive");api->Release();DestroyWindow(window);puts("PASS unconsumed teardown");return 0; }
    // Native D3DX's first PNG load initializes codecs and changes LastError once.
    // Such successes are never admitted; compare the stable success contract here.
    auto warmBytes=file("asset.jpg");IDirect3DTexture9* warm=nullptr;
    // The first memory request must still run native codec initialization even
    // when startup has prepared its pixels. Verify the resulting error sequence.
    SetLastError(0x1357);check(D3DXCreateTextureFromFileInMemory(dev,warmBytes.data(),warmBytes.size(),&warm),"first native codec initialization");
    require(GetLastError()==0x7e,"first codec error behavior changed");warm->Release();
    if(!strcmp(mode,"reset-first")) check(dev->Reset(&pp),"reset unconsumed prepared textures");
    for(int kind=0;kind<5;++kind) {
      const char* name=kind==3?"packed.dds":kind==4?"compressed.dds":"asset.jpg";
      auto encoded=file(name);require(!encoded.empty(),"fixture");
      auto load=[&](bool original,IDirect3DTexture9** output,D3DXIMAGE_INFO* info) {
        if(kind==0 || kind>=3) return (original?memory:D3DXCreateTextureFromFileInMemory)(dev,encoded.data(),encoded.size(),output);
        if(kind==1) return (original?memoryEx:D3DXCreateTextureFromFileInMemoryEx)(dev,encoded.data(),encoded.size(),256,128,4,0,D3DFMT_A8R8G8B8,D3DPOOL_MANAGED,D3DX_FILTER_LINEAR,D3DX_FILTER_LINEAR,0,info,nullptr,output);
        return (original?fileEx:D3DXCreateTextureFromFileExA)(dev,name,128,64,3,0,D3DFMT_A8R8G8B8,D3DPOOL_MANAGED,D3DX_FILTER_LINEAR,D3DX_FILTER_LINEAR,0,info,nullptr,output);
      };
      IDirect3DTexture9 *a=nullptr,*b=nullptr,*oracle=nullptr;D3DXIMAGE_INFO info{},originalInfo{};
      DWORD incoming=kind==2?0:0x1357;
      SetLastError(incoming);HRESULT hr=load(false,&a,&info);DWORD error=GetLastError();check(hr,"hooked loader");
      SetLastError(incoming);HRESULT referenceHR=load(true,&oracle,&originalInfo);DWORD referenceError=GetLastError();check(referenceHR,"original loader");
      printf("LOADER kind=%d error=%lx native_error=%lx\n",kind,(unsigned long)error,(unsigned long)referenceError);
      require(hr==referenceHR && error==referenceError,"HRESULT or LastError mismatch");require(!memcmp(&info,&originalInfo,sizeof(info)),"image info mismatch");
      require(a->GetLevelCount()==oracle->GetLevelCount(),"mip count");
      for(UINT mip=0;mip<a->GetLevelCount();++mip) {
        require(pixels(a,mip)==pixels(oracle,mip),"CPU mip pixels");
        require(sample(dev,a,mip)==sample(dev,oracle,mip),"GPU mip pixels");
      }
      D3DLOCKED_RECT changed{};check(a->LockRect(0,&changed,nullptr,0),"mutate texture");((unsigned char*)changed.pBits)[0]^=0xff;check(a->UnlockRect(0),"mutate unlock");
      SetLastError(incoming);check(load(false,&b,&info),"second independent loader");require(a!=b,"shared mutable texture");require(pixels(b,0)==pixels(oracle,0),"independence");
      if(kind==2) { IDirect3DTexture9* fallback=nullptr;SetLastError(0x1357);check(load(false,&fallback,&info),"filename error fallback");require(GetLastError()==0,"filename success error");fallback->Release(); }
      a->Release();b->Release();oracle->Release();printf("PASS loader=%d exact CPU/GPU pixels, every mip, independence, errors\n",kind);
    }
    // Invalid/missing sources, invalid parameters, and palette outputs retain native behavior.
    for(int kind=0;kind<4;++kind) {
      IDirect3DTexture9 *a=(IDirect3DTexture9*)uintptr_t(1),*b=a;D3DXIMAGE_INFO ia{},ib{};PALETTEENTRY pa[256]{},pb[256]{};
      auto input=file("asset.jpg");
      auto call=[&](bool original,IDirect3DTexture9** out,D3DXIMAGE_INFO* info,PALETTEENTRY* palette) {
        if(kind==0)return (original?memory:D3DXCreateTextureFromFileInMemory)(dev,nullptr,0,out);
        if(kind==1)return (original?fileEx:D3DXCreateTextureFromFileExA)(dev,"missing.jpg",0,0,0,0,D3DFMT_UNKNOWN,D3DPOOL_MANAGED,D3DX_DEFAULT,D3DX_DEFAULT,0,info,nullptr,out);
        return (original?memoryEx:D3DXCreateTextureFromFileInMemoryEx)(dev,input.data(),input.size(),kind==2?0:256,128,1,0,D3DFMT_A8R8G8B8,D3DPOOL_MANAGED,D3DX_FILTER_LINEAR,D3DX_FILTER_LINEAR,0,info,kind==3?palette:nullptr,out);
      };
      SetLastError(0x9753);HRESULT ha=call(false,&a,&ia,pa);DWORD ea=GetLastError();SetLastError(0x9753);HRESULT hb=call(true,&b,&ib,pb);DWORD eb=GetLastError();
      require(ha==hb && ea==eb && !memcmp(&ia,&ib,sizeof(ia)) && !memcmp(pa,pb,sizeof(pa)),"fallback error/output contract");
      if(SUCCEEDED(ha)) { a->Release();b->Release(); } else require(a==b,"failure output pointer");
    }
    check(dev->Reset(&pp),"reset");
    // Replay after reset uses a fresh object and original pixels.
    auto encoded=file("asset.jpg");IDirect3DTexture9* t=nullptr;check(D3DXCreateTextureFromFileInMemory(dev,encoded.data(),encoded.size(),&t),"post-reset");t->Release();
    D3DDISPLAYMODE display{};check(api->GetAdapterDisplayMode(0,&display),"display");
    pp.Windowed=FALSE;pp.BackBufferWidth=display.Width;pp.BackBufferHeight=display.Height;pp.BackBufferFormat=display.Format;pp.FullScreen_RefreshRateInHz=display.RefreshRate;
    check(dev->Reset(&pp),"fullscreen");pp.Windowed=TRUE;pp.FullScreen_RefreshRateInHz=0;pp.BackBufferWidth=512;pp.BackBufferHeight=256;pp.BackBufferFormat=D3DFMT_A8R8G8B8;check(dev->Reset(&pp),"windowed");
    require(dev->Release()==0,"device lifetime cycle");api->Release();DestroyWindow(window);
    puts("PASS fallback, reset, fullscreen, orderly teardown");return 0;
  } catch(const std::exception& e) {printf("ERROR %s\n",e.what());return 1;}
}
