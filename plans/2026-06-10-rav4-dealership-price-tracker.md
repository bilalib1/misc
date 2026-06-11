# RAV4 Dealership Price Tracker

**Forked from:** `../plan-template.md`

I already emailed one Toyota dealership asking for a RAV4 quote from my Gmail (`garbanzobilson@gmail.com`). I want to blast that same ask to ten LA + SF Bay Area dealerships, watch for replies, pull the quoted dollar price out of each, and — once at least five have answered — get a Telegram ping with the lowest price found. The hard part is not the regex; it is having something always-on that keeps checking the inbox after I close my laptop. This plan picks that host and lays out the build.

---

## 3. Preferences / Best Practices

(Inherited from template — autonomous, simple, surgical, TDD, succinct, commit often by filename.)

---

## 4. Context & Problem Statement

- **Who/why:** I am car shopping. Dealers compete on out-the-door price; emailing many at once and comparing is the cheapest way to find the floor.
- **Current state:** One quote request already sent from `garbanzobilson@gmail.com` (logged into Chrome in another tab). Body of that email is the template to reuse.
- **Desired "done":** 10 dealers emailed the same ask → a background job polls Gmail → extracts one price per reply → when ≥5 dealers have replied with a parseable price, send me a Telegram message with the single lowest price (and which dealer). Notify once, then stop.
- **Constraints:**
  - Must survive my laptop being closed → needs a *persistent* host, not a local script.
  - Must read + send as `garbanzobilson@gmail.com` → needs durable Gmail auth (offline OAuth refresh token), not a browser session.
  - Low volume, low urgency: polling every ~15 min is plenty.
  - Secrets never go in the repo. Local copies live in `~/secrets/rav4-tracker/` (chmod 700); the cloud poller reads them from GitHub Actions secrets.

### Prerequisites — what `setup.sh` will ask you for

Run **one** script: `~/code/misc/rav4-tracker/setup.sh`. It automates everything except three things only you can do. It prompts for each, in order:

1. **Google OAuth client file.** You make it once in the Google Cloud Console: create a project → enable Gmail API → OAuth consent screen set to *External* with `garbanzobilson@gmail.com` added as a **test user** (keeps it unverified-but-working) → create a *Desktop app* OAuth client → download the JSON. The script then opens a browser for you to approve a **scoped** grant (`gmail.modify` = read/send/label, nothing destructive) and stores the resulting offline refresh token at `~/secrets/rav4-tracker/token.json`. This token *is* the "authorized, limited, personal-scripting" credential — revocable anytime at myaccount.google.com → Security → Third-party access.
   - **Error 403 `access_denied` ("has not completed verification" / "developer-approved testers only")** = `garbanzobilson@gmail.com` is not on the **Test users** list. Fix: OAuth consent screen (newer UI: *Audience*) → status *Testing* → **Test users → + Add users** → add that exact address → save → retry. Also confirm you signed in with that same account and that the client JSON is from the *same project*.
   - **"Something went wrong, try again"** *after* clicking through the unverified-app warning = usually (a) multiple Google accounts in the browser — retry in Incognito signed in as only that account; or (b) a blank required field on the consent screen — fill **App name / User support email / Developer contact email** and save. Often also just transient; retry. Fallback if OAuth keeps failing: switch to a Gmail **App Password + SMTP/IMAP** (no consent screen; trade-off = full-mailbox access instead of scoped).
2. **Telegram bot token.** In Telegram, message `@BotFather` → `/newbot`. Paste the token; the script then asks you to message your new bot once and auto-captures your `chat_id`.
3. **The 10 dealer emails.** The script opens `dealers.json` (pre-filled with 10 real LA/Bay-Area Toyota dealership names) for you to paste each dealership's internet-sales email. It refuses to send while any are blank.

It also: builds a Python venv, runs the unit tests, pulls your already-sent RAV4 email as the template (you review it), sends a **test** copy to yourself, waits for you to type `SEND` before the real blast, then wires the GitHub Actions poller via `gh`.

---

## 5. Execution Steps

| #  | Task                                                                 | Status      |
| -- | ------------------------------------------------------------------- | ----------- |
| 1  | Decide persistent host                                               | completed — GitHub Actions cron, every 15 min |
| 2  | Gmail OAuth scripts (consent flow → token in ~/secrets)             | started — code done (`oauth_setup.py`); you run `setup.sh` to consent |
| 3  | Pull already-sent RAV4 body                                          | started — `prepare_message.py` done; runs during setup |
| 4  | 10 dealership emails (LA + SF Bay)                                   | started — names scaffolded in `dealers.json`; you fill emails in setup |
| 5  | Telegram bot token + chat_id capture                                 | started — `telegram_setup.py` done; you run during setup |
| 6  | `send.py` — blast body to dealers (test / dry-run / real)            | completed — written, imports clean |
| 7  | `poll.py` — replies → price → threshold → notify                    | completed — written, imports clean |
| 8  | Price heuristic + range filter                                       | completed — `price.py`, 7/7 unit tests pass |
| 9  | Scheduler wiring + secret plumbing                                   | completed — `rav4-poll.yml` + `setup.sh` (`gh secret set`) |
| 10 | Idempotent "already notified" guard                                  | completed — Gmail label `rav4-notified` |
| 11 | Dry-run + test-recipient gate before real blast                      | completed — `--test=` then typed `SEND` gate in `setup.sh` |

---

## 6. Out of Scope / Non-Goals

- **No negotiation/auto-reply.** We read and notify only; I handle the back-and-forth. Auto-replying risks committing me to a deal.
- **No browser automation of my Chrome session.** It cannot run on a remote host and breaks on logout; Gmail API is the durable path.
- **No web UI / dashboard.** A Telegram message is the whole product.
- **No multi-car / multi-make support.** One RAV4 run; not a reusable platform yet.
- **No structured-quote parsing (PDF attachments, dealer portals).** Plaintext-body regex only; attachment-only quotes are ignored (noted as a known gap).

---

## 7. Architecture

```
        ┌──────────────────┐
        │  send.py (once)  │
        └────────┬─────────┘
        Gmail API│ send same body
                 │ to 10 dealers
                 ▼
        ┌──────────────────┐
        │  Gmail mailbox   │◄──── dealers reply
        └────────┬─────────┘
                 │ read (poll)
                 ▼
     ┌───────────────────────────┐
     │  poll.py  (every ~15 min) │
     │  via scheduler (host TBD) │
     └───┬───────────────────┬───┘
 extract │                   │ once ≥5 priced replies
  price  ▼                   ▼
 ┌──────────────┐     ┌──────────────┐
 │ range filter │     │ Telegram Bot │──► my phone
 │ + min()      │     │  sendMessage │   "lowest: $X @ Dealer"
 └──────────────┘     └──────┬───────┘
                             │ then label thread
                             ▼
                    ┌──────────────────┐
                    │ Gmail label =    │
                    │ "rav4-notified"  │ (idempotency)
                    └──────────────────┘
```

- **Auth:** one OAuth refresh token (scope: `gmail.send` + `gmail.readonly` or `gmail.modify` for labeling), stored as a host secret.
- **State:** Gmail itself is the source of truth. Each poll recomputes reply count from the thread(s); a `rav4-notified` label is the single persisted flag so we alert exactly once.

---

## 9. Implementation Details

**send.py — blast the quote request**

1. Auth to Gmail API with stored refresh token.
2. Search `Sent` for the original RAV4 message (`from:me subject:RAV4` or known message id); pull its plaintext body + subject.
3. For each of the 10 dealer emails, send a fresh message (one recipient each, no CC — dealers must not see each other) with that body.
4. Record the 10 sent message ids / recipient addresses (write `dealers.json`: name, email, region, sent_msg_id).

**poll.py — find replies, extract prices, notify**

1. Auth; if any thread already carries label `rav4-notified`, exit (already done).
2. For each dealer in `dealers.json`, search inbox for a reply from that address (`from:<dealer> newer_than:14d`).
3. For each reply, get the plaintext body (walk MIME parts; skip if HTML-only after strip, log it).
4. Regex all dollar amounts: `\$\s?\d{1,3}(?:,\d{3})*(?:\.\d{2})?` → list of floats.
5. **Range filter:** keep only `15000 ≤ x ≤ 80000` (drops deposits, fees, monthly payments, doc fees).
6. **Pick the dealer's price:** if a kept amount sits within ~40 chars of a keyword (`out the door|OTD|total|selling price|your price|sale price`), use that; else use the max kept amount. Store one price per dealer.
7. Count dealers with ≥1 priced reply. If `< 5`, exit (wait for next poll).
8. If `≥ 5`: `min()` over priced dealers → format `"Lowest RAV4: $34,210 — Toyota of <X>. (5 of 10 replied)"`.
9. POST to Telegram `sendMessage` (bot token + my chat_id).
10. On success, apply Gmail label `rav4-notified` to one reply thread so future polls short-circuit.

**Telegram notify**

1. `POST https://api.telegram.org/bot<TOKEN>/sendMessage` with `{chat_id, text}`. One HTTP call, no SDK.

---

## 11. Open Questions / Decisions Needed

Q1–Q6 are now **decided** (kept for the record). The only thing still on you is the dealer emails, handled inside `setup.sh`.

**Still on you:**

- **Dealer emails.** `dealers.json` has 10 real dealership *names*; you paste each internet-sales email when `setup.sh` opens the file. (Couldn't source these reliably myself — wrong addresses would waste the whole blast.)

**Decided:**

- **Q1 host → GitHub Actions cron** (free, persistent, uses the existing `bilalib1/misc` repo; state lives in the Gmail `rav4-notified` label, so no DB). Local secrets in `~/secrets/rav4-tracker/`.
- **Q2 price → keyword-anchored, after-the-label, range-filtered** (§9). Picks the figure following "out the door / total"; falls back to largest in $15k–$80k. 7/7 unit tests.
- **Q3 dealers →** names scaffolded; you confirm emails (above).
- **Q4 "five respond" →** five replies *with a parseable price* (`MIN_REPLIES = 5` in `poll.py`).
- **Q5 OAuth →** scoped `gmail.modify` token via a test-user GCP project; token stored in `~/secrets`, not the repo. *(Considered a Gmail App Password + SMTP/IMAP to skip the GCP project — rejected: an app password grants full mailbox access, the opposite of "limited". Scoped OAuth is the right "authorized limited personal scripting" credential.)*
- **Q6 cadence →** all 10, 2-second spacing (`send.py`).

---

## 12. Test Plan / Acceptance Criteria

### A. E2E / Human Test Plan

1. **Auth smoke:** run `poll.py` with 0 dealers → exits clean, prints "0 priced replies".
2. **Dry blast:** set `dealers.json` to a single test address I control; run `send.py`; confirm the email lands with the right body.
3. **Price parse:** reply to that test email with a body containing `MSRP $41,000, your out-the-door price is $36,750, $500 deposit`; run `poll.py` → it should pick **$36,750** (keyword + range filter beats $41,000 and $500).
4. **Threshold + notify:** seed 5 priced test replies; run `poll.py` → Telegram message arrives with the min; thread gets `rav4-notified`; a second run sends nothing.

### B. Acceptance Criteria

- Same body delivered to 10 distinct dealers, no shared CC.
- Poller runs on a host that works with my laptop closed.
- Exactly one Telegram message, fired only at ≥5 priced replies, showing the correct minimum + dealer.
- No duplicate notifications across repeated polls.

### C. Automated Tests

- Unit: price regex + range filter + keyword picker — multi-amount body, monthly-payment trap (`$499/mo`), comma/decimal formats, HTML-only body.
- Unit: threshold logic — 4 vs 5 priced dealers; replies with no parseable price don't count.
- Integration: Gmail fetch against a real test thread — reply detection by sender.

---

## 13. References / Links

- Gmail API — send: `users.messages.send`; read: `users.messages.list/get`; labels: `users.labels`, `users.messages.modify`.
- Telegram Bot API — `sendMessage`, BotFather for token, `getUpdates` to find my chat_id.
- GitHub Actions — `on.schedule` cron syntax; repo Secrets for tokens.

---

## 14. File List

All code under `~/code/misc/rav4-tracker/` unless noted.

- `../plans/2026-06-10-rav4-dealership-price-tracker.md` — this plan.
- `setup.sh` — the one script you run; orchestrates all of the below.
- `paths.py` — secret locations (`~/secrets/rav4-tracker/`, env-overridable).
- `config.py` — loads Gmail + Telegram creds (local files or Actions env).
- `oauth_setup.py` — one-time browser consent → `token.json`.
- `telegram_setup.py` — capture bot token + chat_id → `telegram.json`.
- `prepare_message.py` — pull your sent RAV4 email → `message.json`.
- `price.py` — pick one price per reply (the testable core).
- `test_price.py` — 7 unit cases; run with `python test_price.py`.
- `send.py` — blast (`--test=`, `--dry-run`, real).
- `poll.py` — replies → price → ≥5 → Telegram → label.
- `dealers.json` — 10 dealership names; you fill emails. *(committed)*
- `requirements.txt`, `.gitignore`.
- `~/code/misc/.github/workflows/rav4-poll.yml` — cron poller (every 15 min).
- `~/secrets/rav4-tracker/` — token.json, client_secret.json, telegram.json, message.json. *(never committed)*

---

## 17. Postmortems

Not applicable yet.

---

## 18. Project History

- **2026-06-10** — Plan drafted. Core open question is the persistent host (recommending GitHub Actions cron). No code yet.
- **2026-06-10** — Built the whole system: `rav4-tracker/` scripts + price logic (7/7 tests) + GitHub Actions poller + one `setup.sh` that prompts for the 3 manual pieces (GCP OAuth client, Telegram bot, dealer emails). Secrets relocated to `~/secrets/rav4-tracker/` (none in repo) per request. All modules import clean in a venv. Not yet run end-to-end — waiting on you to run `setup.sh` and supply consent + bot token + emails.
