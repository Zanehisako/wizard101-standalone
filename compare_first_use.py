#!/usr/bin/env python3
"""Evaluate three annotated gameplay pairs; never manufacture live passes."""
import argparse
import json
from pathlib import Path
from profile_report import report
from prepare_comparison import ROUTE, expected_labels

PHASES = ('first_arrival', 'immediate_revisit', 'after_restart')


def compare(manifest, root=Path('.')):
    issues, results = [], []
    if manifest.get('diagnosis') != 'compilation':
        issues.append('Fresh capture must support compilation before enabling this candidate.')
    if len(manifest.get('pairs', [])) != 3:
        issues.append('Exactly three paired runs are required.')
    if len({pair.get('id') for pair in manifest.get('pairs',[])}) != 3:
        issues.append('Three distinct pair identifiers are required.')
    ordered_sessions = {}
    input_seeds, renderer_builds, settings = set(), set(), set()
    used_windows = set()
    for pair in manifest.get('pairs', []):
        entries = []
        for phase in PHASES:
            baseline, candidate = pair['baseline'][phase], pair['candidate'][phase]
            for field in ('route', 'settings_sha256', 'starting_cache_sha256', 'seed_sha256', 'starting_inputs_sha256'):
                if not baseline.get(field) or baseline[field] != candidate.get(field):
                    issues.append(f'{pair["id"]}/{phase}: unequal or missing {field}.')
            reports = []
            sessions = []
            for mode, sample in [('baseline', baseline), ('candidate', candidate)]:
                if sample['end_us'] <= sample['start_us']:
                    raise ValueError('Activity windows must have positive length')
                path = root / sample['capture']
                window = (str(path.resolve()), sample['start_us'], sample['end_us'])
                if window in used_windows:
                    issues.append(f'{pair["id"]}/{phase}/{mode}: reused activity window.')
                used_windows.add(window)
                capture = report(path, sample['start_us'], sample['end_us'])
                session = json.loads((path.parent/'session.json').read_text())
                sessions.append(session)
                input_seeds.add(session.get('seed_sha256'))
                renderer_builds.add(session.get('renderer_sha256'))
                settings.add(session.get('settings_sha256'))
                label = f'pair{pair["id"]}-{mode}' + ('-restart' if phase == 'after_restart' else '')
                if session.get('comparison_label') != label:
                    issues.append(f'{pair["id"]}/{phase}/{mode}: wrong launch label.')
                ordered_sessions[label] = session.get('started_at','')
                if (session.get('heavyweight_trace') is not False or session.get('seed_restored') is not True
                    or session.get('handoff_inputs_verified') is not True):
                    issues.append(f'{pair["id"]}/{phase}/{mode}: trace session or seed restoration unverified.')
                if sample.get('activity') != 'movement' or sample.get('route') != manifest.get('route',ROUTE):
                    issues.append(f'{pair["id"]}/{phase}/{mode}: unmatched route or activity is not movement.')
                if session.get('warmup_requested') != (mode == 'candidate') or session.get('frame_rate') != 'capped' or session.get('limiter') != 'legacy' or not session.get('profiling_requested'):
                    issues.append(f'{pair["id"]}/{phase}/{mode}: wrong warm-up, pacing, cap or profiling mode.')
                for field in ('settings_sha256', 'starting_cache_sha256', 'seed_sha256', 'starting_inputs_sha256'):
                    if sample.get(field) != session.get(field):
                        issues.append(f'{pair["id"]}/{phase}/{mode}: {field} does not match recorded launch metadata.')
                if session.get('seed_sha256') != session.get('starting_inputs_sha256'):
                    issues.append(f'{pair["id"]}/{phase}/{mode}: archives, tracking, settings or caches differ from seed.')
                if mode == 'candidate':
                    full = report(path)
                    if full['cpu_event_summary'].get('shader_warmup_startup_wait', {}).get('max_ms', float('inf')) > 10100:
                        issues.append(f'{pair["id"]}/{phase}: startup wait budget was not verified.')
                if not capture['capture_finalized'] or capture['dropped_presentations'] != 0:
                    issues.append(f'{pair["id"]}/{phase}/{mode}: unfinished capture or missing/dropped presentation events.')
                if capture['schema_version'] != 2 or not capture['clock_sync']:
                    issues.append(f'{pair["id"]}/{phase}/{mode}: synchronized capture metadata missing.')
                if capture['dropped_by_category'] is None or any(capture['dropped_by_category'].get(c,1) for c in ('pipeline','shader')):
                    issues.append(f'{pair["id"]}/{phase}/{mode}: compilation evidence was lost or loss counters missing.')
                if capture['frame_interval_count'] < 100:
                    issues.append(f'{pair["id"]}/{phase}/{mode}: insufficient coverage.')
                requested = (sample['end_us']-sample['start_us'])/1e6
                if capture['coverage_seconds'] < requested-max(1, requested*.05):
                    issues.append(f'{pair["id"]}/{phase}/{mode}: capture does not cover the annotated activity window.')
                reports.append(capture)
            if sessions[0].get('renderer_sha256') != sessions[1].get('renderer_sha256'):
                issues.append(f'{pair["id"]}/{phase}: different renderer builds in the warm-up comparison.')
            a, b = reports
            if abs(a['coverage_seconds']-b['coverage_seconds']) > max(1, a['coverage_seconds']*.05):
                issues.append(f'{pair["id"]}/{phase}: unmatched activity duration.')
            p99_delta = None
            if a['frame_interval_percentiles_ms']['99'] is not None and b['frame_interval_percentiles_ms']['99'] is not None:
                p99_delta = b['frame_interval_percentiles_ms']['99']-a['frame_interval_percentiles_ms']['99']
                if p99_delta > 1:
                    issues.append(f'{pair["id"]}/{phase}: p99 regressed by {p99_delta:.3f} ms.')
            entries.append({'phase': phase, 'baseline': a, 'candidate': b, 'p99_delta_ms': p99_delta})
        results.append({'id': pair['id'], 'phases': entries})
    labels = expected_labels()[:-1]
    times = [ordered_sessions.get(label,'') for label in labels]
    if any(not t for t in times) or times != sorted(times) or len(set(times)) != len(times):
        issues.append('Three alternating pairs and their distinct restarts were not recorded in controlled order.')
    if any(len(values)!=1 or None in values for values in (input_seeds,renderer_builds,settings)):
        issues.append('All paired launches must share one immutable seed, renderer and settings baseline.')
    persistence = manifest.get('persistence')
    if not persistence:
        issues.append('Ordinary restart without resetting caches is pending.')
    else:
        path = root / persistence['capture']
        persisted = report(path)
        session = json.loads((path.parent/'session.json').read_text())
        if (session.get('comparison_label') != 'persistence' or session.get('seed_restored') is not False
            or session.get('heavyweight_trace') is not False or session.get('persistence_restart') is not True
            or session.get('warmup_requested') is not True or session.get('frame_rate') != 'capped'
            or session.get('limiter') != 'legacy' or not persisted['capture_finalized']
            or persisted['dropped_presentations'] != 0 or persisted['dropped_events'] != 0
            or session.get('renderer_sha256') not in renderer_builds or session.get('settings_sha256') not in settings
            or session.get('seed_sha256') not in input_seeds
            or not persisted['shader_coverage']['restored'] or not session.get('started_at','') > max(times)):
            issues.append('Persistence restart did not verify learned-cache reload after the paired runs.')
    first = [phase for pair in results for phase in pair['phases'] if phase['phase'] == 'first_arrival']
    before = sum(p['baseline']['frame_intervals_above_ms']['50'] for p in first)
    after = sum(p['candidate']['frame_intervals_above_ms']['50'] for p in first)
    if after >= before:
        issues.append('No reduction in first-appearance intervals above 50 ms.')
    if manifest.get('movement_and_combat_accepted') is not True:
        issues.append('User confirmation during ordinary movement and combat is pending.')
    if manifest.get('graphics_accepted') is not True:
        issues.append('HUD, effects, transparency and larger cursor acceptance is pending.')
    return {'eligible_for_rollout': not issues, 'issues': issues, 'pairs': results,
            'first_arrival_above_50ms': {'baseline': before, 'candidate': after},
            'stop_compilation_candidate': manifest.get('diagnosis') in ('asset_loading','resource_retry','game_processing','gpu_execution'),
            'limits': 'CPU presentation intervals and API spans. Event overlap alone is not proof of causation; read hooks do not cover mapped-file faults or decompression.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    args = parser.parse_args()
    print(json.dumps(compare(json.loads(args.manifest.read_text()), args.manifest.parent), indent=2))
