#pragma once
#include <intrin.h>
#include "repair.h"
#include "scene_pool.h"
#include "scene_transaction.h"

extern "C" {
inline void *(*w101_scene_original_alloc)(size_t)=nullptr;
__attribute__((used)) inline void *w101_scene_try_allocate(size_t n) noexcept {
    DWORD incoming=__readgsdword(0x68);
    void *p=w101scene::tryAllocate(n);
    __writegsdword(0x68,incoming);return p;
}
void *w101_scene_allocate(size_t);
}
namespace w101scene {
inline void (*originalFree)(void*,size_t)=nullptr;
inline void freeNode(void *p,size_t size) noexcept {
    if(size==24&&release(p))return;
    originalFree(p,size);
}
inline void destroyList(void *object) noexcept {
    auto list=(void**)object;auto head=(void**)*list;
    *(void**)head[1]=nullptr;
    void *p=*head;
    while(p) {void *next=*(void**)p;freeNode(p,24);p=next;}
    freeNode(*list,24);
}
inline void destroyGuard(void *object) noexcept {
    void *p=((void**)object)[1];if(p)freeNode(p,24);
}
struct Signature { unsigned rva,size; const char *sha; };
inline constexpr Signature signatures[]={
    {0x19c8ee0,2637,"d4020c73c6a31b74a43784c0ce4efd8dfa49199e352605a75e5668003384e5af"},
    {0x28fe30,92,"3bbdffb25ae3257279344f5e905e5b3241e334d32cb348665644191180bd8da2"},
    {0x24bc20,20,"5318986902338796d2768991c8dedf060c3ff2e34a0760785131cbd4e3fa9bbe"},
    {0x24581e8,60,"05a16c32298128a23c4dec191663ea1cb871acc067e63e64ef8108e701428386"},
    {0x1871e90,5,"ff5911db96e994ca7a7add6f09911e324a01c497130aca8df2d58c4e5ed53c1b"},
    {0x3170dff,9,"e57c2d57fadb430fb2859ceb7dd4e4ae3a1f0435f864e4c88638a0ac62a333e1"},
    {0x3170e20,56,"a078fa8ceb9151eb02cbfabeba44f1081ef7d73d4c9830914a6a1ea0e277de3e"},
    {0x3170e58,229,"2cafde6781d7a51ef2a4e0f97a29152392e849989baf327f37b0cc6693422156"}
};
inline Patch patches[9]{};
inline unsigned char *image=nullptr,*relayPage=nullptr;
inline bool enabled=false,prepared=false;
inline const char *status="off";
inline bool verifyImage(unsigned char *base) {
    char digest[65];for(auto &s:signatures)if(!w101repair::hash(base+s.rva,s.size,digest)||strcmp(digest,s.sha))return false;
    return true;
}
inline bool prepare(unsigned char *base) {
    if(prepared)return image==base;
    if(!verifyImage(base)){status="code-or-exception-signature-rejected";return false;}
    if(tlsIndex==TLS_OUT_OF_INDEXES)tlsIndex=TlsAlloc();
    if(tlsIndex==TLS_OUT_OF_INDEXES){status="tls-allocation-failed";return false;}
    // Relays must be within both signed rel32 reach and image-relative EH reach.
    SYSTEM_INFO info;GetSystemInfo(&info);uintptr_t start=((uintptr_t)base+0x370e000+info.dwAllocationGranularity-1)&~uintptr_t(info.dwAllocationGranularity-1);
    for(uintptr_t a=start;a<(uintptr_t)base+0x70000000;a+=info.dwAllocationGranularity) {
        MEMORY_BASIC_INFORMATION region{};
        if(!VirtualQuery((void*)a,&region,sizeof(region)))break;
        if(region.State==MEM_FREE) {relayPage=(unsigned char*)VirtualAlloc((void*)a,4096,MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE);if(relayPage)break;}
        else {uintptr_t end=(uintptr_t)region.BaseAddress+region.RegionSize;if(end>a)a=(end-1)&~uintptr_t(info.dwAllocationGranularity-1);}
    }
    if(!relayPage){status="near-relay-allocation-failed";return false;}
    void *functions[]={(void*)&w101_scene_allocate,(void*)&freeNode,(void*)&destroyList,(void*)&destroyGuard};
    for(unsigned i=0;i<4;i++) {
        unsigned char *r=relayPage+16*i;r[0]=0xff;r[1]=0x25;memset(r+2,0,4);memcpy(r+6,&functions[i],8);
    }
    DWORD old;if(!VirtualProtect(relayPage,4096,PAGE_EXECUTE_READ,&old)||!FlushInstructionCache(GetCurrentProcess(),relayPage,64)) {
        VirtualFree(relayPage,0,MEM_RELEASE);relayPage=nullptr;status="relay-protection-failed";return false;
    }
    constexpr unsigned rvas[]={0x19c8f58,0x19c8f93,0x19c90ed,0x19c9045,0x19c98c8,0x19c98df,0x3170e5a,0x3170e60,0x3170e67};
    for(unsigned i=0;i<9;i++) {
        auto &p=patches[i];p.address=base+rvas[i];p.size=i<6?5:4;memcpy(p.before,p.address,p.size);
        unsigned relay=i<3?0:i<6?1:i==6?2:3;
        intptr_t offset=i<6?relayPage+16*relay-(p.address+5):relayPage+16*relay-base;
        if(offset<INT32_MIN||offset>INT32_MAX){status="relay-range-rejected";return false;}
        int32_t value=(int32_t)offset;
        if(i<6){p.after[0]=0xe8;memcpy(p.after+1,&value,4);}else memcpy(p.after,&value,4);
    }
    // Pin before any edit: callbacks and relays outlive every traversal,
    // exception, failed activation and rollback.
    HMODULE owner=nullptr;
    if(!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS|GET_MODULE_HANDLE_EX_FLAG_PIN,(LPCWSTR)&destroyList,&owner)) {
        status="module-pin-failed";return false;
    }
    image=base;w101_scene_original_alloc=(decltype(w101_scene_original_alloc))(base+0x24581e8);
    originalFree=(decltype(originalFree))(base+0x1871e90);prepared=true;return true;
}
inline bool installVerifiedImage(unsigned char *base) {
#ifndef W101_SCENE_VERIFY
    (void)base;status="qualification-failed-installation-disabled";return false;
#else
    if(enabled)return base==image;
    if(!prepare(base))return false;
    if(!verifyImage(base)){status="code-or-exception-signature-rejected";return false;}
    if(!transact(patches,9,true)){status="transaction-rejected-original-retained";return false;}
    enabled=true;status="scene-node-reuse-enabled";return true;
#endif
}
inline bool disable() {
    if(!enabled)return true;
    if(!transact(patches,9,false)){status="rollback-rejected-cleanup-retained";return false;}
    enabled=false;status="off";return true;
}
inline bool install() {
    DWORD incoming=GetLastError();char value[8];bool ok=false;
    if(GetEnvironmentVariableA("W101_SCENE_NODES",value,sizeof(value))==1&&value[0]=='1') {
        if(w101repair::approvedExecutable())ok=installVerifiedImage((unsigned char*)GetModuleHandleW(nullptr));
        else status="executable-hash-rejected";
    }
    SetLastError(incoming);return ok;
}
}
