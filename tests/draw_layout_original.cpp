// Independent oracle, copied from the installed baseline BindInputLayout.
#include "d3d9/wizard101_draw_layout_direct.h"
namespace dxvk::wizard101 {
void originalDrawLayout(const D3D9VertexElements& elements, const DxsoIsgn& isgn,
    const std::array<uint32_t, caps::MaxStreams>& freq, uint32_t instanced, DirectDrawLayout& out) {
  out.streamsUsed = 0; out.streamsInstanced = instanced;
  auto& attrList = out.attributes; auto& bindList = out.bindings;
  uint32_t attrMask = 0, bindMask = 0;
        for (uint32_t i = 0; i < isgn.elemCount; i++) {
          const auto& decl = isgn.elems[i];

          DxvkVertexAttribute attrib;
          attrib.location = i;
          attrib.binding  = caps::MaxStreams;
          attrib.format   = VK_FORMAT_R32G32B32A32_SFLOAT;
          attrib.offset   = 0;

          for (const auto& element : elements) {
            DxsoSemantic elementSemantic = { static_cast<DxsoUsage>(element.Usage), element.UsageIndex };
            if (elementSemantic.usage == DxsoUsage::PositionT)
              elementSemantic.usage = DxsoUsage::Position;

            if (elementSemantic == decl.semantic) {
              attrib.binding = uint32_t(element.Stream);
              attrib.format  = DecodeDecltype(D3DDECLTYPE(element.Type));
              attrib.offset  = element.Offset;

              out.streamsUsed |= 1u << attrib.binding;
              break;
            }
          }

          attrList[i] = attrib;

          DxvkVertexBinding binding;
          binding.binding = attrib.binding;
          //binding.extent = attrib.offset + lookupFormatInfo(attrib.format)->elementSize;

          uint32_t instanceData = freq[binding.binding % caps::MaxStreams];
          if (instanceData & D3DSTREAMSOURCE_INSTANCEDATA) {
            binding.fetchRate = instanceData & 0x7FFFFF; // Remove instance packed-in flags in the data.
            binding.inputRate = VK_VERTEX_INPUT_RATE_INSTANCE;
          }
          else {
            binding.fetchRate = 0;
            binding.inputRate = VK_VERTEX_INPUT_RATE_VERTEX;
          }

          /*if (bindMask & (1u << binding.binding)) {
            bindList.at(binding.binding).extent = std::max(
              bindList.at(binding.binding).extent, binding.extent);
          } else {*/
            bindList.at(binding.binding) = binding;
          //}

          attrMask |= 1u << i;
          bindMask |= 1u << binding.binding;
        }

        // Compact the attribute and binding lists to filter
        // out attributes and bindings not used by the shader
        uint32_t attrCount = CompactSparseList(attrList.data(), attrMask);
        uint32_t bindCount = CompactSparseList(bindList.data(), bindMask);


  out.attributeCount = attrCount; out.bindingCount = bindCount;
}
}
