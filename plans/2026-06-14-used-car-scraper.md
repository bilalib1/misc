# Used-Car Finder — multi-site scraper → Telegram shortlist

**Forked from:** `../plan-template.md`

One end-to-end Python script (`rav4-tracker/scrape.py`) that, when run, scrapes used-car listings from
**Cars.com + Carvana** (CarMax too, but it yields ~nothing headless), keeps only cars matching the
buyer's spec (silver/light-gray leather hybrid/PHEV SUV, 2021+, <50k mi, $20–40k, clean title), ranks
them by value × reliability with brand diversity, and **sends a Telegram message** with the shortlist in
four buckets. Run `python scrape.py` → get a text of the current qualifying market. Everything runs
**fully headless / invisibly** — no browser window ever appears.

---

## 1. How To Use This Template

**Repo layout:** `~/code` holds all repos, one per directory (this lives in `~/code/misc`). Plans
reference paths relative to their own repo root. Fork into `plans/YYYY-MM-DD-<slug>.md`. **500 lines max.**

---

## 2. Maintain This Plan

- **Living document.** Update the moment anything changes; this file should let us resume cold.
- Keep: current decisions + *why*, paths, commands, thresholds. Drop: diary text, "we changed X to Y"
  (that lives only in §18 History).
- One status table (§5). Project History (§18) is append-only. Keep the File List (§14) current.

---

## 3. Preferences / Best Practices

- **Be autonomous.** For this pipeline the buyer is explicit: iterate the script, audit
  `/tmp/scrape_log.json`, and once the list is diverse + legitimately good, **send the Telegram message
  yourself** — do NOT ask permission or ask "should I send?".
- **Invisibility is a HARD rule (§6).** Nothing may render on the buyer's Mac.
- Simplicity + surgical changes; read/verify with data before acting; delegate long runs to background.

---

## 4. Context & Problem Statement

- **Who/why:** Buyer is shopping for a RAV4-Hybrid-class used car and wants to watch the whole market
  across the big listing sites without checking each one by hand.
- **Done:** `python scrape.py` → a Telegram message arrives with the ranked shortlist in 4 buckets
  (strict/relaxed interior × two price bands). See §8 for the exact filters, §10 for the message format.
- **Constraints:**
  - **Perfect invisibility (hard):** no browser window may ever appear. A *headed* browser on macOS
    surfaces and steals focus even when "hidden" — permanently banned (§17 postmortem).
  - Cars.com Cloudflare blocks Playwright's own Chromium and a fresh-profile Chrome; only a **real
    Chrome** (user's cookies) over CDP passes — auto-launched headless on `:9334`.
  - Carvana (Cloudflare) + CarMax (Akamai) need raw-CDP headless (`zendriver`), not Playwright.
  - Cars.com keeps **sold** cars live → its detail pass drops sold-marked listings.
  - Local Python script in `scraper_venv` (Python 3.13). Secrets in `~/secrets/rav4-tracker/` (not in repo).

---

## 5. Execution Steps

| # | Capability | Status |
| - | ---------- | ------ |
| 1 | Filter-first Cars.com scrape (real-Chrome `:9334` CDP engine, auto-launched) | done |
| 2 | Filter-first Carvana scrape (cvnaid, `zendriver` headless) | done |
| 3 | CarMax scrape (`zendriver` headless) | done — but only a static carousel; ~useless |
| 4 | All filters (§8) — color/interior/leather/body/fuel/year/price/miles/location/salvage/blacklist | done |
| 5 | Scoring = value × reliability (brand × NHTSA complaints) × trim (§9) | done |
| 6 | 4-bucket selection, ≤1 per model per bucket (§9) | done |
| 7 | Telegram send (§10), fully headless | done |
| 8 | Autonomous run → audit → send | recurring — run on demand |

---

## 6. Out of Scope / Non-Goals

- **No headed / visible browser** — invisibility is a hard constraint; everything is `--headless=new`.
- **No auto-negotiation / auto-replies** — we scrape and notify; the buyer handles dealers.
- **No web UI / dashboard** — the Telegram message is the whole product.
- **CarMax is effectively dark** — headless only returns a static recommendation carousel (the real
  filtered grid is Akamai-API-gated), so it contributes ~nothing. Kept but not relied on.
- **The dealership email-quote tracker is a separate sibling system** (`send.py`/`poll.py`/`bot.py` +
  a GitHub Actions cron). Shares the repo + Telegram channel but is NOT part of this scraper.

---

## 7. Architecture

```
                  ┌────────────────────┐
                  │  scrape.py (run)   │  python scrape.py
                  └─────────┬──────────┘
        Cars.com FIRST,     │ then browser sources (sequential — avoids
        alone               │ starving Cars.com's CDP engine)
        ▼                                   ▼
  ┌───────────────┐                 ┌──────────────────────────┐
  │  Cars.com     │                 │  Carvana   +   CarMax     │
  │ real-Chrome   │                 │  zendriver headless       │
  │ CDP :9334     │                 │  (raw CDP, --headless=new)│
  └──────┬────────┘                 └────────────┬─────────────┘
   filter-first URL                  filter-first cvnaid URLs
   body=SUV+fuel+color               (4: interior × leather)
   +clean_title; card                LD+JSON @type=Car
   data-vehicle-details              (Carvana: verify_cf if blocked)
         └──────────────┬────────────────────────┘
                        ▼  normalize → common listing dict
              ┌────────────────────────┐
              │ local filters (§8):    │ is_silver, year/price/miles,
              │ blacklist, leather,    │ interior tag, make blacklist
              │ sold-check (Cars.com)  │
              └───────────┬────────────┘
                          ▼
              ┌────────────────────────┐
              │ reliability (per car):  │ brand × NHTSA complaints
              │ live NHTSA, cached      │ (precomputed once)
              └───────────┬────────────┘
                          ▼
              ┌────────────────────────┐
              │ 4 buckets, top 5 each,  │ {strict, relaxed} ×
              │ ≤1 per model            │ {$20-30k, $30-40k}
              └───────────┬────────────┘
                          ▼
              ┌────────────────────────┐   plus /tmp/scrape_log.json
              │  Telegram sendMessage  │──► buyer's phone
              └────────────────────────┘
```

---

## 8. Filters (all of them)

Where each filter is applied — **S** = server-side (in the query, car never comes back) /
**L** = local (in `scrape.py`/`car_search.py` after fetch). *No persistent DB; state is ephemeral (§ 8a).*

| Filter | Rule | Cars.com | Carvana | CarMax |
| ------ | ---- | -------- | ------- | ------ |
| **Body** | SUV / crossover | S `body_style_slugs=suv` | S `bodyStyles=[suv]` | S body param |
| **Fuel** | Hybrid + Plug-In Hybrid | S `fuel_slugs[]` | S `fuelTypes` (note capital "I" in `Plug-In`) | S |
| **Exterior color** | silver / LIGHT gray only | S `exterior_color_slugs[]=silver,gray` + L `is_silver` | S `colors=[Silver,Gray]` + L `is_silver` | L `is_silver` |
| **`is_silver` (L)** | pass a `SILVER_ROOTS` word (silver, gray, chrome, platinum, stardust, sterling, ingot); VETO `DARK_COLOR_MARKERS` (graphite, magnetic, gunmetal, machine gray, carbonized, coastal…) and `_BLOCKED_COLORS` (black/blue/red/gold…). "titanium" is NOT in the allowlist (gold Venza). | — | — | — |
| **Interior** | strict = non-black; relaxed = black (two message sections) | L (read off detail page; unknown ⇒ treated non-black) | S two queries: `interiorColors` non-black vs `["Black"]` → tagged | L `vehicleInteriorColor` |
| **Leather** | leather OR leather-like (SofTex/NuLuxe) | L leather-by-**trim** (`LEATHER_TRIMS`; e.g. RAV4 XLE Premium/XSE/Limited; SE=cloth) | S `cvnaFeatures=["Genuine Leather Seats"]` and `["Synthetic Leather Seats"]` (AND-combined → 2 queries, unioned) | L `confirms_leather(vehicleInteriorType)` |
| **Year** | ≥ `YEAR_MIN` (2021) | S `year_min` | **L** (Carvana `/cars/filters` ignores the URL year) | L |
| **Price** | $20k–$40k | S | S in URL + **L** re-check (filters URL is authoritative on cvnaid only) | L |
| **Mileage** | < 50k | S | S + L | L |
| **Location** | greater LA (zip 90012, 75 mi) | S `zip`+`maximum_distance` | nationwide (Carvana delivers) | nationwide |
| **Salvage / branded title** | clean title only | S `clean_title=true` | clean by policy (none exist) | clean by policy |
| **Make blacklist** | exclude Jeep, Kia | L `is_blocked_make` | L | L |
| **Availability** | drop sold | L detail page `SOLD_MARKERS` | live query result | live query result |

### 8a. State (no DB)
- **`/tmp/scrape_log.json`** (rewritten each run) — `counts`, `make_distribution`, `selected_strict`,
  `selected_relaxed`, `all_verified` (slim entries incl. image URL). For audit/spot-checking; not read back.
- **`/tmp/shortlist.json`** (only with `--out`) — the selection as a JSON array.

---

## 9. Implementation Details

**Pipeline — `scrape.py run()`**

1. Ensure the invisible `:9334` real-Chrome engine is up (auto-launch via `launch_chrome_with_cdp.sh`).
2. **Cars.com first, alone:** fetch `car_search.search_urls()` (one filter-first URL per color) over CDP,
   4 worker pages; build each card's title from its `data-vehicle-details` JSON (visible text lazy-loads);
   paginate until no new cards; apply the §8 local filters + a detail pass (interior color + sold-check).
3. **Then browser sources** (`_ingest_browser_sources`, in a thread): `scrape_carvana` (4 cvnaid queries)
   + `scrape_carmax`; apply §8 local filters. Server-leather Carvana cars carry `leather_ok` → skip the
   local leather gate. Each source isolated (a crash → [] , never aborts the send).
4. Merge + VIN-dedupe → `verified`.
5. **Precompute reliability** per car (cached by make/model/year), then select (§ below) and send (§10).

**Scoring — `_score(listing)`** = `base × reliability_mult × trim_mult`, higher = better.
- `base = year_pts + mile_pts + price_pts` — `year_pts=(year-2019)*100` (dominant), `mile_pts` and
  `price_pts` are small tiebreakers.
- `trim_mult` = `trim_score_multiplier` (0.95–1.10 by trim rank; known models only).

**Reliability — `car_search.reliability_multiplier(make, model, year)`** = `brand × complaint_factor`:
- **Brand** (`MANUFACTURER_MULTIPLIER`, best=1.0): Toyota/Lexus/Honda 1.0, Acura 0.98, Mazda 0.92,
  Subaru 0.90, Hyundai/Kia/Ford/Nissan/GM ~0.84–0.88, BMW/Volvo/Porsche/VW 0.80, Audi/Mercedes 0.78,
  Dodge/Chrysler 0.74, **Jeep 0.70**, Land Rover/Alfa 0.68; default 0.82. Covers every make.
- **Complaint factor** (live NHTSA `complaintsByVehicle`, cached): complaints ÷ (US sales × years-on-
  market) → complaints per 10k vehicle-years vs a ~2.0 baseline; **damped by data confidence**
  `w = exposure/300k` (new/low-volume = little data); plus a **first-gen penalty** `(1-w)*0.04` so a
  0-complaint new model can't out-score a proven one. Range ~0.90–1.03; falls back to 1.0 if no data.
  *Result: RAV4 2022 ≈ 1.02 > CX-90 2024 ≈ 0.92 — Toyota edges a same-year Mazda even at 0 complaints.*
- US annual sales for the denominator are a rough curated table (`MODEL_ANNUAL_SALES`) + default.

**Selection — `_select_incremental(top_n=5, max_per_model=1)`**, run per bucket: greedy by effective
score with a soft brand/model diversity penalty AND a **hard cap of 1 per model per bucket**
(title-based `_model_id`, so even unrecognized makes are de-duped).

---

## 10. Telegram Message Format

Four buckets — **{strict non-black, relaxed black} × {$20–30k, $30–40k}**, up to 5 cars each, ranked,
≤1 per model per bucket. HTML parse mode, web preview off. A blank line separates the two price bands.

```
Silver/gray leather hybrid/PHEV SUVs, 2021+, <50k mi

Strict — non-black interior:
$20–30k:
1. 2024 Mazda CX-90 PHEV Preferred — $29,590 | 12k mi | Gray — view
2. 2022 Honda CR-V Hybrid EX-L — $29,888 | 19k mi | Silver — view

$30–40k:
1. 2026 Honda CR-V Hybrid Sport-L FWD — $39,080 | 1k mi | Solar Silver — view
... (up to 5)

Relaxed — black interior also OK:
$20–30k:
... (up to 5)

$30–40k:
... (up to 5)
```

Each line: `N. <year make model trim> — $price | Xk mi | Color — <a>view</a>`. Empty bucket → `—`.

---

## 11. Open Questions / Decisions Needed

- **CarMax is dark headless** (static carousel only). Decide: drop it from the pipeline, or keep as a
  near-useless source.
- **Leather is tag-based across all makes** (Carvana `cvnaFeatures`) — a tradeoff vs the buyer's older
  trim-spec preference, but required to span every make. Cars.com still uses accurate trim-spec.
- **NHTSA lookups add ~30–40s** to a run (one live call per unique make/model/year). Parallelize or
  cache to disk if runtime matters.
- **Two-word models** (Santa Fe, Grand Cherokee) → NHTSA lookup falls back to brand-only (model token =
  second title word). Fine for now.

---

## 12. Test Plan / Acceptance Criteria

### A. Repro
```bash
cd ~/code/misc/rav4-tracker
./scraper_venv/bin/python scrape.py --out /tmp/shortlist.json   # full run, audit, no send
./scraper_venv/bin/python scrape.py --no-browser --dry-run      # Cars.com only, fast
./scraper_venv/bin/python scrape.py                             # real end-to-end send
# Invisibility check during a run — must show 0 windows:
osascript -e 'tell application "System Events" to tell (every process whose name contains "Chrome") to get count of windows'
```

### B. Acceptance
- One Telegram message, 4 buckets, ≤5 each, ≤1 per model per bucket.
- Every car: silver/light-gray, leather, hybrid/PHEV SUV, 2021+, <50k mi, in price band, **clean title**,
  not Jeep/Kia, not sold. Reliability-weighted order (Toyota/Honda ahead of same-tier rivals).
- **Zero on-screen browser windows** the entire run.

### C. Automated tests
- *To add:* unit tests for `is_silver`, `has_leather`, `reliability_multiplier` (Toyota > same-year
  Mazda). Currently only the sibling `test_price.py` exists (email tracker).

---

## 13. References / Links

- **Cars.com** params: `stock_type, body_style_slugs[]=suv, clean_title=true, list_price_min/max,
  mileage_max, year_min/max, exterior_color_slugs[], fuel_slugs[], zip, maximum_distance, page_size, sort`.
- **Carvana** `cvnaid` blob (base64): `{filters:{bodyStyles, fuelTypes, colors, interiorColors,
  cvnaFeatures}}` on `/cars/filters`. Listings in `<script type="application/ld+json">` `@type=Car`.
- **NHTSA** complaints: `https://api.nhtsa.gov/complaints/complaintsByVehicle?make=&model=&modelYear=`.
- **zendriver** (raw-CDP headless): `zd.start(headless=True)`, `tab.verify_cf()`, `tab.get(url)`,
  `page.evaluate(..., return_by_value=True)`.
- **Telegram Bot API**: `sendMessage` (HTML, preview off). Sibling docs: `plans/browser_interaction.md`;
  auto-memory `[[feedback-browser-automation]]`, `[[feedback-car-pipeline]]`.

---

## 14. File List

**Scraper (this project) — all under `~/code/misc/rav4-tracker/`:**
- `scrape.py` — the pipeline + CLI. Flags: `--dry-run`, `--out FILE`, `--no-browser`.
- `car_search.py` — filters + scoring: `search_urls`/`crossmake_search_url`, `is_silver`,
  `has_leather`/`LEATHER_TRIMS`, `MANUFACTURER_MULTIPLIER`, `reliability_multiplier` (+ NHTSA/`MODEL_ANNUAL_SALES`),
  `trim_score_multiplier`, `is_blocked_make`/`is_blocked_model`, `send_ranked`.
- `browser_scraper.py` — Carvana + CarMax via zendriver headless: `scrape_carvana` (cvnaid filter-first),
  `scrape_carmax`, `_carvana_crossmake_url`, `_clear_cloudflare`.
- `config.py` — load Telegram + Gmail creds. `paths.py` — secret file locations.

**Sibling email-quote tracker (out of scope, §6) — same dir:**
- `send.py` — blast the quote email to dealers. `poll.py` — poll Gmail replies → price → Telegram.
- `price.py` — price extraction. `prepare_message.py` — pull the sent email body.
- `bot.py` — Telegram control-plane bot. `oauth_setup.py` — Gmail OAuth. `telegram_setup.py` — bot
  token/chat_id capture. `test_price.py` — unit tests for `price.py`.

**Shared invisible-Chrome toolkit — `~/code/misc/src/browser_interaction/`** (own doc:
`plans/browser_interaction.md`): `launch_chrome_with_cdp.sh` (starts the `:9334` headless engine);
Python helpers `__main__.py`, `chrome_cdp_session.py`, `read_ld_json.py`, `navigate_tab.py`,
`get_page_text.py`, `run_javascript_in_tab.py`, `list_open_tabs.py`, `click_in_tab.py`, `type_in_tab.py`,
`upload_files_via_drag_drop.py`, `upload_files_via_file_chooser.py`, `write_google_sheet_cell.py`.

**Not committed:** `scraper_venv/` (Python 3.13: zendriver, playwright, requests, google-auth);
`~/secrets/rav4-tracker/telegram.json` (`{bot_token, chat_id}`).

---

## 15. Long Jobs / Backfill

- A full run is ~1.5–2.5 min (Cars.com ~25s + Carvana 4 queries + NHTSA lookups ~30–40s). Run it in the
  background and tail `/tmp/scrape_run.log`; `/tmp/scrape_log.json` has the full selection for auditing.

---

## 16. Rollback Plan

- Git-tracked; `git revert` / checkout `scrape.py`/`car_search.py`/`browser_scraper.py`. No migrations.
- A Telegram send can't be unsent — audit with `--out` first, then send.

---

## 17. Postmortems

**2026-06-14 — headed browser stole the buyer's desktop focus.** Launching the CarMax/Carvana scraper
via a *headed* CDP Chrome (`CDP_MODE=headed`, `open -g -j` "hidden") surfaced a window and shifted the
buyer to another Space mid-run. **Root cause:** on macOS a headed Chrome cannot be kept invisible — the
OS surfaces it. **Fix:** `zendriver` **headless** (raw CDP) bypasses Akamai/Cloudflare without a window
(the decisive anti-bot layer is automation-protocol fingerprinting, not headed-vs-headless). **Guardrail:**
headed browsers permanently banned. (Near-identical focus-steal also on 2026-06-11.)

---

## 18. Project History

- **2026-06-10** — Built the finder: Cars.com scrape + `car_search` filter rules + value ranking; texted
  a verified top-10. Hardened availability after a sold car nearly went out (Cars.com keeps sold live).
- **2026-06-11/12** — Added CarMax + Carvana (LD+JSON) into one `scrape.py`; price buckets; brand
  diversity; `/tmp/scrape_log.json`. Required `data-vehicle-details` to fix an out-of-region leak.
- **2026-06-14** — **Migrated CarMax/Carvana to `zendriver` headless** (raw CDP); banned headed browsers
  (§17). Verified zero-window bypass; Carvana Cloudflare via `verify_cf`+reload. Forked this plan.
- **2026-06-14** — **Unblocked Cars.com** (auto-launch the `:9334` real-Chrome engine — Playwright's own
  Chromium and a fresh-profile Chrome are Cloudflare-blocked). Made browser sources crash-isolated.
- **2026-06-14** — **Filter-first refactor (both sites).** Replaced per-model loops with no-make queries:
  Carvana cvnaid (body+fuel+color+interior+leather, server-side) and Cars.com body-style URLs. Surfaces
  every make (Mazda CX-90 PHEV, Audi Q5, Dodge Hornet…). Stopped walking thousands (Carvana 2503→~250).
  Fixed Ford Escape (base slug + parser). Removed Nissan Rogue/Murano. Cars.com title from JSON; paginate
  to exhaustion. Full pipeline ~5:36 → ~1:40.
- **2026-06-14** — **4 buckets + diversity + reliability + salvage.** Message → 4 buckets ({strict,
  relaxed}×{$20-30k,$30-40k}), ≤1 per model per bucket. Reliability = rescaled brand multiplier × live
  NHTSA complaints-per-sales factor (confidence-damped + first-gen penalty). Salvage titles eliminated
  via Cars.com `clean_title=true` (only it lists branded titles; Carvana/CarMax clean by policy).
  Blacklist Jeep/Kia. Year floor re-enforced locally (Carvana `/cars/filters` ignores URL year).
