#include "../decompression/Legacy.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(x) do{if(!(x)){fprintf(stderr,"FAIL line=%d %s\n",__LINE__,#x);exit(1);}}while(0)
static buffer_fn orig_buffer;static init_fn orig_init;static inflate_fn orig_inflate;static stream_fn orig_reset,orig_end;
static uint64_t (__cdecl *stats)(unsigned);
static void (__cdecl *hold)(uint64_t);
static int (__cdecl *compressor)(Bytef*,uLongf*,const Bytef*,uLong,int);
static unsigned failures,allocs,frees;
static Bytef *thread_input,*thread_raw;static uLong thread_count,thread_length;
static z_stream publishing_stream;
static int publication_initialized;
/* Deterministically open a stream after init is hooked but before inflate is
   hooked. It must stay on the original backend through reset and cleanup. */
__declspec(dllexport) void __cdecl W101DuringHookPublication(void) {
 CHECK(inflateInit_(&publishing_stream,"1.2.3",sizeof(publishing_stream))==Z_OK);
 publication_initialized=1;
}
static void * __cdecl custom_alloc(void *o,unsigned n,unsigned size) { (void)o;++allocs;return failures?NULL:calloc(n,size); }
static void __cdecl custom_free(void *o,void *p){(void)o;++frees;free(p);}
static void states(z_stream *a,z_stream *b,int ra,int rb,Bytef *ia,Bytef *ib,Bytef *oa,Bytef *ob) {
 if(ra!=rb || a->avail_in!=b->avail_in || a->avail_out!=b->avail_out || a->total_in!=b->total_in || a->total_out!=b->total_out || a->adler!=b->adler || a->data_type!=b->data_type || (!!a->msg)!=(!!b->msg) || (a->msg && strcmp(a->msg,b->msg))) {
  fprintf(stderr,"STATE r=%d/%d in=%lu/%lu out=%lu/%lu avail=%u/%u adler=%lu/%lu type=%d/%d msg=%s/%s\n",ra,rb,a->total_in,b->total_in,a->total_out,b->total_out,a->avail_in,b->avail_in,a->adler,b->adler,a->data_type,b->data_type,a->msg?a->msg:"",b->msg?b->msg:"");exit(2);
 }
 if(!a->next_in || !b->next_in)CHECK(a->next_in==b->next_in);else CHECK((a->next_in-ia)==(b->next_in-ib));
 if(!a->next_out || !b->next_out)CHECK(a->next_out==b->next_out);else CHECK((a->next_out-oa)==(b->next_out-ob));
 CHECK(a->zalloc==b->zalloc && a->zfree==b->zfree && a->opaque==b->opaque && a->reserved==b->reserved);
 CHECK(!!a->state==!!b->state);
}
static void stream_case(Bytef *src,uLong size,unsigned frag_in,unsigned frag_out,int flush,int custom,int existing) {
 Bytef *out1=malloc(8*1024*1024+32),*out2=malloc(8*1024*1024+32);CHECK(out1&&out2);
 memset(out1,0xCD,8*1024*1024);memset(out2,0xCD,8*1024*1024);
 z_stream a={0},b={0};if(custom){a.zalloc=b.zalloc=custom_alloc;a.zfree=b.zfree=custom_free;a.opaque=b.opaque=(void*)123;}
 int ra=orig_init(&a,"1.2.3",sizeof(a)),rb=(existing?orig_init:inflateInit_)(&b,"1.2.3",sizeof(b));CHECK(ra==rb);
 if(ra){CHECK(ra==Z_MEM_ERROR);free(out1);free(out2);return;}
 states(&a,&b,ra,rb,src,src,out1,out2);
 for(unsigned reset=0;reset<2;reset++) {
  unsigned pos=0;int done=0;
  for(unsigned step=0;step<200000 && !done;step++) {
   if(!a.avail_in && pos<size){unsigned n=size-pos;if(n>frag_in)n=frag_in;a.next_in=b.next_in=src+pos;a.avail_in=b.avail_in=n;pos+=n;}
   a.next_out=out1+a.total_out;b.next_out=out2+b.total_out;a.avail_out=b.avail_out=frag_out;
   CHECK(a.total_out+frag_out<=8*1024*1024);
   memset(a.next_out+frag_out,0xEF,32);memset(b.next_out+frag_out,0xEF,32);
   SetLastError(0x1234);ra=orig_inflate(&a,flush);DWORD ea=GetLastError();
   SetLastError(0x1234);rb=inflate(&b,flush);CHECK(ea==GetLastError());
   states(&a,&b,ra,rb,src,src,out1,out2);CHECK(!memcmp(out1,out2,a.total_out));
   for(unsigned guard=0;guard<32;guard++)CHECK(out1[a.total_out+a.avail_out+guard]==0xEF && out2[b.total_out+b.avail_out+guard]==0xEF);
   if(ra==Z_STREAM_END || ra==Z_NEED_DICT || ra==Z_DATA_ERROR || ra==Z_STREAM_ERROR || (pos==size && !a.avail_in && ra==Z_BUF_ERROR))done=1;
  }
  CHECK(done);
  CHECK(orig_reset(&a)==inflateReset(&b));
  states(&a,&b,Z_OK,Z_OK,src,src,out1,out2);
 }
 CHECK(orig_end(&a)==inflateEnd(&b));CHECK(!a.state&&!b.state);free(out1);free(out2);
}
static void buffer_case(Bytef *src,uLong size,uLong cap) {
 Bytef *a=malloc(cap+32),*b=malloc(cap+32);CHECK(a&&b);memset(a,0xBC,cap+32);memset(b,0xBC,cap+32);
 uLongf na=cap,nb=cap;SetLastError(0xABCD);int ra=orig_buffer(a,&na,src,size);DWORD error=GetLastError();
 SetLastError(0xABCD);int rb=uncompress(b,&nb,src,size);CHECK(GetLastError()==error);
 CHECK(ra==rb&&na==nb&&!memcmp(a,b,cap+32));free(a);free(b);
}
static double now(void){LARGE_INTEGER t,f;QueryPerformanceCounter(&t);QueryPerformanceFrequency(&f);return (double)t.QuadPart/f.QuadPart;}
static DWORD WINAPI concurrent(void *arg) {
 (void)arg;Bytef *output=malloc(thread_length);CHECK(output);
 for(unsigned i=0;i<3;i++){
  uLongf bytes=thread_length;CHECK(uncompress(output,&bytes,thread_input,thread_count)==Z_OK);CHECK(bytes==thread_length&&!memcmp(output,thread_raw,bytes));
  z_stream stream={0};CHECK(inflateInit_(&stream,"1.2.3",sizeof(stream))==Z_OK);stream.next_in=thread_input;stream.avail_in=thread_count;stream.next_out=output;stream.avail_out=thread_length;
  CHECK(inflate(&stream,4)==Z_STREAM_END);CHECK(stream.total_out==thread_length&&!memcmp(output,thread_raw,thread_length));CHECK(inflateEnd(&stream)==Z_OK);
  CHECK(stats(0)<=64ULL*1024*1024);
 }
 free(output);return 0;
}
static void dictionary(HMODULE z) {
 int (__cdecl *def_init)(z_streamp,int,const char*,int)=(void*)GetProcAddress(z,"deflateInit_");
 int (__cdecl *def_dict)(z_streamp,const Bytef*,uInt)=(void*)GetProcAddress(z,"deflateSetDictionary");
 inflate_fn deflate=(void*)GetProcAddress(z,"deflate");stream_fn def_end=(void*)GetProcAddress(z,"deflateEnd");
 int (__cdecl *set_dict)(z_streamp,const Bytef*,uInt)=(void*)GetProcAddress(z,"inflateSetDictionary");
 Bytef dict[]="Wizard101 dictionary",encoded[100],output[100];z_stream d={0};CHECK(def_init(&d,6,"1.2.3",sizeof(d))==Z_OK);CHECK(def_dict(&d,dict,sizeof(dict))==Z_OK);
 d.next_in=dict;d.avail_in=sizeof(dict);d.next_out=encoded;d.avail_out=sizeof(encoded);CHECK(deflate(&d,4)==Z_STREAM_END);unsigned count=d.total_out;CHECK(def_end(&d)==Z_OK);
 /* Dictionary setters are not game imports. These supported callers keep
    their original backend through initialization, dictionary, reset and end. */
 for(unsigned custom=0;custom<2;custom++){
  z_stream s={0};if(custom){s.zalloc=custom_alloc;s.zfree=custom_free;}
  CHECK((custom?inflateInit_:orig_init)(&s,"1.2.3",sizeof(s))==Z_OK);s.next_in=encoded;s.avail_in=count;s.next_out=output;s.avail_out=sizeof(output);
  CHECK(inflate(&s,0)==Z_NEED_DICT);CHECK(set_dict(&s,dict,sizeof(dict))==Z_OK);CHECK(inflate(&s,4)==Z_STREAM_END);CHECK(s.total_out==sizeof(dict)&&!memcmp(output,dict,sizeof(dict)));CHECK(inflateReset(&s)==Z_OK);CHECK(inflateEnd(&s)==Z_OK);
 }
}
static double bench(Bytef *src,uLong count,uLong output,int fast,int streaming) {
 Bytef *dst=malloc(output);CHECK(dst);double start=now();unsigned repeat=80;
 for(unsigned i=0;i<repeat;i++) {
  if(streaming){z_stream s={0};CHECK((fast?inflateInit_:orig_init)(&s,"1.2.3",sizeof(s))==Z_OK);s.next_in=src;s.avail_in=count;s.next_out=dst;s.avail_out=output;CHECK((fast?inflate:orig_inflate)(&s,4)==Z_STREAM_END);CHECK((fast?inflateEnd:orig_end)(&s)==Z_OK);}
  else {uLongf n=output;CHECK((fast?uncompress:orig_buffer)(dst,&n,src,count)==Z_OK);CHECK(n==output);}
 }
 double elapsed=now()-start;free(dst);return elapsed;
}
#ifdef W101_WAD_TEST
extern int __cdecl W101WadUncompress(Bytef*,uLongf*,const Bytef*,uLong);
static int buffer_enabled,wad_signature_valid;
static void wad_case(Bytef *src,uLong count,unsigned cap,int expect_hit) {
 Bytef *a=malloc(cap+16),*b=malloc(cap+16);CHECK(a&&b);memset(a,0xa5,cap+16);memset(b,0xa5,cap+16);
 uLongf na=cap,nb=cap;SetLastError(0x1379);int ra=orig_buffer(a,&na,src,count);DWORD ea=GetLastError();
 uint64_t before=stats(1);SetLastError(0x1379);int rb=W101WadUncompress(b,&nb,src,count);DWORD eb=GetLastError();
 CHECK(ra==rb && na==nb && ea==eb && !memcmp(a,b,cap+16));
 CHECK(stats(1)-before==(uint64_t)(expect_hit && buffer_enabled && wad_signature_valid));free(a);free(b);
}
static void small_wad_scope(void) {
 Bytef raw[32757],encoded[33000];uint32_t rng=19887;
 for(unsigned i=0;i<sizeof(raw);i++){rng^=rng<<13;rng^=rng>>17;rng^=rng<<5;raw[i]=rng;}
 const unsigned boundaries[]={1023,1024,32767,32768};
 for(unsigned index=0;index<4;index++) {
  unsigned n=boundaries[index]-32;uLongf count=0;
  for(;n<sizeof(raw);n++) {
   count=sizeof(encoded);CHECK(compressor(encoded,&count,raw,n,0)==Z_OK);
   if(count==boundaries[index])break;
  }
  CHECK(n<sizeof(raw) && count==boundaries[index]);
  uint64_t before=stats(1);buffer_case(encoded,count,n);
  CHECK(stats(1)-before==(uint64_t)(buffer_enabled && count>=32768));
  wad_case(encoded,count,n,count>=1024);
  wad_case(encoded,count,n-1,0);
  encoded[count-1]^=1;wad_case(encoded,count,n,0);encoded[count-1]^=1;
  uint64_t retained=stats(0);hold(64ULL*1024*1024);wad_case(encoded,count,n,0);hold(retained);
 }
 puts("PASS WAD caller 1023/1024/32767/32768 boundaries, caller scope, errors, scratch allocation fallback");
}
#endif
int main(int argc,char **argv) {
 CHECK(argc>=3);HMODULE z=LoadLibraryA("zlib1v142x64.dll");CHECK(z);
 orig_buffer=(buffer_fn)GetProcAddress(z,"uncompress");orig_init=(init_fn)GetProcAddress(z,"inflateInit_");orig_inflate=(inflate_fn)GetProcAddress(z,"inflate");orig_reset=(stream_fn)GetProcAddress(z,"inflateReset");orig_end=(stream_fn)GetProcAddress(z,"inflateEnd");
 compressor=(void*)GetProcAddress(z,"compress2");CHECK(compressor);
 HMODULE dll=LoadLibraryA(argv[1]);CHECK(dll);unsigned (__cdecl *install)(void)=(void*)GetProcAddress(dll,"W101InstallDecompression");CHECK(install);
 #ifdef W101_WAD_TEST
 buffer_enabled=!strcmp(getenv("W101_DECOMPRESS"),"buffer") || !strcmp(getenv("W101_DECOMPRESS"),"both");
 wad_signature_valid=strcmp(argv[2],"bad-signature")!=0;
 if(!wad_signature_valid) {
  unsigned char *p=(unsigned char*)GetModuleHandleA(NULL)+0x150934a;DWORD protection;
  CHECK(VirtualProtect(p,1,PAGE_EXECUTE_READWRITE,&protection));*p^=1;DWORD ignored;CHECK(VirtualProtect(p,1,protection,&ignored));
 }
#endif
 double startup=now();unsigned hooked=install();startup=now()-startup;printf("STARTUP seconds=%.9f\n",startup);if(!strcmp(argv[2],"reject")){
  CHECK(!hooked);struct {uint64_t in,out;uint32_t count,cap;uint64_t bytes;uint32_t operation,success;} p={0};
  LONG (WINAPI *native)(void*)=(void*)GetProcAddress(GetModuleHandleA("ntdll.dll"),"W101NativeDecode");if(native){native(&p);CHECK(!p.success);}
  puts("PASS unverified executable rejected");return 0;
 }int disabled=!strcmp(argv[2],"disabled");CHECK(disabled?hooked==0:hooked==5);
 stats=(void*)GetProcAddress(dll,"W101Stats");hold=(void*)GetProcAddress(dll,"W101BudgetHold");CHECK(stats&&hold);
 uint64_t base_retained=stats(0);
#ifdef W101_WAD_TEST
 if(!wad_signature_valid) {CHECK(!stats(3));puts("PASS mismatched WAD call signature disables small-buffer extension");return 0;}
 CHECK(stats(3));
 if(strcmp(argv[2],"reject") && strcmp(argv[2],"bench"))small_wad_scope();
#endif
 /* A mixture of repetition and random data, not a pure random-copy benchmark. */
 unsigned length=2*1024*1024;Bytef *raw=malloc(length),*src=malloc(4*1024*1024+1);CHECK(raw&&src);
 uint32_t rng=123456789;for(unsigned i=0;i<length;i++){rng^=rng<<13;rng^=rng>>17;rng^=rng<<5;raw[i]=(i%8192<3072)?rng:(i%127);}
 uLongf count=length+65536;CHECK(compressor(src,&count,raw,length,6)==Z_OK);CHECK(count>=32768);printf("fixture input=%lu output=%u\n",count,length);
 if(publication_initialized) {
  Bytef *out=malloc(length);CHECK(out);uint64_t before=stats(2);
  for(unsigned pass=0;pass<2;pass++) {
   publishing_stream.next_in=src;publishing_stream.avail_in=count;publishing_stream.next_out=out;publishing_stream.avail_out=length;
   CHECK(inflate(&publishing_stream,4)==Z_STREAM_END);CHECK(publishing_stream.total_out==length && !memcmp(out,raw,length));
   CHECK(inflateReset(&publishing_stream)==Z_OK);
  }
  CHECK(inflateEnd(&publishing_stream)==Z_OK && stats(2)==before);free(out);
  puts("PASS stream opened during hook publication retains original backend");
 }
 if(disabled) {
  buffer_case(src,count,length);stream_case(src,count,count,length,0,0,0);
  CHECK(stats(1)==0 && stats(2)==0);puts("PASS disabled original imports and stream backend");
 } else if(!strcmp(argv[2],"bench") || !strcmp(argv[2],"bench-one")) {
  unsigned pairs=!strcmp(argv[2],"bench-one")?1:5,paths=!strcmp(argv[2],"bench-one")?1:2;
  for(unsigned pair=0;pair<pairs;pair++)for(unsigned streaming=0;streaming<paths;streaming++){
   double a,b;if(pair%2){b=bench(src,count,length,1,streaming);a=bench(src,count,length,0,streaming);}else{a=bench(src,count,length,0,streaming);b=bench(src,count,length,1,streaming);}
   printf("PAIR path=%s pair=%u original=%.9f candidate=%.9f\n",streaming?"stream":"buffer",pair+1,a,b);fflush(stdout);
  }
 } else {
  buffer_case(src,count,length);buffer_case(src,count,length+16);buffer_case(src,count,length-1);buffer_case(src,count,0);
  buffer_case(src,count-1,length);src[count-1]^=1;buffer_case(src,count,length);src[count-1]^=1;
  buffer_case(src,32767,length);buffer_case(src,32768,length);
  memset(src+count,0,4*1024*1024+1-count);buffer_case(src,4*1024*1024,length);buffer_case(src,4*1024*1024+1,length);
  buffer_case(src,count,8*1024*1024);buffer_case(src,count,8*1024*1024+1);
  Bytef cmf=src[0],flg=src[1];for(unsigned window=0;window<8;window++){
   src[0]=(window<<4)|8;src[1]=0;src[1]=(31-(((unsigned)src[0]<<8)%31))%31;buffer_case(src,count,length);
  }src[0]=cmf;src[1]=flg;
  for(unsigned mutation=0;mutation<64;mutation++){unsigned pos=(mutation*12347+2)%count;src[pos]^=1u<<(mutation%8);buffer_case(src,count,length);src[pos]^=1u<<(mutation%8);}
  stream_case(src,count,count,length,0,0,0);stream_case(src,count,4093,8191,0,0,0);stream_case(src,count,997,4096,2,0,0);
  stream_case(src,count,count,length,4,0,0);stream_case(src,count-1,1009,65536,0,0,0);
  stream_case(src,count,4093,8191,5,0,0);stream_case(src,count,count,length,6,0,0);stream_case(src,count,count,length,-1,0,0);stream_case(src,count,count,length,99,0,0);
  src[count-1]^=1;stream_case(src,count,count,length,0,0,0);src[count-1]^=1;
  Bytef invalid[]={0x78,0x9c,0xff,0xff};stream_case(invalid,sizeof(invalid),4,16,0,0,0);
  Bytef dict[]={0x78,0xbb,0,0,0,1};stream_case(dict,sizeof(dict),6,16,0,0,0);
  stream_case(src,count,count,length,0,1,0);stream_case(src,count,count,length,0,0,1);
  failures=1;stream_case(src,count,count,length,0,1,0);failures=0;CHECK(allocs>=frees);
  dictionary(z);
  z_stream bad={0};CHECK(orig_init(&bad,"2.0",sizeof(bad))==inflateInit_(&bad,"2.0",sizeof(bad)));
  CHECK(orig_init(&bad,"1.2.3",1)==inflateInit_(&bad,"1.2.3",1));CHECK(orig_inflate(&bad,0)==inflate(&bad,0));
  CHECK(stats(0)==base_retained);hold(64ULL*1024*1024);buffer_case(src,count,length);stream_case(src,count,count,length,0,0,0);hold(base_retained);CHECK(stats(0)==base_retained);
  thread_input=src;thread_count=count;thread_raw=raw;thread_length=length;HANDLE threads[48];for(unsigned i=0;i<48;i++){threads[i]=CreateThread(NULL,0,concurrent,NULL,0,NULL);CHECK(threads[i]);}
  CHECK(WaitForMultipleObjects(48,threads,TRUE,30000)==WAIT_OBJECT_0);for(unsigned i=0;i<48;i++)CloseHandle(threads[i]);CHECK(stats(0)==base_retained);
  printf("PASS compatibility buffer_hits=%llu stream_hits=%llu retained=%llu\n",(unsigned long long)stats(1),(unsigned long long)stats(2),(unsigned long long)stats(0));
 }
 free(raw);free(src);return 0;
}
