import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from publish_beta import publish


class BetaPublicationTests(unittest.TestCase):
    def report(self):
        return dict(community_beta_ready=False, public_release_ready=False,
                    live_evidence_verified=False, beta_pending_gates=['native_login'],
                    account_qualification_pending=['steam_continued_play'],
                    blocked_on=['community beta live qualification'])

    def test_experimental_release_retains_every_pending_gate(self):
        report = self.report()
        original = copy.deepcopy(report)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / 'COMMUNITY-BETA.md').write_text('Steam remains experimental.\n')
            with patch('publish_beta.verify', return_value=report) as verify, \
                 patch('publish_beta.subprocess.check_output', return_value='[]'), \
                 patch('publish_beta.subprocess.run') as run:
                publish(root, None, 'owner/repo', 'vtest', 'source-commit', experimental=True)
            verify.assert_called_once_with(root, None, require_live=False)
            saved = json.loads((root / 'RELEASE-STATUS.json').read_text())
            self.assertEqual(saved, original | dict(experimental_release=True))
            calls = [call.args[0] for call in run.call_args_list]
            self.assertIn('--draft', calls[0])
            self.assertIn('--prerelease', calls[0])
            self.assertIn('Experimental Steam Beta', ' '.join(calls[0]))
            self.assertIn('--draft=false', calls[-1])
            self.assertTrue((root / 'SHA256SUMS.txt').is_file())

    def test_qualified_publication_still_requires_live_evidence(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch('publish_beta.verify', side_effect=ValueError('Unverified community beta gates')) as verify, \
             patch('publish_beta.subprocess.run') as run:
            with self.assertRaisesRegex(ValueError, 'Unverified'):
                publish(tmp, None, 'owner/repo', 'vtest', 'source-commit')
            verify.assert_called_once_with(Path(tmp).resolve(), None, require_live=True)
            run.assert_not_called()

    def test_existing_public_release_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch('publish_beta.verify', return_value=self.report()), \
             patch('publish_beta.subprocess.check_output', return_value='[{"tagName":"vtest","isDraft":false}]'), \
             patch('publish_beta.subprocess.run') as run:
            with self.assertRaisesRegex(ValueError, 'overwrite'):
                publish(tmp, None, 'owner/repo', 'vtest', 'source-commit', experimental=True)
            run.assert_not_called()

    def test_experimental_mode_cannot_relabel_qualified_evidence(self):
        report = self.report() | dict(live_evidence_verified=True)
        with tempfile.TemporaryDirectory() as tmp, \
             patch('publish_beta.verify', return_value=report), \
             patch('publish_beta.subprocess.check_output', return_value='[]'), \
             patch('publish_beta.subprocess.run') as run:
            with self.assertRaisesRegex(ValueError, 'pending live qualification'):
                publish(tmp, None, 'owner/repo', 'vtest', 'source-commit', experimental=True)
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
