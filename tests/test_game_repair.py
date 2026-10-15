import copy
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from game_context import analyze
from game.pe_identity import PEIdentity
from thread_map import join_threads
from score_game_repair import metrics, score_frames, score, PHASES, ORDER


def fake_pe():
    data = bytearray(0x600)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 0x3c, 0x80)
    data[0x80:0x84] = b'PE\0\0'
    struct.pack_into('<HHIIIHH', data, 0x84, 0x8664, 2, 0, 0, 0, 240, 0)
    o = 0x98
    struct.pack_into('<H', data, o, 0x20b)
    struct.pack_into('<Q', data, o+24, 0x140000000)
    struct.pack_into('<I', data, o+56, 0x4000)
    struct.pack_into('<II', data, o+112+3*8, 0x2000, 12)
    for i, (name, rva, raw, flags) in enumerate([(b'.text', 0x1000, 0x200, 0x60000020), (b'.pdata', 0x2000, 0x400, 0x40000040)]):
        s = o+240+i*40
        struct.pack_into('<8sIIII', data, s, name, 0x200, rva, 0x200, raw)
        struct.pack_into('<I', data, s+36, flags)
    data[0x200:0x220] = bytes(range(32))
    struct.pack_into('<III', data, 0x400, 0x1000, 0x1020, 0x2010)
    return bytes(data)


def frames():
    # All five phases, with a 60-second settled crowd. Boundary frame intervals
    # are deliberately present and must participate in the global pause gate.
    timestamps = [i*16667 for i in range(4001)]
    boundaries = [0, 3601, 3701, 3801, 3901, 4000]
    windows = [dict(phase=p, start_us=timestamps[boundaries[i]], end_us=timestamps[boundaries[i+1]])
               for i, p in enumerate(PHASES)]
    return dict(timestamps_us=timestamps, windows=windows, dropped_frames=0, finalized=True)


class GameRepairTests(unittest.TestCase):
    def test_thread_identity_requires_exact_unique_agreement(self):
        windows = {'threads': [dict(windows_tid=36, pthread_handle=0, pthread_tsd_handle=1224),
                               dict(windows_tid=40, pthread_handle=2000, pthread_tsd_handle=2224)]}
        native = {'inspection': 'libproc_snapshot', 'threads': [dict(native_tid=100, pthread_handle=1000, pthread_tsd_handle=1224),
                                                              dict(native_tid=200, pthread_handle=2000, pthread_tsd_handle=2224)]}
        mappings, unmapped = join_threads(windows, native)
        self.assertEqual([(t['windows_tid'], t['native_tid']) for t in mappings], [(36, 100), (40, 200)])
        self.assertFalse(unmapped)
        conflicting = copy.deepcopy(native)
        conflicting['threads'][1]['pthread_tsd_handle'] = 1224
        self.assertEqual(join_threads(windows, conflicting)[0], [])
        zero = {'threads': [dict(windows_tid=36, pthread_handle=0, pthread_tsd_handle=0)]}
        self.assertEqual(join_threads(zero, native)[0], [])
        reused = copy.deepcopy(windows)
        reused['threads'].append({**reused['threads'][0], 'windows_tid': 44})
        self.assertEqual([t['windows_tid'] for t in join_threads(reused, native)[0]], [40])

    def test_precise_metrics_and_single_pause(self):
        self.assertTrue(metrics([16667]*600)['passed'])
        result = metrics([16667]*600+[51000])
        self.assertLess(result['p99_ms'], 20)
        self.assertFalse(result['passed'])
        self.assertEqual(result['pauses_over_50ms'], 1)

    def test_numeric_gates_independently(self):
        self.assertFalse(metrics([17000]*100)['passed'])
        self.assertFalse(metrics([16000]*98+[21000]*2)['passed'])
        self.assertEqual(metrics([50000]*100)['pauses_over_50ms'], 0)

    def test_all_phases_and_boundary_pause(self):
        artifact = frames()
        self.assertTrue(score_frames(artifact)['passed'])
        boundary = artifact['windows'][1]['start_us']
        index = artifact['timestamps_us'].index(boundary)
        artifact['timestamps_us'][index] += 40000
        artifact['timestamps_us'][index+1] += 40000
        artifact['timestamps_us'][index+2] += 40000
        artifact['timestamps_us'][index+3] += 40000
        # Extend all later frames rather than hide the pause at a window boundary.
        for i in range(index+4, len(artifact['timestamps_us'])):
            artifact['timestamps_us'][i] += 40000
        for w in artifact['windows']:
            if w['start_us'] >= boundary:
                w['start_us'] += 40000
            if w['end_us'] >= boundary:
                w['end_us'] += 40000
        self.assertFalse(score_frames(artifact)['passed'])

    def test_dropped_unfinished_and_uncovered(self):
        for update in ({'dropped_frames': 1}, {'finalized': False}):
            artifact = frames(); artifact.update(update)
            with self.assertRaises(ValueError):
                score_frames(artifact)
        artifact = frames(); artifact['windows'][1]['start_us'] += 1
        with self.assertRaises(ValueError):
            score_frames(artifact)

    def test_pe_function_bounds_and_signatures(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'fixture.exe'; path.write_bytes(fake_pe())
            pe = PEIdentity(path)
            self.assertIsNone(pe.function(0xfff))
            self.assertEqual(pe.function(0x101f)['begin_rva'], 0x1000)
            self.assertIsNone(pe.function(0x1020))
            self.assertEqual(pe.function(0x1000)['signature'], bytes(range(32)).hex())
            with self.assertRaises(ValueError):
                pe.bytes_at(0x11ff, 2)
            path.write_bytes(fake_pe()[:0x300])
            with self.assertRaises(ValueError):
                PEIdentity(path)

    def test_signature_rejection_and_unknown_cpu(self):
        with tempfile.TemporaryDirectory() as d:
            exe = Path(d)/'fixture.exe'; exe.write_bytes(fake_pe())
            sample = Path(d)/'sample.jsonl'
            rows = [dict(kind='session', executable_sha256=hashlib.sha256(fake_pe()).hexdigest(), diagnostic_only=True),
                    dict(kind='sample', tid=1, cpu_delta_100ns=0, context_valid=True, previous_suspend_count=0,
                         suspension_us=100, frames=[dict(module='fixture.exe', rva=0x1001, function_rva=0x1000, signature='00'*32)]),
                    dict(kind='end', completed=True, resume_failed=False)]
            sample.write_text('\n'.join(map(json.dumps, rows)))
            report = analyze(sample, exe)
            self.assertFalse(report['attribution_verified'])
            self.assertIsNone(report['threads_cpu_us'])
            self.assertEqual(report['rejected']['unverified_function_signature'], 1)
            self.assertEqual(report['observed_game_function_leads'], [])
            rows[1]['frames'][0]['signature'] = bytes(range(32)).hex()
            sample.write_text('\n'.join(map(json.dumps, rows)))
            self.assertEqual(analyze(sample, exe)['observed_game_function_leads'][0]['self_samples'], 1)
            rows[-1]['resume_failed'] = True
            sample.write_text('\n'.join(map(json.dumps, rows)))
            with self.assertRaises(ValueError):
                analyze(sample, exe)

    def test_run_integrity_and_user_acceptance(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            manifest = dict(patch_output_equivalence_verified=True, patch_failure_reset_shutdown_verified=True,
                            verified_hook_identities=[dict(rva=123, signature='verified')], user_gameplay_accepted=False,
                            runs=[])
            for i, mode in enumerate(ORDER):
                artifact = root/f'frames-{i}.json'
                capture = frames(); capture['capture_id'] = str(i)
                artifact.write_text(json.dumps(capture))
                run = dict(mode=mode, restart_id=str(i), diagnostic_hooks=False, context_sampling=False,
                           heavyweight_trace=False, frame_rate=60, resolution=[2560, 1600], limiter='legacy', moltenvk='1.4.2',
                           settings_sha256='same-settings', saved_selections_sha256='same-selections', executable_sha256='same-exe',
                           game_repair_enabled=mode=='candidate', commons_settle_seconds=60, route='same-route',
                           realm='same-realm', crowd_conditions='matched', frames=artifact.name, frames_sha256=hashlib.sha256(artifact.read_bytes()).hexdigest())
                run.update({flag: True for flag in ('all_animations', 'combat_ok', 'controls_ok', 'textures_ok', 'fullscreen_ok', 'larger_cursor')})
                manifest['runs'].append(run)
            path = root/'manifest.json'
            def evaluate(value):
                path.write_text(json.dumps(value)); return score(path)
            result = evaluate(manifest)
            self.assertTrue(result['numeric_gate_passed'])
            self.assertFalse(result['rollout_allowed'])
            manifest['user_gameplay_accepted'] = True
            self.assertTrue(evaluate(manifest)['rollout_allowed'])
            for field, value in [('context_sampling', True), ('frames_sha256', 'changed'),
                                 ('settings_sha256', 'different'), ('mode', 'baseline'), ('combat_ok', False),
                                 ('game_repair_enabled', False), ('frames', 'frames-0.json')]:
                changed = copy.deepcopy(manifest); changed['runs'][1][field] = value
                with self.subTest(field=field), self.assertRaises(ValueError):
                    evaluate(changed)


if __name__ == '__main__':
    unittest.main()
