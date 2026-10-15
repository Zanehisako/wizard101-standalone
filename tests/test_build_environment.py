import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import build_runtime

class DeploymentTargetTests(unittest.TestCase):
    def test_overlay_link_steps_keep_macos_13_on_a_newer_build_host(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(build_runtime,'WORK',Path(directory)), patch.dict(os.environ,{'MACOSX_DEPLOYMENT_TARGET':'26.0'}):
                build_runtime.run([sys.executable,'-c','import os; print(os.environ["MACOSX_DEPLOYMENT_TARGET"])'],log='target')
            self.assertEqual((Path(directory)/'logs/target.log').read_text().strip(),'13.0')

    def test_explicit_build_flags_survive_target_injection(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(build_runtime,'WORK',Path(directory)):
                build_runtime.run([sys.executable,'-c','import os; print(os.environ["W101_BUILD_TEST"]); print(os.environ["MACOSX_DEPLOYMENT_TARGET"])'],env={'W101_BUILD_TEST':'retained'},log='flags')
            self.assertEqual((Path(directory)/'logs/flags.log').read_text().splitlines(),['retained','13.0'])

if __name__=='__main__':unittest.main()
