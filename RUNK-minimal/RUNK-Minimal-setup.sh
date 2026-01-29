#!/usr/bin/env bash
# FILE: RUNK-minimal/install.sh
set -euo pipefail

log()  { printf "[RUNK] %s\n" "$*" >&2; }
warn() { printf "[RUNK][WARN] %s\n" "$*" >&2; }
die()  { printf "[RUNK][ERR] %s\n" "$*" >&2; exit 1; }

if [[ "$(id -u)" -ne 0 ]]; then
  exec sudo bash "$0" "$@"
fi

TARGET_USER="${SUDO_USER:-$(logname 2>/dev/null || true)}"
[[ -n "${TARGET_USER:-}" ]] || die "Could not determine target user"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
[[ -n "$TARGET_HOME" && -d "$TARGET_HOME" ]] || die "Could not determine home for user: $TARGET_USER"

log "One-time setup for: $TARGET_USER"

# ---- deps (Arch) ----
log "Installing packages (Arch/pacman)…"
pacman -S --needed --noconfirm ydotool

# ---- uinput group ----
if ! getent group uinput >/dev/null; then
  log "Creating group: uinput"
  groupadd uinput
fi

if ! id -nG "$TARGET_USER" | grep -qw uinput; then
  log "Adding $TARGET_USER to group uinput"
  usermod -aG uinput "$TARGET_USER"
  warn "Group membership changed. You MUST log out and log back in."
fi

# ---- udev rule ----
RULE_PATH="/etc/udev/rules.d/99-uinput-runk.rules"
log "Installing udev rule: $RULE_PATH"
cat > "$RULE_PATH" <<'EOF'
# RUNK-minimal: allow uinput access for users in the uinput group
KERNEL=="uinput", MODE="0660", GROUP="uinput", OPTIONS+="static_node=uinput"
EOF

udevadm control --reload-rules || true
udevadm trigger || true

# ---- ensure module loads at boot ----
CONF="/etc/modules-load.d/uinput-runk.conf"
log "Ensuring uinput loads at boot: $CONF"
echo "uinput" > "$CONF"

log "Loading uinput now"
modprobe uinput || true

log "Setup complete."
warn "If you were newly added to uinput group: LOG OUT and LOG BACK IN."
