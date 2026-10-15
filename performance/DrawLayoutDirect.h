#pragma once
#include "d3d9_util.h"
#include "../dxso/dxso_isgn.h"
#if defined(__SSE2__) && (defined(__i386__) || defined(__x86_64__)) && !defined(W101_DIRECT_SCALAR_ONLY)
#include <emmintrin.h>
#define W101_DIRECT_SSE2 1
#else
#define W101_DIRECT_SSE2 0
#endif

namespace dxvk::wizard101 {
struct DirectDrawLayout {
  std::array<DxvkVertexAttribute, 2 * caps::InputRegisterCount> attributes;
  std::array<DxvkVertexBinding, 2 * caps::InputRegisterCount> bindings;
  uint32_t attributeCount = 0, bindingCount = 0, streamsUsed = 0, streamsInstanced = 0;
};

// The stack preparation is part of construction, never resource creation.
// Returning false leaves out untouched and invokes the original builder.
inline bool tryBuildDirectDrawLayout(const D3D9VertexElements& elements,
    const DxsoIsgn& isgn, const std::array<uint32_t, caps::MaxStreams>& freq,
    uint32_t instanced, DirectDrawLayout& out) {
#if W101_DIRECT_SSE2
  if (elements.size() < 8 || elements.size() > 64 || isgn.elemCount < 4 || isgn.elemCount > 32)
    return false;
  for (uint32_t i = 0; i < isgn.elemCount; ++i)
    if (uint32_t(isgn.elems[i].semantic.usage) > D3DDECLUSAGE_SAMPLE || isgn.elems[i].semantic.usageIndex > 255)
      return false;
  alignas(16) uint16_t semantics[64];
  for (size_t i = 0; i < elements.size(); ++i) {
    const auto& e = elements[i];
    if (e.Stream >= caps::MaxStreams || e.Type >= D3DDECLTYPE_UNUSED || e.Usage > D3DDECLUSAGE_SAMPLE)
      return false;
    auto usage = e.Usage == D3DDECLUSAGE_POSITIONT ? D3DDECLUSAGE_POSITION : e.Usage;
    semantics[i] = uint16_t(usage) | (uint16_t(e.UsageIndex) << 8);
  }
  uint32_t attrMask = 0, bindMask = 0;
  out.streamsUsed = 0; out.streamsInstanced = instanced;
  for (uint32_t i = 0; i < isgn.elemCount; ++i) {
    const auto& s = isgn.elems[i].semantic;
    uint16_t semantic = uint16_t(s.usage) | (uint16_t(s.usageIndex) << 8);
    const auto target = _mm_set1_epi16(static_cast<short>(semantic));
    size_t match = elements.size(), j = 0;
    for (; j + 8 <= elements.size(); j += 8) {
      const auto values = _mm_load_si128(reinterpret_cast<const __m128i*>(semantics + j));
      const unsigned mask = unsigned(_mm_movemask_epi8(_mm_cmpeq_epi16(values, target)));
      if (mask) { match = j + unsigned(__builtin_ctz(mask)) / 2; break; }
    }
    if (match == elements.size())
      for (; j < elements.size(); ++j)
        if (semantics[j] == semantic) { match = j; break; }
    DxvkVertexAttribute attrib { i, caps::MaxStreams, VK_FORMAT_R32G32B32A32_SFLOAT, 0 };
    if (match != elements.size()) {
      const auto& e = elements[match];
      attrib.binding = uint32_t(e.Stream);
      attrib.format = DecodeDecltype(D3DDECLTYPE(e.Type));
      attrib.offset = e.Offset;
      out.streamsUsed |= 1u << attrib.binding;
    }
    out.attributes[i] = attrib;
    DxvkVertexBinding binding;
    binding.binding = attrib.binding;
    const uint32_t instanceData = freq[binding.binding % caps::MaxStreams];
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
  return true;
#else
  return false;
#endif
}
}
