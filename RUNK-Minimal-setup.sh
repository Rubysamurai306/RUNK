#!/usr/bin/env bash
set -euo pipefail

USER="$(id -un)"

echo "[RUNK] one-time setup for $USER"

# --------------------------------------------------
# Install dependency
# --------------------------------------------------
if ! command -v ydotool >/dev/null 2>&1; then
    echo "[*] Installing ydotool"
    sudo pacman -S --needed --noconfirm ydotool
else
    echo "[✓] ydotool already installed"
fi

# --------------------------------------------------
# Ensure uinput group
# --------------------------------------------------
if ! getent group uinput >/dev/null; then
    echo "[*] Creating uinput group"
    sudo groupadd uinput
fi

# --------------------------------------------------
# Ensure user membership
# --------------------------------------------------
if ! id -nG "$USER" | grep -qw uinput; then
    echo "[*] Adding $USER to uinput group"
    sudo usermod -aG uinput "$USER"
    echo
    echo "[!] Log out and log back in, then re-run RUNK"
    exit 1
fi

# --------------------------------------------------
# Load kernel module
# --------------------------------------------------
if ! lsmod | grep -q uinput; then
    echo "[*] Loading uinput module"
    sudo modprobe uinput
fi

echo "[✓] RUNK setup complete"
