#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <cstdio>
#include <cstring>
#include "../performance/ArrivalMetalArchive.h"

int main(int argc,char **argv) {
    if(argc!=2)return 2;
    @autoreleasepool {
        const char *mode=argv[1];bool saveFailure=!strcmp(mode,"save-failure"),fallback=!strcmp(mode,"fallback");
        bool create=!strcmp(mode,"create")||saveFailure,warm=!strcmp(mode,"warm"),mismatch=!strcmp(mode,"mismatch");
        id<MTLDevice> device=MTLCreateSystemDefaultDevice();if(!device)return 3;
        NSError *error=nil;
        NSString *code=@"#include <metal_stdlib>\nusing namespace metal;\nvertex float4 v(uint i [[vertex_id]]) { float2 p[3]={float2(-1,-1),float2(3,-1),float2(-1,3)};return float4(p[i],0,1);}\nfragment float4 f(){return float4(0.25,0.5,0.75,1);}";
        id<MTLLibrary> library=[device newLibraryWithSource:code options:nil error:&error];if(!library)return 4;
        MTLRenderPipelineDescriptor *descriptor=[[MTLRenderPipelineDescriptor alloc] init];
        descriptor.vertexFunction=[library newFunctionWithName:@"v"];descriptor.fragmentFunction=[library newFunctionWithName:@"f"];
        descriptor.colorAttachments[0].pixelFormat=MTLPixelFormatRGBA8Unorm;
        W101MetalArchive archive(device);bool available=archive.available();
        id<MTLRenderPipelineState> exact=archive.hit(device,descriptor);
        bool prepared=false;
        if(create) {if(!exact)prepared=archive.prepare(descriptor);else prepared=true;}
        else if(warm)prepared=exact!=nil;
        else if(mismatch)prepared=archive.attach(descriptor);
        MTLPipelineOption options=(warm||mismatch)?MTLPipelineOptionFailOnBinaryArchiveMiss:MTLPipelineOptionNone;
        id<MTLRenderPipelineState> pipeline=exact?exact:[device newRenderPipelineStateWithDescriptor:descriptor options:options reflection:nil error:&error];
        bool expectedMiss=mismatch;
        bool pass=expectedMiss?available&&prepared&&!pipeline:fallback?!available&&!prepared&&pipeline:available&&prepared&&pipeline;
        bool pixels=false,saved=false,secondWriterRejected=false;
        if(pipeline) {
            MTLTextureDescriptor *td=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm width:16 height:16 mipmapped:NO];
            td.usage=MTLTextureUsageRenderTarget;td.storageMode=MTLStorageModeShared;
            id<MTLTexture> texture=[device newTextureWithDescriptor:td];id<MTLCommandQueue> queue=[device newCommandQueue];id<MTLCommandBuffer> buffer=[queue commandBuffer];
            MTLRenderPassDescriptor *rp=[MTLRenderPassDescriptor renderPassDescriptor];rp.colorAttachments[0].texture=texture;rp.colorAttachments[0].loadAction=MTLLoadActionClear;rp.colorAttachments[0].storeAction=MTLStoreActionStore;
            id<MTLRenderCommandEncoder> encoder=[buffer renderCommandEncoderWithDescriptor:rp];[encoder setRenderPipelineState:pipeline];[encoder drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];[encoder endEncoding];[buffer commit];[buffer waitUntilCompleted];
            unsigned char bytes[16*16*4]{};[texture getBytes:bytes bytesPerRow:64 fromRegion:MTLRegionMake2D(0,0,16,16) mipmapLevel:0];
            pixels=buffer.status==MTLCommandBufferStatusCompleted;
            for(unsigned i=0;i<256;i++)pixels&=bytes[4*i]==64&&bytes[4*i+1]==128&&bytes[4*i+2]==191&&bytes[4*i+3]==255;
            pass&=pixels;
            if(create){
                const char *folder=getenv("W101_METAL_ARCHIVE_PATH");
                if(saveFailure)pass&=folder&&chmod(folder,0500)==0;
                saved=archive.save();pass&=saveFailure?!saved:(saved||exact);
                if(saveFailure)pass&=chmod(folder,0700)==0;
            }
            W101MetalArchive second(device);secondWriterRejected=!second.available();pass&=secondWriterRejected;
            [queue release];[texture release];
        }
        printf("{\"mode\":\"%s\",\"available\":%s,\"prepared\":%s,\"driver_confirmed_archive_hit\":%s,\"changed_identity_misses\":%s,\"pixels_identical\":%s,\"saved\":%s,\"second_writer_rejected\":%s,\"passed\":%s}\n",mode,available?"true":"false",prepared?"true":"false",warm&&pipeline?"true":"false",expectedMiss&&!pipeline?"true":"false",pixels?"true":"false",saved?"true":"false",secondWriterRejected?"true":"false",pass?"true":"false");
        [pipeline release];[descriptor.vertexFunction release];[descriptor.fragmentFunction release];[descriptor release];[library release];[device release];return pass?0:7;
    }
}
