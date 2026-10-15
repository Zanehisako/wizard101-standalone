#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include "../game/bounds.h"
static W101Merge reference;
static float epsilon,half;
static volatile unsigned fallback_calls;
static void fallback(W101Bound*out,const W101Bound*source) {fallback_calls++;reference(out,source);}
__attribute__((noinline)) static void candidate(W101Bound*out,const W101Bound*source) {w101_merge(out,source,fallback,&epsilon,&half);}
static uint64_t state=0x9231042;
static uint32_t random32(void) {state^=state<<13;state^=state>>7;state^=state<<17;return(uint32_t)state;}
static int equivalent(unsigned csr,int edge,int layout) {
    unsigned char first[96],second[96];
    for(unsigned i=0;i<sizeof(first);i+=4) {uint32_t bits=edge?random32():(random32()&0x807fffff)|((112+random32()%32)<<23);memcpy(first+i,&bits,4);}
    unsigned offset=layout==0?32:layout==1?0:layout==2?4:layout==3?12:layout==4?16:20;
    memcpy(second,first,sizeof(first));
    _mm_setcsr(csr);reference((W101Bound*)first,(W101Bound*)(first+offset));unsigned original_csr=_mm_getcsr();
    _mm_setcsr(csr);candidate((W101Bound*)second,(W101Bound*)(second+offset));unsigned actual_csr=_mm_getcsr();_mm_setcsr(0x1f80);
    int ok=original_csr==actual_csr&&!memcmp(first,second,sizeof(first));
    static unsigned detailed;
    if(!ok&&detailed++<4) {fprintf(stderr,"Mismatch csr=%x/%x edge=%d layout=%d\n",original_csr,actual_csr,edge,layout);
        for(unsigned i=0;i<4;i++) {uint32_t x,y;memcpy(&x,first+4*i,4);memcpy(&y,second+4*i,4);if(x!=y)fprintf(stderr,"Word %u %08x/%08x\n",i,x,y);}}
    return ok;
}
static double benchmark(W101Merge merge,unsigned count,unsigned shape) {
    W101Bound a={{1,2,3},shape==0?4:shape==1?1:10},b={{4,5,6},shape==0?3:shape==1?10:1},out;
    LARGE_INTEGER begin,end,hz;QueryPerformanceFrequency(&hz);QueryPerformanceCounter(&begin);
    for(unsigned i=0;i<count;i++) {out=a;out.xyz[0]+=(float)(i&31)*.0625f;merge(&out,&b);}
    QueryPerformanceCounter(&end);volatile float keep=out.radius;(void)keep;
    return(double)(end.QuadPart-begin.QuadPart)*1e9/hz.QuadPart/count;
}
int main(int argc,char**argv) {
    if(argc!=2)return 2;
    FILE*f=fopen(argv[1],"rb");if(!f)return 3;
    unsigned char *code=VirtualAlloc(NULL,4096,MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE);if(!code)return 4;
    size_t bytes=fread(code,1,4096,f);fclose(f);if(bytes!=391)return 5;
    memcpy(&epsilon,code+383,4);memcpy(&half,code+387,4);
    // The two original RIP-relative literals now refer to trailing fixture data.
    int32_t disp=(int32_t)(383-(0xeb));memcpy(code+0xe7,&disp,4);
    disp=(int32_t)(387-(0x146));memcpy(code+0x142,&disp,4);
    // Negative squared distance is unreachable; retain a sqrtf target anyway.
    code[512]=0xff;code[513]=0x25;memset(code+514,0,4);void*sqrt_target=(void*)sqrtf;memcpy(code+518,&sqrt_target,8);
    disp=(int32_t)(512-0xe1);memcpy(code+0xdd,&disp,4);
    DWORD old;if(!VirtualProtect(code,4096,PAGE_EXECUTE_READ,&old))return 6;
    FlushInstructionCache(GetCurrentProcess(),code,4096);reference=(W101Merge)code;
    unsigned tests=0,failed=0;
    for(unsigned rounding=0;rounding<4;rounding++)for(unsigned denormals=0;denormals<4;denormals++)for(unsigned edge=0;edge<2;edge++)
        for(unsigned i=0;i<24000;i++) {unsigned csr=0x1f80|(rounding<<13)|((denormals&1)?0x40:0)|((denormals&2)?0x8000:0)|(i&0x3f);tests++;if(!equivalent(csr,edge,i%6))failed++;}
    printf("{\"equivalence_cases\":%u,\"mismatches\":%u,\"fallback_calls\":%u,\"benchmarks_ns\":[",tests,failed,fallback_calls);
    for(unsigned shape=0;shape<3;shape++)for(unsigned pair=0;pair<5;pair++) {double orig,patch;
      if(pair&1){patch=benchmark(candidate,1000000,shape);orig=benchmark(reference,1000000,shape);}else {orig=benchmark(reference,1000000,shape);patch=benchmark(candidate,1000000,shape);}
      printf("%s{\"shape\":%u,\"original\":%.3f,\"candidate\":%.3f}",shape||pair?",":"",shape,orig,patch);}
    printf("],\"passed\":%s}\n",!failed?"true":"false");VirtualFree(code,0,MEM_RELEASE);return failed?7:0;
}
