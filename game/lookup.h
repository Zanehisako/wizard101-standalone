/* Equivalent binary search. No memoization, lifetime or ordering changes. */
#pragma once
#include <stdint.h>
typedef void *(*W101Lookup)(const void *,const uint64_t *);
static inline void *w101_lookup(const void *object,const uint64_t *key,const uint64_t *empty) {
    uint64_t sentinel=*(const volatile uint64_t*)empty;
    if(*(const volatile uint64_t*)key==sentinel)return 0;
    int16_t low=0,high=(int16_t)(*(const volatile uint16_t*)((const char*)object+0x28)-1);
    while(low<=high) {
        int16_t mid=(int16_t)(((int32_t)low+(int32_t)high)>>1);
        void **array=*(void **const volatile*)((const char*)object+0x20);
        void *item=*(void *const volatile*)(array+mid);
        // The approved direct getter is exactly LEA RAX,[RCX+0x10]; RET.
        uint64_t wanted=*(const volatile uint64_t*)key;
        uint64_t found=*(const volatile uint64_t*)((const char*)item+0x10);
        int64_t delta=(int64_t)(wanted-found); // original wrapping SUB, then TEST
        if(!delta) {
            array=*(void **const volatile*)((const char*)object+0x20);
            return *(void *const volatile*)(array+mid);
        }
        if(delta<=0)high=(int16_t)(mid-1);
        else low=(int16_t)(mid+1);
    }
    return 0;
}
