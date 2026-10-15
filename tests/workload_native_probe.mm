#import <Metal/Metal.h>
#include "WorkloadNative.h"
#include <cassert>
#include <cstring>
int main(int argc,char**argv) {
  @autoreleasepool {
    if(argc<2) return 2;
    if(!strcmp(argv[1],"disabled")) { assert(!w101::configured()); assert(!w101::recorder().enabled()); return 0; }
    auto& r=w101::recorder();
    if(!strcmp(argv[1],"invalid_path")) { assert(!r.enabled()); return 0; }
    assert(r.enabled());
    if(!strcmp(argv[1],"gpu")) {
      id<MTLDevice> device=MTLCreateSystemDefaultDevice(); assert(device);
      id<MTLCommandQueue> queue=[device newCommandQueue]; id<MTLBuffer> buffer=[device newBufferWithLength:4096 options:MTLResourceStorageModeShared];
      for(int i=0;i<16;++i) {
        id<MTLCommandBuffer> cmd=[queue commandBuffer]; id<MTLBlitCommandEncoder> blit=[cmd blitCommandEncoder];
        [blit fillBuffer:buffer range:NSMakeRange(0,4096) value:0x42]; [blit endEncoding];
        w101::observe(cmd,123,0,0); [cmd commit]; [cmd waitUntilCompleted]; assert(((char*)buffer.contents)[0]==0x42);
      }
      std::this_thread::sleep_for(std::chrono::milliseconds(600));
      [buffer release]; [queue release]; [device release]; r.shutdown();
    } else if(!strcmp(argv[1],"size")) {
      for(int i=0;i<1000000 && r.enabled();++i) { const auto id=r.begin(); if(id) { const auto now=w101::machUs(); r.completed({id,now,now,now-2,now-1,1,1,0,0,4}); } }
      r.shutdown();
    } else if(!strcmp(argv[1],"time")) {
      std::this_thread::sleep_for(std::chrono::milliseconds(1400)); assert(!r.enabled()); r.shutdown();
    } else if(!strcmp(argv[1],"outstanding")) {
      uint64_t ids[256]; for(int i=0;i<256;++i) { ids[i]=r.begin(); assert(ids[i]); } assert(!r.begin());
      for(auto id:ids) { const auto now=w101::machUs(); r.completed({id,now,now,now-2,now-1,1,1,0,0,4}); }
      r.shutdown();
    } else return 2;
  }
  puts("PASS native workload");
}
