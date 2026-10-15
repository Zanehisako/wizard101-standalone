#pragma once
#include <windows.h>
#include <tlhelp32.h>
#include <string.h>

namespace w101scene {
struct Patch { unsigned char *address; unsigned size; unsigned char before[5],after[5]; };
struct Page { unsigned char *address; DWORD protection; };
inline SRWLOCK transactionLock=SRWLOCK_INIT;
#ifdef W101_SCENE_VERIFY
inline unsigned transactionFault=0;
#endif
// There are nine edits on three pages. All resources are acquired before
// suspension. No allocator, callback, heap operation or logging runs frozen.
inline bool transact(Patch *patches,unsigned count,bool enable) noexcept {
    AcquireSRWLockExclusive(&transactionLock);
    HANDLE handles[1024]{};unsigned threads=0;
    Page pages[16]{};unsigned pageCount=0,writable=0;
    bool ok=false,changed=false;ULONGLONG start=0;
    HANDLE snapshot=CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD,0);
    if(snapshot==INVALID_HANDLE_VALUE)goto done;
    {
        THREADENTRY32 row{};row.dwSize=sizeof(row);
        if(!Thread32First(snapshot,&row))goto done;
        do {
            if(row.th32OwnerProcessID==GetCurrentProcessId()&&row.th32ThreadID!=GetCurrentThreadId()) {
                if(threads==1024)goto done;
                HANDLE h=OpenThread(THREAD_SUSPEND_RESUME|THREAD_GET_CONTEXT|THREAD_QUERY_INFORMATION,FALSE,row.th32ThreadID);
                if(!h) {if(GetLastError()==ERROR_INVALID_PARAMETER)continue;goto done;}
                handles[threads++]=h;
            }
            row.dwSize=sizeof(row);
        }while(Thread32Next(snapshot,&row));
        if(GetLastError()!=ERROR_NO_MORE_FILES)goto done;
    }
    CloseHandle(snapshot);snapshot=INVALID_HANDLE_VALUE;
    for(unsigned i=0;i<count;i++) {
        auto &p=patches[i];if(!p.size||p.size>5)goto done;
        uintptr_t first=(uintptr_t)p.address&~uintptr_t(4095),last=((uintptr_t)p.address+p.size-1)&~uintptr_t(4095);
        for(uintptr_t a=first;a<=last;a+=4096) {
            bool found=false;for(unsigned j=0;j<pageCount;j++)if((uintptr_t)pages[j].address==a)found=true;
            if(!found) {if(pageCount==16)goto done;pages[pageCount++].address=(unsigned char*)a;}
        }
    }
    // Protection changes precede suspension; content stays original.
    for(;writable<pageCount;writable++)if(!VirtualProtect(pages[writable].address,4096,PAGE_EXECUTE_READWRITE,&pages[writable].protection))goto done;
    start=GetTickCount64();
    for(unsigned i=0;i<threads;i++) {
        if(SuspendThread(handles[i])==(DWORD)-1) {
            for(unsigned j=i;j<threads;j++){CloseHandle(handles[j]);handles[j]=nullptr;}
            threads=i;goto done;
        }
        CONTEXT context{};context.ContextFlags=CONTEXT_CONTROL;
        bool valid=GetThreadContext(handles[i],&context)!=0;
#ifdef W101_SCENE_VERIFY
        if(transactionFault==1)valid=false;
        if(transactionFault==2)valid=false; // freeze deadline failure, without sleeping
#endif
        if(valid)for(unsigned j=0;j<count;j++) {
            uintptr_t ip=(uintptr_t)context.Rip,a=(uintptr_t)patches[j].address;
            if(ip>=a&&ip<a+patches[j].size)valid=false;
        }
        if(!valid||GetTickCount64()-start>50) {
            for(unsigned j=i+1;j<threads;j++){CloseHandle(handles[j]);handles[j]=nullptr;}
            threads=i+1;goto done;
        }
    }
    if(!enable&&outstanding())goto done; // cleanup must remain reachable
    for(unsigned i=0;i<count;i++)if(memcmp(patches[i].address,enable?patches[i].before:patches[i].after,patches[i].size))goto done;
    for(unsigned i=0;i<count;i++) {
        memcpy(patches[i].address,enable?patches[i].after:patches[i].before,patches[i].size);changed=true;
#ifdef W101_SCENE_VERIFY
        if(transactionFault==10+i)goto done;
#endif
    }
    if(!FlushInstructionCache(GetCurrentProcess(),nullptr,0))goto done;
    ok=true;
done:
    // Roll back the whole transaction before any thread resumes, including
    // edits not yet reached by a fault-injected partial commit.
    if(changed&&!ok) {
        for(unsigned i=0;i<count;i++)memcpy(patches[i].address,enable?patches[i].before:patches[i].after,patches[i].size);
        FlushInstructionCache(GetCurrentProcess(),nullptr,0);
    }
    for(unsigned i=0;i<writable;i++) {
        DWORD ignored;
        if(!VirtualProtect(pages[i].address,4096,pages[i].protection,&ignored)) {
            // Fail closed: restore all bytes, also on protection restoration
            // failure, before resuming. Relays remain pinned until process exit.
            for(unsigned j=0;j<writable;j++)VirtualProtect(pages[j].address,4096,PAGE_EXECUTE_READWRITE,&ignored);
            if(changed)for(unsigned j=0;j<count;j++)memcpy(patches[j].address,enable?patches[j].before:patches[j].after,patches[j].size);
            FlushInstructionCache(GetCurrentProcess(),nullptr,0);
            for(unsigned j=0;j<writable;j++)VirtualProtect(pages[j].address,4096,pages[j].protection,&ignored);
            ok=false;break;
        }
    }
    // Exactly one decrement for each owned increment. Never resume a thread
    // opened but not suspended, or erase somebody else's suspension count.
    for(unsigned i=0;i<threads;i++)if(handles[i]) {
        // If protection setup failed, no suspensions were taken.
        if(start)ResumeThread(handles[i]);
        CloseHandle(handles[i]);
    }
    if(snapshot!=INVALID_HANDLE_VALUE)CloseHandle(snapshot);
    ReleaseSRWLockExclusive(&transactionLock);return ok;
}
}
