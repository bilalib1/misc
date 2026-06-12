#!/bin/bash
# Launch Chrome with the DevTools debugging port so the python helpers can drive it.
#
# Why a copied profile: Chrome 136+ ignores --remote-debugging-port on the DEFAULT
# user-data-dir (anti-cookie-theft mitigation). We copy just the login state
# (cookies + Local State) into a separate dir so the port works AND you stay
# logged in (same Keychain key decrypts the copied cookies). Your real profile is
# never opened with the port and is left untouched.
#
# Usage: ./launch_chrome_with_cdp.sh [port]   (default 9222)
set -euo pipefail
PORT="${1:-9222}"
BIN="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
SRC="$HOME/Library/Application Support/Google/Chrome"
DST="$HOME/Library/Application Support/Google/Chrome-CDP"

if curl -s --max-time 1 "http://localhost:$PORT/json/version" >/dev/null 2>&1; then
  echo "CDP already up on port $PORT"; exit 0
fi

echo "Quitting Chrome..."
osascript -e 'tell application "Google Chrome" to quit' 2>/dev/null || true
for _ in $(seq 1 20); do pgrep -x "Google Chrome" >/dev/null || break; sleep 0.5; done

echo "Copying login state -> $DST"
rm -rf "$DST"; mkdir -p "$DST/Default/Network"
cp "$SRC/Local State" "$DST/Local State"
cp "$SRC/Default/Cookies" "$DST/Default/Cookies" 2>/dev/null || true
cp "$SRC/Default/Network/Cookies" "$DST/Default/Network/Cookies" 2>/dev/null || \
  cp "$SRC/Default/Cookies" "$DST/Default/Network/Cookies" 2>/dev/null || true
cp "$SRC/Default/Preferences" "$DST/Default/Preferences" 2>/dev/null || true
cp "$SRC/Default/Login Data" "$DST/Default/Login Data" 2>/dev/null || true

echo "Launching Chrome with --remote-debugging-port=$PORT"
"$BIN" --user-data-dir="$DST" --remote-debugging-port="$PORT" \
  --remote-allow-origins="http://localhost:$PORT" \
  --no-first-run --no-default-browser-check --restore-last-session=false \
  >/tmp/chrome_cdp.log 2>&1 &

for _ in $(seq 1 20); do
  V=$(curl -s --max-time 1 "http://localhost:$PORT/json/version" 2>/dev/null || true)
  [ -n "$V" ] && { echo "CDP up:"; echo "$V" | head -3; exit 0; }
  sleep 0.5
done
echo "ERROR: port $PORT never came up (see /tmp/chrome_cdp.log)" >&2; exit 1
