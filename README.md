# Iro

[![Tests](https://github.com/duck28/iro/actions/workflows/tests.yml/badge.svg)](https://github.com/duck28/iro/actions/workflows/tests.yml)
[![Release](https://github.com/duck28/iro/actions/workflows/release.yml/badge.svg)](https://github.com/duck28/iro/actions/workflows/release.yml)

[Download for Windows](https://github.com/duck28/iro/releases/latest) · [Report an issue](https://github.com/duck28/iro/issues) · [MIT license](LICENSE)

<img src="branding/iro-logo-original.png" width="160" alt="Iro Fuji and sun logo" />

A Windows Fujifilm recipe library with a paper-and-ink desktop interface, a CLI, and native **X-E5 C1–C7 reads** using the installed Windows Portable Devices driver. Iro means “color.” Formerly Fuji-ADB.

## Start on Windows

Open `dist/Iro-0.3.1-x64.msi` for the branded per-user Windows Installer wizard. The packaged app includes Python, Tkinter and the native camera helper; you do not need Python or C++ installed to use it. It adds a Start menu shortcut and supports Windows uninstall. This local preview is unsigned.

For a portable run, keep the entire `dist/0.3.1/Iro` directory together and open `Iro.exe` inside it. Versioned build folders let an earlier app keep running while a new version builds. The installer contains the desktop app; the source checkout also provides the CLI.

From source, Python 3.11+ with Tkinter is sufficient for the local library:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
.\launch.cmd
```

The execution-policy override applies only to that process. No system policy is changed. `setup.ps1` creates `.venv` and checks Python/Tkinter. Building the native camera helper additionally requires Visual Studio C++ Build Tools and a Windows SDK:

```powershell
cmd /c native\build.cmd
```

Set `VSDEVCMD` to your Visual Studio `VsDevCmd.bat` if it is not in the default VS 2022 Build Tools location. The helper builds with a static C runtime and does not need a separate Visual C++ redistributable on destination PCs.

## Read your X-E5

1. On the camera select **Network/USB Settings → Connection Mode → USB RAW CONV./BACKUP RESTORE**.
2. Use a data-capable USB cable, enable USB communication, reconnect and turn the camera on. Close other camera applications.
3. Open Iro and click **Read C1–C7**. The app verifies model/firmware through PTP, reads each bank, restores the original bank selector and saves the snapshot.
4. Click a camera slot to inspect decoded settings, warnings and raw property bytes. Export the entire snapshot, or open a fully decoded recipe in the editor and save it locally.

Reading temporarily changes the **bank selector D18C**. No names or recipe values are written. Iro restores the original selector and checks it. If the camera disconnects before restoration, the operation reports an error with the original slot; check the camera before continuing. Both Python and the native helper guard restoration on normal failures. Hard termination cannot guarantee restoration.

The X-E5's **FS1–FS3 film-simulation dial recipes are separate from C1–C7** and are not read by this implementation. The camera panel's **Detect** action only inventories connected Fujifilm devices; **Read C1–C7** performs the actual connection and bank read. Real camera slots are shown separately from the local simulator.

### Verified hardware result

On 2026-11-10 the connected X-E5 reported firmware **1.12**, all seven banks were read, and original selector **C1 was restored and verified**. The observed banks returned blank names and equivalent Provia-based settings. Grain D195 returned **6**, which is not yet mapped confidently. It remains visible as an unknown value, with exact bytes preserved; those banks cannot be converted into editable library recipes without resolving the required field. This does not establish whether the camera's separate FS dial slots contain recipes.

Unknown values, sentinels and unreadable fields never silently become defaults. A complete snapshot can contain partially decoded banks. See [camera protocol notes](docs/CAMERA_PROTOCOL.md) for the precise limits and reference material. Camera recipe writes and DAT editing remain disabled.

## CLI

```powershell
.\iro.cmd devices
.\iro.cmd camera-info
.\iro.cmd list-slots --backend usb
.\iro.cmd pull --all --backend usb --output .\captures\xe5-snapshot.json
.\iro.cmd import .\examples\warm-chrome.json
.\iro.cmd list
.\iro.cmd show "Warm Chrome Demo"
.\iro.cmd validate .\examples\warm-chrome.json
.\iro.cmd bundle export .\recipes.json
.\iro.cmd push "Warm Chrome Demo" --slot C1 --backend mock
.\iro.cmd list-slots --backend mock
.\iro.cmd backup-inspect C:\path\camera.DAT
```

`camera-info` performs a fresh PTP identity/capability read. `list-slots` and `pull` with `--backend usb` scan the real camera; `pull` saves raw and decoded fields as an `iro-camera-snapshot-v1` file. It exits nonzero for a failed scan or unverified restoration; if possible, it also saves the partial report. It never silently falls back to the simulator.

For multiple connected Fujifilm devices, obtain WPD IDs with `src\iro\bin\wpd-bridge.exe --list` and supply `--device-id ID` to `camera-info`, `list-slots` or `pull`. Other models may be identified, but bank selection is currently restricted to a verified X-E5. USB `push` returns an explicit unsupported error.

`--backend mock` always refers to local simulated slots. JSON library bundles and exact camera snapshots are different formats. A snapshot preserves camera-only settings that the portable editor does not cover. `bundle export` includes saved library recipes, not unsaved editor changes. Legacy `fuji-adb-bundle-v1` imports and the `fuji-tool.cmd` launcher remain supported.

## Library and interface

- Form-based recipe editing, optional JSON editor, validation, search and import/export.
- Koban/ZenPDF-inspired washi light and sumi dark palettes; persistent theme selection.
- Generated Japanese-inspired Fuji/sun mark in the application and MSI. Original and prompt in `branding/`; runtime icons in `src/iro/assets/`.
- Ctrl+S saves, Ctrl+O imports, Ctrl+N starts a recipe. Unsaved drafts are checked before closing or switching recipes.
- Select a saved recipe and click **Delete recipe** (or press Delete with the recipe list focused). Confirming moves that library entry to local `trash/`; **Undo delete** restores the last deletion during this app session. Trash files remain available after restart. Undo refuses to replace a newer recipe with the same name. Simulated slots and camera snapshots retain their saved copies.

New libraries use `%LOCALAPPDATA%\Iro`. An existing `%LOCALAPPDATA%\FujiADB` library is reused when no Iro library exists, preserving recipes and preferences without copying or overwriting them. `--data-dir PATH` before a command selects a separate local library. Saving/importing an existing exact recipe name replaces that library entry; renaming creates a new entry.

GUI camera reads save timestamped snapshots plus `camera/latest.json` under the active library. Failed reads are saved separately when possible. Uninstalling preserves the library. Device serial numbers are not retained in snapshots.

## Build the MSI

Build on Windows x64 with Python, .NET SDK, Visual C++ Build Tools and Windows SDK installed:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\build-msi.ps1 -InstallBuildTools
```

The first build downloads pinned PyInstaller and WiX 5.0.2 tooling locally. Later builds can omit `-InstallBuildTools`. The script compiles the WPD bridge, packages the desktop runtime and verifies the Tkinter/helper files before building the MSI. Build from a normal Windows terminal; restricted sandboxes can interfere with Tkinter discovery. It retains the previous MSI upgrade family so Iro can replace the earlier preview installation.

GitHub Actions tests Python 3.11 and 3.13, then builds and publishes the MSI and checksum when a matching `vMAJOR.MINOR.PATCH` tag is pushed. Release tags must match the version in `pyproject.toml`. Build outputs and local camera captures are excluded from the source repository.

Installer artwork and notice are in `packaging/`. To regenerate the included installer bitmaps, run `python packaging/prepare_artwork.py` with Pillow installed. The generated source logo is retained unchanged.

## Development checks

```powershell
$env:PYTHONPATH = 'src'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
# On a Windows desktop, include the Tk editor checks:
$env:FUJI_GUI_TESTS = '1'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Unit tests use a fake transport and never require hardware. They cover strict PTP parsing, encodings, unknown/sentinel values, wrong model/mode rejection, disconnects, partial reads and verified selector restoration. The regression fixture contains the serial-free C1 property response captured from X-E5 firmware 1.12. Live hardware verification is separate from the automated suite.

`src/iro/core.py` owns local storage, `devices.py` owns Windows inventory, `camera.py` owns decoding/scans, and `native/wpd_bridge.cpp` owns constrained WPD transport. The Python package has no third-party runtime dependencies. See [third-party protocol attribution](THIRD_PARTY_NOTICES.md).
