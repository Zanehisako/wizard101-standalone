#include "NtIdentity.h"
#include "NativeProtocol.h"
LONG WINAPI W101NativeDecode(w101_decode_params *params) {
 static LONG gate;ULONG error=NtCurrentTeb()->LastErrorValue;params->success=0;
 if(!InterlockedCompareExchange(&gate,-1,0))InterlockedExchange(&gate,w101_nt_verified_game(L"W101_NATIVE_DECODE=auto")?2:1);
 if(InterlockedCompareExchange(&gate,0,0)==2)__wine_unix_call(__wine_unixlib_handle,unix_w101_native_decode,params);
 NtCurrentTeb()->LastErrorValue=error;return 0;
}
