#!/usr/bin/env bash
# One-shot setup + run for the RAV4 dealership price tracker.
# Run from anywhere:  ~/code/misc/rav4-tracker/setup.sh
#
# It will PROMPT you for the three things only you can provide:
#   1. A Google OAuth client file  (you create it in the Google Cloud Console)
#   2. A Telegram bot token        (you create it via @BotFather)
#   3. Confirmation of the 10 dealer emails  (you fill them in an editor)
# Everything else is automated. Secrets are stored OUTSIDE the repo, in
# ~/secrets/rav4-tracker/, and never committed.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/.." && pwd)"
SECRETS="${RAV4_SECRETS_DIR:-$HOME/secrets/rav4-tracker}"
cd "$HERE"

pause() { read -r -p "$1"; }
hr() { printf '\n=== %s ===\n' "$1"; }

mkdir -p "$SECRETS"; chmod 700 "$SECRETS"

# ---------------------------------------------------------------------------
hr "1/7  Python environment"
if [ ! -d .venv ]; then python3 -m venv .venv; fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
echo "deps installed."

# Run the unit tests so we fail early if anything is off.
python test_price.py

# ---------------------------------------------------------------------------
hr "2/7  Google Gmail access (scoped OAuth token — read/send/label only)"
if [ -f "$SECRETS/token.json" ]; then
  echo "Found existing token at $SECRETS/token.json — skipping consent."
else
  cat <<'EOF'
You need a one-time OAuth client file. In a browser:
  1. Go to  https://console.cloud.google.com/  and create a project
     (e.g. "personal-scripts").
  2. APIs & Services > Library > enable "Gmail API".
  3. APIs & Services > OAuth consent screen > External > fill the basics >
     under "Test users" ADD  garbanzobilson@gmail.com  (this keeps the app in
     test mode so you don't need Google verification).
  4. APIs & Services > Credentials > Create Credentials > OAuth client ID >
     Application type "Desktop app" > Create > DOWNLOAD JSON.
EOF
  read -r -p "Path to the downloaded client JSON: " CS
  CS="${CS/#\~/$HOME}"
  cp "$CS" "$SECRETS/client_secret.json"; chmod 600 "$SECRETS/client_secret.json"
  echo "A browser will open. Sign in as garbanzobilson@gmail.com and approve."
  python oauth_setup.py "$SECRETS/client_secret.json"
fi
chmod 600 "$SECRETS/token.json"

# ---------------------------------------------------------------------------
hr "3/7  Telegram bot"
if [ -f "$SECRETS/telegram.json" ]; then
  echo "Found existing $SECRETS/telegram.json — skipping."
else
  cat <<'EOF'
In the Telegram app:
  1. Message  @BotFather  ->  /newbot  -> pick a name and username.
  2. Copy the HTTP API token it gives you (looks like 123456:ABC-DEF...).
EOF
  read -r -p "Paste the bot token: " BOTTOK
  python telegram_setup.py "$BOTTOK"
fi
chmod 600 "$SECRETS/telegram.json"

# ---------------------------------------------------------------------------
hr "4/7  Quote email template"
if [ -f "$SECRETS/message.json" ]; then
  echo "Found existing $SECRETS/message.json — skipping fetch."
else
  echo "Fetching the RAV4 email you already sent..."
  python prepare_message.py || {
    echo "Couldn't auto-find it. Create $SECRETS/message.json as:"
    echo '  {"subject": "...", "body": "..."}'
    pause "Press Enter once you've created it..."
  }
fi
echo "Opening the template so you can review/edit it..."
"${EDITOR:-nano}" "$SECRETS/message.json"

# ---------------------------------------------------------------------------
hr "5/7  Dealer list — CONFIRM the 10 emails"
echo "Real emails are required (blank ones are rejected). Internet-sales"
echo "addresses get the best reply rate. Edit dealers.json now..."
pause "Press Enter to open dealers.json..."
"${EDITOR:-nano}" "$HERE/dealers.json"
# Hard stop if any email is still blank.
python - <<'PY'
import json, sys
d = json.load(open("dealers.json"))
missing = [x["name"] for x in d if not x.get("email")]
if missing:
    print("Still missing emails for:", missing); sys.exit(1)
print(f"{len(d)} dealers, all have emails.")
PY

# ---------------------------------------------------------------------------
hr "6/7  Test send, then the real blast"
read -r -p "Send a TEST copy to which address? [garbanzobilson@gmail.com]: " TESTTO
TESTTO="${TESTTO:-garbanzobilson@gmail.com}"
python send.py "--test=$TESTTO"
echo "Check that inbox. Make sure the subject/body look right."
read -r -p "Type SEND to blast all 10 dealers, anything else to abort: " GO
if [ "$GO" = "SEND" ]; then
  python send.py
  echo "Blast complete."
else
  echo "Aborted the blast. You can re-run setup.sh later; earlier steps are skipped."
  exit 0
fi

# ---------------------------------------------------------------------------
hr "7/7  Persistent poller (GitHub Actions, every 15 min)"
read -r -p "Set up the always-on poller via GitHub Actions now? [y/N]: " WANT
if [[ "$WANT" =~ ^[Yy]$ ]]; then
  if ! gh auth status >/dev/null 2>&1; then
    echo "Logging into GitHub CLI..."; gh auth login
  fi
  ( cd "$REPO_ROOT"
    gh secret set GMAIL_TOKEN_JSON     < "$SECRETS/token.json"
    gh secret set TELEGRAM_BOT_TOKEN   --body "$(python -c 'import json;print(json.load(open("'"$SECRETS"'/telegram.json"))["bot_token"])')"
    gh secret set TELEGRAM_CHAT_ID     --body "$(python -c 'import json;print(json.load(open("'"$SECRETS"'/telegram.json"))["chat_id"])')"
  )
  echo "Secrets set. Trigger one run now to confirm it works:"
  ( cd "$REPO_ROOT" && gh workflow run rav4-poll.yml ) || true
  echo "Watch it at: gh run list --workflow=rav4-poll.yml"
else
  echo "Skipped. To poll locally instead, run:  python poll.py"
fi

hr "Done"
echo "You'll get a Telegram message once 5+ dealers reply with a price."
