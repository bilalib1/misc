#!/bin/bash
# Launch Chrome with the DevTools debugging port so the python helpers can drive
# it -- invisibly, with no window pop-up and without stealing focus.
#
# WHY A COPIED PROFILE: Chrome 136+ ignores --remote-debugging-port on the
# DEFAULT user-data-dir (anti-cookie-theft mitigation). We copy just the login
# state (cookies + Local State) into a separate dir so the port works AND you
# stay logged in (same Keychain key decrypts the copied cookies). Your real
# profile is never opened with the port and is left untouched.
#
# TWO INVISIBLE MODES (see plans/browser_interaction.md "Headless strategy"):
#   headless  (DEFAULT) -- --headless=new. Genuinely windowless. Chrome 149 still
#             leaks "HeadlessChrome" in the UA, so we override --user-agent to the
#             real string. Near-perfect fingerprint; right for Gmail/Sheets/Drive
#             and any site without hardened anti-bot. Nothing ever appears.
#   headed    -- a REAL headed Chrome launched hidden + backgrounded (open -g -j),
#             so it renders a true GPU/Canvas/WebGL fingerprint but never shows a
#             window or takes focus. Use for Akamai/Cloudflare sites (CarMax,
#             Carvana) that block headless. Hideable, not strictly windowless.
#
# WHY WE NO LONGER QUIT YOUR MAIN CHROME EVERY TIME: the copied profile is
# reused. We only quit + recopy login state when the profile is missing or you
# pass --refresh. After first setup, launching is non-disruptive and silent.
#
# Usage:
#   ./launch_chrome_with_cdp.sh [port]              # headless (default)
#   CDP_MODE=headed ./launch_chrome_with_cdp.sh     # real-fingerprint, hidden
#   ./launch_chrome_with_cdp.sh --refresh           # re-pull login state (quits Chrome)
#   ./launch_chrome_with_cdp.sh 9222 --headed       # positional port + mode flag
set -euo pipefail

PORT=9222
MODE="${CDP_MODE:-headless}"
REFRESH=0
for arg in "$@"; do
  case "$arg" in
    --refresh) REFRESH=1 ;;
    --headed)  MODE="headed" ;;
    --headless) MODE="headless" ;;
    ''|*[!0-9]*) ;;            # ignore non-numeric
    *) PORT="$arg" ;;          # bare number => port
  esac
done

BIN="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
SRC="$HOME/Library/Application Support/Google/Chrome"
DST="$HOME/Library/Application Support/Google/Chrome-CDP"

if curl -s --max-time 1 "http://localhost:$PORT/json/version" >/dev/null 2>&1; then
  echo "CDP already up on port $PORT (mode unchanged). Use --refresh after quitting it to switch."
  exit 0
fi

# Real UA for this Chrome build, so --headless=new doesn't leak "HeadlessChrome".
VER="$("$BIN" --version 2>/dev/null | grep -oE '[0-9]+(\.[0-9]+)+' || echo '149.0.0.0')"
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/${VER} Safari/537.36"

# (Re)create the copied login profile only when needed -- this is the only path
# that touches your real Chrome.
if [ "$REFRESH" = "1" ] || { [ ! -e "$DST/Default/Cookies" ] && [ ! -e "$DST/Default/Network/Cookies" ]; }; then
  echo "Refreshing copied login state (this quits your main Chrome briefly)..."
  osascript -e 'tell application "Google Chrome" to quit' 2>/dev/null || true
  for _ in $(seq 1 20); do pgrep -x "Google Chrome" >/dev/null || break; sleep 0.5; done
  rm -rf "$DST"; mkdir -p "$DST/Default/Network"
  cp "$SRC/Local State" "$DST/Local State"
  cp "$SRC/Default/Cookies" "$DST/Default/Cookies" 2>/dev/null || true
  cp "$SRC/Default/Network/Cookies" "$DST/Default/Network/Cookies" 2>/dev/null || \
    cp "$SRC/Default/Cookies" "$DST/Default/Network/Cookies" 2>/dev/null || true
  cp "$SRC/Default/Preferences" "$DST/Default/Preferences" 2>/dev/null || true
  cp "$SRC/Default/Login Data" "$DST/Default/Login Data" 2>/dev/null || true
else
  echo "Reusing existing copied profile (no quit, no disruption). Pass --refresh to re-pull logins."
fi

COMMON=(
  --user-data-dir="$DST"
  --remote-debugging-port="$PORT"
  --remote-allow-origins="http://localhost:$PORT"
  --user-agent="$UA"
  --no-first-run --no-default-browser-check --restore-last-session=false
)

if [ "$MODE" = "headless" ]; then
  echo "Launching --headless=new on port $PORT (windowless, UA-patched)..."
  "$BIN" --headless=new "${COMMON[@]}" about:blank >/tmp/chrome_cdp.log 2>&1 &
else
  echo "Launching headed Chrome HIDDEN + backgrounded on port $PORT (real fingerprint, no focus)..."
  # open -g (no foreground) -j (hidden) -n (new instance). The window exists but
  # the app stays hidden, so it never pops up or steals focus.
  open -na "Google Chrome" -g -j --args "${COMMON[@]}" about:blank
fi

for _ in $(seq 1 24); do
  V=$(curl -s --max-time 1 "http://localhost:$PORT/json/version" 2>/dev/null || true)
  [ -n "$V" ] && { echo "CDP up ($MODE):"; echo "$V" | head -3; exit 0; }
  sleep 0.5
done
echo "ERROR: port $PORT never came up (see /tmp/chrome_cdp.log)" >&2; exit 1
