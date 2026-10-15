#pragma once
#include <windows.h>
#include <stdint.h>
typedef unsigned char Bytef;
typedef unsigned int uInt;
typedef unsigned long uLong;
typedef uLong uLongf;
typedef void *(__cdecl *alloc_func)(void*,uInt,uInt);
typedef void (__cdecl *free_func)(void*,void*);
typedef struct {
 Bytef *next_in;uInt avail_in;uLong total_in;
 Bytef *next_out;uInt avail_out;uLong total_out;
 char *msg;void *state;alloc_func zalloc;free_func zfree;void *opaque;
 int data_type;uLong adler;uLong reserved;
} z_stream,*z_streamp;
typedef int (__cdecl *buffer_fn)(Bytef*,uLongf*,const Bytef*,uLong);
typedef int (__cdecl *init_fn)(z_streamp,const char*,int);
typedef int (__cdecl *inflate_fn)(z_streamp,int);
typedef int (__cdecl *stream_fn)(z_streamp);
#define Z_OK 0
#define Z_STREAM_END 1
#define Z_NEED_DICT 2
#define Z_STREAM_ERROR -2
#define Z_DATA_ERROR -3
#define Z_MEM_ERROR -4
#define Z_BUF_ERROR -5
__declspec(dllimport) int __cdecl uncompress(Bytef*,uLongf*,const Bytef*,uLong);
__declspec(dllimport) int __cdecl inflateInit_(z_streamp,const char*,int);
__declspec(dllimport) int __cdecl inflate(z_streamp,int);
__declspec(dllimport) int __cdecl inflateReset(z_streamp);
__declspec(dllimport) int __cdecl inflateEnd(z_streamp);
