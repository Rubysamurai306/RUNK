#!/usr/bin/env python3
import os
import json
import signal
import subprocess
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib

APP_ID = "com.rafael.runkmax"

# Repo layout (this file is max/runk-max.py)
THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = THIS_DIR.parent
ENGINE_PATH = (REPO_ROOT / "minimal" / "runk-engine.sh").resolve()

# Config locations (user config, not inside repo)
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "runk-max"
CONFIG_PATH = CONFIG_DIR / "current.json"

PRESETS_DIR = THIS_DIR / "presets"

DEFAULT_CONFIG = {
    # Movement set (evdev keycodes)
    "keys": {"W": 17, "A": 30, "S": 31, "D": 32},
    "enable_diagonals": True,

    # Timing (seconds)
    "min_delay": 0.20,
    "max_delay": 0.80,

    # Press duration (seconds)
    "press_min": 0.05,
    "press_max": 0.18,

    # Humanizat
