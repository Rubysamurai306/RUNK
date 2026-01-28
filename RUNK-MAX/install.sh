#!/usr/bin/env bash
set -euo pipefail

log()  { printf "[RUNK] %s\n" "$*"; }
warn() { printf "[RUNK][WARN] %s\n" "$*" >&2; }
die()  { printf "[RUNK][ERR] %s\n" "$*" >&2; exit 1; }

TARGET_USER="${SUDO_USER:-$(id -un)}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
[[ -n "$TARGET_HOME" && -d "$TARGET_HOME" ]] || die "Could not determine home for user: $TARGET_USER"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAX_DIR="$SCRIPT_DIR"                       # RUNK-MAX directory
ROOT_DIR="$(cd "$MAX_DIR/.." && pwd)"
MINIMAL_DIR="$ROOT_DIR/RUNK-minimal"        # optional sibling

DESKTOP_IN="$MAX_DIR/runk.desktop.in"        # optional template

# Validate expected files in RUNK-MAX/
[[ -f "$MAX_DIR/runk-max.py" ]] || die "Missing: $MAX_DIR/runk-max.py"
[[ -f "$MAX_DIR/config/current.json" ]] || warn "Missing: $MAX_DIR/config/current.json (GUI will create it)."
[[ -d "$MAX_DIR/presets" ]] || warn "Missing: $MAX_DIR/presets (preset dropdown will be empty)."
[[ -d "$MINIMAL_DIR" ]] || warn "Missing: $MINIMAL_DIR (ok; MAX is standalone)."

need_root() {
  if [[ "$(id -u)" -ne 0 ]]; then
    die "This step needs sudo/root. Re-run as: sudo $0"
  fi
}

as_target_user() {
  sudo -u "$TARGET_USER" env HOME="$TARGET_HOME" bash -lc "$*"
}

install_packages() {
  log "Installing packages (Arch/pacman)…"
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
    warn "User group membership changed. You MUST log out and log back in for it to take effect."
  fi
}

install_udev_rule() {
  need_root
  local rule_path="/etc/udev/rules.d/99-uinput-runk.rules"
  log "Installing udev rule: $rule_path"

  cat > "$rule_path" <<'EOF'
# RUNK: allow uinput access for users in the uinput group
KERNEL=="uinput", MODE="0660", GROUP="uinput", OPTIONS+="static_node=uinput"
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

install_launcher_wrapper() {
  local bin_dir="$TARGET_HOME/.local/bin"
  local wrapper="$bin_dir/runk-max"

  log "Installing launcher wrapper: $wrapper"
  mkdir -p "$bin_dir"

  cat > "$wrapper" <<EOF
#!/usr/bin/env bash
set -euo pipefail

MAX_DIR="$MAX_DIR"
exec python3 "\$MAX_DIR/runk-max.py"
EOF

  chmod +x "$wrapper"
  chown "$TARGET_USER":"$TARGET_USER" "$wrapper"
}

install_icon_user_home_assets() {
  # Canonical icon location requested: ~/assets/icon.png
  local icon_src="$MAX_DIR/assets/icon.png"
  local icon_dir="$TARGET_HOME/assets"
  local icon_dst="$icon_dir/icon.png"

  mkdir -p "$icon_dir"
  chown "$TARGET_USER":"$TARGET_USER" "$icon_dir"

  if [[ ! -f "$icon_src" ]]; then
    warn "Icon not found at $icon_src — falling back to Icon=keyboard"
    echo "keyboard"
    return 0
  fi

  log "Installing icon to: $icon_dst"
  cp "$icon_src" "$icon_dst"
  chown "$TARGET_USER":"$TARGET_USER" "$icon_dst"

  # Desktop entry needs an absolute path (no ~ expansion)
  echo "$icon_dst"
}

render_desktop_from_template_or_inline() {
  local desktop_path="$1"
  local exec_value="$2"
  local icon_value="$3"

  if [[ -f "$DESKTOP_IN" ]]; then
    log "Using desktop template: $DESKTOP_IN"
    # Escape for sed replacement.
    local esc_exec esc_icon
    esc_exec="$(printf '%s' "$exec_value" | sed -e 's/[\/&]/\\&/g')"
    esc_icon="$(printf '%s' "$icon_value" | sed -e 's/[\/&]/\\&/g')"

    sed \
      -e "s/@EXEC@/$esc_exec/g" \
      -e "s/@ICON@/$esc_icon/g" \
      "$DESKTOP_IN" > "$desktop_path"

    # If the template doesn't include these, append them (idempotent-ish).
    grep -q '^StartupWMClass=' "$desktop_path" || echo 'StartupWMClass=com.rafael.runkmax' >> "$desktop_path"
    grep -q '^Keywords=' "$desktop_path"       || echo 'Keywords=keyboard;macro;ydotool;' >> "$desktop_path"
    return 0
  fi

  log "No runk.desktop.in found; writing desktop entry inline."
  cat > "$desktop_path" <<EOF
[Desktop Entry]
Name=RUNK-MAX
Comment=Rafael's Ultimate Ninja Keyspammer (GUI)
Exec=$exec_value
Icon=$icon_value
Terminal=false
Type=Application
Categories=Utility;Game;
StartupNotify=true
StartupWMClass=com.rafael.runkmax
Keywords=keyboard;macro;ydotool;
EOF
}

install_desktop_entry_user() {
  local app_dir="$TARGET_HOME/.local/share/applications"
  local desktop_path="$app_dir/runk-max.desktop"
  local exec_value="$TARGET_HOME/.local/bin/runk-max"
  local icon_value
  icon_value="$(install_icon_user_home_assets)"

  log "Installing .desktop entry: $desktop_path"
  mkdir -p "$app_dir"

  render_desktop_from_template_or_inline "$desktop_path" "$exec_value" "$icon_value"
  chown "$TARGET_USER":"$TARGET_USER" "$desktop_path"

  as_target_user "command -v update-desktop-database >/dev/null && update-desktop-database $TARGET_HOME/.local/share/applications || true"
  as_target_user "command -v kbuildsycoca5 >/dev/null && kbuildsycoca5 || true"
}

print_post_install() {
  cat <<EOF

[RUNK] Install complete.

Installed/configured:
- Packages: ydotool, jq, python, python-gobject, gtk4
- udev rule: /etc/udev/rules.d/99-uinput-runk.rules
- module load: /etc/modules-load.d/uinput-runk.conf
- launcher: $TARGET_HOME/.local/bin/runk-max
- desktop entry: $TARGET_HOME/.local/share/applications/runk-max.desktop
- icon (canonical): $TARGET_HOME/assets/icon.png (if $MAX_DIR/assets/icon.png existed)

Important:
- If the installer added $TARGET_USER to the uinput group, you MUST log out and log back in.

Launch:
- KDE launcher: search "RUNK-MAX"
- Or run: runk-max

EOF
}

main() {
  log "MAX_DIR: $MAX_DIR"
  log "Target user: $TARGET_USER"

  if [[ "$(id -u)" -ne 0 ]]; then
    log "Not running as root; will prompt for sudo as needed."
  fi

  sudo -v
  install_packages

  ensure_uinput_group
  add_user_to_uinput

  install_udev_rule
  ensure_uinput_module_boot

  install_launcher_wrapper
  install_desktop_entry_user

  print_post_install
}

main "$@"
