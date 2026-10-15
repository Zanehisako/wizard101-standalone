#pragma once
#include "../util/util_cache_file.h"
#include "../util/util_env.h"
#include <mutex>
#include <unordered_set>

namespace dxvk {
// Local rendering inputs, not timing telemetry. The compatibility envelope
// includes the renderer/backend/game identity supplied by the launcher.
class W101ArrivalInputs {
public:
  struct Record { uint32_t kind; std::vector<char> bytes; };
  static constexpr size_t Limit=32u*1024u*1024u-sizeof(cachefile::Header);
  std::vector<Record> records;
  bool restoring=false;
private:
  std::mutex mutex;
  std::unordered_set<std::string> known;
  std::string path;
  Sha1Hash compatibility;
  size_t size=4;
  bool dirty=false;
public:
  void configure() {
    auto key=env::getEnvVar("W101_ARRIVAL_KEY");
    auto dir=env::getEnvVar("W101_ARRIVAL_PATH");
    if(key.size()!=64 || dir.empty()) return;
    for(char c:key) if(!((c>='0'&&c<='9')||(c>='a'&&c<='f'))) return;
    compatibility=Sha1Hash::compute(key.data(),key.size());
    path=dir+"/arrival-inputs.v1";
    std::ifstream file(path,std::ios::binary|std::ios::ate);
    if(!file) { importLegacy(dir); return; }
    if(file.tellg()>std::streamoff(Limit+sizeof(cachefile::Header))) return;
    file.close();
    std::vector<char> data;
    if(!cachefile::read(path,compatibility,data) || data.size()<4 || data.size()>Limit) return;
    uint32_t count; std::memcpy(&count,data.data(),4);
    if(count>2048) return;
    std::vector<Record> parsed; size_t offset=4;
    for(uint32_t i=0;i<count;i++) {
      uint32_t kind,n;
      if(data.size()-offset<8) return;
      std::memcpy(&kind,data.data()+offset,4);std::memcpy(&n,data.data()+offset+4,4);offset+=8;
      if(kind<1 || kind>4 || n<4 || n%4 || n>65536 || n>data.size()-offset) return;
      parsed.push_back({kind,{data.data()+offset,data.data()+offset+n}});offset+=n;
    }
    if(offset!=data.size()) return;
    for(auto& r:parsed) record(r.kind,r.bytes.data(),r.bytes.size());
    dirty=false;
  }
  void importLegacy(const std::string& dir) {
    // Raw DXSO is portable input, not a compiled cache. Require its intact
    // bounded envelope, content/stage identity and full current DXSO validation
    // at restoration. No prior SPIR-V, MSL or driver code is imported here.
    std::string legacy=dir+"/../catalog-v1.w101shaders";
    std::ifstream f(legacy,std::ios::binary|std::ios::ate);
    if(!f || f.tellg()<std::streamoff(sizeof(cachefile::Header)+4)
        || f.tellg()>std::streamoff(Limit+sizeof(cachefile::Header))) return;
    cachefile::Header header;f.seekg(0);f.read((char*)&header,sizeof(header));f.close();
    std::vector<char> data;if(!cachefile::read(legacy,header.key,data) || data.size()<4) return;
    uint32_t count;std::memcpy(&count,data.data(),4);if(count>2048) return;
    size_t offset=4;std::vector<Record> parsed;
    for(uint32_t i=0;i<count;i++) {
      uint32_t stage,n,first,last;
      if(data.size()-offset<8) return;
      std::memcpy(&stage,data.data()+offset,4);std::memcpy(&n,data.data()+offset+4,4);offset+=8;
      if((stage!=1 && stage!=16) || n<8 || n%4 || n>65536 || n>data.size()-offset) return;
      std::memcpy(&first,data.data()+offset,4);std::memcpy(&last,data.data()+offset+n-4,4);
      if(first>>16!=(stage==1?0xfffeu:0xffffu) || last!=0x0000ffff) return;
      parsed.push_back({stage==1?1u:2u,{data.data()+offset,data.data()+offset+n}});offset+=n;
    }
    if(offset!=data.size()) return;
    for(auto& r:parsed) record(r.kind,r.bytes.data(),r.bytes.size());
  }
  void record(uint32_t kind,const void* data,size_t n) noexcept {
    if(path.empty() || restoring || n<4 || n>65536 || n%4) return;
    try {
      auto key=std::to_string(kind)+Sha1Hash::compute(data,n).toString();
      std::lock_guard<std::mutex> guard(mutex);
      if(records.size()>=2048 || size+8+n>Limit || known.count(key)) return;
      records.push_back({kind,std::vector<char>((const char*)data,(const char*)data+n)});
      known.insert(key);size+=8+n;dirty=true;
    } catch(...) { }
  }
  void save() noexcept {
    try {
      std::lock_guard<std::mutex> guard(mutex);
      if(path.empty() || !dirty) return;
      std::vector<char> data(size);uint32_t count=records.size();std::memcpy(data.data(),&count,4);
      size_t offset=4;
      for(const auto& r:records) {
        uint32_t n=r.bytes.size();std::memcpy(data.data()+offset,&r.kind,4);
        std::memcpy(data.data()+offset+4,&n,4);std::memcpy(data.data()+offset+8,r.bytes.data(),n);offset+=8+n;
      }
      if(cachefile::write(path,compatibility,data)) dirty=false;
    } catch(...) { }
  }
};
}
