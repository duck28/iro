from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import uuid

SIMULATIONS = (
    "provia", "velvia", "astia", "classic_chrome", "pro_neg_hi", "pro_neg_std",
    "classic_neg", "nostalgic_neg", "eterna", "eterna_bleach_bypass", "reala_ace",
    "acros", "acros_r", "acros_ye", "acros_g", "monochrome", "monochrome_r",
    "monochrome_ye", "monochrome_g", "sepia",
)
SLOTS = tuple(f"C{i}" for i in range(1, 8))
EXAMPLE = {
    "name": "Warm Chrome Demo", "base_simulation": "classic_chrome",
    "dynamic_range": "DR400", "grain_effect": {"roughness": "strong", "size": "small"},
    "color_chrome_effect": "strong", "color_chrome_fx_blue": "weak",
    "white_balance": {"mode": "daylight", "red_shift": 2, "blue_shift": -5},
    "highlight": -1.0, "shadow": -1.5, "color": 2, "sharpness": -2,
    "noise_reduction": -4, "clarity": -2,
}


def choice(value, choices, field):
    if value not in choices:
        raise ValueError(f"{field}: expected one of {', '.join(map(str, choices))}")


def number(value, low, high, field, step=1):
    if (type(value) not in (int, float) or not math.isfinite(value)
            or not low <= value <= high or not (value / step).is_integer()):
        raise ValueError(f"{field}: expected {low}..{high} in steps of {step}")


def validate(recipe):
    """Validate the portable library format, not camera-specific compatibility."""
    if not isinstance(recipe, dict) or set(recipe) != set(EXAMPLE):
        raise ValueError("Recipe must contain exactly the fields in the example recipe")
    if not isinstance(recipe["name"], str) or not recipe["name"].strip() or len(recipe["name"]) > 80:
        raise ValueError("name: expected 1..80 characters")
    choice(recipe["base_simulation"], SIMULATIONS, "base_simulation")
    choice(recipe["dynamic_range"], ("DR100", "DR200", "DR400", "auto"), "dynamic_range")
    grain = recipe["grain_effect"]
    if not isinstance(grain, dict) or set(grain) != {"roughness", "size"}:
        raise ValueError("grain_effect: requires roughness and size")
    choice(grain["roughness"], ("off", "weak", "strong"), "grain_effect.roughness")
    choice(grain["size"], ("small", "large"), "grain_effect.size")
    for key in ("color_chrome_effect", "color_chrome_fx_blue"):
        choice(recipe[key], ("off", "weak", "strong"), key)
    wb = recipe["white_balance"]
    if not isinstance(wb, dict) or not {"mode", "red_shift", "blue_shift"} <= set(wb) or set(wb) - {"mode", "red_shift", "blue_shift", "kelvin"}:
        raise ValueError("white_balance: requires mode, red_shift, blue_shift; optional kelvin")
    choice(wb["mode"], ("auto", "auto_ambience_priority", "daylight", "shade", "fluorescent_1", "fluorescent_2", "fluorescent_3", "incandescent", "underwater", "kelvin"), "white_balance.mode")
    for key in ("red_shift", "blue_shift"):
        number(wb[key], -9, 9, f"white_balance.{key}")
    if wb["mode"] == "kelvin":
        number(wb.get("kelvin"), 2500, 10000, "white_balance.kelvin")
    elif "kelvin" in wb:
        raise ValueError("white_balance.kelvin requires mode=kelvin")
    for key in ("highlight", "shadow"):
        number(recipe[key], -2, 4, key, .5)
    for key in ("color", "sharpness", "noise_reduction"):
        number(recipe[key], -4, 4, key)
    number(recipe["clarity"], -5, 5, "clarity")
    return recipe


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.write("\n")
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


class Vault:
    def __init__(self, root=None):
        if root is not None:
            self.root = Path(root)
        else:
            base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share"))
            current, legacy = base / "Iro", base / "FujiADB"
            self.root = legacy if legacy.exists() and not current.exists() else current

    def recipes(self):
        return [validate(read_json(p)) for p in sorted((self.root / "recipes").glob("*.json"))]

    def save(self, recipe):
        validate(recipe)
        digest = hashlib.sha256(recipe["name"].encode("utf-8")).hexdigest()
        write_json(self.root / "recipes" / f"{digest}.json", recipe)

    def find(self, name):
        for recipe in self.recipes():
            if recipe["name"] == name:
                return recipe
        raise ValueError(f"Recipe not found: {name}")

    def delete(self, name):
        """Remove a library recipe, retaining a recoverable copy in local trash."""
        digest = hashlib.sha256(name.encode("utf-8")).hexdigest()
        source = self.root / "recipes" / f"{digest}.json"
        recipe = validate(read_json(source))
        if recipe["name"] != name:
            raise ValueError("Recipe name does not match its library file")
        token = uuid.uuid4().hex
        trash = self.root / "trash"
        trash.mkdir(parents=True, exist_ok=True)
        os.replace(source, trash / f"{token}.json")
        return token

    def restore_deleted(self, token):
        if not isinstance(token, str) or len(token) != 32 or any(c not in "0123456789abcdef" for c in token):
            raise ValueError("Invalid deleted-recipe identifier")
        source = self.root / "trash" / f"{token}.json"
        recipe = validate(read_json(source))
        digest = hashlib.sha256(recipe["name"].encode("utf-8")).hexdigest()
        target = self.root / "recipes" / f"{digest}.json"
        if target.exists():
            raise ValueError(f"A recipe named {recipe['name']} already exists; undo would replace it")
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, target)
        return recipe

    def import_file(self, path):
        data = read_json(path)
        if isinstance(data, dict) and data.get("format") in ("iro-bundle-v1", "fuji-adb-bundle-v1"):
            items = data.get("recipes")
            if not isinstance(items, list):
                raise ValueError("Bundle recipes must be an array")
        else:
            items = [data]
        for item in items:
            validate(item)
        names = [r["name"] for r in items]
        if len(set(names)) != len(names):
            raise ValueError("Bundle contains duplicate recipe names")
        for item in items:
            self.save(item)
        return len(items)

    def export(self, path):
        write_json(path, {"format": "iro-bundle-v1", "recipes": self.recipes()})

    def slots(self):
        path = self.root / "mock-slots.json"
        if not path.exists():
            return dict.fromkeys(SLOTS)
        data = read_json(path)
        if not isinstance(data, dict) or set(data) != set(SLOTS):
            raise ValueError("Invalid simulated slot file")
        for recipe in data.values():
            if recipe is not None:
                validate(recipe)
        return data

    def push_mock(self, name, slot):
        choice(slot, SLOTS, "slot")
        data = self.slots()
        data[slot] = self.find(name)
        write_json(self.root / "mock-slots.json", data)


def inspect_backup(path):
    path = Path(path)
    data = path.read_bytes()
    return {"file": str(path.resolve()), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "header_hex": data[:32].hex(" "), "decoded": False,
            "note": "Read-only inspection. No DAT schema, offsets or checksum assumed."}
