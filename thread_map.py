#!/usr/bin/env python3
"""Read Wine 11 thread identities and match them to native Instruments IDs."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time

WINDOWS = r'''
#include <windows.h>
#include <tlhelp32.h>
#include <winternl.h>
#include <stdio.h>
typedef NTSTATUS (WINAPI *QueryThread)(HANDLE, ULONG, PVOID, ULONG, PULONG);
typedef struct { NTSTATUS status; PVOID teb; CLIENT_ID client; ULONG_PTR affinity; LONG priority; LONG base; } Basic;
static void print_name(PCWSTR name) {
  putchar('"');
  if(name) for(unsigned i=0;name[i] && i<63;i++) {
    unsigned c=name[i];
    if(c=='"' || c=='\\') printf("\\%c",c);
    else if(c>=32 && c<127) putchar(c);
    else printf("\\u%04x",c);
  }
  putchar('"');
}
int main() {
  DWORD pid=0; unsigned matches=0;
  HANDLE snap=CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS,0);
  PROCESSENTRY32 p={0}; p.dwSize=sizeof(p);
  if (Process32First(snap,&p)) do {
    if (!_stricmp(p.szExeFile,"WizardGraphicalClient.exe")) {pid=p.th32ProcessID; matches++;}
  } while(Process32Next(snap,&p));
  CloseHandle(snap);
  if(matches!=1) return 2;
  HANDLE process=OpenProcess(PROCESS_QUERY_INFORMATION|PROCESS_VM_READ,FALSE,pid);
  if(!process) return 3;
  QueryThread query=(QueryThread)GetProcAddress(GetModuleHandleA("ntdll.dll"),"NtQueryInformationThread");
  snap=CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD,0);
  THREADENTRY32 t={0}; t.dwSize=sizeof(t); int comma=0;
  printf("{\"windows_pid\":%lu,\"threads\":[",pid);
  if(Thread32First(snap,&t)) do {
    if(t.th32OwnerProcessID!=pid) continue;
    HANDLE thread=OpenThread(THREAD_QUERY_INFORMATION,FALSE,t.th32ThreadID);
    Basic b={0}; unsigned long long pthread=0,pthread_teb=0,teb_tid=0; SIZE_T n=0,tsd_bytes=0,tid_bytes=0;
    if(thread && query && !query(thread,0,&b,sizeof(b),NULL)) {
      // Wine 11 x86-64 ntdll_thread_data.pthread_id in TEB.GdiTebBatch.
      ReadProcessMemory(process,(char*)b.teb+0x3a0,&pthread,sizeof(pthread),&n);
      // Wine 11 signal_x86_64.c asserts this offset. It stores the exact
      // THREAD_IDENTIFIER_INFO.thread_handle, including the initial Wine thread.
      ReadProcessMemory(process,(char*)b.teb+0x320,&pthread_teb,sizeof(pthread_teb),&tsd_bytes);
      ReadProcessMemory(process,(char*)b.teb+0x48,&teb_tid,sizeof(teb_tid),&tid_bytes);
      if(n==sizeof(pthread)) {
        PWSTR name=NULL; GetThreadDescription(thread,&name);
        printf("%s{\"windows_tid\":%llu,\"server_tid\":%lu,\"pthread_handle\":%llu,\"pthread_tsd_handle\":%llu,\"thread_name\":",comma?",":"",tid_bytes==sizeof(teb_tid)&&teb_tid?teb_tid:(unsigned long long)t.th32ThreadID,t.th32ThreadID,pthread,tsd_bytes==sizeof(pthread_teb)?pthread_teb:0);
        print_name(name);printf("}");if(name)LocalFree(name);comma=1;
      }
    }
    if(thread) CloseHandle(thread);
  } while(Thread32Next(snap,&t));
  printf("]}\n"); CloseHandle(snap); CloseHandle(process); return 0;
}
'''

NATIVE = r'''
#include <mach/mach.h>
#include <libproc.h>
#include <sys/proc_info.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <pthread.h>
static uint64_t pthread_offset(void) {
  uint64_t ids[32],handles[32],after[32],self=0;
  pthread_threadid_np(NULL,&self);
  int a=proc_pidinfo(getpid(),PROC_PIDLISTTHREADS,0,handles,sizeof(handles));
  int b=proc_pidinfo(getpid(),28,0,ids,sizeof(ids));
  int c=proc_pidinfo(getpid(),PROC_PIDLISTTHREADS,0,after,sizeof(after));
  if(a<=0 || a!=b || b!=c || a>=sizeof(ids) || memcmp(handles,after,a)) return UINT64_MAX;
  for(unsigned i=0;i<a/sizeof(*ids);i++) if(ids[i]==self) {
    uint64_t pointer=(uint64_t)pthread_self();
    if(handles[i]>=pointer && handles[i]-pointer<=1024) return handles[i]-pointer;
  }
  return UINT64_MAX;
}
static void print_name(const char *name) {
  putchar('"');
  for(unsigned i=0;name[i] && i<63;i++) {
    unsigned char c=name[i];
    if(c=='"' || c=='\\') printf("\\%c",c);
    else if(c>=32 && c<127) putchar(c);
    else printf("\\u%04x",c);
  }
  putchar('"');
}
int main(int argc,char **argv) {
  if(argc!=2) return 2;
  int self_test=!strcmp(argv[1],"--self");
  int pid=self_test?getpid():atoi(argv[1]);
  // cthread_self addresses the pthread TSD area, not pthread_t itself.
  // Measure its offset using independent APIs in this x86-64 helper.
  uint64_t offset=pthread_offset();
  task_t task=MACH_PORT_NULL;
  kern_return_t kr=self_test?KERN_FAILURE:task_for_pid(mach_task_self(),pid,&task);
  if(kr!=KERN_SUCCESS) {
    uint64_t ids[4096],handles[4096],after[4096];
    // XNU proc_info_private.h: PROC_PIDLISTTHREADIDS=28 returns kernel IDs;
    // the public PROC_PIDLISTTHREADS returns pthread handles instead.
    // fill_taskthreadlist uses the same queue order for both flavors. Match
    // positions only when bracketing handle lists are identical and complete.
    int first=proc_pidinfo(pid,PROC_PIDLISTTHREADS,0,handles,sizeof(handles));
    int bytes=proc_pidinfo(pid,28,0,ids,sizeof(ids));
    int last=proc_pidinfo(pid,PROC_PIDLISTTHREADS,0,after,sizeof(after));
    if(bytes<=0) return 3;
    int stable=first==bytes && last==bytes && bytes<sizeof(ids) && !memcmp(handles,after,bytes);
    uint64_t self_id=0; pthread_threadid_np(NULL,&self_id);
    printf("{\"inspection\":\"libproc_snapshot\",\"stable_handles\":%s,\"self_tid\":%llu,\"self_handle\":%llu,\"threads\":[",stable?"true":"false",(unsigned long long)self_id,(unsigned long long)pthread_self());int comma=0;
    for(unsigned i=0;i<bytes/sizeof(*ids);i++) {
      struct proc_threadinfo info;
      if(proc_pidinfo(pid,PROC_PIDTHREADID64INFO,ids[i],&info,sizeof(info))!=sizeof(info)) continue;
      uint64_t pointer=(stable && offset!=UINT64_MAX && handles[i]>=offset)?handles[i]-offset:0;
      printf("%s{\"native_tid\":%llu,\"pthread_handle\":%llu,\"pthread_tsd_handle\":%llu,\"thread_name\":",comma?",":"",(unsigned long long)ids[i],(unsigned long long)pointer,(unsigned long long)(stable?handles[i]:0));
      print_name(info.pth_name);printf("}");comma=1;
    }
    printf("]}\n");return 0;
  }
  thread_act_array_t threads; mach_msg_type_number_t count;
  if(task_threads(task,&threads,&count)!=KERN_SUCCESS) return 4;
  printf("{\"threads\":["); int comma=0;
  for(unsigned i=0;i<count;i++) {
    thread_identifier_info_data_t id; mach_msg_type_number_t n=THREAD_IDENTIFIER_INFO_COUNT;
    if(thread_info(threads[i],THREAD_IDENTIFIER_INFO,(thread_info_t)&id,&n)==KERN_SUCCESS) {
      thread_extended_info_data_t info={0};mach_msg_type_number_t m=THREAD_EXTENDED_INFO_COUNT;
      thread_info(threads[i],THREAD_EXTENDED_INFO,(thread_info_t)&info,&m);
      uint64_t pointer=(offset!=UINT64_MAX && id.thread_handle>=offset)?id.thread_handle-offset:0;
      printf("%s{\"native_tid\":%llu,\"pthread_handle\":%llu,\"pthread_tsd_handle\":%llu,\"thread_name\":",comma?",":"",(unsigned long long)id.thread_id,(unsigned long long)pointer,(unsigned long long)id.thread_handle);
      print_name(info.pth_name);printf("}");comma=1;
    }
    mach_port_deallocate(mach_task_self(),threads[i]);
  }
  printf("]}\n");vm_deallocate(mach_task_self(),(vm_address_t)threads,count*sizeof(thread_t));
  mach_port_deallocate(mach_task_self(),task);return 0;
}
'''

def build(work):
    work=Path(work); work.mkdir(parents=True,exist_ok=True)
    (work/'windows.c').write_text(WINDOWS); (work/'native.c').write_text(NATIVE)
    subprocess.run(['x86_64-w64-mingw32-gcc','-O2','-static',str(work/'windows.c'),'-o',str(work/'threads.exe')],check=True)
    subprocess.run(['clang','-arch','x86_64','-O2',str(work/'native.c'),'-o',str(work/'native-threads')],check=True)
    return work

def join_threads(windows, native):
    """Join exact handles; conflicting or duplicate identities remain unknown."""
    mappings, unmapped = [], []
    inspection = native.get('inspection', 'mach_identifier')
    for thread in windows['threads']:
        pthread = thread.get('pthread_handle', 0)
        tsd = thread.get('pthread_tsd_handle', 0)
        matches = [t for t in native['threads'] if pthread and t.get('pthread_handle') == pthread]
        tsd_matches = [t for t in native['threads'] if tsd and t.get('pthread_tsd_handle') == tsd]
        method = 'pthread_handle_' + inspection
        if tsd:
            if pthread:
                if len(matches) != 1 or len(tsd_matches) != 1 or matches[0]['native_tid'] != tsd_matches[0]['native_tid']:
                    matches = []
            else:
                matches = tsd_matches
                method = 'wine_pthread_tsd_handle_' + inspection
        if len(matches) == 1:
            mappings.append({**thread, 'native_tid': matches[0]['native_tid'], 'method': method})
        else:
            unmapped.append(thread)
    # A snapshot with reused handles must not attribute two Windows threads to
    # one native thread, even if each individual join had only one match.
    counts = {}
    for item in mappings:
        counts[item['native_tid']] = counts.get(item['native_tid'], 0) + 1
    duplicates = [item for item in mappings if counts[item['native_tid']] != 1]
    unmapped.extend({k: v for k, v in item.items() if k not in ('native_tid', 'method')} for item in duplicates)
    return [item for item in mappings if counts[item['native_tid']] == 1], unmapped

def capture(app,data,pid,work,output):
    app=Path(app).resolve(); data=Path(data).resolve(); work=Path(work).resolve()
    runtime=app/'Contents/Resources/Runtime'
    # Process names only: game arguments can contain session credentials.
    name=subprocess.check_output(['ps','-p',str(pid),'-o','comm='],text=True).strip().replace('\\','/').rsplit('/',1)[-1]
    if name.lower()!='wizardgraphicalclient.exe': raise RuntimeError('Target must be the active game.')
    env=dict(os.environ,WINEPREFIX=str(data/'Prefix'),WINEARCH='win64',WINEDEBUG='-all',WINEMSYNC='1',
             WINEDLLPATH=str(runtime/'lib/wine'),DYLD_FALLBACK_LIBRARY_PATH=str(runtime/'lib')+':/usr/lib')
    version=subprocess.check_output([str(runtime/'bin/wine'),'--version'],env=env,text=True).strip()
    if version!='wine-11.0': raise RuntimeError('The TEB offset is verified only for this Wine 11.0 build.')
    before=time.time_ns()//1000
    windows=subprocess.run([str(runtime/'bin/wine'),str(work/'threads.exe')],env=env,capture_output=True,text=True,timeout=15)
    native=subprocess.run([str(work/'native-threads'),str(pid)],capture_output=True,text=True,timeout=15)
    result={'target_pid':pid,'wine_version':version,'unix_bounds_us':[before,time.time_ns()//1000],
            'method':'Exact pthread or Wine-recorded pthread TSD handles only. Independent matches must agree. Names and list position never establish identity.',
            'mappings':[],'completed':False}
    if windows.returncode==0 and native.returncode==0:
        win=json.loads(windows.stdout); mac=json.loads(native.stdout)
        result['mappings'], result['unmapped_windows_threads'] = join_threads(win, mac)
        result['windows_pid']=win['windows_pid']; result['completed']=bool(result['mappings'])
    else:
        result['error']='Native or Wine thread inspection unavailable; no identity inferred.'
        result['returncodes']=[windows.returncode,native.returncode]
    Path(output).write_text(json.dumps(result,indent=2)+'\n')
    print('Matched native thread IDs:',len(result['mappings']))
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--work',type=Path,required=True); p.add_argument('--build-only',action='store_true')
    p.add_argument('--app',type=Path); p.add_argument('--data',type=Path); p.add_argument('--pid',type=int); p.add_argument('--output',type=Path)
    a=p.parse_args(); build(a.work)
    if not a.build_only:
        if any(v is None for v in (a.app,a.data,a.pid,a.output)):p.error('Pass --app, --data, --pid and --output to inspect a live game.')
        capture(a.app,a.data,a.pid,a.work,a.output)
