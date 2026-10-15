#pragma once
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <mutex>
#include <cstring>
#include <sys/file.h>
#include <sys/stat.h>
#include <sys/sysctl.h>
#include <fcntl.h>
#include <unistd.h>

// Independent Metal adaptation of persistent, exact pipeline warming. No
// SCSKiller source is copied. No recorder, profiler, logging or draw changes.
class W101MetalArchive {
    id<MTLBinaryArchive> archive=nil;
    NSString *path=nil;
    int lockFD=-1;
    bool dirty=false;
    std::mutex mutex;
public:
    static constexpr uint64_t MaxFile=64*1024*1024;
    explicit W101MetalArchive(id<MTLDevice> device) noexcept {
        const char *enabled=getenv("W101_METAL_ARCHIVE");
        const char *directory=getenv("W101_METAL_ARCHIVE_PATH"),*key=getenv("W101_METAL_ARCHIVE_KEY");
        if(!enabled||strcmp(enabled,"1")||!directory||directory[0]!='/'||!key||strlen(key)!=64)return;
        for(unsigned i=0;i<64;i++)if(!((key[i]>='0'&&key[i]<='9')||(key[i]>='a'&&key[i]<='f')))return;
        @autoreleasepool {
            char os[128]{};size_t size=sizeof(os);
            if(sysctlbyname("kern.osversion",os,&size,nullptr,0))return;
            NSString *folder=[NSString stringWithUTF8String:directory];if(!folder)return;
            NSError *error=nil;
            if(![[NSFileManager defaultManager] createDirectoryAtPath:folder withIntermediateDirectories:YES attributes:@{NSFilePosixPermissions:@0700} error:&error])return;
            NSString *name=[NSString stringWithFormat:@"v1-mvk142-%s-%llu-%s.metalar",os,(unsigned long long)device.registryID,key];
            path=[[folder stringByAppendingPathComponent:name] copy];
            NSString *lockPath=[path stringByAppendingString:@".lock"];
            lockFD=open(lockPath.fileSystemRepresentation,O_CREAT|O_RDWR|O_NOFOLLOW,0600);
            if(lockFD<0||flock(lockFD,LOCK_EX|LOCK_NB))return;
            MTLBinaryArchiveDescriptor *descriptor=[[MTLBinaryArchiveDescriptor alloc] init];
            struct stat state{};
            if(!lstat(path.fileSystemRepresentation,&state)&&S_ISREG(state.st_mode)&&state.st_size>0&&(uint64_t)state.st_size<=MaxFile)descriptor.url=[NSURL fileURLWithPath:path];
            archive=[device newBinaryArchiveWithDescriptor:descriptor error:&error];
            if(!archive&&descriptor.url) {descriptor.url=nil;error=nil;archive=[device newBinaryArchiveWithDescriptor:descriptor error:&error];}
            [descriptor release];
        }
    }
    bool available() const noexcept {return archive!=nil;}
    bool attach(MTLRenderPipelineDescriptor *descriptor) noexcept {
        if(!archive||descriptor.binaryArchives.count)return false;
        std::lock_guard<std::mutex> guard(mutex);
        descriptor.binaryArchives=@[archive];return true;
    }
    bool prepare(MTLRenderPipelineDescriptor *descriptor) noexcept {
        if(!archive||descriptor.binaryArchives.count)return false;
        std::lock_guard<std::mutex> guard(mutex);
        NSError *error=nil;
        if(![archive addRenderPipelineFunctionsWithDescriptor:descriptor error:&error])return false;
        descriptor.binaryArchives=@[archive];dirty=true;return true;
    }
    bool prepare(MTLComputePipelineDescriptor *descriptor) noexcept {
        if(!archive||descriptor.binaryArchives.count)return false;
        std::lock_guard<std::mutex> guard(mutex);
        NSError *error=nil;
        if(![archive addComputePipelineFunctionsWithDescriptor:descriptor error:&error])return false;
        descriptor.binaryArchives=@[archive];dirty=true;return true;
    }
    // Only VkDevice teardown calls this in the overlay. Disk I/O never occurs
    // in the pipeline creation path. Failed saves preserve the previous file.
    bool save() noexcept {
        if(!archive||!dirty)return false;
        std::lock_guard<std::mutex> guard(mutex);
        NSString *temporary=[path stringByAppendingFormat:@".tmp.%@",NSUUID.UUID.UUIDString];
        int fd=open(temporary.fileSystemRepresentation,O_CREAT|O_EXCL|O_RDWR|O_NOFOLLOW,0600);
        if(fd<0)return false;
        close(fd);NSError *error=nil;
        bool ok=[archive serializeToURL:[NSURL fileURLWithPath:temporary] error:&error];
        struct stat state{};
        ok=ok&&!lstat(temporary.fileSystemRepresentation,&state)&&S_ISREG(state.st_mode)&&state.st_size>0&&(uint64_t)state.st_size<=MaxFile;
        if(ok) {
            fd=open(temporary.fileSystemRepresentation,O_RDONLY|O_NOFOLLOW);
            ok=fd>=0&&fchmod(fd,0600)==0&&fsync(fd)==0;
            if(fd>=0)close(fd);
        }
        if(ok)ok=rename(temporary.fileSystemRepresentation,path.fileSystemRepresentation)==0;
        if(!ok)unlink(temporary.fileSystemRepresentation);else dirty=false;
        return ok;
    }
    ~W101MetalArchive() {
        [archive release];[path release];
        if(lockFD>=0){flock(lockFD,LOCK_UN);close(lockFD);}
    }
    W101MetalArchive(const W101MetalArchive&)=delete;
    W101MetalArchive&operator=(const W101MetalArchive&)=delete;
};
