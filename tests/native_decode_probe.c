/* Native x86_64 parent exercising the same IPC client as Wine. */
#include <stdint.h>
typedef int32_t NTSTATUS;
#include "../decompression/NativeClient.h"
#include "libdeflate.h"
#define CHECK(x) do{if(!(x)){fprintf(stderr,"FAIL line=%d %s\n",__LINE__,#x);exit(1);}}while(0)
static unsigned char *raw,*input;static size_t input_bytes;static unsigned length=2*1024*1024;
static w101_decode_params request(unsigned char *output){w101_decode_params p={(uint64_t)(uintptr_t)input,(uint64_t)(uintptr_t)output,input_bytes,length,0,1,0};return p;}
static void *caller(void *arg){unsigned char *out=malloc(length);CHECK(out);memset(out,0xEF,length);w101_decode_params p=request(out);int success=w101_native_decode(&p);if(success)CHECK(p.output_bytes==length&&!memcmp(out,raw,length));else for(unsigned i=0;i<length;i++)CHECK(out[i]==0xEF);*(int*)arg=success;free(out);return NULL;}
int main(int argc,char **argv){CHECK(argc==2);raw=malloc(length);input=malloc(length+65536);CHECK(raw&&input);uint32_t rng=12345;for(unsigned i=0;i<length;i++){rng^=rng<<13;rng^=rng>>17;rng^=rng<<5;raw[i]=i%8192<3072?rng:i%127;}struct libdeflate_compressor *c=libdeflate_alloc_compressor(6);CHECK(c);input_bytes=libdeflate_zlib_compress(c,raw,length,input,length+65536);libdeflate_free_compressor(c);CHECK(input_bytes>=256*1024);
 int start=w101_native_start();
 if(!strcmp(argv[1],"startup")){CHECK(!start&&w101_native_disabled);puts("PASS startup failure");return 0;}
 CHECK(start);unsigned char *output=malloc(length);CHECK(output);memset(output,0xEF,length);w101_decode_params p=request(output);
 if(!strcmp(argv[1],"orphan")){printf("ORPHAN pid=%d\n",w101_native_pid);fflush(stdout);for(;;)pause();}
 if(!strcmp(argv[1],"late") || !strcmp(argv[1],"crash")){
  uint64_t begin=w101_native_ns();CHECK(!w101_native_decode(&p));CHECK(w101_native_disabled);CHECK((w101_native_ns()-begin)<100000000);
  for(unsigned i=0;i<length;i++)CHECK(output[i]==0xEF);
  CHECK(w101_native_arena->slots[0].state==W101_QUARANTINED);usleep(100000);CHECK(!w101_native_decode(&p));puts("PASS failure isolation quarantine late reply disabled");
 }else if(!strcmp(argv[1],"busy")){
  pthread_t threads[2];int success[2]={0};for(unsigned i=0;i<2;i++)CHECK(!pthread_create(&threads[i],NULL,caller,&success[i]));
  uint64_t end=w101_native_ns()+10000000;while(w101_native_ns()<end && (w101_native_arena->slots[0].state!=W101_BUSY || w101_native_arena->slots[1].state!=W101_BUSY))usleep(100);
  CHECK(w101_native_arena->slots[0].state==W101_BUSY && w101_native_arena->slots[1].state==W101_BUSY);
  uint64_t begin=w101_native_ns();CHECK(!w101_native_decode(&p));CHECK(w101_native_ns()-begin<5000000);for(unsigned i=0;i<length;i++)CHECK(output[i]==0xEF);
  for(unsigned i=0;i<2;i++)pthread_join(threads[i],NULL);
  CHECK((success[0] && success[1]) || w101_native_disabled);
  printf("PASS saturation immediate fallback independent slots successes=%d disabled=%d\n",success[0]+success[1],w101_native_disabled);
 }else{
  CHECK(w101_native_decode(&p));CHECK(p.output_bytes==length&&!memcmp(output,raw,length));
  memset(output,0xEF,length);input[input_bytes-1]^=1;p=request(output);CHECK(!w101_native_decode(&p));for(unsigned i=0;i<length;i++)CHECK(output[i]==0xEF);input[input_bytes-1]^=1;
  p=request(output);p.output_cap=length-1;CHECK(!w101_native_decode(&p));p=request(output);p.input_bytes=256*1024-1;CHECK(!w101_native_decode(&p));
  pthread_t threads[8];int success[8]={0};for(unsigned i=0;i<8;i++)CHECK(!pthread_create(&threads[i],NULL,caller,&success[i]));for(unsigned i=0;i<8;i++)pthread_join(threads[i],NULL);
  puts("PASS decoded bytes malformed short buffer unsupported concurrency");
 }
 pid_t child=w101_native_pid;w101_native_close();CHECK(!w101_native_arena);CHECK(kill(child,0)==-1&&errno==ESRCH);puts("PASS cleanup");free(output);free(raw);free(input);return 0;
}
