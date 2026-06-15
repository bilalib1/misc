# Used-Car Finder — multi-site scraper → Telegram shortlist

**Forked from:** `../plan-template.md`

A single end-to-end Python script (`rav4-tracker/scrape.py`) that, when run, scrapes used-car
listings from **Cars.com, CarMax, and Carvana**, keeps only the cars matching the buyer's exact spec
(silver/light-gray hybrid crossover, non-black leather, 2022-ish+, <50k mi, $20–40k, greater LA +
nationwide-delivery sources), ranks them by value × reliability with brand diversity, VIN-verifies
availability, and **sends the buyer a Telegram message** with the ranked shortlist. Run the script →
get a text of the current qualifying used market. Everything runs **fully headless / invisibly** —
no browser window ever appears.

---

## 1. How To Use This Template

**Repo layout:** `~/code` holds all repos, one directory per repo (this lives in `~/code/misc`). Plans
reference paths relative to their own repo root.

Fork into `plans/YYYY-MM-DD-<slug>.md`, one per task. Keep the `**Forked from:**` line. Every section
stays in every fork. **500 lines max.** Cut prose first when tight.

---

## 2. Maintain This Plan

- **Living document — maintain it constantly.** The moment anything changes (decision, course change,
  result, new constraint, status), update this file so we can clear the conversation and resume cold
  from here alone.
- **Own the plan.** Update + commit *in the same turn* at checkpoints.
- Keep: decisions + *why*, paths, commands, thresholds, acceptance. Drop: diary text, dead
  alternatives, narration.
- One status table (§5). Project History (§18) is append-only. Keep the File List (§14) current.

---

## 3. Preferences / Best Practices

- **Be autonomous.** Decide and execute; ask only when blocked, genuinely ambiguous, or before
  destructive/irreversible actions. For *this* pipeline the buyer is explicit: run the scrape+send
  loop end-to-end without asking permission for reasonable changes.
- **Simplicity + surgical changes.** Minimum code that solves the problem; every changed line traces
  to the request.
- **Read before write; evidence first.** Verify with data before mutating shared state.
- **Write reusable Python scripts** rather than ad-hoc command strings.
- **Delegate long-running work to subagents / background** to keep the main chat unblocked.
- **Invisibility is a HARD rule (see §6).** Nothing may render on the buyer's Mac.

---

## 4. Context & Problem Statement

- **Who/why:** Buyer is shopping for a RAV4-Hybrid-class used car and wants to watch the market across
  the big listing sites without manually checking each one.
- **Desired "done":** Run `python scrape.py` → a Telegram message arrives listing **all currently
  available cars that fit the spec**, from Cars.com + CarMax + Carvana, ranked best-first in two price
  buckets, each VIN-verified as still for sale.
- **The buyer's spec (the filter):**
  - **Exterior:** silver / LIGHT gray ONLY. Dark/blue-leaning grays (graphite, magnetic, gunmetal,
    charcoal, machine gray…) and all vivid colors are vetoed. White is excluded.
  - **Interior:** leather (or leather-like: SofTex/NuLuxe/etc.), **any color except a solid black
    cabin.** Leather is decided by the trim's *standard spec*, never a listing's "Leather Seats" tag.
  - **Powertrain / body:** hybrid or PHEV crossover/SUV.
  - **Year / miles / price:** model year ≥ `YEAR_MIN` (currently **2021** in code; buyer's intent is
    ~2022+), **< 50k mi**, **$20k–$40k**.
  - **Location:** greater LA (~75 mi of zip 90012) for franchise/used dealers via Cars.com; **anywhere**
    via CarMax / Carvana (they deliver).
- **Current state:** Pipeline built and working. CarMax (Akamai) + Carvana (Cloudflare) bypassed via
  **zendriver headless** (raw CDP). Cars.com scraped headless. Filters, scoring, diversity, VIN
  verification, and Telegram send all implemented in `scrape.py` + `car_search.py` + `browser_scraper.py`.
- **Constraints:**
  - **Perfect invisibility (hard):** no browser window may ever appear on the Mac. A *headed* browser
    on macOS surfaces and steals focus even when "hidden" — banned (see §17 postmortem).
  - CarMax/Carvana 403-block plain HTTP and detect Playwright; need raw-CDP headless.
  - Cars.com keeps **sold** cars live in results and detail pages → must VIN-verify before sending.
  - Runs as a **local** Python script in `scraper_venv` (Python 3.13). Secrets in
    `~/secrets/rav4-tracker/` (never in repo).

---

## 5. Execution Steps

| # | Task | Status |
| - | ---- | ------ |
| 1 | Cars.com scraper (headless) + LA-zip filter | completed |
| 2 | `car_search` filter rules (color / interior / leather-by-trim) | completed |
| 3 | Value × reliability scoring + brand-diversity selection | completed |
| 4 | VIN verification on seller's own site (drop sold cars) | completed |
| 5 | CarMax + Carvana bypass | completed — migrated to **zendriver headless** 2026-06-14 |
| 6 | Two-bucket ranked Telegram send | completed |
| 7 | End-to-end run → send (per buyer's autonomous-loop request) | recurring — run on demand |
| 8 | Carvana exhaustive pagination (`?page=N`) | completed 2026-06-14 — e.g. RAV4 21→220 |
| 9 | Concurrency: Cars.com 4 workers + Carvana 4 tabs, run concurrently | completed 2026-06-14 |
| 10 | Auto-launch invisible `:9334` engine (Cars.com Cloudflare) | completed 2026-06-14 |

---

## 6. Out of Scope / Non-Goals

- **No headed / visible browser.** Invisibility is a hard constraint; everything is `--headless=new`.
- **No auto-negotiation or auto-replies.** We scrape and notify only; the buyer handles dealers.
- **No web UI / dashboard.** A Telegram message is the whole product.
- **No exhaustive Carvana crawl.** We sample ~21 listings per model URL (Carvana paginates, doesn't
  infinite-scroll); accepted to keep runs fast and unblocked.
- **The dealership email-quote tracker is a separate sibling system** (`send.py` / `poll.py` /
  `bot.py` + a GitHub Actions cron that emails 10 dealers and texts the lowest quote). It shares the
  repo + Telegram channel but is NOT part of this scraper.

---

## 7. Architecture

```
                  ┌────────────────────┐
                  │  scrape.py (run)   │  python scrape.py
                  └─────────┬──────────┘
        ┌───────────────────┼────────────────────┐
        │ headless          │ zendriver headless  │ zendriver headless
        ▼                   ▼                     ▼
  ┌───────────┐      ┌────────────┐        ┌────────────┐
  │ Cars.com  │      │   CarMax   │        │  Carvana   │
  │ (CDP/PW)  │      │  (Akamai)  │        │(Cloudflare)│
  └─────┬─────┘      └─────┬──────┘        └─────┬──────┘
        │ cards w/         │ LD+JSON             │ LD+JSON
        │ data-vehicle-    │                     │ (verify_cf
        │ details JSON     │                     │  if blocked)
        └───────────────┬──┴─────────────────────┘
                        ▼  normalize → common listing dict
              ┌────────────────────────┐
              │  car_search filters    │ color / interior /
              │  is_silver, has_leather│ leather-by-trim / zip
              └───────────┬────────────┘
                          ▼  verified candidates
              ┌────────────────────────┐
              │ VIN-verify on dealer   │ drop sold (Cars.com lags)
              │ site (Cars.com only)   │
              └───────────┬────────────┘
                          ▼
              ┌────────────────────────┐
              │ score × reliability ×  │ _score, then
              │ trim; diversity select │ _select_incremental
              └───────────┬────────────┘
            under $30k ▼        ▼ $30–40k   (top 5 each)
              ┌────────────────────────┐
              │  Telegram sendMessage  │──► buyer's phone
              └───────────┬────────────┘
                          ▼
                 /tmp/scrape_log.json   (full log for spot-check)
```

- **Invisibility:** CarMax/Carvana → `zendriver.start(headless=True)`; Cars.com → optional
  `connect_over_cdp(SCRAPE_CDP_URL)` else `chromium.launch(headless=True)`. No window, ever.

---

## 8. Databases and Schemas

No persistent database. State is ephemeral:

- **`/tmp/scrape_log.json`** *(rewritten each run)* — `counts`, `make_distribution`, `selected`
  (the sent shortlist), and `all_verified`. Each entry is "slimmed": title, price, miles, ext_color,
  interior, city, dealer, seller_zip, vin, source, **image URL**, url. Used for autonomous
  image-spot-checking and anomaly detection — not read back by the pipeline.
- **`/tmp/shortlist.json`** *(only with `--out`)* — the ranked shortlist as a JSON array.
- Source of truth for "still available" is each **dealer's live site** (VIN check), not any local store.

---

## 9. Implementation Details

**Main pipeline — `scrape.py run()`**

1. `_ingest_browser_sources()` first: run `scrape_carmax` + `scrape_carvana` (zendriver headless),
   pre-filter each by color/interior/leather/price/miles → browser listings.
2. Build Cars.com URLs from `car_search.search_urls()` (one per model × {silver, gray}); cap at
   `MAX_SEARCH_URLS`. Connect to an invisible CDP engine if present, else launch headless Chromium.
3. For each URL, paginate search results; `_extract_card` reads the per-card
   `data-vehicle-details` JSON (VIN, price, mileage, exterior color, seller zip) — **require** that
   blob so nationwide "similar cars" without a seller zip can't leak past the LA filter.
4. **Basic filters:** year ≥ `YEAR_MIN`, price in range, miles ≤ max, `is_silver(ext_color)`,
   `_is_la_area_zip(seller_zip)`, recognized non-blocked model, `has_leather(model, trim)`.
5. **Detail pass:** open each candidate's detail page (interior color isn't on the card); drop sold
   (`SOLD_MARKERS`), black interiors (`has_acceptable_interior`), and confirmed-cloth.
6. Merge browser listings (already verified from live pages), dedupe by VIN.
7. Split into `under30` / `over30` buckets; `_select_incremental(top_n=5)` each.
8. Write `/tmp/scrape_log.json`; then send / `--dry-run` print / `--out` write.

**Exterior color — `is_silver(color)`**

1. Lowercase. 2. If any `DARK_COLOR_MARKERS` substring → reject (graphite, magnetic, machine gray…).
3. If the whole string is a `_BLOCKED_COLORS` word (black/blue/red…/gold) → reject. 4. Pass only if a
`SILVER_ROOTS` word is present (silver, gray, chrome, platinum, titanium, stardust, sterling, ingot).

**Leather decision — `confirms_leather` then `has_leather`**

1. If the listing carries real seat-material text (CarMax `vehicleInteriorType`, Cars.com spec):
   `confirms_leather` → True (leather/leatherette/SofTex/NuLuxe…) keeps; False (cloth/fabric/vinyl)
   drops. 2. If no material text: fall back to `has_leather(model, trim)` — a curated `LEATHER_TRIMS`
   map of trims whose **standard** seat is leather/leather-like (e.g. RAV4 Hybrid XLE Premium/XSE/
   Limited; SE is fabric → dropped). Re-verify per model year.

**Scoring — `_score(listing)`**

1. `year_pts = (year-2019)*100` (dominant), `mile_pts = (MILES_MAX-miles)/500`,
   `price_pts = (PRICE_MAX-price)/2000` (tiebreaker). 2. `base = sum`. 3. `× MANUFACTURER_MULTIPLIER`
   (Toyota/Lexus 1.10 … Jeep 0.90) `× trim_score_multiplier` (0.95–1.10 by trim rank). Higher = better.

**Diversity selection — `_select_incremental(listings, top_n=5, brand_penalty=0.12)`**

1. Greedy: each slot picks the highest *effective* score = `raw × (1 − penalty)`. 2. Penalty grows
   `+0.12` per already-picked same-brand car, `+0.12` more if same brand **and** model. 3. A great
   same-brand car still wins if proportionally better — a nudge, not a cap.

**Carvana — `browser_scraper.py` (zendriver headless, FILTER-FIRST)**

1. `zendriver.start(headless=True)` (system Chrome, `--headless=new`, no window).
2. **No make/model loop.** Build NO-MAKE `/cars/filters?...&cvnaid=<base64>` URLs whose blob filters
   server-side: `bodyStyles=[suv]` + `fuelTypes=[Hybrid, Plug-In Hybrid]` + `colors=[Silver, Gray]` +
   `interiorColors` + `cvnaFeatures` (leather). The leather features are AND-combined, so we run 4
   concurrent queries = {non-black, black} interior × {Genuine, Synthetic} leather (one tab each).
3. Each query: `_clear_cloudflare` (verify_cf / wait+reload), paginate `&page=N` until no new VINs,
   extract `@type=Car|Vehicle` LD+JSON. Tag interior (non-black→"", black→"Black") and `leather_ok=True`.
4. Returns every qualifying car across ALL makes (Mazda CX-90 PHEV, Dodge Hornet, Audi Q5, …). Local
   side (scrape.py `_ingest_browser_sources`) blacklists Jeep/Kia, trusts `leather_ok` (skips the trim
   gate), and the scoring fn ranks all → top 10 strict + top 10 relaxed.

**CarMax — `browser_scraper.py`** (zendriver headless): still per-search; headless only yields a static
22-car carousel (Akamai-API-gated grid never fires), so it contributes ~nothing. Leather verified from
its LD+JSON `vehicleInteriorType` since it has no server leather filter.

---

## 10. Data Snippets

Cars.com card JSON (`data-vehicle-details`, trimmed):
```json
{ "vin": "JTMB6RFV5NJ019126", "price": 34590, "mileage": 22310,
  "exteriorColor": "Silver Sky Metallic", "seller": { "zip": "91204" } }
```

CarMax LD+JSON block (trimmed):
```json
{ "@type": "Car", "name": "2023 Toyota RAV4 Hybrid XSE", "color": "Silver",
  "vehicleInteriorColor": "Black", "vehicleInteriorType": "Leatherette Seats",
  "offers": { "price": 39998 }, "vehicleIdentificationNumber": "4T3..." }
```

Telegram message (what the buyer receives):
```
Under $30k:
1. 2024 Mazda CX-50 Hybrid Premium — $28,990 | 18k mi | Machine Gray — view
2. 2022 Toyota RAV4 Hybrid XLE Premium — $29,450 | 31k mi | Silver — view

$30–40k:
1. 2024 Lexus NX 350h Premium — $38,200 | 12k mi | Silver — view
```

---

## 11. Open Questions / Decisions Needed

- **Year floor mismatch:** `car_search.YEAR_MIN = 2021` but the browser scrapers default `year_min=2022`
  and the buyer says "2022+". Pick one and make it consistent.
- **CarMax is effectively dark headless.** It only exposes a static 22-car recommendation carousel; the
  real filtered grid is Akamai-API-gated and never fires under automation. Decide: drop CarMax from the
  pipeline, or accept it as a near-useless source. (Currently kept but contributes ~nothing.)
- **A few Carvana models still exceed 50 even color-filtered:** RAV4 ~102, CR-V ~71, Jeep Wrangler 365 /
  Grand Cherokee 326 (the parentModel color filter includes gas; only the 4xe subset is kept). `cvnaid`
  also supports `fuelTypes`, but the PHEV value string is finicky (a wrong value silently returns 0), so
  it's NOT used — the client-side `_carvana_is_hybrid` drops the gas cars instead. These counts are real
  qualifying inventory, not waste; revisit fuelTypes only if Jeep's ~17-page walk matters.
- **Concurrency vs reliability:** Cars.com now runs FIRST, then the browser sources (was concurrent).
  With Carvana now light (color-filtered), restoring 8-way concurrency is viable again if speed matters.

*Resolved 2026-06-14:* **Carvana over-scraping** — was walking thousands (Jeep 1,481/model); now builds
a `/cars/filters?...&cvnaid=<base64>` URL that filters **make+parentModel+exterior-color (Silver/Gray)**
server-side (2503→311 total listings; discovered by clicking the filter UI headlessly, then constructing
the blob directly). **Cars.com Cloudflare** hard-blocked Playwright's own Chromium AND a fresh-profile
Chrome; only the real-Chrome `:9334` engine (auto-launched, `--headless=new`) passes — `scrape.py`
auto-starts it. **Ford Escape** now scraped (base `ford-escape` slug + a parser that handles "Escape
PHEV"/"Escape Titanium"; "Carbonized Gray" vetoed). `"titanium"` removed from `SILVER_ROOTS` (gold Venza).
`only_hybrid` no longer drops PHEVs/always-hybrids. Removed Nissan Rogue/Murano (no US hybrid).

---

## 12. Test Plan / Acceptance Criteria / Repro Steps

### A. E2E / Human Test Plan

```bash
cd ~/code/misc/rav4-tracker
# 1. Inspect without sending (full pipeline → file + /tmp/scrape_log.json):
./scraper_venv/bin/python scrape.py --out /tmp/shortlist.json
# 2. Cars.com only (fastest, fully verified, no anti-bot sites):
./scraper_venv/bin/python scrape.py --no-browser --dry-run
# 3. Real end-to-end send:
./scraper_venv/bin/python scrape.py
# During any run, confirm NO visible Chrome (must print nothing):
osascript -e 'tell application "System Events" to get name of every process whose visible is true' | tr ',' '\n' | grep -i chrome
```

### B. Acceptance Criteria

- Running `python scrape.py` sends exactly one Telegram message with two buckets (under $30k / $30–40k),
  best-first, each line `make/model/trim — price | miles | color — view`.
- Every sent car: silver/light-gray exterior, non-black leather (trim-verified), hybrid/PHEV, in range,
  and (Cars.com) VIN-confirmed live on the dealer site. No sold cars.
- **Zero visible browser windows** during the entire run.
- Make distribution shows diversity (no single brand dominating the 10).

### C. Automated Tests

- Unit (`car_search`): `is_silver` (graphite rejected, "Silver Sky" passed), `has_leather` (RAV4 SE
  fabric dropped), `confirms_leather` (cloth=False, SofTex=True). *(to add — currently only the sibling
  `test_price.py` exists, which covers the email tracker, not the scraper.)*
- Integration: `browser_scraper` returns ≥1 `@type=Car` block from CarMax headless (no challenge page).

---

## 13. References / Links

- **Cars.com** search params: `stock_type, makes[], models[], list_price_min/max, mileage_max,
  year_min/max, exterior_color_slugs[], fuel_slugs[]=hybrid|plug_in_hybrid, zip, maximum_distance`.
- **CarMax / Carvana**: car data is in `<script type="application/ld+json">` `@type=Car|Vehicle` blocks.
- **zendriver** (raw-CDP headless): `zd.start(headless=True)`, `tab.verify_cf()`, `page.evaluate(...,
  return_by_value=True)`.
- **Telegram Bot API**: `sendMessage` (HTML parse mode, web preview off).
- Sibling docs: `plans/browser_interaction.md` (headless strategy); auto-memory
  `[[feedback-browser-automation]]`, `[[feedback-car-pipeline]]`.

---

## 14. File List

All under `~/code/misc/rav4-tracker/` unless noted.

- `scrape.py` — **the end-to-end pipeline + CLI.** Scrape → filter → verify → score → Telegram send.
  Flags: `--dry-run`, `--out FILE`, `--no-browser`, `--allow-black`.
- `car_search.py` — filter rules + scoring tables: `is_silver`, `has_acceptable_interior`,
  `has_leather`/`LEATHER_TRIMS`, `MANUFACTURER_MULTIPLIER`, `TRIM_RANKS`, `search_urls`, `send_ranked`.
- `browser_scraper.py` — CarMax + Carvana via **zendriver headless**: `scrape_carmax`, `scrape_carvana`.
- `config.py` / `paths.py` — load Telegram + Gmail creds from `~/secrets/rav4-tracker/`.
- `scraper_venv/` — Python 3.13 venv (zendriver, requests, google-auth). *(not committed)*
- `~/secrets/rav4-tracker/telegram.json` — `{bot_token, chat_id}`. *(never committed)*
- `~/code/misc/src/browser_interaction/` — invisible-Chrome helpers + `launch_chrome_with_cdp.sh`
  (headless engine for the optional Cars.com CDP path). `plans/browser_interaction.md` documents it.
- *Sibling (out of scope, §6):* `send.py`, `poll.py`, `bot.py`, `price.py`, `dealers.json`,
  `.github/workflows/rav4-poll.yml` — the dealership email-quote tracker.

---

## 15. Long Jobs / Backfill

- A full run is ~10–15 min (CarMax + 18 Carvana model pages + Cars.com URLs, each with waits/scroll).
  **Run it in the background** and tail `/tmp/scrape_run.log`; the per-source progress lines show
  candidate/drop/finalist counts. Don't block the main chat on it.
- The pipeline already logs everything to `/tmp/scrape_log.json` (incl. image URLs) for spot-checking
  before/after a send.

---

## 16. Rollback Plan

- Code is local + git-tracked; revert a bad change with `git revert` / checkout of `scrape.py` /
  `browser_scraper.py`. No migrations or shared state to undo.
- A bad Telegram send can't be unsent — mitigate by inspecting `--out` / `--dry-run` first (the
  buyer's required spot-check loop), then sending.

---

## 17. Postmortems

**2026-06-14 — headed browser stole the buyer's desktop focus.** Launching the CarMax/Carvana scraper
via a *headed* CDP Chrome (`CDP_MODE=headed`, `open -g -j` "hidden") surfaced a window and shifted the
buyer to another Space mid-run; buyer interrupted. **Root cause:** on macOS a headed Chrome cannot be
kept invisible — the OS surfaces it. **Fix:** migrated to `zendriver` **headless** (raw CDP), which
bypasses Akamai/Cloudflare without a window (the decisive anti-bot layer is automation-protocol
fingerprinting, not headed-vs-headless). **Guardrail:** headed browsers permanently banned; see
`[[feedback-browser-automation]]`. Cost: ~1 interrupted run + the rewrite. (Earlier near-identical
focus-steal on 2026-06-11.)

---

## 18. Project History

- **2026-06-10** — Built the used-car finder: Cars.com scrape + `car_search.py` filter rules
  (silver-synonym allowlist + dark-color veto; leather-by-trim) + value ranking; texted a verified
  top-10. Hardened availability to **VIN-on-dealer-site** after a sold car was nearly sent (Cars.com
  keeps sold cars live).
- **2026-06-11/12** — Added CarMax + Carvana (LD+JSON) and merged into one `scrape.py` pipeline with
  two price buckets, brand-diversity selection, and `/tmp/scrape_log.json` for spot-checking. Fixed an
  out-of-region leak by requiring the `data-vehicle-details` blob + `_is_la_area_zip`.
- **2026-06-14** — **Migrated CarMax/Carvana to `zendriver` headless (raw CDP); truly invisible
  bypass.** Verified both sites scrape fully headless with zero windows; Carvana's intermittent
  Cloudflare handled via `verify_cf` + reload. Replaced the banned headed path. Forked this plan from
  the template to center the end-to-end "run the script → get a Telegram shortlist" story.
- **2026-06-14** — **Parallelized + unblocked + fixed.** Cars.com was fully Cloudflare-blocked (both
  Playwright's Chromium and a fresh-profile Chrome); fixed by auto-launching the invisible `:9334`
  real-Chrome engine and connecting over CDP — now runs **4 concurrent worker pages** (242→~13 verified
  in ~1:50). Carvana made **exhaustive** (`?page=N` walk, e.g. RAV4 21→220) across **4 concurrent tabs**
  in one browser (shared Cloudflare cookie), running concurrently with Cars.com. Fixed `only_hybrid`
  wrongly dropping PHEVs/always-hybrids (Venza/Lexus/Jeep 4xe 0→recovered). Removed `"titanium"` from
  the silver allowlist after an image spot-check caught a gold Venza. Made browser sources resilient so
  one source crashing (e.g. a zendriver websocket drop on CarMax) no longer aborts the send.
- **2026-06-14** — **Server-side Carvana filtering (stop walking thousands) + two-section message.**
  Carvana was paginating whole catalogs (Jeep 1,481/model). Discovered — by clicking the filter UI in the
  invisible headless browser — that Carvana encodes filters in a base64 `cvnaid` param; now build it
  directly (`make`+`parentModel`+`colors:[Silver,Gray]`) so each model returns pre-filtered Silver/Gray
  (total 2503→311). Cars.com timeouts traced to concurrency starving it under the heavy Carvana load →
  sequenced Cars.com first (retries+stagger also added). Telegram message now has **two sections**:
  (1) full filters (non-black interior), (2) same but interior color relaxed (black OK). Fixed Ford
  Escape (base slug + parser + Carbonized-Gray veto). Removed Nissan Rogue/Murano (no US hybrid).
- **2026-06-14** — **FILTER-FIRST refactor (cross-make).** Replaced Carvana's per-model loop with NO-MAKE
  cvnaid queries filtering body=SUV + fuel=Hybrid/Plug-In Hybrid + color=Silver/Gray + interior + leather
  (`cvnaFeatures`, genuine OR synthetic — AND-combined so 4 queries) ALL server-side. Surfaces every
  qualifying car across all makes (Mazda CX-90 PHEV, Dodge Hornet, Audi Q5, Lexus UX…) instead of a
  curated 13-model list — this is what was hiding cars like the Ford Escape. Leather enforced via the
  feature tag (tradeoff vs the buyer's old trim-spec preference, required to span all makes). Local:
  make blacklist (Jeep, Kia); scoring fn ranks everything → **top 10 strict + top 10 relaxed**. Cars.com
  filter-first refactor is next (still model-by-model).
