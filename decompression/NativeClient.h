/* Included in Wine's Unix loader, or the isolated native IPC probe. */
#include "NativeProtocol.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <sys/wait.h>
#include <sys/stat.h>
#include <poll.h>
#include <spawn.h>
#include <signal.h>
#include <pthread.h>
#include <mach/mach_time.h>
#ifndef environ
extern char **environ;
#endif
static pthread_mutex_t w101_native_start_lock=PTHREAD_MUTEX_INITIALIZER;
static w101_arena *w101_native_arena;
static int w101_native_socket=-1;
static pid_t w101_native_pid;
static int w101_native_started,w101_native_disabled;
static uint64_t w101_native_sequence;
static void w101_native_drain(void){w101_message reply;for(unsigned i=0;i<8;i++)if(recv(w101_native_socket,&reply,sizeof(reply),MSG_DONTWAIT)!=sizeof(reply))break;}
static uint64_t w101_native_ns(void){mach_timebase_info_data_t tb;mach_timebase_info(&tb);return (uint64_t)((__uint128_t)mach_absolute_time()*tb.numer/tb.denom);}
static void w101_native_disable(void){__atomic_store_n(&w101_native_disabled,1,__ATOMIC_RELEASE);if(w101_native_pid>0)kill(w101_native_pid,SIGTERM);}
static void w101_native_close(void){w101_native_disable();if(w101_native_pid>0){waitpid(w101_native_pid,NULL,0);w101_native_pid=0;}if(w101_native_socket>=0){close(w101_native_socket);w101_native_socket=-1;}if(w101_native_arena)munmap(w101_native_arena,W101_ARENA_BYTES);w101_native_arena=NULL;}
static int w101_native_start(void) {
 int ok=0;const char *stage="environment";pthread_mutex_lock(&w101_native_start_lock);
 if(w101_native_started){ok=!__atomic_load_n(&w101_native_disabled,__ATOMIC_ACQUIRE);goto done;}
 w101_native_started=1;__atomic_store_n(&w101_native_disabled,1,__ATOMIC_RELEASE);
 const char *helper=getenv("W101_DECODE_HELPER");if(!helper || helper[0]!='/')goto done;
 int sockets[2]={-1,-1},fd=-1;char name[100];snprintf(name,sizeof(name),"/w101decode-%d-%08x",getpid(),arc4random());
 stage="shm_open";fd=shm_open(name,O_RDWR|O_CREAT|O_EXCL,0600);if(fd<0)goto done;shm_unlink(name);
 stage="arena and socket";
 if(ftruncate(fd,W101_ARENA_BYTES) || socketpair(AF_UNIX,SOCK_DGRAM,0,sockets))goto failed;
 w101_native_arena=mmap(NULL,W101_ARENA_BYTES,PROT_READ|PROT_WRITE,MAP_SHARED,fd,0);
 if(w101_native_arena==MAP_FAILED){w101_native_arena=NULL;goto failed;}
 memset(w101_native_arena,0,4096);w101_native_arena->magic=0x57313031;w101_native_arena->version=1;w101_native_arena->reserved=getpid();
 /* Avoid descriptor aliasing with the helper's fixed fd 3 and fd 4. */
 stage="duplicate descriptors";int child_socket=fcntl(sockets[1],F_DUPFD_CLOEXEC,10),child_arena=fcntl(fd,F_DUPFD_CLOEXEC,10);
 if(child_socket<0 || child_arena<0){if(child_socket>=0)close(child_socket);if(child_arena>=0)close(child_arena);goto failed;}
 posix_spawn_file_actions_t actions;posix_spawnattr_t attrs;
 posix_spawn_file_actions_init(&actions);posix_spawnattr_init(&attrs);
 posix_spawn_file_actions_adddup2(&actions,child_socket,3);posix_spawn_file_actions_adddup2(&actions,child_arena,4);
 posix_spawnattr_setflags(&attrs,POSIX_SPAWN_CLOEXEC_DEFAULT);
 stage="spawn";char *argv[]={(char*)helper,NULL};int status=posix_spawn(&w101_native_pid,helper,&actions,&attrs,argv,environ);
 posix_spawn_file_actions_destroy(&actions);posix_spawnattr_destroy(&attrs);close(child_socket);close(child_arena);close(sockets[1]);sockets[1]=-1;close(fd);fd=-1;
 if(status){w101_native_pid=0;goto failed;}
 w101_native_socket=sockets[0];sockets[0]=-1;fcntl(w101_native_socket,F_SETFL,O_NONBLOCK);
 stage="ready";struct pollfd p={w101_native_socket,POLLIN,0};w101_message ready;
 if(poll(&p,1,2000)!=1 || recv(w101_native_socket,&ready,sizeof(ready),0)!=sizeof(ready) || ready.kind!=0){
#ifdef W101_VERIFY
  siginfo_t child={0};waitid(P_PID,w101_native_pid,&child,WEXITED|WNOHANG|WNOWAIT);fprintf(stderr,"helper ready failure pid=%d status=%d code=%d\n",child.si_pid,child.si_status,child.si_code);
#endif
  w101_native_disable();goto failed;
 }
 __atomic_store_n(&w101_native_disabled,0,__ATOMIC_RELEASE);atexit(w101_native_close);ok=1;goto done;
failed:
 if(fd>=0)close(fd);if(sockets[0]>=0)close(sockets[0]);if(sockets[1]>=0)close(sockets[1]);
 if(w101_native_pid>0){kill(w101_native_pid,SIGTERM);waitpid(w101_native_pid,NULL,0);w101_native_pid=0;}
 if(w101_native_socket>=0){close(w101_native_socket);w101_native_socket=-1;}
 if(w101_native_arena){munmap(w101_native_arena,W101_ARENA_BYTES);w101_native_arena=NULL;}
done:
#ifdef W101_VERIFY
 if(!ok)fprintf(stderr,"native startup stage=%s errno=%d\n",stage,errno);
#else
 (void)stage;
#endif
 pthread_mutex_unlock(&w101_native_start_lock);return ok;
}
static int w101_native_decode(w101_decode_params *p) {
 if(__atomic_load_n(&w101_native_disabled,__ATOMIC_ACQUIRE) || !w101_native_started || !w101_native_arena || p->input_bytes<256*1024 || p->input_bytes>W101_INPUT_MAX || !p->output_cap || p->output_cap>W101_OUTPUT_MAX)return 0;
 w101_native_drain();
 uint64_t deadline=w101_native_ns()+50000000;unsigned index;
 for(index=0;index<2;index++){uint32_t expected=W101_EMPTY;if(__atomic_compare_exchange_n(&w101_native_arena->slots[index].state,&expected,W101_BUSY,0,__ATOMIC_ACQUIRE,__ATOMIC_RELAXED))break;}
 if(index==2)return 0;
 w101_decode_slot *s=&w101_native_arena->slots[index];s->input_bytes=p->input_bytes;s->output_cap=p->output_cap;s->output_bytes=0;s->sequence=__atomic_add_fetch(&w101_native_sequence,1,__ATOMIC_RELAXED);
 memcpy(w101_slot_input(w101_native_arena,index),(void*)(uintptr_t)p->input,p->input_bytes);
 /* Socket send publishes metadata and copied input before helper consumption. */
 __atomic_store_n(&s->state,W101_BUSY,__ATOMIC_RELEASE);w101_message message={s->sequence,index,1};
 if(send(w101_native_socket,&message,sizeof(message),MSG_DONTWAIT)!=sizeof(message)){__atomic_store_n(&s->state,W101_QUARANTINED,__ATOMIC_RELEASE);w101_native_disable();return 0;}
 while(!__atomic_load_n(&w101_native_disabled,__ATOMIC_ACQUIRE) && w101_native_ns()<deadline){
  if(__atomic_load_n(&s->state,__ATOMIC_ACQUIRE)==W101_DONE){
   int ok=s->result==0 && s->output_bytes<=p->output_cap;
   if(ok){memcpy((void*)(uintptr_t)p->output,w101_slot_output(w101_native_arena,index),s->output_bytes);p->output_bytes=s->output_bytes;}
   w101_native_drain();__atomic_store_n(&s->state,W101_EMPTY,__ATOMIC_RELEASE);return ok;
  }
  struct pollfd wait={w101_native_socket,POLLIN,0};int r=poll(&wait,1,1);
  if(r<0 && errno!=EINTR)break;
  if(wait.revents&(POLLERR|POLLHUP|POLLNVAL))break;
  if(r>0)w101_native_drain();
  siginfo_t child={0};if(!waitid(P_PID,w101_native_pid,&child,WEXITED|WNOHANG|WNOWAIT) && child.si_pid==w101_native_pid)break;
 }
 __atomic_store_n(&s->state,W101_QUARANTINED,__ATOMIC_RELEASE);w101_native_disable();return 0;
}
static NTSTATUS w101_native_dispatch(void *arg){int saved=errno;w101_decode_params *p=arg;p->success=p->operation==0?w101_native_start():p->operation==1?w101_native_decode(p):0;errno=saved;return 0;}
