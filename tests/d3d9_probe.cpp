#include <windows.h>
#include <d3d9.h>
#include <d3dcompiler.h>
#include <cstdio>
#include <cstring>
#include <stdexcept>
#include <vector>
#include <fstream>
#include <chrono>
#include <algorithm>

static void check(HRESULT hr, const char* op) {
  if (FAILED(hr)) { std::printf("FAIL %s HRESULT=0x%08lx\n", op, (unsigned long)hr); throw std::runtime_error(op); }
}
int main(int argc, char** argv) {
  setvbuf(stdout, nullptr, _IONBF, 0);
  try {
    auto has = [&](const char* flag) { for(int i=1;i<argc;i++) if(!strcmp(argv[i],flag)) return true; return false; };
    HMODULE dll = LoadLibraryA("d3d9.dll");
    char path[MAX_PATH] = {}; GetModuleFileNameA(dll, path, MAX_PATH);
    std::printf("DLL %s\n", path);
    auto create = reinterpret_cast<IDirect3D9*(WINAPI*)(UINT)>(GetProcAddress(dll, "Direct3DCreate9"));
    if (!create) throw std::runtime_error("Direct3DCreate9 missing");
    IDirect3D9* api = create(D3D_SDK_VERSION);
    if (!api) throw std::runtime_error("Direct3DCreate9 failed");
    D3DADAPTER_IDENTIFIER9 id = {}; check(api->GetAdapterIdentifier(0, 0, &id), "adapter");
    std::printf("GPU %s\n", id.Description);
    WNDCLASSA wc = {}; wc.lpfnWndProc = DefWindowProcA; wc.hInstance = GetModuleHandleA(nullptr); wc.lpszClassName = "D9VKProbe";
    RegisterClassA(&wc);
    HWND win = CreateWindowA(wc.lpszClassName, "Wizard101 D3D9 compatibility test", WS_OVERLAPPEDWINDOW|WS_VISIBLE, 100, 100, 640, 480, nullptr, nullptr, wc.hInstance, nullptr);
    D3DPRESENT_PARAMETERS pp = {}; pp.Windowed = TRUE; pp.SwapEffect = D3DSWAPEFFECT_DISCARD;
    pp.hDeviceWindow = win; pp.BackBufferWidth = 640; pp.BackBufferHeight = 480; pp.BackBufferFormat = D3DFMT_A8R8G8B8; pp.PresentationInterval = has("--vsync") ? D3DPRESENT_INTERVAL_ONE : D3DPRESENT_INTERVAL_IMMEDIATE;
    IDirect3DDevice9* dev = nullptr;
    check(api->CreateDevice(0, D3DDEVTYPE_HAL, win, D3DCREATE_HARDWARE_VERTEXPROCESSING, &pp, &dev), "CreateDevice");
    std::printf("PASS CreateDevice VRAM=%u\n", dev->GetAvailableTextureMem());
    std::vector<IDirect3DTexture9*> formatTextures;
    for (D3DFORMAT fmt : { D3DFMT_A8R8G8B8, D3DFMT_A4R4G4B4, D3DFMT_A1R5G5B5, D3DFMT_R5G6B5, D3DFMT_DXT1, D3DFMT_DXT5 }) {
      IDirect3DTexture9* tex = nullptr;
      check(dev->CreateTexture(64,64,1,0,fmt,D3DPOOL_MANAGED,&tex,nullptr), "CreateTexture");
      D3DLOCKED_RECT lock = {}; check(tex->LockRect(0,&lock,nullptr,0), "LockTexture");
      std::memset(lock.pBits, 0xff, lock.Pitch * (fmt == D3DFMT_DXT1 || fmt == D3DFMT_DXT5 ? 16 : 64));
      if (fmt == D3DFMT_DXT1 || fmt == D3DFMT_DXT5) {
        const int blockBytes=fmt==D3DFMT_DXT1?8:16;
        for(int y=0;y<16;y++) for(int x=0;x<16;x++) {
          auto block=(unsigned char*)lock.pBits+y*lock.Pitch+x*blockBytes;
          memset(block,0,blockBytes);
          int colorOffset=fmt==D3DFMT_DXT1?0:8;
          if(colorOffset) { block[0]=255; block[1]=254; }
          block[colorOffset]=255; block[colorOffset+1]=255;
          block[colorOffset+2]=254; block[colorOffset+3]=255;
        }
      }
      check(tex->UnlockRect(0), "UnlockTexture"); formatTextures.push_back(tex);
      std::printf("PASS texture format=%u\n", (unsigned)fmt);
    }
    const char* vsCode = "float4 main(float4 p:POSITION):POSITION { return p; }";
    const char* psCode = "float4 main():COLOR { return float4(0,1,0,1); }";
    HMODULE compiler = LoadLibraryA("d3dcompiler_47.dll");
    auto compile = reinterpret_cast<pD3DCompile>(GetProcAddress(compiler, "D3DCompile"));
    if (!compile) throw std::runtime_error("D3DCompile missing");
    ID3DBlob *vsBlob = nullptr, *psBlob = nullptr, *errors = nullptr;
    check(compile(vsCode,strlen(vsCode),nullptr,nullptr,nullptr,"main","vs_3_0",0,0,&vsBlob,&errors), "compile VS");
    if(errors) { errors->Release(); errors=nullptr; }
    check(compile(psCode,strlen(psCode),nullptr,nullptr,nullptr,"main","ps_3_0",0,0,&psBlob,&errors), "compile PS");
    if(errors) errors->Release();
    IDirect3DVertexShader9* vs = nullptr; IDirect3DPixelShader9* ps = nullptr;
    check(dev->CreateVertexShader((DWORD*)vsBlob->GetBufferPointer(),&vs), "CreateVertexShader");
    check(dev->CreatePixelShader((DWORD*)psBlob->GetBufferPointer(),&ps), "CreatePixelShader");
    D3DVERTEXELEMENT9 elements[] = {{0,0,D3DDECLTYPE_FLOAT4,D3DDECLMETHOD_DEFAULT,D3DDECLUSAGE_POSITION,0},D3DDECL_END()};
    IDirect3DVertexDeclaration9* decl = nullptr; check(dev->CreateVertexDeclaration(elements,&decl), "declaration");
    dev->SetVertexDeclaration(decl); dev->SetVertexShader(vs); dev->SetPixelShader(ps);
    dev->SetRenderState(D3DRS_CULLMODE,D3DCULL_NONE); dev->SetRenderState(D3DRS_ZENABLE,FALSE);
    float vertices[] = {-1,-1,0,1, 0,1,0,1, 1,-1,0,1};
    auto draw = [&] {
      check(dev->Clear(0,nullptr,D3DCLEAR_TARGET,0xff000000,1,0), "Clear");
      check(dev->BeginScene(), "BeginScene"); check(dev->DrawPrimitiveUP(D3DPT_TRIANGLELIST,1,vertices,16), "Draw"); check(dev->EndScene(), "EndScene");
    };
    for (int repeat=0; repeat<64; ++repeat) draw();
    IDirect3DSurface9 *rt=nullptr,*read=nullptr;
    check(dev->GetRenderTarget(0,&rt), "GetRenderTarget");
    check(dev->CreateOffscreenPlainSurface(640,480,D3DFMT_A8R8G8B8,D3DPOOL_SYSTEMMEM,&read,nullptr), "ReadbackSurface");
    check(dev->GetRenderTargetData(rt,read), "GetRenderTargetData");
    D3DLOCKED_RECT pixels={}; check(read->LockRect(&pixels,nullptr,D3DLOCK_READONLY), "LockReadback");
    DWORD center = *(DWORD*)((char*)pixels.pBits + 240*pixels.Pitch + 320*4);
    DWORD corner = *(DWORD*)((char*)pixels.pBits + 10*pixels.Pitch + 10*4);
    read->UnlockRect(); read->Release(); rt->Release();
    std::printf("PIXELS center=0x%08lx corner=0x%08lx\n",(unsigned long)center,(unsigned long)corner);
    if(center!=0xff00ff00 || corner!=0xff000000) throw std::runtime_error("shader render/readback mismatch");
    check(dev->Present(nullptr,nullptr,nullptr,nullptr), "Present");
    std::printf("PASS shader rendering and readback\n");
    const char* sampleCode="sampler2D tex0 : register(s0); float4 main(float2 uv:TEXCOORD0):COLOR { return tex2D(tex0,uv); }";
    ID3DBlob* sampleBlob=nullptr; errors=nullptr;
    check(compile(sampleCode,strlen(sampleCode),nullptr,nullptr,nullptr,"main","ps_3_0",0,0,&sampleBlob,&errors),"compile sampling shader");
    if(errors) errors->Release();
    IDirect3DPixelShader9* sampleShader=nullptr;
    check(dev->CreatePixelShader((DWORD*)sampleBlob->GetBufferPointer(),&sampleShader),"sampling shader");
    dev->SetPixelShader(sampleShader);
    for(auto texture:formatTextures) {
      D3DSURFACE_DESC desc={}; texture->GetLevelDesc(0,&desc);
      check(dev->SetTexture(0,texture),"bind format texture"); draw();
      IDirect3DSurface9 *target=nullptr,*sync=nullptr;
      check(dev->GetRenderTarget(0,&target),"format target");
      check(dev->CreateOffscreenPlainSurface(640,480,D3DFMT_A8R8G8B8,D3DPOOL_SYSTEMMEM,&sync,nullptr),"format readback surface");
      check(dev->GetRenderTargetData(target,sync),"format readback");
      D3DLOCKED_RECT l={}; check(sync->LockRect(&l,nullptr,D3DLOCK_READONLY),"format readback lock");
      DWORD pixel=*(DWORD*)((char*)l.pBits+240*l.Pitch+320*4);
      sync->UnlockRect(); target->Release(); sync->Release();
      std::printf("TEXTURE PIXEL format=%u center=0x%08lx\n",(unsigned)desc.Format,(unsigned long)pixel);
      if(pixel!=0xffffffff) throw std::runtime_error("texture format sample/readback mismatch");
      check(dev->Present(nullptr,nullptr,nullptr,nullptr),"format Present");
    }
    if (has("--uploads")) {
      std::vector<IDirect3DTexture9*> uploads;
      // 96 MiB exceeds the unchanged 64-bit staging threshold. Queue all
      // uploads/draws before readback, then rewrite and verify every texture.
      for(int i=0;i<96;i++) {
        IDirect3DTexture9* t=nullptr;
        check(dev->CreateTexture(512,512,1,0,D3DFMT_A8R8G8B8,D3DPOOL_MANAGED,&t,nullptr),"stress texture");
        uploads.push_back(t);
      }
      for(int pass=0;pass<2;pass++) {
        auto color = [&](int i) { return DWORD(0xff000000u | ((i+1+pass*96)*0x010101u)); };
        for(int i=0;i<96;i++) {
          D3DLOCKED_RECT l={}; check(uploads[i]->LockRect(0,&l,nullptr,0),"stress lock");
          for(int y=0;y<512;y++) for(int x=0;x<512;x++)
            *(DWORD*)((char*)l.pBits+y*l.Pitch+x*4)=color(i);
          check(uploads[i]->UnlockRect(0),"stress unlock");
          check(dev->SetTexture(0,uploads[i]),"stress bind"); draw();
        }
        IDirect3DSurface9 *target=nullptr,*sync=nullptr;
        check(dev->GetRenderTarget(0,&target),"stress target");
        check(dev->CreateOffscreenPlainSurface(640,480,D3DFMT_A8R8G8B8,D3DPOOL_SYSTEMMEM,&sync,nullptr),"stress read surface");
        for(int i=0;i<96;i++) {
          check(dev->SetTexture(0,uploads[i]),"stress sample"); draw();
          check(dev->GetRenderTargetData(target,sync),"stress readback");
          D3DLOCKED_RECT l={}; check(sync->LockRect(&l,nullptr,D3DLOCK_READONLY),"stress read lock");
          DWORD pixel=*(DWORD*)((char*)l.pBits+240*l.Pitch+320*4);
          sync->UnlockRect();
          if(pixel!=color(i)) throw std::runtime_error("stress sampling/readback mismatch");
        }
        target->Release(); sync->Release();
      }
      dev->SetTexture(0,nullptr); for(auto t:uploads) t->Release();
      std::printf("PASS upload stress: 96 textures 512x512, two upload/rewrite passes, 192 exact sampling/readbacks\n");
    }
    dev->SetTexture(0,nullptr); dev->SetPixelShader(ps);
    for(auto texture:formatTextures) texture->Release();
    sampleShader->Release(); sampleBlob->Release();
    std::printf("PASS six texture formats sampled and read back\n");
    if (has("--sustained")) {
      using Clock=std::chrono::steady_clock;
      std::vector<double> intervals, recovery;
      auto previous=Clock::now(); double slow=0;
      for(int i=0;i<180;i++) {
        MSG msg; while(PeekMessageA(&msg,nullptr,0,0,PM_REMOVE)) { TranslateMessage(&msg); DispatchMessageA(&msg); }
        if(i==90) Sleep(120);
        draw(); check(dev->Present(nullptr,nullptr,nullptr,nullptr),"sustained Present");
        auto now=Clock::now(); double ms=std::chrono::duration<double,std::milli>(now-previous).count(); previous=now;
        if(i==90) slow=ms;
        else if(i>10) intervals.push_back(ms);
        if(i>=96 && i<126) recovery.push_back(ms);
      }
      std::sort(intervals.begin(),intervals.end()); std::sort(recovery.begin(),recovery.end());
      std::printf("PACING vsync=%d frames=180 median_ms=%.3f recovery_median_ms=%.3f slow_ms=%.3f\n",
        has("--vsync"),intervals[intervals.size()/2],recovery[recovery.size()/2],slow);
      if(slow<100) throw std::runtime_error("slow frame injection failed");
      std::printf("PASS sustained presentation and deliberate slow frame\n");
    }
    if(has("--fullscreen")) {
      D3DDISPLAYMODE mode={}; check(api->GetAdapterDisplayMode(0,&mode),"display mode");
      pp.Windowed=FALSE; pp.BackBufferWidth=mode.Width; pp.BackBufferHeight=mode.Height; pp.BackBufferFormat=mode.Format;
      check(dev->Reset(&pp), "Reset fullscreen"); check(dev->Present(nullptr,nullptr,nullptr,nullptr),"Present fullscreen");
      pp.Windowed=TRUE; pp.BackBufferWidth=640; pp.BackBufferHeight=480; pp.BackBufferFormat=D3DFMT_A8R8G8B8;
      check(dev->Reset(&pp), "Reset windowed");
      std::printf("PASS fullscreen/windowed transition\n");
    }
    decl->Release(); ps->Release(); vs->Release(); psBlob->Release(); vsBlob->Release();
    dev->Release(); api->Release(); DestroyWindow(win);
    std::printf("PASS all checks\n"); return 0;
  } catch(const std::exception& e) { std::printf("FAIL %s\n",e.what()); return 1; }
}
