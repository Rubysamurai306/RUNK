#!/usr/bin/env bash
set -euo pipefail

# -------- CONFIG --------
MIN_DELAY=0.3
MAX_DELAY=1.2
SOCKET="$HOME/.ydotool_socket"
# ------------------------

USER_ID="$(id -u)"
GROUP_ID="$(id -g)"
export YDOTOOL_SOCKET="$SOCKET"

cleanup() {
    [[ -n "${YDOTOOLD_PID:-}" ]] && kill "$YDOTOOLD_PID" 2>/dev/null || true
    rm -f "$SOCKET"
}
trap cleanup EXIT INT TERM

# ------------------------
# Start ydotoold (user)
# ------------------------
rm -f "$SOCKET"

ydotoold \
  --socket-path="$SOCKET" \
  --socket-own="$USER_ID:$GROUP_ID" \
  >/dev/null 2>&1 &

YDOTOOLD_PID=$!
sleep 0.3

# Linux keycodes
W=17
A=30
S=31
D=32

rand_sleep() {
    awk -v min="$MIN_DELAY" -v max="$MAX_DELAY" \
        'BEGIN{srand(); print min+rand()*(max-min)}'
}

press() {
    ydotool key $1:1 $1:0
}

echo "[RUNK] balanced WASD spam running (Ctrl+C to stop)"

# ------------------------
# Main loop
# ------------------------
while true; do
    # Choose axis: 0 = W/S, 1 = A/D
    AXIS=$((RANDOM % 2))

    if [[ "$AXIS" -eq 0 ]]; then
        FIRST=$W
        SECOND=$S
    else
        FIRST=$A
        SECOND=$D
    fi

    # Randomize order
    if (( RANDOM % 2 )); then
        TMP=$FIRST
        FIRST=$SECOND
        SECOND=$TMP
    fi

    press "$FIRST"
    sleep "$(rand_sleep)"

    press "$SECOND"
    sleep "$(rand_sleep)"
done
