/* Included after struct futex_queue in Wine 11's unchanged sync.c. */
#include "NtIdentity.h"
struct __attribute__((aligned(128))) w101_queue_slot {struct futex_queue value;char padding[128-sizeof(struct futex_queue)];};
static struct w101_queue_slot w101_sharded_queues[4096];
static LONG w101_queue_state,w101_queue_initializer;

static BOOL w101_sharded_enabled(void) {
 LONG state=InterlockedCompareExchange(&w101_queue_state,0,0);ULONG error=NtCurrentTeb()->LastErrorValue;
 if(!state && !InterlockedCompareExchange(&w101_queue_state,-1,0)) {
  InterlockedExchange(&w101_queue_initializer,GetCurrentThreadId());BOOL ok=w101_nt_verified_game(L"W101_WAIT_QUEUES=sharded");
  /* Recursion permanently selects the original queues. Never change a
     process's table after its first waiter could have been enqueued. */
  InterlockedCompareExchange(&w101_queue_state,ok?2:1,-1);
 } else while(InterlockedCompareExchange(&w101_queue_state,0,0)==-1) {
  if(w101_queue_initializer==GetCurrentThreadId()){InterlockedCompareExchange(&w101_queue_state,1,-1);break;}
  YieldProcessor();
 }
 NtCurrentTeb()->LastErrorValue=error;return w101_queue_state==2;
}
static unsigned w101_queue_hash(ULONG_PTR v){v>>=2;v^=v>>33;v*=0xff51afd7ed558ccdULL;v^=v>>33;v*=0xc4ceb9fe1a85ec53ULL;v^=v>>33;return v&4095;}
#ifdef W101_TEST_HASH
LONG WINAPI W101WaitQueueInfo(void){return w101_queue_state;}
#endif
