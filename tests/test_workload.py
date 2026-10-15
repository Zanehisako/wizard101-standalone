import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from workload_report import summarize,union_us,ClockMap

class WorkloadReportTests(unittest.TestCase):
    def test_gradual_wall_clock_drift_uses_local_anchors(self):
        rows=[{'x':i*1000000,'y':i*1000050} for i in range(1000)]
        clock=ClockMap(rows,'x','y')
        self.assertTrue(clock.usable); self.assertEqual(clock.bad,[])
        self.assertEqual(clock.value(500500000),500525025)
        self.assertEqual(clock.local_variation,50)
    def test_clock_discontinuity_excludes_only_affected_segment(self):
        clock=ClockMap([{'x':0,'y':0},{'x':1000000,'y':1000000},{'x':2000000,'y':2010000},{'x':3000000,'y':3010000}],'x','y')
        self.assertTrue(clock.usable); self.assertEqual(clock.bad,[1])
        self.assertEqual(clock.value(500000),500000)
        self.assertIsNone(clock.value(1500000))
        self.assertEqual(clock.value(2500000),2510000)
        self.assertFalse(clock.interval_valid(500000,2500000))
    def fixture(self,root):
        capture=root/'timing.csv'
        capture.write_text('# schema_version=3\n# clock_sync={"relative_us":0,"unix_us":1000000,"uncertainty_us":1}\n'
            'event,thread,start_us,duration_us,work_units\npresentation,11,0,1,0\npresentation,11,60000,1,0\n'
            '# dropped_events=0\n# dropped_presentations=0\n')
        rows=[{'type':'clock','pid':7,'mach_us':2000000,'unix_us':1000000,'uncertainty_us':1},
              {'type':'gpu','start_mach_us':2001000,'end_mach_us':2030000,'status':4},
              {'type':'gpu','start_mach_us':2020000,'end_mach_us':2059000,'status':4},
              {'type':'footer','dropped_gpu':0,'invalid_timestamps':0,'outstanding_gpu':0}]
        (root/'native.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
        (root/'threads.jsonl').write_text(json.dumps({'type':'thread_identity','pid':7,'windows_tid':11,'native_tid':99,'initial':True})+'\n')
        return capture,rows
    def test_gpu_overlap_uses_union_and_keeps_cause_unknown(self):
        with tempfile.TemporaryDirectory() as d:
            p,rows=self.fixture(Path(d));r=summarize(p)
            self.assertEqual(r['gpu_execution_union_ms'],58)
            self.assertEqual(r['hitches'][0]['classification'],'inconclusive')
            self.assertEqual(r['cause'],'unidentified');self.assertTrue(r['initial_thread_verified'])
    def test_loss_and_missing_initial_thread_cannot_pass(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p,rows=self.fixture(root);rows[-1]['dropped_gpu']=1
            (root/'native.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
            self.assertFalse(summarize(p)['evidence_complete'])
            (root/'threads.jsonl').unlink();r=summarize(p)
            self.assertFalse(r['initial_thread_verified']);self.assertIsNone(r['initial_thread'])
    def test_conflicting_and_truncated_identity_is_unidentified(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p,rows=self.fixture(root)
            with (root/'threads.jsonl').open('a') as f: f.write('{"pid":7,"windows_tid":11,"native_tid":100,"initial":false}\n{"pid":')
            r=summarize(p);self.assertFalse(r['initial_thread_verified']);self.assertNotIn(11,r['verified_thread_mapping'])
    def test_clock_jump_disables_alignment(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p,rows=self.fixture(root)
            rows.append({'type':'clock','pid':7,'mach_us':3000000,'unix_us':2010000,'uncertainty_us':1})
            (root/'native.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
            r=summarize(p);self.assertFalse(r['aligned']);self.assertEqual(r['gpu_buffers'],0)
    def test_window_does_not_count_gpu_outside_it(self):
        with tempfile.TemporaryDirectory() as d:
            p,rows=self.fixture(Path(d));r=summarize(p,30000,40000)
            self.assertEqual(r['gpu_execution_union_ms'],10)
            self.assertEqual(r['timing']['frame_interval_count'],0)
    def test_window_after_native_recording_ended_is_incomplete(self):
        with tempfile.TemporaryDirectory() as d:
            p,rows=self.fixture(Path(d));r=summarize(p,60000,90000)
            self.assertFalse(r['evidence_complete']);self.assertFalse(r['native_covers_requested_window'])
    def test_contentions_align_only_verified_threads_and_preserve_unknown_owner(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p,rows=self.fixture(root)
            rows.append({'type':'clock','pid':7,'mach_us':2061000,'unix_us':1061000,'uncertainty_us':1})
            (root/'native.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
            locks=[{'type':'lock_contention','pid':7,'windows_tid':11,'native_tid':99,
                'owner_windows_tid_at_wait':22,'caller_module':'unidentified','caller_rva':0,
                'start_mach_us':2002000,'end_mach_us':2058000},
                {'type':'footer','records':1,'dropped':0}]
            (root/'locks.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in locks))
            evidence=summarize(p);r=evidence['lock_contentions'][0]
            self.assertEqual(r['start_us'],2000);self.assertEqual(r['end_us'],58000)
            self.assertEqual(r['thread_role'],'initial_game_thread')
            self.assertIsNone(r['owner_native_tid_at_wait']);self.assertEqual(r['caller_module'],'unidentified')
            self.assertEqual(evidence['hitches'][0]['initial_thread_contention_union_ms'],56)
            self.assertTrue(evidence['lock_recording']['complete']);self.assertEqual(evidence['cause'],'unidentified')
            locks[0]['native_tid']=100;locks[-1]['dropped']=1
            (root/'locks.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in locks))
            evidence=summarize(p)
            self.assertEqual(evidence['lock_contentions'][0]['thread_role'],'unidentified')
            self.assertEqual(evidence['hitches'][0]['initial_thread_contention_union_ms'],0)
            self.assertFalse(evidence['lock_recording']['complete'])
            self.assertFalse(evidence['evidence_complete'])

if __name__=='__main__': unittest.main()
