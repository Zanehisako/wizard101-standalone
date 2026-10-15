import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from verify_draw_layout import score
from install_draw_layout import install

class DrawLayoutGateTests(unittest.TestCase):
    @staticmethod
    def rows():
        return [dict(pair=i,workload=w,off_cpu_ms=100,on_cpu_ms=80 if w=='reuse' else 101) for i in range(5) for w in ('reuse','cold')]
    def test_gate_requires_savings_and_four_wins(self):
        rows=self.rows();self.assertTrue(score(rows)['gate_passed'])
        for r in rows:
            if r['workload']=='reuse':r['on_cpu_ms']=99
        self.assertFalse(score(rows)['gate_passed'])
        for r in rows:
            if r['workload']=='reuse':r['on_cpu_ms']=80 if r['pair']<3 else 110
        self.assertFalse(score(rows)['gate_passed'])
    def test_single_cold_regression_rejects_even_if_median_passes(self):
        rows=self.rows();rows[1]['on_cpu_ms']=103
        result=score(rows);self.assertLess(result['median_cold_regression_percent'],2);self.assertFalse(result['gate_passed'])
    def test_missing_pairs_are_rejected(self):
        with self.assertRaises(RuntimeError):score(self.rows()[:-1])
    def test_failed_gate_cannot_mutate_installation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);work=root/'work';work.mkdir();app=root/'app';app.mkdir();data=root/'data';data.mkdir()
            (app/'keep').write_bytes(b'current app');(data/'keep').write_bytes(b'current game and learned textures')
            (work/'draw-layout-build.json').write_text('{}')
            rows=self.rows();rows[1]['on_cpu_ms']=200
            report=root/'report.json';report.write_text(json.dumps({'install_qualified':True,'benchmark_pairs':rows}))
            before={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
            with self.assertRaisesRegex(RuntimeError,'performance gate failed'):install(work,app,data,root/'launcher',report)
            after={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
            self.assertEqual(before,after)
            self.assertFalse((root/'Rollback').exists())
if __name__=='__main__':unittest.main()
