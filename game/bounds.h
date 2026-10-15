#pragma once
#include "transform.h"
typedef struct { float xyz[3],radius; } W101Bound;
typedef void (*W101Merge)(W101Bound*,const W101Bound*);
static inline __m128 w101_sub(__m128 left,__m128 right) {
    __asm__("subps %1,%0" : "+x"(left) : "x"(right));return left;
}
static inline __m128 w101_add_one(__m128 left,__m128 right) {
    __asm__("addss %1,%0" : "+x"(left) : "x"(right));return left;
}
static inline __m128 w101_sub_one(__m128 left,__m128 right) {
    __asm__("subss %1,%0" : "+x"(left) : "x"(right));return left;
}
static inline __m128 w101_div_one(__m128 left,__m128 right) {
    __asm__("divss %1,%0" : "+x"(left) : "x"(right));return left;
}
static inline int w101_below(__m128 left,__m128 right) {
    unsigned char result;__asm__("comiss %2,%1; setb %0" : "=qm"(result) : "x"(left),"x"(right) : "cc");return result;
}
static inline int w101_below_equal(__m128 left,__m128 right) {
    unsigned char result;__asm__("comiss %2,%1; setbe %0" : "=qm"(result) : "x"(left),"x"(right) : "cc");return result;
}
static inline void w101_merge(W101Bound *out,const W101Bound *source,W101Merge original,const float *epsilon,const float *half) {
    uintptr_t a=(uintptr_t)out,b=(uintptr_t)source;
    if(!out || !source || a-b<16 || b-a<16 || (_mm_getcsr()&0x1f80)!=0x1f80) {original(out,source);return;}
    __m128 destination=_mm_loadu_ps(out->xyz),input=_mm_loadu_ps(source->xyz);
    __m128 delta=w101_sub(_mm_shuffle_ps(destination,destination,_MM_SHUFFLE(2,2,1,0)),
                         _mm_shuffle_ps(input,input,_MM_SHUFFLE(2,2,1,0)));
    __m128 squares=w101_mul(delta,delta);
    __m128 source_radius=_mm_set_ss(source->radius),destination_radius=_mm_set_ss(out->radius);
    __m128 dr=w101_sub_one(source_radius,destination_radius);
    __m128 squared_dr=w101_mul_one(dr,dr);
    __m128 squared_distance=w101_add_one(_mm_shuffle_ps(squares,squares,_MM_SHUFFLE(1,1,1,1)),squares);
    squared_distance=w101_add_one(squared_distance,_mm_shuffle_ps(squares,squares,_MM_SHUFFLE(2,2,2,2)));
    __m128 zero=_mm_setzero_ps();
    __asm__ goto("comiss %1,%0; jb %l2" :: "x"(dr),"x"(zero) : "cc" : negative);
    __asm__ goto("comiss %1,%0; jb %l2" :: "x"(squared_dr),"x"(squared_distance) : "cc" : combine);
    _mm_storeu_ps(out->xyz,input);return;
negative:
    __asm__ goto("comiss %1,%0; jbe %l2" :: "x"(squared_distance),"x"(squared_dr) : "cc" : done);
combine:;
    __m128 distance=_mm_sqrt_ss(squared_distance);
    __m128 threshold=_mm_load_ss(epsilon);
    __asm__ goto("comiss %1,%0; jbe %l2" :: "x"(distance),"x"(threshold) : "cc" : radius_only);
    {
        __m128 coefficient=w101_div_one(w101_sub_one(distance,dr),w101_add_one(distance,distance));
        delta=_mm_shuffle_ps(delta,delta,_MM_SHUFFLE(2,2,1,0));
        input=_mm_shuffle_ps(input,input,_MM_SHUFFLE(2,2,1,0));
        __m128 center=w101_add(w101_mul(_mm_shuffle_ps(coefficient,coefficient,0),delta),input);
        w101_store_three(out->xyz,center);
    }
radius_only:;
    __m128 radius=w101_add_one(w101_add_one(source_radius,distance),destination_radius);
    _mm_store_ss(&out->radius,w101_mul_one(radius,_mm_load_ss(half)));
done:;
}
