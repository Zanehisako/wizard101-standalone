#include "util/util_cache_file.h"
#include <thread>
#include <atomic>
#include <stdexcept>
#include <iostream>
using namespace dxvk;
static void check(bool ok) { if (!ok) throw std::runtime_error("cache file check failed"); }
int main() {
  try {
    const auto key = Sha1Hash::compute("revision-one", 12), other = Sha1Hash::compute("revision-two", 12);
    std::vector<char> data(1024, 'x'), loaded;
    check(cachefile::write("test.vkcache", key, data));
    check(cachefile::read("test.vkcache", key, loaded) && loaded == data);
    check(!cachefile::read("test.vkcache", other, loaded));
    { std::fstream f("test.vkcache", std::ios::in | std::ios::out | std::ios::binary); f.seekp(sizeof(cachefile::Header) + 13); f.put('y'); }
    check(!cachefile::read("test.vkcache", key, loaded));
    check(cachefile::write("test.vkcache", key, data));
    { std::fstream f("test.vkcache", std::ios::in | std::ios::out | std::ios::binary); f.seekp(4); uint32_t version = 2; f.write((char*)&version,4); }
    check(!cachefile::read("test.vkcache", key, loaded));
    check(cachefile::write("test.vkcache", key, data));
    { std::ofstream abandoned("test.vkcache.interrupted.tmp"); abandoned << "partial"; }
    check(cachefile::read("test.vkcache", key, loaded) && loaded == data);
    check(!cachefile::write("missing-directory/test.vkcache", key, data));
    check(cachefile::read("test.vkcache", key, loaded) && loaded == data);
    std::atomic<bool> failed {false}; std::vector<std::thread> workers;
    for (int i=0; i<8; ++i) workers.emplace_back([&,i] {
      std::vector<char> own(1024, char('a'+i));
      for (int j=0; j<40; ++j) {
        // Windows permits a transient sharing violation; it must not damage the prior file.
        cachefile::write("test.vkcache", key, own);
        std::vector<char> read;
        if (cachefile::read("test.vkcache", key, read))
          for (char c : read) if (c != read.front()) failed = true;
      }
    });
    for (auto& worker : workers) worker.join(); check(!failed);
    check(cachefile::read("test.vkcache", key, loaded));
    std::vector<char> oversized(cachefile::MaxPayload + 1);
    check(!cachefile::write("test.vkcache", key, oversized));
    check(cachefile::read("test.vkcache", key, loaded));
    { std::ofstream large("oversized.vkcache", std::ios::binary); large.seekp(cachefile::MaxFile); large.put('x'); }
    check(!cachefile::read("oversized.vkcache",key,loaded));
    std::cout << "PASS cache envelope: reload, corruption, key/version mismatch, interrupted temp, unwritable path, concurrent writers, 64 MiB cap\n";
    return 0;
  } catch(const std::exception& e) { std::cout << "FAIL " << e.what() << '\n'; return 1; }
}
