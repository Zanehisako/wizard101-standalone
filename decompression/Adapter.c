/* Main-executable IAT adapter. Original zlib remains installed and loaded. */
#include <windows.h>
#include <bcrypt.h>
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include "zlib.h"
#include "libdeflate.h"
#include "Identity.h"
#ifdef W101_NATIVE
#include "NativeProtocol.h"
static int native_auto,native_ready;
static LONG (WINAPI *native_call)(w101_decode_params*);
#endif

typedef int (__cdecl *uncompress_fn)(Bytef*,uLongf*,const Bytef*,uLong);
typedef int (__cdecl *init_fn)(z_streamp,const char*,int);
typedef int (__cdecl *inflate_fn)(z_streamp,int);
typedef int (__cdecl *stream_fn)(z_streamp);
static uncompress_fn original_buffer;
static init_fn original_init;
static inflate_fn original_inflate;
static stream_fn original_reset,original_end;
static unsigned mode;
static const void *wad_return;
static volatile LONG hooks_ready;
static volatile LONG64 retained,buffer_hits,stream_hits;
#define BUDGET (64ULL*1024*1024)
/* Count actual heap requests, including headers. Static map < 16 KiB. */
typedef union { struct { size_t size; } h; max_align_t alignment; } allocation;
static void *budget_malloc(size_t n) {
    size_t total=n+sizeof(allocation); LONG64 old;
    if(n> BUDGET-sizeof(allocation)) return NULL;
    do { old=retained; if((uint64_t)old+total>BUDGET-16384) return NULL; }
    while(InterlockedCompareExchange64(&retained,old+total,old)!=old);
    allocation *p=malloc(total);
    if(!p) { InterlockedExchangeAdd64(&retained,-(LONG64)total); return NULL; }
    p->h.size=total; return p+1;
}
static void budget_free(void *p) {
    if(p) { allocation *a=(allocation*)p-1; size_t n=a->h.size; free(a); InterlockedExchangeAdd64(&retained,-(LONG64)n); }
}
static voidpf ng_alloc(voidpf opaque,uInt n,uInt size) {
    (void)opaque; if(size && n>SIZE_MAX/size) return NULL;
    return budget_malloc((size_t)n*size);
}
static void ng_free(voidpf opaque,voidpf p) { (void)opaque; budget_free(p); }
typedef struct stream_record { z_streamp public_stream; z_stream ng; struct stream_record *next; } stream_record;
static stream_record *streams[1024];
static SRWLOCK stream_lock=SRWLOCK_INIT;
static unsigned bucket(z_streamp s) { return ((uintptr_t)s>>4)%1024; }
static stream_record *lookup(z_streamp s) {
    stream_record *p; AcquireSRWLockShared(&stream_lock);
    for(p=streams[bucket(s)];p && p->public_stream!=s;p=p->next) {}
    ReleaseSRWLockShared(&stream_lock); return p;
}
static void to_backend(stream_record *p) {
    p->ng.next_in=p->public_stream->next_in; p->ng.avail_in=p->public_stream->avail_in;
    p->ng.next_out=p->public_stream->next_out; p->ng.avail_out=p->public_stream->avail_out;
}
static void to_public(stream_record *p) {
    z_streamp s=p->public_stream;
    s->next_in=p->ng.next_in; s->avail_in=p->ng.avail_in; s->total_in=p->ng.total_in;
    s->next_out=p->ng.next_out; s->avail_out=p->ng.avail_out; s->total_out=p->ng.total_out;
    s->msg=p->ng.msg; s->data_type=p->ng.data_type; s->adler=p->ng.adler;
    /* state, allocator functions and opaque remain original-zlib values. */
}
__declspec(dllexport) int __cdecl W101Uncompress(Bytef *dst,uLongf *length,const Bytef *src,uLong count) {
    DWORD error=GetLastError(); int result; size_t actual=0;
    if(!(mode&1)
#ifdef W101_NATIVE
       && !native_ready
#endif
       )return original_buffer(dst,length,src,count);
    if(!dst || !length || !src || count<((mode&1) && __builtin_return_address(0)==wad_return ? 1024u : 32768u) || count>4*1024*1024 || !*length || *length>8*1024*1024)
        return original_buffer(dst,length,src,count);
    Bytef *scratch=budget_malloc(*length);
#ifdef W101_NATIVE
    if(native_ready && scratch && count>=256*1024) {
        w101_decode_params params={(uint64_t)(uintptr_t)src,(uint64_t)(uintptr_t)scratch,count,*length,0,1,0};
        native_call(&params);
        if(params.success){memcpy(dst,scratch,params.output_bytes);*length=(uLongf)params.output_bytes;budget_free(scratch);InterlockedIncrement64(&buffer_hits);SetLastError(error);return Z_OK;}
    }
    if(!(mode&1)){budget_free(scratch);SetLastError(error);return original_buffer(dst,length,src,count);}
#endif
    struct libdeflate_options options={0}; options.sizeof_options=sizeof(options);
    options.malloc_func=budget_malloc; options.free_func=budget_free;
    struct libdeflate_decompressor *d=scratch?libdeflate_alloc_decompressor_ex(&options):NULL;
    result=d?libdeflate_zlib_decompress(d,src,count,scratch,*length,&actual):LIBDEFLATE_BAD_DATA;
    if(result==LIBDEFLATE_SUCCESS) { memcpy(dst,scratch,actual); *length=(uLongf)actual; InterlockedIncrement64(&buffer_hits); }
    libdeflate_free_decompressor(d); budget_free(scratch); SetLastError(error);
    if(result==LIBDEFLATE_SUCCESS) return Z_OK;
    return original_buffer(dst,length,src,count);
}
__declspec(dllexport) int __cdecl W101InflateInit(z_streamp s,const char *version,int size) {
    BOOL custom=s && (s->zalloc || s->zfree); int result=original_init(s,version,size);DWORD error=GetLastError();
    if(result!=Z_OK || !(mode&2) || custom || !InterlockedCompareExchange(&hooks_ready,0,0)) return result;
    stream_record *p=budget_malloc(sizeof(*p));
    if(p) {
        memset(p,0,sizeof(*p));p->public_stream=s;p->ng.zalloc=ng_alloc;p->ng.zfree=ng_free;
        /* Use the pinned backend's version; original already validated caller ABI. */
        if(inflateInit2_(&p->ng,15,ZLIB_VERSION,sizeof(z_stream))==Z_OK) {
            AcquireSRWLockExclusive(&stream_lock);p->next=streams[bucket(s)];streams[bucket(s)]=p;ReleaseSRWLockExclusive(&stream_lock);
        } else budget_free(p);
    }
    SetLastError(error);return result;
}
__declspec(dllexport) int __cdecl W101Inflate(z_streamp s,int flush) {
    stream_record *p=lookup(s);if(!p) return original_inflate(s,flush);
    if(!s->state || !s->next_out || (!s->next_in && s->avail_in))return Z_STREAM_ERROR;
    /* 1.2.3 treats all other flush integers as ordinary inflation, including
       the later Z_TREES value. Do not expose newer backend semantics. */
    int effective=(flush==Z_FINISH || flush==Z_BLOCK)?flush:Z_NO_FLUSH;
    DWORD error=GetLastError();to_backend(p);int result=inflate(&p->ng,effective);to_public(p);
    InterlockedIncrement64(&stream_hits);SetLastError(error);return result;
}
__declspec(dllexport) int __cdecl W101InflateReset(z_streamp s) {
    stream_record *p=lookup(s);if(!p)return original_reset(s);
    if(!s->state)return Z_STREAM_ERROR;
    DWORD error=GetLastError();to_backend(p);int result=inflateReset(&p->ng);to_public(p);SetLastError(error);return result;
}
__declspec(dllexport) int __cdecl W101InflateEnd(z_streamp s) {
    stream_record *p=lookup(s);if(!p)return original_end(s);
    if(!s->state || !s->zfree)return Z_STREAM_ERROR;
    DWORD error=GetLastError();int result=inflateEnd(&p->ng);
    AcquireSRWLockExclusive(&stream_lock);stream_record **slot=&streams[bucket(s)];
    while(*slot && *slot!=p)slot=&(*slot)->next;if(*slot)*slot=p->next;ReleaseSRWLockExclusive(&stream_lock);
    original_end(s);budget_free(p);SetLastError(error);return result;
}
static BOOL file_hash(const char *path,const char *expected) {
    HANDLE file=CreateFileA(path,GENERIC_READ,FILE_SHARE_READ,NULL,OPEN_EXISTING,0,NULL);
    if(file==INVALID_HANDLE_VALUE)return FALSE;
    BCRYPT_ALG_HANDLE alg=NULL;BCRYPT_HASH_HANDLE hash=NULL;BOOL ok=FALSE;unsigned char digest[32],block[65536];DWORD count;
    if(BCryptOpenAlgorithmProvider(&alg,BCRYPT_SHA256_ALGORITHM,NULL,0)>=0 && BCryptCreateHash(alg,&hash,NULL,0,NULL,0,0)>=0) {
        BOOL read;
        while((read=ReadFile(file,block,sizeof(block),&count,NULL)) && count)if(BCryptHashData(hash,block,count,0)<0){read=FALSE;break;}
        if(read && BCryptFinishHash(hash,digest,sizeof(digest),0)>=0) {
            char hex[65];const char *digits="0123456789abcdef";
            for(unsigned i=0;i<32;i++){hex[2*i]=digits[digest[i]>>4];hex[2*i+1]=digits[digest[i]&15];}hex[64]=0;
            ok=!strcmp(hex,expected);
        }
    }
    if(hash)BCryptDestroyHash(hash);if(alg)BCryptCloseAlgorithmProvider(alg,0);CloseHandle(file);return ok;
}
typedef struct {const char *name;void *replacement;void **original;ULONG_PTR *slot;DWORD protection;} hook;
__declspec(dllexport) unsigned __cdecl W101InstallDecompression(void) {
    static LONG installed;DWORD incoming=GetLastError();unsigned result=0;char value[16]={0},path[32768];
    GetEnvironmentVariableA("W101_DECOMPRESS",value,sizeof(value));
    if(!strcmp(value,"buffer"))mode=1;else if(!strcmp(value,"stream"))mode=2;else if(!strcmp(value,"both"))mode=3;else mode=0;
#ifdef W101_NATIVE
    char native_value[16]={0};GetEnvironmentVariableA("W101_NATIVE_DECODE",native_value,sizeof(native_value));native_auto=!strcmp(native_value,"auto");
    if((!mode && !native_auto) || InterlockedCompareExchange(&installed,1,0))goto done;
#else
    if(!mode || InterlockedCompareExchange(&installed,1,0))goto done;
#endif
    GetModuleFileNameA(NULL,path,sizeof(path));
#ifdef W101_TEST_HASH
    if(!file_hash(path,W101_TEST_HASH))goto done;
#else
    if(!file_hash(path,W101_GAME_SHA256))goto done;
#endif
    HMODULE z=GetModuleHandleA(W101_ZLIB_DLL);
    if(!z || !GetModuleFileNameA(z,path,sizeof(path)) || !file_hash(path,W101_ZLIB_SHA256))goto done;
    if(strcmp(((const char*(__cdecl*)(void))GetProcAddress(z,"zlibVersion"))(),"1.2.3"))goto done;
    hook hooks[]={
        {"uncompress",W101Uncompress,(void**)&original_buffer,NULL,0},
        {"inflateInit_",W101InflateInit,(void**)&original_init,NULL,0},
        {"inflate",W101Inflate,(void**)&original_inflate,NULL,0},
        {"inflateReset",W101InflateReset,(void**)&original_reset,NULL,0},
        {"inflateEnd",W101InflateEnd,(void**)&original_end,NULL,0}};
    unsigned char *base=(unsigned char*)GetModuleHandleA(NULL);
    IMAGE_NT_HEADERS *nt=(IMAGE_NT_HEADERS*)(base+((IMAGE_DOS_HEADER*)base)->e_lfanew);
    IMAGE_IMPORT_DESCRIPTOR *imports=(void*)(base+nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT].VirtualAddress);
    for(;imports->Name;imports++) {
        if(_stricmp((char*)base+imports->Name,W101_ZLIB_DLL) || !imports->OriginalFirstThunk)continue;
        IMAGE_THUNK_DATA *names=(void*)(base+imports->OriginalFirstThunk),*slots=(void*)(base+imports->FirstThunk);
        for(;names->u1.AddressOfData;names++,slots++) {
            if(IMAGE_SNAP_BY_ORDINAL(names->u1.Ordinal))continue;
            const char *name=(const char*)((IMAGE_IMPORT_BY_NAME*)(base+names->u1.AddressOfData))->Name;
            for(unsigned i=0;i<5;i++)if(!strcmp(name,hooks[i].name))hooks[i].slot=&slots->u1.Function;
        }
    }
    /* The small-buffer extension is restricted to the verified WAD call and
       its uncompress IAT thunk. A different caller retains the 32 KiB floor. */
    static const unsigned char signature[]={0x48,0x8d,0x94,0x24,0x90,0,0,0,0x48,0x8b,0xcf,0xe8,0xce,0xff,0xf4,0};
    if(nt->OptionalHeader.SizeOfImage>0x245932e &&
       !memcmp(base+0x150934a,signature,sizeof(signature)) &&
       base[0x2459328]==0xff && base[0x2459329]==0x25) {
        int32_t displacement;memcpy(&displacement,base+0x245932a,4);
        if(base + 0x245932e + displacement==(unsigned char*)hooks[0].slot)
            wad_return=base+0x150935a;
    }
    /* Validate and make all pages writable before publishing any replacement. */
    for(unsigned i=0;i<5;i++) {
        *hooks[i].original=(void*)GetProcAddress(z,hooks[i].name);
        if(!hooks[i].slot || !*hooks[i].original || (void*)*hooks[i].slot!=*hooks[i].original)goto done;
    }
#ifdef W101_NATIVE
    if(native_auto) {
        native_call=(void*)GetProcAddress(GetModuleHandleA("ntdll.dll"),"W101NativeDecode");
        if(native_call){w101_decode_params start={0};native_call(&start);native_ready=start.success;if(native_ready)InterlockedExchangeAdd64(&retained,34LL*1024*1024);}
    }
#endif
    unsigned writable=0;
    for(;writable<5;writable++)if(!VirtualProtect(hooks[writable].slot,sizeof(void*),PAGE_READWRITE,&hooks[writable].protection))break;
    if(writable==5) {
        for(unsigned i=0;i<5;i++) {
            InterlockedExchangePointer((void*volatile*)hooks[i].slot,hooks[i].replacement);
#ifdef W101_TEST_HASH
            if(i==1) {
                void (__cdecl *during_publication)(void)=(void*)GetProcAddress((HMODULE)base,"W101DuringHookPublication");
                if(during_publication)during_publication();
            }
#endif
        }
        /* A stream initialized while imports are being published must remain
           original-backed. Admit shadow streams only after all hooks exist. */
        InterlockedExchange(&hooks_ready,1);
    }
    while(writable){DWORD ignored;--writable;VirtualProtect(hooks[writable].slot,sizeof(void*),hooks[writable].protection,&ignored);}
    if((void*)*hooks[0].slot==hooks[0].replacement)result=5;
done:SetLastError(incoming);return result;
}
#ifdef W101_TEST_HASH
__declspec(dllexport) uint64_t W101Stats(unsigned which) {return which==0?retained:which==1?buffer_hits:which==3?(wad_return!=NULL):stream_hits;}
__declspec(dllexport) void W101BudgetHold(uint64_t bytes) {InterlockedExchange64(&retained,bytes);}
#endif
