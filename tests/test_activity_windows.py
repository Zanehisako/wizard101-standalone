import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from annotate_window import latest_sync, relative_us
from profile_report import report


class ActivityTests(unittest.TestCase):
    def test_loading_gap_is_excluded_and_p99_pools_actual_frames(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'capture.csv'
            rows=['event,start_us,duration_us,thread']
            for start,step in [(1_000_000,16_667),(5_000_000,20_000)]:
                rows += [f'presentation,{start+i*step},1,1' for i in range(101)]
            rows += ['# dropped_events=0','# dropped_presentations=0']
            path.write_text('\n'.join(rows)+'\n')
            windows=[{'start_us':1_000_000,'end_us':2_666_700,'zone':'Ravenwood'},
                     {'start_us':5_000_000,'end_us':7_000_000,'zone':'Commons'}]
            result=report(path,windows=windows)
            self.assertEqual(result['frame_interval_count'],200)
            self.assertEqual(result['frame_intervals_above_ms']['50'],0)
            self.assertEqual(result['frame_interval_percentiles_ms']['99'],20)
            self.assertAlmostEqual(result['coverage_seconds'],3.6667)
            self.assertEqual(len(result['activity_window_summaries']),2)
            self.assertEqual(result['hitches_over_50ms'],[])
            self.assertEqual(result['window_us'],{'start':1_000_000,'end':7_000_000})

    def test_empty_or_overlapping_activity_windows_are_rejected(self):
        with self.assertRaises(ValueError): report('/unused',windows=[])
        with self.assertRaises(ValueError): report('/unused',windows=[{'start_us':0,'end_us':100},{'start_us':50,'end_us':150}])

    def test_tail_marker_handles_large_capture_and_incomplete_clock_line(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'capture.csv'
            marker={'unix_us':1_000_000,'relative_us':500_000,'uncertainty_us':5}
            path.write_bytes(b'x'*2_000_000+b'\n# clock_sync='+json.dumps(marker).encode()+b'\n'+b'x'*70_000+b'\n# clock_sync={')
            self.assertEqual(latest_sync(path),marker)
            with patch('annotate_window.time.time_ns',return_value=1_001_000_000):
                self.assertEqual(relative_us(path),(501_000,5))
            with patch('annotate_window.time.time_ns',return_value=5_000_000_000):
                with self.assertRaisesRegex(RuntimeError,'stale'): relative_us(path)


if __name__=='__main__': unittest.main()
