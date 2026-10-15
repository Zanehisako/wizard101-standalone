/* Thin ARM64 executable, two independent decoder workers. Inherited fds only. */
#include "NativeProtocol.h"
#include "libdeflate.h"
#include <pthread.h>
#include <sys/socket.h>
#include <sys/mman.h>
#include <sys/time.h>
#include <unistd.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
static w101_arena *arena;
static void *worker(void *arg) {
 struct libdeflate_decompressor *d=arg;
 for(;;){
  w101_message message;ssize_t n=recv(3,&message,sizeof(message),0);
  if(n<0 && (errno==EINTR || errno==EAGAIN || errno==EWOULDBLOCK)){if(getppid()!=(pid_t)arena->reserved)_exit(0);continue;}if(n!=sizeof(message))break;
  if(message.kind!=1 || message.slot>=2)break;
  w101_decode_slot *s=&arena->slots[message.slot];
  if(__atomic_load_n(&s->state,__ATOMIC_ACQUIRE)!=W101_BUSY || s->sequence!=message.sequence)continue;
  if(s->input_bytes<256*1024 || s->input_bytes>W101_INPUT_MAX || !s->output_cap || s->output_cap>W101_OUTPUT_MAX)break;
#ifdef W101_VERIFY
  const char *fault=getenv("W101_NATIVE_TEST");
  if(fault && !strcmp(fault,"crash"))_exit(23);
  if(fault && (!strcmp(fault,"late") || !strcmp(fault,"busy")))usleep(!strcmp(fault,"late")?75000:12000);
#endif
  size_t actual=0;int result=libdeflate_zlib_decompress(d,w101_slot_input(arena,message.slot),s->input_bytes,w101_slot_output(arena,message.slot),s->output_cap,&actual);
  s->result=result;s->output_bytes=actual;
  uint32_t expected=W101_BUSY;
  __atomic_compare_exchange_n(&s->state,&expected,W101_DONE,0,__ATOMIC_RELEASE,__ATOMIC_RELAXED);
  /* Completion is authoritative in shared memory. A full notification
     socket must never block a decoder worker. */
  message.kind=2;send(3,&message,sizeof(message),MSG_DONTWAIT);
 }
 libdeflate_free_decompressor(d);return NULL;
}
int main(void) {
#ifdef W101_VERIFY
 const char *fault=getenv("W101_NATIVE_TEST");if(fault && !strcmp(fault,"startup"))usleep(3000000);
#endif
 arena=mmap(NULL,W101_ARENA_BYTES,PROT_READ|PROT_WRITE,MAP_SHARED,4,0);
 if(arena==MAP_FAILED || arena->magic!=0x57313031 || arena->version!=1)return 2;
 if(getppid()!=(pid_t)arena->reserved)return 5;
 struct timeval timeout={0,250000};setsockopt(3,SOL_SOCKET,SO_RCVTIMEO,&timeout,sizeof(timeout));
 pthread_t threads[2];
 for(unsigned i=0;i<2;i++){struct libdeflate_decompressor *d=libdeflate_alloc_decompressor();if(!d || pthread_create(&threads[i],NULL,worker,d))return 3;}
 w101_message ready={0,0,0};if(send(3,&ready,sizeof(ready),0)!=sizeof(ready))return 4;
 for(unsigned i=0;i<2;i++)pthread_join(threads[i],NULL);
 munmap(arena,W101_ARENA_BYTES);close(4);close(3);return 0;
}
