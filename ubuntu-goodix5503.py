#!/usr/bin/env python3
"""Ubuntu integration workbench for Goodix 27c6:5503. Never flashes firmware.

prepare/build/package only write this project. Installation and pairing are
separate actions. The upstream C driver is fetched, not bundled or reimplemented.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
WORK = ROOT / 'build'
VENDOR = ROOT / 'vendor'
DRIVER = VENDOR / 'goodix-5503-linux'
BASE = VENDOR / 'libfprint'
PREFIX = '/opt/goodix5503'
BASE_COMMIT = '80a4b5ec612892c5c056c48dddaa561452cf37ec'
INSTALLER_SHA = 'c94d7c866b0fc0be4d62511b780294900eef972f6e8ec9db761b74cfdf1af4ea'
ENCODER_SHA = '27b211eee3f973b2e5b70823d6fb7c69394876839ab9e2e9a85f14b8ce1008ee'
WBDI_SHA = '567b5af3f2c51eca058172aaa0d0403d82680c75e77d2d073cfd403b1180fb8a'
EXPECTED_FIRMWARE = 'GF3258_RTSEC_APP_10063'
POST_RESET_FIRMWARE = 'GF3208_RTSEC_APP_10063'
RUNTIME_FIRMWARE_IDS = frozenset((EXPECTED_FIRMWARE, POST_RESET_FIRMWARE))
EXPECTED_IAP = 'MILAN_RTSEC_IAP_10027'
DEPS = ['build-essential', 'git', 'meson', 'ninja-build', 'pkg-config', 'patch',
        'libglib2.0-dev', 'libgusb-dev', 'libgudev-1.0-dev', 'libpixman-1-dev',
        'libopencv-dev', 'libssl-dev', 'libcairo2-dev', 'gobject-introspection',
        'libgirepository-2.0-dev', 'python3-venv', 'python3-pip', 'python3-gi',
        'python3-cairo', 'python3-dbusmock', 'python3-pytest', 'libpam-fprintd',
        'fprintd', 'innoextract', 'curl', 'dpkg-dev']


def run(argv, **kw):
    argv = [str(x) for x in argv]
    print('+ ' + shlex.join(argv), flush=True)
    return subprocess.run(argv, check=True, **kw)


def output(argv, **kw):
    return subprocess.check_output([str(x) for x in argv], text=True, **kw).strip()


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def check_digest(path, expected):
    if digest(path) != expected:
        raise RuntimeError(f'SHA-256 mismatch: {path}')


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n')


def diagnose(args):
    devices = []
    for entry in sorted(Path('/sys/bus/usb/devices').glob('*')):
        try:
            vidpid = (entry / 'idVendor').read_text().strip() + ':' + (entry / 'idProduct').read_text().strip()
            if vidpid != '27c6:5503':
                continue
            bus = int((entry / 'busnum').read_text())
            dev = int((entry / 'devnum').read_text())
            node = Path(f'/dev/bus/usb/{bus:03d}/{dev:03d}')
            devices.append({'id': vidpid, 'sysfs': str(entry), 'usb_node': str(node),
                            'usb_node_visible': node.exists(),
                            'usb_node_rw': os.access(node, os.R_OK | os.W_OK)})
        except OSError:
            continue
    status = {'devices': devices, 'original_installer_valid': False,
              'source_available': DRIVER.is_dir() and BASE.is_dir(),
              'missing_build_tools': [p for p in ('git', 'meson', 'ninja', 'cc', 'patch', 'pkg-config') if not shutil.which(p)],
              'missing_pkgconfig': [], 'firmware': 'not queried', 'enroll_verify': 'not tested'}
    source = ROOT / '자료/74ti05afkkxbyyb0.exe'
    if source.is_file():
        status['original_installer_valid'] = digest(source) == INSTALLER_SHA
    for name in ('glib-2.0', 'gusb', 'gudev-1.0', 'pixman-1', 'opencv4', 'openssl'):
        if not shutil.which('pkg-config') or subprocess.run(['pkg-config', '--exists', name]).returncode:
            status['missing_pkgconfig'].append(name)
    bus = subprocess.run(['busctl', '--system', '--auto-start=no', 'call', 'net.reactivated.Fprint',
                          '/net/reactivated/Fprint/Manager', 'net.reactivated.Fprint.Manager', 'GetDevices'],
                         text=True, capture_output=True, timeout=15)
    status['fprintd_bus'] = {'returncode': bus.returncode, 'stdout': bus.stdout.strip(), 'stderr': bus.stderr.strip()}
    save(ROOT / 'evidence/host-diagnosis.json', status)
    print(json.dumps(status, ensure_ascii=False, indent=2))


def clone(url, path, revision=None):
    if not path.exists():
        VENDOR.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='fetch-', dir=VENDOR) as temporary:
            checkout = Path(temporary) / 'checkout'
            if revision:
                run(['git', 'init', checkout])
                run(['git', '-C', checkout, 'remote', 'add', 'origin', url])
                run(['git', '-C', checkout, 'fetch', '--depth=1', 'origin', revision])
                run(['git', '-C', checkout, 'checkout', '--detach', 'FETCH_HEAD'])
            else:
                run(['git', 'clone', '--depth=1', url, checkout])
            shutil.move(checkout, path)
    actual = output(['git', '-C', path, 'rev-parse', 'HEAD'])
    if revision and actual != revision:
        raise RuntimeError(f'Unexpected source revision in {path}: {actual}')
    if path.resolve() == DRIVER.resolve() and (ROOT / 'patches/pairing-profile.json').is_file():
        apply_reviewed_pairing_patch(path)
    verify_source_checkout(path)
    return actual


def apply_reviewed_pairing_patch(path):
    """Apply the recorded patch to a pristine pinned download, exactly once."""
    record = json.loads((ROOT / 'patches/pairing-profile.json').read_text())
    if output(['git', '-C', path, 'rev-parse', 'HEAD']) != record['base_commit']:
        raise RuntimeError('Pairing patch requires its exact pinned upstream commit.')
    patch = ROOT / 'patches/pairing-profile.patch'
    check_digest(patch, record['patch_sha256'])
    if all((path / name).is_file() and digest(path / name) == entry['patched_sha256']
           for name, entry in record['files'].items()):
        return
    if output(['git', '-C', path, 'diff', 'HEAD', '--name-only']):
        raise RuntimeError('Refusing to apply pairing patch to modified source.')
    for name, entry in record['files'].items():
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise RuntimeError('Unsafe local patch path.')
        target = path / relative
        if entry['base_sha256'] is None:
            if target.exists() or target.is_symlink():
                raise RuntimeError('Pairing patch new file already exists: ' + name)
        else:
            check_digest(target, entry['base_sha256'])
    run(['git', '-C', path, 'apply', '--check', patch])
    run(['git', '-C', path, 'apply', patch])


def verify_source_checkout(path):
    """Accept clean upstream, or only the recorded local pairing patch."""
    changed = set(output(['git', '-C', path, 'diff', 'HEAD', '--name-only']).splitlines())
    manifest = ROOT / 'patches/pairing-profile.json'
    if path.resolve() != DRIVER.resolve() or not manifest.is_file():
        if changed:
            raise RuntimeError(f'Modified upstream checkout: {path}')
        return
    record = json.loads(manifest.read_text())
    if output(['git', '-C', path, 'rev-parse', 'HEAD']) != record['base_commit']:
        raise RuntimeError('Local pairing patch has a different upstream base.')
    if changed - set(record['files']):
        raise RuntimeError('Unrecorded upstream source changes: ' + ', '.join(sorted(changed - set(record['files']))))
    check_digest(ROOT / 'patches/pairing-profile.patch', record['patch_sha256'])
    for relative, hashes in record['files'].items():
        candidate = Path(relative)
        if candidate.is_absolute() or '..' in candidate.parts:
            raise RuntimeError('Unsafe local patch path.')
        original = subprocess.run(['git', '-C', str(path), 'show', 'HEAD:' + relative],
                                  capture_output=True, check=False)
        expected_base = hashes['base_sha256']
        if expected_base is None:
            if original.returncode == 0:
                raise RuntimeError('Local patch expected a new module: ' + relative)
        elif original.returncode != 0 or hashlib.sha256(original.stdout).hexdigest() != expected_base:
            raise RuntimeError('Local patch base hash mismatch: ' + relative)
        check_digest(path / relative, hashes['patched_sha256'])


def prepare(args):
    source = Path(args.installer).resolve()
    check_digest(source, INSTALLER_SHA)
    lock = ROOT / 'sources.lock.json'
    previous_lock = json.loads(lock.read_text()) if lock.is_file() else {}
    patch_manifest = ROOT / 'patches/pairing-profile.json'
    pinned_driver = previous_lock.get('driver_commit')
    if not pinned_driver and patch_manifest.is_file():
        pinned_driver = json.loads(patch_manifest.read_text())['base_commit']
    rev = clone('https://github.com/Duro02/goodix-5503-linux.git', DRIVER,
                args.driver_commit or pinned_driver)
    base_rev = clone('https://gitlab.freedesktop.org/libfprint/libfprint.git', BASE, BASE_COMMIT)
    identity = {'driver_commit': rev, 'libfprint_commit': base_rev,
                'installer_sha256': INSTALLER_SHA}
    if lock.exists() and json.loads(lock.read_text()) != identity:
        raise RuntimeError('Existing sources.lock.json differs; source changes need review.')
    save(lock, identity)
    dest = DRIVER / 'artifacts/windows-driver'
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, dest / '74ti05afkkxbyyb0-win10.exe')
    # The exact Win10 extraction is already available in this project, or can
    # be reproduced offline without installing/running Windows software.
    run([sys.executable, ROOT / 'tools/extract_inno_payload.py', source,
         '--output', dest / 'extracted/win10',
         '--manifest', dest / 'win10-extraction-manifest.json'])
    if args.encoder_installer or args.download_encoder:
        encoder = Path(args.encoder_installer).resolve() if args.encoder_installer else dest / '74ti04afkkxbyyb0-win11.exe'
        if args.encoder_installer and not encoder.is_file():
            raise RuntimeError(f'Local encoder installer does not exist: {encoder}')
        if not encoder.exists() and args.download_encoder:
            temporary = encoder.with_suffix('.part')
            run(['curl', '--fail', '--location', '--connect-timeout', '15', '--max-time', '180',
                 'https://download.lenovo.com/consumer/mobiles/74ti04afkkxbyyb0.exe', '-o', temporary])
            check_digest(temporary, ENCODER_SHA)
            temporary.replace(encoder)
        check_digest(encoder, ENCODER_SHA)
        target = dest / 'extracted/win11'
        target.mkdir(parents=True, exist_ok=True)
        run(['innoextract', '--extract', '--silent', '--output-dir', target, encoder])
        matches = list(target.glob('**/Goodix_3.1.581.610/Wbdi.dll'))
        if len(matches) != 1:
            raise RuntimeError('Expected one official Goodix 3.1.581.610 encoder.')
        check_digest(matches[0], WBDI_SHA)
    venv = DRIVER / '.venv'
    if not (venv / 'bin/python').exists():
        run([sys.executable, '-m', 'venv', venv])
    run([venv / 'bin/python', '-m', 'pip', 'install', '-e', str(DRIVER) + '[whitebox]'])
    print('Sources locked. No hardware was accessed. Run probe before pairing.')


def replace_once(path, old, new):
    text = path.read_text()
    if text.count(old) != 1:
        raise RuntimeError(f'Upstream layout changed: {path}; refusing an ambiguous patch.')
    path.write_text(text.replace(old, new, 1))


def validate_probe(report):
    if not isinstance(report, dict):
        raise RuntimeError('Probe did not return a JSON object.')
    selected = {key: report.get(key) for key in
                ('vendor_id', 'product_id', 'firmware', 'iap', 'bus', 'address')}
    supported = (selected['vendor_id'] == '27c6' and selected['product_id'] == '5503'
                 and selected['firmware'] in RUNTIME_FIRMWARE_IDS
                 and selected['iap'] == EXPECTED_IAP)
    save(ROOT / 'evidence/sensor-probe.json', {**selected, 'supported': supported,
         'operation': 'read-only firmware/IAP probe; no pairing',
         'qualification': 'Runtime identity admitted; PSK, chip-ID and OTP checks remain in the driver.',
         'pairing_requires_chip_attestation': True})
    if not supported:
        raise RuntimeError('Unsupported or incomplete device/firmware/IAP response; stopping before installation.')
    return selected


def probe(args):
    result = run(['sudo', '--', DRIVER / '.venv/bin/goodix-5503-probe'],
                 text=True, capture_output=True)
    selected = validate_probe(json.loads(result.stdout))
    print(json.dumps(selected, ensure_ascii=False, indent=2))
    return selected


def continuation_preflight(args):
    check_digest(ROOT / '자료/74ti05afkkxbyyb0.exe', INSTALLER_SHA)
    found = []
    for entry in Path('/sys/bus/usb/devices').glob('*'):
        try:
            if ((entry / 'idVendor').read_text().strip(),
                (entry / 'idProduct').read_text().strip()) == ('27c6', '5503'):
                bus = int((entry / 'busnum').read_text())
                dev = int((entry / 'devnum').read_text())
                found.append(Path(f'/dev/bus/usb/{bus:03d}/{dev:03d}'))
        except OSError:
            continue
    if len(found) != 1 or not found[0].exists():
        raise RuntimeError('센서 USB 노드에 접근할 수 없습니다. 일반 우분투 터미널에서 이 명령을 실행하세요: '
                           + shlex.join([sys.executable, str(ROOT / 'ubuntu-goodix5503.py'),
                                         'continue'] + (['--install'] if args.install else [])))


def continue_work(args):
    """Run on the user's normal Ubuntu terminal; never launches outside it."""
    journal = ROOT / 'evidence/continuation.json'
    state = {'started_utc': datetime.now(timezone.utc).isoformat(),
             'completed': [], 'current': 'preflight', 'status': 'running',
             'pairing_attempted': False}

    def step(name, action):
        state['current'] = name
        save(journal, state)
        value = action()
        state['completed'].append(name)
        save(journal, state)
        return value

    def dependencies():
        run(['sudo', 'apt-get', 'update'])
        run(['sudo', 'apt-get', 'install', *DEPS])

    def compile_or_reuse():
        if (WORK / 'validated.json').exists():
            # package() checks the lock and library digest before reuse.
            return
        tag = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        for name in ('libfprint-source', 'libfprint-build'):
            path = WORK / name
            if path.exists():
                path.rename(WORK / (name + '-previous-' + tag))
        build(args)

    def install_package():
        manifest = json.loads((ROOT / 'dist/package.json').read_text())
        deb = Path(manifest['path']).resolve()
        if deb.parent != (ROOT / 'dist').resolve() or deb.suffix != '.deb':
            raise RuntimeError('Unexpected package path in manifest.')
        check_digest(deb, manifest['sha256'])
        run(['sudo', 'apt-get', 'install', str(deb)])

    try:
        step('preflight', lambda: continuation_preflight(args))
        if not args.skip_deps:
            step('dependencies', dependencies)
        prepare_args = argparse.Namespace(installer=str(ROOT / '자료/74ti05afkkxbyyb0.exe'),
                         driver_commit=None, encoder_installer=None,
                         download_encoder=args.download_encoder)
        step('prepare', lambda: prepare(prepare_args))
        step('probe', lambda: probe(args))
        step('build', compile_or_reuse)
        step('package', lambda: package(args))
        if args.install:
            step('install', install_package)
        state.update(status='complete', current=None)
        save(journal, state)
        print('빌드·패키징 단계 완료. 센서 PSK는 변경하지 않았습니다. '
              '페어링이 필요하면 별도로 pair 명령을 실행하세요.')
    except BaseException as error:
        state.update(status='stopped', error=str(error))
        save(journal, state)
        raise


def integrate(source, driver):
    run(['patch', '--batch', '--forward', '-p1', '-i',
         driver / 'libfprint/patches/sigfm-core-v1.94.100.patch'], cwd=source)
    shutil.copytree(driver / 'libfprint/sigfm', source / 'libfprint/sigfm')
    for pattern, dest in (('libfprint/drivers/goodix5503*', 'libfprint/drivers'),
                          ('libfprint/tests/test-goodix5503*', 'tests')):
        matches = list(driver.glob(pattern))
        if not matches:
            raise RuntimeError(f'Upstream files missing: {pattern}')
        for path in matches:
            shutil.copy2(path, source / dest / path.name)
    marker = "    'goodixmoc': {},\n"
    replace_once(source / 'meson.build', marker,
                 "    'goodix5503': { 'helper': ['openssl'] },\n" + marker)
    marker = "    'goodixmoc' : files(\n"
    files = ['goodix5503.c'] + [f'goodix5503-{x}.c' for x in ('proto', 'config', 'security', 'image', 'tls')]
    block = "    'goodix5503' : files(\n" + ''.join(f"        'drivers/{name}',\n" for name in files) + '    ),\n'
    replace_once(source / 'libfprint/meson.build', marker, block + marker)
    # This pinned libfprint's no-introspection branch iterates a dictionary
    # using one variable. Meson requires both key and value for dictionaries.
    replace_once(source / 'tests/meson.build',
                 '    foreach driver_test: drivers_tests\n',
                 '    foreach driver_test, driver_options: drivers_tests\n')


def build(args):
    lock = json.loads((ROOT / 'sources.lock.json').read_text())
    for path, key in ((DRIVER, 'driver_commit'), (BASE, 'libfprint_commit')):
        if output(['git', '-C', path, 'rev-parse', 'HEAD']) != lock[key]:
            raise RuntimeError('Source revision differs from lock.')
        verify_source_checkout(path)
    WORK.mkdir(exist_ok=True)
    # A fresh build keeps a failed/old test stamp from authorizing packaging.
    stamp = WORK / 'validated.json'
    stamp.unlink(missing_ok=True)
    source = WORK / 'libfprint-source'
    binary = WORK / 'libfprint-build'
    if source.exists() or binary.exists():
        raise RuntimeError('Build directories exist. Use a new directory or remove build/libfprint-{source,build} before rebuilding.')
    shutil.copytree(BASE, source, ignore=shutil.ignore_patterns('.git'))
    integrate(source, DRIVER)
    build_env = {**os.environ, 'CCACHE_DIR': str(WORK / 'ccache')}
    run(['meson', 'setup', binary, source, '--prefix=' + PREFIX, '--libdir=lib',
         '--buildtype=release', '--wrap-mode=nodownload', '-Ddrivers=goodix5503',
         '-Dintrospection=false', '-Ddoc=false', '-Dinstalled-tests=false',
         '-Dudev_rules=disabled', '-Dudev_hwdb=disabled'], env=build_env)
    run(['meson', 'compile', '-C', binary], env=build_env)
    run(['meson', 'test', '-C', binary, '--print-errorlogs', 'goodix5503-sigfm',
         'goodix5503-sigfm-core', 'goodix5503-sigfm-detection', 'goodix5503-sigfm-gallery'], env=build_env)
    python = DRIVER / '.venv/bin/python'
    run([python, '-m', 'unittest', 'discover', '-s', 'tests', '-v'], cwd=DRIVER,
        env={**os.environ, 'PYTHONPATH': str(DRIVER / 'src')})
    validate_built_runtime(lock, binary)


def validate_built_runtime(lock, binary):
    """Finish build after offline tests; not an independently exposed command."""
    libraries = [path for path in (binary / 'libfprint').glob('libfprint-2.so.2.*')
                 if path.is_file() and not path.is_symlink()]
    if len(libraries) != 1:
        raise RuntimeError('Expected one built libfprint runtime.')
    daemon = Path('/usr/libexec/fprintd')
    if not daemon.is_file():
        raise RuntimeError('Ubuntu /usr/libexec/fprintd missing.')
    linkage = run(['ldd', '-r', daemon], env={**os.environ, 'LD_LIBRARY_PATH': str(libraries[0].parent)},
                  text=True, capture_output=True)
    if 'undefined symbol:' in linkage.stdout + linkage.stderr or 'not found' in linkage.stdout + linkage.stderr:
        raise RuntimeError('fprintd runtime linkage failed: ' + linkage.stdout + linkage.stderr)
    resolved = output(['ldd', daemon], env={**os.environ, 'LD_LIBRARY_PATH': str(libraries[0].parent)})
    if str(libraries[0].parent) not in resolved:
        raise RuntimeError('Linkage test did not resolve the custom library.')
    save(WORK / 'validated.json', {**lock, 'library': str(libraries[0]), 'sha256': digest(libraries[0]),
                 'tests': 'passed; hardware not tested'})
    print('Build and offline checks passed. Use package to create a DEB.')


def package(args):
    stamp = json.loads((WORK / 'validated.json').read_text())
    lock = json.loads((ROOT / 'sources.lock.json').read_text())
    if any(stamp.get(key) != value for key, value in lock.items()):
        raise RuntimeError('Validated build does not match the source lock.')
    lib = Path(stamp['library'])
    check_digest(lib, stamp['sha256'])
    version = '0.1+git' + stamp['driver_commit'][:10]
    out = ROOT / 'dist'
    out.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='deb-', dir=WORK) as temporary:
        stage = Path(temporary)
        target = stage / PREFIX.lstrip('/') / 'lib'
        target.mkdir(parents=True)
        shutil.copy2(lib, target / lib.name)
        (target / 'libfprint-2.so.2').symlink_to(lib.name)
        service = stage / 'usr/lib/systemd/system/fprintd.service.d/50-goodix5503.conf'
        service.parent.mkdir(parents=True)
        service.write_text('[Service]\nEnvironment=LD_LIBRARY_PATH=/opt/goodix5503/lib\nLimitCORE=0\nExecStart=\nExecStart=/usr/libexec/fprintd --no-timeout\n')
        hook = stage / 'usr/lib/systemd/system-sleep/goodix5503'
        hook.parent.mkdir(parents=True)
        hook.write_text('#!/bin/sh\nif [ "$1" = post ]; then\n    systemctl try-restart fprintd.service\nfi\nexit 0\n')
        hook.chmod(0o755)
        hwdb = stage / 'usr/lib/udev/hwdb.d/99-goodix5503.hwdb'
        hwdb.parent.mkdir(parents=True)
        hwdb.write_text('# Local Goodix 5503 driver\nusb:v27C6p5503*\n ID_AUTOSUSPEND=1\n ID_PERSIST=0\n')
        doc = stage / 'usr/share/doc/libfprint-goodix5503-isolated'
        doc.mkdir(parents=True)
        shutil.copy2(ROOT / 'README.md', doc)
        shutil.copy2(ROOT / 'sources.lock.json', doc)
        shutil.copy2(DRIVER / 'LICENSE', doc / 'copyright')
        shutil.copy2(BASE / 'COPYING', doc / 'libfprint-COPYING')
        save(doc / 'validated.json', stamp)
        metadata = stage / 'debian'
        metadata.mkdir()
        control = ('Source: libfprint-goodix5503-isolated\nMaintainer: Local build <local@localhost>\n\n'
                   'Package: libfprint-goodix5503-isolated\nArchitecture: any\nDescription: local Goodix integration\n')
        (metadata / 'control').write_text(control)
        dependencies = output(['dpkg-shlibdeps', '-O', '-e' + str(target / lib.name)], cwd=stage)
        deps = next(line.split('=', 1)[1] for line in dependencies.splitlines() if line.startswith('shlibs:Depends='))
        shutil.rmtree(metadata)
        debian = stage / 'DEBIAN'
        debian.mkdir()
        arch = output(['dpkg', '--print-architecture'])
        (debian / 'control').write_text(f'Package: libfprint-goodix5503-isolated\nVersion: {version}\nArchitecture: {arch}\nMaintainer: Local build <local@localhost>\nDepends: fprintd, {deps}\nDescription: experimental isolated Goodix 27c6:5503 driver\n Only fprintd uses this libfprint; pairing is a separate interactive step.\n')
        for name in ('postinst', 'postrm'):
            script = debian / name
            script.write_text('#!/bin/sh\nset -e\nif command -v systemd-hwdb >/dev/null 2>&1; then\n    systemd-hwdb update || true\nfi\nif [ -d /run/systemd/system ]; then\n    systemctl daemon-reload\n    udevadm trigger --action=change --subsystem-match=usb --attr-match=idVendor=27c6 --attr-match=idProduct=5503 || true\n    systemctl try-restart fprintd.service || true\nfi\nexit 0\n')
            script.chmod(0o755)
        # TemporaryDirectory starts at 0700, while the package's archive root
        # and installed directories need ordinary system directory modes.
        stage.chmod(0o755)
        for entry in stage.rglob('*'):
            if entry.is_symlink():
                continue
            if entry.is_dir():
                entry.chmod(0o755)
            elif entry.is_file():
                entry.chmod(0o755 if entry.stat().st_mode & 0o111 else 0o644)
        deb = out / f'libfprint-goodix5503-isolated_{version}_{arch}.deb'
        run(['dpkg-deb', '--root-owner-group', '--build', stage, deb])
        save(out / 'package.json', {'path': str(deb), 'sha256': digest(deb), 'build_validation': stamp})
    print('Created ' + str(deb) + '\nInstall explicitly: sudo apt install ' + shlex.quote(str(deb)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('diagnose', help='read host/sysfs/service state; no sensor commands')
    commands.add_parser('deps', help='install Ubuntu build dependencies using sudo apt')
    prep = commands.add_parser('prepare', help='download/lock sources and create local Python environment')
    prep.add_argument('--installer', default=str(ROOT / '자료/74ti05afkkxbyyb0.exe'))
    prep.add_argument('--driver-commit', help='optional exact 40-digit upstream commit')
    prep.add_argument('--encoder-installer', help='local, exact official Win11 encoder installer')
    prep.add_argument('--download-encoder', action='store_true', help='also fetch pinned official Win11 pairing encoder')
    commands.add_parser('probe', help='USB read-only probe; reject unsupported firmware/IAP (sudo)')
    commands.add_parser('build', help='build isolated libfprint and run offline tests')
    commands.add_parser('package', help='create DEB only after offline checks pass')
    commands.add_parser('pair', help='interactive upstream PSK setup; may invalidate Windows fingerprints')
    continuation = commands.add_parser('continue', help='normal-terminal preparation, probe, build and DEB generation')
    continuation.add_argument('--install', action='store_true', help='also install the checked DEB using sudo apt-get')
    continuation.add_argument('--skip-deps', action='store_true', help='skip apt dependency installation')
    continuation.add_argument('--download-encoder', action='store_true', help='also prepare the separate official pairing encoder')
    args = parser.parse_args()
    if args.command != 'diagnose' and os.geteuid() == 0:
        parser.error('Run as your desktop user; only deps/probe/pair delegate fixed operations to sudo.')
    if getattr(args, 'driver_commit', None) and not re.fullmatch(r'[0-9a-f]{40}', args.driver_commit):
        parser.error('--driver-commit must be a full lowercase Git commit ID')
    if args.command == 'deps':
        run(['sudo', 'apt-get', 'update'])
        run(['sudo', 'apt-get', 'install', *DEPS])
    elif args.command == 'probe':
        probe(args)
    elif args.command == 'continue':
        continue_work(args)
    elif args.command == 'pair':
        verify_source_checkout(DRIVER)
        print('센서 PSK를 바꾸면 Windows 지문 등록이 무효화됩니다. 원래 키 전체 복원은 보장되지 않습니다.\n'
              '도구가 상태를 확인하고 쓰기 전에 별도 확인을 요구합니다. 확인 후에는 고정 MCU 리셋과\n'
              'DN2 칩 ID·기존 검증값을 확인하며, 조건이 다르면 키를 쓰기 전에 중단합니다.', flush=True)
        run([DRIVER / '.venv/bin/goodix-5503-setup'], cwd=DRIVER)
    else:
        globals()[args.command](args)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, subprocess.SubprocessError, ValueError) as error:
        sys.exit('ERROR: ' + str(error))
