import copy
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reliability_qualification import GATES, validate


class ReliabilityQualificationTests(unittest.TestCase):
    def evidence(self):
        return dict(components={'launcher': 'final'}, gates=dict.fromkeys(GATES, True),
                    observations=dict.fromkeys(GATES, 'Observed on this exact candidate'))

    def test_synthetic_success_cannot_replace_live_checks(self):
        report = self.evidence()
        for gate in GATES:
            for unverified in (False, None, 1, 'true'):
                changed = copy.deepcopy(report); changed['gates'][gate] = unverified
                with self.assertRaisesRegex(ValueError, 'Unverified reliability'):
                    validate(changed, report['components'])
            changed = copy.deepcopy(report); changed['observations'][gate] = ''
            with self.assertRaisesRegex(ValueError, 'live observation'):
                validate(changed, report['components'])

    def test_evidence_is_bound_to_components(self):
        report = self.evidence()
        validate(report, report['components'])
        with self.assertRaisesRegex(ValueError, 'exactly'):
            validate(report, {'launcher': 'changed'})


if __name__ == '__main__': unittest.main()
