#pragma once
#include "wizard101_asset_budget.h"
#include "d3d9_util.h"
#include "../dxso/dxso_isgn.h"
#include <memory>
#include <new>

namespace dxvk::wizard101 {
constexpr size_t DrawLayoutLimit = 1024u * 1024u;
constexpr size_t DrawLayoutEntries = 256;

// Every declaration field is retained, including fields that currently do not
// affect construction. Semantic order defines attribute locations. No pointers.
struct DrawLayoutKey {
  std::array<uint64_t, 64> elements;
  std::array<uint64_t, 2 * caps::InputRegisterCount> semantics;
  std::array<uint32_t, caps::MaxStreams> frequencies;
  uint32_t elementCount, semanticCount, instanced;
  bool programmable;
  uint64_t hash;

  DrawLayoutKey() = default;
  DrawLayoutKey(const DrawLayoutKey& b) { *this = b; }
  DrawLayoutKey& operator=(const DrawLayoutKey& b) {
    elementCount = b.elementCount; semanticCount = b.semanticCount;
    instanced = b.instanced; programmable = b.programmable; hash = b.hash;
    frequencies = b.frequencies;
    std::copy_n(b.elements.begin(), elementCount, elements.begin());
    std::copy_n(b.semantics.begin(), semanticCount, semantics.begin());
    return *this;
  }
  static bool make(const D3D9VertexElements& decl, const DxsoIsgn& isgn,
      const std::array<uint32_t, caps::MaxStreams>& freq, uint32_t flags,
      bool shader, DrawLayoutKey& key) {
    if (decl.size() > key.elements.size() || isgn.elemCount > key.semantics.size()) return false;
    key.elementCount = decl.size(); key.semanticCount = isgn.elemCount;
    key.frequencies = freq; key.instanced = flags; key.programmable = shader;
    uint64_t h = 14695981039346656037ull;
    auto add = [&](uint64_t v) { h = (h ^ v) * 1099511628211ull; };
    add(key.elementCount); add(key.semanticCount); add(flags); add(shader);
    for (size_t i = 0; i < decl.size(); ++i) {
      const auto& e = decl[i];
      if (e.Stream >= caps::MaxStreams || e.Type >= D3DDECLTYPE_UNUSED) return false;
      key.elements[i] = uint64_t(e.Stream) | (uint64_t(e.Offset) << 16) |
        (uint64_t(e.Type) << 32) | (uint64_t(e.Method) << 40) |
        (uint64_t(e.Usage) << 48) | (uint64_t(e.UsageIndex) << 56);
      add(key.elements[i]);
    }
    for (uint32_t i = 0; i < isgn.elemCount; ++i) {
      key.semantics[i] = uint64_t(uint32_t(isgn.elems[i].semantic.usage)) |
        (uint64_t(isgn.elems[i].semantic.usageIndex) << 32);
      add(key.semantics[i]);
    }
    for (auto f : freq) add(f);
    h ^= h >> 33; h *= 0xff51afd7ed558ccdull; h ^= h >> 33;
    key.hash = h;
    return true;
  }
  bool operator==(const DrawLayoutKey& b) const {
    return elementCount == b.elementCount && semanticCount == b.semanticCount &&
      instanced == b.instanced && programmable == b.programmable && frequencies == b.frequencies &&
      std::equal(elements.begin(), elements.begin() + elementCount, b.elements.begin()) &&
      std::equal(semantics.begin(), semantics.begin() + semanticCount, b.semantics.begin());
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

// Single command-stream owner. Fixed buckets and intrusive LRU keep allocator
// overhead charged conservatively; each node owns its lease before allocation.
class DrawLayoutCache {
  struct Node {
    AssetLease lease;
    DrawLayoutKey key;
    DrawLayout layout;
    Node *bucketNext = nullptr, *older = nullptr, *newer = nullptr;
    Node(AssetLease&& budget, const DrawLayoutKey& k, const DrawLayout& v): lease(std::move(budget)), key(k), layout(v) { }
  };
  AssetLease baseLease;
  std::array<Node*, 512> buckets{};
  Node *oldest = nullptr, *newest = nullptr;
  size_t count = 0, retained = 0;
  bool collide, failAllocation;
  size_t bucket(uint64_t hash) const { return collide ? 0 : hash % buckets.size(); }
  void unlinkLru(Node* node) {
    if (node->older) node->older->newer = node->newer; else oldest = node->newer;
    if (node->newer) node->newer->older = node->older; else newest = node->older;
  }
  void touch(Node* node) {
    if (node == newest) return;
    unlinkLru(node); node->older = newest; node->newer = nullptr;
    if (newest) newest->newer = node; else oldest = node;
    newest = node;
  }
  void evict() {
    Node* node = oldest;
    auto** link = &buckets[bucket(node->key.hash)];
    while (*link != node) link = &(*link)->bucketNext;
    *link = node->bucketNext;
    unlinkLru(node); retained -= node->lease.size; --count; ++evictions;
    delete node;
  }
public:
  uint64_t hits = 0, misses = 0, evictions = 0, failures = 0;
  explicit DrawLayoutCache(bool collision = false, bool allocation = false)
    : baseLease(sizeof(DrawLayoutCache) + 32), collide(collision), failAllocation(allocation) {
    retained = baseLease.size;
  }
  ~DrawLayoutCache() { clear(); }
  bool available() const { return baseLease.size != 0; }
  size_t entries() const { return count; }
  size_t bytes() const { return retained; }
  const DrawLayout* find(const DrawLayoutKey& key) {
    if (!available()) return nullptr;
    for (Node* node = buckets[bucket(key.hash)]; node; node = node->bucketNext) {
      if ((collide || node->key.hash == key.hash) && node->key == key) {
        touch(node); ++hits; return &node->layout;
      }
    }
    ++misses; return nullptr;
  }
  bool publish(const DrawLayoutKey& key, const DrawLayout& layout) noexcept {
    if (!available() || failAllocation) { ++failures; return false; }
    constexpr size_t charge = sizeof(Node) + 32;
    if (charge + baseLease.size > DrawLayoutLimit) { ++failures; return false; }
    while (count >= DrawLayoutEntries || retained + charge > DrawLayoutLimit) evict();
    try {
      AssetLease budget(charge);
      if (!budget.size) { ++failures; return false; }
      std::unique_ptr<Node> node(new Node(std::move(budget), key, layout));
      auto index = bucket(key.hash);
      node->bucketNext = buckets[index]; node->older = newest;
      if (newest) newest->newer = node.get(); else oldest = node.get();
      newest = buckets[index] = node.get();
      retained += node->lease.size; ++count; node.release(); return true;
    } catch (...) { ++failures; return false; }
  }
  void clear() { while (oldest) evict(); }
};
}
