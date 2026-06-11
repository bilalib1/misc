"""Conversational control plane. The owner texts the Telegram bot; each message
is handed to a Claude Code agent (with this plan + code as context) that answers
and can modify the service. Runs once per cron tick, after poll.py.

Security: only the owner's chat_id is ever served. Anyone else is ignored.
Cloud activation needs ANTHROPIC_API_KEY (Claude Code OAuth isn't available in
CI); without it (or without the `claude` binary) this no-ops cleanly.
"""
import os
import shutil
import subprocess
from pathlib import Path

import requests

from config import telegram_conf

TRACKER = Path(__file__).resolve().parent
REPO = TRACKER.parent  # ~/code/misc
PLAN = REPO / "plans" / "2026-06-10-rav4-dealership-price-tracker.md"

ALLOWED_TOOLS = "Read Edit Write Grep Glob Bash(git *) Bash(python3 *) Bash(python *)"


def get_updates(tok, offset=None):
    params = {"timeout": 0}
    if offset is not None:
        params["offset"] = offset
    r = requests.get(f"https://api.telegram.org/bot{tok}/getUpdates", params=params, timeout=30)
    return r.json().get("result", [])


def send(tok, chat, text):
    for i in range(0, max(len(text), 1), 3500):  # Telegram caps at 4096 chars
        requests.get(
            f"https://api.telegram.org/bot{tok}/sendMessage",
            params={"chat_id": chat, "text": text[i:i + 3500] or "(no output)"},
            timeout=20,
        )


def run_agent(query):
    prompt = (
        "You are operating the RAV4 dealership price-tracker service. "
        f"Its living plan is at {PLAN} and its code in {TRACKER}. "
        "Read the plan first for context. Answer the owner's message concisely "
        "(a few sentences — this goes to Telegram). If they ask to change the "
        "service, make the edit, run `python3 test_price.py` if you touched "
        "price logic, and commit by filename with a clear message. Do not push; "
        "the caller handles that.\n\n"
        f"Owner: {query}"
    )
    r = subprocess.run(
        ["claude", "-p", prompt, "--model", "sonnet", "--permission-mode", "acceptEdits",
         "--allowedTools", ALLOWED_TOOLS, "--max-budget-usd", "1.00"],
        cwd=str(REPO), capture_output=True, text=True, timeout=900,
    )
    out = (r.stdout or "").strip()
    if r.returncode != 0 and not out:
        out = f"(agent error)\n{(r.stderr or '').strip()[:1500]}"
    return out


def head():
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(REPO),
                          capture_output=True, text=True).stdout.strip()


def main():
    tok, owner = telegram_conf()

    if not shutil.which("claude") or (os.environ.get("CI") and not os.environ.get("ANTHROPIC_API_KEY")):
        print("Claude Code unavailable (no binary or no ANTHROPIC_API_KEY in CI); bot disabled.")
        return

    updates = get_updates(tok)
    if not updates:
        print("No Telegram updates.")
        return
    last = max(u["update_id"] for u in updates)

    handled = 0
    for u in updates:
        m = u.get("message") or u.get("edited_message")
        if not m or str(m["chat"]["id"]) != str(owner):  # owner-only
            continue
        text = (m.get("text") or "").strip()
        if not text or text.startswith("/"):
            continue
        send(tok, owner, "On it — launching the agent…")
        before = head()
        try:
            reply = run_agent(text)
        except subprocess.TimeoutExpired:
            reply = "Agent timed out (15 min)."
        after = head()
        if after and after != before:
            push = subprocess.run(["git", "push"], cwd=str(REPO), capture_output=True, text=True)
            reply += f"\n\n[pushed {after[:7]}]" if push.returncode == 0 else f"\n\n[commit {after[:7]}; push failed: {push.stderr.strip()[:200]}]"
        send(tok, owner, reply)
        handled += 1

    get_updates(tok, offset=last + 1)  # confirm/clear so we don't reprocess
    print(f"Handled {handled} owner message(s).")


if __name__ == "__main__":
    main()
