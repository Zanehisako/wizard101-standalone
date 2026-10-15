#pragma once
#include <atomic>
#include <cstddef>
#include <utility>
namespace dxvk::wizard101 {
inline std::atomic<size_t> assetBytes{0};
constexpr size_t AssetLimit=128u*1024u*1024u;
struct AssetLease {
  size_t size=0;
  explicit AssetLease(size_t n) {
    auto old=assetBytes.load(std::memory_order_relaxed);
    while(n<=AssetLimit && old<=AssetLimit-n)
      if(assetBytes.compare_exchange_weak(old,old+n)) { size=n; break; }
  }
  AssetLease(AssetLease&& other) noexcept : size(std::exchange(other.size, 0)) { }
  AssetLease(const AssetLease&)=delete;
  AssetLease& operator=(const AssetLease&)=delete;
  ~AssetLease() { if(size) assetBytes.fetch_sub(size); }
};
}
