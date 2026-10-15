#pragma once
#include "wizard101_asset_budget.h"
#include "d3d9_util.h"
#include "../dxso/dxso_isgn.h"
#include <memory>
#include <new>

namespace dxvk { class D3D9DeviceEx; }
namespace dxvk::wizard101 {
constexpr size_t DrawLayoutLimit = 1024u * 1024u;
constexpr size_t DrawLayoutEntries = 256;

// This state owns bytes only. It never retains a device or a resource. Resource
// metadata may outlive the command-stream cache and release its own reservations.
struct DrawBudget {
  AssetLease self;
  std::atomic<size_t> bytes;
  explicit DrawBudget(AssetLease&& charge): self(std::move(charge)), bytes(self.size) { }
};
inline std::shared_ptr<DrawBudget> makeDrawBudget() noexcept {
  try {
    AssetLease charge(sizeof(DrawBudget) + 64);
    if (!charge.size) return {};
    return std::make_shared<DrawBudget>(std::move(charge));
  } catch (...) { return {}; }
}
std::shared_ptr<DrawBudget> getDrawBudget(D3D9DeviceEx* device);

class DrawLease {
  std::shared_ptr<DrawBudget> owner;
  AssetLease shared;
public:
  DrawLease(const std::shared_ptr<DrawBudget>& budget, size_t n): owner(budget), shared(0) {
    if (!owner) return;
    auto old = owner->bytes.load(std::memory_order_relaxed);
    while (n <= DrawLayoutLimit && old <= DrawLayoutLimit - n) {
      if (owner->bytes.compare_exchange_weak(old, old + n)) {
        AssetLease charge(n);
        if (charge.size) shared.size = std::exchange(charge.size, 0);
        else owner->bytes.fetch_sub(n);
        break;
      }
    }
  }
  DrawLease(DrawLease&& b) noexcept: owner(std::move(b.owner)), shared(std::move(b.shared)) { }
  DrawLease(const DrawLease&) = delete;
  ~DrawLease() { if (shared.size) owner->bytes.fetch_sub(shared.size); }
  size_t size() const { return shared.size; }
  void reset() noexcept {
    if (shared.size) {
      owner->bytes.fetch_sub(shared.size);
      assetBytes.fetch_sub(std::exchange(shared.size, 0));
    }
    owner.reset();
  }
};

inline uint64_t fingerprintAdd(uint64_t h, uint64_t value) {
  return (h ^ value) * 1099511628211ull;
}
template<size_t N> struct DrawFingerprint {
  DrawLease lease;
  std::array<uint64_t, N> words;
  uint32_t count = 0;
  uint64_t hash = 14695981039346656037ull;
  bool valid = false;
  explicit DrawFingerprint(DrawLease&& charge): lease(std::move(charge)) { }
};
using DrawDeclFingerprint = DrawFingerprint<64>;
using DrawSemanticFingerprint = DrawFingerprint<2 * caps::InputRegisterCount>;

// Reservation precedes both the allocation and the complete fingerprint work.
// Failed preparation is represented by null and uses the original draw path.
inline std::shared_ptr<const DrawDeclFingerprint> prepareDrawDeclaration(
    const std::shared_ptr<DrawBudget>& budget, const D3D9VertexElements& elements) noexcept {
  if (!budget || elements.size() > 64) return {};
  try {
    DrawLease charge(budget, sizeof(DrawDeclFingerprint) + 64);
    if (!charge.size()) return {};
    auto result = std::make_shared<DrawDeclFingerprint>(std::move(charge));
    result->count = elements.size();
    result->hash = fingerprintAdd(result->hash, result->count);
    for (size_t i = 0; i < elements.size(); ++i) {
      const auto& e = elements[i];
      if (e.Stream >= caps::MaxStreams || e.Type >= D3DDECLTYPE_UNUSED) return {};
      result->words[i] = uint64_t(e.Stream) | (uint64_t(e.Offset) << 16) |
        (uint64_t(e.Type) << 32) | (uint64_t(e.Method) << 40) |
        (uint64_t(e.Usage) << 48) | (uint64_t(e.UsageIndex) << 56);
      result->hash = fingerprintAdd(result->hash, result->words[i]);
    }
    result->valid = true;
    return result;
  } catch (...) { return {}; }
}
inline std::shared_ptr<const DrawSemanticFingerprint> prepareDrawSemantics(
    const std::shared_ptr<DrawBudget>& budget, const DxsoIsgn& isgn) noexcept {
  if (!budget || isgn.elemCount > 2 * caps::InputRegisterCount) return {};
  try {
    DrawLease charge(budget, sizeof(DrawSemanticFingerprint) + 64);
    if (!charge.size()) return {};
    auto result = std::make_shared<DrawSemanticFingerprint>(std::move(charge));
    result->count = isgn.elemCount;
    result->hash = fingerprintAdd(result->hash, result->count);
    for (uint32_t i = 0; i < isgn.elemCount; ++i) {
      result->words[i] = uint64_t(uint32_t(isgn.elems[i].semantic.usage)) |
        (uint64_t(isgn.elems[i].semantic.usageIndex) << 32);
      result->hash = fingerprintAdd(result->hash, result->words[i]);
    }
    result->valid = true;
    return result;
  } catch (...) { return {}; }
}

// Borrowed views exist only inside the command that still owns the resources.
// They are never stored in a cache slot.
struct DrawLayoutLookup {
  const DrawDeclFingerprint* declaration;
  const DrawSemanticFingerprint* semantics;
  const std::array<uint32_t, caps::MaxStreams>* frequencies;
  uint32_t instanced;
  bool programmable;
  uint64_t hash;
  static bool make(const DrawDeclFingerprint* d, const DrawSemanticFingerprint* s,
      const std::array<uint32_t, caps::MaxStreams>& freq, uint32_t flags,
      bool shader, DrawLayoutLookup& key) {
    if (!d || !s || !d->valid || !s->valid) return false;
    key.declaration=d; key.semantics=s; key.frequencies=&freq;
    key.instanced=flags; key.programmable=shader;
    auto h=fingerprintAdd(d->hash,s->hash);
    h=fingerprintAdd(h,flags); h=fingerprintAdd(h,shader);
    for (auto f:freq) h=fingerprintAdd(h,f);
    h^=h>>33; h*=0xff51afd7ed558ccdull; h^=h>>33;
    key.hash=h; return true;
  }
};
struct DrawLayoutKey {
  std::array<uint64_t,64> elements;
  std::array<uint64_t,2*caps::InputRegisterCount> semantics;
  std::array<uint32_t,caps::MaxStreams> frequencies;
  uint32_t elementCount,semanticCount,instanced;
  bool programmable;
  uint64_t hash;
  void assign(const DrawLayoutLookup& b) {
    elementCount=b.declaration->count; semanticCount=b.semantics->count;
    instanced=b.instanced; programmable=b.programmable; hash=b.hash;
    frequencies=*b.frequencies;
    std::copy_n(b.declaration->words.begin(),elementCount,elements.begin());
    std::copy_n(b.semantics->words.begin(),semanticCount,semantics.begin());
  }
  bool operator==(const DrawLayoutLookup& b) const {
    return elementCount==b.declaration->count && semanticCount==b.semantics->count &&
      instanced==b.instanced && programmable==b.programmable && frequencies==*b.frequencies &&
      std::equal(elements.begin(),elements.begin()+elementCount,b.declaration->words.begin()) &&
      std::equal(semantics.begin(),semantics.begin()+semanticCount,b.semantics->words.begin());
  }
};

struct DrawLayout {
  std::array<DxvkVertexAttribute, 2 * caps::InputRegisterCount> attributes;
  std::array<DxvkVertexBinding, 2 * caps::InputRegisterCount> bindings;
  uint32_t attributeCount = 0, bindingCount = 0, streamsUsed = 0, streamsInstanced = 0;
  DrawLayout() = default;
  DrawLayout(const DrawLayout& b) { *this = b; }
  DrawLayout& operator=(const DrawLayout& b) {
    attributeCount = b.attributeCount; bindingCount = b.bindingCount;
    streamsUsed = b.streamsUsed; streamsInstanced = b.streamsInstanced;
    std::copy_n(b.attributes.begin(), attributeCount, attributes.begin());
    std::copy_n(b.bindings.begin(), bindingCount, bindings.begin());
    return *this;
  }
};

// Original construction path, shared by misses, disabled mode and the CPU probe.
inline void buildDrawLayout(const D3D9VertexElements& elements, const DxsoIsgn& isgn,
    const std::array<uint32_t, caps::MaxStreams>& freq, uint32_t instanced, DrawLayout& out) {
  uint32_t attrMask = 0, bindMask = 0;
  out.streamsUsed = 0; out.streamsInstanced = instanced;
  for (uint32_t i = 0; i < isgn.elemCount; ++i) {
    const auto& decl = isgn.elems[i];
    DxvkVertexAttribute attrib { i, caps::MaxStreams, VK_FORMAT_R32G32B32A32_SFLOAT, 0 };
    for (const auto& element : elements) {
      DxsoSemantic semantic { static_cast<DxsoUsage>(element.Usage), element.UsageIndex };
      if (semantic.usage == DxsoUsage::PositionT) semantic.usage = DxsoUsage::Position;
      if (semantic.usage == decl.semantic.usage && semantic.usageIndex == decl.semantic.usageIndex) {
        attrib.binding = uint32_t(element.Stream);
        attrib.format = DecodeDecltype(D3DDECLTYPE(element.Type));
        attrib.offset = element.Offset;
        out.streamsUsed |= 1u << attrib.binding;
        break;
      }
    }
    out.attributes[i] = attrib;
    DxvkVertexBinding binding;
    binding.binding = attrib.binding;
    uint32_t instanceData = freq[binding.binding % caps::MaxStreams];
    if (instanceData & D3DSTREAMSOURCE_INSTANCEDATA) {
      binding.fetchRate = instanceData & 0x7FFFFF;
      binding.inputRate = VK_VERTEX_INPUT_RATE_INSTANCE;
    } else {
      binding.fetchRate = 0; binding.inputRate = VK_VERTEX_INPUT_RATE_VERTEX;
    }
    out.bindings.at(binding.binding) = binding;
    attrMask |= 1u << i; bindMask |= 1u << binding.binding;
  }
  out.attributeCount = CompactSparseList(out.attributes.data(), attrMask);
  out.bindingCount = CompactSparseList(out.bindings.data(), bindMask);
}



// One command-stream owner; the whole pool is reserved before resource creation.
// Eviction recycles a slot in place, without allocation, freeing or budget CAS.
class DrawLayoutCache {
  struct Node {
    DrawLayoutKey key;
    DrawLayout layout;
    Node *bucketNext=nullptr,*older=nullptr,*newer=nullptr;
  };
  std::shared_ptr<DrawBudget> budget;
  DrawLease baseLease;
  DrawLease poolLease;
  std::unique_ptr<Node[]> pool;
  std::array<Node*,512> buckets{};
  Node *oldest=nullptr,*newest=nullptr;
  size_t count=0;
  bool collide;
  size_t bucket(uint64_t hash) const { return collide?0:hash%buckets.size(); }
  void unlinkLru(Node* node) {
    if(node->older) node->older->newer=node->newer; else oldest=node->newer;
    if(node->newer) node->newer->older=node->older; else newest=node->older;
  }
  void touch(Node* node) {
    if(node==newest) return;
    unlinkLru(node);node->older=newest;node->newer=nullptr;
    if(newest) newest->newer=node; else oldest=node;
    newest=node;
  }
  Node* evict() {
    auto node=oldest;
    auto** link=&buckets[bucket(node->key.hash)];
    while(*link!=node) link=&(*link)->bucketNext;
    *link=node->bucketNext;unlinkLru(node);--count;++evictions;
    return node;
  }
public:
  uint64_t hits=0,misses=0,evictions=0,failures=0;
  explicit DrawLayoutCache(const std::shared_ptr<DrawBudget>& owner,
      bool collision=false,bool allocation=false)
    : budget(owner),baseLease(owner,sizeof(DrawLayoutCache)+32),
      poolLease(owner,baseLease.size()?sizeof(Node)*DrawLayoutEntries+32:0),collide(collision) {
    if(baseLease.size() && poolLease.size() && !allocation) {
      try { pool.reset(new Node[DrawLayoutEntries]); } catch(...) { }
    }
    if (!pool) poolLease.reset();
  }
  bool available() const { return bool(pool); }
  size_t entries() const { return count; }
  size_t bytes() const { return budget?budget->bytes.load():0; }
  const DrawLayout* find(const DrawLayoutLookup& key) {
    if(!available()) {++failures;return nullptr;}
    for(auto node=buckets[bucket(key.hash)];node;node=node->bucketNext) {
      if((collide || node->key.hash==key.hash) && node->key==key) {
        touch(node);++hits;return &node->layout;
      }
    }
    ++misses;return nullptr;
  }
  bool publish(const DrawLayoutLookup& key,const DrawLayout& layout) noexcept {
    if(!available()) {++failures;return false;}
    Node* node=count==DrawLayoutEntries?evict():&pool[count];
    node->key.assign(key);node->layout=layout;
    auto index=bucket(key.hash);
    node->bucketNext=buckets[index];node->older=newest;node->newer=nullptr;
    if(newest) newest->newer=node;else oldest=node;
    newest=buckets[index]=node;++count;return true;
  }
  void clear() noexcept {
    buckets.fill(nullptr);oldest=newest=nullptr;count=0;
  }
};
}
