#!/usr/bin/env python3
"""Classify annotated >50-ms hitches only with explicit blocking-thread evidence."""
import argparse
import json
from pathlib import Path
from profile_report import report

CAUSES={'compilation','asset_loading','resource_retry','game_processing','gpu_execution'}

def diagnose(manifest, root):
    findings=[]; recurring={}; traces={}
    for key,value in manifest.get('traces',{}).items():
        metadata=json.loads((root/value).read_text())
        trace=(root/value).with_suffix('.trace')
        if (metadata.get('completed') is True and metadata.get('scored') is False
            and metadata.get('usable_for_movement_diagnosis') is True
            and metadata.get('synthetic_only') is not True and trace.exists()): traces[key]=metadata
    for sample in manifest.get('windows',[]):
        capture=report(root/sample['capture'],sample['start_us'],sample['end_us'])
        for hitch in capture['hitches_over_50ms']:
            classification='inconclusive'; evidence=None
            for item in sample.get('evidence',[]):
                if item.get('hitch_start_us')!=hitch['start_us']: continue
                # Thread identity mapping and actual stacks/timeline must be
                # supplied from Instruments, never inferred from event overlap.
                complete = (capture['capture_finalized'] and capture['dropped_presentations']==0 and bool(capture['clock_sync']))
                if (complete and item.get('cause') in CAUSES and item.get('cpu_trace') in traces and item.get('gpu_trace') in traces
                    and traces[item['cpu_trace']]['kind']=='cpu' and traces[item['gpu_trace']]['kind']=='gpu'
                    and Path(traces[item['cpu_trace']]['capture']).resolve() == (root/sample['capture']).resolve()
                    and item.get('blocking_thread') and item.get('native_thread_mapping') and item.get('cpu_stack')
                    and item.get('gpu_observation') and item.get('trace_time_range') and item.get('activity')=='movement'):
                    classification=item['cause']; evidence=item; break
            finding={'capture':sample['capture'],'activity':sample.get('activity','unannotated'),**hitch,
                     'classification':classification,'blocking_evidence':evidence}
            if finding['activity']!='movement': finding['classification']='excluded_activity'
            findings.append(finding)
            if classification=='compilation' and evidence and evidence.get('missing_pipeline_coverage') is True:
                pipeline=evidence.get('pipeline_id')
                matched=any(e.get('pipeline_id')==pipeline and 'pipeline' in e['event'] for e in hitch['overlapping_cpu_events'])
                if pipeline and matched and capture['dropped_by_category'] is not None and capture['dropped_by_category'].get('pipeline')==0:
                    recurring.setdefault(pipeline,set()).add(sample['capture'])
    causes={f['classification'] for f in findings}
    other=bool(causes & {'asset_loading','resource_retry','game_processing','gpu_execution'})
    expand=not other and any(len(v)>1 for v in recurring.values())
    return {'hitches':findings,'expand_preparation_supported':expand,'stop_further_warmup':other,
            'next_action':('Propose a separate targeted fix for the proven cause.' if other else
                           'Review recurring missing pipeline coverage before expanding preparation.' if expand else
                           'Collect blocking-thread CPU/GPU evidence; no warm-up expansion justified.'),
            'limits':'Separate CPU/GPU sessions corroborate repeatable route behavior. They do not sample the same frame. Overlap remains inconclusive.'}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('manifest',type=Path); a=p.parse_args()
    print(json.dumps(diagnose(json.loads(a.manifest.read_text()),a.manifest.parent),indent=2))
