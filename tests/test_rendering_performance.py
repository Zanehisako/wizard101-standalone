import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from compare_performance import compare_performance
from prepare_comparison import launch
import test_performance

class RenderingPerformanceTests(unittest.TestCase):
    def fixture(self, root, screen=False):
        manifest=test_performance.PerformanceTests().fixture(root,screen=screen)
        manifest.update(comparison='rendering',candidate_mode='1')
        for directory in root.iterdir():
            path=directory/'session.json'; session=json.loads(path.read_text())
            session.update(pipeline_optimization='off',cpu_optimization='off',
                           stutter_fix='candidate' in directory.name or directory.name=='persistence')
            path.write_text(json.dumps(session))
        return manifest

    def test_rollout_requires_three_pairs_and_visual_control_confirmation(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); manifest=self.fixture(root)
            result=compare_performance(manifest,root)
            self.assertTrue(result['eligible_for_rollout'],result['issues'])
            manifest['graphics_accepted']=False
            self.assertFalse(compare_performance(manifest,root)['eligible_for_rollout'])
            manifest['graphics_accepted']=True; manifest['movement_and_combat_accepted']=False
            self.assertFalse(compare_performance(manifest,root)['eligible_for_rollout'])

    def test_screen_cannot_replace_working_app_and_rejects_mixed_modes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); manifest=self.fixture(root,screen=True)
            result=compare_performance(manifest,root,screen=True)
            self.assertTrue(result['screen_improved'],result['issues'])
            self.assertFalse(result['eligible_for_rollout'])
            path=root/'pair1-candidate/session.json'; initial=json.loads(path.read_text())
            for update in ({'stutter_fix':False},{'stutter_fix':'1'},{'cpu_optimization':'both'},{'pipeline_optimization':'both'}):
                path.write_text(json.dumps(dict(initial,**update)))
                self.assertFalse(compare_performance(manifest,root,screen=True)['screen_improved'])

    def test_equal_long_frames_and_p99_regression_reject_improvement(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); manifest=self.fixture(root,screen=True)
            for phase,sample in manifest['pairs'][0]['candidate'].items():
                path=root/sample['capture']; baseline=root/manifest['pairs'][0]['baseline'][phase]['capture']
                path.write_text(baseline.read_text())
            result=compare_performance(manifest,root,screen=True)
            self.assertFalse(result['screen_improved'])
            self.assertTrue(any('No reduction' in issue for issue in result['issues']))
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); manifest=self.fixture(root,screen=True)
            path=root/'pair1-candidate/timing.csv'; lines=[]
            for line in path.read_text().splitlines():
                if line.startswith('presentation,'):
                    fields=line.split(','); fields[1]=str(1_000_000+int((int(fields[1])-1_000_000)*1.2)); line=','.join(fields)
                lines.append(line)
            path.write_text('\n'.join(lines)+'\n')
            result=compare_performance(manifest,root,screen=True)
            self.assertFalse(result['screen_improved'])
            self.assertTrue(any('p99 regressed' in issue for issue in result['issues']))

    def test_trial_preserves_inputs_and_scored_modes_cannot_be_bypassed(self):
        with tempfile.TemporaryDirectory() as temp:
            work,app,catalog=test_performance.OrdinaryQueueTrialTests().fixture(Path(temp).resolve())
            path=work/'comparison.json'; meta=json.loads(path.read_text()); meta['rendering_build']={'default_mode':'0'};path.write_text(json.dumps(meta))
            original=catalog.read_bytes()
            with patch('prepare_comparison.require_closed'),patch('prepare_comparison.subprocess.Popen') as popen:
                with self.assertRaisesRegex(RuntimeError,'CPU and pipeline'):
                    launch(work,app,'on','diagnostic','off','1','rendering',True,'both','1')
                with self.assertRaisesRegex(RuntimeError,'switch 0 baseline'):
                    launch(work,app,'on','screen-baseline','off','1','rendering',False,'off','1')
                with self.assertRaisesRegex(RuntimeError,'scored labels'):
                    launch(work,app,'on','screen-candidate','off','1','rendering',True,'off','1')
                popen.assert_not_called()
                launch(work,app,'on','diagnostic','off','1','rendering',True,'off','1')
                env=popen.call_args.kwargs['env']
                self.assertEqual(env['DXVK_W101_STUTTER_FIX'],'1')
                self.assertEqual(env['DXVK_W101_CPU_OPT'],'off')
                self.assertEqual(env['DXVK_W101_PIPELINE_OPT'],'off')
                self.assertEqual(env['MVK_CONFIG_SYNCHRONOUS_QUEUE_SUBMITS'],'1')
            self.assertEqual(catalog.read_bytes(),original)
            self.assertFalse(json.loads(path.read_text())['launches'][-1]['eligible_for_rollout'])

if __name__=='__main__': unittest.main()
