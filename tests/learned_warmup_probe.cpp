#include <windows.h>
#include <d3d9.h>
#include <cstdio>

int main() {
  WNDCLASSA wc = {};
  wc.lpfnWndProc = DefWindowProcA;
  wc.hInstance = GetModuleHandleA(nullptr);
  wc.lpszClassName = "LearnedWarmupProbe";
  RegisterClassA(&wc);
  HWND window = CreateWindowA(wc.lpszClassName, "Wizard101 cache verification",
    WS_OVERLAPPEDWINDOW | WS_VISIBLE, 100, 100, 640, 480,
    nullptr, nullptr, wc.hInstance, nullptr);
  auto api = Direct3DCreate9(D3D_SDK_VERSION);
  if (!window || !api) return 1;
  D3DPRESENT_PARAMETERS pp = {};
  pp.Windowed = TRUE;
  pp.SwapEffect = D3DSWAPEFFECT_DISCARD;
  pp.BackBufferWidth = 640;
  pp.BackBufferHeight = 480;
  pp.BackBufferFormat = D3DFMT_A8R8G8B8;
  pp.hDeviceWindow = window;
  pp.PresentationInterval = D3DPRESENT_INTERVAL_IMMEDIATE;
  IDirect3DDevice9* device = nullptr;
  auto result = api->CreateDevice(0, D3DDEVTYPE_HAL, window,
    D3DCREATE_HARDWARE_VERTEXPROCESSING, &pp, &device);
  if (FAILED(result)) return 2;
  if (FAILED(device->Clear(0, nullptr, D3DCLEAR_TARGET, 0xff203040, 1, 0))) return 3;
  if (FAILED(device->Present(nullptr, nullptr, nullptr, nullptr))) return 4;
  device->Release();
  api->Release();
  DestroyWindow(window);
  std::puts("PASS learned cache device and presentation");
  return 0;
}
