"""Offline fresh-checkout bootstrap check; no hardware, keys or network."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

PROJECT = Path(__file__).resolve().parents[1]
UPSTREAM = PROJECT / 'vendor/goodix-5503-linux'
spec = importlib.util.spec_from_file_location('bootstrap_tool', PROJECT / 'ubuntu-goodix5503.py')
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


@unittest.skipUnless(shutil.which('git') and (UPSTREAM / '.git').is_dir(),
                     'Pinned upstream checkout is downloaded by prepare')
class FreshCheckoutBootstrapTests(unittest.TestCase):
    def test_reviewed_patch_applies_to_pristine_checkout_and_is_idempotent(self):
        with tempfile.TemporaryDirectory(prefix='goodix-pristine-') as temporary:
            checkout = Path(temporary) / 'driver'
            subprocess.run(['git', 'clone', '--no-hardlinks', str(UPSTREAM), str(checkout)],
                           check=True, capture_output=True)
            self.assertFalse((checkout / 'src/goodix5503/identity.py').exists())
            with mock.patch.object(tool, 'DRIVER', checkout):
                tool.apply_reviewed_pairing_patch(checkout)
                tool.verify_source_checkout(checkout)
                before = subprocess.check_output(['git', '-C', str(checkout), 'diff', 'HEAD'])
                tool.apply_reviewed_pairing_patch(checkout)
                tool.verify_source_checkout(checkout)
                self.assertEqual(before, subprocess.check_output(['git', '-C', str(checkout), 'diff', 'HEAD']))
                self.assertTrue((checkout / 'src/goodix5503/identity.py').is_file())


if __name__ == '__main__':
    unittest.main()
