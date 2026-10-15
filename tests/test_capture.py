import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from prepare_comparison import GAME, CACHES, seed, restore, sha, expected_labels
from profile_report import report
from diagnose_hitches import diagnose
from capture_trace import record, require_space

class CaptureTests(unittest.TestCase):
    def test_old_report_remains_readable(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'timing.csv'; f.write_text('event,thread,start_us,duration_us\npresentation,1,0,1\npresentation,1,60000,1\n# dropped_events=2\n')
            r=report(f)
            self.assertEqual(r['schema_version'],1)
            self.assertIsNone(r['dropped_by_category'])
            self.assertEqual(r['hitches_over_50ms'][0]['classification'],'inconclusive')

    def test_schema_two_keeps_identity_clock_and_global_aggregates(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'timing.csv'
            f.write_text('# schema_version=2\n# clock_sync={"unix_us":1000,"relative_us":0,"uncertainty_us":3}\n'
                         'event,thread,start_us,duration_us,pipeline_id,shader_ids,coverage,role\n'
                         'presentation,1,0,1,,,,\ngraphics_pipeline_foreground_lock_wait,2,1000,59000,p,v;p,restored;new,foreground\n'
                         'presentation,1,60000,1,,,,\n# dropped_events=0\n# dropped_presentations=0\n'
                         '# dropped_category_pipeline=0\n# aggregate_game_read_file={"count":123,"total_us":246,"max_us":2}\n')
            r=report(f,0,60000)
            self.assertEqual(r['shader_coverage']['restored'],['v'])
            self.assertEqual(r['shader_coverage']['new'],['p'])
            self.assertEqual(r['clock_sync'][0]['unix_us'],1000)
            self.assertEqual(r['aggregated_events']['game_read_file']['count'],123)
            self.assertEqual(r['hitches_over_50ms'][0]['overlapping_cpu_events'][0]['pipeline_id'],'p')

    def test_overlap_cannot_classify_hitch(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); f=root/'timing.csv'
            f.write_text('event,thread,start_us,duration_us\npresentation,1,0,1\ngraphics_pipeline_compile,2,1,59000\npresentation,1,60000,1\n# dropped_events=0\n')
            r=diagnose({'windows':[{'capture':f.name,'start_us':0,'end_us':60000,'activity':'movement'}]},root)
            self.assertEqual(r['hitches'][0]['classification'],'inconclusive')
            self.assertFalse(r['expand_preparation_supported'])

    @unittest.skipUnless(sys.platform=='darwin','APFS/macOS clone and immutable flags')
    def test_seed_restores_archives_tracking_cache_and_settings(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve(); work=root/'work'; data=work/'Data'; bin=data/GAME/'Bin'; bin.mkdir(parents=True)
            (bin/'WizardGraphicalClient.exe').write_bytes(b'game')
            (work/'comparison.json').write_text(json.dumps({'source':str(root/'original')}))
            files={CACHES[0]/'Wizard101/catalog-v1.w101shaders':b'catalog',CACHES[1]:b'pipeline',
                   GAME/'Data/a.wad':b'archive',GAME/'Data/a.wad.utd':b'tracking',GAME/'Bin/x.utd':b'outside',
                   GAME/'Bin/config.xml':b'settings'}
            for path,contents in files.items():
                (data/path).parent.mkdir(parents=True,exist_ok=True); (data/path).write_bytes(contents)
            with patch('prepare_comparison.require_closed'):
                m=seed(work)
                try:
                    for path in files: (data/path).write_bytes(b'mutated')
                    (data/GAME/'Data/new.wad').write_bytes(b'new')
                    (data/GAME/'Bin/new.utd').write_bytes(b'new tracking')
                    (data/GAME/'Data/a.wad.utd').unlink()
                    self.assertEqual(restore(work),m['seed_sha256'])
                    self.assertFalse((data/GAME/'Data/new.wad').exists())
                    self.assertFalse((data/GAME/'Bin/new.utd').exists())
                    for path,contents in files.items(): self.assertEqual((data/path).read_bytes(),contents)
                    self.assertFalse((data/GAME/'Data/a.wad').stat().st_flags & 2)
                    self.assertEqual((work/'Seed'/GAME/'Data/a.wad').read_bytes(),b'archive')
                finally:
                    subprocess.run(['chflags','-R','nouchg',str(work/'Seed')],check=True)
                    for p in [work/'Seed',*(work/'Seed').rglob('*')]: p.chmod(0o755 if p.is_dir() else 0o644)

    def test_alternating_order_includes_persistence(self):
        labels=expected_labels()
        self.assertEqual(labels[:4],['pair1-baseline','pair1-baseline-restart','pair1-candidate','pair1-candidate-restart'])
        self.assertEqual(labels[4],'pair2-candidate')
        self.assertEqual(labels[-1],'persistence')

    def test_trace_capture_rejects_scored_game(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); capture=root/'timing.csv'
            (root/'session.json').write_text(json.dumps({'comparison_label':'pair1-candidate','heavyweight_trace':False}))
            with patch('capture_trace.subprocess.run') as runner:
                with self.assertRaises(RuntimeError): record('cpu',123,capture,root/'cpu.trace')
                runner.assert_not_called()

    def test_low_space_blocks_gpu_recording(self):
        import shutil
        with tempfile.TemporaryDirectory() as d:
            # Less than the observed Metal finalization footprint must block,
            # even when there is ample room for a CPU recording.
            usage=shutil._ntuple_diskusage(20*1024**3,12*1024**3,8*1024**3)
            with patch('capture_trace.shutil.disk_usage',return_value=usage):
                with self.assertRaisesRegex(RuntimeError,'No recording started'):
                    require_space('gpu',Path(d)/'gpu.trace')
                require_space('cpu',Path(d)/'cpu.trace')

    def test_asset_blocking_evidence_stops_warmup_but_missing_thread_is_inconclusive(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); capture=root/'timing.csv'
            capture.write_text('# schema_version=2\n# clock_sync={"unix_us":1000000,"relative_us":0,"uncertainty_us":1}\n'
                'event,thread,start_us,duration_us\npresentation,1,0,1\ngame_read_file,2,1,59000\npresentation,1,60000,1\n'
                '# dropped_events=0\n# dropped_presentations=0\n')
            traces={}
            for kind in ('cpu','gpu'):
                (root/(kind+'.trace')).mkdir()
                (root/(kind+'.json')).write_text(json.dumps({'completed':True,'scored':False,'usable_for_movement_diagnosis':True,'kind':kind,'capture':str(capture)}))
                traces[kind]=kind+'.json'
            evidence=dict(hitch_start_us=0,cause='asset_loading',cpu_trace='cpu',gpu_trace='gpu',blocking_thread='main',
                native_thread_mapping='Windows 1 corresponds to native main thread',cpu_stack='game ReadFile stack',
                gpu_observation='GPU idle while main thread blocked',trace_time_range='1.0s to 1.06s',activity='movement')
            manifest={'traces':traces,'windows':[dict(capture=capture.name,start_us=0,end_us=60000,activity='movement',evidence=[evidence])]}
            self.assertTrue(diagnose(manifest,root)['stop_further_warmup'])
            trace_path=root/'cpu.json'
            trace_metadata=json.loads(trace_path.read_text()); trace_metadata['usable_for_movement_diagnosis']=False
            trace_path.write_text(json.dumps(trace_metadata))
            self.assertFalse(diagnose(manifest,root)['stop_further_warmup'])
            trace_metadata['usable_for_movement_diagnosis']=True; trace_path.write_text(json.dumps(trace_metadata))
            evidence.pop('native_thread_mapping')
            result=diagnose(manifest,root)
            self.assertFalse(result['stop_further_warmup'])
            self.assertEqual(result['hitches'][0]['classification'],'inconclusive')

if __name__=='__main__': unittest.main()
