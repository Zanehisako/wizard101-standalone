#!/usr/bin/env python3
"""Align workload evidence and report correlations without assigning causes."""
import argparse
from bisect import bisect_right
from collections import defaultdict
import json
from pathlib import Path
from profile_report import report

def jsonlines(path):
    rows=[]
    if not Path(path).exists(): return rows,False
    complete=True
    with Path(path).open() as stream:
        for line in stream:
            try: rows.append(json.loads(line))
            except json.JSONDecodeError: complete=False
    return rows,complete

class ClockMap:
    """Interpolate local anchors; exclude discontinuities instead of global drift."""
    def __init__(self, rows, x, y):
        self.points=sorted((r[x],r[y]) for r in rows)
        self.xs=[a for a,b in self.points]
        self.bad=[]; self.local_variation=0
        for i,((a,b),(c,d)) in enumerate(zip(self.points,self.points[1:])):
            variation=abs((d-b)-(c-a))
            if c<=a or d<=b or variation>2000: self.bad.append(i)
            else: self.local_variation=max(self.local_variation,variation)
    @property
    def usable(self): return bool(self.points) and (len(self.points)==1 or len(self.bad)<len(self.points)-1)
    def value(self, x, unchecked=False):
        if not self.points: return None
        if len(self.points)==1: return self.points[0][1]+x-self.points[0][0]
        i=max(0,min(len(self.points)-2,bisect_right(self.xs,x)-1))
        if i in self.bad and not unchecked: return None
        a,b=self.points[i];c,d=self.points[i+1]
        return b+(x-a)*(d-b)/(c-a) if c>a else None
    def interval_valid(self,a,b):
        return not any(a<self.points[i+1][0] and b>self.points[i][0] for i in self.bad)

def union_us(intervals):
    total=0; left=right=None
    for a,b in sorted(intervals):
        if b<=a: continue
        if right is None or a>right:
            if right is not None: total+=right-left
            left,right=a,b
        else: right=max(right,b)
    return total+(right-left if right is not None else 0)

def summarize(capture,start_us=0,end_us=None):
    capture=Path(capture).resolve(); timing=report(capture,start_us,end_us)
    native,parsed=jsonlines(capture.parent/'native.jsonl')
    identities,identityParsed=jsonlines(capture.parent/'threads.jsonl')
    lockRows,locksParsed=jsonlines(capture.parent/'locks.jsonl')
    lockFooter=next((r for r in reversed(lockRows) if r.get('type')=='footer'),None)
    clocks=[r for r in native if r['type']=='clock']; footer=next((r for r in reversed(native) if r['type']=='footer'),None)
    pids={r['pid'] for r in clocks}; pid=next(iter(pids)) if len(pids)==1 else None
    mappings=defaultdict(set); initial=set()
    for r in identities:
        if r.get('pid')==pid:
            mappings[r['windows_tid']].add(r['native_tid'])
            if r['initial']: initial.add((r['windows_tid'],r['native_tid']))
    mapping={k:next(iter(v)) for k,v in mappings.items() if len(v)==1}
    initialVerified=identityParsed and len(initial)==1 and all(mapping.get(w)==n for w,n in initial)
    nativeClock=ClockMap(clocks,'mach_us','unix_us')
    rendererClock=ClockMap(timing['clock_sync'],'unix_us','relative_us')
    def relative(mach,unchecked=False):
        unix=nativeClock.value(mach,unchecked)
        return rendererClock.value(unix,unchecked) if unix is not None else None
    def valid_interval(a,b):
        x,y=nativeClock.value(a),nativeClock.value(b)
        return x is not None and y is not None and nativeClock.interval_valid(a,b) and rendererClock.interval_valid(x,y)
    alignment=nativeClock.usable and rendererClock.usable
    drift=None
    if len(clocks)>1:
        drift=max(c['unix_us']-c['mach_us'] for c in clocks)-min(c['unix_us']-c['mach_us'] for c in clocks)
    uncertainty=max((r['uncertainty_us'] for r in clocks),default=0)+max((r['uncertainty_us'] for r in timing['clock_sync']),default=0)+nativeClock.local_variation+rendererClock.local_variation
    alignment=alignment and uncertainty<=2000
    nativeTimes=[r[k] for r in native for k in ('mach_us','start_mach_us','end_mach_us') if isinstance(r.get(k),int)]
    mappedTimes=[relative(t) for t in nativeTimes] if alignment else []
    mappedTimes=[t for t in mappedTimes if t is not None]
    nativeBounds=[min(mappedTimes),max(mappedTimes)] if mappedTimes else None
    holes=[]
    for i in nativeClock.bad:
        boundaries=[relative(nativeClock.points[i][0],True),relative(nativeClock.points[i+1][0],True)]
        if all(t is not None for t in boundaries): holes.append(sorted(boundaries))
    for i in rendererClock.bad:
        holes.append(sorted([rendererClock.points[i][1],rendererClock.points[i+1][1]]))
    def covered(a,b): return bool(nativeBounds and a>=nativeBounds[0] and b<=nativeBounds[1] and not any(a<y and b>x for x,y in holes))
    coversWindow=end_us is not None and covered(start_us,end_us)
    samples=defaultdict(list); memory=[]; gpu=[]; locks=[]
    if alignment:
        for r in native:
            if r['type']=='thread_cpu' and relative(r['mach_us']) is not None: samples[r['native_tid']].append({**r,'relative_us':relative(r['mach_us'])})
            elif r['type']=='memory' and relative(r['mach_us']) is not None: memory.append({**r,'relative_us':relative(r['mach_us'])})
            elif r['type']=='gpu' and r['status']==4:
                a,b=relative(r['start_mach_us']),relative(r['end_mach_us'])
                if a is not None and b is not None and valid_interval(r['start_mach_us'],r['end_mach_us']) and b>=start_us and (end_us is None or a<=end_us): gpu.append({**r,'start_us':a,'end_us':b})
        for r in lockRows:
            if r.get('type')!='lock_contention' or r.get('pid')!=pid: continue
            a,b=relative(r['start_mach_us']),relative(r['end_mach_us'])
            if a is None or b is None or b<a or not valid_interval(r['start_mach_us'],r['end_mach_us']) or b<start_us or (end_us is not None and a>end_us): continue
            verified=identityParsed and mapping.get(r['windows_tid'])==r['native_tid']
            owner=mapping.get(r['owner_windows_tid_at_wait']) if identityParsed else None
            locks.append({**r,'start_us':a,'end_us':b,'thread_identity_verified':verified,
                'thread_role':'initial_game_thread' if verified and initialVerified and (r['windows_tid'],r['native_tid']) in initial else 'unidentified',
                'owner_native_tid_at_wait':owner,'owner_identity_verified':owner is not None})
    cpu={}
    for tid,values in samples.items():
        values.sort(key=lambda r:r['relative_us']); used=[]
        for a,b in zip(values,values[1:]):
            dt=b['relative_us']-a['relative_us']; dc=b['cpu_us']-a['cpu_us']
            if valid_interval(a['mach_us'],b['mach_us']) and a['relative_us']>=start_us and (end_us is None or b['relative_us']<=end_us) and 0<dt<=750000 and 0<=dc<=dt+10000:
                used.append((dt,dc))
        seconds=sum(t for t,c in used)/1e6
        cpu[tid]={'cpu_ms':sum(c for t,c in used)/1000,'coverage_seconds':seconds,
            'cpu_ms_per_second':sum(c for t,c in used)/1000/seconds if seconds else None,
            'windows_tids':[w for w,n in mapping.items() if n==tid],
            'role':'initial_game_thread' if initialVerified and any(n==tid for w,n in initial) else 'unidentified'}
    def counter_deltas(values,key='relative_us'):
        inside=[r for r in values if r[key]>=start_us and (end_us is None or r[key]<=end_us)]
        if len(inside)<2: return {'coverage_seconds':0,'deltas':{}}
        a,b=inside[0],inside[-1]
        numeric={k:b[k]-a[k] for k in a if k!=key and k in b and isinstance(a[k],int) and not isinstance(a[k],bool) and b[k]>=a[k]}
        return {'coverage_seconds':(b[key]-a[key])/1e6,'deltas':numeric}
    counters=[]
    for line in capture.read_text().splitlines():
        if line.startswith('# workload_sample='): counters.append(json.loads(line.split('=',1)[1]))
    intervals=[(max(start_us,r['start_us']),min(end_us,r['end_us']) if end_us is not None else r['end_us']) for r in gpu]
    hitches=[]
    for h in timing['hitches_over_50ms']:
        a,b=h['start_us'],h['end_us']; work=[r for r in gpu if r['start_us']<b and r['end_us']>a]
        windowCovered=covered(a,b)
        blocking=[r for r in locks if r['thread_role']=='initial_game_thread' and r['start_us']<b and r['end_us']>a]
        hitches.append({**h,'classification':'inconclusive','native_window_covered':windowCovered,'gpu_execution_union_ms':union_us([(max(a,r['start_us']),min(b,r['end_us'])) for r in work])/1000 if windowCovered else None,
            'initial_thread_contention_union_ms':union_us([(max(a,r['start_us']),min(b,r['end_us'])) for r in blocking])/1000 if windowCovered else None,
            'initial_thread_contentions_overlapping':len(blocking),
            'gpu_buffers_overlapping':len(work),'sampling_limit':'250 ms CPU/memory snapshots do not resolve individual short stalls; use a separate CPU trace.'})
    lockComplete=bool(lockRows and locksParsed and lockFooter is not None and lockFooter.get('dropped',1)==0)
    clean=timing['capture_finalized'] and timing['dropped_events']==0 and footer is not None and footer['dropped_gpu']==0 and footer['invalid_timestamps']==0 and footer['outstanding_gpu']==0 and parsed
    clean=clean and (not (capture.parent/'locks.jsonl').exists() or lockComplete)
    return {'capture':str(capture),'window_us':[start_us,end_us],'timing':timing,'aligned':alignment,'clock_uncertainty_us':uncertainty,
        'wall_clock_offset_drift_us':drift,'clock_alignment_method':'piecewise local anchors; discontinuous intervals excluded','clock_discontinuities_us':holes,'native_capture_finalized':footer is not None,'native_footer':footer,
        'identity_log_valid':identityParsed,'verified_thread_mapping':mapping,'initial_thread_verified':initialVerified,
        'initial_thread':list(initial)[0] if initialVerified else None,'thread_cpu':cpu,'workload_counters':counter_deltas(counters),
        'memory_activity':counter_deltas([r for r in memory if r['rusage_valid'] and r['host_vm_valid']]),
        'memory_samples_in_window':[r for r in memory if r['relative_us']>=start_us and (end_us is None or r['relative_us']<=end_us)],
        'gpu_execution_union_ms':union_us(intervals)/1000,'gpu_buffers':len(gpu),'hitches':hitches,
        'lock_contentions':locks,'lock_recording':{'present':bool(lockRows),'parsed':locksParsed,'footer':lockFooter,
            'complete':lockComplete},
        'native_recording_bounds_us':nativeBounds,'native_covers_requested_window':coversWindow,
        'evidence_complete':bool(clean and alignment and initialVerified and ((end_us is None and not holes) or coversWindow)),
        'cause':'unidentified','limitations':'Correlation only. Draw counts are API requests, not pixels/shading cost. GPU intervals cover command buffers, not individual draws. Host paging includes other processes. Unmapped threads and unresolved stacks remain unidentified.'}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('capture',type=Path);p.add_argument('--start-us',type=int,default=0);p.add_argument('--end-us',type=int);p.add_argument('--output',type=Path)
    a=p.parse_args(); result=summarize(a.capture,a.start_us,a.end_us); text=json.dumps(result,indent=2)+'\n'
    if a.output: a.output.write_text(text)
    else: print(text,end='')
