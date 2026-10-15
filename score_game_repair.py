#!/usr/bin/env python3
"""Fail-closed acceptance for six restarted, alternating game-repair runs.

Input: JSON manifest with runs in time order. Each run supplies a hashed JSON
artifact containing frame timestamps in microseconds and contiguous annotated
windows. Full workload/context diagnostics must be disabled during scoring.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

PHASES = ('settled_crowd', 'movement', 'arrivals', 'first_entry', 'restart_revisit')
ORDER = ('baseline', 'candidate', 'candidate', 'baseline', 'baseline', 'candidate')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def metrics(intervals):
    if not intervals:
        raise ValueError('No complete gameplay frame intervals')
    values = sorted(intervals)
    i = (len(values)-1)*.99
    p99 = values[math.floor(i)]+(values[math.ceil(i)]-values[math.floor(i)])*(i-math.floor(i))
    avg = 1e6*len(values)/sum(values)
    pauses = sum(x > 50000 for x in values)
    return dict(frame_intervals=len(values), average_fps=avg, p99_ms=p99/1000,
                pauses_over_50ms=pauses, passed=avg >= 59 and p99 <= 20000 and pauses == 0)


def score_frames(artifact):
    frames, windows = artifact['timestamps_us'], artifact['windows']
    if len(frames) < 2 or any(type(x) is not int or x < 0 for x in frames) or any(a >= b for a, b in zip(frames, frames[1:])):
        raise ValueError('Frame timestamps must be complete and strictly increasing')
    if artifact.get('dropped_frames') != 0 or artifact.get('finalized') is not True:
        raise ValueError('Lost or unfinished frame evidence')
    if not windows or windows[0]['start_us'] != frames[0] or windows[-1]['end_us'] != frames[-1]:
        raise ValueError('Annotations must cover the complete capture')
    for i, window in enumerate(windows):
        if window['phase'] not in (*PHASES, 'loading') or window['start_us'] >= window['end_us']:
            raise ValueError('Invalid activity window')
        if i and windows[i-1]['end_us'] != window['start_us']:
            raise ValueError('Activity windows must be contiguous and nonoverlapping')
    if set(w['phase'] for w in windows) - {'loading'} != set(PHASES):
        raise ValueError('All five gameplay phases are required')
    groups = {phase: [] for phase in PHASES}
    gameplay = []
    for before, after in zip(frames, frames[1:]):
        # Only intervals intersecting a declared loading screen are exempt.
        overlapping = [w for w in windows if before < w['end_us'] and after > w['start_us']]
        if any(w['phase'] == 'loading' for w in overlapping):
            continue
        interval = after-before
        gameplay.append(interval)
        # Boundary intervals remain in the global pause gate; they are not lost.
        if len(overlapping) == 1:
            groups[overlapping[0]['phase']].append(interval)
    phases = {p: metrics(v) for p, v in groups.items()}
    if sum(groups['settled_crowd']) < 60e6:
        raise ValueError('Settled crowd requires at least 60 seconds of measured frames')
    result = metrics(gameplay)
    result['phases'] = phases
    result['passed'] = result['passed'] and all(v['passed'] for v in phases.values())
    return result


def score(manifest_path):
    manifest_path = Path(manifest_path).resolve()
    manifest = json.loads(manifest_path.read_text())
    runs = manifest['runs']
    if len(runs) != 6 or tuple(r['mode'] for r in runs) != ORDER:
        raise ValueError('Run order must be off/on, on/off, off/on')
    if len({r['restart_id'] for r in runs}) != 6:
        raise ValueError('Each run requires an independent game restart')
    if len({str((manifest_path.parent/r['frames']).resolve()) for r in runs}) != 6 or len({r['frames_sha256'] for r in runs}) != 6:
        raise ValueError('Each run requires independent frame evidence; duplicated artifacts are not six runs')
    if manifest.get('patch_output_equivalence_verified') is not True or manifest.get('patch_failure_reset_shutdown_verified') is not True:
        raise ValueError('Patch correctness must pass before gameplay acceptance')
    if not manifest.get('verified_hook_identities'):
        raise ValueError('Verified hook identities are required')
    results = []
    for index, run in enumerate(runs):
        for flag in ('diagnostic_hooks', 'context_sampling', 'heavyweight_trace'):
            if run.get(flag) is not False:
                raise ValueError('Diagnostic hooks must be disabled in scored runs')
        if run.get('frame_rate') != 60 or run.get('resolution') != [2560, 1600] or run.get('limiter') != 'legacy' or run.get('moltenvk') != '1.4.2':
            raise ValueError('Required gameplay baseline changed')
        for flag in ('all_animations', 'combat_ok', 'controls_ok', 'textures_ok', 'fullscreen_ok', 'larger_cursor'):
            if run.get(flag) is not True:
                raise ValueError('Gameplay behavior must be explicitly verified: '+flag)
        if not run.get('settings_sha256') or not run.get('saved_selections_sha256') or not run.get('executable_sha256'):
            raise ValueError('Settings, selections and executable identities are required')
        if run.get('game_repair_enabled') is not (run['mode'] == 'candidate'):
            raise ValueError('Requested repair selection does not match the run')
        if run.get('commons_settle_seconds', 0) < 60 or not run.get('route') or not run.get('crowd_conditions'):
            raise ValueError('Settling, route and crowd observations are required')
        if index % 2:
            partner = runs[index-1]
            for field in ('settings_sha256', 'saved_selections_sha256', 'executable_sha256', 'realm', 'route', 'crowd_conditions'):
                if run.get(field) != partner.get(field) or not run.get(field):
                    raise ValueError('Pair conditions differ: '+field)
        artifact_path = (manifest_path.parent/run['frames']).resolve()
        if sha(artifact_path) != run.get('frames_sha256'):
            raise ValueError('Frame evidence hash mismatch')
        results.append(dict(mode=run['mode'], **score_frames(json.loads(artifact_path.read_text()))))
    numeric = all(r['passed'] for r in results if r['mode'] == 'candidate')
    experience = manifest.get('user_gameplay_accepted') is True
    return dict(runs=results, numeric_gate_passed=numeric, user_gameplay_accepted=experience,
                gameplay_accepted=numeric and experience, rollout_allowed=numeric and experience,
                manifest_sha256=sha(manifest_path))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('manifest', type=Path)
    p.add_argument('--output', type=Path)
    a = p.parse_args()
    result = score(a.manifest)
    text = json.dumps(result, indent=2)+'\n'
    if a.output:
        with a.output.open('x') as f:
            f.write(text)
    print(text, end='')
