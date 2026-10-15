#pragma once
#include <mutex>
namespace dxvk::wizard101 {
inline void InstallDecompressionHooks() {
  static std::once_flag once;
  std::call_once(once,[] {
    DWORD incoming=GetLastError();
    auto value=env::getEnvVar("W101_DECOMPRESS");
    if(value=="buffer" || value=="stream" || value=="both" || env::getEnvVar("W101_NATIVE_DECODE")=="auto") {
      char path[32768];
      if(GetModuleFileNameA(nullptr,path,sizeof(path))) {
        char* slash=strrchr(path,'\\');
        if(slash && size_t(slash-path)+sizeof("\\w101decompress.dll")<sizeof(path)) {
          strcpy(slash,"\\w101decompress.dll");
          HMODULE dll=LoadLibraryExA(path,nullptr,LOAD_WITH_ALTERED_SEARCH_PATH);
          if(dll) {
            auto install=(unsigned(__cdecl*)())GetProcAddress(dll,"W101InstallDecompression");
            if(install) Logger::info(str::format("W101 decompression: ",install()," verified game imports"));
            // Keep code resident for the lifetime of patched IAT entries.
          }
        }
      }
    }
    SetLastError(incoming);
  });
}
}
