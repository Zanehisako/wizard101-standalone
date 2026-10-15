#include "d3d9/d3d9_state.h"
#include "d3d9/d3d9_multithread.h"
#include "d3d9/wizard101_texture_profile.h"
#include <cassert>
#include <iostream>
#include <memory>
#include <thread>
#include <vector>
#include <limits>
#include <utility>
using namespace dxvk;
namespace dxvk { Logger Logger::s_instance("cpu-unit.log"); }
struct State {
  std::unique_ptr<D3D9ShaderConstantsVSSoftware> vsConsts = std::make_unique<D3D9ShaderConstantsVSSoftware>();
  std::unique_ptr<D3D9ShaderConstantsPS> psConsts = std::make_unique<D3D9ShaderConstantsPS>();
};
template<DxsoProgramType Stage, D3D9ConstantType Type, typename T>
void roundtrip(State& s, UINT start, const T* data, UINT count, bool emu) {
  UpdateStateConstants<Stage,Type>(&s,start,data,count,emu);
  assert((StateConstantsUnchanged<Stage,Type>(&s,start,data,count,emu)));
}
template<DxsoProgramType Stage>
void constants() {
  State s;
  float f[] = {1,2,3,4,5,6,7,8};
  assert((!StateConstantsUnchanged<Stage,D3D9ConstantType::Float>(&s,0,f,2,false)));
  roundtrip<Stage,D3D9ConstantType::Float>(s,0,f,2,false);
  f[7] = -1;
  assert((!StateConstantsUnchanged<Stage,D3D9ConstantType::Float>(&s,0,f,2,false)));
  roundtrip<Stage,D3D9ConstantType::Float>(s,0,f,2,false);
  for (bool emu : {false,true}) {
    float z[4] = {};
    roundtrip<Stage,D3D9ConstantType::Float>(s,5,z,1,emu);
    z[0] = -0.0f;
    assert((!StateConstantsUnchanged<Stage,D3D9ConstantType::Float>(&s,5,z,1,emu)));
    roundtrip<Stage,D3D9ConstantType::Float>(s,5,z,1,emu);
    z[0] = std::numeric_limits<float>::quiet_NaN();
    roundtrip<Stage,D3D9ConstantType::Float>(s,5,z,1,emu);
    uint32_t nan=0x7fc00123; memcpy(&z[0],&nan,4);
    assert((StateConstantsUnchanged<Stage,D3D9ConstantType::Float>(&s,5,z,1,emu)) == emu);
    z[1] = std::numeric_limits<float>::infinity();
    assert((!StateConstantsUnchanged<Stage,D3D9ConstantType::Float>(&s,5,z,1,emu)));
    roundtrip<Stage,D3D9ConstantType::Float>(s,5,z,1,emu);
  }
  int integers[8] = {INT_MIN,INT_MAX,0,-1,1,2,3,4};
  roundtrip<Stage,D3D9ConstantType::Int>(s,0,integers,2,false);
  integers[7]++;
  assert((!StateConstantsUnchanged<Stage,D3D9ConstantType::Int>(&s,0,integers,2,false)));
  BOOL b[5] = {0,1,-1,2,0};
  roundtrip<Stage,D3D9ConstantType::Bool>(s,11,b,5,false);
  b[2] = 1; b[3] = -42;
  assert((StateConstantsUnchanged<Stage,D3D9ConstantType::Bool>(&s,11,b,5,false)));
  b[4] = 7;
  assert((!StateConstantsUnchanged<Stage,D3D9ConstantType::Bool>(&s,11,b,5,false)));
  assert((StateConstantsUnchanged<Stage,D3D9ConstantType::Float>(&s,0,f,0,false)));
  if constexpr (Stage == DxsoProgramTypes::VertexShader) {
    BOOL crossed[4] = {1,0,-1,2};
    roundtrip<Stage,D3D9ConstantType::Bool>(s,30,crossed,4,false);
    roundtrip<Stage,D3D9ConstantType::Float>(s,8191,f,1,true);
    roundtrip<Stage,D3D9ConstantType::Int>(s,2047,integers,1,false);
  }
}
static double cpu() {
  FILETIME a,b,k,u; assert(GetProcessTimes(GetCurrentProcess(),&a,&b,&k,&u));
  auto tick=[](FILETIME x) { return (uint64_t(x.dwHighDateTime)<<32)|x.dwLowDateTime; };
  return (tick(k)+tick(u))/10000.0;
}
static void lockChecks() {
  D3D9Multithread m(TRUE), other(TRUE), unprotected(FALSE);
  auto a=m.AcquireLock(); auto b=m.AcquireLock();
  auto c=std::move(a); b=std::move(c); b=std::move(b);
  // Moved nested guards retain ownership even after the original outer guard
  // has been released; another thread must remain excluded.
  std::atomic<bool> entered {false}, started {false};
  std::thread waiter([&] { started=true; auto g=m.AcquireLock(); entered=true; });
  while (!started) std::this_thread::yield();
  Sleep(25); assert(!entered);
  b=D3D9DeviceLock(); waiter.join(); assert(entered);
  try { auto x=m.AcquireLock(); auto y=m.AcquireLock(); throw 1; } catch (...) { }
  auto x=other.AcquireLock(); x=m.AcquireLock(); x=D3D9DeviceLock();
  std::thread after([&] { auto g=m.AcquireLock(); entered=false; }); after.join(); assert(!entered);
  auto no=unprotected.AcquireLock();
  int value=0;
  std::vector<std::thread> ts;
  for(int i=0;i<4;i++) ts.emplace_back([&] { for(int j=0;j<25000;j++) { auto g=m.AcquireLock(); value++; } });
  for(auto& t:ts) t.join(); assert(value==100000);
  std::cout<<"PASS nested locks, thread exclusion, acquire/release, moves, self-move, exceptions, contention\n";
}
static void lockBench(const char* name) {
  D3D9Multithread m(TRUE);
  const auto start=cpu(); uint64_t total=0;
  if (!strcmp(name,"recursive")) {
    auto outer=m.AcquireLock();
    for(int j=0;j<12000000;j++) { auto g=m.AcquireLock(); total++; }
  } else {
    std::vector<std::thread> ts;
    for(int i=0;i<4;i++) ts.emplace_back([&] { for(int j=0;j<500000;j++) { auto g=m.AcquireLock(); total++; } });
    for(auto& t:ts) t.join();
  }
  std::cout<<"BENCH {\"workload\":\""<<name<<"\",\"cpu_ms\":"<<cpu()-start<<",\"operations\":"<<total<<"}\n";
}
int main(int argc,char** argv) {
  profileEnabled();
  if(argc==2) { lockBench(argv[1]); return 0; }
  constants<DxsoProgramTypes::VertexShader>(); constants<DxsoProgramTypes::PixelShader>();
  std::cout<<"PASS float, integer, bool normalization, bit equality, NaN emulation, signed zero, zero count\n";
  lockChecks();
  SetLastError(0x1234);
  int out=0;
  const auto hr=wizard101::TimedTextureCall("game_d3dx_texture_test",[](int* p) -> HRESULT {
    assert(GetLastError()==0x1234); *p=42; SetLastError(0x5678); return E_FAIL;
  },&out);
  assert(hr==E_FAIL && out==42 && GetLastError()==0x5678);
  std::cout<<"PASS texture timing preserves arguments, output, HRESULT and Win32 error\n";
  std::cout<<"MODE "<<cpuOptimizationName()<<"\n";
  if(profileEnabled()) { Sleep(2300); profileShutdown(); }
  std::cout<<"PASS all CPU unit checks\n";
}
