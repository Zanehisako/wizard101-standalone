#pragma once
#import <Metal/Metal.h>
// Diagnostic only. Metal handlers enqueue timestamps; they never wait for disk.
#include <atomic>
#include <array>
#include <mutex>
#include <thread>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cmath>
#include <cstring>
#include <algorithm>
#include <dispatch/dispatch.h>
#include <mach/mach.h>
#include <mach/mach_time.h>
#include <libproc.h>
#include <sys/resource.h>
#include <sys/time.h>
#include <sys/sysctl.h>
#include <pthread.h>
#include <unistd.h>

namespace w101 {
inline bool configured() { static const bool on=[] { const auto p=getenv("W101_WORKLOAD_NATIVE"); return p && *p; }(); return on; }
inline uint64_t machUs() {
    static const double scale = [] { mach_timebase_info_data_t t; mach_timebase_info(&t); return double(t.numer) / t.denom / 1000; }();
    return uint64_t(mach_absolute_time() * scale);
}
inline uint64_t unixUs() { timeval t; gettimeofday(&t, nullptr); return uint64_t(t.tv_sec)*1000000+t.tv_usec; }
struct GPUEvent { uint64_t id, created, completed, start, end, tid; int use, family, queue, status; };
class NativeRecorder {
    FILE* file = nullptr;
    std::mutex mutex;
    std::array<GPUEvent,4096> ring {};
    size_t head = 0, count = 0, bytes = 0;
    uint64_t origin = 0, deadline = 0;
    size_t maxBytes = 128u*1024u*1024u;
    std::thread writer;
    std::atomic<bool> active {false}, stop {false};
    std::atomic<uint64_t> dropped {0}, rejected {0}, ids {0};
    std::atomic<unsigned> outstanding {0};
    std::atomic<unsigned long> pressure {0};
    std::atomic<bool> pressureKnown {false};
    dispatch_source_t pressureSource = nullptr;
    bool row(const char* text) {
        if (machUs()>=deadline) { active=false; stop=true; return false; }
        const size_t length = strlen(text);
        if (bytes+length+2048 > maxBytes) { active=false; stop=true; return false; }
        if (fwrite(text,1,length,file)!=length) { active=false; stop=true; return false; }
        bytes+=length; return true;
    }
    void sample() {
        char line[1024]; const auto before=machUs(), wall=unixUs(), after=machUs();
        snprintf(line,sizeof(line),"{\"type\":\"clock\",\"mach_us\":%llu,\"unix_us\":%llu,\"uncertainty_us\":%llu,\"pid\":%d}\n",
            (unsigned long long)((before+after)/2),(unsigned long long)wall,(unsigned long long)(after-before),getpid()); row(line);
        // In-process Mach APIs supply kernel IDs directly; no name-based guesses.
        thread_act_array_t threads; mach_msg_type_number_t n=0;
        if (task_threads(mach_task_self(),&threads,&n)==KERN_SUCCESS) {
            for (unsigned i=0;i<n;++i) {
                thread_identifier_info_data_t identity={}; mach_msg_type_number_t c=THREAD_IDENTIFIER_INFO_COUNT;
                thread_basic_info_data_t cpu={}; mach_msg_type_number_t b=THREAD_BASIC_INFO_COUNT;
                if (thread_info(threads[i],THREAD_IDENTIFIER_INFO,(thread_info_t)&identity,&c)==KERN_SUCCESS &&
                    thread_info(threads[i],THREAD_BASIC_INFO,(thread_info_t)&cpu,&b)==KERN_SUCCESS) {
                    uint64_t cpuUs=uint64_t(cpu.user_time.seconds+cpu.system_time.seconds)*1000000+cpu.user_time.microseconds+cpu.system_time.microseconds;
                    snprintf(line,sizeof(line),"{\"type\":\"thread_cpu\",\"mach_us\":%llu,\"native_tid\":%llu,\"cpu_us\":%llu,\"state\":%d}\n",
                        (unsigned long long)machUs(),(unsigned long long)identity.thread_id,(unsigned long long)cpuUs,cpu.run_state); row(line);
                }
                mach_port_deallocate(mach_task_self(),threads[i]);
            }
            vm_deallocate(mach_task_self(),(vm_address_t)threads,n*sizeof(thread_t));
        }
        task_vm_info_data_t vm={}; mach_msg_type_number_t v=TASK_VM_INFO_COUNT;
        const bool vmValid=task_info(mach_task_self(),TASK_VM_INFO,(task_info_t)&vm,&v)==KERN_SUCCESS;
        rusage_info_v4 usage={}; const bool usageValid=proc_pid_rusage(getpid(),RUSAGE_INFO_V4,(rusage_info_t*)&usage)==0;
        vm_statistics64_data_t host={}; mach_msg_type_number_t h=HOST_VM_INFO64_COUNT;
        const auto hostPort=mach_host_self(); const bool hostValid=host_statistics64(hostPort,HOST_VM_INFO64,(host_info64_t)&host,&h)==KERN_SUCCESS;
        mach_port_deallocate(mach_task_self(),hostPort);
        snprintf(line,sizeof(line),"{\"type\":\"memory\",\"mach_us\":%llu,\"task_vm_valid\":%s,\"rusage_valid\":%s,\"host_vm_valid\":%s,\"resident_bytes\":%llu,\"footprint_bytes\":%llu,\"process_pageins\":%llu,\"disk_read_bytes\":%llu,\"host_pageins\":%llu,\"host_compressions\":%llu,\"pressure_valid\":%s,\"pressure\":%lu}\n",
            (unsigned long long)machUs(),vmValid?"true":"false",usageValid?"true":"false",hostValid?"true":"false",
            (unsigned long long)vm.resident_size,(unsigned long long)vm.phys_footprint,(unsigned long long)usage.ri_pageins,
            (unsigned long long)usage.ri_diskio_bytesread,(unsigned long long)host.pageins,(unsigned long long)host.compressions,pressureKnown.load()?"true":"false",pressure.load()); row(line);
    }
    void write() noexcept {
        pthread_setname_np("w101-native-writer");
        pthread_set_qos_class_self_np(QOS_CLASS_UTILITY,0);
        try {
            std::array<GPUEvent,4096> batch;
            for (;;) {
                if (machUs()>=deadline) { active=false; stop=true; }
                size_t n;
                { std::lock_guard<std::mutex> lock(mutex); n=count; for(size_t i=0;i<n;++i) batch[i]=ring[(head+i)%ring.size()]; head=(head+n)%ring.size(); count=0; }
                for(size_t i=0;i<n;++i) {
                    const auto& e=batch[i]; char line[768];
                    snprintf(line,sizeof(line),"{\"type\":\"gpu\",\"id\":%llu,\"created_mach_us\":%llu,\"completed_mach_us\":%llu,\"start_mach_us\":%llu,\"end_mach_us\":%llu,\"creator_native_tid\":%llu,\"command_use\":%d,\"queue_family\":%d,\"queue\":%d,\"status\":%d}\n",
                        (unsigned long long)e.id,(unsigned long long)e.created,(unsigned long long)e.completed,(unsigned long long)e.start,
                        (unsigned long long)e.end,(unsigned long long)e.tid,e.use,e.family,e.queue,e.status);
                    if (!row(line)) { dropped+=n-i; break; }
                }
                if (!stop.load()) sample();
                fflush(file);
                if (stop.load()) { std::lock_guard<std::mutex> lock(mutex); if(!count) break; }
                if (!stop.load()) std::this_thread::sleep_for(std::chrono::milliseconds(250));
            }
            // Late callbacks are counted and never access a closed FILE.
            active=false;
            { std::lock_guard<std::mutex> lock(mutex); dropped+=count; count=0; }
            char footer[512]; snprintf(footer,sizeof(footer),"{\"type\":\"footer\",\"finalized\":true,\"dropped_gpu\":%llu,\"invalid_timestamps\":%llu,\"outstanding_gpu\":%u,\"duration_us\":%llu}\n",
                (unsigned long long)dropped.load(),(unsigned long long)rejected.load(),outstanding.load(),(unsigned long long)(machUs()-origin));
            fwrite(footer,1,strlen(footer),file); fclose(file); file=nullptr;
        } catch (...) { active=false; stop=true; if(file) { fclose(file); file=nullptr; } }
    }
public:
    NativeRecorder() noexcept {
        const char* path=getenv("W101_WORKLOAD_NATIVE"); if(!path || !*path) return;
        origin=machUs(); unsigned seconds=900;
        if(const char* s=getenv("W101_WORKLOAD_SECONDS")) seconds=std::max(1,std::min(900,atoi(s)));
        if(const char* s=getenv("W101_WORKLOAD_NATIVE_MAX_BYTES")) maxBytes=std::max(size_t(16384),std::min(maxBytes,size_t(strtoull(s,nullptr,10))));
        deadline=origin+uint64_t(seconds)*1000000;
        if(const char* s=getenv("W101_WORKLOAD_DEADLINE_UNIX_US")) {
            const auto absolute=strtoull(s,nullptr,10), now=unixUs();
            deadline=std::min(deadline,origin+(absolute>now?absolute-now:0));
        }
        file=fopen(path,"wb"); if(!file) return;
        char header[512]; snprintf(header,sizeof(header),"{\"type\":\"header\",\"schema\":1,\"clock\":\"system_mach_time\",\"origin_mach_us\":%llu,\"deadline_mach_us\":%llu,\"sample_interval_ms\":250,\"gpu_scope\":\"command_buffer_execution; concurrent intervals require union\"}\n",
            (unsigned long long)origin,(unsigned long long)deadline); row(header);
        active=true;
        try { writer=std::thread([this]{write();}); } catch(...) { active=false; fclose(file); file=nullptr; return; }
        pressureSource=dispatch_source_create(DISPATCH_SOURCE_TYPE_MEMORYPRESSURE,0,DISPATCH_MEMORYPRESSURE_NORMAL|DISPATCH_MEMORYPRESSURE_WARN|DISPATCH_MEMORYPRESSURE_CRITICAL,dispatch_get_global_queue(QOS_CLASS_UTILITY,0));
        if(pressureSource) { dispatch_source_set_event_handler(pressureSource, ^{ pressure=dispatch_source_get_data(pressureSource); pressureKnown=true; }); dispatch_resume(pressureSource); }
    }
    bool enabled() const { return active.load(std::memory_order_relaxed); }
    uint64_t begin() { if(!enabled()) return 0; if(machUs()>=deadline) { active=false; stop=true; return 0; } auto old=outstanding.fetch_add(1); if(old>=256) { --outstanding; ++dropped; return 0; } return ++ids; }
    void completed(GPUEvent e) noexcept {
        --outstanding;
        if(!enabled()) { ++dropped; return; }
        if(e.completed>=deadline) { ++dropped; active=false; stop=true; return; }
        if(!e.start || e.end<e.start || e.end>e.completed+1000) { ++rejected; return; }
        std::unique_lock<std::mutex> lock(mutex,std::try_to_lock);
        if(!lock.owns_lock() || count==ring.size()) { ++dropped; return; }
        if(!enabled()) { ++dropped; return; }
        ring[(head+count)%ring.size()]=e; ++count;
    }
    void shutdown() noexcept { active=false; stop=true; if(pressureSource) dispatch_source_cancel(pressureSource); if(writer.joinable() && writer.get_id()!=std::this_thread::get_id()) writer.join(); }
};
inline NativeRecorder& recorder() { static NativeRecorder* r=new NativeRecorder(); return *r; }
inline std::atomic<unsigned>& devices() { static std::atomic<unsigned> d{0}; return d; }
inline void deviceCreated() { if(getenv("W101_WORKLOAD_NATIVE")) { ++devices(); recorder(); } }
inline void deviceDestroyed() { if(getenv("W101_WORKLOAD_NATIVE") && devices().fetch_sub(1)==1) recorder().shutdown(); }
inline void observe(id<MTLCommandBuffer> buffer,int use,int family,int queue) {
    auto& r=recorder(); const auto eventId=r.begin(); if(!eventId || !buffer) { if(eventId) r.completed({}); return; }
    uint64_t tid=0; pthread_threadid_np(nullptr,&tid); const auto created=machUs();
    [buffer addCompletedHandler:^(id<MTLCommandBuffer> done) {
        const double start=done.GPUStartTime, end=done.GPUEndTime;
        r.completed({eventId,created,machUs(),std::isfinite(start)&&start>0?uint64_t(start*1000000):0,
            std::isfinite(end)&&end>0?uint64_t(end*1000000):0,tid,use,family,queue,int(done.status)});
    }];
}
}
