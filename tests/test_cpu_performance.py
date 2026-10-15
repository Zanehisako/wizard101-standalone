import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from profile_report import report
from verify_cpu_opt import evaluate
from compare_performance import compare_performance
from prepare_comparison import launch
from test_performance import PerformanceTests, OrdinaryQueueTrialTests

class CpuTests(unittest.TestCase):
    def test_cpu_windows_exclude_partial_and_loading_intervals(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'timing.csv'
            lines=['event,thread,start_us,duration_us']
            for i in range(7): lines.append('# process_cpu_sample='+json.dumps({'relative_us':i*1000000,'cpu_us':i*200000}))
            lines += ['# cpu_counters={"constant_uploads":42,"overflow_calls":0}', '# dropped_events=0']
            path.write_text('\n'.join(lines)+'\n')
            r=report(path,windows=[{'start_us':500000,'end_us':2200000},{'start_us':4000000,'end_us':6000000}])
            self.assertEqual(r['process_cpu']['sample_intervals'],3)
            self.assertEqual(r['process_cpu']['cpu_ms'],600)
            self.assertEqual(r['process_cpu']['cpu_ms_per_second'],200)
            self.assertEqual(r['cpu_counters']['constant_uploads'],42)
            path.write_text(path.read_text()+'# process_cpu_sample={"relative_us":6000100,"cpu_us":1200100}\n')
            self.assertFalse(report(path)['process_cpu']['valid_samples'])

    def test_five_run_medians_and_independent_regression_gates(self):
        runs=[{'mode':m,'workload':w,'cpu_ms':100+(i-2)} for m in ('off','constants','locking','both')
              for w in ('unchanged','changing','recursive','contended') for i in range(5)]
        for r in runs:
            if r['mode'] in ('constants','both') and r['workload']=='unchanged': r['cpu_ms']*=.8
            if r['mode'] in ('locking','both') and r['workload']=='recursive': r['cpu_ms']*=.7
            if r['mode']=='both' and r['workload']=='contended': r['cpu_ms']*=1.06
        r=evaluate(runs)
        self.assertTrue(r['synthetic_qualified']['constants'])
        self.assertTrue(r['synthetic_qualified']['locking'])
        self.assertFalse(r['synthetic_qualified']['both'])
        self.assertEqual(r['ordinary_play_trial_mode'],'constants')

    def test_cpu_comparison_requires_measured_samples_and_preserves_stutter_gate(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); manifest=PerformanceTests().fixture(root,screen=True)
            manifest['comparison']='cpu'; manifest['candidate_mode']='constants'
            for directory in root.iterdir():
                candidate='candidate' in directory.name
                path=directory/'session.json'; s=json.loads(path.read_text())
                s.update(pipeline_optimization='off',cpu_optimization='constants' if candidate else 'off')
                path.write_text(json.dumps(s))
                path=directory/'timing.csv'
                lines=[]
                for i in range(61):
                    lines.append('# process_cpu_sample='+json.dumps({'relative_us':i*1000000,'cpu_us':i*(150000 if candidate else 200000)}))
                lines.append('# cpu_counters={"constant_uploads":42,"overflow_calls":0}')
                path.write_text(path.read_text()+'\n'+'\n'.join(lines)+'\n')
            r=compare_performance(manifest,root,screen=True)
            self.assertTrue(r['screen_improved'],r['issues'])
            self.assertTrue(r['cpu_savings']['matched_inputs_verified'])
            self.assertEqual(r['cpu_savings']['changes_percent'],[-25,-25])
            self.assertFalse(r['eligible_for_rollout'])
            for phase,sample in manifest['pairs'][0]['candidate'].items():
                a=root/manifest['pairs'][0]['baseline'][phase]['capture']; b=root/sample['capture']
                frames=[line for line in a.read_text().splitlines() if line.startswith('presentation,')]
                other=[line for line in b.read_text().splitlines() if not line.startswith('presentation,')]
                b.write_text('\n'.join(other+frames)+'\n')
            r=compare_performance(manifest,root,screen=True)
            self.assertFalse(r['screen_improved'])
            self.assertTrue(r['cpu_savings']['matched_inputs_verified'])

    def test_ordinary_trial_is_unscored_and_rejects_combined_experiments(self):
        with tempfile.TemporaryDirectory() as temp:
            work,app,catalog=OrdinaryQueueTrialTests().fixture(Path(temp).resolve())
            path=work/'comparison.json'; meta=json.loads(path.read_text()); meta['cpu_build']={'default_mode':'off'}; path.write_text(json.dumps(meta))
            before=catalog.read_bytes()
            with patch('prepare_comparison.require_closed'),patch('prepare_comparison.subprocess.Popen') as popen:
                with self.assertRaisesRegex(RuntimeError,'pipeline modes off'):
                    launch(work,app,'on','diagnostic','both','1','cpu',True,'constants')
                popen.assert_not_called()
                launch(work,app,'on','diagnostic','off','1','cpu',True,'constants')
                env=popen.call_args.kwargs['env']; self.assertEqual(env['DXVK_W101_CPU_OPT'],'constants')
                self.assertEqual(env['DXVK_W101_PIPELINE_OPT'],'off')
            self.assertEqual(catalog.read_bytes(),before)
            self.assertFalse(json.loads(path.read_text())['launches'][-1]['eligible_for_rollout'])

if __name__=='__main__': unittest.main()
