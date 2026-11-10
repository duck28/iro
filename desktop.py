"""Windowed entry point for the packaged Windows app."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from iro.core import Vault
from iro.gui import launch

if __name__ == "__main__":
    launch(Vault())
