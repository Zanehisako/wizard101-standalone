import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from package_shipping import validate_live, signing_identity
from account_qualification import ACCOUNT_GATES
from reliability_qualification import GATES as RELIABILITY_GATES

class ShippingApprovalTests(unittest.TestCase):
    def evidence(self):
        return {'components': {'Contents/MacOS/Wizard101Native': 'final-signed-hash'},
                'gates': dict.fromkeys(['fresh_install_gameplay', 'native_login', 'character_selection',
                    'session_survives_launcher_exit', 'audio', 'keyboard_mouse', 'cursor', 'fullscreen',
                    'graphics', 'updates', 'gui_cancel_resume', 'performance_accepted',
                    'rosetta_first_run', 'second_apple_silicon_mac', 'oldest_supported_macos', 'clean_source_rebuild'] + ACCOUNT_GATES + RELIABILITY_GATES, True),
                'observations': dict.fromkeys(RELIABILITY_GATES, 'Observed live on this exact candidate')}

    def test_build_and_synthetic_passes_cannot_authorize_public_release(self):
        evidence = self.evidence()
        evidence['gates'] = {'self_tests': True, 'bundle_audit': True, 'gpu_probes': True}
        with self.assertRaisesRegex(ValueError, 'Unverified public release gates'):
            validate_live(evidence, evidence['components'])

    def test_component_change_invalidates_gameplay_evidence(self):
        evidence = self.evidence()
        with self.assertRaisesRegex(ValueError, 'final signed app exactly'):
            validate_live(evidence, {'Contents/MacOS/Wizard101Native': 'changed-hash'})

    def test_every_gate_requires_explicit_boolean_pass(self):
        evidence = self.evidence()
        for gate in evidence['gates']:
            for value in [False, None, 'true', 1]:
                rejected = self.evidence(); rejected['gates'][gate] = value
                with self.assertRaises(ValueError, msg=gate): validate_live(rejected, rejected['components'])

    def test_exact_artifact_with_all_required_live_gates_is_accepted(self):
        evidence = self.evidence()
        validate_live(evidence, evidence['components'])

if __name__ == '__main__': unittest.main()
