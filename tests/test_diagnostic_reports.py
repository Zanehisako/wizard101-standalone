import sys
import unittest
import tempfile
import json
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from read_diagnostic_report import summarize, load_report


class DiagnosticReportTests(unittest.TestCase):
    def test_build15_missing_facts_are_unavailable(self):
        report = summarize({'schema': 2, 'app_build': '15', 'content_readiness': {'status': 'ready'}})
        self.assertEqual(report['app_build'], '15')
        self.assertEqual(report['launch_content_mode'], 'unavailable')
        self.assertEqual(report['transfer_observations'], 'unavailable')
        self.assertEqual(report['primary_preload_failure']['received_bytes'], 'unavailable')

    def test_schema1_remains_readable(self):
        self.assertEqual(summarize({'schema': 1})['report_schema'], 1)

    def test_build16_retains_real_zero_and_failure_details(self):
        failure = {'archive': {'path': 'Data/GameData/Novus-WorldData.wad'}, 'revision': 'r123.Test',
                   'verification': 'notPerformed', 'transfer': {'receivedBytes': 0, 'httpStatus': 404, 'outcome': 'http'}}
        report = summarize({'schema': 3, 'launch_content_mode': 'streaming_once', 'patch': {'latestFailure': failure},
                            'archive_verification': {'archives': [{'archive': 'Novus-WorldData.wad', 'installed': {'status': 'valid_streamed_header'}}]}})
        self.assertEqual(report['primary_preload_failure']['received_bytes'], 0)
        self.assertEqual(report['primary_preload_failure']['http_status'], 404)
        self.assertEqual(report['primary_preload_failure']['network_code'], 'unavailable')
        self.assertEqual(report['archive_statuses'][0]['installed'], 'valid_streamed_header')
        self.assertEqual(report['launch_content_mode'], 'streaming_once')

    def test_unknown_schema_is_rejected(self):
        with self.assertRaises(ValueError):
            summarize({'schema': 999})

    def test_shareable_zip_is_read_without_extracting(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'report.zip'
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('Wizard101 Diagnostics/Diagnostic-Report.json', json.dumps({'schema': 3, 'app_build': '16'}))
                archive.writestr('Wizard101 Diagnostics/README.txt', 'Attach this ZIP.')
            self.assertEqual(summarize(load_report(path))['app_build'], '16')

    def test_zip_without_diagnostic_json_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'report.zip'
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('../unrelated.json', '{}')
            with self.assertRaisesRegex(ValueError, 'Expected one diagnostic JSON'):
                load_report(path)


if __name__ == '__main__':
    unittest.main()
