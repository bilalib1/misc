# Browser Interaction via CDP

**Problem:** Driving my real, logged-in Chrome by screenshots + AppleScript/cliclick is slow and
fragile — it steals window focus, fights macOS Spaces, and chokes on native file dialogs and
canvas apps (Google Sheets). **Change:** talk to Chrome over the DevTools Protocol (CDP) instead —
a lightweight, text-first, headless-feeling hook layer that operates a single tab in the background
without me losing control of the browser. Python helpers in `src/browser_interaction/` wrap the raw
hooks into self-explanatory tool calls.

---

## Setup (one-time per session)

`src/browser_interaction/launch_chrome_with_cdp.sh [port]` — quits Chrome, copies just the login
state (cookies + `Local State`) into a separate `Chrome-CDP` profile, relaunches with
`--remote-debugging-port`. **Why the copy:** Chrome 136+ ignores the debug port on the *default*
profile (anti-cookie-theft). Same Keychain key decrypts the copied cookies, so all Google logins
persist; the real profile is never opened with the port and stays untouched.

Verify: `curl -s localhost:9222/json/version`.

## Toolkit (`src/browser_interaction/`)

| File | Key functions | Does |
|---|---|---|
| `chrome_cdp_session.py` | `ChromeCDPSession.for_url`, `.call`, `.wait_for_event`, `find_target_by_url` | Core websocket session to one tab. Everything builds on this. |
| `list_open_tabs.py` | `list_open_tabs` | Tabs as compact title+url text. |
| `navigate_tab.py` | `open_url_in_new_tab`, `navigate_existing_tab` | Open/point a tab, wait for load. |
| `run_javascript_in_tab.py` | `run_javascript_in_tab` | Eval JS (awaits promises), return value as text. Workhorse. |
| `get_page_text.py` | `get_page_text`, `get_element_text` | Read page/element as plain text (screenshot replacement). |
| `click_in_tab.py` | `click_element_by_text`, `click_element_by_css` | Real trusted mouse clicks at element center (Google apps ignore `.click()`). |
| `type_in_tab.py` | `type_text_into_focused`, `set_value_by_css` | Real key events (for canvas grids) or direct DOM value set. |
| `upload_files_via_file_chooser.py` | `upload_files_via_file_chooser` | Upload with **no native dialog**: intercept file chooser, `DOM.setFileInputFiles`. |

## Lessons baked in

- Google menus/buttons need **real** `Input.dispatchMouseEvent`, not `element.click()`.
- File uploads: `Page.setInterceptFileChooserDialog` + `DOM.setFileInputFiles` → no OS dialog, no focus.
- Menu items append shortcut hints ("File upload⌃ then U") → match by prefix, not equality.
- Send `Escape` before opening a menu so the first click doesn't toggle an already-open one.
- Read backgrounded tabs with `textContent` (innerText is empty when a tab isn't painted) — moot under CDP, but relevant for the AppleScript fallback.

## Proven on

Shinkei reimbursement: read Gmail receipts across 3 accounts, filled the Google Sheet, uploaded
Alaska + Uber receipt PDFs to the Drive folder — upload done entirely headless via CDP.

## Next / ideas

- `read_accessibility_tree.py` — `Accessibility.getFullAXTree` as an even leaner text view than innerText.
- `download_gmail_message_pdf.py` — generalize the grab-body-HTML → headless-Chrome print-to-PDF receipt flow (note: headless Chrome from the same app bundle hijacks AppleScript — irrelevant under CDP).
- A thin CLI dispatcher so these are one `python3 -m browser_interaction <verb>` call.
- Persist the CDP profile path (currently `~/Library/.../Chrome-CDP`) and document teardown.
