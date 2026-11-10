import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from iro.core import EXAMPLE, Vault, inspect_backup, validate, write_json
from iro.devices import identify, parse_inventory


class CoreTests(unittest.TestCase):
    def test_delete_and_restore_preserve_other_recipes_and_slot_copies(self):
        with tempfile.TemporaryDirectory() as directory:
            vault = Vault(directory)
            vault.save(EXAMPLE)
            other = copy.deepcopy(EXAMPLE)
            other['name'] = 'Other look'
            vault.save(other)
            vault.push_mock(EXAMPLE['name'], 'C1')
            token = vault.delete(EXAMPLE['name'])
            self.assertEqual(vault.recipes(), [other])
            self.assertEqual(vault.slots()['C1'], EXAMPLE)
            self.assertEqual(Vault(directory).restore_deleted(token), EXAMPLE)
            self.assertEqual(vault.find(EXAMPLE['name']), EXAMPLE)

    def test_undo_refuses_to_replace_a_newer_recipe(self):
        with tempfile.TemporaryDirectory() as directory:
            vault = Vault(directory)
            vault.save(EXAMPLE)
            token = vault.delete(EXAMPLE['name'])
            newer = copy.deepcopy(EXAMPLE)
            newer['color'] = -2
            vault.save(newer)
            with self.assertRaises(ValueError):
                vault.restore_deleted(token)
            self.assertEqual(vault.find(EXAMPLE['name']), newer)
            self.assertTrue((vault.root / 'trash' / f'{token}.json').exists())
            with self.assertRaises(ValueError):
                vault.restore_deleted('../outside')

    def test_existing_fuji_adb_library_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict('os.environ', {'LOCALAPPDATA': directory}):
                self.assertEqual(Vault().root, root / 'Iro')
                (root / 'FujiADB').mkdir()
                self.assertEqual(Vault().root, root / 'FujiADB')
                (root / 'Iro').mkdir()
                self.assertEqual(Vault().root, root / 'Iro')

    def test_legacy_bundle_import(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_json(root / 'old.json', {'format': 'fuji-adb-bundle-v1', 'recipes': [EXAMPLE]})
            vault = Vault(root / 'vault')
            self.assertEqual(vault.import_file(root / 'old.json'), 1)
            self.assertEqual(vault.find(EXAMPLE['name']), EXAMPLE)

    def test_invalid_values(self):
        for field, value in (("highlight", -1.25), ("shadow", float("nan")), ("clarity", 6), ("color", True), ("base_simulation", "unknown")):
            with self.subTest(field=field):
                recipe = copy.deepcopy(EXAMPLE)
                recipe[field] = value
                with self.assertRaises(ValueError):
                    validate(recipe)

    def test_kelvin_required(self):
        recipe = copy.deepcopy(EXAMPLE)
        recipe["white_balance"]["mode"] = "kelvin"
        with self.assertRaises(ValueError):
            validate(recipe)
        recipe["white_balance"]["kelvin"] = 5600
        validate(recipe)

    def test_roundtrip_and_mock_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            a, b = Vault(root / "a"), Vault(root / "b")
            recipe = copy.deepcopy(EXAMPLE)
            recipe["name"] = "Warm / Chrome .. 日本語"
            a.save(recipe)
            a.push_mock(recipe["name"], "C7")
            self.assertEqual(Vault(root / "a").slots()["C7"], recipe)
            a.export(root / "bundle.json")
            self.assertEqual(b.import_file(root / "bundle.json"), 1)
            self.assertEqual(b.find(recipe["name"]), recipe)
            self.assertEqual(len(list((a.root / "recipes").glob("*.json"))), 1)

    def test_invalid_bundle_does_not_import_partial_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_json(root / "bad.json", {"format": "iro-bundle-v1", "recipes": [EXAMPLE, {}]})
            vault = Vault(root / "vault")
            with self.assertRaises(ValueError):
                vault.import_file(root / "bad.json")
            self.assertEqual(vault.recipes(), [])

    def test_device_detection(self):
        self.assertEqual(identify("FUJIFILM X-E5"), "X-E5")
        self.assertEqual(identify("FUJIFILM X-H2S"), "X-H2S")
        self.assertIsNone(identify("USB Camera"))
        self.assertIsNone(identify("FUJIFILM X-E50"))
        rows = [{"FriendlyName": "FUJIFILM X-E5", "InstanceId": "USB\\VID_04CB&PID_1234", "Status": "OK"},
                {"FriendlyName": "Other", "InstanceId": "USB\\VID_1234"}]
        found = parse_inventory(rows)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["model"], "X-E5")
        self.assertFalse(found[0]["recipe_transfer"])

    def test_backup_inspection_preserves_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "camera.DAT"
            path.write_bytes(bytes(range(256)))
            report = inspect_backup(path)
            self.assertEqual(report["bytes"], 256)
            self.assertEqual(path.read_bytes(), bytes(range(256)))
            self.assertFalse(report["decoded"])

    def test_usb_transfer_fails_before_writing(self):
        project = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, str(project / "run.py"), "--data-dir", directory,
                                     "push", "anything", "--slot", "C1", "--backend", "usb"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn("not implemented", result.stderr)
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
