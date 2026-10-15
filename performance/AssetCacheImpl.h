// Included inside dxvk::wizard101, after the common asset types.
constexpr size_t PersistentAssetLimit=32u*1024u*1024u;
inline unsigned assetCodec(const void* bytes,UINT count) {
  const auto* p=static_cast<const unsigned char*>(bytes);
  if(count>=8 && !std::memcmp(p,"\x89PNG\r\n\x1a\n",8)) return 0;
  if(count>=3 && p[0]==0xff && p[1]==0xd8 && p[2]==0xff) return 1;
  if(count>=4 && !std::memcmp(p,"DDS ",4)) return 2;
  if(count>=2 && p[0]=='B' && p[1]=='M') return 3;
  return 4; // Unclassified codecs retain their native initialization path.
}
struct AssetFile {
  HANDLE value=INVALID_HANDLE_VALUE;
  explicit AssetFile(HANDLE h=INVALID_HANDLE_VALUE):value(h) { }
  ~AssetFile() { if(value!=INVALID_HANDLE_VALUE) CloseHandle(value); }
  AssetFile(const AssetFile&)=delete;
};
inline bool assetFileDigest(HANDLE file,std::array<unsigned char,32>& digest) {
  BCRYPT_ALG_HANDLE alg=nullptr; BCRYPT_HASH_HANDLE hash=nullptr;
  bool ok=false;
  if(BCryptOpenAlgorithmProvider(&alg,BCRYPT_SHA256_ALGORITHM,nullptr,0)>=0
      && BCryptCreateHash(alg,&hash,nullptr,0,nullptr,0,0)>=0) {
    unsigned char block[16384]; DWORD read=0; BOOL result;
    while((result=ReadFile(file,block,sizeof(block),&read,nullptr)) && read)
      if(BCryptHashData(hash,block,read,0)<0) { result=FALSE; break; }
    ok=result && BCryptFinishHash(hash,digest.data(),digest.size(),0)>=0;
  }
  if(hash) BCryptDestroyHash(hash); if(alg) BCryptCloseAlgorithmProvider(alg,0);
  return ok;
}
inline bool assetModuleDigest(HMODULE module,std::array<unsigned char,32>& digest) {
  wchar_t path[32768];
  if(!module || !GetModuleFileNameW(module,path,32768)) return false;
  AssetFile file(CreateFileW(path,GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,0,nullptr));
  return file.value!=INVALID_HANDLE_VALUE && assetFileDigest(file.value,digest);
}
struct PreparedAsset {
  std::shared_ptr<const AssetEntry> entry;
  std::shared_ptr<AssetLease> lease;
  IDirect3DTexture9* texture=nullptr;
  void (*release)(IDirect3DTexture9*)=nullptr;
  ~PreparedAsset() { if(texture) release(texture); }
};
class AssetCache {
  BCRYPT_ALG_HANDLE sha=nullptr;
  std::mutex lock;
  std::list<std::shared_ptr<const AssetEntry>> lru,known;
  std::list<std::shared_ptr<PreparedAsset>> prepared;
  std::array<unsigned char,32> compatibility{};
  std::string path;
  size_t knownBytes=0;
  bool ready=false,compatible=false,dirty=false;
  std::array<std::atomic<bool>,4> codecReady{};
  static size_t recordBytes(const AssetEntry& e) {
    size_t n=sizeof(AssetKey)+sizeof(uint32_t)*10;
    for(const auto& l:e.levels) n+=sizeof(uint32_t)*4+l.pixels.size();
    return n;
  }
  void track(const std::shared_ptr<const AssetEntry>& e) {
    for(auto i=known.begin();i!=known.end();++i) if((*i)->key==e->key) {
      knownBytes-=recordBytes(**i); known.erase(i); break;
    }
    const size_t size=recordBytes(*e);
    if(size>PersistentAssetLimit-128) return;
    while(!known.empty() && (knownBytes+size>PersistentAssetLimit-128 || known.size()>=4096)) {
      knownBytes-=recordBytes(*known.back()); known.pop_back();
    }
    known.push_front(e); knownBytes+=size; dirty=true;
  }
public:
  bool canReuse(unsigned codec) { return codec<codecReady.size() && codecReady[codec].load(); }
  void observedSuccess(unsigned codec) { if(codec<codecReady.size()) codecReady[codec].store(true); }
  std::atomic<uint64_t> hits{0},misses{0},insertions{0},preparedHits{0},preparedCount{0};
  AssetCache() { BCryptOpenAlgorithmProvider(&sha,BCRYPT_SHA256_ALGORITHM,nullptr,0); }
  ~AssetCache() { if(sha) BCryptCloseAlgorithmProvider(sha,0); }
  bool key(const void* bytes,UINT count,const std::array<uint32_t,12>& params,AssetKey& result) {
    if(!sha || !bytes || !count) return false;
    result.parameters=params;
    return BCryptHash(sha,nullptr,0,(PUCHAR)bytes,count,result.digest.data(),result.digest.size())>=0;
  }
  bool fileKey(HANDLE file,UINT count,const std::array<uint32_t,12>& params,AssetKey& result) {
    if(!count) return false;
    result.parameters=params;
    return assetFileDigest(file,result.digest);
  }
  std::shared_ptr<const AssetEntry> find(const AssetKey& key,bool needsInfo) {
    std::lock_guard<std::mutex> guard(lock);
    for(auto i=lru.begin();i!=lru.end();++i) if((*i)->key==key && (!needsInfo || (*i)->hasInfo)) {
      auto entry=*i; lru.splice(lru.begin(),lru,i); ++hits; return entry;
    }
    ++misses; return {};
  }
  bool takePrepared(const AssetKey& key,IDirect3DTexture9** output,ImageInfo* info) {
    std::shared_ptr<PreparedAsset> item;
    { std::lock_guard<std::mutex> guard(lock);
      if(!ready) return false;
      for(auto i=prepared.begin();i!=prepared.end();++i)
        if((*i)->entry->key==key && (!info || (*i)->entry->hasInfo)) {
          item=std::move(*i); prepared.erase(i); break;
        }
    }
    if(!item) return false;
    // Public ownership takes over before dropping our private ref. No device cycle.
    item->texture->AddRef(); *output=item->texture;
    if(info) *info=item->entry->info;
    ++hits; ++preparedHits; return true;
  }
  void clear() {
    std::list<std::shared_ptr<const AssetEntry>> retired;
    std::list<std::shared_ptr<PreparedAsset>> textures;
    { std::lock_guard<std::mutex> guard(lock); retired.swap(lru); textures.swap(prepared); ready=false; }
  }
  void remember(const AssetKey& key,IDirect3DTexture9* texture,const ImageInfo* info) {
    D3DSURFACE_DESC desc{};
    if(!texture || FAILED(texture->GetLevelDesc(0,&desc)) || desc.Pool!=D3DPOOL_MANAGED || desc.Usage) return;
    const auto count=texture->GetLevelCount();
    if(!count || count>15) return;
    size_t size=sizeof(AssetEntry)+512+count*(sizeof(AssetLevel)+64);
    std::vector<AssetLevel> levels; levels.reserve(count);
    for(UINT i=0;i<count;++i) {
      D3DSURFACE_DESC d{}; AssetLevel l{};
      if(FAILED(texture->GetLevelDesc(i,&d)) || !d.Width || !d.Height || d.Width>16384 || d.Height>16384
          || d.Format!=desc.Format || !layout(d.Format,d.Width,d.Height,l.rowBytes,l.rows)) return;
      l.width=d.Width; l.height=d.Height;
      size+=size_t(l.rowBytes)*l.rows; if(size>AssetLimit) return;
      levels.push_back(std::move(l));
    }
    std::list<std::shared_ptr<const AssetEntry>> retired;
    { std::lock_guard<std::mutex> guard(lock);
      // Learned snapshots share leases with the process cache; evict both if necessary.
      while(!known.empty() && assetBytes.load()+size>AssetLimit) {
        knownBytes-=recordBytes(*known.back()); retired.splice(retired.end(),known,std::prev(known.end()));
      }
      while(!lru.empty() && (assetBytes.load()+size>AssetLimit || lru.size()>=4096))
        retired.splice(retired.end(),lru,std::prev(lru.end()));
    }
    retired.clear();
    auto lease=std::make_shared<AssetLease>(size); if(!lease->size) return;
    auto entry=std::make_shared<AssetEntry>(); entry->lease=lease; entry->key=key; entry->format=desc.Format;
    entry->levels=std::move(levels); if(info) { entry->hasInfo=true; entry->info=*info; }
    for(UINT i=0;i<count;++i) {
      auto& level=entry->levels[i]; level.pixels.resize(size_t(level.rowBytes)*level.rows);
      D3DLOCKED_RECT rect{};
      if(FAILED(texture->LockRect(i,&rect,nullptr,D3DLOCK_READONLY))) return;
      if(!rect.pBits || rect.Pitch<0 || UINT(rect.Pitch)<level.rowBytes) { texture->UnlockRect(i); return; }
      for(UINT y=0;y<level.rows;++y) std::memcpy(level.pixels.data()+size_t(y)*level.rowBytes,(const unsigned char*)rect.pBits+size_t(y)*rect.Pitch,level.rowBytes);
      if(FAILED(texture->UnlockRect(i))) return;
    }
    { std::lock_guard<std::mutex> guard(lock);
      for(auto i=lru.begin();i!=lru.end();++i) if((*i)->key==key) { lru.erase(i); break; }
      lru.push_front(entry); track(entry); ++insertions;
    }
  }
  static HRESULT restore(const AssetEntry& entry,IDirect3DDevice9* device,IDirect3DTexture9** output,ImageInfo* info) {
    if(entry.levels.empty() || !device || !output) return D3DERR_INVALIDCALL;
    if(feature("W101_PERFORMANCE_TEST") && feature("W101_ASSET_PREPARE_TEST","create")) return E_OUTOFMEMORY;
    IDirect3DTexture9* texture=nullptr;
    HRESULT hr=device->CreateTexture(entry.levels[0].width,entry.levels[0].height,entry.levels.size(),0,entry.format,D3DPOOL_MANAGED,&texture,nullptr);
    if(FAILED(hr)) return hr;
    for(UINT i=0;i<entry.levels.size();++i) {
      const auto& level=entry.levels[i]; D3DLOCKED_RECT rect{};
      if(feature("W101_PERFORMANCE_TEST") && feature("W101_ASSET_PREPARE_TEST","lock")) { texture->Release(); return E_OUTOFMEMORY; }
      hr=texture->LockRect(i,&rect,nullptr,0);
      if(FAILED(hr)) { texture->Release(); return hr; }
      if(!rect.pBits || rect.Pitch<0 || UINT(rect.Pitch)<level.rowBytes) { texture->UnlockRect(i); texture->Release(); return D3DERR_INVALIDCALL; }
      for(UINT y=0;y<level.rows;++y) std::memcpy((unsigned char*)rect.pBits+size_t(y)*rect.Pitch,level.pixels.data()+size_t(y)*level.rowBytes,level.rowBytes);
      hr=texture->UnlockRect(i); if(FAILED(hr)) { texture->Release(); return hr; }
    }
    if(info) *info=entry.info;
    *output=texture; return D3D_OK;
  }
  void configure(IDirect3DDevice9* device) {
    path=env::getEnvVar("W101_ASSET_CACHE_FILE");
    if(path.empty() || !sha) return;
    HMODULE renderer=nullptr;
    GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS|GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
        (LPCWSTR)&assetModuleDigest,&renderer);
    struct Signature {
      std::array<unsigned char,32> renderer,decoder;
      D3DCAPS9 caps{}; D3DADAPTER_IDENTIFIER9 adapter{};
    } signature{};
    IDirect3D9* api=nullptr; D3DDEVICE_CREATION_PARAMETERS creation{};
    if(!assetModuleDigest(renderer,signature.renderer) || !assetModuleDigest(GetModuleHandleW(L"d3dx9_43.dll"),signature.decoder)
        || FAILED(device->GetDeviceCaps(&signature.caps)) || FAILED(device->GetCreationParameters(&creation))
        || FAILED(device->GetDirect3D(&api))) return;
    HRESULT hr=api->GetAdapterIdentifier(creation.AdapterOrdinal,0,&signature.adapter); api->Release();
    compatible=SUCCEEDED(hr) && BCryptHash(sha,nullptr,0,(PUCHAR)&signature,sizeof(signature),compatibility.data(),compatibility.size())>=0;
  }
  void load() {
    if(!compatible) return;
    AssetFile file(CreateFileA(path.c_str(),GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,0,nullptr));
    LARGE_INTEGER length{};
    if(file.value==INVALID_HANDLE_VALUE || !GetFileSizeEx(file.value,&length) || length.QuadPart<80
        || length.QuadPart>PersistentAssetLimit) return;
    // Verify the entire bounded stream before accepting any entry. No 32 MiB scratch copy.
    BCRYPT_HASH_HANDLE hash=nullptr;
    if(BCryptCreateHash(sha,&hash,nullptr,0,nullptr,0,0)<0) return;
    unsigned char block[16384]; size_t remaining=size_t(length.QuadPart)-32; bool valid=true;
    while(remaining) {
      DWORD read=0,n=DWORD(std::min(remaining,sizeof(block)));
      if(!ReadFile(file.value,block,n,&read,nullptr) || read!=n || BCryptHashData(hash,block,n,0)<0) { valid=false; break; }
      remaining-=n;
    }
    std::array<unsigned char,32> got{},want{}; DWORD read=0;
    valid=valid && ReadFile(file.value,want.data(),32,&read,nullptr) && read==32
        && BCryptFinishHash(hash,got.data(),32,0)>=0 && got==want;
    BCryptDestroyHash(hash); if(!valid) return;
    LARGE_INTEGER zero{}; if(!SetFilePointerEx(file.value,zero,nullptr,FILE_BEGIN)) return;
    size_t available=size_t(length.QuadPart)-32;
    auto get=[&](void* dst,size_t n) {
      DWORD read=0; if(n>available || !ReadFile(file.value,dst,DWORD(n),&read,nullptr) || read!=n) return false;
      available-=n; return true;
    };
    uint32_t header[4]{}; std::array<unsigned char,32> signature{};
    if(!get(header,sizeof(header)) || header[0]!=0x41313057 || header[1]!=0x53455453 || header[2]!=1
        || header[3]>4096 || !get(signature.data(),32) || signature!=compatibility) return;
    std::list<std::shared_ptr<const AssetEntry>> loaded;
    for(uint32_t i=0;i<header[3];++i) {
      auto e=std::make_shared<AssetEntry>(); uint32_t meta[9]{};
      if(!get(&e->key,sizeof(e->key)) || !get(meta,sizeof(meta)) || !meta[1] || meta[1]>15 || meta[2]>1) return;
      e->format=D3DFORMAT(meta[0]); e->hasInfo=meta[2];
      // The seventh image-info field follows separately for a stable 32-bit format.
      e->info={meta[3],meta[4],meta[5],meta[6],D3DFORMAT(meta[7]),D3DRESOURCETYPE(meta[8]),0};
      if(!get(&e->info.ImageFileFormat,4) || e->key.parameters[0]>2 || !e->key.parameters[1]
          || (e->key.parameters[0] && (e->key.parameters[5] || e->key.parameters[7]!=D3DPOOL_MANAGED))) return;
      size_t size=sizeof(AssetEntry)+512+meta[1]*(sizeof(AssetLevel)+64);
      // Reserve before any pixel allocation, then grow the lease within the common budget.
      e->levels.reserve(meta[1]);
      for(uint32_t mip=0;mip<meta[1];++mip) {
        AssetLevel l{}; uint32_t dims[4]{},bytes,rows;
        if(!get(dims,sizeof(dims)) || !dims[0] || !dims[1] || dims[0]>16384 || dims[1]>16384
            || !layout(e->format,dims[0],dims[1],bytes,rows) || dims[2]!=rows || dims[3]!=bytes
            || (mip && (dims[0]!=std::max(1u,e->levels[0].width>>mip) || dims[1]!=std::max(1u,e->levels[0].height>>mip)))) return;
        size_t n=size_t(bytes)*rows; if(n>available || size+n>PersistentAssetLimit) return;
        auto pixelLease=std::make_shared<AssetLease>(n); if(!pixelLease->size) return;
        l.width=dims[0]; l.height=dims[1]; l.rows=rows; l.rowBytes=bytes; l.pixels.resize(n);
        if(!get(l.pixels.data(),n)) return;
        // Each entry ultimately owns one lease. Pixel memory remains reserved during construction.
        if(!e->lease) { e->lease=std::make_shared<AssetLease>(size); if(!e->lease->size) return; }
        e->lease->size+=pixelLease->size; pixelLease->size=0; size+=n;
        e->levels.push_back(std::move(l));
      }
      for(const auto& old:loaded) if(old->key==e->key) return;
      loaded.push_back(e);
    }
    if(available) return;
    { std::lock_guard<std::mutex> guard(lock);
      lru=loaded; known=std::move(loaded); knownBytes=0;
      for(const auto& e:known) knownBytes+=recordBytes(*e);
    }
  }
  void prepare(IDirect3DDevice9* device,void (*retain)(IDirect3DTexture9*),void (*release)(IDirect3DTexture9*)) {
    std::list<std::shared_ptr<const AssetEntry>> entries;
    { std::lock_guard<std::mutex> guard(lock); entries=lru; }
    for(const auto& e:entries) {
      // Managed CPU storage, aligned staging, converted GPU pixels and object overhead.
      // Use RGBA worst case even for compressed or packed formats.
      size_t reserve=16384+e->levels.size()*4096;
      for(const auto& l:e->levels) reserve+=size_t(l.width)*l.height*12;
      if(feature("W101_PERFORMANCE_TEST") && feature("W101_ASSET_PREPARE_TEST","allocation")) continue;
      auto lease=std::make_shared<AssetLease>(reserve); if(!lease->size) continue;
      auto item=std::make_shared<PreparedAsset>(); item->entry=e; item->lease=lease; item->release=release;
      IDirect3DTexture9* texture=nullptr;
      if(FAILED(restore(*e,device,&texture,nullptr))) continue;
      // Conversion to private ownership happens before any throwing operation.
      retain(texture); item->texture=texture; texture->Release();
      texture->PreLoad();
      if(feature("W101_PERFORMANCE_TEST") && feature("W101_ASSET_PREPARE_TEST","upload")) throw std::bad_alloc();
      { std::lock_guard<std::mutex> guard(lock); prepared.push_back(item); }
      ++preparedCount;
    }
  }
  void markReady() { std::lock_guard<std::mutex> guard(lock); ready=true; }
  void save() {
    if(!compatible || !dirty) return;
    std::list<std::shared_ptr<const AssetEntry>> entries;
    { std::lock_guard<std::mutex> guard(lock); entries=known; }
    uint32_t header[]={0x41313057,0x53455453,1,uint32_t(entries.size())};
    size_t total=sizeof(header)+32+32;
    for(const auto& e:entries) total+=recordBytes(*e);
    if(total>PersistentAssetLimit) return;
    auto temporary=path+"."+std::to_string(GetCurrentProcessId())+"."+std::to_string(GetTickCount64())+".tmp";
    bool ok=false;
    {
      AssetFile file(CreateFileA(temporary.c_str(),GENERIC_WRITE,0,nullptr,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,nullptr));
      if(file.value==INVALID_HANDLE_VALUE) return;
      BCRYPT_HASH_HANDLE hash=nullptr;
      if(BCryptCreateHash(sha,&hash,nullptr,0,nullptr,0,0)>=0) {
        auto put=[&](const void* src,size_t n) {
          DWORD written=0; return WriteFile(file.value,src,DWORD(n),&written,nullptr) && written==n
              && BCryptHashData(hash,(PUCHAR)src,DWORD(n),0)>=0;
        };
        ok=put(header,sizeof(header)) && put(compatibility.data(),32);
        for(const auto& e:entries) {
          uint32_t meta[]={uint32_t(e->format),uint32_t(e->levels.size()),uint32_t(e->hasInfo),e->info.Width,e->info.Height,e->info.Depth,e->info.MipLevels,uint32_t(e->info.Format),uint32_t(e->info.ResourceType),e->info.ImageFileFormat};
          ok=ok && put(&e->key,sizeof(e->key)) && put(meta,sizeof(meta));
          for(const auto& l:e->levels) {
            uint32_t dims[]={l.width,l.height,l.rows,l.rowBytes};
            ok=ok && put(dims,sizeof(dims)) && put(l.pixels.data(),l.pixels.size());
          }
        }
        std::array<unsigned char,32> digest{}; DWORD written=0;
        ok=ok && BCryptFinishHash(hash,digest.data(),32,0)>=0
            && WriteFile(file.value,digest.data(),32,&written,nullptr) && written==32 && FlushFileBuffers(file.value);
        BCryptDestroyHash(hash);
      }
    }
    if(feature("W101_PERFORMANCE_TEST") && feature("W101_ASSET_PREPARE_TEST","save")) ok=false;
    if(ok) ok=MoveFileExA(temporary.c_str(),path.c_str(),MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH);
    if(!ok) DeleteFileA(temporary.c_str());
  }
};
inline std::mutex cacheRegistryLock;
// Orderly teardown unregisters and releases private textures. Abrupt process
// detachment leaves the registry to the OS: never release COM objects under the loader lock.
inline auto& cacheRegistry=*new std::vector<std::pair<IDirect3DDevice9*,std::shared_ptr<AssetCache>>>;
inline std::shared_ptr<AssetCache> assetCache(IDirect3DDevice9* device) {
  std::lock_guard<std::mutex> guard(cacheRegistryLock);
  for(const auto& item:cacheRegistry) if(item.first==device) return item.second;
  return {};
}
inline void registerAssetDevice(IDirect3DDevice9* device) {
  if(!feature("W101_ASSET_CACHE")) return;
  try { auto cache=std::make_shared<AssetCache>();
    std::lock_guard<std::mutex> guard(cacheRegistryLock); cacheRegistry.emplace_back(device,std::move(cache));
  } catch(...) { }
}
inline void unregisterAssetDevice(IDirect3DDevice9* device) {
  std::shared_ptr<AssetCache> retired;
  { std::lock_guard<std::mutex> guard(cacheRegistryLock);
    for(auto i=cacheRegistry.begin();i!=cacheRegistry.end();++i) if(i->first==device) { retired=std::move(i->second); cacheRegistry.erase(i); break; } }
  if(retired) {
    try { retired->save(); } catch(...) { }
    retired->clear();
    Logger::info(str::format("W101 asset cache: hits=",retired->hits.load()," misses=",retired->misses.load()," insertions=",retired->insertions.load()," retained_process_bytes=",assetBytes.load()," prepared=",retired->preparedCount.load()," prepared_hits=",retired->preparedHits.load()));
  }
}
