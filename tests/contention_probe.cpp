#include <windows.h>
#include <d3d9.h>
#include <cstdio>
#include <thread>
#include <chrono>
int main() {
  auto* api=Direct3DCreate9(D3D_SDK_VERSION);if(!api)return 1;
  WNDCLASSA wc{};wc.lpfnWndProc=DefWindowProcA;wc.hInstance=GetModuleHandleA(nullptr);wc.lpszClassName="ContentionProbe";RegisterClassA(&wc);
  auto window=CreateWindowA(wc.lpszClassName,"Contention verification",WS_OVERLAPPEDWINDOW,0,0,64,64,nullptr,nullptr,wc.hInstance,nullptr);
  D3DPRESENT_PARAMETERS pp{};pp.Windowed=TRUE;pp.SwapEffect=D3DSWAPEFFECT_DISCARD;pp.hDeviceWindow=window;pp.BackBufferWidth=64;pp.BackBufferHeight=64;pp.BackBufferFormat=D3DFMT_A8R8G8B8;
  IDirect3DDevice9* device=nullptr;if(FAILED(api->CreateDevice(0,D3DDEVTYPE_HAL,window,D3DCREATE_HARDWARE_VERTEXPROCESSING,&pp,&device)))return 3;
  CRITICAL_SECTION section;InitializeCriticalSection(&section);
  auto start=std::chrono::steady_clock::now();
  FILETIME creation,exit,kernelBefore,userBefore,kernelAfter,userAfter;
  GetThreadTimes(GetCurrentThread(),&creation,&exit,&kernelBefore,&userBefore);
  for(int i=0;i<100000000;++i){EnterCriticalSection(&section);LeaveCriticalSection(&section);}
  printf("BENCH uncontended_100000000_us=%lld\n",(long long)std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now()-start).count());
  GetThreadTimes(GetCurrentThread(),&creation,&exit,&kernelAfter,&userAfter);
  auto ticks=[](FILETIME t){return (uint64_t(t.dwHighDateTime)<<32)|t.dwLowDateTime;};
  printf("BENCH uncontended_cpu_100ns=%llu\n",(unsigned long long)(ticks(kernelAfter)+ticks(userAfter)-ticks(kernelBefore)-ticks(userBefore)));
  auto held=CreateEventA(nullptr,TRUE,FALSE,nullptr);DWORD owner=0;
  std::thread worker([&]{owner=GetCurrentThreadId();EnterCriticalSection(&section);SetEvent(held);Sleep(80);LeaveCriticalSection(&section);});
  WaitForSingleObject(held,INFINITE);SetLastError(0x1234);EnterCriticalSection(&section);
  if(GetLastError()!=0x1234)return 2;EnterCriticalSection(&section);LeaveCriticalSection(&section);LeaveCriticalSection(&section);worker.join();
  printf("PASS contended acquisition, recursive acquisition, LastError initial_tid=%lu owner_tid=%lu\n",GetCurrentThreadId(),owner);
  CloseHandle(held);DeleteCriticalSection(&section);device->Release();api->Release();DestroyWindow(window);return 0;
}
