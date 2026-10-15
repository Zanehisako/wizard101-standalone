import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from verify_draw_layout_v2 import score
from install_draw_layout import install

class DrawLayoutV2GateTests(unittest.TestCase):
    @staticmethod
    def rows():
        return [dict(pair=i,workload=w,order='on/off' if i%2 else 'off/on',
                     off_cpu_ms=3000,on_cpu_ms=2400 if w=='reuse' else 3030,
                     operations=20000000,fingerprint_preparation_timed=w=='fresh')
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
        rows=self.rows();rows[-1]['fingerprint_preparation_timed']=False
        with self.assertRaises(RuntimeError):score(rows)
    def test_pair_order_duplicates_and_missing_pairs_reject(self):
        for mutate in (lambda r:r.pop(),lambda r:r[1].update(pair=0),lambda r:r[1].update(order='off/on')):
            rows=self.rows();mutate(rows)
            with self.assertRaises(RuntimeError):score(rows)
    def test_failed_v2_gate_cannot_mutate_installation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);work=root/'work';work.mkdir();app=root/'app';app.mkdir();data=root/'data';data.mkdir()
            (app/'keep').write_bytes(b'current app');(data/'keep').write_bytes(b'current game and learned textures')
            (work/'draw-layout-build.json').write_text(json.dumps({'revision':2}))
            rows=self.rows();rows[-1]['on_cpu_ms']=3300
            report=root/'report.json';report.write_text(json.dumps({'install_qualified':True,'benchmark_pairs':rows}))
            before={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
            with self.assertRaisesRegex(RuntimeError,'performance gate failed'):install(work,app,data,root/'launcher',report)
            self.assertEqual(before,{str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()})
            self.assertFalse((root/'Rollback').exists())

if __name__=='__main__':unittest.main()
