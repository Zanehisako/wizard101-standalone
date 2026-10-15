#!/usr/bin/env python3
"""Annotate a live activity window using the synchronized renderer clock."""
import argparse
import json
from pathlib import Path
import time

def latest_sync(capture):
    # Read recent clock markers without parsing a growing gameplay CSV.
    with Path(capture).open('rb') as source:
        source.seek(0,2); end=source.tell()
        for size in (65536,262144,1048576,4194304):
            begin=max(0,end-size); source.seek(begin); data=source.read(end-begin)
            lines=data.splitlines()
            if begin: lines=lines[1:]
            for line in reversed(lines):
                if line.startswith(b'# clock_sync='):
                    try: return json.loads(line.split(b'=',1)[1])
                    except json.JSONDecodeError: continue
    raise RuntimeError('Synchronized renderer capture is required.')

def relative_us(capture):
    sync=latest_sync(capture); wall=time.time_ns()//1000
    if abs(wall-sync['unix_us'])>2_000_000: raise RuntimeError('Capture clock is stale or the game stopped recording.')
    return sync['relative_us']+wall-sync['unix_us'],sync['uncertainty_us']

def annotate(capture,activity,phase,zone,seconds,crowd=None,settled_seconds=None):
    capture=Path(capture).resolve(); session=json.loads((capture.parent/'session.json').read_text())
    if crowd and (zone.lower()!='commons' or activity not in ('stationary','movement') or settled_seconds is None or settled_seconds<60):
        raise RuntimeError('Crowd windows require Commons, stationary/movement, and at least 60 seconds of settling.')
    start,uncertainty=relative_us(capture)
    print(f'{activity}: {zone} / {phase}, {seconds:g} seconds. Begin now.',flush=True)
    time.sleep(seconds)
    end,last_uncertainty=relative_us(capture)
    window={'capture':str(capture),'start_us':start,'end_us':end,'activity':activity,'phase':phase,'zone':zone,
            'clock_uncertainty_us':max(uncertainty,last_uncertainty),
            **{k:session.get(k) for k in ('route','settings_sha256','starting_cache_sha256','seed_sha256','starting_inputs_sha256')}}
    if crowd: window.update(crowd=crowd,settled_seconds=settled_seconds)
    path=capture.parent/'windows.json'; windows=json.loads(path.read_text()) if path.exists() else []
    windows.append(window); path.write_text(json.dumps(windows,indent=2)+'\n')
    print('Window saved:',path,flush=True)
    return window

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('capture',type=Path)
    p.add_argument('--activity',choices=('stationary','movement','portal','loading','menu','shutdown'),required=True)
    p.add_argument('--phase',choices=('first_arrival','immediate_revisit','after_restart','persistence','diagnostic'),required=True)
    p.add_argument('--crowd',choices=('quiet','crowded')); p.add_argument('--settled-seconds',type=float)
    p.add_argument('--zone',required=True); p.add_argument('--seconds',type=float,default=30)
    a=p.parse_args()
    if not 0<a.seconds<=60: p.error('Use an activity window between 0 and 60 seconds.')
    annotate(a.capture,a.activity,a.phase,a.zone,a.seconds,a.crowd,a.settled_seconds)
