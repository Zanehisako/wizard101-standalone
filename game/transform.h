/* Equivalent SSE2 composition for the verified 52-byte game transform ABI. */
#pragma once
#include <stdint.h>
#include <string.h>
#include <emmintrin.h>
typedef struct { float m[9], t[3], scale; } W101Transform;
typedef W101Transform *(*W101Compose)(const W101Transform *, W101Transform *, const W101Transform *);
/* C permits commutative operands to swap, including different NaN payloads.
   Keep the verified instruction operand order, with no FMA/reassociation. */
static inline __m128 w101_mul(__m128 left,__m128 right) {
    __asm__("mulps %1,%0" : "+x"(left) : "x"(right));return left;
}
static inline __m128 w101_add(__m128 left,__m128 right) {
    __asm__("addps %1,%0" : "+x"(left) : "x"(right));return left;
}
static inline __m128 w101_mul_one(__m128 left,__m128 right) {
    __asm__("mulss %1,%0" : "+x"(left) : "x"(right));return left;
}

static inline int w101_overlap(const void *a, const void *b) {
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return x-y<sizeof(W101Transform) || y-x<sizeof(W101Transform);
}
static inline __m128 w101_three(const float *p) {
    /* Duplicate a real lane: padding with zero would add 0*Inf exceptions. */
    return _mm_setr_ps(p[0],p[1],p[2],p[2]);
}
static inline void w101_store_three(float *p,__m128 v) {
    _mm_storel_pi((__m64*)p,v);
    _mm_store_ss(p+2,_mm_shuffle_ps(v,v,_MM_SHUFFLE(2,2,2,2)));
}
static inline W101Transform *w101_compose(const W101Transform *a,W101Transform *out,const W101Transform *b,W101Compose original) {
    /* The original writes scale before reading the other input fields. Keep
       every overlapping layout on that exact path. Operand ordering also
       preserves original NaN selection. Unmasked traps retain original order. */
    if(!a || !b || !out || w101_overlap(a,out) || w101_overlap(b,out) ||
       (_mm_getcsr()&0x1f80)!=0x1f80)
        return original(a,out,b);
    _mm_store_ss(&out->scale,w101_mul_one(_mm_set_ss(a->scale),_mm_set_ss(b->scale)));
    __m128 b0=w101_three(b->m),b1=w101_three(b->m+3),b2=w101_three(b->m+6);
    for(unsigned row=0;row<3;row++) {
        const float *r=a->m+3*row;
        __m128 p0=w101_mul(_mm_set1_ps(r[0]),b0);
        if(row==0) p0=_mm_move_ss(p0,w101_mul_one(_mm_set_ss(b->m[0]),_mm_set_ss(r[0])));
        __m128 p1=w101_mul(_mm_set1_ps(r[1]),b1);
        __m128 p2=w101_mul(_mm_set1_ps(r[2]),b2);
        w101_store_three(out->m+3*row,w101_add(w101_add(p0,p1),p2));
    }
    __m128 c0=_mm_setr_ps(a->m[0],a->m[3],a->m[6],a->m[6]);
    __m128 c1=_mm_setr_ps(a->m[1],a->m[4],a->m[7],a->m[7]);
    __m128 c2=_mm_setr_ps(a->m[2],a->m[5],a->m[8],a->m[8]);
    __m128 translated=w101_add(w101_add(w101_mul(c0,_mm_set1_ps(b->t[0])),
                                          w101_mul(c1,_mm_set1_ps(b->t[1]))),
                                          w101_mul(c2,_mm_set1_ps(b->t[2])));
    translated=w101_add(w101_mul(translated,_mm_set1_ps(a->scale)),w101_three(a->t));
    w101_store_three(out->t,translated);
    return out;
}
