#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include "../game/transform.h"
static W101Compose reference;
static volatile unsigned fallback_calls;
static W101Transform *fallback(const W101Transform*a,W101Transform*out,const W101Transform*b) {
    fallback_calls++;return reference(a,out,b);
}
__attribute__((noinline)) static W101Transform *candidate(const W101Transform*a,W101Transform*out,const W101Transform*b) {
    return w101_compose(a,out,b,fallback);
}
static uint64_t state=0x2391042;
static uint32_t random32(void) { state^=state<<13;state^=state>>7;state^=state<<17;return (uint32_t)state; }
static void fill(W101Transform *t,int edge) {
    for(unsigned i=0;i<13;i++) {
        uint32_t bits;
        if(edge) bits=random32();
        else bits=(random32()&0x807fffff)|((112+random32()%32)<<23);
        memcpy((char*)t+4*i,&bits,4);
    }
}
static int equivalent(unsigned csr,int edge,int layout) {
    unsigned char first[260],second[260];
    for(unsigned i=0;i<sizeof(first);i++) first[i]=(unsigned char)random32();
    fill((W101Transform*)first,edge);fill((W101Transform*)(first+64),edge);
    unsigned offset=layout==0?128:layout==1?0:layout==2?64:layout==3?4:layout==4?60:layout==5?68:layout==6?48:112;
    memcpy(second,first,sizeof(first));
    W101Transform *a=(W101Transform*)first,*b=(W101Transform*)(first+64),*out=(W101Transform*)(first+offset);
    _mm_setcsr(csr); W101Transform *returned=reference(a,out,b);unsigned original_csr=_mm_getcsr();
    _mm_setcsr(csr); W101Transform *actual=candidate((W101Transform*)second,(W101Transform*)(second+offset),(W101Transform*)(second+64));
    unsigned actual_csr=_mm_getcsr();_mm_setcsr(0x1f80);
    int ok=returned==out && actual==(W101Transform*)(second+offset) && original_csr==actual_csr && !memcmp(first,second,sizeof(first));
    static unsigned detailed;
    if(!ok && detailed++<3) {
        fprintf(stderr,"CSR original=%x candidate=%x\n",original_csr,actual_csr);
        for(unsigned i=0;i<13;i++) {uint32_t x,y;memcpy(&x,first+offset+4*i,4);memcpy(&y,second+offset+4*i,4);
          if(x!=y)fprintf(stderr,"Output word %u original=%08x candidate=%08x\n",i,x,y);}
    }
    return ok;
}
static double benchmark(W101Compose compose,unsigned count) {
    W101Transform a,b,out;fill(&a,0);fill(&b,0);LARGE_INTEGER begin,end,hz;
    QueryPerformanceFrequency(&hz);QueryPerformanceCounter(&begin);
    for(unsigned i=0;i<count;i++) { a.t[0]=(float)(i&255)*.25f;compose(&a,&out,&b); }
    QueryPerformanceCounter(&end);
    volatile float retain=out.t[0];(void)retain;
    return (double)(end.QuadPart-begin.QuadPart)*1e9/hz.QuadPart/count;
}
int main(int argc,char**argv) {
    if(argc!=2)return 2;
    FILE*f=fopen(argv[1],"rb");if(!f)return 3;
    unsigned char *code=VirtualAlloc(NULL,4096,MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE);
    if(!code)return 4;
    size_t bytes=fread(code,1,4096,f);fclose(f);if(bytes!=810)return 5;
    DWORD old;if(!VirtualProtect(code,4096,PAGE_EXECUTE_READ,&old))return 6;
    FlushInstructionCache(GetCurrentProcess(),code,bytes);reference=(W101Compose)code;
    unsigned tests=0,failed=0;
    for(unsigned rounding=0;rounding<4;rounding++)for(unsigned denormals=0;denormals<4;denormals++)for(unsigned edge=0;edge<2;edge++)
      for(unsigned i=0;i<20000;i++) {unsigned csr=0x1f80|(rounding<<13)|((denormals&1)?0x40:0)|((denormals&2)?0x8000:0)|(i&0x3f);
        tests++;if(!equivalent(csr,edge,(int)(i%8))) {failed++;if(failed<5)fprintf(stderr,"Mismatch csr=%x edge=%u layout=%u\n",csr,edge,i%8);}}
    unsigned before=fallback_calls;
    // Unmask precision with exact identity/zero inputs: this must use original.
    W101Transform a={.m={1,0,0,0,1,0,0,0,1},.scale=1},b=a,out;
    _mm_setcsr(0x0f80);unsigned requested_control=_mm_getcsr();candidate(&a,&out,&b);_mm_setcsr(0x1f80);
    int unmasked_supported=(requested_control&0x1f80)!=0x1f80;
    int traps_fallback=!unmasked_supported||fallback_calls==before+1;
    printf("{\"equivalence_cases\":%u,\"mismatches\":%u,\"fallback_calls\":%u,\"unmasked_control_supported\":%s,\"unmasked_original_path\":%s,\"benchmarks_ns\":[",tests,failed,fallback_calls,unmasked_supported?"true":"false",unmasked_supported?(traps_fallback?"true":"false"):"null");
    for(unsigned pair=0;pair<7;pair++) {double original_ns,patched_ns;
      if(pair&1){patched_ns=benchmark(candidate,1500000);original_ns=benchmark(reference,1500000);}
      else {original_ns=benchmark(reference,1500000);patched_ns=benchmark(candidate,1500000);}
      printf("%s{\"original\":%.3f,\"candidate\":%.3f}",pair?",":"",original_ns,patched_ns);}
    printf("],\"passed\":%s}\n",!failed&&traps_fallback?"true":"false");
    VirtualFree(code,0,MEM_RELEASE);return failed||!traps_fallback?7:0;
}
