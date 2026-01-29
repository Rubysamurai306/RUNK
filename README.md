![RUNK Logo](https://1lm.me/cc.png)

# RUNK-MAX ⚡️  
### *Rafael’s Ultimate Ninja Keyspammer (Wayland GUI)*

**RUNK-MAX** is a **Wayland-first** GTK4 GUI that generates **randomized keyboard movement input** (built around **W/A/S/D**) using **`ydotool` + `ydotoold`** (uinput).  
It exists because Wayland is locked down by design — and most “macro” tools are still X11-only.

If you want **hands-free**, **human-ish**, **tunable** movement spam on Wayland: this is it.

---

## ✨ What It Does

- ✅ Random movement cycling (W/A/S/D)
- ✅ Optional diagonals (W+A, W+D, etc.)
- ✅ Configurable delays + press duration ranges
- ✅ Idle gaps (probability-based “breaks”)
- ✅ Double-taps (probability-based variation)
- ✅ Presets (load/save profiles instantly)
- ✅ Key capture (map keys without guessing codes)
- ✅ User-space config (keeps the repo clean)

---

## 🧠 Why Wayland?

Wayland blocks traditional input injection used by X11 macro tools.  
RUNK-MAX uses **uinput** via `ydotool`, which works cleanly on Wayland **when your user has permission to use `/dev/uinput`**.

---

## 🧩 Compatibility

✅ **Tested on:**  
- **CachyOS** (Wayland)  
- **Lumine bootloader** environment

⚠️ **Should work on:**  
- Most **Arch-based** distros (and likely others) as long as:
  - `ydotool` is available
  - GTK4 + python-gobject are installed
  - uinput permissions are set correctly

🧪 **Future:**  
More distros will be tested and installers adapted over time.

---

## 🚀 Install (Arch / CachyOS)

RUNK-MAX needs system changes:
- installs packages (pacman)
- creates a udev rule for `/dev/uinput`
- ensures the `uinput` module loads
- adds your user to the `uinput` group
- installs `.desktop` launcher + wrapper

That’s why you **must run the installer as root**:

```bash
cd RUNK/RUNK-MAX
sudo bash install.sh
