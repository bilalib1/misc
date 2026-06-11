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

    me = requests.get(f"https://api.telegram.org/bot{tok}/getMe", timeout=20).json()
    if not me.get("ok"):
        raise SystemExit(f"That bot token looks wrong: {me.get('description', me)}")
    uname = me["result"]["username"]
    # A leftover webhook makes getUpdates return nothing; clear it.
    requests.get(f"https://api.telegram.org/bot{tok}/deleteWebhook", timeout=20)

    print(f"Your bot is @{uname}.")
    print(f"  Open  https://t.me/{uname}  -> tap START -> send any message (e.g. 'hi').")
    print("  (Messaging BotFather or any other chat will NOT work.)")
    chat = None
    for _ in range(90):  # ~3 min
        r = requests.get(f"https://api.telegram.org/bot{tok}/getUpdates", timeout=20).json()
        for u in r.get("result", []):
            msg = u.get("message") or u.get("edited_message")
            if msg:
                chat = msg["chat"]["id"]
        if chat:
            break
        time.sleep(2)
    if not chat:
        raise SystemExit(f"No message seen. Make sure you messaged @{uname} (not BotFather) and re-run.")
    paths.TELEGRAM.write_text(json.dumps({"bot_token": tok, "chat_id": chat}))
    requests.get(
        f"https://api.telegram.org/bot{tok}/sendMessage",
        params={"chat_id": chat, "text": "RAV4 tracker connected. You'll get the lowest quote here."},
        timeout=20,
    )
    print(f"Saved {paths.TELEGRAM} (chat_id={chat}). Check Telegram for a confirmation message.")


if __name__ == "__main__":
    main()
