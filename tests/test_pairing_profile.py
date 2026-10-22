"""Offline pairing regression tests. No USB, secrets, services or installation.

Run with vendor/goodix-5503-linux/.venv/bin/python so PyUSB is importable;
every USB session constructor is replaced before the tested code is called.
"""
import contextlib
import importlib.util
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
if not (PROJECT / 'vendor/goodix-5503-linux/src/goodix5503').is_dir() or importlib.util.find_spec('usb') is None:
    raise unittest.SkipTest('Run prepare, then use the vendor Python environment for pairing tests')
sys.path.insert(0, str(PROJECT / "vendor/goodix-5503-linux/src"))
from goodix5503 import provision, setup

BASE_FIRMWARE = "GF3208_RTSEC_APP_10063"
OLD = b"\x11" * 32
PREPARED = b"\x44" * 32


class FakeSession:
    def __init__(self, *, firmware=BASE_FIRMWARE,
                 iap="MILAN_RTSEC_IAP_10027", chip=0x220F,
                 reset_reply=b"", records=None, post_firmware=None, post_iap=None):
        self.firmware = firmware
        self.iap = iap
        self.chip = chip
        self.reset_reply = reset_reply
        self.records = list(records if records is not None else [OLD, OLD, PREPARED])
        self.post_firmware = post_firmware
        self.post_iap = post_iap
        self.events = []
        self.closed = False

    def request(self, command, payload=b"", *, checksum=True):
        self.events.append((command, bytes(payload)))
        if command == provision.COMMAND_NOP:
            return b""
        if command == provision.COMMAND_FIRMWARE_VERSION:
            return self.firmware.encode() + b"\0"
        if command == provision.COMMAND_GET_IAP_VERSION:
            return self.iap.encode() + b"\0"
        if command == provision.COMMAND_PRESET_PSK_READ:
            value = self.records.pop(0)
            return b"\0" + struct.pack("<II", provision.OFFICIAL_R_PSK_HASH_SELECTOR,
                                       len(value)) + value
        raise AssertionError(f"unexpected public command {command:#x}")

    def _ReadOnlyUsbSession__exchange(self, command, payload, **kwargs):
        self.events.append((command, bytes(payload)))
        if command == 0xA2:
            if payload != b"\x05\x14":
                raise AssertionError("reset payload must remain fixed")
            if self.post_firmware is not None:
                self.firmware = self.post_firmware
            if self.post_iap is not None:
                self.iap = self.post_iap
            return self.reset_reply
        if command == 0xE0:
            expected = struct.pack("<II", provision.OFFICIAL_WHITEBOX_PSK_SELECTOR, 96)
            if payload != expected + b"\x33" * 96:
                raise AssertionError("PSK write must remain the exact prepared TLV")
            return b"\0"
        raise AssertionError(f"unexpected internal command {command:#x}")

    def read_chip_id(self):
        self.events.append(("chip", self.chip))
        return self.chip

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


@contextlib.contextmanager
def offline_provision(session):
    with contextlib.ExitStack() as stack:
        for name, value in (("ReadOnlyUsbSession", session),
                            ("_read_secure_secret", bytearray(OLD)),
                            ("_load_and_validate_material",
                             (bytearray(b"\x22" * 32), bytearray(b"\x33" * 96),
                              bytearray(PREPARED)))):
            stack.enter_context(patch.object(provision, name, return_value=value))
        stack.enter_context(patch.object(provision, "_drop_sudo_privileges"))
        stack.enter_context(patch.object(provision, "_disable_core_dumps"))
        stack.enter_context(patch.object(provision.os, "geteuid", return_value=1000))
        sleep = stack.enter_context(patch.object(provision.time, "sleep"))
        sleep.side_effect = lambda delay: session.events.append(("sleep", delay))
        yield sleep


class PairingProfileTests(unittest.TestCase):
    def run_pairing(self, session):
        return provision.provision_prepared_pairing(
            confirmation=provision.WRITE_CONFIRMATION)

    def assert_no_write(self, session):
        self.assertFalse(any(command == 0xE0 for command, _ in session.events))
        self.assertTrue(session.closed)

    def test_confirmed_base_identity_dn2_writes_once_after_attestation(self):
        session = FakeSession()
        with offline_provision(session) as sleep:
            result = self.run_pairing(session)
        self.assertEqual(result["operation"], "fixed-psk-write-and-readback")
        commands = [command for command, _ in session.events]
        self.assertEqual(commands.count(0xE0), 1)
        self.assertEqual(commands.count(0xA2), 1)
        self.assertLess(commands.index(0xA2), commands.index("sleep"))
        self.assertLess(commands.index("sleep"), commands.index("chip"))
        self.assertLess(commands.index("chip"), commands.index(0xE0))
        self.assertEqual(commands[-1], provision.COMMAND_PRESET_PSK_READ)
        self.assertEqual(session.records, [])
        sleep.assert_called_once_with(.010)

    def test_unknown_initial_identity_or_iap_never_resets_or_writes(self):
        for arguments in ({"firmware": "GF3208_RTSEC_APP_10062"},
                          {"firmware": "GF3288_RTSEC_APP_10063"},
                          {"iap": "MILAN_RTSEC_IAP_10026"}):
            with self.subTest(arguments=arguments):
                session = FakeSession(**arguments)
                with offline_provision(session), self.assertRaises(Exception):
                    self.run_pairing(session)
                self.assert_no_write(session)
                self.assertFalse(any(command == 0xA2 for command, _ in session.events))

    def test_failed_reset_profile_or_recheck_never_writes(self):
        for arguments in ({"reset_reply": b"12345"}, {"chip": 0x2503},
                          {"chip": 0}, {"records": [OLD, b"\x77" * 32]},
                          {"records": [OLD, b"\x11" * 31]},
                          {"post_firmware": "GF3208_RTSEC_APP_10062"},
                          {"post_iap": "MILAN_RTSEC_IAP_10026"}):
            with self.subTest(arguments=arguments):
                session = FakeSession(**arguments)
                with offline_provision(session), self.assertRaises(Exception):
                    self.run_pairing(session)
                self.assert_no_write(session)

    def test_already_committed_pairing_does_not_reset_or_write(self):
        session = FakeSession(records=[PREPARED])
        with offline_provision(session) as sleep:
            result = self.run_pairing(session)
        self.assertEqual(result["operation"], "already-provisioned-no-write")
        self.assert_no_write(session)
        self.assertFalse(any(command in (0xA2, "chip") for command, _ in session.events))
        sleep.assert_not_called()

    def test_base_identity_root_check_only_reads(self):
        session = FakeSession(records=[OLD])
        with (patch.object(setup, "ReadOnlyUsbSession", return_value=session),
              patch.object(setup, "_sudo_identity", return_value=(1000, 1000)),
              patch.object(setup, "disable_core_dumps"),
              patch.object(setup, "_read_exact_secure_file", side_effect=FileNotFoundError)):
            result = setup._root_check()
        self.assertEqual(result["firmware"], BASE_FIRMWARE)
        self.assertEqual(result["pairing"], "host-psk-missing")
        self.assertEqual([command for command, _ in session.events],
                         [provision.COMMAND_NOP, provision.COMMAND_FIRMWARE_VERSION,
                          provision.COMMAND_GET_IAP_VERSION,
                          provision.COMMAND_PRESET_PSK_READ])

    def test_root_check_rejects_unknown_identity_and_iap(self):
        for arguments in ({"firmware": "GF3208_RTSEC_APP_10062"},
                          {"iap": "MILAN_RTSEC_IAP_10026"}):
            with self.subTest(arguments=arguments):
                session = FakeSession(**arguments)
                with (patch.object(setup, "ReadOnlyUsbSession", return_value=session),
                      patch.object(setup, "_sudo_identity", return_value=(1000, 1000)),
                      patch.object(setup, "disable_core_dumps"),
                      self.assertRaises(Exception)):
                    setup._root_check()
                self.assert_no_write(session)


if __name__ == "__main__":
    unittest.main()
