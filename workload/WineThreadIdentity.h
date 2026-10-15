/* Wine 11 diagnostic callsites verify the initial thread, without names or stacks. */
#include <sys/stat.h>
#include <sys/time.h>
#include <sys/file.h>
#include <time.h>
static void w101_thread_identity(unsigned long windows_tid, int initial)
{
#ifdef __APPLE__
    const char *path = getenv("W101_WORKLOAD_THREADS"), *limit = getenv("W101_WORKLOAD_DEADLINE_UNIX_US");
    struct timeval now;
    struct stat st;
    uint64_t native_tid = 0;
    char row[384];
    struct timespec clock;
    static uint64_t monotonic_deadline;
    int fd, n, saved_errno = errno;
    if (!path || !*path || !limit) return;
    clock_gettime(CLOCK_MONOTONIC, &clock);
    if (initial) monotonic_deadline=(uint64_t)clock.tv_sec*1000000+clock.tv_nsec/1000+900000000;
    if (monotonic_deadline && (uint64_t)clock.tv_sec*1000000+clock.tv_nsec/1000>=monotonic_deadline) { errno=saved_errno; return; }
    gettimeofday(&now, NULL);
    if ((uint64_t)now.tv_sec * 1000000 + now.tv_usec >= strtoull(limit, NULL, 10)) { errno=saved_errno; return; }
    if ((fd = open(path, O_WRONLY | O_CREAT | O_APPEND | O_CLOEXEC | O_NONBLOCK, 0600)) < 0) { errno=saved_errno; return; }
    if (!flock(fd, LOCK_EX | LOCK_NB) && !fstat(fd, &st) && st.st_size < 1024*1024-512 && !pthread_threadid_np(NULL, &native_tid))
    {
        n=snprintf(row,sizeof(row),"{\"type\":\"thread_identity\",\"pid\":%d,\"windows_tid\":%lu,\"native_tid\":%llu,\"initial\":%s,\"unix_us\":%llu}\n",
                   getpid(),windows_tid,(unsigned long long)native_tid,initial?"true":"false",(unsigned long long)now.tv_sec*1000000+now.tv_usec);
        if (n>0 && n<sizeof(row)) write(fd,row,n);
    }
    close(fd); errno=saved_errno;
#endif
}
