"""Shared test setup: make the panel and project modules importable."""

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "control_panel"
PANEL_CONFIG = PANEL / "config.json"
PANEL_EXAMPLE = PANEL / "config.example.json"

# The panel reads its config at import time. Use the example when the machine
# has no live config (CI / a fresh checkout); the real config is git-ignored.
if not PANEL_CONFIG.exists():
    shutil.copyfile(PANEL_EXAMPLE, PANEL_CONFIG)

for path in (str(ROOT), str(PANEL)):
    if path not in sys.path:
        sys.path.insert(0, path)

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
