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

    # Humanization
    "idle_enabled": True,
    "idle_chance": 10,      # 1 in N loops
    "idle_min": 1.0,
    "idle_max": 3.0,

    "double_tap_enabled": True,
    "double_tap_chance": 8, # 1 in N presses

    # Pause behavior (engine should handle SIGUSR1)
    "pause_via_signal": True
}


def load_json(path: Path, fallback: dict) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {**fallback, **data}
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


def in_range(a: float, b: float) -> bool:
    return isinstance(a, (int, float)) and isinstance(b, (int, float)) and a <= b


class RUNKMaxWindow(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application):
        super().__init__(application=app, title="RUNK-MAX")
        self.set_default_size(520, 420)

        self.config = load_json(CONFIG_PATH, DEFAULT_CONFIG)

        self.ydotoold_proc: subprocess.Popen | None = None
        self.engine_proc: subprocess.Popen | None = None
        self.socket_path: str | None = None

        # ---- UI ----
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        root.set_margin_top(12)
        root.set_margin_bottom(12)
        root.set_margin_start(12)
        root.set_margin_end(12)
        self.set_child(root)

        # Status row
        status_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.status_label = Gtk.Label(label="Status: Stopped")
        self.status_label.set_xalign(0.0)
        status_row.append(self.status_label)

        self.socket_label = Gtk.Label(label="")
        self.socket_label.set_xalign(1.0)
        status_row.append(self.socket_label)
        status_row.set_hexpand(True)
        root.append(status_row)

        # Controls row
        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)

        self.start_btn = Gtk.Button(label="Start")
        self.start_btn.connect("clicked", self.on_start)
        controls.append(self.start_btn)

        self.pause_btn = Gtk.Button(label="Pause/Resume")
        self.pause_btn.connect("clicked", self.on_pause)
        self.pause_btn.set_sensitive(False)
        controls.append(self.pause_btn)

        self.stop_btn = Gtk.Button(label="Stop")
        self.stop_btn.connect("clicked", self.on_stop)
        self.stop_btn.set_sensitive(False)
        controls.append(self.stop_btn)

        root.append(controls)

        # Preset loader
        preset_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        preset_row.append(Gtk.Label(label="Preset:", xalign=0.0))

        self.preset_combo = Gtk.DropDown.new_from_strings(self.list_presets())
        self.preset_combo.connect("notify::selected", self.on_preset_selected)
        preset_row.append(self.preset_combo)

        load_btn = Gtk.Button(label="Load preset")
        load_btn.connect("clicked", self.on_load_preset)
        preset_row.append(load_btn)

        root.append(preset_row)

        # Options grid
        grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        root.append(grid)

        r = 0

        # Diagonals
        self.diag_check = Gtk.CheckButton(label="Enable diagonals (WA/WD/SA/SD)")
        self.diag_check.set_active(bool(self.config.get("enable_diagonals", True)))
        self.diag_check.connect("toggled", self.on_any_change)
        grid.attach(self.diag_check, 0, r, 2, 1)
        r += 1

        # Delay range
        grid.attach(Gtk.Label(label="Min delay (s):", xalign=0.0), 0, r, 1, 1)
        self.min_delay = Gtk.SpinButton.new_with_range(0.01, 10.0, 0.01)
        self.min_delay.set_value(float(self.config.get("min_delay", 0.2)))
        self.min_delay.connect("value-changed", self.on_any_change)
        grid.attach(self.min_delay, 1, r, 1, 1)
        r += 1

        grid.attach(Gtk.Label(label="Max delay (s):", xalign=0.0), 0, r, 1, 1)
        self.max_delay = Gtk.SpinButton.new_with_range(0.01, 10.0, 0.01)
        self.max_delay.set_value(float(self.config.get("max_delay", 0.8)))
        self.max_delay.connect("value-changed", self.on_any_change)
        grid.attach(self.max_delay, 1, r, 1, 1)
        r += 1

        # Press duration range
        grid.attach(Gtk.Label(label="Press min (s):", xalign=0.0), 0, r, 1, 1)
        self.press_min = Gtk.SpinButton.new_with_range(0.01, 2.0, 0.01)
        self.press_min.set_value(float(self.config.get("press_min", 0.05)))
        self.press_min.connect("value-changed", self.on_any_change)
        grid.attach(self.press_min, 1, r, 1, 1)
        r += 1

        grid.attach(Gtk.Label(label="Press max (s):", xalign=0.0), 0, r, 1, 1)
        self.press_max = Gtk.SpinButton.new_with_range(0.01, 2.0, 0.01)
        self.press_max.set_value(float(self.config.get("press_max", 0.18)))
        self.press_max.connect("value-changed", self.on_any_change)
        grid.attach(self.press_max, 1, r, 1, 1)
        r += 1

        # Idle
        self.idle_check = Gtk.CheckButton(label="Enable idle gaps")
        self.idle_check.set_active(bool(self.config.get("idle_enabled", True)))
        self.idle_check.connect("toggled", self.on_any_change)
        grid.attach(self.idle_check, 0, r, 2, 1)
        r += 1

        grid.attach(Gtk.Label(label="Idle chance (1 in N):", xalign=0.0), 0, r, 1, 1)
        self.idle_chance = Gtk.SpinButton.new_with_range(2, 200, 1)
        self.idle_chance.set_value(int(self.config.get("idle_chance", 10)))
        self.idle_chance.connect("value-changed", self.on_any_change)
        grid.attach(self.idle_chance, 1, r, 1, 1)
        r += 1

        grid.attach(Gtk.Label(label="Idle min (s):", xalign=0.0), 0, r, 1, 1)
        self.idle_min = Gtk.SpinButton.new_with_range(0.1, 60.0, 0.1)
        self.idle_min.set_value(float(self.config.get("idle_min", 1.0)))
        self.idle_min.connect("value-changed", self.on_any_change)
        grid.attach(self.idle_min, 1, r, 1, 1)
        r += 1

        grid.attach(Gtk.Label(label="Idle max (s):", xalign=0.0), 0, r, 1, 1)
        self.idle_max = Gtk.SpinButton.new_with_range(0.1, 60.0, 0.1)
        self.idle_max.set_value(float(self.config.get("idle_max", 3.0)))
        self.idle_max.connect("value-changed", self.on_any_change)
        grid.attach(self.idle_max, 1, r, 1, 1)
        r += 1

        # Double tap
        self.dt_check = Gtk.CheckButton(label="Enable double taps")
        self.dt_check.set_active(bool(self.config.get("double_tap_enabled", True)))
        self.dt_check.connect("toggled", self.on_any_change)
        grid.attach(self.dt_check, 0, r, 2, 1)
        r += 1

        grid.attach(Gtk.Label(label="Double tap chance (1 in N):", xalign=0.0), 0, r, 1, 1)
        self.dt_chance = Gtk.SpinButton.new_with_range(2, 200, 1)
        self.dt_chance.set_value(int(self.config.get("double_tap_chance", 8)))
        self.dt_chance.connect("value-changed", self.on_any_change)
        grid.attach(self.dt_chance, 1, r, 1, 1)
        r += 1

        # Save indicator
        self.save_label = Gtk.Label(label="")
        self.save_label.set_xalign(0.0)
        root.append(self.save_label)

        # Periodic status updates
        GLib.timeout_add(400, self.tick_status)

        # Save initial normalized config
        self.pull_ui_to_config()
        save_json(CONFIG_PATH, self.config)

    # ---------- Presets ----------
    def list_presets(self) -> list[str]:
        if not PRESETS_DIR.exists():
            return ["(none)"]
        names = [p.name for p in PRESETS_DIR.glob("*.json")]
        return names if names else ["(none)"]

    def on_preset_selected(self, *_):
        # no-op; user clicks "Load preset"
        return

    def on_load_preset(self, *_):
        names = self.list_presets()
        if not names or names == ["(none)"]:
            self.show_error("No presets found", f"Create presets in:\n{PRESETS_DIR}")
            return

        idx = self.preset_combo.get_selected()
        if idx < 0 or idx >= len(names):
            return
        preset_path = PRESETS_DIR / names[idx]
        try:
            preset = load_json(preset_path, DEFAULT_CONFIG)
        except Exception as e:
            self.show_error("Preset load failed", str(e))
            return

        self.config = {**DEFAULT_CONFIG, **preset}
        self.push_config_to_ui()
        save_json(CONFIG_PATH, self.config)
        self.save_label.set_label(f"Loaded preset: {preset_path.name}")

    # ---------- UI <-> Config ----------
    def on_any_change(self, *_):
        self.pull_ui_to_config()
        save_json(CONFIG_PATH, self.config)
        self.save_label.set_label(f"Saved: {CONFIG_PATH}")

    def pull_ui_to_config(self):
        self.config["enable_diagonals"] = self.diag_check.get_active()
        self.config["min_delay"] = float(self.min_delay.get_value())
        self.config["max_delay"] = float(self.max_delay.get_value())
        self.config["press_min"] = float(self.press_min.get_value())
        self.config["press_max"] = float(self.press_max.get_value())
        self.config["idle_enabled"] = self.idle_check.get_active()
        self.config["idle_chance"] = int(self.idle_chance.get_value())
        self.config["idle_min"] = float(self.idle_min.get_value())
        self.config["idle_max"] = float(self.idle_max.get_value())
        self.config["double_tap_enabled"] = self.dt_check.get_active()
        self.config["double_tap_chance"] = int(self.dt_chance.get_value())

        # Normalize obvious invalid ranges (keep it forgiving)
        if self.config["max_delay"] < self.config["min_delay"]:
            self.config["max_delay"] = self.config["min_delay"]
            self.max_delay.set_value(self.config["max_delay"])

        if self.config["press_max"] < self.config["press_min"]:
            self.config["press_max"] = self.config["press_min"]
            self.press_max.set_value(self.config["press_max"])

        if self.config["idle_max"] < self.config["idle_min"]:
            self.config["idle_max"] = self.config["idle_min"]
            self.idle_max.set_value(self.config["idle_max"])

    def push_config_to_ui(self):
        self.diag_check.set_active(bool(self.config.get("enable_diagonals", True)))
        self.min_delay.set_value(float(self.config.get("min_delay", 0.2)))
        self.max_delay.set_value(float(self.config.get("max_delay", 0.8)))
        self.press_min.set_value(float(self.config.get("press_min", 0.05)))
        self.press_max.set_value(float(self.config.get("press_max", 0.18)))
        self.idle_check.set_active(bool(self.config.get("idle_enabled", True)))
        self.idle_chance.set_value(int(self.config.get("idle_chance", 10)))
        self.idle_min.set_value(float(self.config.get("idle_min", 1.0)))
        self.idle_max.set_value(float(self.config.get("idle_max", 3.0)))
        self.dt_check.set_active(bool(self.config.get("double_tap_enabled", True)))
        self.dt_chance.set_value(int(self.config.get("double_tap_chance", 8)))

    # ---------- Process control ----------
    def ensure_ydotoold(self) -> bool:
        # Prefer XDG_RUNTIME_DIR socket (per-user, correct for sessions)
        xdg_runtime = os.environ.get("XDG_RUNTIME_DIR")
        if xdg_runtime:
            self.socket_path = os.path.join(xdg_runtime, "ydotool.sock")
        else:
            self.socket_path = os.path.join(str(Path.home()), ".ydotool_socket")

        env = os.environ.copy()
        env["YDOTOOL_SOCKET"] = self.socket_path

        # If already running (maybe from another run), do nothing.
        # We won’t try to “take ownership” of an existing daemon.
        if subprocess.call(["pgrep", "-u", str(os.getuid()), "ydotoold"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0:
            self.socket_label.set_label(f"Socket: {self.socket_path}")
            return True

        # Start ydotoold as *user* (this app), NOT sudo
        uid = os.getuid()
        gid = os.getgid()

        try:
            # Remove stale socket path if it exists (safe)
            try:
                os.remove(self.socket_path)
            except FileNotFoundError:
                pass

            self.ydotoold_proc = subprocess.Popen(
                ["ydotoold",
                 f"--socket-path={self.socket_path}",
                 f"--socket-own={uid}:{gid}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env
            )
        except FileNotFoundError:
            self.show_error("ydotoold not found", "Install ydotool first.")
            return False

        # Give daemon a moment
        GLib.usleep(250_000)
        self.socket_label.set_label(f"Socket: {self.socket_path}")
        return True

    def start_engine(self) -> bool:
        if not ENGINE_PATH.exists():
            self.show_error("Engine missing", f"Expected:\n{ENGINE_PATH}")
            return False

        self.pull_ui_to_config()
        save_json(CONFIG_PATH, self.config)

        env = os.environ.copy()
        if self.socket_path:
            env["YDOTOOL_SOCKET"] = self.socket_path

        # Prefer engine supporting --config; adjust if your engine uses a different interface
        try:
            self.engine_proc = subprocess.Popen(
                ["bash", str(ENGINE_PATH), "--config", str(CONFIG_PATH)],
                env=env
            )
        except Exception as e:
            self.show_error("Failed to start engine", str(e))
            return False

        return True

    def stop_engine(self):
        if self.engine_proc and self.engine_proc.poll() is None:
            self.engine_proc.terminate()
            try:
                self.engine_proc.wait(timeout=1.5)
            except subprocess.TimeoutExpired:
                self.engine_proc.kill()
        self.engine_proc = None

    def stop_ydotoold(self):
        # Only kill if we started it.
        if self.ydotoold_proc and self.ydotoold_proc.poll() is None:
            self.ydotoold_proc.terminate()
            try:
                self.ydotoold_proc.wait(timeout=1.5)
            except subprocess.TimeoutExpired:
                self.ydotoold_proc.kill()
        self.ydotoold_proc = None

        # Best-effort socket cleanup if we created it
        if self.socket_path:
            try:
                os.remove(self.socket_path)
            except FileNotFoundError:
                pass

    # ---------- Handlers ----------
    def on_start(self, *_):
        if self.engine_proc and self.engine_proc.poll() is None:
            return

        # validate ranges lightly (don’t be annoying)
        self.pull_ui_to_config()
        if not in_range(self.config["min_delay"], self.config["max_delay"]):
            self.show_error("Invalid delay range", "Max delay must be >= Min delay.")
            return
        if not in_range(self.config["press_min"], self.config["press_max"]):
            self.show_error("Invalid press range", "Press max must be >= Press min.")
            return

        if not self.ensure_ydotoold():
            return
        if not self.start_engine():
            return

        self.start_btn.set_sensitive(False)
        self.pause_btn.set_sensitive(True)
        self.stop_btn.set_sensitive(True)
        self.status_label.set_label("Status: Running")

    def on_pause(self, *_):
        if not self.engine_proc or self.engine_proc.poll() is not None:
            return
        # Engine should trap SIGUSR1 and toggle pause
        try:
            os.kill(self.engine_proc.pid, signal.SIGUSR1)
        except Exception as e:
            self.show_error("Pause failed", str(e))

    def on_stop(self, *_):
        self.stop_engine()
        self.stop_ydotoold()

        self.start_btn.set_sensitive(True)
        self.pause_btn.set_sensitive(False)
        self.stop_btn.set_sensitive(False)
        self.status_label.set_label("Status: Stopped")

    def tick_status(self):
        # Called periodically
        if self.engine_proc and self.engine_proc.poll() is not None:
            # Engine died
            self.engine_proc = None
            self.start_btn.set_sensitive(True)
            self.pause_btn.set_sensitive(False)
            self.stop_btn.set_sensitive(False)
            self.status_label.set_label("Status: Stopped (engine exited)")
        return True

    def show_error(self, title: str, message: str):
        dlg = Gtk.AlertDialog()
        dlg.set_message(title)
        dlg.set_detail(message)
        dlg.show(self)


class RUNKMaxApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)

    def do_activate(self):
        win = RUNKMaxWindow(self)
        win.present()


def main():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        save_json(CONFIG_PATH, DEFAULT_CONFIG)

    app = RUNKMaxApp()
    raise SystemExit(app.run(None))


if __name__ == "__main__":
    main()
