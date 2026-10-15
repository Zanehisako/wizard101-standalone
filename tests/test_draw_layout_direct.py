import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from verify_draw_layout_direct import score
from install_draw_layout_direct import install
from install_draw_layout_direct import restore

class DirectDrawLayoutGateTests(unittest.TestCase):
    @staticmethod
    def rows():
        return [dict(pair=i,workload=w,order='on/off' if i%2 else 'off/on',
                     off_cpu_ms=3000,on_cpu_ms=2400 if w=='reuse' else 3030,
                     operations=20000000,stack_preparation_timed=True,fresh_resource_creation_timed=w=='fresh')
                for w in ('reuse','cold','fresh') for i in range(5)]
    def test_valid_measurements_pass(self):
        self.assertTrue(score(self.rows())['gate_passed'])
    def test_median_pair_reduction_and_four_wins(self):
        rows=self.rows()
        for r in rows[:5]:r['on_cpu_ms']=2970
        self.assertFalse(score(rows)['gate_passed'])
        for r in rows[:5]:r['on_cpu_ms']=2400 if r['pair']<3 else 3100
        self.assertFalse(score(rows)['gate_passed'])
    def test_each_cold_and_fresh_pair_is_capped(self):
        for workload in ('cold','fresh'):
            rows=self.rows();next(r for r in rows if r['workload']==workload)['on_cpu_ms']=3090
            self.assertFalse(score(rows)['gate_passed'])
    def test_short_or_invalid_cpu_samples_reject(self):
        for value in (1999,float('inf'),float('nan')):
            rows=self.rows();rows[0]['on_cpu_ms']=value
            with self.assertRaises(RuntimeError):score(rows)
    def test_preparation_cannot_be_hidden(self):
        rows=self.rows();rows[-1]['fresh_resource_creation_timed']=False
        with self.assertRaises(RuntimeError):score(rows)
    def test_every_sample_includes_stack_preparation(self):
        for index in (0,5,10):
            rows=self.rows();rows[index]['stack_preparation_timed']=False
            with self.assertRaises(RuntimeError):score(rows)
    def test_wrong_revision_cannot_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);work=root/'work';work.mkdir()
            (work/'draw-layout-build.json').write_text(json.dumps({'revision':2}))
            report=root/'report.json';report.write_text(json.dumps({'revision':2,'install_qualified':True,'benchmark_pairs':self.rows()}))
            with self.assertRaisesRegex(RuntimeError,'revision 3'):
                install(work,root/'app',root/'data',root/'launcher',report)
    def test_passing_cpu_without_correctness_cannot_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);work=root/'work';work.mkdir()
            (work/'draw-layout-build.json').write_text(json.dumps({'revision':3}))
            report=root/'report.json';report.write_text(json.dumps({'revision':3,'install_qualified':True,'benchmark_pairs':self.rows()}))
            before={str(p):p.read_bytes() for p in root.rglob('*') if p.is_file()}
            with self.assertRaisesRegex(RuntimeError,'correctness verification'):
                install(work,root/'app',root/'data',root/'launcher',report)
            self.assertEqual(before,{str(p):p.read_bytes() for p in root.rglob('*') if p.is_file()})
    def test_pair_order_duplicates_and_missing_pairs_reject(self):
        for mutate in (lambda r:r.pop(),lambda r:r[1].update(pair=0),lambda r:r[1].update(order='off/on')):
            rows=self.rows();mutate(rows)
            with self.assertRaises(RuntimeError):score(rows)
    def test_failed_direct_gate_cannot_mutate_installation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);work=root/'work';work.mkdir();app=root/'app';app.mkdir();data=root/'data';data.mkdir()
            (app/'keep').write_bytes(b'current app');(data/'keep').write_bytes(b'current game and learned textures')
            (work/'draw-layout-build.json').write_text(json.dumps({'revision':3}))
            rows=self.rows();rows[-1]['on_cpu_ms']=3300
            report=root/'report.json';report.write_text(json.dumps({'revision':3,'install_qualified':True,'benchmark_pairs':rows}))
            before={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
            with self.assertRaisesRegex(RuntimeError,'performance gate failed'):install(work,app,data,root/'launcher',report)
            self.assertEqual(before,{str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()})
            self.assertFalse((root/'Rollback').exists())

    def test_signed_launcher_hash_allows_complete_rollback(self):
        import shutil
        import plistlib
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);work=root/'work';work.mkdir();app=root/'app';data=root/'Data';launcher=root/'launcher'
            resources=app/'Contents/Resources';renderer=resources/'Renderer';renderer.mkdir(parents=True)
            binary=app/'Contents/MacOS/Wizard101Native';binary.parent.mkdir();binary.write_bytes(b'old launcher')
            (app/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'org.wizard101native.combined','W101ExperimentDefaults':{'W101_DRAW_LAYOUT_CACHE':'0'}}))
            (renderer/'d3d9.dll').write_bytes(b'old renderer')
            metadataFiles=[renderer/n for n in ['asset-preparation-build.json','workload-performance-build.json','combined-build.json']]
            runtimeMetadata=resources/'Runtime/workload-performance-build.json';runtimeMetadata.parent.mkdir();metadataFiles.append(runtimeMetadata)
            for p in metadataFiles:p.write_text('{}')
            game=data/'Prefix/drive_c/ProgramData/KingsIsle Entertainment/Wizard101/Bin';game.mkdir(parents=True);(game/'d3d9.dll').write_bytes(b'old renderer')
            cache=data/'Prefix/drive_c/graphics-patch-cache/Wizard101/known-assets.w101assets';cache.parent.mkdir(parents=True);cache.write_bytes(b'learned textures')
            candidate=work/'d3d9.dll';candidate.write_bytes(b'new renderer')
            sourceLauncher=launcher/'Contents/MacOS/Wizard101Native';sourceLauncher.parent.mkdir(parents=True);sourceLauncher.write_bytes(b'verified launcher')
            report=root/'report.json';report.write_text('{}')
            from build_runtime import sha
            def sign(args,**kwargs):
                if args[:2]==['codesign','--force']:
                    p=Path(args[-1])/'Contents/MacOS/Wizard101Native';p.write_bytes(p.read_bytes()+b'changed signature')
            with patch('install_draw_layout_direct.idle'),patch('install_draw_layout_direct.clone',side_effect=shutil.copytree),patch('install_draw_layout_direct.subprocess.run',side_effect=sign),patch('install_draw_layout_direct.require_verified',return_value=(candidate,{'baseline_renderer_sha256':sha(game/'d3d9.dll')},{'runtime_inputs':{}})):
                manifest=install(work,app,data,launcher,report)
                self.assertEqual(manifest['installed_launcher_sha256'],sha(binary))
                self.assertNotEqual(sha(binary),sha(sourceLauncher))
                self.assertEqual(cache.read_bytes(),b'learned textures')
                restore(Path(manifest['backup']))
            self.assertEqual(binary.read_bytes(),b'old launcher')
            self.assertEqual((game/'d3d9.dll').read_bytes(),b'old renderer')
            self.assertEqual(cache.read_bytes(),b'learned textures')

if __name__=='__main__':unittest.main()
