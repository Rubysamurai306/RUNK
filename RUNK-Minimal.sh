#!/usr/bin/env bash
set -euo pipefail

# ---------------- CONFIG ----------------
MIN_DELAY=0.2       # minimum delay between presses
MAX_DELAY=0.8       # maximum delay
SOCKET="$HOME/.ydotool_socket"
IDLE_CHANCE=10      # 1 in 10 loops triggers idle gap
IDLE_MIN=1          # min idle seconds
IDLE_MAX=3          # max idle seconds
DOUBLE_TAP_CHANCE=8 # 1 in 8 loops triggers double tap
PAUSE_KEY=49        # keycode for ' (apostrophe)
# ----------------------------------------

USER_ID="$(id -u)"
GROUP_ID="$(id -g)"
export YDOTOOL_SOCKET="$SOCKET"

PAUSED=0

cleanup() {
    [[ -n "${YDOTOOLD_PID:-}" ]] && kill "$YDOTOOLD_PID" 2>/dev/null || true
    rm -f "$SOCKET"
}
trap cleanup EXIT INT TERM

# ---------------- START ydotoold ----------------
rm -f "$SOCKET"

ydotoold \
    --socket-path="$SOCKET" \
    --socket-own="$USER_ID:$GROUP_ID" \
    >/dev/null 2>&1 &

YDOTOOLD_PID=$!
sleep 0.3

# Keycodes
W=17
A=30
S=31
D=32

rand_sleep() {
    awk -v min="$MIN_DELAY" -v max="$MAX_DELAY" \
        'BEGIN{srand(); print min+rand()*(max-min)}'
}

rand_idle() {
    awk -v min="$IDLE_MIN" -v max="$IDLE_MAX" \
        'BEGIN{srand(); print min+rand()*(max-min)}'
}

press() {
    local key=$1
    local duration
    duration=$(awk -v min=0.05 -v max=0.18 'BEGIN{srand(); print min+rand()*(max-min)}')
    ydotool key "$key":1
    sleep "$duration"
    ydotool key "$key":0
}

echo "[RUNK] balanced plus spam running (press ' to toggle pause)"

# ---------------- MAIN LOOP ----------------
while true; do
    # Check pause key
    if ydotool get-key "$PAUSE_KEY" >/dev/null 2>&1; then
        PAUSED=$((1-PAUSED))
        if (( PAUSED )); then
            echo "[RUNK] Paused..."
        else
            echo "[RUNK] Resumed..."
        fi
        sleep 0.5 # debounce
    fi

    # If paused, skip movement
    while (( PAUSED )); do
        sleep 0.3
        # keep checking pause key to resume
        if ydotool get-key "$PAUSE_KEY" >/dev/null 2>&1; then
            PAUSED=0
            echo "[RUNK] Resumed..."
            sleep 0.5
        fi
    done

    # Possibly idle
    (( RANDOM % IDLE_CHANCE == 0 )) && sleep "$(rand_idle)"

    # Choose movement: axis or diagonal
    AXIS=$((RANDOM % 3)) # 0=W/S, 1=A/D, 2=diagonal

    case "$AXIS" in
        0) KEYS=($W $S) ;;
        1) KEYS=($A $D) ;;
        2) # diagonal W+A, W+D, S+A, S+D
           DIAG=$((RANDOM % 4))
           case $DIAG in
               0) KEYS=($W $A) ;;
               1) KEYS=($W $D) ;;
               2) KEYS=($S $A) ;;
               3) KEYS=($S $D) ;;
           esac
           ;;
    esac

    # Micro-randomization: shuffle order
    (( RANDOM % 2 == 0 )) && KEYS=("${KEYS[1]}" "${KEYS[0]}")

    # Press keys with optional double tap
    for key in "${KEYS[@]}"; do
        press "$key"
        (( RANDOM % DOUBLE_TAP_CHANCE == 0 )) && press "$key"
    done

    # Reverse keys to maintain drift-free behavior
    for (( idx=${#KEYS[@]}-1 ; idx>=0 ; idx-- )); do
        press "${KEYS[idx]}"
        (( RANDOM % DOUBLE_TAP_CHANCE == 0 )) && press "${KEYS[idx]}"
    done

    # Random sleep before next loop
    sleep "$(rand_sleep)"
done

