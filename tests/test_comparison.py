import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from compare_first_use import compare, PHASES


class ComparisonTests(unittest.TestCase):
    def fixture(self, root):
        from prepare_comparison import ROUTE, expected_labels
        from datetime import datetime, timedelta, timezone
        pairs={str(i):dict(id=str(i),baseline={},candidate={}) for i in range(1,4)}
        for index,label in enumerate(expected_labels()):
            directory=root/label; directory.mkdir()
            candidate='candidate' in label or label=='persistence'
            spikes=2 if candidate else 6
            lines=['# schema_version=2','# clock_sync={"relative_us":0,"unix_us":1,"uncertainty_us":1}',
                   'event,start_us,duration_us,thread,shader_ids,coverage']
            if candidate:
                lines.append('shader_warmup_startup_wait,0,100000,1,,')
                lines.append('shader_translation,0,1,2,v,restored')
            timestamp=1_000_000
            for i in range(2200):
                lines.append(f'presentation,{timestamp},1,1,,')
                timestamp+=60000 if i < spikes or 1200 <= i < 1200+spikes else 16667
            lines+=['# dropped_events=0','# dropped_presentations=0','# dropped_category_pipeline=0','# dropped_category_shader=0']
            (directory/'timing.csv').write_text('\n'.join(lines)+'\n')
            session=dict(warmup_requested=candidate,frame_rate='capped',limiter='legacy',profiling_requested=True,
                         settings_sha256='s'*64,starting_cache_sha256='c'*64,renderer_sha256='r'*64,
                         seed_sha256='a'*64,starting_inputs_sha256='a'*64,seed_restored=label!='persistence',
                         heavyweight_trace=False,handoff_inputs_verified=True,comparison_label=label,persistence_restart=label=='persistence',
                         started_at=(datetime(2026,10,2,tzinfo=timezone.utc)+timedelta(minutes=index)).isoformat())
            (directory/'session.json').write_text(json.dumps(session))
            if label=='persistence': continue
            pair,mode,*suffix=label.split('-'); ident=pair[-1]
            for phase in (('after_restart',) if suffix else ('first_arrival','immediate_revisit')):
                start=21_300_000 if phase=='immediate_revisit' else 1_000_000
                pairs[ident][mode][phase]=dict(capture=f'{label}/timing.csv',start_us=start,end_us=start+15_500_000,
                    route=ROUTE,activity='movement',settings_sha256='s'*64,starting_cache_sha256='c'*64,
                    seed_sha256='a'*64,starting_inputs_sha256='a'*64)
        return dict(diagnosis='compilation',movement_and_combat_accepted=True,graphics_accepted=True,
                    pairs=list(pairs.values()),persistence={'capture':'persistence/timing.csv'})

    def test_evaluates_three_matched_pairs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); manifest = self.fixture(root)
            result = compare(manifest, root)
            self.assertTrue(result['eligible_for_rollout'], result['issues'])
            self.assertEqual(result['first_arrival_above_50ms'], {'baseline':18, 'candidate':6})

    def test_missing_acceptance_or_different_cache_cannot_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); manifest = self.fixture(root)
            manifest['movement_and_combat_accepted'] = False
            manifest['pairs'][0]['candidate']['first_arrival']['starting_cache_sha256'] = 'different'
            result = compare(manifest, root)
            self.assertFalse(result['eligible_for_rollout'])
            self.assertTrue(any('starting_cache' in issue for issue in result['issues']))

    def test_trace_sessions_and_reused_windows_cannot_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); manifest=self.fixture(root)
            path=root/'pair1-candidate/session.json'; session=json.loads(path.read_text()); session['heavyweight_trace']=True
            path.write_text(json.dumps(session))
            manifest['pairs'][0]['candidate']['immediate_revisit']=copy.deepcopy(manifest['pairs'][0]['candidate']['first_arrival'])
            result=compare(manifest,root)
            self.assertFalse(result['eligible_for_rollout'])
            self.assertTrue(any('reused' in issue for issue in result['issues']))
            self.assertTrue(any('trace' in issue for issue in result['issues']))

    def test_missing_persistence_and_changed_archives_cannot_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); manifest=self.fixture(root); manifest.pop('persistence')
            manifest['pairs'][0]['baseline']['first_arrival']['starting_inputs_sha256']='changed'
            result=compare(manifest,root)
            self.assertFalse(result['eligible_for_rollout'])
            self.assertTrue(any('restart' in issue for issue in result['issues']))
            self.assertTrue(any('starting_inputs' in issue for issue in result['issues']))

    def test_asset_diagnosis_stops_compilation_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); manifest = self.fixture(root); manifest['diagnosis'] = 'asset_loading'
            result = compare(manifest, root)
            self.assertFalse(result['eligible_for_rollout'])
            self.assertTrue(result['stop_compilation_candidate'])

    def test_dropped_presentations_cannot_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); manifest = self.fixture(root)
            path = root/'pair1-candidate/timing.csv'; path.write_text(path.read_text().replace('dropped_presentations=0','dropped_presentations=1'))
            self.assertFalse(compare(manifest, root)['eligible_for_rollout'])


if __name__ == '__main__': unittest.main()
