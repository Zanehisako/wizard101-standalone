#!/usr/bin/env python3
"""Summarize CPU renderer events overlapping long presentation intervals."""
import csv
import json
import math
from collections import defaultdict
import sys
from pathlib import Path

def report(path, start_us=0, end_us=None, *, windows=None):
    ranges = windows if windows is not None else [{'start_us': start_us, 'end_us': end_us}]
    if windows is not None:
        if not ranges: raise ValueError('At least one activity window is required')
        ranges = sorted(ranges, key=lambda w: w['start_us'])
        for index, window in enumerate(ranges):
            if window['end_us'] <= window['start_us']:
                raise ValueError('Activity windows must have positive length')
            if index and ranges[index-1]['end_us'] >= window['start_us']:
                raise ValueError('Activity windows must be disjoint')
        start_us=ranges[0]['start_us']; end_us=ranges[-1]['end_us']
    lines = Path(path).read_text().splitlines()
    footer, metadata, aggregates, losses, syncs = {}, {}, {}, {}, []
    cpu_samples, cpu_counters = [], []
    for line in lines:
        if line.startswith('# ') and '=' in line:
            name, value = line[2:].split('=', 1)
            if name in ('dropped_events', 'dropped_presentations', 'filtered_short_events', 'filtered_short_file_reads'):
                footer[name] = int(value)
            elif name == 'clock_sync':
                syncs.append(json.loads(value))
            elif name == 'process_cpu_sample':
                cpu_samples.append(json.loads(value))
            elif name == 'cpu_counters':
                cpu_counters.append(json.loads(value))
            elif name.startswith('aggregate_'):
                aggregates[name[10:]] = json.loads(value)
            elif name.startswith('dropped_category_'):
                losses[name[17:]] = int(value)
            else:
                metadata[name] = value
    rows = list(csv.DictReader(line for line in lines if not line.startswith('#')))
    for row in rows:
        for key in ('start_us','duration_us','thread'): row[key] = int(row[key])
    rows = [row for row in rows if any(row['start_us'] + row['duration_us'] >= window['start_us']
            and (window['end_us'] is None or row['start_us'] <= window['end_us']) for window in ranges)]
    groups = [sorted((row for row in rows if row['event']=='presentation' and row['start_us'] >= window['start_us']
                     and (window['end_us'] is None or row['start_us'] <= window['end_us'])),key=lambda row:row['start_us']) for window in ranges]
    frames = [frame for group in groups for frame in group]
    # A gap between movement windows is travel/loading, never a movement frame.
    pairs = [pair for group in groups for pair in zip(group, group[1:])]
    intervals = sorted((b['start_us']-a['start_us'])/1000 for a,b in pairs)
    def percentile(p, values=intervals):
        if not values: return None
        index = (len(values)-1)*p/100
        low, high = math.floor(index), math.ceil(index)
        return values[low]+(values[high]-values[low])*(index-low)
    events = defaultdict(list)
    for row in rows: events[row['event']].append(row['duration_us']/1000)
    spikes = []
    work_rows=sorted((r for r in rows if r['event']!='presentation'),key=lambda r:r['start_us'])
    active=[]; index=0
    for before, after in pairs:
        gap = after['start_us']-before['start_us']
        active=[r for r in active if r['start_us']+r['duration_us']>before['start_us']]
        while index<len(work_rows) and work_rows[index]['start_us']<after['start_us']:
            r=work_rows[index]; index+=1
            if r['start_us']+r['duration_us']>before['start_us']: active.append(r)
        if gap <= 33300: continue
        work=list(active)
        work.sort(key=lambda r:r['duration_us'],reverse=True)
        spikes.append({'start_us':before['start_us'],'end_us':after['start_us'],
                       'presentation_thread':before['thread'], 'present_interval_ms':gap/1000,
                       'classification':'inconclusive',
                       'overlapping_cpu_events':work[:10]})
    spikes.sort(key=lambda s:s['present_interval_ms'],reverse=True)
    cpu_ms, cpu_seconds, cpu_intervals = 0, 0, 0
    valid_cpu = bool(cpu_samples) and all(b['relative_us']-a['relative_us'] >= 900000 and b['cpu_us'] >= a['cpu_us']
                                        for a,b in zip(cpu_samples,cpu_samples[1:]))
    if valid_cpu:
        for a,b in zip(cpu_samples,cpu_samples[1:]):
            if any(a['relative_us'] >= w['start_us'] and (w['end_us'] is None or b['relative_us'] <= w['end_us']) for w in ranges):
                cpu_ms += (b['cpu_us']-a['cpu_us'])/1000
                cpu_seconds += (b['relative_us']-a['relative_us'])/1e6
                cpu_intervals += 1
    return {'file':str(path),'event_count':len(rows),'presentations':len(frames),
            'process_cpu': {'cpu_ms':cpu_ms, 'coverage_seconds':cpu_seconds, 'sample_intervals':cpu_intervals,
                            'cpu_ms_per_second':cpu_ms/cpu_seconds if cpu_seconds else None,
                            'valid_samples':valid_cpu, 'scope':'complete sample intervals inside requested windows'},
            'process_cpu_samples':cpu_samples,
            'cpu_counters':cpu_counters[-1] if cpu_counters else None,
            'cpu_counter_scope':'whole capture; relaxed atomic snapshots; excludes calls after capture ends',
            'capture_finalized':'dropped_events' in footer,
            'dropped_events':footer.get('dropped_events'),
            'dropped_presentations':footer.get('dropped_presentations'),
            'filtered_short_events':footer.get('filtered_short_events'),
            'filtered_short_file_reads':footer.get('filtered_short_file_reads'),
            'schema_version':int(metadata.get('schema_version', 1)),
            'clock_sync':syncs, 'clock_metadata':metadata,
            'dropped_by_category':losses or None,
            'aggregated_events':aggregates,
            'aggregate_scope':'whole capture, including outside the requested window',
            'shader_coverage':{coverage:sorted({key for row in rows
                for key,label in zip(row.get('shader_ids','').split(';'),row.get('coverage','').split(';'))
                if key and label == coverage}) for coverage in ('restored','new','generated','unknown')},
            'window_us':{'start':start_us,'end':end_us},
            'coverage_seconds':sum((group[-1]['start_us']-group[0]['start_us'])/1e6 for group in groups if len(group)>1),
            'activity_window_summaries':[{'zone':window.get('zone'),
                'frame_interval_count':max(0,len(group)-1),
                'coverage_seconds':(group[-1]['start_us']-group[0]['start_us'])/1e6 if len(group)>1 else 0,
                'p99_ms':percentile(99,sorted((b['start_us']-a['start_us'])/1000 for a,b in zip(group,group[1:])))}
                for window,group in zip(ranges,groups)],
            'frame_interval_count':len(intervals),
            'frame_interval_percentiles_ms':{str(p):percentile(p) for p in (50,90,95,99)},
            'frame_intervals_above_ms':{str(t):sum(i>t for i in intervals) for t in (33.3,50,100)},
            'cpu_event_summary':{name:{'count':len(v),'max_ms':max(v),'mean_ms':sum(v)/len(v)} for name,v in sorted(events.items())},
            'present_intervals_over_33ms':sum(i>=33 for i in intervals),
            'present_intervals_over_33_3ms':len(spikes),'largest_intervals':spikes[:30],
            'hitches_over_50ms':[s for s in sorted(spikes,key=lambda s:s['start_us']) if s['present_interval_ms']>50],
            'limits':'CPU wall-time capture, not GPU execution or proof of causation. Intervals include game work and pacing. Concurrent/nested event durations must not be summed.'}

if __name__=='__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture')
    parser.add_argument('--start-us', type=int, default=0)
    parser.add_argument('--end-us', type=int)
    args = parser.parse_args()
    print(json.dumps(report(args.capture, args.start_us, args.end_us), indent=2))
