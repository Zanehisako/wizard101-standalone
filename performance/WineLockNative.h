/* Native append-only, bounded contention records. No lock addresses or payloads. */
#include <mach/mach_time.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <pthread.h>
struct w101_lock_params {
    unsigned long long begin, section, caller_rva;
    unsigned int owner_tid, windows_tid, identified;
};
static pthread_mutex_t w101_lock_writer_mutex=PTHREAD_MUTEX_INITIALIZER;
static int w101_lock_fd=-1, w101_lock_started;
static unsigned long long w101_lock_deadline, w101_lock_mask, w101_lock_rows, w101_lock_dropped;
static unsigned long long w101_lock_now(void)
{
    mach_timebase_info_data_t tb;
    mach_timebase_info(&tb);
    return (unsigned long long)((__uint128_t)mach_absolute_time()*tb.numer/tb.denom/1000);
}
static void w101_lock_close(void)
{
    char row[256]; int n;
    if(w101_lock_fd<0) return;
    n=snprintf(row,sizeof(row),"{\"type\":\"footer\",\"records\":%llu,\"dropped\":%llu}\n",w101_lock_rows,__atomic_load_n(&w101_lock_dropped,__ATOMIC_RELAXED));
    write(w101_lock_fd,row,n); close(w101_lock_fd); w101_lock_fd=-1;
}
static NTSTATUS w101_lock_begin_native(void *args)
{
    struct w101_lock_params *p=args;
    int saved=errno;
    const char *path=getenv("W101_WORKLOAD_LOCKS"), *limit=getenv("W101_WORKLOAD_DEADLINE_UNIX_US");
    unsigned long long now=w101_lock_now();
    struct timeval wall;
    if(!path || !*path || !limit) { p->begin=0; errno=saved; return 0; }
    pthread_mutex_lock(&w101_lock_writer_mutex);
    if(!w101_lock_started) {
        w101_lock_started=1; gettimeofday(&wall,NULL);
        unsigned long long unix_now=(unsigned long long)wall.tv_sec*1000000+wall.tv_usec, end=strtoull(limit,NULL,10);
        w101_lock_deadline=now+(end>unix_now?((end-unix_now)<900000000?end-unix_now:900000000):0);
        w101_lock_mask=now ^ ((unsigned long long)getpid()<<32);
        if(now<w101_lock_deadline) {
            w101_lock_fd=open(path,O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC,0600);
            if(w101_lock_fd>=0) { const char header[]="{\"type\":\"header\",\"schema\":1,\"threshold_us\":1000,\"max_bytes\":4194304,\"caller_policy\":\"main executable RVA or unidentified\"}\n"; write(w101_lock_fd,header,sizeof(header)-1); atexit(w101_lock_close); }
        }
    }
    p->begin=w101_lock_fd>=0 && now<w101_lock_deadline ? now:0;
    if(now>=w101_lock_deadline) w101_lock_close();
    pthread_mutex_unlock(&w101_lock_writer_mutex); errno=saved; return 0;
}
static NTSTATUS w101_lock_end_native(void *args)
{
    struct w101_lock_params *p=args;
    int saved=errno,n;
    unsigned long long end=w101_lock_now(), native_tid=0, token;
    struct stat st;
    char row[640];
    if(!p->begin || end<p->begin || end-p->begin<1000) { errno=saved; return 0; }
    if(pthread_mutex_trylock(&w101_lock_writer_mutex)) { __atomic_fetch_add(&w101_lock_dropped,1,__ATOMIC_RELAXED); errno=saved; return 0; }
    if(w101_lock_fd>=0 && end<w101_lock_deadline && !fstat(w101_lock_fd,&st) && st.st_size<4194304-1024) {
        pthread_threadid_np(NULL,&native_tid);
        token=p->section^w101_lock_mask; token^=token>>33; token*=0xff51afd7ed558ccdULL; token^=token>>33;
        n=snprintf(row,sizeof(row),"{\"type\":\"lock_contention\",\"pid\":%d,\"windows_tid\":%u,\"native_tid\":%llu,\"owner_windows_tid_at_wait\":%u,\"lock_token\":\"%llx\",\"caller_module\":\"%s\",\"caller_rva\":%llu,\"start_mach_us\":%llu,\"end_mach_us\":%llu,\"dropped_so_far\":%llu}\n",getpid(),p->windows_tid,native_tid,p->owner_tid,token,p->identified?"main_executable":"unidentified",p->caller_rva,p->begin,end,__atomic_load_n(&w101_lock_dropped,__ATOMIC_RELAXED));
        if(n>0 && n<sizeof(row) && write(w101_lock_fd,row,n)==n) ++w101_lock_rows; else __atomic_fetch_add(&w101_lock_dropped,1,__ATOMIC_RELAXED);
    } else { __atomic_fetch_add(&w101_lock_dropped,1,__ATOMIC_RELAXED); w101_lock_close(); }
    pthread_mutex_unlock(&w101_lock_writer_mutex); errno=saved; return 0;
}
