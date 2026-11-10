"""Washi / sumi desktop theme, following Koban and ZenPDF's paper-and-ink palette."""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .core import EXAMPLE, SIMULATIONS, read_json, validate, write_json
from .devices import discover
from .camera import CameraError, FIELD_NAMES, read_camera_slots

ASSETS = Path(__file__).with_name("assets")
PALETTES = {
    "light": dict(app="#f5f3ee", surface="#fbfaf7", raised="#eeebe4", line="#e3dfd6", ink="#1f1e1c", muted="#5f5b54", accent="#b9432f", on="#fbfaf7"),
    "dark": dict(app="#141413", surface="#1a1a18", raised="#262522", line="#2d2c29", ink="#ebe7df", muted="#aaa59b", accent="#e0644c", on="#161614"),
}
WB_MODES = ("auto", "auto_ambience_priority", "daylight", "shade", "fluorescent_1", "fluorescent_2", "fluorescent_3", "incandescent", "underwater", "kelvin")


def pretty(value):
    return value.replace("_", " ").title() if isinstance(value, str) else str(value)


class RecipeApp:
    def __init__(self, root, vault):
        self.root, self.vault = root, vault
        self.theme = "light"
        try:
            self.theme = read_json(vault.root / "preferences.json").get("theme", "light")
        except (ValueError, OSError, AttributeError):
            pass
        if self.theme not in PALETTES:
            self.theme = "light"
        self.results = queue.Queue()
        self.scanning = False
        self.reading = False
        self.slot_mode = "camera"
        self.camera_snapshot = None
        try:
            previous = read_json(vault.root / "camera" / "latest.json")
            if previous.get("format") == "iro-camera-snapshot-v1" and previous.get("complete") and previous.get("selector_restored"):
                self.camera_snapshot = previous
        except (ValueError, OSError, AttributeError):
            pass
        self.camera = "No camera scanned"
        self.camera_note = "Connect your camera by USB, then detect."
        self.current = copy.deepcopy(EXAMPLE)
        self.snapshot = copy.deepcopy(self.current)
        self.active_name = None
        self.last_deleted = None
        self.status = tk.StringVar(value="Start with the example, or import a recipe from your library.")
        self.search = tk.StringVar()
        self.variables = {}
        root.title("Iro — Recipe Library")
        root.geometry("1280x880")
        root.minsize(1080, 760)
        root.iconbitmap(str(ASSETS / "app.ico"))
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind("<Control-s>", lambda e: self.guard(self.save))
        root.bind("<Control-o>", lambda e: self.guard(self.import_file))
        root.bind("<Control-n>", lambda e: self.new())
        self.search.trace_add("write", lambda *_: self.guard(self.refresh_library))
        self.build()
        root.after(150, self.poll)

    def guard(self, fn):
        try:
            return fn()
        except (ValueError, OSError, tk.TclError) as exc:
            messagebox.showerror("Iro", str(exc), parent=self.root)

    def frame(self, parent, kind="surface", **kw):
        return tk.Frame(parent, background=self.p[kind], **kw)

    def label(self, parent, text, size=10, color="ink", bold=False, **kw):
        return tk.Label(parent, text=text, background=parent.cget("background"), foreground=self.p[color], font=("Segoe UI", size, "bold" if bold else "normal"), **kw)

    def button(self, parent, text, fn, primary=False):
        return tk.Button(parent, text=text, command=lambda: self.guard(fn), background=self.p["ink"] if primary else self.p["surface"], foreground=self.p["on"] if primary else self.p["ink"], activebackground=self.p["accent"] if primary else self.p["raised"], activeforeground=self.p["on"] if primary else self.p["ink"], relief="flat", borderwidth=0, padx=13, pady=8, cursor="hand2", font=("Segoe UI", 10), highlightthickness=1, highlightbackground=self.p["line"], highlightcolor=self.p["accent"])

    def line(self, parent):
        self.frame(parent, "line", height=1).pack(fill="x")

    def build(self):
        self.p = PALETTES[self.theme]
        for widget in self.root.winfo_children():
            widget.destroy()
        self.root.configure(background=self.p["app"])
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TCombobox", fieldbackground=self.p["surface"], background=self.p["raised"], foreground=self.p["ink"], arrowcolor=self.p["muted"], bordercolor=self.p["line"], lightcolor=self.p["line"], darkcolor=self.p["line"], padding=7, font=("Segoe UI", 10))
        style.configure("Vertical.TScrollbar", background=self.p["raised"], troughcolor=self.p["app"], bordercolor=self.p["line"], arrowcolor=self.p["muted"], lightcolor=self.p["line"], darkcolor=self.p["line"])
        style.map("TCombobox", fieldbackground=[("readonly", self.p["surface"])], foreground=[("readonly", self.p["ink"])], selectbackground=[("readonly", self.p["raised"])], selectforeground=[("readonly", self.p["ink"])])
        self.root.option_add("*TCombobox*Listbox.background", self.p["surface"])
        self.root.option_add("*TCombobox*Listbox.foreground", self.p["ink"])
        header = self.frame(self.root)
        header.pack(fill="x")
        brand = self.frame(header)
        brand.pack(side="left", padx=23, pady=13)
        self.logo = tk.PhotoImage(file=str(ASSETS / "logo-64.png"))
        tk.Label(brand, image=self.logo, background=self.p["surface"], borderwidth=0, highlightthickness=0).pack(side="left", padx=(0, 11))
        wordmark = self.frame(brand)
        wordmark.pack(side="left")
        self.label(wordmark, "Iro", 17, bold=True).pack(anchor="w")
        self.label(wordmark, "THE RECIPE LIBRARY", 8, "muted").pack(anchor="w", pady=(3, 0))
        self.button(header, "Sumi / dark" if self.theme == "light" else "Washi / light", self.toggle_theme).pack(side="right", padx=(8, 24))
        self.button(header, "Export library", self.export_file).pack(side="right", padx=4)
        self.button(header, "Import recipes", self.import_file).pack(side="right", padx=4)
        self.line(self.root)
        middle = self.frame(self.root, "app")
        middle.pack(fill="both", expand=True)
        sidebar = self.frame(middle, width=248)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        self.frame(middle, "line", width=1).pack(side="left", fill="y")
        side_top = self.frame(sidebar)
        side_top.pack(fill="x", padx=20, pady=(24, 10))
        self.label(side_top, "YOUR COLLECTION", 8, "muted", True).pack(anchor="w")
        self.button(side_top, "+  New recipe", self.new).pack(fill="x", pady=(15, 12))
        self.label(side_top, "Search recipes", 9, "muted").pack(anchor="w", pady=(0, 5))
        tk.Entry(side_top, textvariable=self.search, relief="flat", background=self.p["raised"], foreground=self.p["ink"], insertbackground=self.p["ink"], font=("Segoe UI", 10), highlightthickness=1, highlightbackground=self.p["line"], highlightcolor=self.p["accent"]).pack(fill="x", ipady=7)
        self.count_label = self.label(sidebar, "", 9, "muted")
        self.count_label.pack(anchor="w", padx=20, pady=8)
        self.library = tk.Listbox(sidebar, borderwidth=0, relief="flat", highlightthickness=0, background=self.p["surface"], foreground=self.p["ink"], selectbackground=self.p["raised"], selectforeground=self.p["accent"], activestyle="none", exportselection=False, font=("Segoe UI", 11))
        self.library.pack(fill="both", expand=True, padx=20)
        self.library.bind("<<ListboxSelect>>", self.select_recipe)
        self.library.bind("<Delete>", lambda e: self.guard(self.delete_recipe))
        library_actions = self.frame(sidebar)
        library_actions.pack(fill="x", padx=20, pady=(10, 0))
        self.delete_button = self.button(library_actions, "Delete recipe", self.delete_recipe)
        self.delete_button.pack(fill="x")
        self.undo_button = self.button(library_actions, "Undo delete", self.undo_delete)
        self.undo_button.pack(fill="x", pady=(5, 0))
        self.label(sidebar, "A little less noise.\nA little more character.", 10, "muted", justify="left").pack(anchor="w", padx=20, pady=22)
        self.line(sidebar)
        self.label(sidebar, "LOCAL FIRST  /  v0.3.1", 8, "muted").pack(anchor="w", padx=20, pady=17)
        workspace = self.frame(middle, "app")
        workspace.pack(side="left", fill="both", expand=True, padx=26, pady=(22, 14))
        heading = self.frame(workspace, "app")
        heading.pack(fill="x", pady=(0, 14))
        self.label(heading, "Recipe studio", 23, bold=True).pack(side="left")
        self.label(heading, "色 と 記 憶   /   COLOR & MEMORY", 9, "muted").pack(side="right", pady=(10, 0))
        camera = self.frame(workspace, highlightbackground=self.p["line"], highlightthickness=1)
        camera.pack(fill="x", pady=(0, 16))
        camera_inner = self.frame(camera)
        camera_inner.pack(fill="x", padx=17, pady=12)
        camera_text = self.frame(camera_inner)
        camera_text.pack(side="left")
        self.camera_title = self.label(camera_text, self.camera, 12, bold=True)
        self.camera_title.pack(anchor="w")
        self.camera_subtitle = self.label(camera_text, self.camera_note, 9, "muted")
        self.camera_subtitle.pack(anchor="w", pady=(4, 0))
        self.read_button = self.button(camera_inner, "Reading…" if self.reading else "Read C1–C7", self.begin_read, True)
        self.read_button.pack(side="right", padx=(8, 0))
        self.scan_button = self.button(camera_inner, "Detecting…" if self.scanning else "Detect", self.scan)
        self.scan_button.pack(side="right")
        if self.scanning or self.reading:
            self.scan_button.configure(state="disabled")
            self.read_button.configure(state="disabled")
        self.label(workspace, "Create a look. Keep it close.", 11, "muted").pack(anchor="w", pady=(0, 10))
        scroll_frame = self.frame(workspace, "app")
        scroll_frame.pack(fill="both", expand=True)
        canvas = tk.Canvas(scroll_frame, background=self.p["app"], highlightthickness=0)
        scroll = ttk.Scrollbar(scroll_frame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        form = self.frame(canvas, "app")
        window = canvas.create_window((0, 0), window=form, anchor="nw")
        form.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window, width=e.width))
        def wheel(event):
            if canvas.winfo_exists() and canvas.winfo_height() < form.winfo_reqheight():
                canvas.yview_scroll(int(-event.delta / 120), "units")
        self.root.bind("<MouseWheel>", wheel)
        self.variables = {}
        foundation = self.section(form, "01", "The foundation")
        self.field(foundation, "Recipe name", "name", 0, 0, span=2)
        self.field(foundation, "Film simulation", "base_simulation", 1, 0, SIMULATIONS)
        self.field(foundation, "Dynamic range", "dynamic_range", 1, 1, ("DR100", "DR200", "DR400", "auto"))
        tone = self.section(form, "02", "Tone & detail")
        for i, (label, key, values) in enumerate((("Highlight", "highlight", tuple(x / 2 for x in range(-4, 9))), ("Shadow", "shadow", tuple(x / 2 for x in range(-4, 9))), ("Color", "color", tuple(range(-4, 5))), ("Sharpness", "sharpness", tuple(range(-4, 5))), ("Noise reduction", "noise_reduction", tuple(range(-4, 5))), ("Clarity", "clarity", tuple(range(-5, 6))))):
            self.field(tone, label, key, i // 3, i % 3, values)
        color = self.section(form, "03", "Color & atmosphere")
        for i, (label, key, values) in enumerate((("Grain strength", "grain_effect.roughness", ("off", "weak", "strong")), ("Grain size", "grain_effect.size", ("small", "large")), ("Color Chrome", "color_chrome_effect", ("off", "weak", "strong")), ("Color Chrome FX Blue", "color_chrome_fx_blue", ("off", "weak", "strong")))):
            self.field(color, label, key, i // 2, i % 2, values)
        wb = self.section(form, "04", "White balance")
        self.field(wb, "White balance", "white_balance.mode", 0, 0, WB_MODES)
        self.field(wb, "Temperature (K)", "white_balance.kelvin", 0, 1)
        self.field(wb, "Red shift", "white_balance.red_shift", 1, 0, tuple(range(-9, 10)))
        self.field(wb, "Blue shift", "white_balance.blue_shift", 1, 1, tuple(range(-9, 10)))
        self.variables["white_balance.mode"].trace_add("write", lambda *_: self.update_temperature())
        self.update_temperature()
        actions = self.frame(workspace, "app")
        actions.pack(fill="x", pady=12)
        self.label(actions, "Saved on this computer", 9, "muted").pack(side="left")
        self.button(actions, "Save recipe", self.save, True).pack(side="right")
        self.button(actions, "Edit JSON", self.edit_json).pack(side="right", padx=7)
        self.line(workspace)
        slot_header = self.frame(workspace, "app")
        slot_header.pack(fill="x", pady=(12, 8))
        self.slot_heading = self.label(slot_header, "", 8, "muted", True)
        self.slot_heading.pack(side="left")
        self.slot_toggle = self.button(slot_header, "", self.toggle_slots)
        self.slot_toggle.pack(side="right")
        self.slot_hint = self.label(slot_header, "", 8, "muted")
        self.slot_hint.pack(side="right", padx=8)
        self.slot_row = self.frame(workspace, "app")
        self.slot_row.pack(fill="x")
        self.label(workspace, "Camera reads preserve recipe values and restore the bank selector. FS1–FS3 dial recipes are separate.", 9, "muted").pack(anchor="w", pady=(8, 0))
        self.line(self.root)
        footer = self.frame(self.root)
        footer.pack(fill="x")
        tk.Label(footer, textvariable=self.status, background=self.p["surface"], foreground=self.p["muted"], font=("Segoe UI", 9), anchor="w").pack(side="left", padx=20, pady=10)
        self.guard(self.refresh_library)
        self.guard(self.refresh_slots)

    def section(self, parent, number, title):
        card = self.frame(parent, highlightbackground=self.p["line"], highlightthickness=1)
        card.pack(fill="x", pady=(0, 12))
        titlebar = self.frame(card)
        titlebar.pack(fill="x", padx=17, pady=(13, 4))
        self.label(titlebar, number, 9, "accent").pack(side="left", padx=(0, 9))
        self.label(titlebar, title, 11, bold=True).pack(side="left")
        fields = self.frame(card)
        fields.pack(fill="x", padx=10, pady=(0, 10))
        return fields

    def field(self, parent, label, key, row, column, values=None, span=1):
        parent.columnconfigure(column, weight=1, uniform="field")
        cell = self.frame(parent)
        cell.grid(row=row, column=column, columnspan=span, sticky="ew", padx=7, pady=7)
        self.label(cell, label, 9, "muted").pack(anchor="w", pady=(0, 5))
        value = self.current
        for segment in key.split("."):
            value = value.get(segment, 5600)
        var = tk.StringVar(value=pretty(value) if values is not None else str(value))
        self.variables[key] = var
        if values is not None:
            widget = ttk.Combobox(cell, values=[pretty(v) for v in values], textvariable=var, state="readonly", width=15)
        else:
            widget = tk.Entry(cell, textvariable=var, background=self.p["surface"], foreground=self.p["ink"], relief="flat", font=("Segoe UI", 11), insertbackground=self.p["ink"], highlightthickness=1, highlightbackground=self.p["line"], highlightcolor=self.p["accent"])
        widget.pack(fill="x", ipady=5 if values is None else 0)
        if key == "white_balance.kelvin":
            self.temperature = widget

    def update_temperature(self):
        self.temperature.configure(state="normal" if self.variables["white_balance.mode"].get().lower() == "kelvin" else "disabled", disabledbackground=self.p["raised"], disabledforeground=self.p["muted"])

    def recipe(self):
        recipe = copy.deepcopy(EXAMPLE)
        for key, var in self.variables.items():
            parts = key.split(".")
            target = recipe if len(parts) == 1 else recipe[parts[0]]
            value = var.get()
            if key == "white_balance.kelvin":
                if self.variables["white_balance.mode"].get().lower() != "kelvin":
                    continue
                value = int(value)
            elif key in ("highlight", "shadow"):
                value = float(value)
            elif key in ("color", "sharpness", "noise_reduction", "clarity", "white_balance.red_shift", "white_balance.blue_shift"):
                value = int(value)
            elif key != "name":
                value = value.lower().replace(" ", "_")
                if key == "dynamic_range" and value != "auto":
                    value = value.upper()
            target[parts[-1]] = value
        return validate(recipe)

    def can_discard(self):
        try:
            dirty = self.recipe() != self.snapshot
        except ValueError:
            dirty = True
        return not dirty or messagebox.askyesno("Unsaved recipe", "Discard your unsaved recipe changes?", parent=self.root)

    def refresh_library(self):
        if not hasattr(self, "library") or not self.library.winfo_exists():
            return
        recipes = sorted(self.vault.recipes(), key=lambda r: r["name"].casefold())
        self.library.delete(0, "end")
        for recipe in recipes:
            if self.search.get().casefold() in recipe["name"].casefold():
                self.library.insert("end", recipe["name"])
        self.count_label.configure(text=f"{len(recipes)} saved recipe{'s' if len(recipes) != 1 else ''}")
        for i in range(self.library.size()):
            if self.library.get(i) == self.active_name:
                self.library.selection_set(i)
        self.update_library_actions()

    def update_library_actions(self):
        self.delete_button.configure(state="normal" if self.library.curselection() else "disabled")
        self.undo_button.configure(state="normal" if self.last_deleted else "disabled")

    def delete_recipe(self):
        selection = self.library.curselection()
        if not selection:
            return
        name = self.library.get(selection[0])
        message = f'Move "{name}" to the local recipe trash? You can undo this deletion.'
        if name == self.active_name:
            try:
                dirty = self.recipe() != self.snapshot
            except ValueError:
                dirty = True
            if dirty:
                message += "\n\nUnsaved edits to this recipe will be discarded."
        if not messagebox.askyesno("Delete recipe", message, parent=self.root):
            return
        self.last_deleted = self.vault.delete(name)
        if self.active_name == name:
            recipe = copy.deepcopy(EXAMPLE)
            recipe["name"] = "Untitled recipe"
            self.load(recipe)
        else:
            self.refresh_library()
        self.status.set(f'Deleted "{name}" from the library. Use Undo delete to restore it.')

    def undo_delete(self):
        if not self.last_deleted:
            return
        recipe = self.vault.restore_deleted(self.last_deleted)
        self.last_deleted = None
        self.refresh_library()
        self.status.set(f'Restored "{recipe["name"]}" to the library.')

    def refresh_slots(self):
        self.slot_heading.configure(text="CAMERA C1–C7" if self.slot_mode == "camera" else "SIMULATED SLOTS")
        self.slot_toggle.configure(text="Simulator" if self.slot_mode == "camera" else "Camera snapshot")
        self.slot_hint.configure(text="Read-only saved snapshot" if self.slot_mode == "camera" else "Click to assign locally")
        for widget in self.slot_row.winfo_children():
            widget.destroy()
        slots = (self.camera_snapshot or {}).get("slots", dict.fromkeys(f"C{i}" for i in range(1, 8))) if self.slot_mode == "camera" else self.vault.slots()
        for i, (slot, recipe) in enumerate(slots.items()):
            self.slot_row.columnconfigure(i, weight=1, uniform="slot")
            fn = (lambda s=slot: self.view_camera_snapshot(s)) if self.slot_mode == "camera" else (lambda s=slot: self.assign(s))
            button = self.button(self.slot_row, slot + ("  ●" if recipe else "  —"), fn)
            button.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 5, 0))
            if recipe:
                button.configure(foreground=self.p["accent"])
            elif self.slot_mode == "camera":
                button.configure(state="disabled")

    def toggle_slots(self):
        self.current = self.recipe()
        self.slot_mode = "mock" if self.slot_mode == "camera" else "camera"
        self.build()

    def view_camera_snapshot(self, selected="C1"):
        snapshot = self.camera_snapshot
        if not snapshot:
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("Camera C1–C7 — Iro")
        dialog.geometry("1040x740")
        dialog.minsize(850, 550)
        dialog.configure(background=self.p["app"])
        info = snapshot["camera"]
        self.label(dialog, f"{info['model']}  /  Firmware {info['firmware']}", 17, bold=True).pack(anchor="w", padx=22, pady=(20, 5))
        self.label(dialog, f"Saved read: {snapshot['captured_at']}  ·  Original {snapshot['original_slot']} restored", 9, "muted").pack(anchor="w", padx=22)
        self.label(dialog, "C1–C7 shooting banks. This snapshot does not include the separate FS1–FS3 dial recipes.", 9, "muted").pack(anchor="w", padx=22, pady=(5, 15))
        body = self.frame(dialog, "app")
        body.pack(fill="both", expand=True, padx=22)
        slots = list(snapshot["slots"])
        names = tk.Listbox(body, width=25, background=self.p["surface"], foreground=self.p["ink"], selectbackground=self.p["raised"], selectforeground=self.p["accent"], font=("Segoe UI", 11), relief="flat", borderwidth=0, exportselection=False)
        names.pack(side="left", fill="y", padx=(0, 12))
        for slot in slots:
            names.insert("end", f"{slot}  /  {snapshot['slots'][slot]['name'] or 'Unnamed'}")
        notebook = ttk.Notebook(body)
        notebook.pack(side="left", fill="both", expand=True)
        texts = []
        for title in ("Recipe settings", "Raw camera properties"):
            panel = self.frame(notebook)
            notebook.add(panel, text=title)
            text = tk.Text(panel, background=self.p["surface"], foreground=self.p["ink"], font=("Consolas", 10), relief="flat", padx=18, pady=15, wrap="word")
            scroll = ttk.Scrollbar(panel, command=text.yview)
            text.configure(yscrollcommand=scroll.set)
            scroll.pack(side="right", fill="y")
            text.pack(fill="both", expand=True)
            texts.append(text)
        buttons = self.frame(dialog, "app")
        buttons.pack(fill="x", padx=22, pady=16)
        def chosen():
            return snapshot["slots"][slots[names.curselection()[0]]]
        def import_recipe():
            recipe = chosen()["recipe"]
            if recipe is not None and self.can_discard():
                dialog.destroy()
                self.load(recipe)
                self.status.set("Camera recipe loaded in the editor. Save to add it to your local library.")
        load = self.button(buttons, "Open in recipe editor", import_recipe, True)
        load.pack(side="right")
        def export():
            path = filedialog.asksaveasfilename(parent=dialog, title="Save exact camera snapshot", defaultextension=".json", initialfile="iro-xe5-camera-snapshot.json", filetypes=[("Camera snapshot", "*.json")])
            if path:
                write_json(path, snapshot)
        self.button(buttons, "Export snapshot", export).pack(side="left")
        def render(event=None):
            if not names.curselection():
                return
            slot = slots[names.curselection()[0]]
            record = chosen()
            lines = [f"{slot}  /  {record['name'] or '(unnamed on camera)'}", ""]
            for key, value in record["decoded"].items():
                if key == "name":
                    continue
                lines.append(pretty(key) + ": " + (json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else pretty(value)))
            if record["warnings"]:
                lines += ["", "UNMAPPED / UNREADABLE VALUES", *record["warnings"], "", "Raw values are preserved. Import is disabled until required fields can be decoded without guesses."]
            else:
                lines += ["", "The editor imports recipe fields. Extra camera-only properties remain in this snapshot."]
            raw = []
            for key, value in record["properties"].items():
                raw.append(f"{key}  {FIELD_NAMES.get(int(key, 16), 'Preset name')}\n  {json.dumps(value, ensure_ascii=False)}")
            for text, content in zip(texts, ("\n".join(lines), "\n\n".join(raw))):
                text.configure(state="normal")
                text.delete("1.0", "end")
                text.insert("1.0", content)
                text.configure(state="disabled")
            load.configure(state="normal" if record["recipe"] else "disabled")
        names.bind("<<ListboxSelect>>", render)
        names.selection_set(slots.index(selected) if selected in slots else 0)
        render()

    def select_recipe(self, event=None):
        selection = self.library.curselection()
        self.update_library_actions()
        if not selection:
            return
        name = self.library.get(selection[0])
        if name == self.active_name:
            return
        if self.can_discard():
            self.guard(lambda: self.load(self.vault.find(name), name))
        else:
            self.refresh_library()

    def load(self, recipe, active_name=None):
        self.current = copy.deepcopy(recipe)
        self.snapshot = copy.deepcopy(recipe)
        self.active_name = active_name
        self.build()

    def new(self):
        if self.can_discard():
            recipe = copy.deepcopy(EXAMPLE)
            recipe["name"] = "Untitled recipe"
            self.load(recipe)
            self.status.set("New recipe — choose a film simulation and make it yours.")

    def save(self):
        recipe = self.recipe()
        self.vault.save(recipe)
        self.current = copy.deepcopy(recipe)
        self.snapshot = copy.deepcopy(recipe)
        self.active_name = recipe["name"]
        self.refresh_library()
        self.status.set(f"Saved {recipe['name']} to your library.")

    def assign(self, slot):
        self.save()
        self.vault.push_mock(self.active_name, slot)
        self.refresh_slots()
        self.status.set(f"{self.active_name} → simulated {slot}. No camera settings changed.")

    def import_file(self):
        path = filedialog.askopenfilename(parent=self.root, title="Import recipe or library", filetypes=[("Recipe JSON", "*.json")])
        if path:
            count = self.vault.import_file(path)
            self.refresh_library()
            self.status.set(f"Imported {count} recipe(s). Matching names replaced in your library.")

    def export_file(self):
        path = filedialog.asksaveasfilename(parent=self.root, title="Export saved library", defaultextension=".json", filetypes=[("Recipe bundle", "*.json")])
        if path:
            self.vault.export(path)
            self.status.set("Saved library exported. Unsaved editor changes are not included.")

    def toggle_theme(self):
        self.current = self.recipe()
        self.theme = "dark" if self.theme == "light" else "light"
        write_json(self.vault.root / "preferences.json", {"theme": self.theme})
        self.build()

    def edit_json(self):
        recipe = self.recipe()
        dialog = tk.Toplevel(self.root)
        dialog.title("Edit recipe JSON — Iro")
        dialog.geometry("650x720")
        dialog.configure(background=self.p["app"])
        dialog.transient(self.root)
        dialog.grab_set()
        text = tk.Text(dialog, background=self.p["surface"], foreground=self.p["ink"], insertbackground=self.p["ink"], font=("Consolas", 11), undo=True, relief="flat", padx=18, pady=18)
        text.pack(fill="both", expand=True, padx=15, pady=15)
        text.insert("1.0", json.dumps(recipe, indent=2, ensure_ascii=False))
        def apply():
            self.current = validate(json.loads(text.get("1.0", "end")))
            dialog.destroy()
            self.build()
            self.status.set("JSON applied to the editor. Save to keep it in your library.")
        self.button(dialog, "Apply to editor", apply, True).pack(anchor="e", padx=15, pady=(0, 15))

    def scan(self):
        if self.scanning or self.reading:
            return
        self.scanning = True
        self.scan_button.configure(text="Detecting…", state="disabled")
        self.read_button.configure(state="disabled")
        self.status.set("Checking Windows for connected Fujifilm cameras…")
        def worker():
            try:
                self.results.put(("discovery", discover(), None))
            except Exception as exc:
                self.results.put(("discovery", None, str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def begin_read(self):
        if self.reading or self.scanning:
            return
        self.reading = True
        self.read_button.configure(text="Reading…", state="disabled")
        self.scan_button.configure(state="disabled")
        self.status.set("Reading camera banks. Recipe values stay unchanged; the selector will be restored.")
        def worker():
            try:
                snapshot = read_camera_slots(progress=lambda msg: self.results.put(("progress", msg, None)))
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                write_json(self.vault.root / "camera" / f"xe5-{stamp}.json", snapshot)
                write_json(self.vault.root / "camera" / "latest.json", snapshot)
                self.results.put(("read", snapshot, None))
            except Exception as exc:
                snapshot = exc.snapshot if isinstance(exc, CameraError) else None
                if snapshot is not None:
                    try:
                        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                        write_json(self.vault.root / "camera" / f"failed-{stamp}.json", snapshot)
                    except OSError:
                        pass
                self.results.put(("read", snapshot, str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        try:
            kind, data, error = self.results.get_nowait()
        except queue.Empty:
            pass
        else:
            if kind == "progress":
                self.status.set(data)
                self.root.after(50, self.poll)
                return
            if kind == "read":
                self.reading = False
                self.read_button.configure(text="Read C1–C7", state="normal")
                self.scan_button.configure(state="normal")
                if error:
                    self.status.set("Camera read failed. Check the camera connection and selector restoration status.")
                    messagebox.showerror("Camera read", error, parent=self.root)
                else:
                    self.camera_snapshot = data
                    self.camera = f"{data['camera']['model']} · Firmware {data['camera']['firmware']}"
                    self.camera_note = "Seven banks read · Original selector restored"
                    count = sum(bool(r["warnings"]) for r in data["slots"].values())
                    self.status.set(f"Read C1–C7; restored {data['original_slot']}. " + (f"{count} bank(s) contain unmapped values, preserved in the snapshot." if count else "Camera snapshot saved."))
                    self.camera_title.configure(text=self.camera)
                    self.camera_subtitle.configure(text=self.camera_note)
                    self.slot_mode = "camera"
                    self.refresh_slots()
                    self.view_camera_snapshot()
                self.root.after(150, self.poll)
                return
            devices = data
            self.scanning = False
            self.scan_button.configure(text="Detect cameras", state="normal")
            self.read_button.configure(state="normal")
            if error:
                self.camera, self.camera_note = "Discovery unavailable", "Windows could not provide the USB inventory."
                self.status.set("Camera discovery failed. Your recipe library is still available.")
                messagebox.showerror("Camera discovery", error, parent=self.root)
            elif not devices:
                self.camera, self.camera_note = "No Fujifilm camera found", "Check the USB cable and camera connection mode."
                self.status.set("No Fujifilm USB device detected.")
            else:
                names = list(dict.fromkeys(d["model"] or d["name"] for d in devices))
                self.camera = " / ".join(names)
                self.camera_note = "Detected over USB · Use Read C1–C7 for X-E5 bank access"
                self.status.set("Detected " + ", ".join(names) + ". Your camera settings have not been changed.")
            self.camera_title.configure(text=self.camera)
            self.camera_subtitle.configure(text=self.camera_note)
        self.root.after(150, self.poll)

    def close(self):
        if self.reading:
            messagebox.showinfo("Camera read in progress", "Wait for the read and bank-selector restoration to finish before closing Iro.", parent=self.root)
            return
        if self.can_discard():
            self.root.destroy()


def launch(vault):
    root = tk.Tk()
    RecipeApp(root, vault)
    root.mainloop()
