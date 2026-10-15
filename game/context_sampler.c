/* External x64 Windows-context sampling. No injection or game-memory writes.
 * Only the captured stack and immutable PE sections are used for unwinding.
 * Stack bytes, registers other than code addresses, paths and arguments are
 * never emitted. This executable is a diagnostic, never a scored game run. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <tlhelp32.h>
#include <dbghelp.h>
#include <bcrypt.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAX_MODULES 256
#define MAX_THREADS 256
#define STACK_BYTES 16384
#define MAX_FRAMES 24
typedef struct {
    DWORD64 base; DWORD size; char name[MAX_PATH];
    IMAGE_SECTION_HEADER sections[96]; unsigned nsections;
    RUNTIME_FUNCTION *functions; unsigned count;
} Module;
typedef struct { DWORD tid; HANDLE handle; uint64_t cpu, created, delta; } Thread;
static Module modules[MAX_MODULES]; static unsigned nmodules;
static HANDLE process; static LARGE_INTEGER frequency;
static unsigned char stack[STACK_BYTES]; static DWORD64 stack_base; static SIZE_T stack_size;
static volatile LONG stopping, active, stop_watchdog, resume_failed;
static HANDLE active_thread; static uint64_t active_since;
static uint64_t ticks(void) { LARGE_INTEGER t; QueryPerformanceCounter(&t); return t.QuadPart; }
static uint64_t ft(FILETIME t) { return ((uint64_t)t.dwHighDateTime<<32)|t.dwLowDateTime; }
static uint64_t cpu_time(HANDLE t,uint64_t *created) {
    FILETIME c,e,k,u; if(!GetThreadTimes(t,&c,&e,&k,&u)) return UINT64_MAX;
    if(created) *created=ft(c);
    return ft(k)+ft(u);
}
static void resume_owned(void) {
    if(InterlockedCompareExchange(&active,2,1)!=1) return;
    /* One successful SuspendThread owns exactly one decrement, even when
     * someone else already suspended the thread. Never drain their count. */
    if(ResumeThread(active_thread)==(DWORD)-1) InterlockedExchange(&resume_failed,1);
    InterlockedExchange(&active,0);
}
static DWORD WINAPI watchdog(void *unused) {
    (void)unused;
    while(!stop_watchdog) {
        if(active==1 && ticks()-active_since>(uint64_t)frequency.QuadPart/10) {
            InterlockedExchange(&stopping,1); resume_owned();
        }
        Sleep(1);
    }
    return 0;
}
static BOOL WINAPI cancelled(DWORD signal) { (void)signal; InterlockedExchange(&stopping,1); return TRUE; }
static BOOL read_exact(DWORD64 address,void *out,SIZE_T count) {
    SIZE_T n=0; return ReadProcessMemory(process,(void*)(uintptr_t)address,out,count,&n) && n==count;
}
static Module *module_at(DWORD64 pc) {
    for(unsigned i=0;i<nmodules;i++) if(pc>=modules[i].base && pc-modules[i].base<modules[i].size) return &modules[i];
    return NULL;
}
static BOOL code_at(DWORD64 pc) {
    Module *m=module_at(pc); if(!m) return FALSE;
    DWORD64 rva=pc-m->base;
    for(unsigned i=0;i<m->nsections;i++) {
        IMAGE_SECTION_HEADER *s=&m->sections[i];
        if(rva>=s->VirtualAddress && rva-s->VirtualAddress<s->Misc.VirtualSize && (s->Characteristics&IMAGE_SCN_MEM_EXECUTE)) return TRUE;
    }
    return FALSE;
}
static DWORD64 CALLBACK module_base(HANDLE h,DWORD64 pc) { (void)h; Module *m=module_at(pc); return m?m->base:0; }
static PVOID CALLBACK function_at(HANDLE h,DWORD64 pc) {
    (void)h; Module *m=module_at(pc); if(!m) return NULL;
    DWORD64 rva=pc-m->base; unsigned lo=0,hi=m->count;
    while(lo<hi) { unsigned mid=lo+(hi-lo)/2; if(m->functions[mid].BeginAddress<=rva) lo=mid+1; else hi=mid; }
    if(!lo || rva>=m->functions[lo-1].EndAddress) return NULL;
    return &m->functions[lo-1];
}
static BOOL CALLBACK unwind_read(HANDLE h,DWORD64 address,PVOID out,DWORD count,LPDWORD read) {
    (void)h; *read=0;
    if(address>=stack_base && address-stack_base<=stack_size && count<=stack_size-(address-stack_base)) {
        memcpy(out,stack+(address-stack_base),count); *read=count; return TRUE;
    }
    Module *m=module_at(address); if(!m) return FALSE;
    DWORD64 rva=address-m->base;
    for(unsigned i=0;i<m->nsections;i++) {
        IMAGE_SECTION_HEADER *s=&m->sections[i];
        if(rva>=s->VirtualAddress && rva-s->VirtualAddress<=s->Misc.VirtualSize && count<=s->Misc.VirtualSize-(rva-s->VirtualAddress)
                && !(s->Characteristics&IMAGE_SCN_MEM_WRITE)) {
            if(read_exact(address,out,count)) { *read=count; return TRUE; }
        }
    }
    return FALSE;
}
static int load_modules(DWORD pid) {
    HANDLE snap=CreateToolhelp32Snapshot(TH32CS_SNAPMODULE,pid); if(snap==INVALID_HANDLE_VALUE) return 0;
    MODULEENTRY32 e={0}; e.dwSize=sizeof(e);
    if(Module32First(snap,&e)) do {
        if(nmodules==MAX_MODULES) { CloseHandle(snap); return 0; }
        Module *m=&modules[nmodules]; IMAGE_DOS_HEADER dos; IMAGE_NT_HEADERS64 nt;
        m->base=(DWORD64)(uintptr_t)e.modBaseAddr; m->size=e.modBaseSize;
        if(!read_exact(m->base,&dos,sizeof(dos)) || dos.e_magic!=IMAGE_DOS_SIGNATURE || dos.e_lfanew<0 || (DWORD)dos.e_lfanew>m->size-sizeof(nt)) continue;
        if(!read_exact(m->base+dos.e_lfanew,&nt,sizeof(nt)) || nt.Signature!=IMAGE_NT_SIGNATURE || nt.FileHeader.Machine!=IMAGE_FILE_MACHINE_AMD64 || nt.OptionalHeader.Magic!=IMAGE_NT_OPTIONAL_HDR64_MAGIC || nt.FileHeader.NumberOfSections>96) continue;
        m->nsections=nt.FileHeader.NumberOfSections;
        if(!read_exact(m->base+dos.e_lfanew+24+nt.FileHeader.SizeOfOptionalHeader,m->sections,m->nsections*sizeof(m->sections[0]))) continue;
        strncpy(m->name,e.szModule,sizeof(m->name)-1);
        IMAGE_DATA_DIRECTORY d=nt.OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_EXCEPTION];
        if(d.Size && d.Size<=8*1024*1024 && d.VirtualAddress<m->size && d.Size<=m->size-d.VirtualAddress && d.Size%sizeof(RUNTIME_FUNCTION)==0) {
            m->functions=malloc(d.Size);
            if(!m->functions || !read_exact(m->base+d.VirtualAddress,m->functions,d.Size)) { free(m->functions); m->functions=NULL; }
            else m->count=d.Size/sizeof(RUNTIME_FUNCTION);
        }
        nmodules++;
    } while(Module32Next(snap,&e));
    CloseHandle(snap); return nmodules!=0;
}
static int hash_file(const char *path,char hex[65]) {
    HANDLE f=CreateFileA(path,GENERIC_READ,FILE_SHARE_READ,NULL,OPEN_EXISTING,0,NULL);
    BCRYPT_ALG_HANDLE alg=NULL; BCRYPT_HASH_HANDLE hash=NULL; unsigned char b[65536],digest[32]; DWORD n; int ok=0;
    if(f==INVALID_HANDLE_VALUE) return 0;
    if(BCryptOpenAlgorithmProvider(&alg,BCRYPT_SHA256_ALGORITHM,NULL,0)<0 || BCryptCreateHash(alg,&hash,NULL,0,NULL,0,0)<0) goto done;
    do { if(!ReadFile(f,b,sizeof(b),&n,NULL)) goto done; if(n && BCryptHashData(hash,b,n,0)<0) goto done; } while(n);
    if(BCryptFinishHash(hash,digest,32,0)<0) goto done;
    for(unsigned i=0;i<32;i++) sprintf(hex+2*i,"%02x",digest[i]);
    ok=1;
done:
    if(hash) BCryptDestroyHash(hash);
    if(alg) BCryptCloseAlgorithmProvider(alg,0);
    CloseHandle(f); return ok;
}
static void json_string(const char *s) {
    putchar('"'); for(;*s;s++) { unsigned char c=*s; if(c=='"'||c=='\\') printf("\\%c",c); else if(c>=32&&c<127) putchar(c); else printf("\\u%04x",c); } putchar('"');
}
static void print_frame(DWORD64 pc,int caller) {
    Module *m=module_at(pc); /* Return addresses belong to the preceding call instruction. */
    RUNTIME_FUNCTION *f=function_at(process,caller?pc-1:pc);
    printf("{\"module\":"); json_string(m?m->name:"unknown");
    printf(",\"rva\":%llu,\"function_rva\":",(unsigned long long)(m?pc-m->base:0));
    if(f) printf("%lu",f->BeginAddress); else printf("null");
    if(f && m) {
        unsigned char signature[32]; unsigned length=f->EndAddress-f->BeginAddress; if(length>32) length=32;
        if(read_exact(m->base+f->BeginAddress,signature,length)) {
            printf(",\"signature\":\""); for(unsigned i=0;i<length;i++) printf("%02x",signature[i]); putchar('"');
        }
    }
    putchar('}');
}
static int sample(Thread *t,unsigned ordinal,const char *fault) {
    CONTEXT context; memset(&context,0,sizeof(context)); context.ContextFlags=CONTEXT_FULL;
    uint64_t start=ticks(),cpu=cpu_time(t->handle,NULL); stack_size=0;
    active_thread=t->handle; active_since=start;
    DWORD previous=SuspendThread(t->handle);
    if(previous==(DWORD)-1) return 0;
    InterlockedExchange(&active,1);
    BOOL got=FALSE,read=FALSE;
    /* Do not allocate, log, unwind or call any target-process code here. */
    if(fault && !strcmp(fault,"timeout")) Sleep(150);
    if(!stopping && !(fault && !strcmp(fault,"context"))) got=GetThreadContext(t->handle,&context);
    if(got && !(fault && !strcmp(fault,"read"))) {
        stack_base=context.Rsp; SIZE_T bytes=STACK_BYTES-(context.Rsp&4095);
        read=ReadProcessMemory(process,(void*)(uintptr_t)stack_base,stack,bytes,&stack_size);
        if(!read) stack_size=0;
    }
    LONG was_active=active; resume_owned();
    while(active==2) Sleep(0);
    uint64_t end=ticks();
    if(resume_failed) return -1;
    uint64_t delta=cpu!=UINT64_MAX && cpu>=t->cpu?cpu-t->cpu:0; if(cpu!=UINT64_MAX) t->cpu=cpu;
    printf("{\"kind\":\"sample\",\"ordinal\":%u,\"tid\":%lu,\"qpc\":%llu,\"cpu_delta_100ns\":%llu,\"previous_suspend_count\":%lu,\"suspension_us\":%llu,\"context_valid\":%s,\"stack_captured\":%s,\"frames\":[",
        ordinal,t->tid,(unsigned long long)start,(unsigned long long)delta,previous,(unsigned long long)((end-start)*1000000/frequency.QuadPart),got && was_active==1 && !stopping?"true":"false",read?"true":"false");
    if(got && was_active==1 && !stopping && code_at(context.Rip)) {
        print_frame(context.Rip,0);
        STACKFRAME64 frame; memset(&frame,0,sizeof(frame));
        frame.AddrPC.Offset=context.Rip; frame.AddrPC.Mode=AddrModeFlat;
        frame.AddrStack.Offset=context.Rsp; frame.AddrStack.Mode=AddrModeFlat;
        frame.AddrFrame.Offset=context.Rbp; frame.AddrFrame.Mode=AddrModeFlat;
        DWORD64 last_pc=context.Rip,last_sp=context.Rsp;
        if(read) for(unsigned i=0;i<MAX_FRAMES;i++) {
            if(!StackWalk64(IMAGE_FILE_MACHINE_AMD64,process,t->handle,&frame,&context,unwind_read,function_at,module_base,NULL)) break;
            DWORD64 pc=frame.AddrPC.Offset,sp=frame.AddrStack.Offset;
            if(pc==last_pc && sp==last_sp) continue; /* StackWalk64's first frame is the current PC. */
            if(!code_at(pc) || sp<=last_sp || sp-stack_base>=stack_size) break;
            putchar(','); print_frame(pc,1); last_pc=pc; last_sp=sp;
        }
    }
    puts("]}"); SecureZeroMemory(stack,sizeof(stack)); return 1;
}
static int compare_cpu(const void *a,const void *b) {
    const Thread *x=a,*y=b; return x->delta<y->delta?1:x->delta>y->delta?-1:0;
}
int main(int argc,char **argv) {
    DWORD pid=0,only_tid=0; unsigned seconds=5; const char *expected=NULL,*fault=NULL; int test=0;
    for(int i=1;i<argc;i++) {
        if(!strcmp(argv[i],"--test-target")) test=1;
        else if(i+1<argc && !strcmp(argv[i],"--pid")) pid=strtoul(argv[++i],NULL,10);
        else if(i+1<argc && !strcmp(argv[i],"--tid")) only_tid=strtoul(argv[++i],NULL,10);
        else if(i+1<argc && !strcmp(argv[i],"--seconds")) seconds=strtoul(argv[++i],NULL,10);
        else if(i+1<argc && !strcmp(argv[i],"--expected")) expected=argv[++i];
        else if(i+1<argc && !strcmp(argv[i],"--fault") && test) fault=argv[++i];
        else return 2;
    }
    if(!expected || strlen(expected)!=64 || seconds<1 || seconds>10) return 2;
    QueryPerformanceFrequency(&frequency);
    if(!pid) {
        HANDLE snap=CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS,0); PROCESSENTRY32 e={0}; e.dwSize=sizeof(e); unsigned matches=0;
        if(Process32First(snap,&e)) do { if(!_stricmp(e.szExeFile,test?"context_target.exe":"WizardGraphicalClient.exe")) { pid=e.th32ProcessID; matches++; } } while(Process32Next(snap,&e));
        CloseHandle(snap); if(matches!=1) { fputs("Expected one target in this prefix.\n",stderr); return 3; }
    }
    process=OpenProcess(PROCESS_QUERY_INFORMATION|PROCESS_VM_READ,FALSE,pid); if(!process) return 4;
    char path[32768],hex[65]; DWORD len=sizeof(path);
    if(!QueryFullProcessImageNameA(process,0,path,&len) || !hash_file(path,hex) || strcmp(hex,expected)) { fputs("Executable hash mismatch; no thread suspended.\n",stderr); CloseHandle(process); return 5; }
    const char *name=strrchr(path,'\\'); name=name?name+1:path;
    if(_stricmp(name,test?"context_target.exe":"WizardGraphicalClient.exe")) { CloseHandle(process); return 5; }
    if(!load_modules(pid)) { CloseHandle(process); return 6; }
    Thread threads[MAX_THREADS]; unsigned count=0;
    HANDLE snap=CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD,0); THREADENTRY32 e={0}; e.dwSize=sizeof(e);
    if(Thread32First(snap,&e)) do {
        if(e.th32OwnerProcessID!=pid || (only_tid && e.th32ThreadID!=only_tid)) continue;
        if(count==MAX_THREADS) { CloseHandle(snap); return 7; }
        HANDLE h=OpenThread(THREAD_QUERY_INFORMATION|THREAD_GET_CONTEXT|THREAD_SUSPEND_RESUME,FALSE,e.th32ThreadID);
        if(h) { Thread *t=&threads[count]; t->handle=h; t->tid=e.th32ThreadID; t->cpu=cpu_time(h,&t->created); t->delta=0; count++; }
    } while(Thread32Next(snap,&e)); CloseHandle(snap);
    if(!count) return 8;
    Sleep(250);
    unsigned initial=0; for(unsigned i=0;i<count;i++) {
        uint64_t current=cpu_time(threads[i].handle,NULL);
        threads[i].delta=current!=UINT64_MAX && threads[i].cpu!=UINT64_MAX && current>=threads[i].cpu?current-threads[i].cpu:0;
        if(current!=UINT64_MAX) threads[i].cpu=current;
        if(threads[i].created<threads[initial].created) initial=i;
    }
    DWORD earliest=threads[initial].tid; qsort(threads,count,sizeof(*threads),compare_cpu);
    unsigned selected=count>4?4:count;
    /* Always retain the earliest extant thread as a lead, never call it the main thread without corroboration. */
    for(unsigned i=selected;i<count;i++) if(threads[i].tid==earliest) { Thread temp=threads[selected-1]; threads[selected-1]=threads[i]; threads[i]=temp; break; }
    SetConsoleCtrlHandler(cancelled,TRUE);
    HANDLE guard=CreateThread(NULL,0,watchdog,NULL,0,NULL); if(!guard) return 9;
    uint64_t observed_cpu=0; for(unsigned i=0;i<count;i++) observed_cpu+=threads[i].delta;
    uint64_t clock_begin=ticks(); FILETIME wall; GetSystemTimePreciseAsFileTime(&wall); uint64_t clock_end=ticks();
    printf("{\"kind\":\"session\",\"schema\":1,\"windows_pid\":%lu,\"executable_sha256\":\"%s\",\"qpc_frequency\":%llu,\"clock_qpc\":%llu,\"clock_unix_us\":%llu,\"clock_bracket_us\":%llu,\"diagnostic_only\":true,\"cpu_clock_observed_advancing\":%s,\"seconds\":%u,\"interval_ms\":50,\"stack_max_bytes\":%u,\"earliest_extant_tid\":%lu,\"threads\":[",pid,hex,(unsigned long long)frequency.QuadPart,(unsigned long long)((clock_begin+clock_end)/2),(unsigned long long)(ft(wall)/10-11644473600000000ULL),(unsigned long long)((clock_end-clock_begin)*1000000/frequency.QuadPart),observed_cpu?"true":"false",seconds,STACK_BYTES,earliest);
    for(unsigned i=0;i<selected;i++) printf("%s%lu",i?",":"",threads[i].tid);
    puts("]}");
    uint64_t begin=ticks(),deadline=begin+seconds*frequency.QuadPart; unsigned ordinal=0; int failed=0;
    while(ticks()<deadline && !stopping && !ferror(stdout)) {
        uint64_t cycle=ticks();
        for(unsigned i=0;i<selected && !stopping;i++) if(sample(&threads[i],ordinal++,fault)<0) { failed=1; InterlockedExchange(&stopping,1); break; }
        uint64_t elapsed=(ticks()-cycle)*1000/frequency.QuadPart; if(elapsed<50) Sleep((DWORD)(50-elapsed));
    }
    resume_owned(); InterlockedExchange(&stop_watchdog,1); WaitForSingleObject(guard,INFINITE); CloseHandle(guard);
    printf("{\"kind\":\"end\",\"samples_attempted\":%u,\"cancelled\":%s,\"resume_failed\":%s,\"completed\":%s}\n",ordinal,stopping?"true":"false",resume_failed?"true":"false",!stopping && !failed && !ferror(stdout)?"true":"false");
    for(unsigned i=0;i<count;i++) CloseHandle(threads[i].handle);
    for(unsigned i=0;i<nmodules;i++) free(modules[i].functions);
    CloseHandle(process); return failed || resume_failed || ferror(stdout)?10:stopping?11:0;
}
