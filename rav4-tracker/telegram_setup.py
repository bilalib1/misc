"""Capture your Telegram chat_id. Pass the bot token as arg 1, then message
the bot once; we poll getUpdates until we see it, then save telegram.json."""
import json
import sys
import time

import requests

import paths


def main():
    paths.ensure()
    tok = sys.argv[1].strip()
    print("Now open Telegram and send any message (e.g. 'hi') to your bot...")
    chat = None
    for _ in range(60):  # ~2 min
        r = requests.get(f"https://api.telegram.org/bot{tok}/getUpdates", timeout=20).json()
        for u in r.get("result", []):
            msg = u.get("message") or u.get("edited_message")
            if msg:
                chat = msg["chat"]["id"]
        if chat:
            break
        time.sleep(2)
    if not chat:
        raise SystemExit("No message received. Re-run and message the bot promptly.")
    paths.TELEGRAM.write_text(json.dumps({"bot_token": tok, "chat_id": chat}))
    requests.get(
        f"https://api.telegram.org/bot{tok}/sendMessage",
        params={"chat_id": chat, "text": "RAV4 tracker connected. You'll get the lowest quote here."},
        timeout=20,
    )
    print(f"Saved {paths.TELEGRAM} (chat_id={chat}). Check Telegram for a confirmation message.")


if __name__ == "__main__":
    main()
