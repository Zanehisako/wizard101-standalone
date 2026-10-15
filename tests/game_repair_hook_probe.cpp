#include <windows.h>
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include "../game/repair.h"
extern "C" volatile LONG w101_minhook_fault;
struct Item {unsigned char pad[16];uint64_t name;};
struct Object {unsigned char pad[32];Item**array;uint16_t count;};
static Item items[256];static Item*array[256];static Object object{};
static unsigned char *base;
static volatile LONG stop,failures,calls;
static DWORD WINAPI worker(void*) {
    auto target=(W101Lookup)(base+w101repair::LookupRVA);
    while(!stop)for(unsigned i=0;i<16;i++) {uint64_t key=i*4;
        if(target(&object,&key)!=items+i)InterlockedIncrement(&failures);
        InterlockedIncrement(&calls);}
    return 0;
}
static double benchmark(W101Lookup function,unsigned count,bool miss) {
    LARGE_INTEGER begin,end,hz;QueryPerformanceFrequency(&hz);QueryPerformanceCounter(&begin);
    void *observed=nullptr;
    for(unsigned i=0;i<count;i++){uint64_t key=(i%object.count)*4+(miss?1:0);observed=function(&object,&key);}
    QueryPerformanceCounter(&end);void*volatile keep=observed;(void)keep;
    return(double)(end.QuadPart-begin.QuadPart)*1e9/hz.QuadPart/count;
}
int main(int argc,char**argv) {
    if(argc!=2)return 2;
    FILE*f=fopen(argv[1],"rb");if(!f)return 3;
    unsigned char raw[1024];size_t size=fread(raw,1,sizeof(raw),f);fclose(f);
    if(size<=164||size>=sizeof(raw))return 4;
    base=(unsigned char*)VirtualAlloc(nullptr,0x3000000,MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE);if(!base)return 5;
    memcpy(base+w101repair::LookupRVA,raw,164);
    const unsigned char getter[]={0x48,0x8d,0x41,0x10,0xc3};memcpy(base+w101repair::GetterRVA,getter,5);
    uint64_t empty=UINT64_C(0xaabbbbbbbbbbbbbb);memcpy(base+w101repair::EmptyRVA,&empty,8);
    memcpy(base+0x2e00000,raw+164,size-164);
    DWORD old;VirtualProtect(base,0x3000000,PAGE_EXECUTE_READ,&old);
    RUNTIME_FUNCTION original{};original.BeginAddress=w101repair::LookupRVA;original.EndAddress=original.BeginAddress+164;original.UnwindData=0x2e00000;
    bool checks[14]{};
    checks[0]=RtlAddFunctionTable(&original,1,(DWORD64)base);
    for(unsigned i=0;i<256;i++){items[i].name=i*4;array[i]=items+i;}object.array=array;object.count=16;
    auto target=(W101Lookup)(base+w101repair::LookupRVA);uint64_t key=20;
    SetEnvironmentVariableA("W101_GAME_REPAIR","0");SetLastError(0x1901);
    checks[1]=!w101repair::install()&&GetLastError()==0x1901&&!w101repair::created;
    SetEnvironmentVariableA("W101_GAME_REPAIR","1");SetLastError(0x1902);
    checks[2]=!w101repair::install()&&GetLastError()==0x1902&&!w101repair::created; // fixture EXE is unapproved
    VirtualProtect(base+w101repair::LookupRVA,164,PAGE_EXECUTE_READWRITE,&old);base[w101repair::LookupRVA+30]^=1;
    checks[3]=!w101repair::installVerifiedImage(base)&&!w101repair::created;
    base[w101repair::LookupRVA+30]^=1;VirtualProtect(base+w101repair::LookupRVA,164,old,&old);
    VirtualProtect(base+w101repair::GetterRVA,5,PAGE_EXECUTE_READWRITE,&old);base[w101repair::GetterRVA+4]^=1;
    checks[4]=!w101repair::installVerifiedImage(base)&&!w101repair::created;
    base[w101repair::GetterRVA+4]^=1;VirtualProtect(base+w101repair::GetterRVA,5,old,&old);
    HANDLE threads[4];for(auto &thread:threads)thread=CreateThread(nullptr,0,worker,nullptr,0,nullptr);
    Sleep(20);
    for(unsigned fault=1;fault<=3;fault++) {
        w101_minhook_fault=(LONG)fault;
        checks[4+fault]=!w101repair::installVerifiedImage(base)&&!w101repair::enabled&&target(&object,&key)==items+5;
    }
    w101_minhook_fault=0;
    checks[8]=w101repair::installVerifiedImage(base)&&w101repair::enabled&&target(&object,&key)==items+5;
    SetLastError(0x29101);target(&object,&key);checks[9]=GetLastError()==0x29101;
    // A thread redirected to the original 5-byte prologue remains unwindable.
    uint64_t stack[4]={UINT64_C(0x12345678),UINT64_C(0xaabbccdd),0,0};CONTEXT context{};
    // MOV [RSP+8],RBX saves RBX without changing it. At the following tail jump,
    // the real register still equals that saved value; a zero register with a
    // nonzero saved value is not an execution state of this trampoline.
    context.Rip=(DWORD64)w101repair::trampoline+5;context.Rsp=(DWORD64)stack;context.Rbx=stack[1];
    PVOID handler=nullptr;DWORD64 establisher=0;
    RtlVirtualUnwind(UNW_FLAG_NHANDLER,(DWORD64)w101repair::trampoline,context.Rip,&w101repair::trampolineUnwind,&context,&handler,&establisher,nullptr);
    checks[10]=context.Rbx==stack[1]&&context.Rip==stack[0]&&context.Rsp==(DWORD64)(stack+1);
    DWORD64 unwindBase=0;
    checks[10]=checks[10]&&RtlLookupFunctionEntry((DWORD64)w101repair::trampoline+5,&unwindBase,nullptr)==&w101repair::trampolineUnwind&&unwindBase==(DWORD64)w101repair::trampoline;
    bool transitions=true;
    for(unsigned i=0;i<60;i++) {transitions=transitions&&w101repair::disable();transitions=transitions&&w101repair::installVerifiedImage(base);}
    checks[11]=transitions&&!failures;
    DWORD prior=SuspendThread(threads[0]);bool disabled=w101repair::disable();bool enabled=w101repair::installVerifiedImage(base);
    checks[12]=prior==0&&disabled&&enabled&&ResumeThread(threads[0])==1;
    bool restored=w101repair::disable();InterlockedExchange(&stop,1);
    DWORD joined=WaitForMultipleObjects(4,threads,TRUE,10000);for(auto thread:threads)CloseHandle(thread);
    checks[13]=joined==WAIT_OBJECT_0&&restored&&!failures&&!memcmp(base+w101repair::LookupRVA,raw,164)&&calls>100;
    const char *names[]={"fixture_unwind","default_off","exe_hash_rejection_last_error","function_signature_rejection","getter_signature_rejection","context_failure_restores","timeout_restores","suspend_failure_restores","activation","last_error_preserved","trampoline_unwind","concurrent_activation_rollback","other_suspend_owner_preserved","byte_exact_rollback_shutdown"};
    bool passed=true;printf("{\"checks\":{");for(unsigned i=0;i<14;i++){printf("%s\"%s\":%s",i?",":"",names[i],checks[i]?"true":"false");passed=passed&&checks[i];}
    printf("},\"calls\":%ld,\"incorrect_results\":%ld,\"hook_benchmarks_ns\":[",calls,failures);
    unsigned sizes[]={4,16,64,256};
    for(unsigned s=0;s<4;s++)for(unsigned miss=0;miss<2;miss++)for(unsigned pair=0;pair<5;pair++) {
        object.count=(uint16_t)sizes[s];double orig,patch;
        if(pair&1){passed=passed&&w101repair::installVerifiedImage(base);patch=benchmark(target,400000,miss);passed=passed&&w101repair::disable();orig=benchmark(target,400000,miss);}
        else {passed=passed&&w101repair::disable();orig=benchmark(target,400000,miss);passed=passed&&w101repair::installVerifiedImage(base);patch=benchmark(target,400000,miss);}
        printf("%s{\"size\":%u,\"miss\":%s,\"original\":%.3f,\"candidate\":%.3f}",s||miss||pair?",":"",sizes[s],miss?"true":"false",orig,patch);
    }
    passed=passed&&w101repair::disable();
    printf("],\"passed\":%s}\n",passed?"true":"false");
    // Allocations and unwind registrations deliberately remain until process
    // exit, exactly as production; no unsafe freeing under a live callback.
    return passed?0:7;
}
