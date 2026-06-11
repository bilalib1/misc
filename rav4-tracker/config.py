"""Credential loading. Local runs read ~/secrets/rav4-tracker/*; GitHub Actions reads env vars."""
import json
import os

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

import paths

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]  # send + read + label


def _token_data():
    env = os.environ.get("GMAIL_TOKEN_JSON")
    if env:
        return json.loads(env)
    if paths.TOKEN.exists():
        return json.loads(paths.TOKEN.read_text())
    raise SystemExit("No Gmail credentials. Run ./setup.sh (or python oauth_setup.py) first.")


def gmail():
    creds = Credentials.from_authorized_user_info(_token_data(), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def telegram_conf():
    tok = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if tok and chat:
        return tok, str(chat)
    if paths.TELEGRAM.exists():
        d = json.loads(paths.TELEGRAM.read_text())
        return d["bot_token"], str(d["chat_id"])
    raise SystemExit("No Telegram config. Run ./setup.sh (or python telegram_setup.py) first.")
