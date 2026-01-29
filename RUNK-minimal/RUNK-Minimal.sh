#!/usr/bin/env bash
# FILE: RUNK-minimal/RUNK-Minimal.sh
set -euo pipefail

# ---------------- CONFIG ----------------
MIN_DELAY=0.2       # minimum delay between cycles
MAX_DELAY=0.8       # maximum delay between cycles

IDLE_CHANCE=10      # 1 in N loops triggers idle gap
IDLE_MIN=1          # min idle seconds
IDLE_MAX=3          # max idle seconds

DOUBLE_TAP_CHANCE=8 # 1 in N presses triggers double tap

PRESS_MIN=0.05      # min press duration
PRESS_MAX=0.18      # max press duration
# ----------------------------------------

USER_ID="$(id -u)"
GROUP_ID="$(id -g)"

SOCKET_DIR="${XDG_RUNTIME_DIR:-$HOME}"
SOCKET="$SOCKET_DIR/ydotool-runk-minimal.sock"
export YDOTOOL_SOCKET="$SOCKET"

cleanup() {
  [[ -n "${YDOTOOLD_PID:-}" ]] && kill "$YDOTOOLD_PID" 2>/dev/null || true
  rm -f "$SOCKET" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# ---------------- START ydotoold ----------------
rm -f "$SOCKET" 2>/dev/null || true

ydotoold \
  --socket-path="$SOCKET" \
  --socket-own="$USER_ID:$GROUP_ID" \
  >/dev/null 2>&1 &

YDOTOOLD_PID=$!
sleep 0.25

# Keycodes (evdev)
W=17
A=30
S=31
D=32

rand_float() {
  python3 - <<PY
import random
print(random.uniform($1, $2))
PY
}

press() {
  local key="$1"
  local duration
  duration="$(rand_float "$PRESS_MIN" "$PRESS_MAX")"
  ydotool key "$key":1 >/dev/null 2>&1
  sleep "$duration"
  ydotool key "$key":0 >/dev/null 2>&1
}

echo "[RUNK] RUNK-Minimal running (Ctrl+C to stop)"

# ---------------- MAIN LOOP ----------------
while true; do
  (( RANDOM % IDLE_CHANCE == 0 )) && sleep "$(rand_float "$IDLE_MIN" "$IDLE_MAX")"

  AXIS=$((RANDOM % 3)) # 0=W/S, 1=A/D, 2=diagonal

  case "$AXIS" in
    0) KEYS=($W $S) ;;
    1) KEYS=($A $D) ;;
    2)
      case $((RANDOM % 4)) in
        0) KEYS=($W $A) ;;
        1) KEYS=($W $D) ;;
        2) KEYS=($S $A) ;;
        3) KEYS=($S $D) ;;
      esac
      ;;
  esac

  (( RANDOM % 2 == 0 )) && KEYS=("${KEYS[1]}" "${KEYS[0]}")

  for key in "${KEYS[@]}"; do
    press "$key"
    (( RANDOM % DOUBLE_TAP_CHANCE == 0 )) && press "$key"
  done

  for (( idx=${#KEYS[@]}-1 ; idx>=0 ; idx-- )); do
    press "${KEYS[idx]}"
    (( RANDOM % DOUBLE_TAP_CHANCE == 0 )) && press "${KEYS[idx]}"
  done

  sleep "$(rand_float "$MIN_DELAY" "$MAX_DELAY")"
done
