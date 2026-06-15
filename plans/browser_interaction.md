# Browser Interaction via CDP

**Problem:** Driving my real, logged-in Chrome by screenshots + AppleScript/cliclick is slow and
fragile — it steals window focus, fights macOS Spaces, and chokes on native file dialogs and
canvas apps (Google Sheets). **Change:** talk to Chrome over the DevTools Protocol (CDP) instead —
a lightweight, text-first, **invisible** hook layer that operates tabs in the background without me
losing control of the browser. Python helpers in `src/browser_interaction/` wrap the raw hooks into
self-explanatory tool calls, each runnable as one `python3 -m browser_interaction <verb>` call.

---

## Headless strategy (why Chrome never pops up)

**One hard rule: perfectly invisible.** No window may ever appear and the desktop/focus must never
be disturbed. On macOS the *only* mode that satisfies this is **`--headless=new`**, which creates no
platform window at all. **Headed Chrome is permanently off the table** — see below.

The key 2026 insight: the decisive anti-bot detection layer is **automation-PROTOCOL fingerprinting**
(WebDriver presence / the CDP `Runtime.enable` command), **NOT** headed-vs-headless. So a
bare-CDP, no-WebDriver, no-Playwright driver passes that layer while staying fully headless.
Headedness buys almost nothing and costs invisibility.

| Mode | Flag | Window? | Use for |
|---|---|---|---|
| **headless** (the only mode) | `--headless=new` + UA override | **None, ever** | Everything — ordinary sites *and* hardened anti-bot sites |

`--headless=new` shares the headed codebase and renders a real GPU fingerprint, but Chrome 149
still leaks `"HeadlessChrome"` in `navigator.userAgent` — so `launch_chrome_with_cdp.sh` passes a
matching `--user-agent` override to erase that one tell.

### Hardened anti-bot sites, fully headless (CarMax / Carvana)

The old belief that Akamai/Cloudflare sites "require a headed browser" is **wrong and now disproven
(2026-06-14)**. CarMax (Akamai) and Carvana (Cloudflare) are both scraped **fully headless** by
**[`zendriver`](https://github.com/cdpdriver/zendriver)** — a raw-CDP, nodriver-style library that
drives Chrome over a bare WebSocket CDP connection with no WebDriver and no Playwright shim.
- It passes because it never trips automation-protocol fingerprinting (it doesn't call
  `Runtime.enable`; Playwright does). In the 2026 anti-detect benchmark nodriver scored best
  (28/31 vs Cloudflare).
- Cloudflare interstitials ("Just a moment…") are handled headless: `tab.verify_cf()` solves the
  interactive Turnstile checkbox, plus a wait/reload loop clears the auto-clearing JS challenge.
- See `rav4-tracker/browser_scraper.py` (`zendriver.start(headless=True)`, `_clear_cloudflare`).

### Banned: headed Chrome (do not reintroduce)

A real headed Chrome — even launched "hidden + backgrounded" via `open -g -j` / `CDP_MODE=headed` /
`launch_chrome_with_cdp.sh --headed`, or hidden after launch with the `_hide_chromium()` AppleScript
`Cmd+H` trick — **is NOT invisible on macOS**. It surfaces and steals focus/Space. It disrupted the
desktop on **2026-06-11 and again 2026-06-14**, and is permanently retired. (Note: the
`launch_chrome_with_cdp.sh` script still carries a `--headed` branch; **do not use it.**)

**Other things that DON'T work on macOS** (tested, rejected): `--window-position=-32000,-32000` is
clamped back on-screen (window reappears at 0,0); `open -g -j` does not reliably hide a headed window.

**The #1 stealth win is free here:** Cloudflare/Akamai/DataDome detect automation mainly via the
`Runtime.enable` CDP command (the reason `patchright` and `rebrowser-patches` exist — see Research).
Our helpers only ever call `Runtime.evaluate`, which needs no `Runtime.enable`, so they never trip
that signal. **Playwright/Puppeteer do call it** — so for hardened sites use the bare-CDP reader
(`read_ld_json.py`) or `zendriver`, never Playwright + `playwright-stealth`.

---

## Setup (one-time per session)

`src/browser_interaction/launch_chrome_with_cdp.sh [port] [--refresh]`
— launches the CDP Chrome **invisibly** with `--headless=new`. (The script still has a `--headed` /
`CDP_MODE=headed` branch, but it is **banned** — headed Chrome is not invisible on macOS; see
"Headless strategy" above.)

It copies just the login state (cookies + `Local State`) into a separate `Chrome-CDP` profile and
relaunches with `--remote-debugging-port`. **Why the copy:** Chrome 136+ ignores the debug port on
the *default* profile (anti-cookie-theft). Same Keychain key decrypts the copied cookies, so all
Google logins persist; the real profile is never opened with the port and stays untouched.

**Now non-disruptive:** the copied profile is *reused* across launches. We only quit your main
Chrome + re-copy login state when the profile is missing or you pass `--refresh`. Day-to-day
launches touch nothing of yours and show nothing.

Verify: `curl -s localhost:9222/json/version`.

## Toolkit (`src/browser_interaction/`)

Run any verb as `cd src/browser_interaction && python3 -m browser_interaction <verb> …`
(dispatcher: `__main__.py`).

| File | Verb / Key functions | Does |
|---|---|---|
| `chrome_cdp_session.py` | `ChromeCDPSession.for_url`, `.for_new_tab`, `.call`, `.wait_for_event` | Core websocket session to one tab. Everything builds on this. |
| `list_open_tabs.py` | `tabs` | Tabs as compact title+url text. |
| `navigate_tab.py` | `open`, `goto` | Open/point a tab, wait for load. |
| `run_javascript_in_tab.py` | `eval` | Eval JS (awaits promises), return value as text. Workhorse. |
| `get_page_text.py` | `text` | Read page/element as plain text (screenshot replacement). |
| `click_in_tab.py` | `click`, `clickcss` | Real trusted mouse clicks at element center (Google apps ignore `.click()`). |
| `type_in_tab.py` | `type` | Real key events (for canvas grids) or direct DOM value set. |
| `upload_files_via_drag_drop.py` | `upload` | **Headless-safe upload (use this).** Inject files into a synthetic drag via `Input.dispatchDragEvent` — no menu, no dialog, no visible window. Drop all files in one call to avoid Drive's "keep both" conflict. |
| `upload_files_via_file_chooser.py` | `upload_files_via_file_chooser` | Upload via intercepted file chooser (`DOM.setFileInputFiles`). **Needs a composited/visible window** — Google's *New* menu won't open headless/hidden, so prefer `upload` above. |
| `write_google_sheet_cell.py` | `setcell` | Write one Sheets cell over CDP: anchor on the Name Box (`#t-name-box`), then real key events. Canvas-safe, headless. |
| `read_ld_json.py` | `ldjson`, `cars` | Headless listing scraper: open a bg tab, hydrate + scroll, return `<script type=ld+json>` records. Playwright-free → no `Runtime.enable` tell. |

## Lessons baked in

- Google menus/buttons need **real** `Input.dispatchMouseEvent`, not `element.click()`.
- File uploads: `Page.setInterceptFileChooserDialog` + `DOM.setFileInputFiles` → no OS dialog, no focus.
- Menu items append shortcut hints ("File upload⌃ then U") → match by prefix, not equality.
- Send `Escape` before opening a menu so the first click doesn't toggle an already-open one.
- **Headless Chrome can't open Google's overflow menus** (the *New* menu in Drive): `--headless=new`
  only exposes a detached hidden menu template (items at y≈1837, unclickable). So menu-driven flows
  (file-chooser upload) don't work headless. For uploads, **drag-drop instead**
  (`upload_files_via_drag_drop`) — fully headless. (Headed would composite the menu, but headed is
  banned; drag-drop sidesteps the need entirely.)
- `ChromeCDPSession.call()` buffers any CDP *events* it sees while awaiting a command result, so a
  fast event (e.g. `Page.fileChooserOpened`) fired mid-call isn't dropped before `wait_for_event`.
- Read backgrounded tabs with `textContent` (innerText is empty when a tab isn't painted) — moot under CDP, but relevant for the AppleScript fallback.
- **Never call `Runtime.enable`** — it's the main automation tell on anti-bot sites. Bare `Runtime.evaluate` is enough and is invisible to that check.

## Proven on

- **Shinkei reimbursement:** read Gmail receipts across 3 accounts, filled the Google Sheet
  (`setcell`), and uploaded the receipt PDFs to the Drive folder. Final upload (Lyft) done **fully
  headless** via drag-drop after confirming the file-chooser menu can't open invisibly.
- **Car buying (rav4-tracker):** Cars.com / dealer-site listing reads; **CarMax (Akamai) + Carvana
  (Cloudflare) LD+JSON scraped FULLY HEADLESS** via `zendriver` — `rav4-tracker/browser_scraper.py`
  (`scrape_carmax`, `scrape_carvana`). Proven live 2026-06-14; no window ever appears.

## Research — current best-in-class (2026-06-11)

Where this hand-rolled layer sits vs. the ecosystem:

- **Our bare-CDP layer ≈ a minimal `nodriver`.** [`nodriver`](https://github.com/ultrafunkamsterdam/nodriver)
  (async, no WebDriver, drives Chrome directly) and its **actively-maintained fork
  [`zendriver`](https://github.com/cdpdriver/zendriver)** are the same architecture — direct CDP,
  no `Runtime.enable`. In 2026 anti-detect benchmarks nodriver scored best (28/31 vs Cloudflare).
  **`zendriver` is already adopted** for the hardened car sites (`browser_scraper.py`, headless) —
  the right answer over Playwright, which trips `Runtime.enable`.
- **Stealth-patched Playwright (avoid):** [`patchright`](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright)
  and [`rebrowser-patches`](https://github.com/rebrowser/rebrowser-patches) exist *specifically* to
  remove the `Runtime.enable` leak from Playwright/Puppeteer. Prefer `zendriver` over going back to
  Playwright at all; reach for `patchright` only if some flow is unavoidably Playwright-bound.
- **Anti-detect via Firefox:** [`camoufox`](https://github.com/daijro/camoufox) rewrites Firefox
  internals for a consistent fingerprint — a fallback if Chromium-based stealth starts failing on a
  specific site.
- **Agentic browsers (LLM-driven), for reference:** [`browser-use`](https://github.com/browser-use/browser-use)
  (~97k★, the category leader), [`stagehand`](https://github.com/browserbase/stagehand) (NL actions
  on Playwright), [`skyvern`](https://github.com/Skyvern-AI/skyvern) (vision-first). These wrap a
  browser for an LLM to click around; **not** what we want here — I *am* the agent and drive these
  helpers directly, which is faster and cheaper than a self-navigating loop for known flows.

**Takeaway:** keep the bespoke CDP layer for the logged-in Google flows (it already avoids the top
detection vector). For hardened anti-bot sites, `zendriver` headless is the proven answer (CarMax +
Carvana). Never reach for a headed browser — it is not invisible on macOS and is banned.

## Next / ideas

- ~~Thin CLI dispatcher (`python3 -m browser_interaction <verb>`).~~ **Done** (`__main__.py`).
- ~~Headless listing reader without Playwright.~~ **Done** (`read_ld_json.py`).
- `read_accessibility_tree.py` — `Accessibility.getFullAXTree` as an even leaner text view than innerText.
- `download_gmail_message_pdf.py` — generalize the grab-body-HTML → print-to-PDF receipt flow.
- ~~Port `browser_scraper.py` off Playwright onto `zendriver`.~~ **Done** — CarMax + Carvana now
  scrape fully headless via `zendriver` (2026-06-14).
- Teardown helper for the `Chrome-CDP` profile (currently `~/Library/.../Chrome-CDP`).
