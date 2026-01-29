#!/usr/bin/env python3
# FILE: RUNK-MAX/runk-max.py
"""
RUNK-MAX (Wayland-oriented)

Storage (repo stays clean):
- Current config:
  $XDG_CONFIG_HOME/runk-max/current.json  OR  ~/.config/runk-max/current.json
- Presets:
  $XDG_CONFIG_HOME/runk-max/presets/*.json  OR  ~/.config/runk-max/presets/*.json

First run:
- If current.json missing, seed from presets/Default.json if present.
- If presets missing, auto-create Default.json, Gaming.json, subtle.json in user presets dir.

CLI:
- --reset  deletes current.json (next launch reseeds from Default.json)

UI syncing:
- Guard prevents programmatic UI updates (preset load) from triggering on_any_change() and
  overwriting config with half-applied values.
"""
from __future__ import annotations

import json
import os
import random
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

APP_ID = "com.rafael.runkmax"

DEFAULT_CONFIG: dict = {
    "keys": {
        "W": {"code": 17, "enabled": True, "label": "W"},
        "A": {"code": 30, "enabled": True, "label": "A"},
        "S": {"code": 31, "enabled": True, "label": "S"},
        "D": {"code": 32, "enabled": True, "label": "D"},
    },
    "enable_diagonals": True,
    "min_delay": 0.25,
    "max_delay": 0.90,
    "press_min": 0.06,
    "press_max": 0.20,
    "idle_enabled": True,
    "idle_chance": 10,
    "idle_min": 1.0,
    "idle_max": 3.5,
    "double_tap_enabled": True,
    "double_tap_chance": 8,
}


def _deepcopy_jsonish(obj):
    return json.loads(json.dumps(obj))


def get_user_config_dir() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else (Path.home() / ".config")
    return base / "runk-max"


def get_user_config_path() -> Path:
    return get_user_config_dir() / "current.json"


def get_user_presets_dir() -> Path:
    return get_user_config_dir() / "presets"


def load_json(path: Path, fallback: dict) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            return normalize_config(d, fallback)
    except FileNotFoundError:
        pass
    except Exception:
        pass
    return _deepcopy_jsonish(fallback)


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    tmp.replace(path)


def normalize_config(cfg: dict, fallback: dict) -> dict:
    merged = _deepcopy_jsonish(fallback)
    for k, v in cfg.items():
        merged[k] = v

    merged.setdefault("keys", _deepcopy_jsonish(fallback["keys"]))

    for k in ("W", "A", "S", "D"):
        if k not in merged["keys"] or not isinstance(merged["keys"][k], dict):
            merged["keys"][k] = _deepcopy_jsonish(fallback["keys"][k])
        merged["keys"][k].setdefault("code", fallback["keys"][k]["code"])
        merged["keys"][k].setdefault("enabled", fallback["keys"][k]["enabled"])
        merged["keys"][k].setdefault("label", fallback["keys"][k].get("label", k))

    def b(x, default=False):
        return bool(x) if isinstance(x, (bool, int)) else default

    def f(x, default=0.0):
        try:
            return float(x)
        except Exception:
            return default

    def i(x, default=0):
        try:
            return int(x)
        except Exception:
            return default

    def s(x, default=""):
        return str(x) if isinstance(x, (str, int, float, bool)) else default

    merged["enable_diagonals"] = b(merged.get("enable_diagonals", True), True)
    merged["min_delay"] = f(merged.get("min_delay", 0.25), 0.25)
    merged["max_delay"] = f(merged.get("max_delay", 0.90), 0.90)
    merged["press_min"] = f(merged.get("press_min", 0.06), 0.06)
    merged["press_max"] = f(merged.get("press_max", 0.20), 0.20)
    merged["idle_enabled"] = b(merged.get("idle_enabled", True), True)
    merged["idle_chance"] = i(merged.get("idle_chance", 10), 10)
    merged["idle_min"] = f(merged.get("idle_min", 1.0), 1.0)
    merged["idle_max"] = f(merged.get("idle_max", 3.5), 3.5)
    merged["double_tap_enabled"] = b(merged.get("double_tap_enabled", True), True)
    merged["double_tap_chance"] = i(merged.get("double_tap_chance", 8), 8)

    for k in ("W", "A", "S", "D"):
        merged["keys"][k]["enabled"] = b(merged["keys"][k].get("enabled", True), True)
        merged["keys"][k]["code"] = i(
            merged["keys"][k].get("code", fallback["keys"][k]["code"]),
            fallback["keys"][k]["code"],
        )
        merged["keys"][k]["label"] = s(merged["keys"][k].get("label", k), k)

    if merged["max_delay"] < merged["min_delay"]:
        merged["max_delay"] = merged["min_delay"]
    if merged["press_max"] < merged["press_min"]:
        merged["press_max"] = merged["press_min"]
    if merged["idle_max"] < merged["idle_min"]:
        merged["idle_max"] = merged["idle_min"]

    merged["idle_chance"] = max(2, merged["idle_chance"])
    merged["double_tap_chance"] = max(2, merged["double_tap_chance"])
    return merged


def _friendly_key_name(keyval: int) -> str:
    name = Gdk.keyval_name(keyval) or ""
    if not name:
        return "Unknown"
    if len(name) == 1:
        return name.upper()
    return name.replace("_", " ").title()


def _sanitize_preset_name(name: str) -> str:
    name = name.strip()
    name = re.sub(r"\s+", " ", name)
    if not name:
        return ""
    if not re.fullmatch(r"[A-Za-z0-9 _\-\.\(\)]+", name):
        return ""
    return name


def ensure_default_presets_exist() -> None:
    presets_dir = get_user_presets_dir()
    presets_dir.mkdir(parents=True, exist_ok=True)

    default_path = presets_dir / "Default.json"
    gaming_path = presets_dir / "Gaming.json"
    subtle_path = presets_dir / "subtle.json"

    if not default_path.exists():
        save_json(
            default_path,
            {
                "keys": {
                    "W": {"code": 17, "enabled": True, "label": "W"},
                    "A": {"code": 30, "enabled": False, "label": "A"},
                    "S": {"code": 31, "enabled": False, "label": "S"},
                    "D": {"code": 32, "enabled": False, "label": "D"},
                },
                "enable_diagonals": False,
                "min_delay": 0.25,
                "max_delay": 0.90,
                "press_min": 0.06,
                "press_max": 0.20,
                "idle_enabled": True,
                "idle_chance": 10,
                "idle_min": 1.0,
                "idle_max": 3.5,
                "double_tap_enabled": True,
                "double_tap_chance": 8,
            },
        )

    if not gaming_path.exists():
        save_json(gaming_path, normalize_config(_deepcopy_jsonish(DEFAULT_CONFIG), DEFAULT_CONFIG))

    if not subtle_path.exists():
        save_json(
            subtle_path,
            {
                "keys": {
                    "W": {"code": 17, "enabled": True, "label": "W"},
                    "A": {"code": 30, "enabled": True, "label": "A"},
                    "S": {"code": 31, "enabled": True, "label": "S"},
                    "D": {"code": 32, "enabled": True, "label": "D"},
                },
                "enable_diagonals": True,
                "min_delay": 0.8,
                "max_delay": 1.6,
                "press_min": 0.05,
                "press_max": 0.12,
                "idle_enabled": True,
                "idle_chance": 6,
                "idle_min": 2.0,
                "idle_max": 5.0,
                "double_tap_enabled": True,
                "double_tap_chance": 20,
            },
        )


def handle_cli_reset_if_requested(argv: list[str]) -> tuple[bool, list[str]]:
    flag = "--reset"
    if flag not in argv:
        return False, argv

    ensure_default_presets_exist()
    cfg = get_user_config_path()
    try:
        cfg.unlink(missing_ok=True)
    except TypeError:
        if cfg.exists():
            cfg.unlink()

    print(f"[RUNK] Reset complete: deleted {cfg}")
    filtered = [a for a in argv if a != flag]
    return True, filtered


class EngineThread:
    def __init__(self):
        self._stop = threading.Event()
        self._pause = threading.Event()
        self.thread: threading.Thread | None = None

        self.ydotoold_proc: subprocess.Popen | None = None
        self.socket_path: str | None = None
        self.started_ydotoold: bool = False
        self._ydotool_lock = threading.Lock()

    def start(self, config: dict, on_status):
        if self.thread and self.thread.is_alive():
            return
        self._stop.clear()
        self._pause.clear()
        self.thread = threading.Thread(target=self._run, args=(config, on_status), daemon=True)
        self.thread.start()

    def stop(self):
        self._stop.set()
        self._pause.clear()
        if self.thread:
            self.thread.join(timeout=1.5)
        self.thread = None
        self._stop_ydotoold()

    def toggle_pause(self):
        if self._pause.is_set():
            self._pause.clear()
        else:
            self._pause.set()

    def _run(self, config: dict, on_status):
        def status(s: str):
            GLib.idle_add(on_status, s)

        enabled = {k: v for k, v in config["keys"].items() if v.get("enabled")}
        if len(enabled) < 2:
            status("Stopped: enable at least 2 keys")
            return

        vert = [config["keys"][k]["code"] for k in ("W", "S") if config["keys"][k]["enabled"]]
        horiz = [config["keys"][k]["code"] for k in ("A", "D") if config["keys"][k]["enabled"]]
        enable_diag = bool(config.get("enable_diagonals", True)) and (len(vert) > 0 and len(horiz) > 0)

        if not self._ensure_ydotoold():
            status("Stopped: ydotoold missing or failed")
            return

        status("Running")

        min_delay = float(config["min_delay"])
        max_delay = float(config["max_delay"])
        press_min = float(config["press_min"])
        press_max = float(config["press_max"])

        idle_enabled = bool(config.get("idle_enabled", True))
        idle_chance = int(config.get("idle_chance", 10))
        idle_min = float(config.get("idle_min", 1.0))
        idle_max = float(config.get("idle_max", 3.5))

        double_enabled = bool(config.get("double_tap_enabled", True))
        double_chance = int(config.get("double_tap_chance", 8))

        env = os.environ.copy()
        if self.socket_path:
            env["YDOTOOL_SOCKET"] = self.socket_path

        def press_key(code: int):
            subprocess.run(
                ["ydotool", "key", f"{code}:1"],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(random.uniform(press_min, press_max))
            subprocess.run(
                ["ydotool", "key", f"{code}:0"],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

        def maybe_double(code: int):
            press_key(code)
            if double_enabled and random.randint(1, max(2, double_chance)) == 1:
                time.sleep(random.uniform(0.03, 0.12))
                press_key(code)

        paused_reported = False

        while not self._stop.is_set():
            while self._pause.is_set() and not self._stop.is_set():
                if not paused_reported:
                    status("Paused")
                    paused_reported = True
                time.sleep(0.15)

            if self._stop.is_set():
                break

            paused_reported = False
            status("Running")

            if idle_enabled and random.randint(1, max(2, idle_chance)) == 1:
                time.sleep(random.uniform(idle_min, idle_max))

            move_type = random.choice(["axis", "diag"]) if enable_diag else "axis"

            if move_type == "diag":
                keys = [random.choice(vert), random.choice(horiz)]
            else:
                if vert and horiz:
                    axis = random.choice(["vert", "horiz"])
                elif vert:
                    axis = "vert"
                else:
                    axis = "horiz"

                if axis == "vert":
                    first = random.choice(vert)
                    opp = [c for c in vert if c != first]
                    second = opp[0] if opp else first
                    keys = [first, second]
                else:
                    first = random.choice(horiz)
                    opp = [c for c in horiz if c != first]
                    second = opp[0] if opp else first
                    keys = [first, second]

            if random.random() < 0.5:
                keys = list(reversed(keys))

            for code in keys:
                maybe_double(code)
            for code in reversed(keys):
                maybe_double(code)

            time.sleep(random.uniform(min_delay, max_delay))

        status("Stopped")
        self._stop_ydotoold()

    def _ensure_ydotoold(self) -> bool:
        with self._ydotool_lock:
            xdg_runtime = os.environ.get("XDG_RUNTIME_DIR")
            pid = os.getpid()
            if xdg_runtime:
                self.socket_path = os.path.join(xdg_runtime, f"ydotool-runk-{pid}.sock")
            else:
                self.socket_path = str(Path.home() / f".ydotool_runk_socket_{pid}")

            env = os.environ.copy()
            env["YDOTOOL_SOCKET"] = self.socket_path

            try:
                os.remove(self.socket_path)
            except FileNotFoundError:
                pass
            except Exception:
                pass

            try:
                uid = os.getuid()
                gid = os.getgid()
                self.ydotoold_proc = subprocess.Popen(
                    ["ydotoold", f"--socket-path={self.socket_path}", f"--socket-own={uid}:{gid}"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=env,
                )
                self.started_ydotoold = True
                time.sleep(0.25)
                return True
            except FileNotFoundError:
                return False
            except Exception:
                return False

    def _stop_ydotoold(self):
        with self._ydotool_lock:
            if self.ydotoold_proc and self.ydotoold_proc.poll() is None:
                self.ydotoold_proc.terminate()
                try:
                    self.ydotoold_proc.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    self.ydotoold_proc.kill()

            self.ydotoold_proc = None

            if self.started_ydotoold and self.socket_path:
                try:
                    os.remove(self.socket_path)
                except FileNotFoundError:
                    pass
                except Exception:
                    pass

            self.started_ydotoold = False


class PresetSaveWindow(Gtk.Window):
    def __init__(self, parent: Gtk.Window, on_save):
        super().__init__(title="Save Preset", transient_for=parent, modal=True)
        self.set_default_size(360, 120)
        self._on_save = on_save

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        root.set_margin_top(12)
        root.set_margin_bottom(12)
        root.set_margin_start(12)
        root.set_margin_end(12)
        self.set_child(root)

        root.append(Gtk.Label(label="Preset name:", xalign=0.0))

        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text("e.g. MyPreset")
        self.entry.connect("activate", self.on_ok)
        root.append(self.entry)

        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        btn_row.set_halign(Gtk.Align.END)

        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", self.on_cancel)
        btn_row.append(cancel)

        ok = Gtk.Button(label="Save")
        ok.connect("clicked", self.on_ok)
        btn_row.append(ok)

        root.append(btn_row)

    def on_cancel(self, *_):
        self.close()

    def on_ok(self, *_):
        name = _sanitize_preset_name(self.entry.get_text())
        self._on_save(name)
        self.close()


class ConfirmOverwriteWindow(Gtk.Window):
    def __init__(self, parent: Gtk.Window, preset_name: str, on_choice):
        super().__init__(title="Overwrite Preset?", transient_for=parent, modal=True)
        self.set_default_size(420, 140)
        self._on_choice = on_choice

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        root.set_margin_top(12)
        root.set_margin_bottom(12)
        root.set_margin_start(12)
        root.set_margin_end(12)
        self.set_child(root)

        root.append(Gtk.Label(label=f'"{preset_name}" already exists.', xalign=0.0))
        root.append(Gtk.Label(label="Overwrite it?", xalign=0.0))

        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        btn_row.set_halign(Gtk.Align.END)

        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", self.on_cancel)
        btn_row.append(cancel)

        overwrite = Gtk.Button(label="Overwrite")
        overwrite.connect("clicked", self.on_overwrite)
        btn_row.append(overwrite)

        root.append(btn_row)

    def on_cancel(self, *_):
        self._on_choice(False)
        self.close()

    def on_overwrite(self, *_):
        self._on_choice(True)
        self.close()


class RUNKMaxWindow(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application):
        super().__init__(application=app, title="RUNK-MAX")
        self.set_default_size(760, 640)

        self._syncing_ui = False
        self.capture_target: str | None = None
        self._capturing_btn: Gtk.Button | None = None

        ensure_default_presets_exist()

        self.config_path = get_user_config_path()
        default_preset = get_user_presets_dir() / "Default.json"

        if not self.config_path.exists():
            self.config = (
                load_json(default_preset, DEFAULT_CONFIG)
                if default_preset.exists()
                else _deepcopy_jsonish(DEFAULT_CONFIG)
            )
        else:
            self.config = load_json(self.config_path, DEFAULT_CONFIG)

        save_json(self.config_path, self.config)

        self.engine = EngineThread()

        self._key_controller = Gtk.EventControllerKey()
        self._key_controller.connect("key-pressed", self.on_key_pressed)
        self.add_controller(self._key_controller)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        root.set_margin_top(12)
        root.set_margin_bottom(12)
        root.set_margin_start(12)
        root.set_margin_end(12)
        self.set_child(root)

        self.status_label = Gtk.Label(label="Status: Stopped")
        self.status_label.set_xalign(0.0)
        root.append(self.status_label)

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.start_btn = Gtk.Button(label="Start")
        self.start_btn.connect("clicked", self.on_start)
        controls.append(self.start_btn)

        self.pause_btn = Gtk.Button(label="Pause/Resume")
        self.pause_btn.set_sensitive(False)
        self.pause_btn.connect("clicked", self.on_pause)
        controls.append(self.pause_btn)

        self.stop_btn = Gtk.Button(label="Stop")
        self.stop_btn.set_sensitive(False)
        self.stop_btn.connect("clicked", self.on_stop)
        controls.append(self.stop_btn)
        root.append(controls)

        presets_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        presets_row.append(Gtk.Label(label="Preset:", xalign=0.0))

        self.preset_combo = Gtk.DropDown.new_from_strings([])
        self.refresh_presets_dropdown(select_name=None)
        presets_row.append(self.preset_combo)

        load_btn = Gtk.Button(label="Load preset")
        load_btn.connect("clicked", self.on_load_preset)
        presets_row.append(load_btn)

        save_btn = Gtk.Button(label="Save preset")
        save_btn.connect("clicked", self.on_save_preset_clicked)
        presets_row.append(save_btn)

        root.append(presets_row)

        frame_keys = Gtk.Frame(label="Keys (enable/disable + keycode + capture)")
        root.append(frame_keys)
        key_grid = Gtk.Grid(column_spacing=10, row_spacing=6)
        key_grid.set_margin_top(8)
        key_grid.set_margin_bottom(8)
        key_grid.set_margin_start(8)
        key_grid.set_margin_end(8)
        frame_keys.set_child(key_grid)

        self.key_widgets: dict[str, tuple[Gtk.CheckButton, Gtk.SpinButton, Gtk.Label, Gtk.Button]] = {}
        row = 0
        for name in ("W", "A", "S", "D"):
            chk = Gtk.CheckButton(label=f"{name} enabled")
            chk.connect("toggled", self.on_any_change)

            code = Gtk.SpinButton.new_with_range(1, 400, 1)
            code.connect("value-changed", self.on_any_change)

            label = Gtk.Label(label=f"Key: {self.config['keys'][name].get('label', name)}")
            label.set_xalign(0.0)

            cap = Gtk.Button(label="Capture")
            cap.connect("clicked", self.on_capture_clicked, name)

            key_grid.attach(chk, 0, row, 1, 1)
            key_grid.attach(Gtk.Label(label="code:", xalign=1.0), 1, row, 1, 1)
            key_grid.attach(code, 2, row, 1, 1)
            key_grid.attach(label, 3, row, 1, 1)
            key_grid.attach(cap, 4, row, 1, 1)

            self.key_widgets[name] = (chk, code, label, cap)
            row += 1

        frame_opts = Gtk.Frame(label="Behavior")
        root.append(frame_opts)
        grid = Gtk.Grid(column_spacing=10, row_spacing=8)
        grid.set_margin_top(8)
        grid.set_margin_bottom(8)
        grid.set_margin_start(8)
        grid.set_margin_end(8)
        frame_opts.set_child(grid)

        r = 0
        self.diag_check = Gtk.CheckButton(label="Enable diagonals (needs vertical + horizontal enabled)")
        self.diag_check.connect("toggled", self.on_any_change)
        grid.attach(self.diag_check, 0, r, 2, 1)
        r += 1

        grid.attach(Gtk.Label(label="Min delay (s):", xalign=0.0), 0, r, 1, 1)
        self.min_delay = Gtk.SpinButton.new_with_range(0.01, 10.0, 0.01)
        self.min_delay.connect("value-changed", self.on_any_change)
        grid.attach(self.min_delay, 1, r, 1, 1)
        r += 1

        grid.attach(Gtk.Label(label="Max delay (s):", xalign=0.0), 0, r, 1, 1)
        self.max_delay = Gtk.SpinButton.new_with_range(0.01, 10.0, 0.01)
        self.max_delay.connect("value-changed", self.on_any_change)
        grid.attach(self.max_delay, 1, r, 1, 1)
        r += 1

        grid.attach(Gtk.Label(label="Press min (s):", xalign=0.0), 0, r, 1, 1)
        self.press_min = Gtk.SpinButton.new_with_range(0.01, 2.0, 0.01)
        self.press_min.connect("value-changed", self.on_any_change)
        grid.attach(self.press_min, 1, r, 1, 1)
        r += 1

        grid.attach(Gtk.Label(label="Press max (s):", xalign=0.0), 0, r, 1, 1)
        self.press_max = Gtk.SpinButton.new_with_range(0.01, 2.0, 0.01)
        self.press_max.connect("value-changed", self.on_any_change)
        grid.attach(self.press_max, 1, r, 1, 1)
        r += 1

        self.idle_check = Gtk.CheckButton(label="Enable idle gaps")
        self.idle_check.connect("toggled", self.on_any_change)
        grid.attach(self.idle_check, 0, r, 2, 1)
        r += 1

        grid.attach(Gtk.Label(label="Idle chance (1 in N):", xalign=0.0), 0, r, 1, 1)
        self.idle_chance = Gtk.SpinButton.new_with_range(2, 200, 1)
        self.idle_chance.connect("value-changed", self.on_any_change)
        grid.attach(self.idle_chance, 1, r, 1, 1)
        r += 1

        grid.attach(Gtk.Label(label="Idle min (s):", xalign=0.0), 0, r, 1, 1)
        self.idle_min = Gtk.SpinButton.new_with_range(0.1, 60.0, 0.1)
        self.idle_min.connect("value-changed", self.on_any_change)
        grid.attach(self.idle_min, 1, r, 1, 1)
        r += 1

        grid.attach(Gtk.Label(label="Idle max (s):", xalign=0.0), 0, r, 1, 1)
        self.idle_max = Gtk.SpinButton.new_with_range(0.1, 60.0, 0.1)
        self.idle_max.connect("value-changed", self.on_any_change)
        grid.attach(self.idle_max, 1, r, 1, 1)
        r += 1

        self.double_check = Gtk.CheckButton(label="Enable double taps")
        self.double_check.connect("toggled", self.on_any_change)
        grid.attach(self.double_check, 0, r, 2, 1)
        r += 1

        grid.attach(Gtk.Label(label="Double tap chance (1 in N):", xalign=0.0), 0, r, 1, 1)
        self.double_chance = Gtk.SpinButton.new_with_range(2, 200, 1)
        self.double_chance.connect("value-changed", self.on_any_change)
        grid.attach(self.double_chance, 1, r, 1, 1)

        self.push_config_to_ui()
        self.connect("close-request", self.on_close)

    # ---- presets ----
    def list_presets(self) -> list[str]:
        presets_dir = get_user_presets_dir()
        if not presets_dir.exists():
            return ["(none)"]
        names = sorted([p.name for p in presets_dir.glob("*.json")])
        return names if names else ["(none)"]

    def refresh_presets_dropdown(self, select_name: str | None):
        names = self.list_presets()
        model = Gtk.StringList.new(names)
        self.preset_combo.set_model(model)
        if select_name and select_name in names:
            self.preset_combo.set_selected(names.index(select_name))
        else:
            self.preset_combo.set_selected(0)

    def on_load_preset(self, *_):
        if self.engine.thread and self.engine.thread.is_alive():
            self.set_status("Stop engine before loading preset")
            return
        if self.capture_target:
            self.set_status("Finish capture before loading preset")
            return

        names = self.list_presets()
        if names == ["(none)"]:
            self.set_status("No presets found")
            return

        idx = self.preset_combo.get_selected()
        if idx < 0 or idx >= len(names):
            return

        preset_path = get_user_presets_dir() / names[idx]
        preset_cfg = load_json(preset_path, DEFAULT_CONFIG)

        self.config = normalize_config(preset_cfg, DEFAULT_CONFIG)
        self.push_config_to_ui()
        save_json(self.config_path, self.config)
        self.set_status(f"Loaded preset: {preset_path.name}")

    def on_save_preset_clicked(self, *_):
        if self.engine.thread and self.engine.thread.is_alive():
            self.set_status("Stop engine before saving preset")
            return
        if self.capture_target:
            self.set_status("Finish capture before saving preset")
            return

        def do_save(name: str):
            if not name:
                self.set_status("Preset save canceled/invalid name")
                return

            presets_dir = get_user_presets_dir()
            presets_dir.mkdir(parents=True, exist_ok=True)

            filename = f"{name}.json" if not name.lower().endswith(".json") else name
            preset_path = presets_dir / filename

            def write_preset():
                self.pull_ui_to_config()
                save_json(preset_path, normalize_config(self.config, DEFAULT_CONFIG))
                self.refresh_presets_dropdown(select_name=preset_path.name)
                self.set_status(f"Saved preset: {preset_path.name}")

            if preset_path.exists():

                def on_choice(overwrite: bool):
                    if overwrite:
                        write_preset()
                    else:
                        self.set_status("Preset save canceled")

                ConfirmOverwriteWindow(self, preset_path.name, on_choice).present()
                return

            write_preset()

        PresetSaveWindow(self, do_save).present()

    # ---- lifecycle ----
    def on_close(self, *_):
        self.engine.stop()
        return False

    def set_status(self, text: str):
        self.status_label.set_label(f"Status: {text}")
        running = (text == "Running" or text == "Paused")
        self.start_btn.set_sensitive((not running) and (not self.capture_target))
        self.pause_btn.set_sensitive(running)
        self.stop_btn.set_sensitive(running)
        return False

    # ---- controls ----
    def on_start(self, *_):
        if self.capture_target:
            self.set_status("Finish capture first")
            return
        self.pull_ui_to_config()
        save_json(self.config_path, self.config)
        self.engine.start(self.config, self.set_status)

    def on_pause(self, *_):
        self.engine.toggle_pause()

    def on_stop(self, *_):
        self.engine.stop()
        self.set_status("Stopped")

    def on_any_change(self, *_):
        if self._syncing_ui:
            return
        self.pull_ui_to_config()
        save_json(self.config_path, self.config)

    # ---- capture ----
    def _set_capture_ui(self, capturing: bool, target_key: str | None):
        for _k, (_chk, _spin, _label, cap_btn) in self.key_widgets.items():
            cap_btn.set_sensitive(not capturing)
            cap_btn.set_label("Capture")

        if capturing and target_key:
            _chk, _spin, _label, btn = self.key_widgets[target_key]
            btn.set_sensitive(True)
            btn.set_label("Waiting… (Esc cancels)")
            self._capturing_btn = btn
        else:
            self._capturing_btn = None

        running = bool(self.engine.thread and self.engine.thread.is_alive())
        self.start_btn.set_sensitive((not capturing) and (not running))

    def on_capture_clicked(self, _btn: Gtk.Button, key_name: str):
        if self.engine.thread and self.engine.thread.is_alive():
            self.set_status("Stop engine before capture")
            return

        if self.capture_target == key_name:
            self.capture_target = None
            self._set_capture_ui(False, None)
            self.set_status("Stopped")
            return

        self.capture_target = key_name
        self._set_capture_ui(True, key_name)
        self.set_status(f"Capture: press a key for {key_name}")

    @staticmethod
    def _gdk_keycode_to_evdev(hardware_keycode: int) -> int:
        return max(1, int(hardware_keycode) - 8)

    def on_key_pressed(self, _controller, keyval: int, keycode: int, _state) -> bool:
        if not self.capture_target:
            return False

        if keyval == Gdk.KEY_Escape:
            self.capture_target = None
            self._set_capture_ui(False, None)
            self.set_status("Stopped")
            return True

        evdev = max(1, min(400, self._gdk_keycode_to_evdev(keycode)))
        name = _friendly_key_name(keyval)

        self._syncing_ui = True
        try:
            chk, spin, label, _cap = self.key_widgets[self.capture_target]
            chk.set_active(True)
            spin.set_value(evdev)
            label.set_label(f"Key: {name}")
            self.config["keys"][self.capture_target]["label"] = name
        finally:
            self._syncing_ui = False

        self.capture_target = None
        self._set_capture_ui(False, None)

        self.pull_ui_to_config()
        save_json(self.config_path, self.config)
        self.set_status("Stopped")
        return True

    # ---- UI <-> config ----
    def push_config_to_ui(self):
        self._syncing_ui = True
        try:
            for k, (chk, spin, label, _cap) in self.key_widgets.items():
                chk.set_active(bool(self.config["keys"][k]["enabled"]))
                spin.set_value(int(self.config["keys"][k]["code"]))
                label.set_label(f"Key: {self.config['keys'][k].get('label', k)}")

            self.diag_check.set_active(bool(self.config.get("enable_diagonals", True)))
            self.min_delay.set_value(float(self.config.get("min_delay", 0.25)))
            self.max_delay.set_value(float(self.config.get("max_delay", 0.90)))
            self.press_min.set_value(float(self.config.get("press_min", 0.06)))
            self.press_max.set_value(float(self.config.get("press_max", 0.20)))

            self.idle_check.set_active(bool(self.config.get("idle_enabled", True)))
            self.idle_chance.set_value(int(self.config.get("idle_chance", 10)))
            self.idle_min.set_value(float(self.config.get("idle_min", 1.0)))
            self.idle_max.set_value(float(self.config.get("idle_max", 3.5)))

            self.double_check.set_active(bool(self.config.get("double_tap_enabled", True)))
            self.double_chance.set_value(int(self.config.get("double_tap_chance", 8)))
        finally:
            self._syncing_ui = False

    def pull_ui_to_config(self):
        for k, (chk, spin, label, _cap) in self.key_widgets.items():
            self.config["keys"][k]["enabled"] = bool(chk.get_active())
            self.config["keys"][k]["code"] = int(spin.get_value())
            lbl = label.get_text().replace("Key:", "").strip()
            if lbl:
                self.config["keys"][k]["label"] = lbl

        self.config["enable_diagonals"] = bool(self.diag_check.get_active())

        self.config["min_delay"] = float(self.min_delay.get_value())
        self.config["max_delay"] = float(self.max_delay.get_value())
        if self.config["max_delay"] < self.config["min_delay"]:
            self.config["max_delay"] = self.config["min_delay"]
            self._syncing_ui = True
            try:
                self.max_delay.set_value(self.config["max_delay"])
            finally:
                self._syncing_ui = False

        self.config["press_min"] = float(self.press_min.get_value())
        self.config["press_max"] = float(self.press_max.get_value())
        if self.config["press_max"] < self.config["press_min"]:
            self.config["press_max"] = self.config["press_min"]
            self._syncing_ui = True
            try:
                self.press_max.set_value(self.config["press_max"])
            finally:
                self._syncing_ui = False

        self.config["idle_enabled"] = bool(self.idle_check.get_active())
        self.config["idle_chance"] = int(self.idle_chance.get_value())
        self.config["idle_min"] = float(self.idle_min.get_value())
        self.config["idle_max"] = float(self.idle_max.get_value())
        if self.config["idle_max"] < self.config["idle_min"]:
            self.config["idle_max"] = self.config["idle_min"]
            self._syncing_ui = True
            try:
                self.idle_max.set_value(self.config["idle_max"])
            finally:
                self._syncing_ui = False

        self.config["double_tap_enabled"] = bool(self.double_check.get_active())
        self.config["double_tap_chance"] = int(self.double_chance.get_value())


class RUNKMaxApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)

    def do_activate(self):
        win = RUNKMaxWindow(self)
        win.present()


def main():
    handled, gtk_argv = handle_cli_reset_if_requested(sys.argv)
    if handled:
        raise SystemExit(0)

    ensure_default_presets_exist()
    app = RUNKMaxApp()
    raise SystemExit(app.run(gtk_argv))


if __name__ == "__main__":
    main()
