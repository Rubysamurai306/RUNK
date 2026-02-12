<img src="https://raw.githubusercontent.com/Rubysamurai306/RUNK/main/RUNK-MAX/assets/icon.png" width="256" />


# RUNK-MAX ⚡️
### *Rafael’s Ultimate Ninja Keyspammer (Wayland)*

**RUNK-MAX** is a **Wayland-first** GTK4 GUI keyspammer that generates **randomized, human-like movement input** (**W/A/S/D** by default) using **`ydotool`**.

I made it because most Wayland macro options I found were either **deprecated**, **broken**, or **X11-only**.

If you want **hands-free**, **tunable** movement spam on Wayland: this is it.

---

## What It Does

-  Random movement cycling (W/A/S/D by default)
-  Optional diagonal movement (W+A, W+D, etc.)
-  Configurable delay + press duration ranges
-  Probability-based idle breaks (random “gaps”)
-  Probability-based double-taps (variation)
-  Presets (save/load profiles instantly)
-  Key capture (map keys without hunting keycodes)
-  User-space config (easy preset creation from the GUI)

---

## Why Wayland?

Wayland blocks a lot of traditional X11-style input injection.

RUNK-MAX uses **uinput** via `ydotool`, which works on Wayland **as long as your user has permission to access**:

- `/dev/uinput`

---

## Compatibility

### Tested on
- **CachyOS** (KDE Wayland) using **Lumine**

### Should work on
- Most **Arch-based** distros (Pacman)
- Other distros should work script-wise, but you may need to adjust the installer/deps until official support lands

### Future
More distros will be tested and installers adapted over time.

---

## Install (Arch / CachyOS)

The installer performs system-level setup:

- Installs dependencies (pacman)
- Creates a udev rule for `/dev/uinput`
- Ensures the `uinput` module loads
- Adds your user to the `uinput` group
- Installs a `.desktop` launcher + wrapper

Because of that, you **must run the installer as root**:

```bash
cd RUNK/RUNK-MAX
sudo bash install.sh
```
---
## **RUNK-minimal**
this one is much more barebones, with just 2 files needed. only run the installer then you launch the actual program itself from the terminal. NO GUI. NO PAUSE. if you want to pause the keyspammer, simply **CTRL+C** and kill the app from within the terminal.
```
cd RUNK/RUNK-minimal
sudo bash install.sh
```
