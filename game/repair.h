#pragma once
#include <windows.h>
#include <bcrypt.h>
#include <stdint.h>
#include <string.h>
#include "lookup.h"
#include "vendor/minhook/include/MinHook.h"

namespace w101repair {
inline constexpr unsigned LookupRVA=0x2239020,LookupSize=164,GetterRVA=0x224ed40,EmptyRVA=0x2dce7d8;
inline constexpr char GameSHA[]="544ab726ef7b920a5ccb67aa3d06b245db7e0012317d2fe7856d58c17c31cf7e";
inline constexpr char LookupSHA[]="5d67b2171d7d6f6f65bd27ea33557c072985a9392d3f3ce40cf8ce8fa30e8d1e";
inline unsigned char *image=nullptr;
inline void *target=nullptr,*trampoline=nullptr;
inline RUNTIME_FUNCTION trampolineUnwind{};
inline bool created=false,enabled=false,unwindRegistered=false;
inline const char *status="off";
inline void hex(const unsigned char digest[32],char out[65]) {
    const char *digits="0123456789abcdef";
    for(unsigned i=0;i<32;i++){out[2*i]=digits[digest[i]>>4];out[2*i+1]=digits[digest[i]&15];}out[64]=0;
}
inline bool hash(const void *data,unsigned count,char out[65]) {
    BCRYPT_ALG_HANDLE alg=nullptr;BCRYPT_HASH_HANDLE h=nullptr;unsigned char digest[32];bool ok=false;
    if(BCryptOpenAlgorithmProvider(&alg,BCRYPT_SHA256_ALGORITHM,nullptr,0)>=0 &&
       BCryptCreateHash(alg,&h,nullptr,0,nullptr,0,0)>=0 &&
       BCryptHashData(h,(PUCHAR)data,count,0)>=0 && BCryptFinishHash(h,digest,32,0)>=0) {hex(digest,out);ok=true;}
    if(h)BCryptDestroyHash(h);
    if(alg)BCryptCloseAlgorithmProvider(alg,0);
    return ok;
}
inline bool approvedExecutable() {
    wchar_t path[32768];if(!GetModuleFileNameW(nullptr,path,32768))return false;
    HANDLE file=CreateFileW(path,GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,0,nullptr);
    if(file==INVALID_HANDLE_VALUE)return false;
    BCRYPT_ALG_HANDLE alg=nullptr;BCRYPT_HASH_HANDLE h=nullptr;bool ok=false;unsigned char digest[32],block[65536];
    if(BCryptOpenAlgorithmProvider(&alg,BCRYPT_SHA256_ALGORITHM,nullptr,0)>=0 && BCryptCreateHash(alg,&h,nullptr,0,nullptr,0,0)>=0) {
        DWORD n;BOOL read;
        while((read=ReadFile(file,block,sizeof(block),&n,nullptr)) && n)if(BCryptHashData(h,block,n,0)<0){read=FALSE;break;}
        if(read && BCryptFinishHash(h,digest,32,0)>=0){char text[65];hex(digest,text);ok=!strcmp(text,GameSHA);}
    }
    if(h)BCryptDestroyHash(h);
    if(alg)BCryptCloseAlgorithmProvider(alg,0);
    CloseHandle(file);return ok;
}
inline void *lookup(const void *object,const uint64_t *key) {
    return w101_lookup(object,key,(const uint64_t*)(image+EmptyRVA));
}
inline bool installVerifiedImage(unsigned char *base) {
    if(created && image!=base){status="different-image-rejected";return false;}
    if(enabled)return true;
    if(!created) {
        char digest[65];const unsigned char getter[]={0x48,0x8d,0x41,0x10,0xc3};
        if(!hash(base+LookupRVA,LookupSize,digest)||strcmp(digest,LookupSHA)||memcmp(base+GetterRVA,getter,sizeof(getter))) {
            status="code-signature-rejected";return false;
        }
        HMODULE owner=nullptr;
        if(!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS|GET_MODULE_HANDLE_EX_FLAG_PIN,(LPCWSTR)&lookup,&owner)) {
            status="module-pin-failed";return false;
        }
        MH_STATUS result=MH_Initialize();
        if(result!=MH_OK && result!=MH_ERROR_ALREADY_INITIALIZED){status="hook-init-failed";return false;}
        image=base;target=base+LookupRVA;
        if(MH_CreateHook(target,(void*)&lookup,&trampoline)!=MH_OK){status="hook-create-failed";return false;}
        created=true;
        // Pinned MinHook's 64-byte slot holds a 5-byte original instruction,
        // 14-byte return jump and 14-byte relay. Validate that exact layout
        // before placing prologue unwind metadata in its unused final 16 bytes.
        auto *code=(unsigned char*)trampoline;uint64_t back=0;
        memcpy(&back,code+11,8);
        if(memcmp(code,base+LookupRVA,5)||code[5]!=0xff||code[6]!=0x25||
           code[7]||code[8]||code[9]||code[10]||back!=(uint64_t)(base+LookupRVA+5)) {
            status="trampoline-layout-rejected";return false;
        }
        const unsigned char unwind[]={1,5,2,0,5,0x34,1,0};
        memcpy(code+48,unwind,sizeof(unwind));
        trampolineUnwind.BeginAddress=0;trampolineUnwind.EndAddress=19;trampolineUnwind.UnwindData=48;
        if(!RtlAddFunctionTable(&trampolineUnwind,1,(DWORD64)trampoline)){status="unwind-registration-failed";return false;}
        unwindRegistered=true;
    }
    if(!unwindRegistered){status="unqualified-trampoline";return false;}
    if(MH_EnableHook(target)!=MH_OK){status="activation-rejected-original-retained";return false;}
    enabled=true;status="lookup-enabled";return true;
}
inline bool disable() {
    if(!enabled)return true;
    if(MH_DisableHook(target)!=MH_OK){status="deactivation-rejected-hook-retained";return false;}
    enabled=false;status="off";return true;
}
inline bool install() {
    DWORD incoming=GetLastError();char selected[8];bool ok=false;
    if(GetEnvironmentVariableA("W101_GAME_REPAIR",selected,sizeof(selected))==1 && selected[0]=='1') {
        if(approvedExecutable())ok=installVerifiedImage((unsigned char*)GetModuleHandleW(nullptr));
        else status="executable-hash-rejected";
    }
    SetLastError(incoming);return ok;
}
// No loader-lock teardown. The pinned code and at most one 64-byte trampoline
// remain valid until process exit, including failed activation and rollback.
}
