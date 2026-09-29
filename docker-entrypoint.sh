#!/bin/sh
set -eu

# PyAutoGUI imports need an X display. This private Xvfb display only lets the
# Linux container initialize its dependencies; it does not expose or control
# the Windows desktop.
DISPLAY_NUMBER="${DISPLAY:-:99}"
XAUTHORITY_FILE="${XAUTHORITY:-/tmp/touchlessmouse-xauthority}"

touch "$XAUTHORITY_FILE"
xauth -f "$XAUTHORITY_FILE" add "$DISPLAY_NUMBER" . "$(mcookie)"

Xvfb "$DISPLAY_NUMBER" \
    -screen 0 1280x1024x24 \
    -nolisten tcp \
    -auth "$XAUTHORITY_FILE" &

export DISPLAY="$DISPLAY_NUMBER"
export XAUTHORITY="$XAUTHORITY_FILE"

# Wait for the X socket before importing PyAutoGUI through the FastAPI app.
display_socket="/tmp/.X11-unix/X${DISPLAY_NUMBER#:}"
attempt=0
while [ ! -S "$display_socket" ]; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 50 ]; then
        echo "Xvfb did not become ready at $DISPLAY_NUMBER" >&2
        exit 1
    fi
    sleep 0.1
done

# Uvicorn replaces this shell as PID 1, so Docker manages the server process
# directly and its logs are emitted to the container log stream.
exec "$@"
