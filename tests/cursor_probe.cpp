#include <windows.h>
#include <d3d9.h>
#include <cstdio>
#include <cstdlib>
#include <stdexcept>
#include <vector>

static void require(bool value, const char* label) {
  if (!value) throw std::runtime_error(label);
}

static void inspect(HCURSOR cursor, int expected) {
  require(cursor != nullptr, "cursor load");
  ICONINFO info = {};
  require(GetIconInfo(cursor, &info), "cursor info");
  BITMAP bitmap = {};
  require(GetObjectW(info.hbmColor, sizeof(bitmap), &bitmap) != 0, "color bitmap");
  std::printf("Cursor bitmap=%ldx%ld hotspot=%lu,%lu expected=%d\n",
    bitmap.bmWidth, bitmap.bmHeight, info.xHotspot, info.yHotspot, expected);
  require(bitmap.bmWidth == expected && bitmap.bmHeight == expected, "cursor dimensions");
  require(info.xHotspot == unsigned(7 * expected / 32)
       && info.yHotspot == unsigned(11 * expected / 32), "scaled click hotspot");
  BITMAPINFO dib = {};
  dib.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
  dib.bmiHeader.biWidth = expected; dib.bmiHeader.biHeight = -expected;
  dib.bmiHeader.biPlanes = 1; dib.bmiHeader.biBitCount = 32;
  std::vector<DWORD> pixels(expected * expected);
  HDC dc = GetDC(nullptr);
  require(GetDIBits(dc, info.hbmColor, 0, expected, pixels.data(), &dib, DIB_RGB_COLORS)
    == expected, "cursor pixel readback");
  ReleaseDC(nullptr, dc);
  require(pixels[(expected / 4) * expected + expected / 4] == 0xff00ff00,
          "opaque green preserved");
  require(pixels[(expected / 4) * expected + expected * 3 / 4] == 0xffff0000,
          "opaque red preserved");
  require(pixels[(expected * 3 / 4) * expected + expected / 4] == 0,
          "transparent pixels preserved");
  DeleteObject(info.hbmColor); DeleteObject(info.hbmMask);
  std::printf("PASS cursor %dx%d hotspot=%u,%u, color and transparency\n",
              expected, expected, unsigned(info.xHotspot), unsigned(info.yHotspot));
}

// Reload the IAT on each call, matching Wizard101's direct import call sites.
__attribute__((noinline)) static HCURSOR load(const char* path) {
  return LoadCursorFromFileA(path);
}

int main(int argc, char** argv) {
  setvbuf(stdout, nullptr, _IONBF, 0);
  try {
    require(argc == 2, "expected size argument");
    HCURSOR before = load("test.cur");
    inspect(before, 32); DestroyCursor(before);
    HMODULE dll = LoadLibraryA("d3d9.dll");
    require(dll != nullptr, "load patched DLL");
    auto create = reinterpret_cast<IDirect3D9*(WINAPI*)(UINT)>(
      GetProcAddress(dll, "Direct3DCreate9"));
    require(create != nullptr, "create export");
    IDirect3D9* api = create(D3D_SDK_VERSION);
    require(api != nullptr, "create D3D9");
    int expected = std::atoi(argv[1]);
    // Repeated creations and loads check hook idempotence and handle ownership.
    IDirect3D9* second = create(D3D_SDK_VERSION); require(second != nullptr, "second create");
    for (int i = 0; i < 20; ++i) {
      HCURSOR cursor = load("test.cur");
      inspect(cursor, expected);
      require(DestroyCursor(cursor), "caller destroys returned cursor");
    }
    require(load("missing-file.cur") == nullptr, "failed load propagated");
    second->Release(); api->Release();
    std::puts("PASS cursor hook, hotspot, transparency, lifetime, missing file, scope");
    return 0;
  } catch (const std::exception& e) {
    std::printf("FAIL %s\n", e.what()); return 1;
  }
}
