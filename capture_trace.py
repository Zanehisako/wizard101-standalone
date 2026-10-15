#!/usr/bin/env python3
"""Record one 30-second diagnostic CPU or GPU trace alongside renderer events."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import shutil
import time
import xml.etree.ElementTree as ET
from profile_report import report

TEMPLATES={'cpu':'Time Profiler','gpu':'Metal System Trace'}

def require_space(kind, output, thread_states=False):
    parent=Path(output).resolve().parent
    while not parent.exists(): parent=parent.parent
    free=shutil.disk_usage(parent).free
    # A live 30-second Metal recording produced 4.1 GiB of raw data, and
    # Instruments copied it into the bundle during finalization. Allow both
    # copies, intermediate tables and operating-system headroom.
    required=(16*1024**3 if kind=='gpu' or thread_states else 256*1024**2)
    if free<required:
        raise RuntimeError(f'{TEMPLATES[kind]} needs {required/1024**3:g} GiB free before recording; '
                           f'currently {free/1024**3:.2f} GiB. No recording started.')

def clock():
    before=time.monotonic_ns(); wall=time.time_ns(); after=time.monotonic_ns()
    return {'unix_us':wall//1000,'monotonic_ns':(before+after)//2,'uncertainty_us':(after-before+999)//1000}

def record(kind, pid, capture, output, thread_states=False):
    output=Path(output).resolve(); capture=Path(capture).resolve()
    if output.suffix != '.trace': raise RuntimeError('Use a new output path ending in .trace.')
    session=json.loads((capture.parent/'session.json').read_text())
    if session.get('comparison_label') != 'trace-'+kind or session.get('heavyweight_trace') is not True:
        raise RuntimeError('Launch a separate trace-'+kind+' diagnostic session; tracing cannot share scored sessions.')
    require_space(kind,output,thread_states)
    if time.time()-capture.stat().st_mtime>3 or report(capture)['capture_finalized']:
        raise RuntimeError('Renderer event capture ended or is stale. Exit normally and launch a fresh diagnostic session.')
    # Validate PID without exposing launch arguments or session keys.
    name=subprocess.check_output(['ps','-p',str(pid),'-o','comm='],text=True).strip().lower().replace('\\','/').rsplit('/',1)[-1]
    if name!='wizardgraphicalclient.exe': raise RuntimeError('PID must be the active WizardGraphicalClient.exe process.')
    if not capture.is_file(): raise RuntimeError('Game timing capture has not started.')
    if output.exists() or output.with_suffix('.json').exists(): raise RuntimeError('Choose a new trace output path.')
    output.parent.mkdir(parents=True,exist_ok=True)
    command=['xcrun','xctrace','record','--template',TEMPLATES[kind],'--attach',str(pid),'--time-limit','30s','--output',str(output),'--no-prompt']
    if thread_states: command.extend(['--instrument','Thread State Trace'])
    metadata={'kind':kind,'template':TEMPLATES[kind],'target_pid':pid,'capture':str(capture),'scored':False,
              'requested_duration_seconds':30,'clock_before':clock(),'completed':False}
    if thread_states: metadata['additional_instruments']=['Thread State Trace']
    # Preserve the start clock and target even if Instruments fills the disk.
    metadata_path=output.with_suffix('.json')
    metadata_path.write_text(json.dumps(metadata,indent=2)+'\n')
    print('Recording '+TEMPLATES[kind]+': move through the annotated route for 30 seconds.',flush=True)
    with output.with_suffix('.log').open('w') as log:
        try:
            # Metal System Trace may need substantial time to finalize a large
            # recording after its 30-second sampling window has ended.
            result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=600 if kind=='gpu' or thread_states else 120)
            returncode=result.returncode
        except subprocess.TimeoutExpired:
            returncode=None
            metadata['error']='xctrace exceeded the recording/finalization deadline'
    metadata.update(clock_after=clock(),returncode=returncode)
    if returncode==0 and output.exists():
        toc=subprocess.run(['xcrun','xctrace','export','--input',str(output),'--toc'],capture_output=True,text=True,timeout=30)
        if toc.returncode == 0:
            tree=ET.fromstring(toc.stdout)
            # Instruments exports inherited environment metadata. Keep the
            # local TOC limited to the trace run and data schemas.
            for parent in tree.iter():
                for child in list(parent):
                    if child.tag=='environment': parent.remove(child)
            output.with_suffix('.toc.xml').write_text(ET.tostring(tree,encoding='unicode'))
            metadata['completed']=tree.find('run') is not None
            summary=tree.find('run/info/summary')
            if summary is not None:
                try:
                    metadata['trace_unix_bounds_us']=[int(datetime.fromisoformat(summary.findtext(key)).timestamp()*1_000_000)
                                                     for key in ('start-date','end-date')]
                except (TypeError,ValueError):
                    pass
    timing=report(capture)
    metadata['game_clock_sync']=timing['clock_sync']
    if timing['clock_sync']:
        def relative(unix_us):
            sync=min(timing['clock_sync'],key=lambda s:abs(s['unix_us']-unix_us))
            return sync['relative_us']+unix_us-sync['unix_us']
        unix_bounds=metadata.get('trace_unix_bounds_us',[metadata[key]['unix_us'] for key in ('clock_before','clock_after')])
        bounds=[relative(value) for value in unix_bounds]
        window=report(capture,*bounds)
        metadata['game_recording_bounds_us']=bounds
        metadata['presentations_during_recording_bounds']=window['presentations']
        metadata['usable_for_movement_diagnosis']=metadata['completed'] and window['presentations']>0
    else:
        metadata['usable_for_movement_diagnosis']=False
    metadata['alignment']='Match Unix microseconds using clock_sync brackets and trace run start; Windows thread IDs require native stack/thread evidence.'
    temporary_metadata=metadata_path.with_suffix('.json.tmp')
    temporary_metadata.write_text(json.dumps(metadata,indent=2)+'\n')
    temporary_metadata.replace(metadata_path)
    if not metadata['completed']: raise RuntimeError('Trace incomplete; inspect '+str(output.with_suffix('.log')))
    if not metadata['usable_for_movement_diagnosis']:
        print('Trace saved without rendered-frame coverage; movement diagnosis remains unverified.',flush=True)
    print(output,flush=True)
    return metadata

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('kind',choices=TEMPLATES)
    p.add_argument('--pid',type=int,required=True); p.add_argument('--capture',type=Path,required=True); p.add_argument('--output',type=Path,required=True)
    p.add_argument('--thread-states',action='store_true',help='Add heavyweight CPU thread-state tracing (requires 16 GiB free).')
    a=p.parse_args()
    if a.thread_states and a.kind!='cpu': p.error('--thread-states is a CPU diagnostic option.')
    record(a.kind,a.pid,a.capture,a.output,a.thread_states)
