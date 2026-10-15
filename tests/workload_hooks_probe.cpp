#include <windows.h>
#include <d3d9.h>
#include <cstdio>
#include <cstring>
#include <cassert>
#include <thread>
#include <atomic>

int main() {
  // The executable is named WizardGraphicalClient.exe to exercise scoped hooks.
  const auto initial=GetCurrentThreadId();
  char bytes[8]={}; DWORD n=123;
  auto baselineRead=(decltype(&::ReadFile))GetProcAddress(GetModuleHandleA("kernel32.dll"),"ReadFile");
  auto baselineWait=(decltype(&::WaitForSingleObject))GetProcAddress(GetModuleHandleA("kernel32.dll"),"WaitForSingleObject");
  SetLastError(0x1234); BOOL before=baselineRead(INVALID_HANDLE_VALUE,bytes,4,&n,nullptr);
  const auto invalidError=GetLastError();
  HANDLE event=CreateEvent(nullptr,TRUE,TRUE,nullptr);
  SetLastError(0x1234); DWORD waitBefore=baselineWait(event,0), waitError=GetLastError();
  auto dll=LoadLibraryA("d3d9.dll"); assert(dll);
  auto create=(IDirect3D9*(WINAPI*)(UINT))GetProcAddress(dll,"Direct3DCreate9"); assert(create);
  auto api=create(D3D_SDK_VERSION); assert(api);
  WNDCLASSA wc={}; wc.lpfnWndProc=DefWindowProcA; wc.hInstance=GetModuleHandleA(nullptr); wc.lpszClassName="WorkloadProbe"; RegisterClassA(&wc);
  HWND window=CreateWindowA(wc.lpszClassName,"Workload verification",WS_OVERLAPPEDWINDOW,0,0,64,64,nullptr,nullptr,wc.hInstance,nullptr);
  D3DPRESENT_PARAMETERS pp={}; pp.Windowed=TRUE; pp.SwapEffect=D3DSWAPEFFECT_DISCARD; pp.hDeviceWindow=window;
  pp.BackBufferWidth=64; pp.BackBufferHeight=64; pp.BackBufferFormat=D3DFMT_A8R8G8B8;
  IDirect3DDevice9* device=nullptr; assert(SUCCEEDED(api->CreateDevice(0,D3DDEVTYPE_HAL,window,D3DCREATE_HARDWARE_VERTEXPROCESSING,&pp,&device)));
  SetLastError(0x1234); BOOL after=ReadFile(INVALID_HANDLE_VALUE,bytes,4,&n,nullptr);
  assert(before==after && GetLastError()==invalidError);
  SetLastError(0x1234); assert(WaitForSingleObject(event,0)==waitBefore && GetLastError()==waitError);
  assert(WaitForSingleObjectEx(event,0,FALSE)==WAIT_OBJECT_0);
  assert(WaitForMultipleObjects(1,&event,TRUE,0)==WAIT_OBJECT_0);
  assert(WaitForMultipleObjectsEx(1,&event,FALSE,0,FALSE)==WAIT_OBJECT_0);
  ResetEvent(event); assert(WaitForSingleObject(event,2)==WAIT_TIMEOUT);
  assert(WaitForSingleObject(nullptr,0)==WAIT_FAILED && GetLastError()==ERROR_INVALID_HANDLE);
  CRITICAL_SECTION section; InitializeCriticalSection(&section); EnterCriticalSection(&section); LeaveCriticalSection(&section); DeleteCriticalSection(&section);
  HANDLE file=CreateFileA("hook-data.tmp",GENERIC_READ|GENERIC_WRITE,0,nullptr,CREATE_ALWAYS,FILE_ATTRIBUTE_TEMPORARY,nullptr);
  assert(file!=INVALID_HANDLE_VALUE); assert(WriteFile(file,"ASSET",5,&n,nullptr) && n==5);
  SetFilePointer(file,0,nullptr,FILE_BEGIN); assert(ReadFile(file,bytes,8,&n,nullptr) && n==5 && !memcmp(bytes,"ASSET",5));
  assert(ReadFile(file,bytes,8,&n,nullptr) && n==0); CloseHandle(file);
  file=CreateFileA("hook-data.tmp",GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,FILE_FLAG_OVERLAPPED,nullptr);
  assert(file!=INVALID_HANDLE_VALUE); OVERLAPPED pending={}; pending.hEvent=CreateEvent(nullptr,TRUE,FALSE,nullptr);
  BOOL read=ReadFile(file,bytes,5,&n,&pending);
  assert(read || GetLastError()==ERROR_IO_PENDING); assert(GetOverlappedResult(file,&pending,&n,TRUE) && n==5 && !memcmp(bytes,"ASSET",5));
  CloseHandle(pending.hEvent); CloseHandle(file); DeleteFileA("hook-data.tmp"); CloseHandle(event);
  std::atomic<unsigned long long> work{0}; DWORD workerId=0;
  std::thread worker([&] { workerId=GetCurrentThreadId(); auto until=GetTickCount64()+700; unsigned long long x=1; while(GetTickCount64()<until) x=x*1664525+1013904223; work=x; });
  worker.join(); device->Release(); api->Release(); DestroyWindow(window);
  printf("PASS read sync/async/EOF/errors, wait signaled/timeout/invalid/multiple/alertable, critical section initial_tid=%lu worker_tid=%lu\n",initial,workerId);
}
