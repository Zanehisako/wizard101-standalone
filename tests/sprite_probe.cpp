// Synthetic HUD workload: an atlas, alpha blend, and frequently discarded VBs.
#include <windows.h>
#include <d3d9.h>
#include <cstdio>
#include <cstring>
#include <stdexcept>
#include <vector>
static void check(HRESULT value) { if (FAILED(value)) throw std::runtime_error("D3D9 operation"); }
struct Vertex { float x,y,z,w; DWORD color; float u,v; };
int main() {
  try {
    setvbuf(stdout,nullptr,_IONBF,0);
    HMODULE module=LoadLibraryA("d3d9.dll");
    auto create=(IDirect3D9*(WINAPI*)(UINT))GetProcAddress(module,"Direct3DCreate9");
    if(!create) throw std::runtime_error("native renderer missing");
    auto api=create(D3D_SDK_VERSION);
    WNDCLASSA wc={}; wc.lpfnWndProc=DefWindowProcA; wc.hInstance=GetModuleHandleA(nullptr); wc.lpszClassName="SyntheticHUD";
    RegisterClassA(&wc);
    auto window=CreateWindowA(wc.lpszClassName,"Synthetic HUD probe",WS_OVERLAPPEDWINDOW|WS_VISIBLE,20,20,280,300,nullptr,nullptr,wc.hInstance,nullptr);
    D3DPRESENT_PARAMETERS pp={}; pp.Windowed=TRUE; pp.SwapEffect=D3DSWAPEFFECT_DISCARD; pp.hDeviceWindow=window;
    pp.BackBufferWidth=256; pp.BackBufferHeight=256; pp.BackBufferFormat=D3DFMT_A8R8G8B8; pp.PresentationInterval=D3DPRESENT_INTERVAL_IMMEDIATE;
    IDirect3DDevice9* dev=nullptr; check(api->CreateDevice(0,D3DDEVTYPE_HAL,window,D3DCREATE_HARDWARE_VERTEXPROCESSING,&pp,&dev));
    IDirect3DTexture9* atlas=nullptr; check(dev->CreateTexture(64,64,1,D3DUSAGE_DYNAMIC,D3DFMT_A8R8G8B8,D3DPOOL_DEFAULT,&atlas,nullptr));
    IDirect3DVertexBuffer9* vb=nullptr; check(dev->CreateVertexBuffer(64*6*sizeof(Vertex),D3DUSAGE_DYNAMIC|D3DUSAGE_WRITEONLY,0,D3DPOOL_DEFAULT,&vb,nullptr));
    check(dev->SetFVF(D3DFVF_XYZRHW|D3DFVF_DIFFUSE|D3DFVF_TEX1)); check(dev->SetStreamSource(0,vb,0,sizeof(Vertex))); check(dev->SetTexture(0,atlas));
    check(dev->SetRenderState(D3DRS_ZENABLE,FALSE)); check(dev->SetRenderState(D3DRS_LIGHTING,FALSE)); check(dev->SetRenderState(D3DRS_CULLMODE,D3DCULL_NONE));
    check(dev->SetRenderState(D3DRS_ALPHABLENDENABLE,TRUE)); check(dev->SetRenderState(D3DRS_SRCBLEND,D3DBLEND_SRCALPHA)); check(dev->SetRenderState(D3DRS_DESTBLEND,D3DBLEND_INVSRCALPHA));
    check(dev->SetTextureStageState(0,D3DTSS_COLOROP,D3DTOP_SELECTARG1)); check(dev->SetTextureStageState(0,D3DTSS_COLORARG1,D3DTA_TEXTURE));
    check(dev->SetTextureStageState(0,D3DTSS_ALPHAOP,D3DTOP_SELECTARG1)); check(dev->SetTextureStageState(0,D3DTSS_ALPHAARG1,D3DTA_TEXTURE));
    check(dev->SetSamplerState(0,D3DSAMP_MINFILTER,D3DTEXF_POINT)); check(dev->SetSamplerState(0,D3DSAMP_MAGFILTER,D3DTEXF_POINT));
    IDirect3DSurface9 *target=nullptr,*read=nullptr;
    check(dev->GetRenderTarget(0,&target)); check(dev->CreateOffscreenPlainSurface(256,256,D3DFMT_A8R8G8B8,D3DPOOL_SYSTEMMEM,&read,nullptr));
    for(int frame=0;frame<24;frame++) {
      DWORD colors[64]; for(int i=0;i<64;i++) colors[i]=((i%2?0xffu:0x80u)<<24)|(((i+frame)%3==0?0xffu:0)<<16)|(((i+frame)%3==1?0xffu:0)<<8)|((i+frame)%3==2?0xffu:0);
      D3DLOCKED_RECT lock={}; check(atlas->LockRect(0,&lock,nullptr,D3DLOCK_DISCARD));
      for(int y=0;y<64;y++) for(int x=0;x<64;x++) *(DWORD*)((char*)lock.pBits+y*lock.Pitch+x*4)=colors[(y/8)*8+x/8];
      check(atlas->UnlockRect(0));
      void* buffer=nullptr; check(vb->Lock(0,0,&buffer,D3DLOCK_DISCARD)); auto vertices=(Vertex*)buffer;
      for(int i=0;i<64;i++) {
        float x=float((i%8)*32)-0.5f,y=float((i/8)*32)-0.5f,u=float(i%8)/8,v=float(i/8)/8;
        Vertex q[6]={{x,y,0,1,0xffffffff,u,v},{x+32,y,0,1,0xffffffff,u+.125f,v},{x,y+32,0,1,0xffffffff,u,v+.125f},
                     {x+32,y,0,1,0xffffffff,u+.125f,v},{x+32,y+32,0,1,0xffffffff,u+.125f,v+.125f},{x,y+32,0,1,0xffffffff,u,v+.125f}};
        memcpy(vertices+i*6,q,sizeof(q));
      }
      check(vb->Unlock()); check(dev->Clear(0,nullptr,D3DCLEAR_TARGET,0xff000000,1,0)); check(dev->BeginScene());
      // Separate draw calls exercise command/constant changes just like sprites.
      for(int i=0;i<64;i++) check(dev->DrawPrimitive(D3DPT_TRIANGLELIST,i*6,2));
      check(dev->EndScene()); check(dev->GetRenderTargetData(target,read)); check(read->LockRect(&lock,nullptr,D3DLOCK_READONLY));
      bool valid=true;
      for(int i=0;i<64;i++) {
        DWORD pixel=*(DWORD*)((char*)lock.pBits+((i/8)*32+16)*lock.Pitch+((i%8)*32+16)*4);
        DWORD rgb=colors[i]&0xffffff,expected=i%2?rgb:((rgb>>1)&0x7f7f7f)+(rgb&0x010101);
        if((pixel&0xffffff)!=expected) { std::printf("Mismatch frame=%d sprite=%d pixel=%08lx expectedRGB=%06lx\n",frame,i,(unsigned long)pixel,(unsigned long)expected); valid=false; break; }
      }
      read->UnlockRect(); if(!valid) throw std::runtime_error("HUD atlas/vertex/blend readback");
      check(dev->Present(nullptr,nullptr,nullptr,nullptr));
    }
    read->Release(); target->Release(); vb->Release(); atlas->Release(); dev->Release(); api->Release(); DestroyWindow(window);
    std::puts("PASS synthetic HUD: 1536 atlas, dynamic-vertex and alpha-blend readbacks"); return 0;
  } catch(const std::exception& e) { std::printf("FAIL %s\n",e.what()); return 1; }
}
