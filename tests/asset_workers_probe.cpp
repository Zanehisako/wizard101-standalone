#include "d3d9/wizard101_asset_preparation.h"
#include <cstdio>
#include <thread>
#include <chrono>
#include <stdexcept>
using namespace dxvk::wizard101;
int main() {
  try {
    { AssetLease a(80*1024*1024),b(64*1024*1024); if(!a.size || b.size || assetBytes.load()>AssetLimit)throw std::runtime_error("memory bound"); }
    if(assetBytes.load())throw std::runtime_error("lease release");
    std::vector<uint16_t> source(1024*1024); std::vector<uint32_t> output(source.size());
    for(size_t i=0;i<source.size();++i)source[i]=uint16_t(i*37);
    PreparationWorkers workers;
    for(unsigned mode=0;mode<5;++mode) {
      workers.convert((unsigned char*)source.data(),2048,(unsigned char*)output.data(),4096,1024,1024,mode);
      for(size_t i=0;i<source.size();++i) if(output[i]!=expand16(source[i],mode))throw std::runtime_error("parallel result");
    }
    std::atomic<bool> failed{false};std::vector<std::thread> callers;
    for(int i=0;i<24;++i)callers.emplace_back([&,i] {std::vector<uint32_t> result(source.size());for(int j=0;j<4;++j){workers.convert((unsigned char*)source.data(),2048,(unsigned char*)result.data(),4096,1024,1024,i%5);for(size_t x=0;x<source.size();++x)if(result[x]!=expand16(source[x],i%5))failed=true;}});
    workers.shutdown(); for(auto& t:callers)t.join(); if(failed)throw std::runtime_error("queue/shutdown result");
    PreparationWorkers bench;
    auto timed=[&](bool parallel) {auto start=std::chrono::steady_clock::now();for(int n=0;n<64;++n){
      if(parallel)bench.convert((unsigned char*)source.data(),2048,(unsigned char*)output.data(),4096,1024,1024,n%5);
      else for(size_t i=0;i<source.size();++i)output[i]=expand16(source[i],n%5);
    }return std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now()-start).count();};
    for(int pair=0;pair<5;++pair) {long long serial,parallel;if(pair%2){parallel=timed(true);serial=timed(false);}else{serial=timed(false);parallel=timed(true);}printf("BENCH pair=%d serial_us=%lld parallel_us=%lld\n",pair,serial,parallel);}
    printf("PASS memory budget, five conversion modes, 24 callers, queue pressure, stop/drain, stopped fallback\n");return 0;
  }catch(const std::exception& e){printf("FAIL %s\n",e.what());return 1;}
}
