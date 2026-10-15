#include <windows.h>
#include <stdint.h>
#include <stdio.h>
static volatile LONG done;
static volatile uint64_t work;
__attribute__((noinline)) static uint64_t measured_leaf(uint64_t value) {
    for(unsigned i=0;i<200000;i++) value=(value*6364136223846793005ULL+1)^i;
    work=value; return value;
}
__attribute__((noinline)) static uint64_t measured_parent(uint64_t value) {
    uint64_t result=measured_leaf(value); work=result+1; return result+1;
}
static DWORD WINAPI worker(void *unused) {
    (void)unused; uint64_t value=1;
    while(!done) value=measured_parent(value); return (DWORD)value;
}
int main(void) {
    DWORD tid; HANDLE t=CreateThread(NULL,0,worker,NULL,0,&tid); if(!t) return 1;
    printf("{\"pid\":%lu,\"tid\":%lu,\"base\":%llu,\"leaf\":%llu,\"parent\":%llu}\n",GetCurrentProcessId(),tid,
      (unsigned long long)(uintptr_t)GetModuleHandleA(NULL),(unsigned long long)(uintptr_t)measured_leaf,(unsigned long long)(uintptr_t)measured_parent);
    fflush(stdout);
    /* stdin commands let the verifier check preexisting suspension and liveness. */
    char command[64];
    while(fgets(command,sizeof(command),stdin)) {
        if(!strncmp(command,"suspend",7)) printf("SUSPEND %lu\n",SuspendThread(t));
        else if(!strncmp(command,"resume",6)) printf("RESUME %lu\n",ResumeThread(t));
        else if(!strncmp(command,"alive",5)) { uint64_t before=work; Sleep(100); printf("ALIVE %d\n",work!=before); }
        else break;
        fflush(stdout);
    }
    InterlockedExchange(&done,1); WaitForSingleObject(t,2000); CloseHandle(t); return 0;
}
