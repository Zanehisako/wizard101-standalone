#include <windows.h>
#include <excpt.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <initializer_list>
#include "../game/scene_nodes.h"

// Private PE mapping. Its entrypoint is never called. Execute the actual scene
// traversal and native FH4 cleanup with controlled scene objects and callbacks.
static unsigned char *base;
static void *(*crtMalloc)(size_t);
static void (*crtFree)(void*);
static volatile LONG heapLive,heapCalls;
static thread_local int failAfter=-1;
static void *testMalloc(size_t n) {
    if(n==24) {
        InterlockedIncrement(&heapCalls);
        if(failAfter==0)return nullptr;
        if(failAfter>0)failAfter--;
    }
    void *p=crtMalloc(n);if(p&&n==24)InterlockedIncrement(&heapLive);return p;
}
static void testFree(void *p) {if(p)InterlockedDecrement(&heapLive);crtFree(p);}
static int noNewHandler(size_t) {return 0;}
static void throwBridge(void *object,void *info) {
    // Preserve the compiler's original exception object and ThrowInfo. Supply
    // the private mapped image base explicitly, since it has no loader entry.
    ULONG_PTR args[]={0x19930520,(ULONG_PTR)object,(ULONG_PTR)info,(ULONG_PTR)base};
    RaiseException(0xe06d7363,EXCEPTION_NONCONTINUABLE,4,args);abort();
}
static bool mapImage(const char *path) {
    FILE *f=fopen(path,"rb");if(!f)return false;
    fseek(f,0,SEEK_END);long length=ftell(f);rewind(f);
    auto raw=(unsigned char*)malloc(length);bool ok=fread(raw,1,length,f)==(size_t)length;fclose(f);if(!ok)return false;
    auto dos=(IMAGE_DOS_HEADER*)raw;auto nt=(IMAGE_NT_HEADERS64*)(raw+dos->e_lfanew);
    base=(unsigned char*)VirtualAlloc(nullptr,nt->OptionalHeader.SizeOfImage,MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE);if(!base)return false;
    memcpy(base,raw,nt->OptionalHeader.SizeOfHeaders);
    auto sections=IMAGE_FIRST_SECTION(nt);
    for(unsigned i=0;i<nt->FileHeader.NumberOfSections;i++)memcpy(base+sections[i].VirtualAddress,raw+sections[i].PointerToRawData,sections[i].SizeOfRawData);
    // These verified functions contain only relative references. No entrypoint,
    // scene constructors, static initializers or arbitrary game DLLs execute.
    auto dir=nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    auto descriptors=(IMAGE_IMPORT_DESCRIPTOR*)(base+dir.VirtualAddress);
    for(auto d=descriptors;d->Name;d++) {
        const char *name=(const char*)base+d->Name;
        bool needed=strstr(name,"VCRUNTIME")||strstr(name,"crt-")||!strcmp(name,"KERNEL32.dll")||!strcmp(name,"MSVCP140.dll");
        if(!needed)continue;
        HMODULE module=LoadLibraryA(name);if(!module)return false;
        auto lookup=(IMAGE_THUNK_DATA64*)(base+d->OriginalFirstThunk),iat=(IMAGE_THUNK_DATA64*)(base+d->FirstThunk);
        for(unsigned i=0;lookup[i].u1.AddressOfData;i++) {
            FARPROC address;
            if(IMAGE_SNAP_BY_ORDINAL64(lookup[i].u1.Ordinal))address=GetProcAddress(module,(LPCSTR)IMAGE_ORDINAL64(lookup[i].u1.Ordinal));
            else address=GetProcAddress(module,(LPCSTR)((IMAGE_IMPORT_BY_NAME*)(base+lookup[i].u1.AddressOfData))->Name);
            if(!address)return false;
            iat[i].u1.Function=(ULONGLONG)address;
        }
    }
    crtMalloc=(decltype(crtMalloc))*(void**)(base+0x2954f88);crtFree=(decltype(crtFree))*(void**)(base+0x2954f80);
    *(void**)(base+0x2954f88)=(void*)&testMalloc;*(void**)(base+0x2954f80)=(void*)&testFree;
    *(void**)(base+0x2954c88)=(void*)&throwBridge;
    // The original allocator's new-handler thunk is identified from its import.
    auto thunk=base+0x24592aa;int32_t disp;memcpy(&disp,thunk+2,4);*(void**)(thunk+6+disp)=(void*)&noNewHandler;
    *(void**)(base+0x3447a00)=nullptr; // end the controlled RTTI ancestry chain
    dir=nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_EXCEPTION];
    bool registered=RtlAddFunctionTable((RUNTIME_FUNCTION*)(base+dir.VirtualAddress),dir.Size/sizeof(RUNTIME_FUNCTION),(DWORD64)base)!=0;
    for(unsigned i=0;i<nt->FileHeader.NumberOfSections;i++) {
        DWORD ignored,flags=sections[i].Characteristics;
        DWORD protection=flags&IMAGE_SCN_MEM_EXECUTE?PAGE_EXECUTE_READ:flags&IMAGE_SCN_MEM_WRITE?PAGE_READWRITE:PAGE_READONLY;
        if(!VirtualProtect(base+sections[i].VirtualAddress,sections[i].Misc.VirtualSize,protection,&ignored))return false;
    }
    free(raw);return registered;
}
struct Scene { alignas(16) unsigned char bytes[512]; };
static void *vtable[3];
static thread_local unsigned events[65536],eventCount,throwAt;
static thread_local bool record=true,recurse=false,inside=false,caught;
static Scene recursiveScene;
using Traverse=void(*)(void*,void*,float);
static Traverse traverse;
static unsigned char allString[32]={'A','L','L'};
static void invoke(Scene *scene) {traverse(scene,allString,1.0f);}
static void *getter(Scene *s) {
    unsigned id;memcpy(&id,s->bytes+0x180,4);
    if(record) {if(eventCount==65536)abort();events[eventCount++]=id;}
    if(throwAt&&eventCount==throwAt)((void(*)())(base+0x2458fc4))();
    if(recurse&&!inside) {inside=true;invoke(&recursiveScene);inside=false;}
    return base+0x34479f8;
}
extern "C" int sceneCatch(EXCEPTION_POINTERS *p,void*) {
    if(p->ExceptionRecord->ExceptionCode!=0xe06d7363)return EXCEPTION_CONTINUE_SEARCH;
    caught=true;return EXCEPTION_EXECUTE_HANDLER;
}
static __attribute__((noinline)) bool protectedInvoke(Scene *s) {
    caught=false;
    __try1(sceneCatch)
    invoke(s);
    __except1
    return caught;
}
static Scene scenes[1024];static Scene *children[1024];
static void setup(unsigned n,bool wide) {
    memset(scenes,0,sizeof(scenes));memset(&recursiveScene,0,sizeof(recursiveScene));
    *(void***)recursiveScene.bytes=vtable;unsigned id=65535;memcpy(recursiveScene.bytes+0x180,&id,4);
    for(unsigned i=0;i<n;i++) {*(void***)scenes[i].bytes=vtable;memcpy(scenes[i].bytes+0x180,&i,4);children[i]=scenes+i;}
    if(wide&&n>1) {*(Scene***)(scenes[0].bytes+0xe8)=children+1;*(uint16_t*)(scenes[0].bytes+0xf2)=(uint16_t)(n-1);}
    if(!wide)for(unsigned i=0;i+1<n;i++){*(Scene***)(scenes[i].bytes+0xe8)=children+i+1;*(uint16_t*)(scenes[i].bytes+0xf2)=1;}
    eventCount=0;throwAt=0;failAfter=-1;
}
static double benchmark(unsigned repeats) {
    LARGE_INTEGER start,end,hz;QueryPerformanceFrequency(&hz);record=false;
    for(unsigned i=0;i<100;i++)invoke(scenes);
    QueryPerformanceCounter(&start);for(unsigned i=0;i<repeats;i++)invoke(scenes);QueryPerformanceCounter(&end);record=true;
    return double(end.QuadPart-start.QuadPart)*1e9/hz.QuadPart/repeats;
}
static volatile LONG stop,incorrect,concurrentCalls;
static DWORD WINAPI worker(void*) {
    record=false;
    while(!stop) {invoke(scenes);auto slot=w101scene::current();if(slot&&slot->live)InterlockedIncrement(&incorrect);InterlockedIncrement(&concurrentCalls);}
    return 0;
}
int main(int argc,char **argv) {
    if(argc!=2||!mapImage(argv[1])){puts("{\"setup_failed\":true}");return 2;}
    traverse=(Traverse)(base+0x19c8ee0);vtable[2]=(void*)&getter;*(uint64_t*)(allString+16)=3;*(uint64_t*)(allString+24)=15;
    bool pass=true;const char *names[48];bool values[48];unsigned checks=0;
    auto check=[&](const char *n,bool v){names[checks]=n;values[checks++]=v;pass&=v;};
    check("mapped_original_identities",w101scene::verifyImage(base));
    SetEnvironmentVariableA("W101_SCENE_NODES","0");SetLastError(0x4512);check("default_off",!w101scene::install()&&GetLastError()==0x4512&&!w101scene::prepared);
    SetEnvironmentVariableA("W101_SCENE_NODES","1");check("unapproved_executable_rejected",!w101scene::install()&&!w101scene::prepared);
    check("prepare",w101scene::prepare(base));
    setup(100,true);invoke(scenes);eventCount=0;SetLastError(0x945);invoke(scenes);DWORD originalError=GetLastError();check("baseline_executes_and_cleans",eventCount==200&&heapLive==0);
    unsigned reference[65536],referenceCount=eventCount;memcpy(reference,events,eventCount*4);unsigned char state[sizeof(scenes)];memcpy(state,scenes,sizeof(scenes));
    check("activation",w101scene::installVerifiedImage(base));
    eventCount=0;SetLastError(0x945);invoke(scenes);
    check("identical_state_and_callbacks",eventCount==referenceCount&&!memcmp(reference,events,eventCount*4)&&!memcmp(state,scenes,sizeof(scenes))&&heapLive==0&&w101scene::outstanding()==0);
    check("last_error_equivalent_to_original",GetLastError()==originalError);
    LONG before=heapCalls;eventCount=0;invoke(scenes);check("pool_reuses_and_is_bounded",heapCalls==before&&sizeof(w101scene::slots)<1024*1024&&w101scene::current()->live==0);
    check("rollback",w101scene::disable()&&w101scene::verifyImage(base));
    bool recursionOk=true;
    setup(8,false);recurse=true;invoke(scenes);referenceCount=eventCount;memcpy(reference,events,eventCount*4);
    recursionOk&=w101scene::installVerifiedImage(base);eventCount=0;invoke(scenes);
    recursionOk&=eventCount==referenceCount&&!memcmp(reference,events,eventCount*4)&&!w101scene::outstanding()&&!heapLive;
    recurse=false;check("recursive_callback_order",recursionOk);
    // Exercise the original MSVC allocation throw and FH4 unwind, including
    // state 0 list cleanup, the two insertion guards and nested callbacks.
    bool exceptions=true;
    for(unsigned selected=0;selected<2;selected++) {
        exceptions&=selected?w101scene::installVerifiedImage(base):w101scene::disable();
        for(unsigned point=1;point<=20;point++) {setup(20,true);throwAt=point;exceptions&=protectedInvoke(scenes)&&heapLive==0&&w101scene::outstanding()==0;}
    }
    check("native_fh4_callback_exceptions",exceptions);
    setup(600,true);check("exhaustion_activation",w101scene::installVerifiedImage(base));before=heapCalls;invoke(scenes);
    check("node_exhaustion_original_fallback",heapCalls>before&&!heapLive&&!w101scene::outstanding());
    setup(600,true);failAfter=0;check("exhausted_allocator_failure_unwinds",protectedInvoke(scenes)&&!heapLive&&!w101scene::outstanding());failAfter=-1;
    check("allocation_failure_rollback",w101scene::disable());
    bool failuresOk=true;
    for(int point=0;point<20;point++){setup(20,true);failAfter=point;failuresOk&=protectedInvoke(scenes)&&!heapLive&&!w101scene::outstanding();}
    failAfter=-1;check("original_allocation_failures",failuresOk);
    setup(16,true);HANDLE threads[4];for(auto &thread:threads)thread=CreateThread(nullptr,0,worker,nullptr,0,nullptr);
    Sleep(20);
    bool faultsOk=true;
    for(unsigned fault: {1u,2u,10u,11u,12u,13u,14u,15u,16u,17u,18u}) {
        w101scene::transactionFault=fault;bool rejected=!w101scene::installVerifiedImage(base)&&w101scene::verifyImage(base);
        faultsOk&=rejected;
    }
    w101scene::transactionFault=0;check("partial_commit_and_freeze_failures_restore_every_byte",faultsOk);
    check("concurrent_activation",w101scene::installVerifiedImage(base));Sleep(40);
    InterlockedExchange(&stop,1);bool joined=WaitForMultipleObjects(4,threads,TRUE,10000)==WAIT_OBJECT_0;
    for(auto thread:threads)CloseHandle(thread);
    check("concurrency_shutdown",joined&&!incorrect&&concurrentCalls>100&&!heapLive&&!w101scene::outstanding());
    // Rollback is refused while this thread owns a pooled node.
    void *held=w101scene::tryAllocate(24);check("live_nodes_prevent_unsafe_rollback",held&&!w101scene::disable());w101scene::release(held);
    check("byte_exact_final_rollback",w101scene::disable()&&w101scene::verifyImage(base));
    printf("{\"checks\":{");for(unsigned i=0;i<checks;i++)printf("%s\"%s\":%s",i?",":"",names[i],values[i]?"true":"false");
    printf("},\"heap_live\":%ld,\"concurrent_calls\":%ld,\"pool_bytes\":%zu,\"benchmarks_ns\":[",heapLive,concurrentCalls,sizeof(w101scene::slots));
    unsigned sizes[]={16,128,600};bool first=true;
    for(unsigned n:sizes)for(unsigned pair=0;pair<5;pair++) {
        setup(n,true);double off,on;
        if(pair&1){pass&=w101scene::installVerifiedImage(base);on=benchmark(3000);pass&=w101scene::disable();off=benchmark(3000);}
        else {pass&=w101scene::disable();off=benchmark(3000);pass&=w101scene::installVerifiedImage(base);on=benchmark(3000);}
        printf("%s{\"size\":%u,\"pair\":%u,\"original\":%.3f,\"candidate\":%.3f}",first?"":",",n,pair,off,on);first=false;
    }
    pass&=w101scene::disable();printf("],\"fallback_pairs_ns\":[");
    auto savedSlot=w101scene::current();TlsSetValue(w101scene::tlsIndex,(void*)1);
    setup(128,true);
    for(unsigned pair=0;pair<5;pair++) {
        double off,on;
        if(pair&1){pass&=w101scene::installVerifiedImage(base);on=benchmark(3000);pass&=w101scene::disable();off=benchmark(3000);}
        else {pass&=w101scene::disable();off=benchmark(3000);pass&=w101scene::installVerifiedImage(base);on=benchmark(3000);}
        printf("%s{\"pair\":%u,\"original\":%.3f,\"candidate\":%.3f}",pair?",":"",pair,off,on);
    }
    TlsSetValue(w101scene::tlsIndex,savedSlot);pass&=w101scene::disable();printf("],\"passed\":%s}\n",pass?"true":"false");return pass?0:7;
}
