#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#define CHECK(x) do{if(!(x)){fprintf(stderr,"FAIL line=%d %s\n",__LINE__,#x);exit(1);}}while(0)
typedef LONG (WINAPI *wait_fn)(const void*,const void*,SIZE_T,const LARGE_INTEGER*);
static wait_fn wait_addr;
static void (WINAPI *wake_one)(const void*), (WINAPI *wake_all)(const void*);
static LONG (WINAPI *info)(void), (WINAPI *depth)(const void*);
static volatile LONG value,completed;static LONG order[300];
static DWORD WINAPI waiter(void *arg) {
 LONG cmp=0;LARGE_INTEGER timeout;timeout.QuadPart=-30000000;LONG r=wait_addr(&value,&cmp,4,&timeout);
 CHECK(r==0);LONG pos=InterlockedIncrement(&completed)-1;order[pos]=(LONG)(intptr_t)arg;return 0;
}
static void await_depth(LONG n){ULONGLONG end=GetTickCount64()+3000;while(depth(&value)!=n && GetTickCount64()<end)Sleep(1);CHECK(depth(&value)==n);}
static void fifo(void){HANDLE handles[16];value=0;completed=0;for(unsigned i=0;i<16;i++){handles[i]=CreateThread(NULL,0,waiter,(void*)(intptr_t)i,0,NULL);CHECK(handles[i]);await_depth(i+1);}for(unsigned i=0;i<16;i++){wake_one(&value);CHECK(WaitForSingleObject(handles[i],3000)==WAIT_OBJECT_0);CHECK(order[i]==(LONG)i);CloseHandle(handles[i]);}CHECK(depth(&value)==0);}
static void all(void){HANDLE handles[280];value=0;completed=0;for(unsigned i=0;i<280;i++){handles[i]=CreateThread(NULL,32768,waiter,(void*)(intptr_t)i,0,NULL);CHECK(handles[i]);}await_depth(280);value=1;wake_all(&value);for(unsigned i=0;i<280;i++){CHECK(WaitForSingleObject(handles[i],3000)==WAIT_OBJECT_0);CloseHandle(handles[i]);}CHECK(completed==280 && !depth(&value));}
static unsigned char addresses[64*4096] __attribute__((aligned(128)));
static volatile LONG start;
static DWORD WINAPI collision(void *arg){unsigned id=(unsigned)(uintptr_t)arg;LONG cmp=1;while(!start)YieldProcessor();for(unsigned i=0;i<20000;i++){LONG *addr=(LONG*)(addresses+id*4096);CHECK(wait_addr(addr,&cmp,4,NULL)==0);wake_one(addr);wake_all(addr);}return 0;}
static double now(void){LARGE_INTEGER t,f;QueryPerformanceCounter(&t);QueryPerformanceFrequency(&f);return (double)t.QuadPart/f.QuadPart;}
static void bench(void){HANDLE h[16];start=0;for(unsigned i=0;i<16;i++){h[i]=CreateThread(NULL,0,collision,(void*)(uintptr_t)i,0,NULL);CHECK(h[i]);}double begin=now();InterlockedExchange(&start,1);CHECK(WaitForMultipleObjects(16,h,TRUE,30000)==WAIT_OBJECT_0);double elapsed=now()-begin;for(unsigned i=0;i<16;i++)CloseHandle(h[i]);printf("BENCH seconds=%.9f\n",elapsed);}
typedef struct {volatile LONG *addr;unsigned id;} job;
static DWORD WINAPI timed(void *arg){job *j=arg;LONG cmp=0;for(unsigned i=0;i<100;i++){LARGE_INTEGER t;t.QuadPart=-10000;LONG r=wait_addr(j->addr,&cmp,4,&t);CHECK(r==0 || r==0x102);if((i+j->id)%3)wake_one(j->addr);else wake_all(j->addr);}return 0;}
static RTL_CRITICAL_SECTION crit;static LONG protected_count;
static DWORD WINAPI critical(void *arg){(void)arg;for(unsigned i=0;i<10000;i++){EnterCriticalSection(&crit);EnterCriticalSection(&crit);CHECK(crit.RecursionCount==2 && (DWORD)(uintptr_t)crit.OwningThread==GetCurrentThreadId());++protected_count;LeaveCriticalSection(&crit);LeaveCriticalSection(&crit);}return 0;}
int main(int argc,char **argv){CHECK(argc==2);HMODULE n=GetModuleHandleA("ntdll.dll");wait_addr=(wait_fn)GetProcAddress(n,"RtlWaitOnAddress");wake_one=(void*)GetProcAddress(n,"RtlWakeAddressSingle");wake_all=(void*)GetProcAddress(n,"RtlWakeAddressAll");info=(void*)GetProcAddress(n,"W101WaitQueueInfo");depth=(void*)GetProcAddress(n,"W101WaitQueueDepth");CHECK(wait_addr&&wake_one&&wake_all&&info&&depth);
 LONG cmp=1;CHECK(wait_addr(&value,&cmp,4,NULL)==0);int sharded=getenv("W101_WAIT_QUEUES") && !strcmp(getenv("W101_WAIT_QUEUES"),"sharded");if(!strcmp(argv[1],"reject"))sharded=0;CHECK(info()==(sharded?2:1));printf("queue_state=%ld\n",info());
 if(!strcmp(argv[1],"reject")){puts("PASS unverified executable rejected");return 0;}
 if(!strcmp(argv[1],"bench")){bench();return 0;}
 CHECK(wait_addr(&value,&cmp,3,NULL)==(LONG)0xc000000d);value=0;cmp=0;LARGE_INTEGER zero;zero.QuadPart=0;CHECK(wait_addr(&value,&cmp,4,&zero)==0x102);CHECK(!depth(&value));wake_one(NULL);wake_all(NULL);
 for(unsigned i=0;i<5;i++){fifo();all();}
 HANDLE h[32];job jobs[32];for(unsigned i=0;i<32;i++){jobs[i].addr=(LONG*)(addresses+(i%8)*4096);jobs[i].id=i;h[i]=CreateThread(NULL,0,timed,&jobs[i],0,NULL);CHECK(h[i]);}CHECK(WaitForMultipleObjects(32,h,TRUE,15000)==WAIT_OBJECT_0);for(unsigned i=0;i<32;i++)CloseHandle(h[i]);
 InitializeCriticalSection(&crit);for(unsigned i=0;i<16;i++){h[i]=CreateThread(NULL,0,critical,NULL,0,NULL);CHECK(h[i]);}CHECK(WaitForMultipleObjects(16,h,TRUE,15000)==WAIT_OBJECT_0);for(unsigned i=0;i<16;i++)CloseHandle(h[i]);CHECK(protected_count==160000);DeleteCriticalSection(&crit);
 puts("PASS ordering wake-one wake-all collisions timeouts recursion ownership shutdown");return 0;
}
