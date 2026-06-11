"""Pull the RAV4 quote email you already sent and save it as the template to
re-send. Writes ~/secrets/rav4-tracker/message.json. Review it before blasting."""
import base64
import json

from config import gmail
import paths


def plain_from_payload(payload):
    if payload.get("mimeType", "").startswith("text/plain") and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", "replace")
    for part in payload.get("parts", []) or []:
        text = plain_from_payload(part)
        if text:
            return text
    return ""


def main():
    paths.ensure()
    g = gmail()
    res = g.users().messages().list(
        userId="me", q='in:sent (RAV4 OR "RAV 4")', maxResults=5
    ).execute()
    msgs = res.get("messages", [])
    if not msgs:
        raise SystemExit(
            'No sent RAV4 email found. Create message.json manually:\n'
            '  {"subject": "...", "body": "..."}\n'
            f"  at {paths.MESSAGE}"
        )
    m = g.users().messages().get(userId="me", id=msgs[0]["id"], format="full").execute()
    headers = {h["name"].lower(): h["value"] for h in m["payload"]["headers"]}
    subject = headers.get("subject", "RAV4 quote request")
    body = plain_from_payload(m["payload"]).strip()
    paths.MESSAGE.write_text(json.dumps({"subject": subject, "body": body}, indent=2))
    print(f"Saved {paths.MESSAGE}")
    print(f"  subject: {subject!r}")
    print(f"  body: {len(body)} chars. REVIEW it before sending.")


if __name__ == "__main__":
    main()
