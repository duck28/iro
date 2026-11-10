"""X-E5 preset reads using the installed Windows WPD driver.

The native bridge has no recipe-write API. The only outgoing property value is
D18C (bank selector), restored and checked after every scan.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import queue
import struct
import subprocess
import sys
import threading
import time

from .core import SLOTS, validate

MODE_GUIDANCE = "Set Network/USB Settings > Connection Mode > USB RAW CONV./BACKUP RESTORE, reconnect the camera, and close other camera apps."
FIELD_NAMES = {
    0xD18E: "Image size", 0xD18F: "Image quality", 0xD190: "Dynamic range",
    0xD191: "D191", 0xD192: "Film simulation", 0xD193: "Monochrome warm/cool",
    0xD194: "Monochrome magenta/green", 0xD195: "Grain effect", 0xD196: "Color Chrome",
    0xD197: "Color Chrome FX Blue", 0xD198: "Smooth skin", 0xD199: "White balance",
    0xD19A: "WB red shift", 0xD19B: "WB blue shift", 0xD19C: "Color temperature",
    0xD19D: "Highlight", 0xD19E: "Shadow", 0xD19F: "Color", 0xD1A0: "Sharpness",
    0xD1A1: "High ISO noise reduction", 0xD1A2: "Clarity", 0xD1A3: "Long exposure NR",
    0xD1A4: "Color space", 0xD1A5: "D1A5",
}
FILM = dict(enumerate(("provia", "velvia", "astia", "pro_neg_hi", "pro_neg_std", "monochrome",
    "monochrome_ye", "monochrome_r", "monochrome_g", "sepia", "classic_chrome", "acros",
    "acros_ye", "acros_r", "acros_g", "eterna", "classic_neg", "eterna_bleach_bypass", "nostalgic_neg", "reala_ace"), 1))
WB = {2: "auto", 4: "daylight", 6: "incandescent", 8: "underwater", 0x8001: "fluorescent_1",
      0x8002: "fluorescent_2", 0x8003: "fluorescent_3", 0x8006: "shade", 0x8007: "kelvin", 0x8021: "auto_ambience_priority"}
GRAIN = {1: ("off", "small"), 2: ("weak", "small"), 3: ("strong", "small"), 4: ("weak", "large"), 5: ("strong", "large")}
NR = {0x8000: -4, 0x7000: -3, 0x4000: -2, 0x3000: -1, 0x2000: 0, 0x1000: 1, 0: 2, 0x6000: 3, 0x5000: 4}


class CameraError(ValueError):
    def __init__(self, message, snapshot=None):
        super().__init__(message)
        self.snapshot = snapshot


class CameraPropertyError(CameraError):
    """A property was rejected by the camera; the session remains synchronized."""


class Dataset:
    def __init__(self, data):
        self.data, self.offset = data, 0

    def take(self, size):
        if size < 0 or self.offset + size > len(self.data):
            raise CameraError("Truncated PTP dataset")
        value = self.data[self.offset:self.offset + size]
        self.offset += size
        return value

    def u16(self):
        return struct.unpack("<H", self.take(2))[0]

    def u32(self):
        return struct.unpack("<I", self.take(4))[0]

    def text(self):
        count = self.take(1)[0]
        if count == 0:
            return ""
        raw = self.take(count * 2)
        if raw[-2:] != b"\0\0":
            raise CameraError("PTP string is missing its terminator")
        try:
            return raw[:-2].decode("utf-16-le", errors="strict")
        except UnicodeError as exc:
            raise CameraError("Invalid PTP UTF-16 string") from exc

    def array(self):
        count = self.u32()
        if count > (len(self.data) - self.offset) // 2:
            raise CameraError("Invalid PTP capability array")
        return [self.u16() for _ in range(count)]


def parse_device_info(data):
    reader = Dataset(data)
    reader.u16(); reader.u32(); reader.u16(); reader.text(); reader.u16()
    operations = reader.array()
    reader.array()
    properties = reader.array()
    reader.array(); reader.array()
    manufacturer, model, firmware = reader.text(), reader.text(), reader.text()
    reader.text()  # Consume the serial without storing it in snapshots or logs.
    if reader.offset != len(data):
        raise CameraError("Unexpected trailing PTP DeviceInfo bytes")
    return dict(manufacturer=manufacturer, model=model, firmware=firmware, operations=operations, properties=properties)


def raw_value(code, data):
    if code == 0xD18D:
        reader = Dataset(data)
        text = reader.text()
        if reader.offset != len(data):
            raise CameraError("Unexpected bytes after preset name")
        return text
    if len(data) != 2:
        raise CameraError(f"Property 0x{code:04X}: expected a 16-bit value, got {len(data)} bytes")
    signed = code in (0xD193, 0xD194, 0xD19A, 0xD19B, 0xD19D, 0xD19E, 0xD19F, 0xD1A0, 0xD1A2)
    return int.from_bytes(data, "little", signed=signed)


def decode_slot(slot, properties):
    """Keep unknown/sentinel values explicit; never manufacture defaults."""
    warnings, decoded = [], {}
    def value(code):
        record = properties.get(f"0x{code:04X}", {})
        if "value" not in record:
            raise CameraError(f"{FIELD_NAMES.get(code, hex(code))}: unreadable")
        return record["value"]
    def mapped(code, mapping):
        raw = value(code)
        if raw not in mapping:
            raise CameraError(f"{FIELD_NAMES.get(code, hex(code))}: unmapped value {raw} (0x{raw & 0xFFFF:04X})")
        return mapping[raw]
    def field(key, fn):
        try:
            decoded[key] = fn()
        except (ValueError, TypeError) as exc:
            warnings.append(str(exc))
    name = properties.get("0xD18D", {}).get("value", "")
    if not isinstance(name, str):
        name = ""
    decoded["name"] = name.strip() or f"X-E5 {slot}"
    field("base_simulation", lambda: mapped(0xD192, FILM))
    field("dynamic_range", lambda: mapped(0xD190, {100: "DR100", 200: "DR200", 400: "DR400"}))
    field("grain_effect", lambda: dict(zip(("roughness", "size"), mapped(0xD195, GRAIN))))
    field("color_chrome_effect", lambda: mapped(0xD196, {1: "off", 2: "weak", 3: "strong"}))
    field("color_chrome_fx_blue", lambda: mapped(0xD197, {1: "off", 2: "weak", 3: "strong"}))
    def white_balance():
        wb = dict(mode=mapped(0xD199, WB), red_shift=value(0xD19A), blue_shift=value(0xD19B))
        if wb["mode"] == "kelvin":
            wb["kelvin"] = value(0xD19C)
        return wb
    field("white_balance", white_balance)
    for key, code in (("highlight", 0xD19D), ("shadow", 0xD19E), ("color", 0xD19F), ("sharpness", 0xD1A0), ("clarity", 0xD1A2)):
        def tone(code=code):
            raw = value(code)
            if raw == -32768:
                raise CameraError(f"{FIELD_NAMES[code]}: camera sentinel value (not assumed to be zero)")
            return raw / 10
        field(key, tone)
    field("noise_reduction", lambda: mapped(0xD1A1, NR))
    recipe = None
    if not warnings:
        try:
            recipe = validate(decoded)
        except ValueError as exc:
            warnings.append(f"Portable recipe validation: {exc}")
    return dict(name=name, display_name=decoded["name"], decoded=decoded, recipe=recipe, warnings=warnings, properties=properties)


class WpdBridge:
    def __init__(self, device_id=None, timeout=45):
        self.timeout, self.process = timeout, None
        self.device_id = device_id
        self.responses = queue.Queue()
        self.broken = False

    def __enter__(self):
        if sys.platform != "win32":
            raise CameraError("Camera connection currently requires Windows")
        helper = Path(__file__).with_name("bin") / "wpd-bridge.exe"
        if not helper.is_file():
            raise CameraError("Native WPD bridge is missing. Run native/build.cmd or use the packaged Iro app.")
        command = [str(helper)]
        if self.device_id:
            command += ["--device-id", self.device_id]
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        text=True, encoding="utf-8", bufsize=1, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        def reader():
            try:
                for line in self.process.stdout:
                    self.responses.put(line)
            finally:
                self.responses.put(None)
        threading.Thread(target=reader, daemon=True).start()
        try:
            self.identity = self.receive()
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def receive(self):
        try:
            line = self.responses.get(timeout=self.timeout)
        except queue.Empty as exc:
            self.broken = True
            raise CameraError("Camera operation timed out. Reconnect the camera if necessary; selector restoration may require checking.") from exc
        if line is None:
            self.broken = True
            raise CameraError("Camera connection ended unexpectedly")
        try:
            response = json.loads(line)
        except ValueError as exc:
            self.broken = True
            raise CameraError("Malformed response from native camera bridge") from exc
        if not isinstance(response, dict) or not isinstance(response.get("ok"), bool):
            self.broken = True
            raise CameraError("Invalid response envelope from native camera bridge")
        if not response["ok"]:
            message = response.get("error", "Camera command failed")
            if message in ("Camera PTP response 0x2002", "Camera PTP response 0x200A"):
                raise CameraPropertyError(message)
            raise CameraError(message)
        if "data" not in response:
            self.broken = True
            raise CameraError("Missing response data from native camera bridge")
        return response["data"]

    def request(self, command):
        if self.broken or self.process.poll() is not None:
            raise CameraError("Camera bridge has disconnected")
        try:
            self.process.stdin.write(command + "\n")
            self.process.stdin.flush()
        except OSError as exc:
            raise CameraError("Camera bridge input failed") from exc
        return self.receive()

    def bytes(self, command):
        data = self.request(command)
        try:
            return bytes.fromhex(data["hex"])
        except (KeyError, TypeError, ValueError) as exc:
            raise CameraError("Invalid binary data from native bridge") from exc

    def __exit__(self, *_):
        if not self.process:
            return
        # EOF also triggers the native bridge's restoration guard.
        try:
            self.process.stdin.close()
        except OSError:
            pass
        try:
            self.process.wait(timeout=self.timeout + 5)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=10)
        finally:
            self.process.stdout.close()
            self.process.stderr.close()


def inspect_camera(device_id=None, bridge_factory=WpdBridge):
    with bridge_factory(device_id=device_id) as bridge:
        info = parse_device_info(bridge.bytes("ptp-info"))
        info["preset_interface"] = all(p in info["properties"] for p in range(0xD18C, 0xD1A6))
        info["backend"] = "windows-wpd"
        return info


def read_camera_slots(device_id=None, progress=None, bridge_factory=WpdBridge):
    snapshot = dict(format="iro-camera-snapshot-v1", backend="windows-wpd", captured_at=datetime.now(timezone.utc).isoformat(),
                    camera=None, original_slot=None, selector_restored=False, complete=False, slots={})
    with bridge_factory(device_id=device_id) as bridge:
        info = parse_device_info(bridge.bytes("ptp-info"))
        snapshot["camera"] = info
        if info["model"] != "X-E5" or "FUJI" not in info["manufacturer"].upper():
            raise CameraError("Preset reads are currently enabled only for a verified Fujifilm X-E5", snapshot)
        if not {0x1015, 0x1016} <= set(info["operations"]) or not {0xD18C, 0xD18D} <= set(info["properties"]):
            raise CameraError("The camera does not expose the preset interface. " + MODE_GUIDANCE, snapshot)
        original = raw_value(0xD18C, bridge.bytes("get D18C"))
        if original not in range(1, 8):
            raise CameraError(f"Cannot safely preserve bank selector value {original}", snapshot)
        snapshot["original_slot"] = f"C{original}"
        failure = None
        selected = False
        try:
            for index, slot in enumerate(SLOTS, 1):
                if progress:
                    progress(f"Reading {slot}…")
                selected = True  # A failed response may still have reached the camera.
                bridge.request(f"select {index}")
                time.sleep(.1)
                if raw_value(0xD18C, bridge.bytes("get D18C")) != index:
                    raise CameraError(f"Bank selector readback mismatch for {slot}")
                fields = {}
                for code in range(0xD18D, 0xD1A6):
                    key = f"0x{code:04X}"
                    try:
                        data = bridge.bytes(f"get {code:04X}")
                        fields[key] = dict(hex=data.hex())
                        try:
                            fields[key]["value"] = raw_value(code, data)
                        except CameraError as exc:
                            fields[key]["error"] = str(exc)
                    except CameraPropertyError as exc:
                        fields[key] = dict(error=str(exc))
                snapshot["slots"][slot] = decode_slot(slot, fields)
            snapshot["complete"] = True
        except BaseException as exc:
            failure = exc
        finally:
            try:
                if selected:
                    bridge.request("restore")
                if raw_value(0xD18C, bridge.bytes("get D18C")) != original:
                    raise CameraError("Original selector readback mismatch")
                snapshot["selector_restored"] = True
            except Exception as exc:
                snapshot["restoration_error"] = str(exc)
                raise CameraError(f"Could not verify restoration of {snapshot['original_slot']}. Check the camera before use. {exc}", snapshot) from failure
        if failure:
            raise CameraError(f"Camera read failed: {failure}", snapshot) from failure
    return snapshot
