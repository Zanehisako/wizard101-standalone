import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compare_performance import compare_performance
import test_comparison
from prepare_comparison import launch


class PerformanceTests(unittest.TestCase):
    def fixture(self, root, screen=False, queue=False):
        manifest = test_comparison.ComparisonTests().fixture(root)
        manifest['comparison'] = 'queue' if queue else 'pipeline'
        manifest['candidate_mode'] = 'both'
        for directory in root.iterdir():
            path = directory/'session.json'; session = json.loads(path.read_text())
            candidate = 'candidate' in directory.name or directory.name == 'persistence'
            session.update(warmup_requested=True, pipeline_optimization='off' if queue or not candidate else 'both',
                           synchronous_queue_submits='0' if queue and candidate else '1', async_=False)
            session['async'] = session.pop('async_')
            path.write_text(json.dumps(session))
            if not candidate:
                timing = directory/'timing.csv'
                timing.write_text(timing.read_text().replace('event,start_us,duration_us,thread,shader_ids,coverage\n',
                    'event,start_us,duration_us,thread,shader_ids,coverage\nshader_warmup_startup_wait,0,100000,1,,\n'))
        if screen:
            manifest['pairs'] = manifest['pairs'][:1]; manifest.pop('persistence')
            for mode in ('baseline','candidate'):
                directory = root/f'pair1-{mode}'
                session = json.loads((directory/'session.json').read_text()); session['comparison_label'] = f'screen-{mode}'
                (directory/'session.json').write_text(json.dumps(session))
                manifest['pairs'][0][mode].pop('after_restart')
        return manifest

    def test_screen_never_allows_rollout(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); manifest=self.fixture(root, screen=True)
            result=compare_performance(manifest,root,screen=True)
            self.assertTrue(result['screen_improved'],result['issues'])
            self.assertFalse(result['eligible_for_rollout'])

    def test_three_pairs_require_live_acceptance_and_persistence(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); manifest=self.fixture(root)
            result=compare_performance(manifest,root)
            self.assertTrue(result['eligible_for_rollout'],result['issues'])
            manifest['graphics_accepted']=False; manifest.pop('persistence')
            self.assertFalse(compare_performance(manifest,root)['eligible_for_rollout'])

    def test_unequal_warmup_and_mixed_experiment_fail(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); manifest=self.fixture(root,screen=True)
            path=root/'pair1-baseline/session.json'; session=json.loads(path.read_text())
            session.update(warmup_requested=False,synchronous_queue_submits='0'); path.write_text(json.dumps(session))
            result=compare_performance(manifest,root,screen=True)
            self.assertFalse(result['screen_improved'])
            self.assertTrue(any('warm-up' in issue for issue in result['issues']))
            self.assertTrue(any('queue' in issue for issue in result['issues']))

    def test_queue_experiment_keeps_pipeline_off(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); manifest=self.fixture(root,screen=True,queue=True)
            self.assertTrue(compare_performance(manifest,root,screen=True)['screen_improved'])
            path=root/'pair1-candidate/session.json'; session=json.loads(path.read_text())
            session['pipeline_optimization']='both'; path.write_text(json.dumps(session))
            self.assertFalse(compare_performance(manifest,root,screen=True)['screen_improved'])

    def test_lost_presentations_and_p99_regression_fail(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); manifest=self.fixture(root,screen=True)
            path=root/'pair1-candidate/timing.csv'
            path.write_text(path.read_text().replace('# dropped_presentations=0','# dropped_presentations=1'))
            self.assertFalse(compare_performance(manifest,root,screen=True)['screen_improved'])
            lines=[]
            for line in path.read_text().replace('# dropped_presentations=1','# dropped_presentations=0').splitlines():
                if line.startswith('presentation,'):
                    fields=line.split(','); fields[1]=str(1_000_000+int((int(fields[1])-1_000_000)*1.2)); line=','.join(fields)
                lines.append(line)
            path.write_text('\n'.join(lines)+'\n')
            self.assertFalse(compare_performance(manifest,root,screen=True)['screen_improved'])

    def test_cpu_savings_do_not_pass_a_stutter_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); manifest=self.fixture(root,screen=True)
            manifest['cpu_savings']={'measured_cpu_seconds_saved':1.2}
            for phase,sample in manifest['pairs'][0]['candidate'].items():
                path=root/sample['capture']; baseline=root/manifest['pairs'][0]['baseline'][phase]['capture']
                path.write_text(baseline.read_text())
            result=compare_performance(manifest,root,screen=True)
            self.assertFalse(result['screen_improved']); self.assertEqual(result['cpu_savings'],manifest['cpu_savings'])

    def test_expansion_requires_improved_screen(self):
        with tempfile.TemporaryDirectory() as temp:
            work=Path(temp).resolve()/'Comparison'; app=Path(temp).resolve()/'Performance.app'
            from prepare_comparison import GAME, sha
            game=work/'Data'/GAME/'Bin'; renderer=app/'Contents/Resources/Renderer'; game.mkdir(parents=True); renderer.mkdir(parents=True)
            (game/'WizardGraphicalClient.exe').write_bytes(b'synthetic'); (game/'d3d9.dll').write_bytes(b'renderer'); (renderer/'d3d9.dll').write_bytes(b'renderer')
            (work/'comparison.json').write_text(json.dumps(dict(source='separate',renderer_sha256=sha(game/'d3d9.dll'),performance_build={},
                launches=[{'label':'screen-baseline'},{'label':'screen-candidate'}])))
            # A nonempty provenance object is required for the candidate.
            meta=json.loads((work/'comparison.json').read_text()); meta['performance_build']={'default_mode':'off'}
            (work/'comparison.json').write_text(json.dumps(meta))
            with patch('prepare_comparison.require_closed'), patch('prepare_comparison.subprocess.Popen') as popen:
                with self.assertRaisesRegex(RuntimeError,'improved screening'):
                    launch(work,app,'on','pair1-baseline','off','1','pipeline')
                popen.assert_not_called()

    def test_diagnostic_queue_trial_cannot_pass_as_scored_screen(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); manifest=self.fixture(root,screen=True,queue=True)
            path=root/'pair1-candidate/session.json'; session=json.loads(path.read_text())
            session.update(comparison_label='diagnostic',seed_restored=False,handoff_inputs_verified=False)
            path.write_text(json.dumps(session))
            result=compare_performance(manifest,root,screen=True)
            self.assertFalse(result['screen_improved'])
            self.assertFalse(result['eligible_for_rollout'])


class OrdinaryQueueTrialTests(unittest.TestCase):
    def fixture(self, root):
        from prepare_comparison import GAME, CACHES, sha
        work=root/'Comparison'; app=root/'Performance.app'
        game=work/'Data'/GAME/'Bin'; renderer=app/'Contents/Resources/Renderer'
        game.mkdir(parents=True); renderer.mkdir(parents=True)
        (game/'WizardGraphicalClient.exe').write_bytes(b'synthetic')
        (game/'d3d9.dll').write_bytes(b'renderer'); (renderer/'d3d9.dll').write_bytes(b'renderer')
        (game/'config.xml').write_bytes(b'preserved graphics settings')
        catalog=work/'Data'/CACHES[0]/'Wizard101/catalog-v1.w101shaders'
        catalog.parent.mkdir(parents=True); catalog.write_bytes(b'newly learned shaders')
        (work/'comparison.json').write_text(json.dumps(dict(source='separate',renderer_sha256=sha(game/'d3d9.dll'),
            performance_build={'default_mode':'off'},launches=[])))
        return work,app,catalog

    def test_trial_preserves_learned_cache_and_is_explicitly_unscored(self):
        with tempfile.TemporaryDirectory() as temp:
            work,app,catalog=self.fixture(Path(temp).resolve())
            with patch('prepare_comparison.require_closed'), patch('prepare_comparison.subprocess.Popen') as popen:
                launch(work,app,'on','diagnostic','off','0','queue',ordinary_play=True)
            self.assertEqual(catalog.read_bytes(),b'newly learned shaders')
            self.assertFalse((work/'Seed').exists())
            env=popen.call_args.kwargs['env']
            self.assertEqual(env['MVK_CONFIG_SYNCHRONOUS_QUEUE_SUBMITS'],'0')
            self.assertEqual(env['DXVK_W101_PIPELINE_OPT'],'off')
            self.assertEqual(env['W101_WARMUP_SELECTION'],'1')
            recorded=json.loads((work/'comparison.json').read_text())['launches'][0]
            self.assertTrue(recorded['ordinary_play_trial'])
            self.assertFalse(recorded['eligible_for_rollout'])
            self.assertFalse(recorded['seed_restored'])
            self.assertEqual(recorded['route'],'ordinary play')

    def test_ordinary_flag_cannot_bypass_scored_order_or_mix_experiments(self):
        with tempfile.TemporaryDirectory() as temp:
            work,app,_=self.fixture(Path(temp).resolve())
            original=(work/'comparison.json').read_bytes()
            cases=[('on','screen-candidate','off','0','queue'),('on','pair1-candidate','off','0','queue'),
                   ('on','diagnostic','both','0','queue'),('off','diagnostic','off','0','queue'),
                   ('on','diagnostic','off','0','pipeline')]
            with patch('prepare_comparison.require_closed'), patch('prepare_comparison.subprocess.Popen') as popen:
                for args in cases:
                    with self.subTest(args=args), self.assertRaises(RuntimeError):
                        launch(work,app,*args,ordinary_play=True)
                popen.assert_not_called()
            self.assertEqual((work/'comparison.json').read_bytes(),original)

    def test_default_launch_still_requires_queue_baseline_first(self):
        with tempfile.TemporaryDirectory() as temp:
            work,app,_=self.fixture(Path(temp).resolve())
            with patch('prepare_comparison.require_closed'), patch('prepare_comparison.subprocess.Popen') as popen:
                with self.assertRaisesRegex(RuntimeError,'Next controlled launch must be screen-baseline'):
                    launch(work,app,'on','screen-candidate','off','0','queue')
                popen.assert_not_called()


if __name__=='__main__': unittest.main()
