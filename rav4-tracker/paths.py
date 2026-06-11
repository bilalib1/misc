"""All local secrets live outside the repo, in ~/secrets/rav4-tracker/.
Override with RAV4_SECRETS_DIR. GitHub Actions ignores this and uses env vars."""
import os
from pathlib import Path

SECRETS_DIR = Path(
    os.environ.get("RAV4_SECRETS_DIR", Path.home() / "secrets" / "rav4-tracker")
)

TOKEN = SECRETS_DIR / "token.json"            # Gmail OAuth refresh token (scoped: gmail.modify)
CLIENT_SECRET = SECRETS_DIR / "client_secret.json"  # downloaded OAuth client
TELEGRAM = SECRETS_DIR / "telegram.json"      # {bot_token, chat_id}
MESSAGE = SECRETS_DIR / "message.json"        # {subject, body} — has your name/phone, kept private


def ensure():
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    return SECRETS_DIR
