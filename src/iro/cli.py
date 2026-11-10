import argparse
import json
import subprocess
import sys

from .core import EXAMPLE, SLOTS, Vault, inspect_backup, read_json, validate, write_json
from .devices import discover
from .camera import CameraError, inspect_camera, read_camera_slots


def main(argv=None):
    parser = argparse.ArgumentParser(description="Iro: Windows recipe library and X-E5 bank reader.")
    parser.add_argument("--data-dir", help="Override local recipe/simulator storage")
    sub = parser.add_subparsers(dest="command", required=True)
    for cmd in ("gui", "devices", "list", "example"):
        sub.add_parser(cmd)
    info = sub.add_parser("camera-info")
    info.add_argument("--device-id", help="Explicit WPD identifier when multiple cameras are connected")
    for cmd in ("import", "validate", "backup-inspect"):
        sub.add_parser(cmd).add_argument("file")
    sub.add_parser("show").add_argument("name")
    slots = sub.add_parser("list-slots")
    slots.add_argument("--backend", choices=("mock", "usb"), required=True)
    slots.add_argument("--device-id")
    push = sub.add_parser("push")
    push.add_argument("name")
    push.add_argument("--slot", choices=SLOTS, required=True)
    push.add_argument("--backend", choices=("mock", "usb"), required=True)
    pull = sub.add_parser("pull")
    pull.add_argument("--all", action="store_true", required=True)
    pull.add_argument("--output", required=True)
    pull.add_argument("--backend", choices=("mock", "usb"), required=True)
    pull.add_argument("--device-id")
    bundle = sub.add_parser("bundle").add_subparsers(dest="action", required=True)
    bundle.add_parser("export").add_argument("file")
    args = parser.parse_args(argv)
    vault = Vault(args.data_dir)
    try:
        if args.command == "push" and args.backend == "usb":
            raise ValueError("USB recipe writing is not implemented. Camera access supports reads only.")
        if args.command == "gui":
            from .gui import launch
            launch(vault)
            return 0
        if args.command == "devices":
            output = discover()
        elif args.command == "camera-info":
            output = inspect_camera(args.device_id)
        elif args.command == "example":
            output = EXAMPLE
        elif args.command == "list":
            output = [r["name"] for r in vault.recipes()]
        elif args.command == "show":
            output = vault.find(args.name)
        elif args.command == "import":
            output = {"imported": vault.import_file(args.file)}
        elif args.command == "validate":
            validate(read_json(args.file))
            output = {"valid": True, "scope": "Portable recipe schema; camera compatibility unverified"}
        elif args.command == "bundle":
            vault.export(args.file)
            output = {"exported": args.file}
        elif args.command == "list-slots":
            output = read_camera_slots(args.device_id) if args.backend == "usb" else {"backend": "mock", "slots": vault.slots()}
        elif args.command == "push":
            vault.push_mock(args.name, args.slot)
            output = {"backend": "mock", "slot": args.slot, "recipe": args.name}
        elif args.command == "pull":
            if args.backend == "usb":
                snapshot = read_camera_slots(args.device_id)
                write_json(args.output, snapshot)
                output = {"backend": "windows-wpd", "exported": args.output, "slots": len(snapshot["slots"]),
                          "selector_restored": snapshot["selector_restored"],
                          "warnings": {s: r["warnings"] for s, r in snapshot["slots"].items() if r["warnings"]}}
            else:
                recipes = {r["name"]: r for r in vault.slots().values() if r is not None}
                write_json(args.output, {"format": "iro-bundle-v1", "recipes": list(recipes.values())})
                output = {"backend": "mock", "exported": args.output}
        else:
            output = inspect_backup(args.file)
        print(json.dumps(output, indent=2, ensure_ascii=True))
        return 0
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        if isinstance(exc, CameraError) and exc.snapshot is not None and args.command == "pull":
            try:
                write_json(args.output, exc.snapshot)
            except OSError as save_error:
                print(f"Could not save partial camera report: {save_error}", file=sys.stderr)
        print(f"Error: {exc}", file=sys.stderr)
        return 1
