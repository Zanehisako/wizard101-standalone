#pragma once
#include <windows.h>
#include <stdint.h>
#include <intrin.h>

// Only the private, synchronous 24-byte traversal list is eligible. Slots and
// their TLS pointers live until process exit; there is no loader-lock teardown.
namespace w101scene {
constexpr unsigned Nodes=256, Threads=64, None=256;
struct alignas(16) Node { unsigned char bytes[24]; unsigned short next; };
static_assert(sizeof(Node)==32);
struct Slot {
    volatile LONG owner=0;
    unsigned head=0, live=0;
    Node nodes[Nodes]{};
};
inline Slot slots[Threads]{};
inline DWORD tlsIndex=TLS_OUT_OF_INDEXES;
inline Slot *tlsValue() noexcept {
    if(tlsIndex<64)return (Slot*)__readgsqword(0x1480+tlsIndex*8);
    if(tlsIndex==TLS_OUT_OF_INDEXES)return nullptr;
    DWORD error=__readgsdword(0x68);
    auto p=(Slot*)TlsGetValue(tlsIndex);__writegsdword(0x68,error);return p;
}
inline Slot *current() noexcept {
    auto p=tlsValue();
    return p==(Slot*)1?nullptr:p;
}
static_assert(sizeof(slots)<1024*1024-65536, "Pool plus installation storage must fit 1 MiB");
// A slot is retained for a thread's entire lifetime. More than 64 distinct
// threads, including thread churn, use the original allocator. Never recycle
// a slot based on a Windows thread ID, which can be reused.
inline void *tryAllocate(size_t size) noexcept {
    if(size!=24)return nullptr;
    if(tlsIndex==TLS_OUT_OF_INDEXES)return nullptr;
    auto local=tlsValue();
    if(local==(Slot*)1)return nullptr;
    if(!local) {
        for(auto &slot:slots)if(InterlockedCompareExchange(&slot.owner,1,0)==0) {
            for(unsigned n=0;n<Nodes;n++)slot.nodes[n].next=(unsigned short)(n+1);
            if(!TlsSetValue(tlsIndex,&slot)){InterlockedExchange(&slot.owner,0);return nullptr;}
            local=&slot;break;
        }
        if(!local)TlsSetValue(tlsIndex,(void*)1);
    }
    if(!local||local->head==None)return nullptr;
    unsigned n=local->head;local->head=local->nodes[n].next;local->live++;
    return local->nodes[n].bytes;
}
inline bool release(void *pointer) noexcept {
    // A traversal list never leaves its allocating thread. Its node pointers
    // are not passed to callbacks or stored in scene objects. This check uses
    // only that thread's slot and never touches another thread's free list.
    auto local=current();if(!local)return false;
    uintptr_t p=(uintptr_t)pointer,b=(uintptr_t)local->nodes;
    if(p<b||p>=b+sizeof(local->nodes)||(p-b)%sizeof(Node))return false;
    unsigned n=(unsigned)((p-b)/sizeof(Node));
    local->nodes[n].next=(unsigned short)local->head;local->head=n;local->live--;
    return true;
}
inline unsigned outstanding() noexcept {
    // Read only while all other threads are frozen, or joined in tests.
    unsigned total=0;for(auto &slot:slots)total+=slot.live;return total;
}
}
