#!/usr/bin/env bash
set -euo pipefail

# -----------------------------
# RUNK-MAX Installer (Arch/Wayland)
# -----------------------------
# Run from the repo root:
#   sudo ./install-runk-max.sh
# or without sudo (will prompt when needed):
#   ./install-runk-max.sh
#
# Assumes repo layout:
#   ./minimal/...
#   ./max/runk-max.py
#   ./max/config.json
# -----------------------------

log() { printf "[RUNK] %s\n" "$*"; }
warn() { printf "[RUNK][WARN] %s\n" "$*" >&2; }
die() { printf "[RUNK][ERR] %s\n" "$*" >&2; exit 1; }

# Determine target user (the "real" desktop user)
TARGET_USER="${SUDO_USER:-$(id -un)}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
[[ -n "$TARGET_HOME" && -d "$TARGET_HOME" ]] || die "Could not determine home for user: $TARGET_USER"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Validate expected files
[[ -f "$REPO_ROOT/max/runk-max.py" ]] || die "Missing: $REPO_ROOT/max/runk-max.py"
[[ -f "$REPO_ROOT/max/config.json" ]] || warn "Missing: $REPO_ROOT/max/config.json (GUI can create it, but presets are recommended)."
[[ -d "$REPO_ROOT/minimal" ]] || warn "Missing ./minimal directory (ok if MAX does not call minimal scripts yet)."

need_root() {
  if [[ "$(id -u)" -ne 0 ]]; then
    die "This step needs sudo/root. Re-run as: sudo $0"
  fi
}

as_target_user() {
  # Run command as the target user (works even when script is run with sudo)
  sudo -u "$TARGET_USER" env HOME="$TARGET_HOME" XDG_RUNTIME_DIR="/run/user/$(id -u "$TARGET_USER")" bash -lc "$*"
}

install_packages() {
  log "Installing packages (Arch/pacman)…"
  # ydotool: input injection
  # jq: parse JSON config
  # python + gobject bindings: GTK GUI
  # gtk4: GTK runtime
  # Note: package names are correct for Arch repos (PyGObject is python-gobject).
  sudo pacman -S --needed --noconfirm \
    ydotool jq \
    python python-gobject gtk4
}

ensure_uinput_group() {
  if ! getent group uinput >/dev/null; then
    log "Creating group: uinput"
    sudo groupadd uinput
  else
    log "Group exists: uinput"
  fi
}

add_user_to_uinput() {
  if id -nG "$TARGET_USER" | grep -qw uinput; then
    log "User already in group uinput: $TARGET_USER"
  else
    log "Adding $TARGET_USER to group uinput"
    sudo usermod -aG uinput "$TARGET_USER"
    warn "User group membership changed. You must log out and log back in for it to take effect."
  fi
}

install_udev_rule() {
  need_root
  local rule_path="/etc/udev/rules.d/99-uinput-runk.rules"
  log "Installing udev rule: $rule_path"
  cat > "$rule_path" <<'EOF'
# RUNK: allow uinput access for users in the uinput group
KERNEL=="uinput", SUBSYSTEM=="misc", GROUP="uinput", MODE="0660"
EOF

  log "Reloading udev rules"
  udevadm control --reload-rules || true
  udevadm trigger || true
}

ensure_uinput_module_boot() {
  need_root
  local conf="/etc/modules-load.d/uinput-runk.conf"
  log "Ensuring uinput loads at boot: $conf"
  echo "uinput" > "$conf"

  log "Loading uinput kernel module now"
  modprobe uinput || true
}

install_user_service() {
  # Install as *user* service in ~/.config/systemd/user so it runs in user session
  local user_systemd_dir="$TARGET_HOME/.config/systemd/user"
  local service_path="$user_systemd_dir/ydotoold.service"

  log "Installing systemd user service: $service_path"
  mkdir -p "$user_systemd_dir"

  # ydotoold must run as user; socket must be in /run/user/$UID for correct permissions
  local uid
  uid="$(id -u "$TARGET_USER")"

  cat > "$service_path" <<EOF
[Unit]
Description=ydotoold (RUNK)
After=graphical-session.target
Wants=graphical-session.target

[Service]
Type=simple
Environment=YDOTOOL_SOCKET=/run/user/${uid}/ydotool.sock
ExecStart=/usr/bin/ydotoold --socket-path=/run/user/${uid}/ydotool.sock --socket-own=${uid}:${uid}
Restart=on-failure
RestartSec=1

[Install]
WantedBy=default.target
EOF

  log "Enabling + starting user service for $TARGET_USER"
  # We need the user's systemd --user instance. This works best when the user is logged in.
  # We still try to enable now; if start fails, it will work after next login.
  as_target_user "systemctl --user daemon-reload"
  as_target_user "systemctl --user enable --now ydotoold.service" || {
    warn "Could not start ydotoold.service right now (often happens if user session isn't active)."
    warn "After logging in, run: systemctl --user enable --now ydotoold.service"
  }
}

install_launcher_wrapper() {
  # Create a stable entrypoint in ~/.local/bin so .desktop Exec doesn't depend on cwd.
  local bin_dir="$TARGET_HOME/.local/bin"
  local wrapper="$bin_dir/runk-max"

  log "Installing launcher wrapper: $wrapper"
  mkdir -p "$bin_dir"

  cat > "$wrapper" <<EOF
#!/usr/bin/env bash
set -euo pipefail

# RUNK-MAX wrapper
REPO_ROOT="$REPO_ROOT"
exec python3 "\$REPO_ROOT/max/runk-max.py"
EOF

  chmod +x "$wrapper"
  chown "$TARGET_USER":"$TARGET_USER" "$wrapper"
}

install_desktop_entry_user() {
  local app_dir="$TARGET_HOME/.local/share/applications"
  local desktop_path="$app_dir/runk-max.desktop"

  log "Installing .desktop entry: $desktop_path"
  mkdir -p "$app_dir"

  cat > "$desktop_path" <<EOF
[Desktop Entry]
Name=RUNK-MAX
Comment=Rafael's Ultimate Ninja Keyspammer (GUI)
Exec=$TARGET_HOME/.local/bin/runk-max
Icon=keyboard
Terminal=false
Type=Application
Categories=Utility;Game;
StartupNotify=true
EOF

  chown "$TARGET_USER":"$TARGET_USER" "$desktop_path"

  # Refresh KDE cache if available
  as_target_user "command -v kbuildsycoca5 >/dev/null && kbuildsycoca5 || true"
}

print_post_install() {
  cat <<EOF

[RUNK] Install complete.

What was installed:
- Packages: ydotool, jq, python, python-gobject, gtk4
- udev rule: /etc/udev/rules.d/99-uinput-runk.rules (uinput group permissions)
- module load: /etc/modules-load.d/uinput-runk.conf (loads uinput at boot)
- user service: ~/.config/systemd/user/ydotoold.service (runs as $TARGET_USER)
- launcher: ~/.local/bin/runk-max
- desktop entry: ~/.local/share/applications/runk-max.desktop

Important:
- If the installer added $TARGET_USER to the uinput group, you MUST log out and log back in.

Manual service commands (as your user):
  systemctl --user status ydotoold.service
  systemctl --user restart ydotoold.service
  systemctl --user disable --now ydotoold.service

Launch:
- KDE launcher: search "RUNK-MAX"
- Or run: runk-max

EOF
}

main() {
  log "Repo root: $REPO_ROOT"
  log "Target user: $TARGET_USER"

  # Use sudo for system changes when needed; script can be run with or without sudo.
  if [[ "$(id -u)" -ne 0 ]]; then
    log "Not running as root; will prompt for sudo as needed."
  fi

  # Install packages (needs sudo)
  sudo -v
  install_packages

  ensure_uinput_group
  add_user_to_uinput

  install_udev_rule
  ensure_uinput_module_boot

  install_user_service
  install_launcher_wrapper
  install_desktop_entry_user

  print_post_install
}

main "$@"
