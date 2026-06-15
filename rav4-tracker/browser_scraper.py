"""
Zendriver (raw-CDP) headless scraper for CarMax and Carvana.

WHY ZENDRIVER, HEADLESS: CarMax (Akamai) and Carvana (Cloudflare) block naive
automation. The decisive anti-bot layer in 2026 is automation-PROTOCOL
fingerprinting (WebDriver / CDP `Runtime.enable`), not headed-vs-headless.
Zendriver drives Chrome over a bare WebSocket CDP connection with no WebDriver
and no Playwright shim, so it passes that layer while running FULLY HEADLESS
(`--headless=new`) — which on macOS means no window is ever created and the
user's desktop is never disturbed. This replaced a Playwright+stealth version
that required a *headed* browser (which macOS surfaces, stealing focus).

Both sites embed structured car data in LD+JSON <script> blocks, so we navigate,
let the SPA hydrate (clearing Cloudflare's interstitial when present), scroll to
load lazy listings, extract the blocks, and close the browser.

CarMax  — full schema: VIN, price, year, make, model, trim, exterior color,
           interior color + type, mileage, fuel type, stock number → listing URL.
Carvana — VIN, price, year, make, model, trim (from description), exterior
           color, mileage, listing URL (in offers.url).

Public API is unchanged (sync, same return schema as before):
    from browser_scraper import scrape_carmax, scrape_carvana
    listings = scrape_carmax(zip_code="90012", radius=75, year_min=2022,
                             price_min=20000, price_max=40000, miles_max=50000)
    listings = scrape_carvana(zip_code="90012", year_min=2022,
                              price_min=20000, price_max=40000, miles_max=50000)

Each function returns a list of dicts:
    {
        "title":         "2023 Toyota RAV4 Hybrid XSE",
        "make":          "Toyota",
        "model":         "RAV4 Hybrid",
        "trim":          "XSE",
        "year":          2023,
        "price":         39998,
        "miles":         42030,
        "color":         "White",
        "interior":      "Black",
        "interior_type": "Leather Seats",   # CarMax only
        "fuel":          "Hybrid",           # CarMax only
        "vin":           "4T3E6RFV3PU134387",
        "url":           "https://www.carmax.com/car/70022154",
        "source":        "carmax",
    }
"""

import asyncio
import base64
import json
import re

import zendriver as zd

# ---------------------------------------------------------------------------
# Pure parsing helpers (no browser) — reused by callers/filters
# ---------------------------------------------------------------------------

# Fuel types we consider "hybrid / EV" for post-fetch filtering.
# CarMax LD+JSON reports: "Hybrid", "Electric", "Gas", "Diesel", "Flex".
_HYBRID_FUELS = {"hybrid", "plug-in hybrid", "phev"}
# Match hybrid/PHEV tokens incl. brand designators: Jeep 4xe, Volvo Recharge,
# Toyota Prime, Audi e-tron, and Lexus/BMW h/e suffixes (350h, 250h, 450h, 30e…).
_HYBRID_TITLE_RE = re.compile(
    r"\b(hybrid|phev|plug.?in|recharge|prime|e-tron|4xe|\d{2,3}[eh])\b", re.I)

# Safety cap on Carvana pagination: each results page holds ~21 listings, so
# 40 pages covers ~840 listings — far beyond any single model's inventory in our
# price/year/mileage window. Stops a runaway if the "no new VINs" exit ever fails.
CARVANA_MAX_PAGES = 40   # safety cap; the cross-make queries page until no new VINs


def _carvana_trim_from_text(name: str, desc: str) -> str:
    """Extract the trim level from Carvana's name or description.

    Carvana LD+JSON name is often just "2024 Toyota RAV4 Hybrid" (no trim).
    The description is more complete: "Used 2024 Toyota RAV4 Hybrid XLE Premium
    with 19,739 miles."  Grab whatever comes after the fuel-type designator
    (Hybrid / PHEV / Recharge / 350h / 250h …) and before "with N miles".
    """
    _TRIM_PAT = re.compile(
        r"(?:Used|New\s+)?\d{4}\s+\S+\s+(?:\S+\s+){1,3}"
        r"(?:Hybrid|Plug-?in\s+Hybrid|PHEV|Recharge|\d{2,3}[eh])\s+"
        r"(.+?)(?:\s+with\b|\s+\d[\d,]*\s+miles|$)",
        re.I,
    )
    for text in (name, desc):
        m = _TRIM_PAT.search(text or "")
        if m:
            t = m.group(1).strip()
            if t and not re.match(r"^(with\b|\d)", t, re.I) and len(t) > 1:
                return t
    return ""


def _is_hybrid(listing):
    fuel = (listing.get("fuel") or "").lower()
    if fuel in _HYBRID_FUELS:
        return True
    title = (listing.get("title") or "").lower()
    return bool(_HYBRID_TITLE_RE.search(title))


_CARVANA_ALWAYS_HYBRID = ("venza", "prius")   # models with no gas variant


def _carvana_is_hybrid(name, desc):
    """Keep only hybrids/PHEVs. Checks name + description (the name alone often
    omits the trim, so the description carries the 350h/4xe/Hybrid token) plus an
    always-hybrid allowlist for models like Venza that never spell out 'hybrid'."""
    blob = f"{name} {desc}".lower()
    if any(a in blob for a in _CARVANA_ALWAYS_HYBRID):
        return True
    return bool(_HYBRID_TITLE_RE.search(blob))


# Carvana filter values (from the UI's filter accordions, verified live 2026-06-14).
# FILTER-FIRST: we filter SERVER-SIDE on body type + fuel + exterior + interior color
# and do NOT name a make/model — one query returns every qualifying car across ALL
# makes. Leather-by-trim + model recognition happen locally afterward (in scrape.py).
CARVANA_BODY = ["suv"]                          # SUV / Crossover
CARVANA_FUEL = ["Hybrid", "Plug-In Hybrid"]     # note the capital "I" in Plug-In
CARVANA_COLORS = ["Silver", "Gray"]             # buyer's exterior-color filter
# Two disjoint interior buckets so we KNOW each car's interior without a detail page
# (listing LD+JSON omits it): nonblack -> strict section, black -> relaxed section.
CARVANA_INTERIOR = {
    "nonblack": ["Beige", "Brown", "Gray", "White", "Unspecified"],
    "black":    ["Black"],
}
# Leather enforced server-side (the buyer wants leather/leather-like across ALL makes,
# and we no longer have per-model trim data). The two feature values are AND-combined
# by Carvana, so we query them SEPARATELY and union. "Synthetic Leather Seats" covers
# SofTex/NuLuxe (e.g. RAV4 XLE Premium, Lexus); "Genuine Leather Seats" is real leather.
CARVANA_LEATHER = ["Genuine Leather Seats", "Synthetic Leather Seats"]


def _carvana_crossmake_url(interior, leather, year_min, price_min, price_max, miles_max):
    """Build a NO-MAKE Carvana /cars/filters URL (cvnaid blob) filtering by body type
    + fuel + exterior color + interior bucket + ONE leather feature. Returns every
    matching car across all makes; blacklist/ranking happen locally afterward."""
    filters = {"bodyStyles": CARVANA_BODY, "fuelTypes": CARVANA_FUEL,
               "colors": CARVANA_COLORS, "interiorColors": CARVANA_INTERIOR[interior],
               "cvnaFeatures": [leather]}
    cvnaid = base64.urlsafe_b64encode(
        json.dumps({"filters": filters}, separators=(",", ":")).encode()).decode().rstrip("=")
    return ("https://www.carvana.com/cars/filters"
            f"?year={year_min}-2026&price={price_min}-{price_max}&mileage=0-{miles_max}"
            f"&cvnaid={cvnaid}")


# ---------------------------------------------------------------------------
# Browser (zendriver) helpers — all async, all headless
# ---------------------------------------------------------------------------

_LD_JSON_JS = """
Array.from(document.querySelectorAll('script[type="application/ld+json"]'))
  .map(s => { try { return JSON.parse(s.textContent); } catch { return null; } })
  .filter(x => x !== null)
"""

_CARMAX_STOCK_URLS_JS = """
(() => {
    const links = document.querySelectorAll('a[href*="/car/"]');
    const result = {};
    for (const a of links) {
        const m = a.href.match(/carmax\\.com\\/car\\/(\\d+)/);
        if (m && !(m[1] in result)) result[m[1]] = a.href;
    }
    return result;
})()
"""

_RESULT_COUNT_JS = """
(() => {
    const t = (document.body ? document.body.innerText : '').slice(0, 4000);
    const m = t.match(/([\\d,]+)\\s+(results?|vehicles?|cars?|listings?)/i);
    return m ? parseInt(m[1].replace(/,/g, ''), 10) : null;
})()
"""

_CF_MARKERS = ("just a moment", "checking your browser", "performing security verification",
               "verify you are human", "needs to review the security", "attention required")


async def _start_browser():
    """Start a fully-headless zendriver Chrome (no window, no focus steal)."""
    return await zd.start(headless=True)


async def _is_blocked(page):
    """True if the page is currently showing a Cloudflare/Akamai interstitial."""
    title = (await page.evaluate("document.title", return_by_value=True)) or ""
    body = (await page.evaluate(
        "document.body ? document.body.innerText.slice(0,300) : ''",
        return_by_value=True)) or ""
    blob = f"{title}\n{body}".lower()
    return any(m in blob for m in _CF_MARKERS)


async def _clear_cloudflare(page, attempts=3):
    """If a Cloudflare interstitial is up, solve/wait it out. Returns True if clear.

    Carvana's Cloudflare is intermittent: usually the page loads straight to
    content; sometimes a "Just a moment…" JS challenge (occasionally an
    interactive Turnstile checkbox) appears. We try verify_cf() for the
    interactive case, then wait for the JS challenge to auto-clear, reloading
    between attempts. All headless — no window is ever shown.
    """
    for _ in range(attempts):
        if not await _is_blocked(page):
            return True
        try:
            await page.verify_cf(timeout=12)
        except Exception:
            pass  # no interactive checkbox — it's the auto-clearing JS challenge
        await page.sleep(6)
        if not await _is_blocked(page):
            return True
        try:
            await page.reload()
        except Exception:
            pass
        await page.sleep(5)
    return not await _is_blocked(page)


async def _scroll_until_stable(page, count_js, max_scrolls=25, pause=2.2, stability_rounds=2):
    """Scroll until the JS-evaluated count stops growing for stability_rounds rounds."""
    prev, stable = 0, 0
    for i in range(max_scrolls):
        await page.scroll_down(500)
        await page.sleep(pause)
        cur = await page.evaluate(count_js, return_by_value=True) or 0
        if cur == prev:
            stable += 1
            if stable >= stability_rounds:
                print(f"    (scroll stable at {cur} after {i+1} scrolls)")
                break
        else:
            stable = 0
        prev = cur
    return prev


async def _dismiss_cookie_dialog(page):
    """Best-effort click of a cookie-consent button. Headless, fast no-op if absent."""
    try:
        await page.evaluate("""
        (() => {
            const labels = ['accept all','accept','i accept','agree','allow all',
                            'got it','continue'];
            const btns = Array.from(document.querySelectorAll('button, a[role="button"]'));
            for (const b of btns) {
                const t = (b.innerText || '').trim().toLowerCase();
                if (labels.some(l => t === l || t.startsWith(l))) { b.click(); return true; }
            }
            return false;
        })()
        """, return_by_value=True)
    except Exception:
        pass


def _car_blocks(ld_blocks, types):
    """Flatten LD+JSON (handles @graph / arrays) and return @type-matching dicts."""
    out = []
    for b in ld_blocks or []:
        items = b if isinstance(b, list) else [b]
        for x in items:
            if isinstance(x, dict) and x.get("@type") in types:
                out.append(x)
            elif isinstance(x, dict) and isinstance(x.get("@graph"), list):
                out.extend(g for g in x["@graph"]
                           if isinstance(g, dict) and g.get("@type") in types)
    return out


# ---------------------------------------------------------------------------
# CarMax (Akamai)
# ---------------------------------------------------------------------------

async def _scrape_carmax_async(zip_code, radius, year_min, price_min,
                               price_max, miles_max, only_hybrid, wait_secs):
    url = (
        f"https://www.carmax.com/cars"
        f"?body_styles=suv_crossover"
        f"&fuel_types%5B%5D=hybrid"
        f"&fuel_types%5B%5D=plug_in_hybrid"
        f"&year_min={year_min}"
        f"&list_price_min={price_min}"
        f"&list_price_max={price_max}"
        f"&mileage_max={miles_max}"
        f"&zip={zip_code}"
        f"&maximum_distance={radius}"
        f"&sort=list_price_asc"
    )

    results = []
    browser = await _start_browser()
    try:
        page = await browser.get(url)
        await page.sleep(wait_secs)
        await _dismiss_cookie_dialog(page)
        await _clear_cloudflare(page)   # CarMax is Akamai, but harmless if no interstitial

        # NOTE: CarMax's filtered results grid is rendered client-side by a SPA
        # that fetches its Akamai-protected inventory API. Under headless
        # automation that API call never fires, so the page only ever shows a
        # static "Used cars near me for sale" recommendation carousel of ~22
        # cars (the same set regardless of our price/year/fuel filters) plus
        # matching SEO LD+JSON. There is NO pagination (?page=N is ignored, no
        # load-more button, scrolling loads nothing further, detail pages carry
        # no @type=Car LD+JSON), so we cannot make CarMax exhaustive without its
        # API. We extract the carousel's @type=Car blocks as before; scrape.py's
        # downstream color/year/hybrid filters drop the non-matching ones.
        await _scroll_until_stable(
            page, "document.querySelectorAll('a[href*=\"/car/\"]').length")

        ld_blocks = await page.evaluate(_LD_JSON_JS, return_by_value=True)
        stock_urls = await page.evaluate(_CARMAX_STOCK_URLS_JS, return_by_value=True) or {}
        car_blocks = _car_blocks(ld_blocks, ("Car",))
        print(f"[carmax] {len(car_blocks)} @type=Car LD+JSON blocks "
              f"(static recommendation carousel; filtered results grid is "
              f"API-rendered and unreachable headless)")

        for block in car_blocks:
            try:
                odo = block.get("mileageFromOdometer") or {}
                miles = odo.get("value") if isinstance(odo, dict) else odo
                img = block.get("image", "")
                m = re.search(r"/assets/(\d+)/", img if isinstance(img, str) else "")
                stock_num = m.group(1) if m else None
                listing_url = stock_urls.get(stock_num) or (
                    f"https://www.carmax.com/car/{stock_num}" if stock_num else "")

                rec = {
                    "title": block.get("name", ""),
                    "make": (block.get("brand") or {}).get("name", ""),
                    "model": block.get("model", ""),
                    "trim": block.get("vehicleConfiguration") or "",
                    "year": block.get("vehicleModelDate"),
                    "price": (block.get("offers") or {}).get("price"),
                    "miles": miles,
                    "color": block.get("color", ""),
                    "interior": block.get("vehicleInteriorColor", ""),
                    "interior_type": block.get("vehicleInteriorType", ""),
                    "fuel": (block.get("vehicleEngine") or {}).get("fuelType", ""),
                    "vin": block.get("vehicleIdentificationNumber", ""),
                    "url": listing_url,
                    "source": "carmax",
                }
                if only_hybrid and not _is_hybrid(rec):
                    continue
                results.append(rec)
            except Exception as e:
                print(f"[carmax] parse error: {e}")
    finally:
        await browser.stop()
    return results


def scrape_carmax(zip_code="90012", radius=75, year_min=2022,
                  price_min=20000, price_max=40000, miles_max=50000,
                  only_hybrid=True, wait_secs=8):
    """Search CarMax for SUV crossover hybrids (headless). Returns structured listings."""
    return asyncio.run(_scrape_carmax_async(
        zip_code, radius, year_min, price_min, price_max, miles_max,
        only_hybrid, wait_secs))


# ---------------------------------------------------------------------------
# Carvana (Cloudflare)
# ---------------------------------------------------------------------------

async def _scrape_carvana_model(tab, slug, base_url, only_hybrid, wait_secs, first):
    """Paginate one Carvana model query on the given tab; return its listings (VIN-deduped).

    base_url is normally a /cars/filters cvnaid URL pre-filtered to Silver/Gray, so
    each model comes back small (tens, not thousands). Carvana paginates via ?page=N
    (each page embeds ~21 cars as LD+JSON); we walk pages until one yields no NEW VINs,
    capped at CARVANA_MAX_PAGES. The color filter broadens to the base model (incl.
    gas), so we always hybrid-filter by name/description (_carvana_is_hybrid)."""
    out = []
    seen = set()
    total = None
    for page_num in range(1, CARVANA_MAX_PAGES + 1):
        url = base_url + (f"&page={page_num}" if page_num > 1 else "")
        page = await tab.get(url)   # navigate THIS worker's own tab
        await page.sleep(wait_secs if (first and page_num == 1) else 4)

        if not await _clear_cloudflare(page):
            print(f"[carvana/{slug}] SKIP page {page_num} — Cloudflare did not clear")
            break
        await _dismiss_cookie_dialog(page)

        if page_num == 1:
            total = await page.evaluate(_RESULT_COUNT_JS, return_by_value=True)
            if total and total > 2000:   # unrecognised slug => full catalog; skip model
                print(f"[carvana/{slug}] SKIP — {total} total suggests unrecognised slug")
                break

        car_blocks = _car_blocks(
            await page.evaluate(_LD_JSON_JS, return_by_value=True), ("Car", "Vehicle"))

        page_new = 0
        for block in car_blocks:
            try:
                vin = block.get("vehicleIdentificationNumber", "")
                if vin and vin in seen:
                    continue
                if vin:
                    seen.add(vin)
                page_new += 1

                miles = block.get("mileageFromOdometer")
                if isinstance(miles, dict):
                    miles = miles.get("value")

                name = block.get("name", "")
                desc = block.get("description", "")
                if only_hybrid and not _carvana_is_hybrid(name, desc):
                    continue

                trim = _carvana_trim_from_text(name, desc)
                full_title = (f"{name} {trim}".strip()
                              if trim and trim.lower() not in name.lower() else name)

                listing_url = (block.get("offers") or {}).get("url", "")
                if not listing_url:
                    sku = block.get("sku")
                    listing_url = f"https://www.carvana.com/vehicle/{sku}" if sku else ""

                out.append({
                    "title": full_title,
                    "make": block.get("manufacturer") or block.get("brand", ""),
                    "model": block.get("model", ""),
                    "trim": trim,
                    "year": block.get("modelDate"),
                    "price": (block.get("offers") or {}).get("price"),
                    "miles": miles,
                    "color": block.get("color", ""),
                    "interior": block.get("vehicleInteriorColor", ""),
                    "interior_type": "",
                    "fuel": "",
                    "vin": vin,
                    "url": listing_url,
                    "source": "carvana",
                })
            except Exception as e:
                print(f"[carvana] parse error: {e}")

        # Exhausted: a page with no cars, or no NEW VINs (last page repeats / empties).
        if not car_blocks or page_new == 0:
            break

    print(f"[carvana/{slug}] {len(out)} listings kept" + (f" / {total} total" if total else ""))
    return out


async def _scrape_carvana_async(zip_code, year_min, price_min, price_max,
                                miles_max, only_hybrid, wait_secs):
    """FILTER-FIRST Carvana scrape: TWO no-make cross-make queries — non-black and
    black interior — each filtered server-side to Silver/Gray Hybrid/PHEV SUVs, then
    paginated. Returns every qualifying car across ALL makes (model/leather selection
    is done locally by scrape.py). The interior tag drives strict vs relaxed sections.
    Leather is enforced server-side; server already fuel-filtered, so the client
    hybrid check is off (only_hybrid=False)."""
    # 4 queries = {non-black, black} interior x {genuine, synthetic} leather.
    queries = [(interior, tag, leather)
               for interior, tag in (("nonblack", ""), ("black", "Black"))
               for leather in CARVANA_LEATHER]

    async def _run(tab, interior, tag, leather, first):
        url = _carvana_crossmake_url(interior, leather, year_min, price_min, price_max, miles_max)
        label = f"{interior}/{leather.split()[0].lower()}"
        cars = await _scrape_carvana_model(
            tab, label, url, only_hybrid=False, wait_secs=wait_secs, first=first)
        for c in cars:
            c["interior"] = tag
            c["leather_ok"] = True   # server-verified leather/leather-like
        return cars

    browser = await _start_browser()
    try:
        # One tab per query (share the cookie jar), all four running concurrently.
        tabs = [await browser.get("about:blank", new_tab=(i > 0)) for i in range(len(queries))]
        worker_out = await asyncio.gather(
            *[_run(tabs[i], qi, tg, le, first=(i == 0))
              for i, (qi, tg, le) in enumerate(queries)])
    finally:
        await browser.stop()

    results, seen = [], set()
    for wr in worker_out:
        for rec in wr:
            vin = rec.get("vin", "")
            if vin and vin in seen:
                continue
            if vin:
                seen.add(vin)
            results.append(rec)
    return results


def scrape_carvana(zip_code="90012", year_min=2022,
                   price_min=20000, price_max=40000, miles_max=50000,
                   only_hybrid=True, wait_secs=6):
    """Search Carvana per-model (headless), reusing one browser session."""
    return asyncio.run(_scrape_carvana_async(
        zip_code, year_min, price_min, price_max, miles_max,
        only_hybrid, wait_secs))


# ---------------------------------------------------------------------------
# Filtering helpers (used by ad-hoc tooling; scrape.py applies its own filters)
# ---------------------------------------------------------------------------

_FUEL_SUFFIX_RE = re.compile(
    r"\s*(plug.?in\s+hybrid|hybrid|phev|electric|ev|recharge)\s*$", re.I)


def _model_has_any_leather(model_str, cs):
    """True if LEATHER_TRIMS has ANY entry for this model family (Carvana fallback)."""
    m = model_str.lower().strip()
    if m in cs.LEATHER_TRIMS:
        return True
    base = _FUEL_SUFFIX_RE.sub("", m).strip()
    if base in cs.LEATHER_TRIMS:
        return True
    if (base + " hybrid") in cs.LEATHER_TRIMS:
        return True
    if (base + " plug-in hybrid") in cs.LEATHER_TRIMS:
        return True
    return False


def filter_listings(listings, car_search_module, close_misses=False):
    """Apply color/interior/leather rules to browser-scraped listings."""
    cs = car_search_module
    out, misses = [], []
    for c in listings:
        if not cs.is_silver(c.get("color", "")):
            continue
        interior = c.get("interior", "")
        interior_ok = cs.has_acceptable_interior(interior)
        model = c.get("model", "").lower()
        trim = c.get("trim", "").lower()
        if c.get("source") == "carvana":
            leather = _model_has_any_leather(model, cs)
        else:
            leather = cs.has_leather(model, trim)
        if interior_ok and leather:
            out.append(c)
        elif close_misses and leather and not interior_ok:
            c = dict(c)
            c["_close_miss"] = f"black interior ({interior})"
            misses.append(c)
    return out, misses


def to_shortlist_entry(c):
    """Convert a browser_scraper listing dict to car_search.send_ranked() format."""
    miles_k = f"{int(c['miles'] or 0) // 1000}k mi" if c.get("miles") else "? mi"
    return {
        "title": c["title"],
        "price": f"${c['price']:,}" if c.get("price") else "?",
        "miles": miles_k,
        "city": c.get("source", "").title(),
        "url": c["url"],
        "vin": c["vin"],
        "verified": bool(c["vin"] and c["url"]),
        "color": c.get("color", ""),
        "interior": c.get("interior", ""),
        "source": c.get("source", ""),
    }


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "carmax"
    if cmd == "carmax":
        print("Scraping CarMax (hybrid SUVs, 2022+, $20-40k, LA 75mi) headless...")
        rs = scrape_carmax()
        print(f"\nGot {len(rs)} hybrid CarMax listings:")
        for r in rs:
            print(f"  {r['title']} | ${r['price']} | {r['miles']}mi | ext:{r['color']} | "
                  f"int:{r['interior']} | {r['interior_type']} | fuel:{r['fuel']}")
    elif cmd == "carvana":
        print("Scraping Carvana (hybrid SUVs, 2022+, $20-40k) headless...")
        rs = scrape_carvana()
        print(f"\nGot {len(rs)} hybrid Carvana listings:")
        for r in rs:
            print(f"  {r['title']} | ${r['price']} | {r['miles']}mi | ext:{r['color']}")
    else:
        print("Usage: python browser_scraper.py [carmax|carvana]")
