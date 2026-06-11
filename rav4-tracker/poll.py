"""Check for dealer replies, extract each price, and once >=5 dealers have
replied with a parseable price, Telegram the lowest one — exactly once.

Idempotency: after notifying we add the Gmail label `rav4-notified` to the
winning reply. Every later run sees that label and exits. No external state.
"""
import base64
import json
from pathlib import Path

import requests

from config import gmail, telegram_conf
from price import pick_price

DEALERS = Path(__file__).parent / "dealers.json"
LABEL = "rav4-notified"
MIN_REPLIES = 5


def plain(payload):
    if payload.get("mimeType", "").startswith("text/plain") and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", "replace")
    for part in payload.get("parts", []) or []:
        text = plain(part)
        if text:
            return text
    return ""


def label_id(g, name):
    for lab in g.users().labels().list(userId="me").execute().get("labels", []):
        if lab["name"] == name:
            return lab["id"]
    return g.users().labels().create(userId="me", body={"name": name}).execute()["id"]


def already_notified(g):
    res = g.users().messages().list(userId="me", q=f"label:{LABEL}", maxResults=1).execute()
    return bool(res.get("messages"))


def notify(text):
    tok, chat = telegram_conf()
    requests.get(
        f"https://api.telegram.org/bot{tok}/sendMessage",
        params={"chat_id": chat, "text": text},
        timeout=20,
    )


def main():
    g = gmail()
    lid = label_id(g, LABEL)
    if already_notified(g):
        print("Already notified earlier; nothing to do.")
        return

    dealers = json.loads(DEALERS.read_text())
    priced = []  # (price, dealer_name, msg_id)
    for d in dealers:
        if not d.get("email"):
            continue
        res = g.users().messages().list(
            userId="me", q=f"from:{d['email']} newer_than:21d", maxResults=5
        ).execute()
        for ref in res.get("messages", []):
            full = g.users().messages().get(userId="me", id=ref["id"], format="full").execute()
            price = pick_price(plain(full["payload"]))
            if price is not None:
                priced.append((price, d["name"], ref["id"]))
                break

    print(f"{len(priced)} of {len(dealers)} dealers replied with a parseable price.")
    if len(priced) < MIN_REPLIES:
        return

    price, name, msg_id = min(priced, key=lambda x: x[0])
    text = f"Lowest RAV4 quote: ${price:,.0f} — {name}. ({len(priced)} of {len(dealers)} replied)"
    notify(text)
    g.users().messages().modify(userId="me", id=msg_id, body={"addLabelIds": [lid]}).execute()
    print("Notified:", text)


if __name__ == "__main__":
    main()
