"""Windows Plug-and-Play inventory. Actual PTP connections live in camera.py."""
import json
import re
import subprocess
import sys

MODELS = ("X-E5", "X-T5", "X-T50", "X100VI", "X100V", "X-T4", "X-S20", "X-H2S", "X-H2", "X-M5", "X-E4", "GFX100 II", "GFX100S II", "GFX100RF")


def identify(name):
    text = name.upper()
    # Longest first avoids X-H2 matching X-H2S, etc.
    for model in sorted(MODELS, key=len, reverse=True):
        code = re.sub(r"[^A-Z0-9]", "", model)
        pattern = r"(?<![A-Z0-9])" + r"[^A-Z0-9]*".join(code) + r"(?![A-Z0-9])"
        if re.search(pattern, text):
            return model
    return None


def parse_inventory(records):
    if isinstance(records, dict):
        records = [records]
    devices = []
    seen = set()
    for row in records or []:
        identifier = row.get("InstanceId") or ""
        if "VID_04CB" not in identifier.upper() or identifier in seen:
            continue
        seen.add(identifier)
        name = row.get("FriendlyName") or "Fujifilm USB device"
        devices.append({"name": name, "model": identify(name), "instance_id": identifier,
                        "status": row.get("Status"), "recipe_transfer": False,
                        "recipe_read_candidate": identify(name) == "X-E5",
                        "note": "Inventory name only; use camera-info for a fresh PTP identity and capability read."})
    return devices


def discover():
    if sys.platform != "win32":
        raise ValueError("Automatic USB discovery currently requires Windows")
    script = ("$ErrorActionPreference='Stop'; "
              "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new(); "
              "$devices=@(Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -like '*VID_04CB*' } | "
              "Select-Object FriendlyName,InstanceId,Status); ConvertTo-Json -InputObject $devices -Compress")
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                            capture_output=True, encoding="utf-8", errors="replace", timeout=45,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise ValueError("Windows USB discovery failed: " + result.stderr.strip())
    return parse_inventory(json.loads(result.stdout.strip() or "[]"))
