/* Read-only native CPU evidence for Wine's Windows-context samples. */
#include <libproc.h>
#include <sys/proc_info.h>
#include <pthread.h>
#include <stdint.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
static uint64_t ns(clockid_t clock) {
    struct timespec t; clock_gettime(clock,&t); return (uint64_t)t.tv_sec*1000000000+t.tv_nsec;
}
static atomic_int finished;
static atomic_ullong busy_tid;
static uint64_t busy_cpu,work;
static void *busy(void *unused) {
    (void)unused; uint64_t tid; pthread_threadid_np(NULL,&tid); atomic_store(&busy_tid,tid);
    uint64_t start=ns(CLOCK_THREAD_CPUTIME_ID);
    while(!atomic_load(&finished)) work=work*6364136223846793005ULL+1;
    busy_cpu=ns(CLOCK_THREAD_CPUTIME_ID)-start; return NULL;
}
int main(int argc,char **argv) {
    if(argc==2 && !strcmp(argv[1],"--self-test")) {
        pthread_t t; if(pthread_create(&t,NULL,busy,NULL)) return 1;
        while(!atomic_load(&busy_tid)) usleep(1000);
        struct proc_threadinfo before,after;
        if(proc_pidinfo(getpid(),PROC_PIDTHREADID64INFO,atomic_load(&busy_tid),&before,sizeof(before))!=sizeof(before)) return 2;
        usleep(250000);
        if(proc_pidinfo(getpid(),PROC_PIDTHREADID64INFO,atomic_load(&busy_tid),&after,sizeof(after))!=sizeof(after)) return 3;
        atomic_store(&finished,1); pthread_join(t,NULL);
        uint64_t measured=after.pth_user_time+after.pth_system_time-before.pth_user_time-before.pth_system_time;
        double ratio=busy_cpu?(double)measured/busy_cpu:0;
        printf("{\"measured_cpu_ns\":%llu,\"thread_clock_cpu_ns\":%llu,\"ratio\":%.6f,\"passed\":%s}\n",
            (unsigned long long)measured,(unsigned long long)busy_cpu,ratio,ratio>.85 && ratio<1.05?"true":"false");
        return ratio>.85 && ratio<1.05?0:4;
    }
    if(argc!=3) return 2;
    int pid=atoi(argv[1]),seconds=atoi(argv[2]);
    if(pid<=0 || seconds<1 || seconds>15) return 2;
    uint64_t deadline=ns(CLOCK_MONOTONIC)+(uint64_t)seconds*1000000000;
    while(ns(CLOCK_MONOTONIC)<deadline && !ferror(stdout)) {
        uint64_t ids[256],start=ns(CLOCK_REALTIME);
        // XNU PROC_PIDLISTTHREADIDS=28 returns native kernel IDs. Public flavor
        // PROC_PIDLISTTHREADS returns pthread handles, which are different IDs.
        int bytes=proc_pidinfo(pid,28,0,ids,sizeof(ids));
        if(bytes<=0 || (size_t)bytes>=sizeof(ids)) return 3;
        printf("{\"kind\":\"native_cpu\",\"unix_us\":%llu,\"threads\":[",(unsigned long long)(start/1000));
        unsigned emitted=0;
        for(unsigned i=0;i<(unsigned)bytes/sizeof(ids[0]);i++) {
            struct proc_threadinfo info;
            if(proc_pidinfo(pid,PROC_PIDTHREADID64INFO,ids[i],&info,sizeof(info))!=sizeof(info)) continue;
            printf("%s{\"native_tid\":%llu,\"cpu_ns\":%llu,\"run_state\":%d}",emitted++?",":"",
                (unsigned long long)ids[i],(unsigned long long)(info.pth_user_time+info.pth_system_time),info.pth_run_state);
        }
        printf("],\"bracket_us\":%llu}\n",(unsigned long long)((ns(CLOCK_REALTIME)-start)/1000));
        usleep(50000);
    }
    return ferror(stdout)?4:0;
}
