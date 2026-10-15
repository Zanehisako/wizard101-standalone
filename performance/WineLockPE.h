/* Wine 11: called only on the existing RtlEnterCriticalSection wait branch. */
#include "unixlib.h"
struct w101_lock_params {
    ULONGLONG begin, section, caller_rva;
    ULONG owner_tid, windows_tid, identified;
};
static int w101_lock_enabled(void)
{
    static LONG state;
    WCHAR *p, *name;
    const WCHAR key[] = L"W101_WORKLOAD_LOCKS=";
    unsigned int i;
    if (InterlockedCompareExchange(&state,-1,0)) return InterlockedCompareExchange(&state,0,0) == 2;
    name = NtCurrentTeb()->Peb->ProcessParameters->ImagePathName.Buffer;
    for (p=name; *p; ++p) if (*p=='\\' || *p=='/') name=p+1;
    if (wcsicmp(name,L"WizardGraphicalClient.exe")) { InterlockedExchange(&state,1); return 0; }
    /* The launch environment is immutable during recording. No allocation,
       environment/loader lock or stack walk inside a contention branch. */
    p=NtCurrentTeb()->Peb->ProcessParameters->Environment;
    if (p) for (;*p;p+=wcslen(p)+1) {
        for (i=0; key[i] && key[i]==p[i]; ++i) ;
        if (!key[i] && p[i]) { InterlockedExchange(&state,2); return 1; }
    }
    InterlockedExchange(&state,1); return 0;
}
static void w101_lock_begin(struct w101_lock_params *params, RTL_CRITICAL_SECTION *crit, void *caller)
{
    ULONG error=NtCurrentTeb()->LastErrorValue;
    char *base;
    IMAGE_NT_HEADERS *nt;
    memset(params,0,sizeof(*params));
    if (!w101_lock_enabled()) return;
    params->section=(ULONG_PTR)crit;
    params->owner_tid=HandleToULong(crit->OwningThread);
    params->windows_tid=GetCurrentThreadId();
    base=(char *)NtCurrentTeb()->Peb->ImageBaseAddress;
    nt=(IMAGE_NT_HEADERS *)(base+((IMAGE_DOS_HEADER *)base)->e_lfanew);
    if ((char *)caller>=base && (char *)caller<base+nt->OptionalHeader.SizeOfImage) {
        params->caller_rva=(char *)caller-base; params->identified=1;
    }
    __wine_unix_call(__wine_unixlib_handle,unix_w101_lock_begin,params);
    NtCurrentTeb()->LastErrorValue=error;
}
static void w101_lock_end(struct w101_lock_params *params)
{
    ULONG error=NtCurrentTeb()->LastErrorValue;
    if (params->begin) __wine_unix_call(__wine_unixlib_handle,unix_w101_lock_end,params);
    NtCurrentTeb()->LastErrorValue=error;
}
