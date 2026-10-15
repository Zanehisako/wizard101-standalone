import copy
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build_installer import component_settings
from package_shipping import BETA_LIVE_GATES, validate_beta_live, package
from reduce_runtime import pe_snapshot, verify_preserved, strip_tool


class BetaGateTests(unittest.TestCase):
    def evidence(self):
        return dict(components={'launcher': 'sha'}, installer_sha256='pkg-sha', gates=dict.fromkeys(BETA_LIVE_GATES, True))

    def test_synthetic_passes_do_not_authorize_beta(self):
        evidence = self.evidence(); evidence['gates'] = {'self_tests': True, 'bundle_audit': True}
        with self.assertRaisesRegex(ValueError, 'Unverified community beta gates'):
            validate_beta_live(evidence, evidence['components'], 'pkg-sha')

    def test_live_passes_bind_installer_and_app(self):
        evidence = self.evidence()
        for hashes, pkg in [({'launcher': 'changed'}, 'pkg-sha'), (evidence['components'], 'changed')]:
            with self.assertRaisesRegex(ValueError, 'exactly'): validate_beta_live(evidence, hashes, pkg)
        validate_beta_live(evidence, evidence['components'], 'pkg-sha')

    def test_each_beta_gate_requires_boolean_pass(self):
        for gate in BETA_LIVE_GATES:
            for value in [False, None, 'true', 1]:
                evidence = self.evidence(); evidence['gates'][gate] = value
                with self.assertRaises(ValueError): validate_beta_live(evidence, evidence['components'], 'pkg-sha')

    def test_relocation_is_disabled_for_nested_helpers_too(self):
        result = component_settings([dict(BundleIsRelocatable=True, ChildBundles=[dict(BundleIsRelocatable=True)])])[0]
        self.assertFalse(result['BundleIsRelocatable'])
        self.assertFalse(result['ChildBundles'][0]['BundleIsRelocatable'])
        self.assertEqual(result['BundleOverwriteAction'], 'upgrade')

    def test_beta_cannot_use_signed_release_arguments(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, 'unsigned PKG'):
                package('unused', Path(tmp) / 'new', format='dmg', channel='community-beta')


@unittest.skipUnless(shutil.which('x86_64-w64-mingw32-gcc'), 'MinGW PE compiler required')
class BinaryPreservationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        source = cls.root / 'fixture.c'
        source.write_text('#include <windows.h>\n__declspec(dllexport) DWORD example(void) { return GetTickCount(); }\nvoid *pointer = &example;\n')
        cls.original = cls.root / 'original.dll'
        cls.stripped = cls.root / 'stripped.dll'
        subprocess.run(['x86_64-w64-mingw32-gcc', '-g', '-shared', str(source), '-o', str(cls.original)], check=True, capture_output=True)
        subprocess.run([strip_tool(), '--strip-debug', '--strip-unneeded', str(cls.original), '-o', str(cls.stripped)], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def test_real_pe_strip_preserves_code_import_export_unwind_and_relocations(self):
        original, stripped = pe_snapshot(self.original), pe_snapshot(self.stripped)
        self.assertTrue(original['debug_sections'])
        self.assertTrue({'.text', '.idata', '.edata', '.pdata', '.xdata', '.reloc'} <= set(original['sections']))
        verify_preserved(original, stripped)
        self.assertLess(self.stripped.stat().st_size, self.original.stat().st_size)

    def test_corruption_in_each_load_bearing_section_is_rejected(self):
        original = pe_snapshot(self.original)
        data = self.stripped.read_bytes()
        pe = struct.unpack_from('<I', data, 60)[0]
        count, optional = struct.unpack_from('<H', data, pe + 6)[0], struct.unpack_from('<H', data, pe + 20)[0]
        for i in range(count):
            section = pe + 24 + optional + i * 40
            name = data[section:section + 8].rstrip(b'\0').decode()
            if name not in {'.text', '.idata', '.edata', '.pdata', '.xdata', '.reloc'}: continue
            raw = struct.unpack_from('<I', data, section + 20)[0]
            corrupt = bytearray(data); corrupt[raw] ^= 1
            target = self.root / 'corrupt.dll'; target.write_bytes(corrupt)
            with self.assertRaisesRegex(ValueError, 'load-bearing'): verify_preserved(original, pe_snapshot(target))


if __name__ == '__main__': unittest.main()
