#include <windows.h>
#include <d3d9.h>
#include <d3dcompiler.h>
#include <cstdio>
#include <cstring>
#include <vector>
#include <string>
#include <stdexcept>
#include <cstdint>
static void check(HRESULT hr,const char* op) { if(FAILED(hr)) {printf("FAIL %s %08lx\n",op,(unsigned long)hr);throw std::runtime_error(op);} }
struct V { float p[4],c[4],uv[2]; };
int main(int argc,char** argv) {
 setvbuf(stdout,nullptr,_IONBF,0);
 try {
  const bool extended=argc>1 && !strcmp(argv[1],"extended");
  auto dll=LoadLibraryA("d3d9.dll");
  auto create=(IDirect3D9*(WINAPI*)(UINT))GetProcAddress(dll,"Direct3DCreate9");
  IDirect3D9* api=nullptr; IDirect3D9Ex* apiEx=nullptr;
  if(extended) {auto ex=(HRESULT(WINAPI*)(UINT,IDirect3D9Ex**))GetProcAddress(dll,"Direct3DCreate9Ex"); check(ex(D3D_SDK_VERSION,&apiEx),"createEx");api=apiEx;}
  else api=create(D3D_SDK_VERSION);
  if(!api)throw std::runtime_error("api");
  WNDCLASSA wc={};wc.lpfnWndProc=DefWindowProcA;wc.hInstance=GetModuleHandleA(nullptr);wc.lpszClassName="LayoutProbe";RegisterClassA(&wc);
  auto win=CreateWindowA(wc.lpszClassName,"Draw layout verification",WS_OVERLAPPEDWINDOW|WS_VISIBLE,60,60,320,240,nullptr,nullptr,wc.hInstance,nullptr);
  D3DPRESENT_PARAMETERS pp={};pp.Windowed=TRUE;pp.SwapEffect=D3DSWAPEFFECT_DISCARD;pp.BackBufferWidth=128;pp.BackBufferHeight=96;pp.BackBufferFormat=D3DFMT_A8R8G8B8;pp.hDeviceWindow=win;pp.PresentationInterval=D3DPRESENT_INTERVAL_IMMEDIATE;
  IDirect3DDevice9* dev=nullptr;IDirect3DDevice9Ex* devEx=nullptr;
  if(extended) {check(apiEx->CreateDeviceEx(0,D3DDEVTYPE_HAL,win,D3DCREATE_HARDWARE_VERTEXPROCESSING|D3DCREATE_MULTITHREADED,&pp,nullptr,&devEx),"deviceEx");dev=devEx;}
  else check(api->CreateDevice(0,D3DDEVTYPE_HAL,win,D3DCREATE_HARDWARE_VERTEXPROCESSING|D3DCREATE_MULTITHREADED,&pp,&dev),"device");
  HMODULE compiler=LoadLibraryA("d3dcompiler_47.dll");auto compile=(pD3DCompile)GetProcAddress(compiler,"D3DCompile");if(!compile)throw std::runtime_error("compiler");
  auto blob=[&](const char* src,const char* profile) {ID3DBlob *b=nullptr,*e=nullptr;auto hr=compile(src,strlen(src),nullptr,nullptr,nullptr,"main",profile,0,0,&b,&e);if(e){if(FAILED(hr))printf("%s\n",(char*)e->GetBufferPointer());e->Release();}check(hr,"compile");return b;};
  std::vector<IDirect3DVertexShader9*> shaders;
  for(const char* src:{
    "void main(float4 p:POSITION,float4 c:COLOR,float2 uv:TEXCOORD0,out float4 q:POSITION,out float4 o:COLOR){q=p;o=c+float4(uv*0.1,0,0);}",
    "void main(float2 uv:TEXCOORD0,float4 c:COLOR,float4 p:POSITION,out float4 q:POSITION,out float4 o:COLOR){q=p;o=c.bgra+float4(uv*0.1,0,0);}",
    "void main(float4 p:POSITION,float4 c:COLOR,float2 delta:TEXCOORD1,out float4 q:POSITION,out float4 o:COLOR){q=p+float4(delta,0,0);o=c;}"}) {
    auto b=blob(src,"vs_3_0");IDirect3DVertexShader9* s=nullptr;check(dev->CreateVertexShader((DWORD*)b->GetBufferPointer(),&s),"VS");b->Release();shaders.push_back(s);
  }
  auto directCode=blob("void main(float4 p:POSITION,float4 c:COLOR,float2 uv:TEXCOORD0,float2 extra:TEXCOORD1,out float4 q:POSITION,out float4 o:COLOR){q=p+float4(extra*0.05,0,0);o=c+float4(uv*0.1,0,0);}","vs_3_0");
  IDirect3DVertexShader9* directShader=nullptr;check(dev->CreateVertexShader((DWORD*)directCode->GetBufferPointer(),&directShader),"direct VS");directCode->Release();shaders.push_back(directShader);
  auto b=blob("float4 main(float4 c:COLOR):COLOR{return c;}","ps_3_0");IDirect3DPixelShader9* ps=nullptr;check(dev->CreatePixelShader((DWORD*)b->GetBufferPointer(),&ps),"PS");b->Release();
  V vertices[]={{{-.7f,-.6f,0,1},{.2f,.3f,.7f,1},{.2f,.4f}},{{0,.6f,0,1},{.2f,.3f,.7f,1},{.2f,.4f}},{{.7f,-.6f,0,1},{.2f,.3f,.7f,1},{.2f,.4f}}};
  std::vector<IDirect3DVertexDeclaration9*> decls;
  auto declaration=[&](const std::vector<D3DVERTEXELEMENT9>& e) {IDirect3DVertexDeclaration9* d=nullptr;check(dev->CreateVertexDeclaration(e.data(),&d),"declaration");return d;};
  const D3DVERTEXELEMENT9 end=D3DDECL_END();
  decls.push_back(declaration({{0,0,D3DDECLTYPE_FLOAT4,0,D3DDECLUSAGE_POSITION,0},{0,16,D3DDECLTYPE_FLOAT4,0,D3DDECLUSAGE_COLOR,0},{0,32,D3DDECLTYPE_FLOAT2,0,D3DDECLUSAGE_TEXCOORD,0},end}));
  decls.push_back(declaration({{0,32,D3DDECLTYPE_FLOAT2,0,D3DDECLUSAGE_TEXCOORD,0},{0,16,D3DDECLTYPE_FLOAT4,0,D3DDECLUSAGE_COLOR,0},{0,0,D3DDECLTYPE_FLOAT4,0,D3DDECLUSAGE_POSITION,0},end}));
  decls.push_back(declaration({{0,0,D3DDECLTYPE_FLOAT4,0,D3DDECLUSAGE_POSITION,0},end}));
  decls.push_back(declaration({{0,0,D3DDECLTYPE_FLOAT4,0,D3DDECLUSAGE_POSITION,0},{0,16,D3DDECLTYPE_FLOAT4,0,D3DDECLUSAGE_COLOR,0},{1,0,D3DDECLTYPE_FLOAT2,0,D3DDECLUSAGE_TEXCOORD,1},end}));
  // Matching inputs span vector lanes and the scalar tail; duplicate semantic
  // has a different offset so the exact artifact detects choosing the last one.
  std::vector<D3DVERTEXELEMENT9> vectorElements;
  for(unsigned i=0;i<8;++i) vectorElements.push_back({0,32,D3DDECLTYPE_FLOAT2,0,D3DDECLUSAGE_TEXCOORD,BYTE(i+4)});
  vectorElements[1]={0,0,D3DDECLTYPE_FLOAT4,0,D3DDECLUSAGE_POSITION,0};
  vectorElements[5]={0,16,D3DDECLTYPE_FLOAT4,0,D3DDECLUSAGE_COLOR,0};
  vectorElements.push_back({0,32,D3DDECLTYPE_FLOAT2,0,D3DDECLUSAGE_TEXCOORD,0});
  vectorElements.push_back({0,32,D3DDECLTYPE_FLOAT2,0,D3DDECLUSAGE_TEXCOORD,1});
  vectorElements.push_back({0,0,D3DDECLTYPE_FLOAT4,0,D3DDECLUSAGE_COLOR,0});
  vectorElements.push_back(end);decls.push_back(declaration(vectorElements));
  IDirect3DVertexBuffer9 *vb=nullptr,*inst=nullptr,*large=nullptr; IDirect3DIndexBuffer9* ib=nullptr;
  const auto pool=extended?D3DPOOL_DEFAULT:D3DPOOL_MANAGED;
  auto buffer=[&](UINT size,const void* bytes) {IDirect3DVertexBuffer9* v=nullptr;check(dev->CreateVertexBuffer(size,0,0,pool,&v,nullptr),"VB");void* p=nullptr;check(v->Lock(0,0,&p,0),"VB lock");memcpy(p,bytes,size);check(v->Unlock(),"VB unlock");return v;};
  vb=buffer(sizeof(vertices),vertices);float offsets[]={-.2f,0,.2f,0,-.4f,0,.4f,0};inst=buffer(sizeof(offsets),offsets);
  std::vector<unsigned char> storage(3*2048);for(unsigned i=0;i<3;++i)memcpy(storage.data()+i*2048,&vertices[i],sizeof(V));large=buffer(storage.size(),storage.data());
  check(dev->CreateIndexBuffer(6,0,D3DFMT_INDEX16,pool,&ib,nullptr),"IB");void* index=nullptr;check(ib->Lock(0,0,&index,0),"IB lock");WORD indices[]={0,1,2};memcpy(index,indices,6);ib->Unlock();
  FILE* pixels=fopen("pixels.bin","wb");if(!pixels)throw std::runtime_error("pixel file");unsigned frames=0;
  auto states=[&] {dev->SetRenderState(D3DRS_CULLMODE,D3DCULL_NONE);dev->SetRenderState(D3DRS_ZENABLE,FALSE);dev->SetRenderState(D3DRS_LIGHTING,FALSE);dev->SetRenderState(D3DRS_ALPHABLENDENABLE,FALSE);};states();
  auto draw=[&](const char* label,bool indexed=false,bool up=false,UINT stride=sizeof(V),const void* input=nullptr) {
    check(dev->Clear(0,nullptr,D3DCLEAR_TARGET,0xff172331,1,0),"clear");check(dev->BeginScene(),"begin");
    if(up)check(dev->DrawPrimitiveUP(D3DPT_TRIANGLELIST,1,input?input:vertices,stride),"drawUP");
    else if(indexed)check(dev->DrawIndexedPrimitive(D3DPT_TRIANGLELIST,0,0,3,0,1),"indexed draw");
    else check(dev->DrawPrimitive(D3DPT_TRIANGLELIST,0,1),"draw");
    check(dev->EndScene(),"end");
    IDirect3DSurface9 *target=nullptr,*read=nullptr;check(dev->GetRenderTarget(0,&target),"target");D3DSURFACE_DESC desc={};target->GetDesc(&desc);
    check(dev->CreateOffscreenPlainSurface(desc.Width,desc.Height,desc.Format,D3DPOOL_SYSTEMMEM,&read,nullptr),"read surface");check(dev->GetRenderTargetData(target,read),"readback");
    D3DLOCKED_RECT lock={};check(read->LockRect(&lock,nullptr,D3DLOCK_READONLY),"read lock");
    for(unsigned y=0;y<desc.Height;++y)if(fwrite((char*)lock.pBits+y*lock.Pitch,desc.Width*4,1,pixels)!=1)throw std::runtime_error("pixel write");
    read->UnlockRect();read->Release();target->Release();++frames;
    printf("FRAME %u %s %ux%u\n",frames,label,desc.Width,desc.Height);
  };
  for(unsigned n=0;n<12;++n) {
    dev->SetVertexDeclaration(decls[4]);dev->SetVertexShader(directShader);dev->SetPixelShader(ps);
    draw("vector-lanes-tail-duplicate",false,true);
  }
  // Four shader inputs with a missing scalar-tail attribute.
  vectorElements[9].UsageIndex=2;auto vectorMissing=declaration(vectorElements);
  dev->SetVertexDeclaration(vectorMissing);vectorMissing->Release();draw("vector-missing",false,true);
  for(unsigned n=0;n<24;++n) {dev->SetVertexDeclaration(decls[n%3]);dev->SetVertexShader(shaders[n%2]);dev->SetPixelShader(ps);draw("shader-declaration-missing",false,true);}
  dev->SetVertexShader(shaders[0]);dev->SetPixelShader(ps);dev->SetVertexDeclaration(decls[0]);dev->SetStreamSource(0,vb,0,sizeof(V));dev->SetStreamSource(1,inst,0,8);dev->SetIndices(ib);
  IDirect3DStateBlock9* block=nullptr;check(dev->CreateStateBlock(D3DSBT_ALL,&block),"stateblock");
  for(unsigned n=0;n<6;++n) {dev->SetVertexDeclaration(decls[1]);dev->SetVertexShader(shaders[1]);draw("stateblock-other");check(block->Apply(),"apply");draw("stateblock-restored");}block->Release();
  dev->SetVertexDeclaration(decls[4]);dev->SetVertexShader(directShader);
  IDirect3DStateBlock9* vectorBlock=nullptr;check(dev->CreateStateBlock(D3DSBT_ALL,&vectorBlock),"vector stateblock");
  dev->SetVertexDeclaration(decls[0]);dev->SetVertexShader(shaders[0]);draw("vector-stateblock-other");
  check(vectorBlock->Apply(),"vector apply");vectorBlock->Release();draw("vector-stateblock-restored");
  vectorElements[9]={1,0,D3DDECLTYPE_FLOAT2,0,D3DDECLUSAGE_TEXCOORD,1};
  auto vectorInstanced=declaration(vectorElements);dev->SetVertexDeclaration(vectorInstanced);vectorInstanced->Release();
  for(unsigned n=0;n<4;++n) {
    check(dev->SetStreamSourceFreq(0,D3DSTREAMSOURCE_INDEXEDDATA|2),"vector indexed frequency");
    check(dev->SetStreamSourceFreq(1,D3DSTREAMSOURCE_INSTANCEDATA|(1+n%2)),"vector instance frequency");draw("vector-instancing-destruction",true);
  }
  check(dev->SetStreamSourceFreq(0,1),"vector freq reset0");check(dev->SetStreamSourceFreq(1,1),"vector freq reset1");
  dev->SetVertexShader(shaders[2]);dev->SetVertexDeclaration(decls[3]);
  for(unsigned n=0;n<12;++n) {
    check(dev->SetStreamSourceFreq(0,D3DSTREAMSOURCE_INDEXEDDATA|(2+(n%2))),"indexed frequency");
    check(dev->SetStreamSourceFreq(1,D3DSTREAMSOURCE_INSTANCEDATA|(1+(n%2))),"instance frequency");draw("instancing-divisors",true);
  }
  check(dev->SetStreamSourceFreq(0,1),"freq reset0");check(dev->SetStreamSourceFreq(1,1),"freq reset1");
  dev->SetVertexShader(shaders[0]);dev->SetStreamSource(0,large,0,2048);
  for(unsigned n=0;n<280;++n) {auto d=declaration({{0,0,D3DDECLTYPE_FLOAT4,0,D3DDECLUSAGE_POSITION,0},{0,16,D3DDECLTYPE_FLOAT4,0,D3DDECLUSAGE_COLOR,0},{0,WORD(40+n*4),D3DDECLTYPE_FLOAT2,0,D3DDECLUSAGE_TEXCOORD,0},end});dev->SetVertexDeclaration(d);d->Release();draw("fresh-declaration-destruction");}
  dev->SetStreamSource(0,vb,0,sizeof(V));dev->SetVertexDeclaration(decls[0]);draw("declaration-revisit");
  struct F {float x,y,z;DWORD color;float uv[2];}; F fixed[]={ {-.7f,-.6f,0,0xff2857a1,{.2f,.4f}},{0,.6f,0,0xff2857a1,{.2f,.4f}},{.7f,-.6f,0,0xff2857a1,{.2f,.4f}} };
  for(unsigned n=0;n<4;++n) {dev->SetVertexShader(nullptr);dev->SetPixelShader(nullptr);check(dev->SetFVF(D3DFVF_XYZ|D3DFVF_DIFFUSE|(n%2?D3DFVF_TEX1:0)),"FVF");draw("fixed-function",false,true,sizeof(F),fixed);dev->SetVertexDeclaration(decls[0]);dev->SetVertexShader(shaders[0]);dev->SetPixelShader(ps);draw("after-fixed",false,true);}
  // Recreate shader and buffer objects with different values after unbinding.
  // Cache entries may outlive resources, and allocator address reuse must be harmless.
  for(unsigned n=0;n<6;++n) {
    auto code=blob(n%2 ? "void main(float4 p:POSITION,float4 c:COLOR,out float4 q:POSITION,out float4 o:COLOR){q=p;o=c.bgra;}" : "void main(float4 p:POSITION,float4 c:COLOR,out float4 q:POSITION,out float4 o:COLOR){q=p;o=c;}","vs_3_0");
    IDirect3DVertexShader9* transient=nullptr;check(dev->CreateVertexShader((DWORD*)code->GetBufferPointer(),&transient),"transient shader");code->Release();
    V changed[3];memcpy(changed,vertices,sizeof(changed));for(auto& v:changed)v.c[0]=.1f*n;
    auto transientBuffer=buffer(sizeof(changed),changed);
    dev->SetVertexDeclaration(decls[0]);dev->SetVertexShader(transient);dev->SetStreamSource(0,transientBuffer,0,sizeof(V));
    transient->Release();transientBuffer->Release();draw("shader-buffer-destruction");
    dev->SetVertexShader(nullptr);dev->SetStreamSource(0,nullptr,0,0);
  }
  auto releaseBuffers=[&] {dev->SetStreamSource(0,nullptr,0,0);dev->SetStreamSource(1,nullptr,0,0);dev->SetIndices(nullptr);vb->Release();inst->Release();large->Release();ib->Release();};releaseBuffers();
  auto reset=[&] {if(extended)check(devEx->ResetEx(&pp,nullptr),"ResetEx");else check(dev->Reset(&pp),"Reset");states();dev->SetVertexDeclaration(decls[0]);dev->SetVertexShader(shaders[0]);dev->SetPixelShader(ps);draw("after-reset",false,true);dev->SetVertexDeclaration(decls[4]);dev->SetVertexShader(directShader);draw("vector-after-reset",false,true);};reset();
  D3DDISPLAYMODE mode={};check(api->GetAdapterDisplayMode(0,&mode),"display mode");
  // Small valid fullscreen mode keeps exact readbacks and local disk use bounded.
  if(extended) {
    D3DDISPLAYMODEEX full={};full.Size=sizeof(full);full.Width=mode.Width;full.Height=mode.Height;full.RefreshRate=mode.RefreshRate;full.Format=mode.Format;full.ScanLineOrdering=D3DSCANLINEORDERING_PROGRESSIVE;
    pp.Windowed=FALSE;pp.BackBufferWidth=mode.Width;pp.BackBufferHeight=mode.Height;pp.BackBufferFormat=mode.Format;
    check(devEx->ResetEx(&pp,&full),"fullscreenEx");
  } else {pp.Windowed=FALSE;pp.BackBufferWidth=mode.Width;pp.BackBufferHeight=mode.Height;pp.BackBufferFormat=mode.Format;check(dev->Reset(&pp),"fullscreen");}
  states();dev->SetVertexDeclaration(decls[0]);dev->SetVertexShader(shaders[1]);dev->SetPixelShader(ps);draw("fullscreen",false,true);dev->SetVertexDeclaration(decls[4]);dev->SetVertexShader(directShader);draw("vector-fullscreen",false,true);
  pp.Windowed=TRUE;pp.BackBufferWidth=128;pp.BackBufferHeight=96;pp.BackBufferFormat=D3DFMT_A8R8G8B8;reset();
  fclose(pixels);dev->SetVertexDeclaration(nullptr);dev->SetVertexShader(nullptr);dev->SetPixelShader(nullptr);
  for(auto d:decls)d->Release();for(auto s:shaders)s->Release();ps->Release();dev->Release();api->Release();DestroyWindow(win);
  printf("PASS exact pixel artifact, shaders, declarations, missing attributes, instancing, state blocks, destruction, vector lanes and tails, fixed function, reset, fullscreen, teardown frames=%u extended=%d\n",frames,extended);
  return 0;
 }catch(const std::exception& e){printf("FAIL %s\n",e.what());return 1;}
}
