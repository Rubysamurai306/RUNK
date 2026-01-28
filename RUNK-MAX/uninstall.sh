#!/usr/bin/env bash
# RUNK-MAX/uninstall.sh
#
# Removes what install.sh creates (and optionally more):
# - ~/.local/bin/runk-max
# - ~/.local/share/applications/runk-max.desktop
# - ~/assets/icon.png (optional)
# - ~/.local/share/icons/hicolor/*/apps/runk-max.{png,svg} (optional)
# - /etc/udev/rules.d/99-uinput-runk.rules (sudo)
# - /etc/modules-load.d/uinput-runk.conf (sudo)
# - Optionally remove target user from uinput group (sudo)
# - Optionally remove packages on Arch/pacman (sudo)
#
# Usage:
#   ./uninstall.sh
#   ./uninstall.sh --keep-icon
#   ./uninstall.sh --remove-from-uinput-group
#   sudo ./uninstall.sh --purge-packages
#   sudo ./uninstall.sh --purge-packages --remove-from-uinput-group
#
set -euo pipefail

log()  { printf "[RUNK] %s\n" "$*"; }
warn() { printf "[RUNK][WARN] %s\n" "$*" >&2; }
die()  { printf "[RUNK][ERR] %s\n" "$*" >&2; exit 1; }

KEEP_ICON=0
REMOVE_FROM_UINPUT_GROUP=0
REMOVE_THEME_ICONS=0
PURGE_PACKAGES=0

for arg in "${@:-}"; do
  case "$arg" in
    --keep-icon) KEEP_ICON=1 ;;
    --remove-from-uinput-group) REMOVE_FROM_UINPUT_GROUP=1 ;;
    --remove-theme-icons) REMOVE_THEME_ICONS=1 ;;
    --purge-packages) PURGE_PACKAGES=1 ;;
    -h|--help)
      cat <<'EOF'
RUNK-MAX uninstall.sh

Options:
  --keep-icon                 Keep ~/assets/icon.png
  --remove-theme-icons        Remove ~/.local/share/icons/hicolor/*/apps/runk-max.(png|svg)
  --remove-from-uinput-group  Remove the target user from the "uinput" group (requires sudo)
  --purge-packages            Arch only: remove packages installed by installer (requires sudo)
  -h, --help                  Show this help

Notes:
- Packages are only removed with --purge-packages.
- System files (/etc/udev, /etc/modules-load.d) are only removed when run with sudo.
EOF
      exit 0
      ;;
    *) die "Unknown argument: $arg" ;;
  esac
done

TARGET_USER="${SUDO_USER:-$(id -un)}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
[[ -n "$TARGET_HOME" && -d "$TARGET_HOME" ]] || die "Could not determine home for user: $TARGET_USER"

as_target_user() {
  sudo -u "$TARGET_USER" env HOME="$TARGET_HOME" bash -lc "$*"
}

need_root() {
  if [[ "$(id -u)" -ne 0 ]]; then
    die "This step needs sudo/root. Re-run as: sudo $0 ${*:-}"
  fi
}

remove_file() {
  local path="$1"
  if [[ -e "$path" ]]; then
    log "Removing: $path"
    rm -f -- "$path"
  else
    log "Not found (ok): $path"
  fi
}

remove_glob_matches() {
  # Remove files matching a glob (without failing if none exist)
  local pattern="$1"
  shopt -s nullglob
  local matches=( $pattern )
  shopt -u nullglob

  if (( ${#matches[@]} == 0 )); then
    log "Not found (ok): $pattern"
    return 0
  fi

  for f in "${matches[@]}"; do
    log "Removing: $f"
    rm -f -- "$f"
  done
}

refresh_desktop_caches() {
  as_target_user "command -v update-desktop-database >/dev/null && update-desktop-database '$TARGET_HOME/.local/share/applications' || true"
  as_target_user "command -v kbuildsycoca5 >/dev/null && kbuildsycoca5 || true"
  as_target_user "command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -f -t '$TARGET_HOME/.local/share/icons/hicolor' || true"
}

remove_user_artifacts() {
  remove_file "$TARGET_HOME/.local/bin/runk-max"
  remove_file "$TARGET_HOME/.local/share/applications/runk-max.desktop"

  if [[ "$KEEP_ICON" -eq 1 ]]; then
    log "Keeping icon (per --keep-icon): $TARGET_HOME/assets/icon.png"
  else
    remove_file "$TARGET_HOME/assets/icon.png"
    if [[ -d "$TARGET_HOME/assets" ]] && [[ -z "$(ls -A "$TARGET_HOME/assets" 2>/dev/null || true)" ]]; then
      log "Removing empty dir: $TARGET_HOME/assets"
      rmdir "$TARGET_HOME/assets" 2>/dev/null || true
    fi
  fi

  if [[ "$REMOVE_THEME_ICONS" -eq 1 ]]; then
    # Common icon sizes; keep glob wide in case you add more later.
    remove_glob_matches "$TARGET_HOME/.local/share/icons/hicolor/"'*/apps/runk-max.png'
    remove_glob_matches "$TARGET_HOME/.local/share/icons/hicolor/"'*/apps/runk-max.svg'
  fi

  refresh_desktop_caches
}

remove_system_artifacts() {
  local rule_path="/etc/udev/rules.d/99-uinput-runk.rules"
  local mod_conf="/etc/modules-load.d/uinput-runk.conf"

  if [[ "$(id -u)" -ne 0 ]]; then
    warn "Not running as root; skipping system-level removals."
    warn "Run with sudo to remove:"
    warn "  $rule_path"
    warn "  $mod_conf"
    return 0
  fi

  remove_file "$rule_path"
  remove_file "$mod_conf"

  log "Reloading udev rules"
  udevadm control --reload-rules || true
  udevadm trigger || true

  log "Note: not unloading uinput kernel module (may affect other apps)."
}

maybe_remove_user_from_group() {
  if [[ "$REMOVE_FROM_UINPUT_GROUP" -ne 1 ]]; then
    return 0
  fi
  need_root "$@"

  if ! getent group uinput >/dev/null; then
    log "Group uinput does not exist (ok)."
    return 0
  fi

  if id -nG "$TARGET_USER" | grep -qw uinput; then
    log "Removing $TARGET_USER from group uinput"
    gpasswd -d "$TARGET_USER" uinput || true
    warn "User group membership changed. Log out/in for it to take effect."
  else
    log "User not in group uinput (ok): $TARGET_USER"
  fi
}

is_arch_linux() {
  [[ -f /etc/arch-release ]] || [[ -f /etc/os-release && "$(grep -E '^ID=' /etc/os-release | cut -d= -f2 | tr -d '"')" == "arch" ]]
}

maybe_purge_packages() {
  if [[ "$PURGE_PACKAGES" -ne 1 ]]; then
    return 0
  fi
  need_root "$@"

  if ! is_arch_linux; then
    die "--purge-packages is currently implemented for Arch Linux only."
  fi

  if ! command -v pacman >/dev/null; then
    die "pacman not found; cannot purge packages."
  fi

  # Only remove if installed; keep it safe + idempotent.
  local pkgs=(ydotool jq python python-gobject gtk4)
  local installed=()
  for p in "${pkgs[@]}"; do
    if pacman -Qi "$p" >/dev/null 2>&1; then
      installed+=("$p")
    fi
  done

  if (( ${#installed[@]} == 0 )); then
    log "No target packages found installed (ok)."
    return 0
  fi

  log "Purging packages (pacman -Rns): ${installed[*]}"
  pacman -Rns --noconfirm "${installed[@]}" || warn "Package removal had warnings/errors; check pacman output."
}

print_post_uninstall() {
  cat <<EOF

[RUNK] Uninstall complete.

Removed (user):
- $TARGET_HOME/.local/bin/runk-max
- $TARGET_HOME/.local/share/applications/runk-max.desktop
- $TARGET_HOME/assets/icon.png $( [[ "$KEEP_ICON" -eq 1 ]] && echo "(kept)" || echo "(removed if existed)" )
- theme icons: $( [[ "$REMOVE_THEME_ICONS" -eq 1 ]] && echo "removed (if existed)" || echo "kept" )

System-level (only if run with sudo):
- /etc/udev/rules.d/99-uinput-runk.rules
- /etc/modules-load.d/uinput-runk.conf

Packages:
- $( [[ "$PURGE_PACKAGES" -eq 1 ]] && echo "purge attempted (Arch)" || echo "not removed" )

EOF
}

main() {
  log "Target user: $TARGET_USER"
  remove_user_artifacts
  remove_system_artifacts
  maybe_remove_user_from_group "$@"
  maybe_purge_packages "$@"
  print_post_uninstall
}

main "$@"
