import copy
import json
from pathlib import Path
import struct
import unittest
from unittest.mock import patch

from iro.camera import CameraError, CameraPropertyError, Dataset, decode_slot, parse_device_info, raw_value, read_camera_slots
from iro.core import EXAMPLE


def ptp_string(value):
    raw = value.encode("utf-16-le") + b"\0\0"
    return bytes([len(raw) // 2]) + raw


def device_info(model="X-E5", preset=True):
    def array(values):
        return struct.pack("<I", len(values)) + b"".join(struct.pack("<H", v) for v in values)
    return (struct.pack("<HIH", 100, 6, 100) + ptp_string("Fujifilm") + struct.pack("<H", 0)
            + array([0x1001, 0x1015, 0x1016]) + array([]) + array(list(range(0xD18C, 0xD1A6)) if preset else [])
            + array([]) + array([]) + ptp_string("FUJIFILM") + ptp_string(model) + ptp_string("1.12") + ptp_string("PRIVATE-SERIAL"))


def fixture():
    path = Path(__file__).with_name("fixtures") / "xe5-1.12-c1.json"
    return json.loads(path.read_text(encoding="utf-8"))["properties"]


class FakeBridge:
    def __init__(self, model="X-E5", preset=True, fail_slot=None, fail_restore=False, missing_prop=None):
        self.model, self.preset = model, preset
        self.fail_slot, self.fail_restore, self.missing_prop = fail_slot, fail_restore, missing_prop
        self.original = self.selected = 2
        self.commands = []
        self.values = fixture()
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.closed = True

    def bytes(self, command):
        self.commands.append(command)
        if command == "ptp-info":
            return device_info(self.model, self.preset)
        code = int(command[4:], 16)
        if code == 0xD18C:
            return struct.pack("<H", self.selected)
        if code == self.missing_prop:
            raise CameraPropertyError("Camera PTP response 0x200A")
        if code == 0xD18D:
            return ptp_string(f"Look {self.selected}")
        return bytes.fromhex(self.values[f"0x{code:04X}"]["hex"])

    def request(self, command):
        self.commands.append(command)
        if command == "restore":
            if self.fail_restore:
                raise CameraError("Cable disconnected during restoration")
            self.selected = self.original
        else:
            self.selected = int(command[7:])
            if self.selected == self.fail_slot:
                raise CameraError("Bank selection failed after reaching the camera")


class CameraTests(unittest.TestCase):
    def read(self, bridge):
        with patch("iro.camera.time.sleep"):
            return read_camera_slots(bridge_factory=lambda **kw: bridge)

    def test_device_identity_is_strict_and_serial_is_not_retained(self):
        info = parse_device_info(device_info())
        self.assertEqual(info["model"], "X-E5")
        self.assertEqual(info["firmware"], "1.12")
        self.assertNotIn("PRIVATE-SERIAL", json.dumps(info))
        for data in (device_info()[:-1], device_info() + b"\0", b"\xff" * 5):
            with self.assertRaises(CameraError):
                parse_device_info(data)

    def test_ptp_strings_and_half_tones(self):
        self.assertEqual(Dataset(ptp_string("色彩" )).text(), "色彩")
        self.assertEqual(raw_value(0xD19E, struct.pack("<h", -15)), -15)
        self.assertEqual(raw_value(0xD199, struct.pack("<H", 0x8006)), 0x8006)
        for invalid in (b"\x02\0", b"\x01ab"):
            with self.assertRaises(CameraError):
                Dataset(invalid).text()

    def test_live_grain_six_remains_unknown(self):
        raw = fixture()
        result = decode_slot("C1", raw)
        self.assertEqual(result["decoded"]["base_simulation"], "provia")
        self.assertIsNone(result["recipe"])
        self.assertIn("unmapped value 6", result["warnings"][0])
        self.assertEqual(result["properties"], raw)

    def test_known_recipe_decode_matches_library_schema(self):
        raw = fixture()
        values = {0xD18D: EXAMPLE["name"], 0xD190: 400, 0xD192: 11, 0xD195: 3,
                  0xD196: 3, 0xD197: 2, 0xD199: 4, 0xD19A: 2, 0xD19B: -5,
                  0xD19D: -10, 0xD19E: -15, 0xD19F: 20, 0xD1A0: -20, 0xD1A1: 0x8000, 0xD1A2: -20}
        for code, value in values.items():
            raw[f"0x{code:04X}"]["value"] = value
        result = decode_slot("C3", raw)
        self.assertEqual(result["warnings"], [])
        self.assertEqual(result["recipe"], EXAMPLE)

    def test_sentinel_is_not_invented_as_zero(self):
        raw = fixture()
        raw["0xD195"]["value"] = 1
        raw["0xD19E"]["value"] = -32768
        result = decode_slot("C1", raw)
        self.assertIsNone(result["recipe"])
        self.assertNotIn("shadow", result["decoded"])

    def test_seven_banks_are_read_and_original_restored(self):
        bridge = FakeBridge()
        report = self.read(bridge)
        self.assertEqual(list(report["slots"]), [f"C{i}" for i in range(1, 8)])
        self.assertEqual([r["name"] for r in report["slots"].values()], [f"Look {i}" for i in range(1, 8)])
        self.assertTrue(report["selector_restored"])
        self.assertTrue(report["complete"])
        self.assertEqual(bridge.selected, 2)
        self.assertTrue(bridge.closed)
        self.assertEqual([c for c in bridge.commands if c.startswith("select ")], [f"select {i}" for i in range(1, 8)])
        self.assertFalse(any(c.startswith("set ") for c in bridge.commands))

    def test_selection_failure_still_restores_and_preserves_partial_read(self):
        bridge = FakeBridge(fail_slot=4)
        with self.assertRaises(CameraError) as caught:
            self.read(bridge)
        self.assertEqual(bridge.selected, 2)
        self.assertIn("restore", bridge.commands)
        self.assertTrue(caught.exception.snapshot["selector_restored"])
        self.assertFalse(caught.exception.snapshot["complete"])
        self.assertEqual(len(caught.exception.snapshot["slots"]), 3)

    def test_restoration_failure_is_never_reported_as_success(self):
        with self.assertRaises(CameraError) as caught:
            self.read(FakeBridge(fail_restore=True))
        self.assertFalse(caught.exception.snapshot["selector_restored"])
        self.assertIn("Could not verify restoration of C2", str(caught.exception))

    def test_wrong_model_or_mode_never_selects_banks(self):
        for bridge in (FakeBridge(model="X-T5"), FakeBridge(preset=False)):
            with self.subTest(model=bridge.model, preset=bridge.preset):
                with self.assertRaises(CameraError):
                    self.read(bridge)
                self.assertFalse(any(c.startswith("select ") for c in bridge.commands))

    def test_unreadable_property_is_preserved_without_defaults(self):
        report = self.read(FakeBridge(missing_prop=0xD19F))
        for record in report["slots"].values():
            self.assertIsNone(record["recipe"])
            self.assertIn("error", record["properties"]["0xD19F"])
            self.assertNotIn("color", record["decoded"])

    def test_disconnect_during_property_read_aborts_and_restores(self):
        bridge = FakeBridge()
        original = bridge.bytes
        def disconnected(command):
            if command == "get D198":
                raise CameraError("Camera connection ended unexpectedly")
            return original(command)
        bridge.bytes = disconnected
        with self.assertRaises(CameraError):
            self.read(bridge)
        self.assertIn("restore", bridge.commands)
        self.assertEqual(bridge.selected, bridge.original)
