#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../game/lookup.h"
typedef struct {unsigned char pad[16];uint64_t name;} Item;
typedef struct {unsigned char pad[32];Item**array;uint16_t count;} Object;
static W101Lookup reference;
static uint64_t empty=UINT64_C(0xaabbbbbbbbbbbbbb),state=UINT64_C(0x29adf00);
static uint64_t random64(void) {state^=state<<13;state^=state>>7;state^=state<<17;return state;}
__attribute__((noinline)) static void *candidate(const void*obj,const uint64_t*key) {return w101_lookup(obj,key,&empty);}
static double benchmark(W101Lookup lookup,Object*obj,unsigned count,int miss) {
    LARGE_INTEGER begin,end,hz;QueryPerformanceFrequency(&hz);QueryPerformanceCounter(&begin);
    void *retain=0;
    for(unsigned i=0;i<count;i++) {uint64_t key=((uint64_t)(i%obj->count)<<2)+(miss?1:0);retain=lookup(obj,&key);}
    QueryPerformanceCounter(&end);void*volatile observed=retain;(void)observed;
    return(double)(end.QuadPart-begin.QuadPart)*1e9/hz.QuadPart/count;
}
int main(int argc,char**argv) {
    if(argc!=2)return 2;
    FILE*f=fopen(argv[1],"rb");if(!f)return 3;
    unsigned char*code=VirtualAlloc(NULL,4096,MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE);if(!code)return 4;
    size_t bytes=fread(code,1,4096,f);fclose(f);if(bytes!=164)return 5;
    // Preserve the original getter and empty sentinel in the read-only fixture.
    unsigned char getter[]={0x48,0x8d,0x41,0x10,0xc3};memcpy(code+192,getter,5);memcpy(code+208,&empty,8);
    int32_t disp=208-0x1f;memcpy(code+0x1b,&disp,4);disp=192-0x5b;memcpy(code+0x57,&disp,4);
    DWORD old;if(!VirtualProtect(code,4096,PAGE_EXECUTE_READ,&old))return 6;
    FlushInstructionCache(GetCurrentProcess(),code,4096);reference=(W101Lookup)code;
    Item*items=calloc(32768,sizeof(Item));Item**array=calloc(32768,sizeof(Item*));if(!items||!array)return 8;
    Object obj={.array=array};for(unsigned i=0;i<32768;i++){array[i]=items+i;items[i].name=(uint64_t)i<<2;}
    unsigned cases=0,failed=0;
    // All normal lengths; empty/overflow counts whose original initial range is empty.
    for(unsigned length=0;length<32768;length++) {
      obj.count=(uint16_t)length;
      uint64_t keys[]={empty,0,(uint64_t)(length/2)<<2,(uint64_t)length<<2,UINT64_MAX,UINT64_C(0x8000000000000000)};
      for(unsigned k=0;k<6;k++){cases++;if(reference(&obj,keys+k)!=candidate(&obj,keys+k))failed++;}}
    for(unsigned length=32769;length<65536;length++){obj.count=(uint16_t)length;uint64_t key=7;cases++;if(reference(&obj,&key)!=candidate(&obj,&key))failed++;}
    // Duplicates, unsorted keys and wrapping signed comparisons preserve the exact search.
    for(unsigned round=0;round<2500;round++) {
      obj.count=1+(unsigned)(random64()%256);
      for(unsigned i=0;i<obj.count;i++)items[i].name=random64();
      if(obj.count>2)items[1].name=items[0].name;
      for(unsigned i=0;i<64;i++){uint64_t key=(i&1)?items[random64()%obj.count].name:random64();cases++;if(reference(&obj,&key)!=candidate(&obj,&key))failed++;}}
    for(unsigned i=0;i<32768;i++)items[i].name=(uint64_t)i<<2;
    printf("{\"equivalence_cases\":%u,\"mismatches\":%u,\"benchmarks_ns\":[",cases,failed);
    unsigned sizes[]={4,16,64,256};
    for(unsigned s=0;s<4;s++)for(unsigned miss=0;miss<2;miss++)for(unsigned pair=0;pair<5;pair++) {
      obj.count=(uint16_t)sizes[s];double orig,patch;
      if(pair&1){patch=benchmark(candidate,&obj,400000,miss);orig=benchmark(reference,&obj,400000,miss);}else {orig=benchmark(reference,&obj,400000,miss);patch=benchmark(candidate,&obj,400000,miss);}
      printf("%s{\"size\":%u,\"miss\":%s,\"original\":%.3f,\"candidate\":%.3f}",s||miss||pair?",":"",sizes[s],miss?"true":"false",orig,patch);}
    printf("],\"passed\":%s}\n",!failed?"true":"false");free(items);free(array);VirtualFree(code,0,MEM_RELEASE);return failed?7:0;
}
