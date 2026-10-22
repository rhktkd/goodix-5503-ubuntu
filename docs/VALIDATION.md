# Validation and limitations

## Reported hardware result

- Laptop: Lenovo ThinkBook 14 G3 ACL.
- USB sensor: Goodix `27c6:5503`.
- Firmware: `GF3208_RTSEC_APP_10063`; IAP: `MILAN_RTSEC_IAP_10027`.
- OS: Ubuntu 26.04.1 LTS amd64.
- The user completed the fixed PSK write/readback, host-key installation, enrollment, `verify-match`, PAM activation and fingerprint unlock on the actual device.
- The agent checked the installed package, installed library hash and PAM configuration. Device interactions and lock-screen results were supplied or confirmed by the user; the agent did not directly access the user's USB device or observe the lock screen.

## Offline checks

- Exact supplied Windows 10 installer: 35 files extracted with embedded SHA-1 verification.
- Actual Linux C/C++ build: 126 targets.
- SIGFM matcher/core/detection/gallery: 4 tests passed.
- After the Windows 11 encoder was supplied and the local pairing patch was applied: 64 upstream Python tests passed, none skipped.
- Pairing profile regression suite: 6 tests passed using mocked USB and fixed test data.
- Local tooling/integrity suite: 13 tests passed before publication changes. Publication also adds a pristine-checkout/idempotent-patch test and clean-export checks; their current results are recorded in `PUBLICATION_MANIFEST.json` when exporting.
- `fprintd` dynamic linkage: resolved the isolated library with no missing libraries or undefined symbols.
- DEB layout, root ownership, directory/file modes, SONAME link and maintainer-script syntax were checked. No native binary package is distributed in this source repository.

Run the portable tooling checks without any device access:

```bash
python3 -B -m unittest discover -s tests -p 'test_ubuntu_tooling.py' -v
python3 -B -m unittest discover -s tests -p 'test_source_bootstrap.py' -v
```

Installer-dependent tests skip when the proprietary installer is absent. The bootstrap test skips until upstream source has been downloaded. For the pairing suite, use the Python environment created by `prepare`:

```bash
vendor/goodix-5503-linux/.venv/bin/python -B -m unittest discover -s tests -p 'test_pairing_profile.py' -v
```

## Limits

This is a locally tested community integration, not a statistical biometric evaluation. False-accept and false-reject rates, repeated wrong-finger rejection, reboot/suspend recovery and long-term reliability were not established. Ubuntu 22.04/24.04, other firmware/IAP versions and other sensors are not covered by the reported result.

The local patch permits two exact APP identities already recognized by the C runtime. Before a new persistent PSK write it additionally checks the reset-time DN2 chip ID `0x220f` and unchanged R-family verification record. The ordinary read-only USB command allowlist is not broadened.

A non-fatal scanned-print/gallery warning was observed in the libfprint service log; the user subsequently confirmed `verify-match`. No matcher threshold or authentication decision was changed to suppress that warning.
