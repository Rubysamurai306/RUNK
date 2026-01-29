<img src="https://raw.githubusercontent.com/Rubysamurai306/RUNK/main/RUNK-MAX/assets/icon.png" width="256" />


# RUNK-MAX ⚡️  
### *Rafael’s Ultimate Ninja Keyspammer (Wayland)*

**RUNK-MAX** is a **Wayland-first** GTK4 GUI that generates **randomized keyboard movement input** (built around **W/A/S/D**, this program was primarily made with gaming in mind.) using **`ydotool`**.
It exists because Wayland is locked down by design — and most “macro” tools are still X11-only.

If you want **hands-free**, **human-like**, **tunable** movement spam on Wayland: this is it.

---

## ✨ What It Does

- ✅ Random movement cycling (W/A/S/D as standard.)
- ✅ Optional diagonals (W+A, W+D, etc.)
- ✅ Configurable delays + press duration ranges
- ✅ Idle gaps (probability-based “breaks”)
- ✅ Double-taps (probability-based variation)
- ✅ Presets (load/save profiles instantly)
- ✅ Key capture (map keys without having to dig for the correct keybind numerical values)
- ✅ User-space config (you can also make and save your own presets easily from within the GUI)

---

## 🧠 Why Wayland?

Wayland blocks traditional input injection used by X11 macro tools.  
RUNK-MAX uses **uinput** via `ydotool`, which works cleanly on Wayland **when your user has permission to use `/dev/uinput`**.

---

## 🧩 Compatibility

✅ **Tested on:**  
- **CachyOS** (KDE,Wayland) on **Lumine bootloader**

⚠️ **Should work on:**  
- all **Arch-based** distros (mainly all that use Pacman as a package mangager. support for other distros like ubuntu-based is coming.)

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
```
---
## **RUNK-minimal**
this one is much more barebones, with just 2 files needed. only run the installer then you launch the actual program itself from the terminal. NO GUI. NO PAUSE. if you want to pause the keyspammer, simply **CTRL+C** and kill the app from within the terminal.
```
cd RUNK/RUNK-minimal
sudo bash install.sh
```
