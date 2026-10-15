#include "../performance/ArrivalBudget.h"
#include <cassert>
#include <thread>
#include <vector>
#include <cstdio>
using namespace dxvk::wizard101;
constexpr size_t MiB=1024*1024;
int main() {
  {
    AssetLease base(48*MiB,false,true);
    std::atomic<unsigned> ready{0},attempted{0},acquired{0};std::atomic<bool> release{false};
    std::vector<std::thread> threads;
    for(unsigned i=0;i<3;i++)threads.emplace_back([&]{
      ++ready;while(ready.load()<3)std::this_thread::yield();
      AssetLease lease(16*MiB,true);if(lease.size)++acquired;
      ++attempted;
      while(!release.load())std::this_thread::yield();
    });
    while(attempted.load()<3)std::this_thread::yield();
    assert(assetBytes==64*MiB && preparedAssetBytes==16*MiB);
    release=true;for(auto& t:threads)t.join();
    assert(acquired==1 && assetBytes==48*MiB && preparedAssetBytes==0);
  }
  {
    AssetLease cpu(32*MiB,false,true),gpu(32*MiB,true),learned(64*MiB);
    AssetLease extra(1),extraGpu(1,true),extraStartup(1,false,true);
    assert(cpu.size && gpu.size && learned.size && !extra.size && !extraGpu.size && !extraStartup.size);
    assert(assetBytes==128*MiB && preparedAssetBytes==32*MiB);
    AssetLease moved(std::move(gpu));assert(!gpu.size && moved.size==32*MiB);
  }
  assert(assetBytes==0 && preparedAssetBytes==0);
  puts("PASS atomic startup, speculation, process bounds and retirement");
}
