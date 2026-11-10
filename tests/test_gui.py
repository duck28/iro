"""Opt-in live-Tk checks for the recipe editor's conversions and persistence."""
import os
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from iro.core import EXAMPLE, Vault


@unittest.skipUnless(os.environ.get("FUJI_GUI_TESTS") == "1", "Set FUJI_GUI_TESTS=1 on a Windows desktop")
class EditorTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from iro.gui import RecipeApp
        self.temp = tempfile.TemporaryDirectory()
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = RecipeApp(self.root, Vault(Path(self.temp.name)))

    def tearDown(self):
        for timer in self.root.tk.call("after", "info"):
            self.root.after_cancel(timer)
        self.root.destroy()
        self.temp.cleanup()

    def test_form_roundtrip(self):
        self.assertEqual(self.app.recipe(), EXAMPLE)
        self.app.variables["white_balance.mode"].set("Kelvin")
        self.app.variables["white_balance.kelvin"].set("5600")
        self.app.variables["shadow"].set("-0.5")
        recipe = self.app.recipe()
        self.assertEqual(recipe["white_balance"]["kelvin"], 5600)
        self.assertEqual(recipe["shadow"], -.5)
        self.app.variables["white_balance.mode"].set("Daylight")
        self.assertNotIn("kelvin", self.app.recipe()["white_balance"])

    def test_delete_cancel_confirm_and_undo(self):
        self.app.save()
        with patch('iro.gui.messagebox.askyesno', return_value=False):
            self.app.delete_recipe()
        self.assertEqual(self.app.vault.find(EXAMPLE['name']), EXAMPLE)
        with patch('iro.gui.messagebox.askyesno', return_value=True):
            self.app.delete_recipe()
        self.assertEqual(self.app.vault.recipes(), [])
        self.assertIsNone(self.app.active_name)
        self.assertEqual(self.app.variables['name'].get(), 'Untitled recipe')
        self.assertEqual(str(self.app.undo_button.cget('state')), 'normal')
        self.app.variables['name'].set('Unsaved new look')
        self.app.undo_delete()
        self.assertEqual(self.app.vault.find(EXAMPLE['name']), EXAMPLE)
        self.assertEqual(self.app.variables['name'].get(), 'Unsaved new look')
        self.assertEqual(str(self.app.undo_button.cget('state')), 'disabled')

    def test_theme_preserves_unsaved_recipe_and_save(self):
        self.app.variables["name"].set("Unpublished look")
        self.app.variables["base_simulation"].set("Reala Ace")
        self.app.toggle_theme()
        self.assertEqual(self.app.theme, "dark")
        self.assertEqual(self.app.recipe()["base_simulation"], "reala_ace")
        self.assertEqual(self.app.variables["name"].get(), "Unpublished look")
        self.app.save()
        self.assertEqual(self.app.vault.find("Unpublished look"), self.app.recipe())
        self.app.assign("C3")
        self.assertEqual(self.app.vault.slots()["C3"]["name"], "Unpublished look")

    def test_camera_result_preserves_invalid_draft_and_blocks_unknown_import(self):
        from iro.camera import decode_slot
        path = Path(__file__).with_name('fixtures') / 'xe5-1.12-c1.json'
        properties = json.loads(path.read_text(encoding='utf-8'))['properties']
        snapshot = dict(format='iro-camera-snapshot-v1', camera={'model': 'X-E5', 'firmware': '1.12'},
                        complete=True, selector_restored=True, original_slot='C1', captured_at='2026-11-10T00:00:00Z',
                        slots={f'C{i}': decode_slot(f'C{i}', properties) for i in range(1, 8)})
        self.app.variables['name'].set('')
        self.app.reading = True
        self.app.results.put(('read', snapshot, None))
        self.app.poll()
        self.assertEqual(self.app.variables['name'].get(), '')
        self.assertFalse(self.app.reading)
        self.assertEqual(self.app.camera_snapshot, snapshot)
        self.assertTrue(all(r['recipe'] is None for r in snapshot['slots'].values()))
        dialogs = [w for w in self.root.winfo_children() if w.winfo_class() == 'Toplevel']
        self.assertEqual(len(dialogs), 1)
        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)
        load = next(w for w in descendants(dialogs[0]) if w.winfo_class() == 'Button' and w.cget('text') == 'Open in recipe editor')
        self.assertEqual(str(load.cget('state')), 'disabled')
