#!/usr/bin/env python3
"""Screen or verify renderer overhead experiments without changing warm-up gates."""
import argparse
import json
from pathlib import Path
from profile_report import report
from prepare_comparison import ROUTE, expected_labels

PHASES = ('first_arrival', 'immediate_revisit', 'after_restart')


def compare_performance(manifest, root=Path('.'), *, screen=False):
    issues, results = [], []
    experiment = manifest.get('comparison')
    optimized = manifest.get('candidate_mode')
    if experiment not in ('pipeline', 'queue', 'cpu', 'rendering'):
        issues.append('Specify pipeline, queue, cpu or rendering comparison.')
    if experiment == 'rendering' and optimized != '1':
        issues.append('Select rendering switch 1 for the candidate.')
    if experiment == 'pipeline' and optimized not in ('replay','lookup','both'):
        issues.append('Select replay, lookup or both for the candidate.')
    if experiment == 'cpu' and optimized not in ('constants','locking','both'):
        issues.append('Select constants, locking or both for the CPU candidate.')
    phases = PHASES[:2] if screen else PHASES
    count = 1 if screen else 3
    if len(manifest.get('pairs', [])) != count:
        issues.append(f'Exactly {count} paired runs are required.')
    if len({pair.get('id') for pair in manifest.get('pairs',[])}) != count:
        issues.append('Distinct pair identifiers are required.')
    ordered_sessions = {}
    input_seeds, renderer_builds, settings = set(), set(), set()
    used_windows = set()
    for pair in manifest.get('pairs', []):
        entries = []
        for phase in phases:
            baseline, candidate = pair['baseline'][phase], pair['candidate'][phase]
            for field in ('route', 'settings_sha256', 'starting_cache_sha256', 'seed_sha256', 'starting_inputs_sha256'):
                if not baseline.get(field) or baseline[field] != candidate.get(field):
                    issues.append(f'{pair["id"]}/{phase}: unequal or missing {field}.')
            a_zones=[window.get('zone') for window in baseline.get('windows',[])]
            b_zones=[window.get('zone') for window in candidate.get('windows',[])]
            if a_zones != b_zones:
                issues.append(f'{pair["id"]}/{phase}: unmatched movement areas.')
            if manifest.get('required_zones') and (a_zones != manifest['required_zones'] or b_zones != manifest['required_zones']):
                issues.append(f'{pair["id"]}/{phase}: route areas are incomplete.')
            reports = []
            sessions = []
            for mode, sample in [('baseline', baseline), ('candidate', candidate)]:
                path = root / sample['capture']
                windows=sample.get('windows',[{'start_us':sample.get('start_us'),'end_us':sample.get('end_us')}])
                for activity in windows:
                    if activity['end_us'] <= activity['start_us']:
                        raise ValueError('Activity windows must have positive length')
                    window=(str(path.resolve()),activity['start_us'],activity['end_us'])
                    if window in used_windows:
                        issues.append(f'{pair["id"]}/{phase}/{mode}: reused activity window.')
                    elif any(previous[0]==window[0] and previous[1]<=window[2] and previous[2]>=window[1] for previous in used_windows):
                        issues.append(f'{pair["id"]}/{phase}/{mode}: overlapping activity windows.')
                    used_windows.add(window)
                capture = report(path, windows=windows)
                session = json.loads((path.parent/'session.json').read_text())
                sessions.append(session)
                input_seeds.add(session.get('seed_sha256'))
                renderer_builds.add(session.get('renderer_sha256'))
                settings.add(session.get('settings_sha256'))
                label = f'screen-{mode}' if screen else f'pair{pair["id"]}-{mode}' + ('-restart' if phase == 'after_restart' else '')
                if session.get('comparison_label') != label:
                    issues.append(f'{pair["id"]}/{phase}/{mode}: wrong launch label.')
                ordered_sessions[label] = session.get('started_at','')
                if (session.get('heavyweight_trace') is not False or session.get('seed_restored') is not True
                    or session.get('handoff_inputs_verified') is not True):
                    issues.append(f'{pair["id"]}/{phase}/{mode}: trace session or seed restoration unverified.')
                if sample.get('activity') != 'movement' or sample.get('route') != manifest.get('route',ROUTE):
                    issues.append(f'{pair["id"]}/{phase}/{mode}: unmatched route or activity is not movement.')
                if session.get('warmup_requested') is not True or session.get('frame_rate') != 'capped' or session.get('limiter') != 'legacy' or not session.get('profiling_requested'):
                    issues.append(f'{pair["id"]}/{phase}/{mode}: wrong warm-up, pacing, cap or profiling mode.')
                expected_opt = optimized if experiment == 'pipeline' and mode == 'candidate' else 'off'
                expected_submit = '0' if experiment == 'queue' and mode == 'candidate' else '1'
                if (session.get('pipeline_optimization') != expected_opt or session.get('synchronous_queue_submits') != expected_submit
                    or session.get('async') is not False):
                    issues.append(f'{pair["id"]}/{phase}/{mode}: wrong pipeline, queue submission or async mode.')
                expected_cpu = optimized if experiment == 'cpu' and mode == 'candidate' else 'off'
                if session.get('cpu_optimization','off') != expected_cpu:
                    issues.append(f'{pair["id"]}/{phase}/{mode}: wrong CPU optimization mode.')
                expected_stutter = experiment == 'rendering' and mode == 'candidate'
                if session.get('stutter_fix',False) is not expected_stutter:
                    issues.append(f'{pair["id"]}/{phase}/{mode}: wrong rendering switch.')
                if experiment == 'cpu':
                    cpu = capture['process_cpu']
                    if (not cpu['valid_samples'] or cpu['coverage_seconds'] < .8*capture['coverage_seconds']
                        or cpu['sample_intervals'] < 4 or not capture['cpu_counters'] or capture['cpu_counters']['overflow_calls']):
                        issues.append(f'{pair["id"]}/{phase}/{mode}: insufficient CPU samples or incomplete aggregate counters.')
                for field in ('settings_sha256', 'starting_cache_sha256', 'seed_sha256', 'starting_inputs_sha256'):
                    if sample.get(field) != session.get(field):
                        issues.append(f'{pair["id"]}/{phase}/{mode}: {field} does not match recorded launch metadata.')
                if session.get('seed_sha256') != session.get('starting_inputs_sha256'):
                    issues.append(f'{pair["id"]}/{phase}/{mode}: archives, tracking, settings or caches differ from seed.')
                full = report(path)
                if full['cpu_event_summary'].get('shader_warmup_startup_wait', {}).get('max_ms', float('inf')) > 10100:
                    issues.append(f'{pair["id"]}/{phase}/{mode}: startup wait budget was not verified.')
                if not capture['capture_finalized'] or capture['dropped_presentations'] != 0:
                    issues.append(f'{pair["id"]}/{phase}/{mode}: unfinished capture or missing/dropped presentation events.')
                if capture['schema_version'] != 2 or not capture['clock_sync']:
                    issues.append(f'{pair["id"]}/{phase}/{mode}: synchronized capture metadata missing.')
                if capture['dropped_by_category'] is None or any(capture['dropped_by_category'].get(c,1) for c in ('pipeline','shader')):
                    issues.append(f'{pair["id"]}/{phase}/{mode}: compilation evidence was lost or loss counters missing.')
                if capture['frame_interval_count'] < 100:
                    issues.append(f'{pair["id"]}/{phase}/{mode}: insufficient coverage.')
                requested = sum((window['end_us']-window['start_us'])/1e6 for window in windows)
                if capture['coverage_seconds'] < requested-max(1, requested*.05):
                    issues.append(f'{pair["id"]}/{phase}/{mode}: capture does not cover the annotated activity window.')
                for window,summary in zip(windows,capture['activity_window_summaries']):
                    seconds=(window['end_us']-window['start_us'])/1e6
                    if summary['frame_interval_count'] < 100 or summary['coverage_seconds'] < seconds-max(1,seconds*.05):
                        issues.append(f'{pair["id"]}/{phase}/{mode}: insufficient movement coverage in {window.get("zone","window")}.')
                reports.append(capture)
            if sessions[0].get('renderer_sha256') != sessions[1].get('renderer_sha256'):
                issues.append(f'{pair["id"]}/{phase}: different renderer builds in the performance comparison.')
            a, b = reports
            if abs(a['coverage_seconds']-b['coverage_seconds']) > max(1, a['coverage_seconds']*.05):
                issues.append(f'{pair["id"]}/{phase}: unmatched activity duration.')
            for aw,bw in zip(a['activity_window_summaries'],b['activity_window_summaries']):
                if abs(aw['coverage_seconds']-bw['coverage_seconds']) > max(1,aw['coverage_seconds']*.05):
                    issues.append(f'{pair["id"]}/{phase}/{aw["zone"]}: unmatched movement duration.')
                if aw['p99_ms'] is not None and bw['p99_ms'] is not None and bw['p99_ms']-aw['p99_ms'] > 1:
                    issues.append(f'{pair["id"]}/{phase}/{aw["zone"]}: p99 regressed over 1 ms.')
            p99_delta = None
            if a['frame_interval_percentiles_ms']['99'] is not None and b['frame_interval_percentiles_ms']['99'] is not None:
                p99_delta = b['frame_interval_percentiles_ms']['99']-a['frame_interval_percentiles_ms']['99']
                if p99_delta > 1:
                    issues.append(f'{pair["id"]}/{phase}: p99 regressed by {p99_delta:.3f} ms.')
            cpu_change = None
            if experiment == 'cpu' and a['process_cpu']['cpu_ms_per_second'] and b['process_cpu']['cpu_ms_per_second'] is not None:
                cpu_change = (b['process_cpu']['cpu_ms_per_second']/a['process_cpu']['cpu_ms_per_second']-1)*100
            entries.append({'phase': phase, 'baseline': a, 'candidate': b, 'p99_delta_ms': p99_delta, 'process_cpu_change_percent':cpu_change})
        results.append({'id': pair['id'], 'phases': entries})
    labels = ['screen-baseline','screen-candidate'] if screen else expected_labels()[:-1]
    times = [ordered_sessions.get(label,'') for label in labels]
    if any(not t for t in times) or times != sorted(times) or len(set(times)) != len(times):
        issues.append('Screen order was not recorded.' if screen else 'Three alternating pairs and their distinct restarts were not recorded in controlled order.')
    if any(len(values)!=1 or None in values for values in (input_seeds,renderer_builds,settings)):
        issues.append('All paired launches must share one immutable seed, renderer and settings baseline.')
    persistence = manifest.get('persistence')
    if not persistence and not screen:
        issues.append('Ordinary restart without resetting caches is pending.')
    elif persistence and not screen:
        path = root / persistence['capture']
        persisted = report(path)
        session = json.loads((path.parent/'session.json').read_text())
        if (session.get('comparison_label') != 'persistence' or session.get('seed_restored') is not False
            or session.get('heavyweight_trace') is not False or session.get('persistence_restart') is not True
            or session.get('warmup_requested') is not True or session.get('pipeline_optimization') != (optimized if experiment == 'pipeline' else 'off')
            or session.get('synchronous_queue_submits') != ('0' if experiment == 'queue' else '1') or session.get('async') is not False
            or session.get('cpu_optimization','off') != (optimized if experiment == 'cpu' else 'off')
            or session.get('stutter_fix',False) is not (experiment == 'rendering')
            or session.get('frame_rate') != 'capped'
            or session.get('limiter') != 'legacy' or not persisted['capture_finalized']
            or persisted['dropped_presentations'] != 0 or persisted['dropped_events'] != 0
            or session.get('renderer_sha256') not in renderer_builds or session.get('settings_sha256') not in settings
            or session.get('seed_sha256') not in input_seeds
            or not persisted['shader_coverage']['restored'] or not session.get('started_at','') > max(times)):
            issues.append('Persistence restart did not verify learned-cache reload after the paired runs.')
    cpu_evidence_issues = [issue for issue in issues if 'p99 regressed' not in issue]
    first = [phase for pair in results for phase in pair['phases'] if phase['phase'] == 'first_arrival']
    before = sum(p['baseline']['frame_intervals_above_ms']['50'] for p in first)
    after = sum(p['candidate']['frame_intervals_above_ms']['50'] for p in first)
    if after >= before:
        issues.append('No reduction in first-appearance intervals above 50 ms.')
    if not screen and manifest.get('movement_and_combat_accepted') is not True:
        issues.append('User confirmation during ordinary movement and combat is pending.')
    if not screen and manifest.get('graphics_accepted') is not True:
        issues.append('HUD, effects, transparency and larger cursor acceptance is pending.')
    movement = [phase for pair in results for phase in pair['phases']]
    total_before = sum(p['baseline']['frame_intervals_above_ms']['50'] for p in movement)
    total_after = sum(p['candidate']['frame_intervals_above_ms']['50'] for p in movement)
    if total_after >= total_before:
        issues.append('No reduction in movement intervals above 50 ms.')
    return {'comparison': experiment, 'screen_improved': not issues if screen else None,
            'eligible_for_rollout': not issues and not screen, 'issues': issues, 'pairs': results,
            'movement_above_50ms': {'baseline': total_before, 'candidate': total_after},
            'cpu_savings': {'source':'measured process CPU intervals inside marked movement windows',
                           'matched_inputs_verified': not cpu_evidence_issues,
                           'changes_percent':[p['process_cpu_change_percent'] for p in movement]} if experiment=='cpu' else manifest.get('cpu_savings'),
            'first_arrival_above_50ms': {'baseline': before, 'candidate': after},
            'limits': 'CPU presentation intervals and API spans. Event overlap alone is not proof of causation; read hooks do not cover mapped-file faults or decompression.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--screen', action='store_true')
    args = parser.parse_args()
    print(json.dumps(compare_performance(json.loads(args.manifest.read_text()), args.manifest.parent, screen=args.screen), indent=2))
