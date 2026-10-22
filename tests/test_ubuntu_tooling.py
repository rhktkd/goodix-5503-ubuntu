"""Offline integration-tooling tests, NOT real driver or hardware tests.

The packaging fixture is a tiny locally compiled dummy shared library. It does
not implement libfprint and must never be installed or used as a sensor driver.
All fixture packages and extraction outputs live in automatically removed
temporary directories; no fake DEB is written to the project's dist directory.
No package is installed, no maintainer script is run, and no USB is accessed.
"""
import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock


PROJECT = Path(__file__).resolve().parents[1]
INSTALLER = PROJECT / '자료/74ti05afkkxbyyb0.exe'


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tool = load_module('goodix_ubuntu_tooling_under_test', PROJECT / 'ubuntu-goodix5503.py')
extractor = load_module('goodix_inno_extractor_under_test',
                        PROJECT / 'tools/extract_inno_payload.py')


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class OriginalInstallerOfflineExtractionTests(unittest.TestCase):
    """Verify actual supplied installer bytes without executing their contents."""

    @unittest.skipUnless(INSTALLER.is_file(), 'User-supplied pinned Lenovo installer is not distributed')
    def test_all_35_files_reextract_and_match_embedded_sha1(self):
        self.assertTrue(INSTALLER.is_file(), 'The exact supplied installer is required')
        with tempfile.TemporaryDirectory(prefix='goodix-extract-test-') as temporary:
            root = Path(temporary)
            output = root / 'payload'
            manifest = root / 'manifest.json'
            result = extractor.extract(INSTALLER, output, manifest)
            self.assertEqual(result['source_sha256'], tool.INSTALLER_SHA)
            self.assertFalse(result['installer_executed'])
            self.assertFalse(result['payload_executed'])
            self.assertEqual(len(result['files']), 35)
            self.assertEqual(sum(f['size'] for f in result['files']), 22695715)
            actual_files = [p for p in output.rglob('*') if p.is_file()]
            self.assertEqual(len(actual_files), 35)
            self.assertEqual(json.loads(manifest.read_text()), result)
            for entry in result['files']:
                path = output / entry['path']
                payload = path.read_bytes()
                with self.subTest(path=entry['path']):
                    self.assertEqual(len(payload), entry['size'])
                    self.assertEqual(hashlib.sha1(payload).hexdigest(),
                                     entry['installer_sha1_verified'])
                    self.assertEqual(sha256(path), entry['sha256'])
                    self.assertFalse(path.stat().st_mode & 0o111)
            self.assertEqual(sha256(output / 'Goodix_3.1.581.520/Wbdi.dll'),
                '3f43ddab54d81a538f05e8e124996e1dee9f1d6fa215761e3a8422003ee1a657')
            self.assertEqual(sha256(output / 'Goodix_3.1.581.520/WbdiUsb.inf'),
                '6ffbc144aa52a359cdfaaa651e59f3a509d2294dabe7961d7cda0d3ffb6e5ec2')

    @unittest.skipUnless(INSTALLER.is_file(), 'User-supplied pinned Lenovo installer is not distributed')
    def test_modified_original_installer_rejected_before_output(self):
        with tempfile.TemporaryDirectory(prefix='goodix-corrupt-test-') as temporary:
            root = Path(temporary)
            altered = bytearray(INSTALLER.read_bytes())
            altered[-1] ^= 1
            source = root / 'modified.exe'
            source.write_bytes(altered)
            with self.assertRaisesRegex(ValueError, 'SHA-256'):
                extractor.extract(source, root / 'payload', root / 'manifest.json')
            self.assertFalse((root / 'payload').exists())
            self.assertFalse((root / 'manifest.json').exists())

    def test_prepare_invalid_sha_never_calls_git_pip_or_subprocess(self):
        with tempfile.TemporaryDirectory(prefix='goodix-prepare-test-') as temporary:
            source = Path(temporary) / 'invalid.exe'
            source.write_bytes(b'not the pinned Lenovo installer')
            args = argparse.Namespace(installer=str(source), driver_commit=None,
                                      encoder_installer=None, download_encoder=False)
            with mock.patch.object(tool, 'clone') as clone, \
                    mock.patch.object(tool, 'run') as run, \
                    mock.patch.object(tool, 'output') as output:
                with self.assertRaisesRegex(RuntimeError, 'SHA-256 mismatch'):
                    tool.prepare(args)
                clone.assert_not_called()
                run.assert_not_called()
                output.assert_not_called()


@unittest.skipUnless(all(shutil.which(name) for name in
                        ('cc', 'dpkg-shlibdeps', 'dpkg-deb', 'dpkg')),
                     'Real offline packaging tooling (cc and dpkg) is required')
class DummyLibraryPackagingToolingTests(unittest.TestCase):
    """Package a fake C library to verify tooling only; never a driver test."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='goodix-dummy-package-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.work = self.root / 'build'
        self.vendor = self.root / 'vendor'
        self.driver = self.vendor / 'goodix-5503-linux'
        self.base = self.vendor / 'libfprint'
        for directory in (self.work, self.driver, self.base):
            directory.mkdir(parents=True)
        self.patch = mock.patch.multiple(tool, ROOT=self.root, WORK=self.work,
                                        VENDOR=self.vendor, DRIVER=self.driver,
                                        BASE=self.base)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        (self.root / 'README.md').write_text('TOOLING TEST FIXTURE ONLY. NOT A DRIVER.\n')
        (self.driver / 'LICENSE').write_text('Dummy test fixture, no upstream code.\n')
        (self.base / 'COPYING').write_text('Dummy test fixture, no libfprint code.\n')
        self.lock = {'driver_commit': 'a' * 40,
                     'libfprint_commit': tool.BASE_COMMIT,
                     'installer_sha256': tool.INSTALLER_SHA}
        (self.root / 'sources.lock.json').write_text(json.dumps(self.lock))
        source = self.work / 'NOT_A_DRIVER.c'
        source.write_text('#include <stdio.h>\n'
                          'int tooling_fixture_only(void) { '
                          'return puts("Packaging fixture, not a driver"); }\n')
        self.library = self.work / 'libfprint-2.so.2.0.0'
        subprocess.run(['cc', '-shared', '-fPIC', '-Wl,-soname,libfprint-2.so.2',
                        '-o', self.library, source], check=True,
                       capture_output=True, text=True)
        self.stamp = {**self.lock, 'library': str(self.library),
                      'sha256': sha256(self.library),
                      'tests': 'DUMMY TOOLING FIXTURE ONLY; no driver/hardware tested'}
        self.stamp_path = self.work / 'validated.json'
        self.stamp_path.write_text(json.dumps(self.stamp))

    def test_real_deb_packaging_isolated_paths_and_separate_hashes(self):
        with contextlib.redirect_stdout(io.StringIO()):
            tool.package(argparse.Namespace())
        manifest = json.loads((self.root / 'dist/package.json').read_text())
        deb = Path(manifest['path'])
        self.assertTrue(deb.is_relative_to(self.root))
        self.assertEqual(manifest['sha256'], sha256(deb))
        self.assertEqual(manifest['build_validation']['sha256'], sha256(self.library))
        self.assertNotEqual(manifest['sha256'], manifest['build_validation']['sha256'])
        payload = self.root / 'unpacked'
        control = self.root / 'control'
        subprocess.run(['dpkg-deb', '--extract', deb, payload], check=True,
                       capture_output=True, text=True)
        subprocess.run(['dpkg-deb', '--control', deb, control], check=True,
                       capture_output=True, text=True)
        library = payload / 'opt/goodix5503/lib/libfprint-2.so.2.0.0'
        self.assertEqual(sha256(library), sha256(self.library))
        link = library.with_name('libfprint-2.so.2')
        self.assertTrue(link.is_symlink())
        self.assertEqual(os.readlink(link), library.name)
        self.assertEqual(link.resolve(), library.resolve())
        all_shared = list(payload.rglob('*.so*'))
        self.assertEqual(set(all_shared), {library, link})
        self.assertTrue(all(p.is_relative_to(payload / 'opt/goodix5503')
                            for p in all_shared))
        service = payload / 'usr/lib/systemd/system/fprintd.service.d/50-goodix5503.conf'
        text = service.read_text()
        self.assertIn('Environment=LD_LIBRARY_PATH=/opt/goodix5503/lib\n', text)
        self.assertIn('ExecStart=/usr/libexec/fprintd --no-timeout\n', text)
        self.assertIn('LimitCORE=0\n', text)
        hook = payload / 'usr/lib/systemd/system-sleep/goodix5503'
        self.assertTrue(hook.stat().st_mode & 0o111)
        self.assertIn('try-restart fprintd.service', hook.read_text())
        hwdb = payload / 'usr/lib/udev/hwdb.d/99-goodix5503.hwdb'
        self.assertIn('usb:v27C6p5503*\n ID_AUTOSUSPEND=1\n ID_PERSIST=0\n',
                      hwdb.read_text())
        self.assertIn('Depends: fprintd, libc6', (control / 'control').read_text())
        for name in ('postinst', 'postrm'):
            script = control / name
            self.assertTrue(script.stat().st_mode & 0o111)
            self.assertIn('systemd-hwdb update', script.read_text())
            subprocess.run(['sh', '-n', script], check=True, capture_output=True)

    def test_changed_library_rejected_before_deb_creation(self):
        with self.library.open('ab') as stream:
            stream.write(b'changed after validation')
        with self.assertRaisesRegex(RuntimeError, 'SHA-256 mismatch'):
            tool.package(argparse.Namespace())
        self.assertFalse((self.root / 'dist').exists())

    def test_changed_source_lock_rejected_before_deb_creation(self):
        changed = {**self.lock, 'driver_commit': 'b' * 40}
        (self.root / 'sources.lock.json').write_text(json.dumps(changed))
        with self.assertRaisesRegex(RuntimeError, 'source lock'):
            tool.package(argparse.Namespace())
        self.assertFalse((self.root / 'dist').exists())


class ContinuationControlTests(unittest.TestCase):
    """Control-flow checks with mocked probes; no hardware or sudo."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='goodix-continuation-test-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        patcher = mock.patch.object(tool, 'ROOT', self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.args = argparse.Namespace(install=True, skip_deps=True, download_encoder=False)

    def valid_report(self):
        return {'vendor_id': '27c6', 'product_id': '5503',
                'firmware': tool.EXPECTED_FIRMWARE, 'iap': tool.EXPECTED_IAP,
                'bus': 3, 'address': 7, 'unexpected_secret': 'must not be retained'}

    def test_probe_gate_accepts_exact_profile_without_storing_extra_fields(self):
        tool.validate_probe(self.valid_report())
        saved = json.loads((self.root / 'evidence/sensor-probe.json').read_text())
        self.assertTrue(saved['supported'])
        self.assertNotIn('unexpected_secret', saved)

    def test_probe_gate_rejects_other_device_firmware_and_missing_iap(self):
        for changed in ({'vendor_id': 'ffff'}, {'product_id': '550a'},
                        {'firmware': 'OTHER'}, {'iap': None}):
            with self.subTest(changed=changed):
                with self.assertRaisesRegex(RuntimeError, 'Unsupported'):
                    tool.validate_probe({**self.valid_report(), **changed})
                saved = json.loads((self.root / 'evidence/sensor-probe.json').read_text())
                self.assertFalse(saved['supported'])

    def test_upstream_post_reset_identity_is_admitted_without_relaxing_iap(self):
        tool.validate_probe({**self.valid_report(), 'firmware': tool.POST_RESET_FIRMWARE})
        saved = json.loads((self.root / 'evidence/sensor-probe.json').read_text())
        self.assertTrue(saved['supported'])
        self.assertTrue(saved['pairing_requires_chip_attestation'])
        self.assertIn('PSK, chip-ID and OTP', saved['qualification'])
        with self.assertRaisesRegex(RuntimeError, 'Unsupported'):
            tool.validate_probe({**self.valid_report(), 'firmware': tool.POST_RESET_FIRMWARE,
                                 'iap': 'MILAN_RTSEC_IAP_10026'})

    def test_missing_usb_stops_before_apt_git_and_probe(self):
        with mock.patch.object(tool, 'check_digest'), \
                mock.patch.object(Path, 'glob', return_value=[]), \
                mock.patch.object(tool, 'run') as run, \
                mock.patch.object(tool, 'prepare') as prepare, \
                mock.patch.object(tool, 'probe') as probe:
            with self.assertRaisesRegex(RuntimeError, 'USB'):
                tool.continue_work(self.args)
            run.assert_not_called()
            prepare.assert_not_called()
            probe.assert_not_called()
        state = json.loads((self.root / 'evidence/continuation.json').read_text())
        self.assertEqual(state['current'], 'preflight')
        self.assertEqual(state['status'], 'stopped')
        self.assertEqual(state['completed'], [])
        self.assertFalse(state['pairing_attempted'])

    def test_failed_probe_stops_before_build_package_and_install(self):
        with mock.patch.object(tool, 'continuation_preflight'), \
                mock.patch.object(tool, 'prepare'), \
                mock.patch.object(tool, 'probe', side_effect=RuntimeError('Unsupported firmware')), \
                mock.patch.object(tool, 'build') as build, \
                mock.patch.object(tool, 'package') as package, \
                mock.patch.object(tool, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'Unsupported firmware'):
                tool.continue_work(self.args)
            build.assert_not_called()
            package.assert_not_called()
            run.assert_not_called()
        state = json.loads((self.root / 'evidence/continuation.json').read_text())
        self.assertEqual(state['current'], 'probe')
        self.assertEqual(state['completed'], ['preflight', 'prepare'])
        self.assertFalse(state['pairing_attempted'])


class RecordedSourcePatchIntegrityTests(unittest.TestCase):
    def test_recorded_patch_is_accepted_and_tampered_python_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix='goodix-patch-integrity-') as temporary:
            root = Path(temporary)
            driver = root / 'driver'
            driver.mkdir()
            (root / 'patches').mkdir()
            source = driver / 'setup.py'
            source.write_bytes(b'patched source')
            patch_file = root / 'patches/pairing-profile.patch'
            patch_file.write_bytes(b'recorded local patch')
            manifest = {'base_commit': 'a' * 40,
                        'patch_sha256': sha256(patch_file),
                        'files': {'setup.py': {'base_sha256': hashlib.sha256(b'base source').hexdigest(),
                                               'patched_sha256': sha256(source)}}}
            (root / 'patches/pairing-profile.json').write_text(json.dumps(manifest))
            with mock.patch.multiple(tool, ROOT=root, DRIVER=driver), \
                    mock.patch.object(tool, 'output', side_effect=['setup.py', 'a' * 40] * 2), \
                    mock.patch.object(tool.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, b'base source', b'')):
                tool.verify_source_checkout(driver)
                source.write_bytes(b'changed after patch review')
                with self.assertRaisesRegex(RuntimeError, 'SHA-256 mismatch'):
                    tool.verify_source_checkout(driver)

    def test_unrecorded_source_change_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix='goodix-patch-extra-') as temporary:
            root = Path(temporary)
            driver = root / 'driver'
            driver.mkdir()
            (root / 'patches').mkdir()
            (root / 'patches/pairing-profile.json').write_text(json.dumps({'base_commit': 'a' * 40, 'files': {}}))
            with mock.patch.multiple(tool, ROOT=root, DRIVER=driver), \
                    mock.patch.object(tool, 'output', side_effect=['unexpected.py', 'a' * 40]), \
                    self.assertRaisesRegex(RuntimeError, 'Unrecorded upstream source changes'):
                tool.verify_source_checkout(driver)


if __name__ == '__main__':
    unittest.main(verbosity=2)
