#!/bin/bash
# open-dashboard.sh — open the specship dashboard in your browser
#
# Starts a local HTTP server in the REPO ROOT (the directory that contains
# .specship/) and opens the dashboard URL. Serving from the repo root means
# the dashboard can fetch artifact files like specs/*.md and render them
# inline — otherwise those files are above the server root and unreachable
# due to browser security.
#
# Use Ctrl-C to stop the server when done.
#
# Run from your repo root (the directory that contains .specship/), or from
# any subdirectory — the script walks up to find it.

set -e

# Find the repo root (the directory containing .specship/)
REPO_ROOT=""
if [[ -d ".specship" ]]; then
    REPO_ROOT="$PWD"
else
    DIR="$PWD"
    while [[ "$DIR" != "/" ]]; do
        if [[ -d "$DIR/.specship" ]]; then
            REPO_ROOT="$DIR"
            break
        fi
        DIR=$(dirname "$DIR")
    done
fi

if [[ -z "$REPO_ROOT" ]]; then
    echo "Could not find .specship/ in $PWD or any parent directory."
    echo "Run this from inside a repo that has specship installed."
    exit 1
fi

if [[ ! -f "$REPO_ROOT/.specship/dashboard/dashboard.html" ]]; then
    echo "Found .specship/ at $REPO_ROOT/.specship but it has no dashboard/dashboard.html."
    echo "Has specship been installed? Try re-running install.sh."
    exit 1
fi

# Pick a port — try 8765 first, fall back if busy
PORT=8765
for try in 8765 8766 8767 8768 8769; do
    if ! (echo > /dev/tcp/127.0.0.1/$try) 2>/dev/null; then
        PORT=$try
        break
    fi
done

URL="http://localhost:$PORT/.specship/dashboard/dashboard.html"

echo "Serving $REPO_ROOT on port $PORT"
echo "Dashboard:  $URL"
echo "Press Ctrl-C to stop."
echo ""
echo "Note: serving the whole repo over HTTP is required so the dashboard can"
echo "fetch spec/fix/investigation content. Server is bound to 127.0.0.1 only."
echo ""

# Open the browser (best-effort, platform-aware)
(
    sleep 0.5  # give the server a moment to bind
    if command -v open >/dev/null 2>&1; then
        open "$URL"           # macOS
    elif command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$URL"       # most Linux desktops
    elif command -v wslview >/dev/null 2>&1; then
        wslview "$URL"        # WSL
    else
        echo "Open this URL in your browser: $URL"
    fi
) &

# Run the server in foreground (Ctrl-C stops it)
exec python3 -m http.server "$PORT" --directory "$REPO_ROOT" --bind 127.0.0.1
