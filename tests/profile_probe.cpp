#include "util/util_profile.h"
#include <windows.h>
#include <cstring>
#include <string>
#include <cassert>
#include <iostream>
#include <thread>
#include <vector>
int main(int argc,char**argv) {
  if (argc < 2) return 2;
  if (!strcmp(argv[1],"disabled")) {
    assert(!dxvk::profileEnabled()); dxvk::ProfileScope event("disabled");
  } else if (!strcmp(argv[1],"overhead")) {
    assert(!dxvk::profileEnabled());
    FILETIME created, exited, kernel, user;
    auto ticks=[](const FILETIME& t) { return uint64_t(t.dwHighDateTime)<<32 | t.dwLowDateTime; };
    auto cpu=[&] {
      assert(GetThreadTimes(GetCurrentThread(),&created,&exited,&kernel,&user));
      return (ticks(kernel)+ticks(user))/10000.0;
    };
    auto begin=std::chrono::steady_clock::now(); const auto cpuStart=cpu();
    for (int i=0;i<20000000;++i) { dxvk::ProfileScope event("disabled"); }
    std::cout << "PROFILE_OVERHEAD calls=20000000 cpu_ms=" << cpu()-cpuStart
      << " wall_ms=" << std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-begin).count() << '\n';
  } else if (!strcmp(argv[1],"contention")) {
    assert(dxvk::profileEnabled());
    std::vector<std::thread> producers;
    for (int t=0;t<8;++t) producers.emplace_back([] {
      for (int i=0;i<100000;++i) {
        const auto now=std::chrono::steady_clock::now();
        dxvk::profileEvent("graphics_pipeline_background_lock_wait",now,now+std::chrono::microseconds(200));
      }
    });
    for (int i=0;i<128;++i) {
      { dxvk::ProfileScope frame("presentation"); }
      Sleep(2);
    }
    for (auto& producer:producers) producer.join();
    for (int i=0;i<10;++i) {
      const auto now=std::chrono::steady_clock::now();
      dxvk::profileEvent("graphics_pipeline_background_lock_wait",now,now+std::chrono::microseconds(1));
      dxvk::profileEvent("game_read_file",now,now+std::chrono::microseconds(1));
    }
  } else if (!strcmp(argv[1],"devices")) {
    dxvk::profileDeviceCreated(); dxvk::profileDeviceCreated();
    assert(dxvk::profileEnabled());
    { dxvk::ProfileScope event("two_devices"); }
    dxvk::profileDeviceDestroyed(); assert(dxvk::profileEnabled());
    { dxvk::ProfileScope event("last_device"); }
    dxvk::profileDeviceDestroyed(); assert(!dxvk::profileEnabled());
    dxvk::profileShutdown();
    { dxvk::ProfileScope event("after_shutdown"); }
  } else if (!strcmp(argv[1],"time")) {
    assert(dxvk::profileEnabled());
    { dxvk::ProfileScope event("before_deadline"); }
    const auto now=std::chrono::steady_clock::now();
    dxvk::profileEvent("beyond_deadline",now,now+std::chrono::seconds(181));
    assert(!dxvk::profileEnabled()); Sleep(300);
  } else if (!strcmp(argv[1],"size")) {
    assert(dxvk::profileEnabled());
    static const std::string name(4000,'x');
    for(int batch=0;batch<200 && dxvk::profileEnabled();++batch) {
      for(int i=0;i<8192;++i) { dxvk::ProfileScope event(name.c_str()); }
      Sleep(300);
    }
    assert(!dxvk::profileEnabled()); Sleep(300);
  } else return 2;
  dxvk::profileShutdown();
  std::cout << "PASS bounded profile " << argv[1] << '\n';
}
