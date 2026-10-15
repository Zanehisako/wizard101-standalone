#pragma once
#include <stdint.h>
#define W101_ARENA_BYTES (32u*1024*1024)
#define W101_INPUT_MAX (4u*1024*1024)
#define W101_OUTPUT_MAX (8u*1024*1024)
#define W101_SLOT_BYTES (W101_INPUT_MAX+W101_OUTPUT_MAX)
enum {W101_EMPTY=0,W101_BUSY=1,W101_DONE=2,W101_QUARANTINED=3};
typedef struct __attribute__((aligned(128))) {
 uint32_t state,input_bytes,output_cap,result;
 uint64_t sequence,output_bytes;
 unsigned char padding[96];
} w101_decode_slot;
typedef struct {uint32_t magic,version;uint64_t reserved;w101_decode_slot slots[2];} w101_arena;
typedef struct {uint64_t sequence;uint32_t slot,kind;} w101_message;
typedef struct {
 uint64_t input,output;uint32_t input_bytes,output_cap;
 uint64_t output_bytes;uint32_t operation,success;
} w101_decode_params;
static unsigned char *w101_slot_input(void *arena,unsigned slot){return (unsigned char*)arena+4096+slot*W101_SLOT_BYTES;}
static unsigned char *w101_slot_output(void *arena,unsigned slot){return w101_slot_input(arena,slot)+W101_INPUT_MAX;}
