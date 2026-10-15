#pragma once
#include <atomic>
#include <cstddef>
#include <utility>
namespace dxvk::wizard101 {
inline std::atomic<size_t> assetBytes{0};
inline std::atomic<size_t> preparedAssetBytes{0};
constexpr size_t AssetLimit=128u*1024u*1024u;
struct AssetLease {
  size_t size=0;
  bool speculative=false;
  explicit AssetLease(size_t n,bool prepared=false,bool startup=false) : speculative(prepared) {
    if(prepared) {
      auto used=preparedAssetBytes.load();
      while(true) {
        if(n>32u*1024u*1024u || used>32u*1024u*1024u-n) return;
        if(preparedAssetBytes.compare_exchange_weak(used,used+n)) break;
      }
    }
    const size_t limit=prepared || startup ? 64u*1024u*1024u : AssetLimit;
    auto old=assetBytes.load(std::memory_order_relaxed);
    while(n<=limit && old<=limit-n)
      if(assetBytes.compare_exchange_weak(old,old+n)) { size=n; break; }
    if(prepared && !size) preparedAssetBytes.fetch_sub(n);
  }
  AssetLease(AssetLease&& other) noexcept : size(std::exchange(other.size, 0)), speculative(other.speculative) { }
  AssetLease(const AssetLease&)=delete;
  AssetLease& operator=(const AssetLease&)=delete;
  ~AssetLease() { if(size) {assetBytes.fetch_sub(size);if(speculative)preparedAssetBytes.fetch_sub(size);} }
};
}
