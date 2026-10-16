import copy
import json
from pathlib import Path
import plistlib
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from account_qualification import ACCOUNT_GATES, template, validate_accounts, write_account_checks
from install_account_candidate import BUNDLE_ID, replace_app, require_idle
from package_shipping import components


class AccountQualificationTests(unittest.TestCase):
    def evidence(self):
        evidence = template({'launcher': 'candidate'}, 'installer')
        evidence['gates'] = dict.fromkeys(ACCOUNT_GATES, True)
        evidence['observations'] = dict.fromkeys(ACCOUNT_GATES, 'Observed locally on the candidate')
        return evidence

    def test_both_providers_need_live_passes_and_observations(self):
        complete = self.evidence()
        validate_accounts(complete, complete['components'], 'installer')
        for gate in ACCOUNT_GATES:
            for value in [False, None, 1, 'true']:
                evidence = copy.deepcopy(complete); evidence['gates'][gate] = value
                with self.assertRaisesRegex(ValueError, 'Unverified US / Steam'):
                    validate_accounts(evidence, complete['components'], 'installer')
            evidence = copy.deepcopy(complete); evidence['observations'][gate] = ' '
            with self.assertRaisesRegex(ValueError, 'observation'):
                validate_accounts(evidence, complete['components'], 'installer')

    def test_previous_beta_or_changed_artifacts_cannot_authorize_replacement(self):
        evidence = self.evidence()
        for hashes, installer in [({'launcher': 'old-beta'}, 'installer'), (evidence['components'], 'old-installer')]:
            with self.assertRaisesRegex(ValueError, 'exactly'):
                validate_accounts(evidence, hashes, installer)
        evidence['gates'] = {'native_login': True, 'character_selection': True, 'self_tests': True}
        with self.assertRaisesRegex(ValueError, 'Unverified US / Steam'):
            validate_accounts(evidence, evidence['components'], 'installer')

    def test_offline_checklist_is_unqualified_and_json_is_inert(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_account_checks(tmp, {'</script>': '&'}, 'installer')
            evidence = json.loads((Path(tmp) / 'ACCOUNT-LIVE-TEMPLATE.json').read_text())
            self.assertEqual(set(evidence['gates']), set(ACCOUNT_GATES))
            self.assertFalse(any(evidence['gates'].values()))
            page = (Path(tmp) / 'ACCOUNT-LIVE-CHECKS.html').read_text()
            self.assertNotIn('"</script>"', page)
            self.assertNotIn('__W101_CHECK_DATA__', page)
            self.assertIn('Wizard101-Account-Live-Results.json', page)

    def test_running_game_or_launcher_prevents_replacement(self):
        for process in ['WizardGraphicalClient.exe', '/Applications/Wizard101 Standalone.app/Contents/MacOS/Wizard101Native']:
            with patch('install_account_candidate.subprocess.check_output', return_value=process):
                with self.assertRaisesRegex(ValueError, 'Close Wizard101'): require_idle()

    def app(self, path, contents):
        (path / 'Contents/MacOS').mkdir(parents=True)
        (path / 'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': BUNDLE_ID}))
        (path / 'Contents/MacOS/Wizard101Native').write_text(contents)
        return path

    @patch('install_account_candidate.verify_signature')
    @patch('install_account_candidate.require_idle')
    def test_replacement_retains_previous_app_and_rejects_changed_candidate(self, idle, signature):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.app(root / 'Candidate.app', 'candidate')
            target = self.app(root / 'Installed.app', 'previous')
            expected, previous = components(source), components(target)
            with self.assertRaisesRegex(ValueError, 'changed after qualification'):
                replace_app(source, target, {})
            self.assertEqual(components(target), previous)
            backup = replace_app(source, target, expected)
            self.assertEqual(components(target), expected)
            self.assertEqual(components(source), expected)
            self.assertEqual(components(backup), previous)
            self.assertFalse(list(root.glob('.Wizard101-account-stage-*')))

    @patch('install_account_candidate.verify_signature')
    @patch('install_account_candidate.require_idle')
    def test_failed_activation_restores_previous_app(self, idle, signature):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.app(root / 'Candidate.app', 'candidate')
            target = self.app(root / 'Installed.app', 'previous')
            previous = components(target)
            rename = Path.rename
            def fail_activation(path, destination):
                if path.name.startswith('.Wizard101-account-stage-'):
                    raise OSError('simulated activation failure')
                return rename(path, destination)
            with patch.object(Path, 'rename', fail_activation):
                with self.assertRaisesRegex(OSError, 'activation failure'):
                    replace_app(source, target, components(source))
            self.assertEqual(components(target), previous)
            self.assertFalse(list(root.glob('.Wizard101-account-stage-*')))


if __name__ == '__main__': unittest.main()
