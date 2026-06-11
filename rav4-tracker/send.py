"""Blast the saved quote request to every dealer in dealers.json.

Usage:
  python send.py --test=you@example.com   # one test mail to yourself
  python send.py --dry-run                 # print recipients, send nothing
  python send.py                           # the real blast
"""
import base64
import json
import sys
import time
from email.mime.text import MIMEText
from pathlib import Path

from config import gmail
import paths

DEALERS = Path(__file__).parent / "dealers.json"


def raw(to, subject, body):
    msg = MIMEText(body)
    msg["To"] = to
    msg["Subject"] = subject
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


def send_one(g, to, subject, body):
    return g.users().messages().send(userId="me", body={"raw": raw(to, subject, body)}).execute()


def main():
    args = sys.argv[1:]
    dry = "--dry-run" in args
    test_to = next((a.split("=", 1)[1] for a in args if a.startswith("--test=")), None)

    msg = json.loads(paths.MESSAGE.read_text())
    dealers = json.loads(DEALERS.read_text())
    g = gmail()

    if test_to:
        r = send_one(g, test_to, "[TEST] " + msg["subject"], msg["body"])
        print(f"Test sent to {test_to}: id={r['id']}")
        return

    bad = [d["name"] for d in dealers if not d.get("email")]
    if bad and not dry:
        raise SystemExit(f"These dealers have no email yet: {bad}. Fill dealers.json first.")

    for d in dealers:
        if dry:
            print(f"[dry-run] -> {d['name']} <{d.get('email') or 'MISSING'}>")
            continue
        r = send_one(g, d["email"], msg["subject"], msg["body"])
        d["sent_msg_id"] = r["id"]
        print(f"Sent -> {d['name']} <{d['email']}>: id={r['id']}")
        time.sleep(2)  # gentle spacing, less spammy

    if not dry:
        DEALERS.write_text(json.dumps(dealers, indent=2))
        print(f"Updated {DEALERS} with sent message ids.")


if __name__ == "__main__":
    main()
