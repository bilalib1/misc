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

---

## 5. Execution Steps

| #  | Task                                                                 | Status      |
| -- | ------------------------------------------------------------------- | ----------- |
| 1  | Decide persistent host (see §11 Q1)                                  | not started |
| 2  | Gmail API OAuth: GCP project, consent, offline refresh token        | not started |
| 3  | Pull the already-sent RAV4 email body from Sent folder              | not started |
| 4  | Gather 10 dealership emails (LA + SF Bay) — see §11 Q3              | not started |
| 5  | Create Telegram bot (BotFather), capture token + my chat_id         | not started |
| 6  | `send.py` — send the reused body to all 10 dealers via Gmail API    | not started |
| 7  | `poll.py` — fetch replies, extract prices, check threshold, notify  | not started |
| 8  | Price-extraction heuristic + range filter (see §9, §11 Q2)          | not started |
| 9  | Wire poller to chosen scheduler; store secrets                      | not started |
| 10 | Idempotent "already notified" guard (Gmail label)                   | not started |
| 11 | Dry-run end-to-end with a test recipient before real blast          | not started |

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

- **Q1 — Persistent host (the core question).** Three options:
  - **(A) GitHub Actions scheduled workflow [recommended].** Free, truly persistent (runs in the cloud regardless of my laptop), I already have `github.com/bilalib1/misc`. Tokens go in repo Secrets. Cron granularity ~5–15 min (delays possible but fine here). State stays in Gmail (the `rav4-notified` label), so no commit-back needed. Lowest setup, zero cost.
  - **(B) Cheap always-on box** — Fly.io free tier / $5 droplet / Raspberry Pi with `cron`. Most reliable timing, full control, local SQLite if wanted. Costs a little setup/$, but no GitHub-runner quirks.
  - **(C) Local macOS `launchd`.** Simplest to write, but **not persistent** — dies when the laptop sleeps. Fails the main requirement; listed only to reject.
  - **Recommendation: A.** Pick B only if cron timing reliability turns out to matter. Need your nod.
- **Q2 — Which price counts when a reply has several dollar figures?** Plan uses keyword-near-amount, else max-in-range (§9.6). Is "out the door / total" the number you care about, or base selling price? This changes the heuristic.
- **Q3 — Where do the 10 dealer emails come from?** Do you hand me the list, or should I research LA + SF Bay Toyota dealers' internet-sales emails myself? Wrong/generic addresses (e.g. `info@`) lower reply rates.
- **Q4 — Does "five respond" mean five *replies*, or five replies *with a parseable price*?** Plan assumes the latter (we need prices to compute a min). Confirm.
- **Q5 — OAuth consent friction.** Gmail send/read scopes are "restricted"; an unverified personal app still works for my own account via the test-user path. OK to set up a throwaway GCP project for this?
- **Q6 — Send cadence.** Fire all 10 at once, or stagger? All-at-once is simpler; staggering looks less bulk-y to dealer spam filters.

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

- `~/code/misc/plans/2026-06-10-rav4-dealership-price-tracker.md` — this plan.
- `send.py` — *(to create)* one-shot blast to 10 dealers.
- `poll.py` — *(to create)* scheduled reply-poller + notifier.
- `dealers.json` — *(to create)* the 10 dealers: name, email, region, sent_msg_id.
- `.github/workflows/rav4-poll.yml` — *(to create, if host = A)* cron that runs `poll.py`.

---

## 17. Postmortems

Not applicable yet.

---

## 18. Project History

- **2026-06-10** — Plan drafted. Core open question is the persistent host (recommending GitHub Actions cron). No code yet.
