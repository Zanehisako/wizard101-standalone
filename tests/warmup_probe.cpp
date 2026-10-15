#include "d3d9/d3d9_warmup.h"
#include "dxso/dxso_decoder.h"
#include "dxso/dxso_header.h"
#include "dxso/dxso_code.h"
#include "util/log/log.h"
#include "util/util_warmup.h"
#include <thread>
#include <future>
#include <iostream>
#include <stdexcept>
#include <chrono>
namespace dxvk { Logger Logger::s_instance("warmup-unit.log"); }
using namespace dxvk;
using namespace std::chrono_literals;
static void check(bool value) { if (!value) throw std::runtime_error("warm-up invariant failed"); }
int main() {
  try {
    const auto key = Sha1Hash::compute("synthetic", 9);
    W101ShaderCatalog::Record shader { 1, { 0xfffe0300, 0x0000ffff } };
    std::vector<W101ShaderCatalog::Record> decoded;
    auto encoded = W101ShaderCatalog::encode({ shader });
    check(W101ShaderCatalog::decode(encoded, decoded) && decoded.size() == 1);
    auto damaged = encoded; damaged.pop_back(); check(!W101ShaderCatalog::decode(damaged, decoded));
    damaged = encoded; uint32_t size = 0xffffffff; memcpy(damaged.data() + 8, &size, 4);
    check(!W101ShaderCatalog::decode(damaged, decoded));
    check(!W101ShaderCatalog::decode(std::vector<char>(W101ShaderCatalog::MaxBytes + 1), decoded));
    auto wrongStage = shader; wrongStage.stage = 16;
    check(W101ShaderCatalog::decode(W101ShaderCatalog::encode({wrongStage}), decoded) && decoded.empty());
    std::vector<W101ShaderCatalog::Record> huge(2050, shader);
    check(W101ShaderCatalog::decode(W101ShaderCatalog::encode(huge), decoded) && decoded.size() == 2048);
    // Even a checksummed, malformed token stream must fail inside the bounded
    // decoder, rather than walk past the restored bytecode allocation.
    std::vector<uint32_t> truncated { 0xfffe0300, 0x0f000001, 0x0000ffff };
    bool rejected = false;
    try { DxsoReader reader(reinterpret_cast<char*>(truncated.data()), truncated.size()*4); DxsoHeader header(reader); DxsoCode code(reader); auto iter = code.iter(); DxsoDecodeContext decoder(header.info()); while (decoder.decodeInstruction(iter)) {} }
    catch (...) { rejected = true; }
    check(rejected);
    WarmupGate gate(true);
    std::promise<void> entered;
    auto future = entered.get_future();
    std::thread background;
    {
      WarmupGate::Foreground required(gate);
      background = std::thread([&] { WarmupGate::Background queued(gate); check(bool(queued)); entered.set_value(); });
      check(future.wait_for(50ms) == std::future_status::timeout);
      auto begin = std::chrono::steady_clock::now();
      { WarmupGate::Foreground secondRequired(gate); }
      check(std::chrono::steady_clock::now() - begin < 50ms);
    }
    check(future.wait_for(1s) == std::future_status::ready); background.join();
    {
      WarmupGate stopped(true); WarmupGate::Foreground required(stopped);
      std::promise<bool> cancelled; auto done = cancelled.get_future();
      std::thread waiter([&] { WarmupGate::Background pending(stopped); cancelled.set_value(bool(pending)); });
      stopped.stop(); check(!done.get()); waiter.join();
    }
    std::atomic<unsigned> restores { 0 };
    {
      W101ShaderCatalog learn("catalog.test", key, false, [](const auto&) {}, [] { return false; });
      // Catalog loading is deliberately off the caller thread.
      std::this_thread::sleep_for(100ms);
      for (int i=0; i<12; i++) learn.record(shader.stage, shader.words.data(), shader.words.size()*4);
      learn.stop();
    }
    std::vector<char> saved;
    check(cachefile::read("catalog.test", key, saved));
    check(W101ShaderCatalog::decode(saved, decoded) && decoded.size() == 1);
    {
      W101ShaderCatalog restored("catalog.test", key, true, [&](const auto&) { ++restores; }, [] { return false; });
      restored.waitStartup(); restored.stop();
    }
    check(restores == 1);
    {
      W101ShaderCatalog incompatible("catalog.test", Sha1Hash::compute("other",5), true, [&](const auto&) { ++restores; }, [] { return false; });
      incompatible.waitStartup(); incompatible.stop();
    }
    check(restores == 1);
    {
      W101ShaderCatalog unwritable("missing-dir/catalog.test", key, false, [](const auto&) {}, [] { return false; });
      std::this_thread::sleep_for(100ms); unwritable.record(shader.stage, shader.words.data(), shader.words.size()*4); unwritable.stop();
    }
    {
      W101ShaderCatalog busy("catalog.test", key, true, [](const auto&) {}, [] { return true; });
      auto begin = std::chrono::steady_clock::now(); busy.waitStartup();
      auto seconds = std::chrono::duration<double>(std::chrono::steady_clock::now()-begin).count();
      check(seconds >= 9.8 && seconds < 10.5); busy.stop();
    }
    std::cout << "PASS catalog limits, malformed bytecode, dedup, reload, incompatible key, unwritable storage, foreground priority, shutdown cancellation, 10-second startup budget\n";
    return 0;
  } catch (const std::exception& e) { std::cout << "FAIL " << e.what() << '\n'; return 1; }
}
