#pragma once
#include "wizard101_asset_preparation.h"
#include "../util/util_profile.h"
#include "../util/log/log.h"
#include "wizard101_performance_identity.h"
namespace dxvk::wizard101 {
using MemoryLoader=HRESULT(WINAPI*)(IDirect3DDevice9*,const void*,UINT,IDirect3DTexture9**);
using MemoryLoaderEx=HRESULT(WINAPI*)(IDirect3DDevice9*,const void*,UINT,UINT,UINT,UINT,DWORD,D3DFORMAT,D3DPOOL,DWORD,DWORD,D3DCOLOR,ImageInfo*,PALETTEENTRY*,IDirect3DTexture9**);
using FileLoaderExA=HRESULT(WINAPI*)(IDirect3DDevice9*,const char*,UINT,UINT,UINT,DWORD,D3DFORMAT,D3DPOOL,DWORD,DWORD,D3DCOLOR,ImageInfo*,PALETTEENTRY*,IDirect3DTexture9**);
inline MemoryLoader originalAssetMemory=nullptr;
inline MemoryLoaderEx originalAssetMemoryEx=nullptr;
inline FileLoaderExA originalAssetFileExA=nullptr;
inline HRESULT WINAPI loadAssetMemory(IDirect3DDevice9* device,const void* bytes,UINT count,IDirect3DTexture9** output) {
  DWORD incoming=GetLastError(); auto cache=assetCache(device); AssetKey key;
  bool keyed=false; unsigned codec=4;
  try {
    if(cache && device && bytes && count && output) {
      keyed=cache->key(bytes,count,{0,count},key);
      codec=assetCodec(bytes,count);
      if(keyed && cache->canReuse(codec) && cache->takePrepared(key,output,nullptr)) { SetLastError(incoming); return D3D_OK; }
      if(keyed && cache->canReuse(codec)) if(auto entry=cache->find(key,false)) {
        if(SUCCEEDED(AssetCache::restore(*entry,device,output,nullptr))) { SetLastError(incoming); return D3D_OK; }
      }
    }
  } catch(...) { keyed=false; }
  SetLastError(incoming);
  HRESULT hr; DWORD error;
  { ProfileScope scope("native_asset_decode"); hr=originalAssetMemory(device,bytes,count,output); error=GetLastError(); }
  // Cache only the unchanged-LastError success contract observed in the probe.
  if(keyed && hr==D3D_OK && error==incoming && output) try { cache->observedSuccess(codec); cache->remember(key,*output,nullptr); } catch(...) { }
  SetLastError(error); return hr;
}
inline HRESULT WINAPI loadAssetMemoryEx(IDirect3DDevice9* device,const void* bytes,UINT count,UINT width,UINT height,UINT mips,DWORD usage,D3DFORMAT format,D3DPOOL pool,DWORD filter,DWORD mipFilter,D3DCOLOR colorKey,ImageInfo* info,PALETTEENTRY* palette,IDirect3DTexture9** output) {
  DWORD incoming=GetLastError(); auto cache=assetCache(device); AssetKey key; bool keyed=false; unsigned codec=4;
  try {
    if(cache && device && bytes && count && output && pool==D3DPOOL_MANAGED && usage==0 && !palette) {
      keyed=cache->key(bytes,count,{1,count,width,height,mips,usage,uint32_t(format),uint32_t(pool),filter,mipFilter,colorKey,1},key);
      codec=assetCodec(bytes,count);
      if(keyed && cache->canReuse(codec) && cache->takePrepared(key,output,info)) { SetLastError(incoming); return D3D_OK; }
      if(keyed && cache->canReuse(codec)) if(auto entry=cache->find(key,info!=nullptr)) {
        if(SUCCEEDED(AssetCache::restore(*entry,device,output,info))) { SetLastError(incoming); return D3D_OK; }
      }
    }
  } catch(...) { keyed=false; }
  SetLastError(incoming); HRESULT hr; DWORD error;
  { ProfileScope scope("native_asset_decode"); hr=originalAssetMemoryEx(device,bytes,count,width,height,mips,usage,format,pool,filter,mipFilter,colorKey,info,palette,output); error=GetLastError(); }
  if(keyed && hr==D3D_OK && error==incoming && output) try { cache->observedSuccess(codec); cache->remember(key,*output,info); } catch(...) { }
  SetLastError(error); return hr;
}
inline HRESULT WINAPI loadAssetFileExA(IDirect3DDevice9* device,const char* filename,UINT width,UINT height,UINT mips,DWORD usage,D3DFORMAT format,D3DPOOL pool,DWORD filter,DWORD mipFilter,D3DCOLOR colorKey,ImageInfo* info,PALETTEENTRY* palette,IDirect3DTexture9** output) {
  DWORD incoming=GetLastError(); auto cache=assetCache(device); AssetKey key; bool keyed=false;
  // Deny writes/rename during hashing and decoding, so the key names the exact decoded content.
  // If native D3DX requires exclusive access, retry without this optional guard.
  HANDLE file=INVALID_HANDLE_VALUE;
  try {
    // The verified FileExA decoder clears LastError on success. Nonzero incoming
    // errors use the original call, rather than assuming an unchanged-error contract.
    if(cache && device && filename && output && !incoming && pool==D3DPOOL_MANAGED && usage==0 && !palette) {
      file=CreateFileA(filename,GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,0,nullptr);
      LARGE_INTEGER size{};
      if(file!=INVALID_HANDLE_VALUE && GetFileSizeEx(file,&size) && size.QuadPart>0 && size.QuadPart<=AssetLimit) {
        UINT count=UINT(size.QuadPart);
        keyed=cache->fileKey(file,count,{2,count,width,height,mips,usage,uint32_t(format),uint32_t(pool),filter,mipFilter,colorKey,1},key);
        if(keyed && cache->takePrepared(key,output,info)) { CloseHandle(file); SetLastError(incoming); return D3D_OK; }
        if(keyed) if(auto entry=cache->find(key,info!=nullptr)) {
          if(SUCCEEDED(AssetCache::restore(*entry,device,output,info))) { CloseHandle(file); SetLastError(incoming); return D3D_OK; }
        }
      }
    }
  } catch(...) { keyed=false; }
  if(!keyed && file!=INVALID_HANDLE_VALUE) { CloseHandle(file); file=INVALID_HANDLE_VALUE; }
  SetLastError(incoming); HRESULT hr; DWORD error;
  { ProfileScope scope("native_asset_decode"); hr=originalAssetFileExA(device,filename,width,height,mips,usage,format,pool,filter,mipFilter,colorKey,info,palette,output); error=GetLastError(); }
  if(FAILED(hr) && file!=INVALID_HANDLE_VALUE) {
    CloseHandle(file); file=INVALID_HANDLE_VALUE; keyed=false; SetLastError(incoming);
    hr=originalAssetFileExA(device,filename,width,height,mips,usage,format,pool,filter,mipFilter,colorKey,info,palette,output); error=GetLastError();
  }
  if(keyed && hr==D3D_OK && error==incoming && output) try { cache->remember(key,*output,info); } catch(...) { }
  if(file!=INVALID_HANDLE_VALUE) CloseHandle(file);
  SetLastError(error); return hr;
}
inline bool verifiedPerformanceExe() {
  if(env::getExeName()!="WizardGraphicalClient.exe") return false;
  if(feature("W101_PERFORMANCE_TEST")) return true; // disposable verification prefixes only
  char path[32768]; if(!GetModuleFileNameA(nullptr,path,sizeof(path))) return false;
  HANDLE file=CreateFileA(path,GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,0,nullptr);
  if(file==INVALID_HANDLE_VALUE) return false;
  BCRYPT_ALG_HANDLE alg=nullptr; BCRYPT_HASH_HANDLE hash=nullptr; unsigned char digest[32]; bool ok=false;
  if(BCryptOpenAlgorithmProvider(&alg,BCRYPT_SHA256_ALGORITHM,nullptr,0)>=0 && BCryptCreateHash(alg,&hash,nullptr,0,nullptr,0,0)>=0) {
    unsigned char block[65536]; DWORD read=0; BOOL result;
    while((result=ReadFile(file,block,sizeof(block),&read,nullptr)) && read) if(BCryptHashData(hash,block,read,0)<0) { result=FALSE; break; }
    if(result && BCryptFinishHash(hash,digest,sizeof(digest),0)>=0) {
      char hex[65]; static const char digits[]="0123456789abcdef";
      for(unsigned i=0;i<32;++i) { hex[i*2]=digits[digest[i]>>4]; hex[i*2+1]=digits[digest[i]&15]; } hex[64]=0;
      ok=!strcmp(hex,W101_PERFORMANCE_GAME_SHA256);
    }
  }
  if(hash) BCryptDestroyHash(hash); if(alg) BCryptCloseAlgorithmProvider(alg,0); CloseHandle(file); return ok;
}
inline void InstallAssetHooks() {
  if(!feature("W101_ASSET_CACHE") && !profileEnabled()) return;
  static std::once_flag once;
  std::call_once(once,[] {
    DWORD incoming=GetLastError();
    if(!verifiedPerformanceExe()) { Logger::warn("W101 asset adapter: executable hash not approved; native loader retained"); SetLastError(incoming); return; }
    auto* base=(unsigned char*)GetModuleHandleW(nullptr);
    auto* nt=(IMAGE_NT_HEADERS*)(base+((IMAGE_DOS_HEADER*)base)->e_lfanew);
    auto* imports=(IMAGE_IMPORT_DESCRIPTOR*)(base+nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT].VirtualAddress);
    unsigned count=0;
    for(;imports->Name;++imports) {
      if(_stricmp((const char*)base+imports->Name,"d3dx9_43.dll") || !imports->OriginalFirstThunk) continue;
      auto* names=(IMAGE_THUNK_DATA*)(base+imports->OriginalFirstThunk); auto* slots=(IMAGE_THUNK_DATA*)(base+imports->FirstThunk);
      for(;names->u1.AddressOfData;++names,++slots) {
        if(IMAGE_SNAP_BY_ORDINAL(names->u1.Ordinal)) continue;
        const char* name=(const char*)((IMAGE_IMPORT_BY_NAME*)(base+names->u1.AddressOfData))->Name;
        void* replacement=nullptr;
        if(!strcmp(name,"D3DXCreateTextureFromFileInMemory")) { originalAssetMemory=(MemoryLoader)slots->u1.Function; replacement=(void*)loadAssetMemory; }
        if(!strcmp(name,"D3DXCreateTextureFromFileInMemoryEx")) { originalAssetMemoryEx=(MemoryLoaderEx)slots->u1.Function; replacement=(void*)loadAssetMemoryEx; }
        if(!strcmp(name,"D3DXCreateTextureFromFileExA")) { originalAssetFileExA=(FileLoaderExA)slots->u1.Function; replacement=(void*)loadAssetFileExA; }
        DWORD protection,ignored;
        if(replacement && VirtualProtect(&slots->u1.Function,sizeof(void*),PAGE_READWRITE,&protection)) {
          InterlockedExchangePointer((void* volatile*)&slots->u1.Function,replacement);
          VirtualProtect(&slots->u1.Function,sizeof(void*),protection,&ignored); ++count;
        }
      }
    }
    Logger::info(str::format("W101 asset adapter: ",count," verified main-executable native D3DX memory/file imports; managed static 2D only"));
    SetLastError(incoming);
  });
}
}
