#!/usr/bin/env python3
import os
import json
import random
import time
import subprocess
import threading
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib

APP_ID = "com.rafael.runkmax"

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config" / "current.json"
PRESETS_DIR = SCRIPT_DIR / "presets"

DEFAULT_CONFIG = {
    "keys": {
        "W": {"code": 17, "enabled": True},
        "A": {"code": 30, "enabled": True},
        "S": {"code": 31, "enabled": True},
        "D": {"code": 32, "enabled": True},
    },
    "enable_diagonals": True,
    "min_delay": 0.25,
    "max_delay": 0.90,
    "press_min": 0.06,
    "press_max": 0.20,
    "idle_enabled": True,
    "idle_chance": 10,     # 1 in N loops
    "idle_min": 1.0,
    "idle_max": 3.5,
    "double_tap_enabled": True,
    "double_tap_chance": 8 # 1 in N presses
}


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
    return fallback.copy()


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    tmp.replace(path)


def normalize_config(cfg: dict, fallback: dict) -> dict:
    """
    Make sure nested keys exist and types are sane enough for the UI.
    Shallow-merge with defaults, then fix nested structure for keys.
    """
    merged = fallback.copy()
    merged.update(cfg)

    merged.setdefault("keys", fallback["keys"])
    for k in ("W", "A", "S", "D"):
        merged["keys"].setdefault(k, fallback["keys"][k])
        merged["keys"][k].setdefault("code", fallback["keys"][k]["code"])
        merged["keys"][k].setdefault("enabled", fallback["keys"][k]["enabled"])

    # Coerce obvious scalar types (best-effort)
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
        merged["keys"][k]["code"] = i(merged["keys"][k].get("code", fallback["keys"][k]["code"]),
                                      fallback["keys"][k]["code"])

    # Normalize ranges
    if merged["max_delay"] < merged["min_delay"]:
        merged["max_delay"] = merged["min_delay"]
    if merged["press_max"] < merged["press_min"]:
        merged["press_max"] = merged["press_min"]
    if merged["idle_max"] < merged["idle_min"]:
        merged["idle_max"] = merged["idle_min"]

    # Clamp some values to sensible ranges to avoid weird UI states
    merged["idle_chance"] = max(2, merged["idle_chance"])
    merged["double_tap_chance"] = max(2, merged["double_tap_chance"])

    return merged


class EngineThread:
    """
    Self-contained engine:
    - starts ydotoold on Start (user-mode)
    - injects key events via ydotool
    - supports pause/resume + stop
    - uses config with per-key enable/disable
    """
    def __init__(self):
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._pause.clear()
        self.thread: threading.Thread | None = None

        self.ydotoold_proc: subprocess.Popen | None = None
        self.socket_path: str | None = None

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
        idle_max = float(config.get("idle_max", 3.0))

        double_enabled = bool(config.get("double_tap_enabled", True))
        double_chance = int(config.get("double_tap_chance", 8))

        env = os.environ.copy()
        if self.socket_path:
            env["YDOTOOL_SOCKET"] = self.socket_path

        def press_key(code: int):
            subprocess.run(["ydotool", "key", f"{code}:1"], env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(random.uniform(press_min, press_max))
            subprocess.run(["ydotool", "key", f"{code}:0"], env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        def maybe_double(code: int):
            press_key(code)
            if double_enabled and random.randint(1, max(2, double_chance)) == 1:
                time.sleep(random.uniform(0.03, 0.12))
                press_key(code)

        while not self._stop.is_set():
            while self._pause.is_set() and not self._stop.is_set():
                status("Paused")
                time.sleep(0.15)

            if self._stop.is_set():
                break

            status("Running")

            if idle_enabled and random.randint(1, max(2, idle_chance)) == 1:
                time.sleep(random.uniform(idle_min, idle_max))

            move_type = random.choice(["axis", "diag"]) if enable_diag else "axis"
            keys: list[int]

            if move_type == "diag":
                k1 = random.choice(vert)
                k2 = random.choice(horiz)
                keys = [k1, k2]
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
        xdg_runtime = os.environ.get("XDG_RUNTIME_DIR")
        if xdg_runtime:
            self.socket_path = os.path.join(xdg_runtime, "ydotool.sock")
        else:
            self.socket_path = str(Path.home() / ".ydotool_socket")

        env = os.environ.copy()
        env["YDOTOOL_SOCKET"] = self.socket_path

        try:
            r = subprocess.run(
                ["pgrep", "-u", str(os.getuid()), "ydotoold"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if r.returncode == 0:
                return True
        except Exception:
            pass

        try:
            try:
                os.remove(self.socket_path)
            except FileNotFoundError:
                pass

            uid = os.getuid()
            gid = os.getgid()
            self.ydotoold_proc = subprocess.Popen(
                ["ydotoold", f"--socket-path={self.socket_path}", f"--socket-own={uid}:{gid}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env
            )
            time.sleep(0.25)
            return True
        except Exception:
            return False

    def _stop_ydotoold(self):
        if self.ydotoold_proc and self.ydotoold_proc.poll() is None:
            self.ydotoold_proc.terminate()
            try:
                self.ydotoold_proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                self.ydotoold_proc.kill()
        self.ydotoold_proc = None
        if self.socket_path:
            try:
                os.remove(self.socket_path)
            except FileNotFoundError:
                pass


class RUNKMaxWindow(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application):
        super().__init__(application=app, title="RUNK-MAX")
        self.set_default_size(600, 560)

        self.config = load_json(CONFIG_PATH, DEFAULT_CONFIG)
        save_json(CONFIG_PATH, self.config)

        self.engine = EngineThread()

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        root.set_margin_top(12)
        root.set_margin_bottom(12)
        root.set_margin_start(12)
        root.set_margin_end(12)
        self.set_child(root)

        # Status
        self.status_label = Gtk.Label(label="Status: Stopped")
        self.status_label.set_xalign(0.0)
        root.append(self.status_label)

        # Controls
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

        # Presets row
        presets_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        presets_row.append(Gtk.Label(label="Preset:", xalign=0.0))

        self.preset_names = self.list_presets()
        self.preset_combo = Gtk.DropDown.new_from_strings(self.preset_names)
        presets_row.append(self.preset_combo)

        load_btn = Gtk.Button(label="Load preset")
        load_btn.connect("clicked", self.on_load_preset)
        presets_row.append(load_btn)

        root.append(presets_row)

        # Keys section
        frame_keys = Gtk.Frame(label="Keys (enable/disable + keycode)")
        root.append(frame_keys)
        key_grid = Gtk.Grid(column_spacing=10, row_spacing=6)
        key_grid.set_margin_top(8)
        key_grid.set_margin_bottom(8)
        key_grid.set_margin_start(8)
        key_grid.set_margin_end(8)
        frame_keys.set_child(key_grid)

        self.key_widgets = {}
        row = 0
        for name in ("W", "A", "S", "D"):
            chk = Gtk.CheckButton(label=f"{name} enabled")
            chk.connect("toggled", self.on_any_change)
            code = Gtk.SpinButton.new_with_range(1, 300, 1)
            code.connect("value-changed", self.on_any_change)

            key_grid.attach(chk, 0, row, 1, 1)
            key_grid.attach(Gtk.Label(label="code:", xalign=1.0), 1, row, 1, 1)
            key_grid.attach(code, 2, row, 1, 1)

            self.key_widgets[name] = (chk, code)
            row += 1

        # Options section
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
        r += 1

        self.push_config_to_ui()

        self.connect("close-request", self.on_close)

    # ----- Presets -----
    def list_presets(self) -> list[str]:
        if not PRESETS_DIR.exists():
            return ["(none)"]
        names = sorted([p.name for p in PRESETS_DIR.glob("*.json")])
        return names if names else ["(none)"]

    def on_load_preset(self, *_):
        if self.engine.thread and self.engine.thread.is_alive():
            self.set_status("Stop engine before loading preset")
            return

        names = self.list_presets()
        if names == ["(none)"]:
            self.set_status("No presets found")
            return

        idx = self.preset_combo.get_selected()
        if idx < 0 or idx >= len(names):
            return

        preset_path = PRESETS_DIR / names[idx]
        try:
            preset_cfg = load_json(preset_path, DEFAULT_CONFIG)
        except Exception as e:
            self.set_status(f"Preset load failed: {e}")
            return

        self.config = normalize_config(preset_cfg, DEFAULT_CONFIG)
        self.push_config_to_ui()
        save_json(CONFIG_PATH, self.config)
        self.set_status(f"Loaded preset: {preset_path.name}")

    # ----- lifecycle -----
    def on_close(self, *_):
        self.engine.stop()
        return False

    def set_status(self, text: str):
        self.status_label.set_label(f"Status: {text}")
        running = (text == "Running" or text == "Paused")
        self.start_btn.set_sensitive(not running)
        self.pause_btn.set_sensitive(running)
        self.stop_btn.set_sensitive(running)
        return False

    # ----- controls -----
    def on_start(self, *_):
        self.pull_ui_to_config()
        save_json(CONFIG_PATH, self.config)
        self.engine.start(self.config, self.set_status)

    def on_pause(self, *_):
        self.engine.toggle_pause()

    def on_stop(self, *_):
        self.engine.stop()
        self.set_status("Stopped")

    def on_any_change(self, *_):
        self.pull_ui_to_config()
        save_json(CONFIG_PATH, self.config)

    # ----- UI <-> config -----
    def push_config_to_ui(self):
        for k, (chk, spin) in self.key_widgets.items():
            chk.set_active(bool(self.config["keys"][k]["enabled"]))
            spin.set_value(int(self.config["keys"][k]["code"]))

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

    def pull_ui_to_config(self):
        for k, (chk, spin) in self.key_widgets.items():
            self.config["keys"][k]["enabled"] = bool(chk.get_active())
            self.config["keys"][k]["code"] = int(spin.get_value())

        self.config["enable_diagonals"] = bool(self.diag_check.get_active())

        self.config["min_delay"] = float(self.min_delay.get_value())
        self.config["max_delay"] = float(self.max_delay.get_value())
        if self.config["max_delay"] < self.config["min_delay"]:
            self.config["max_delay"] = self.config["min_delay"]
            self.max_delay.set_value(self.config["max_delay"])

        self.config["press_min"] = float(self.press_min.get_value())
        self.config["press_max"] = float(self.press_max.get_value())
        if self.config["press_max"] < self.config["press_min"]:
            self.config["press_max"] = self.config["press_min"]
            self.press_max.set_value(self.config["press_max"])

        self.config["idle_enabled"] = bool(self.idle_check.get_active())
        self.config["idle_chance"] = int(self.idle_chance.get_value())
        self.config["idle_min"] = float(self.idle_min.get_value())
        self.config["idle_max"] = float(self.idle_max.get_value())
        if self.config["idle_max"] < self.config["idle_min"]:
            self.config["idle_max"] = self.config["idle_min"]
            self.idle_max.set_value(self.config["idle_max"])

        self.config["double_tap_enabled"] = bool(self.double_check.get_active())
        self.config["double_tap_chance"] = int(self.double_chance.get_value())


class RUNKMaxApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)

    def do_activate(self):
        win = RUNKMaxWindow(self)
        win.present()


def main():
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        save_json(CONFIG_PATH, DEFAULT_CONFIG)

    app = RUNKMaxApp()
    raise SystemExit(app.run(None))


if __name__ == "__main__":
    main()
