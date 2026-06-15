"""Silver hybrid shortlist — Cars.com + CarMax + Carvana combined.

Sources:
  • Cars.com  — all models in car_search.MODELS (Toyota, Honda, Mitsubishi,
                Lexus, Ford, Hyundai, Mazda, Jeep …) filtered by silver/gray
                color bucket at the URL level; VIN-verified on dealer site.
  • CarMax    — nationwide hybrid/PHEV SUVs via Playwright stealth (Akamai
                bypass); LD+JSON gives full color/interior/trim in one pass.
  • Carvana   — nationwide hybrid/PHEV SUVs via Playwright stealth (Cloudflare
                bypass); same LD+JSON extraction.

All sources are filtered by the same car_search rules (color, interior,
leather-by-trim) and ranked by value score. Top 10 sent to Telegram as
a numbered bare-bones list: make/model/trim, price, miles, link.

Usage:
  python scrape.py                # full run → send to Telegram
  python scrape.py --dry-run      # fetch + filter + verify, print only
  python scrape.py --out FILE     # write verified JSON to FILE, don't send
"""
import asyncio
import json
import os
import re
import subprocess
import sys
import time as _t

from playwright.async_api import async_playwright
from playwright_stealth import Stealth as _Stealth

import car_search as _cs
from car_search import (
    YEAR_MIN, PRICE_MIN, PRICE_MAX, MILES_MAX,
    is_silver, has_acceptable_interior, has_leather, confirms_leather,
    is_blocked_model, is_blocked_make,
    MANUFACTURER_MULTIPLIER, trim_score_multiplier,
    search_urls,
    UNVERIFIABLE_SELLERS, SOLD_MARKERS,
)
from browser_scraper import scrape_carmax, scrape_carvana

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
TOP_N = 10
MIN_MAKES = 4
# Hard deadline for the entire Cars.com phase (seconds). If we hit it, we use
# whatever we have plus the CarMax/Carvana results.
CARS_COM_DEADLINE_SECS = 600   # 10 min ceiling (interior detail-fetch added time)
MAX_SEARCH_URLS = 40           # cover ALL models×colors (incl. Outlander PHEV — buyer's front-runner)
NAV_TIMEOUT_MS = 30_000        # 30 s per page (was 20 s; Ford/Santa Fe were timing out)
CARS_COM_CONCURRENCY = 4       # parallel Cars.com worker pages (search + detail fetches)


# ---------------------------------------------------------------------------
# Invisible CDP engine for Cars.com
# ---------------------------------------------------------------------------

def _ensure_cdp_engine(cdp_url):
    """Start the invisible --headless=new CDP engine if it isn't already up.

    Cars.com's Cloudflare hard-blocks Playwright's own Chromium AND a fresh-profile
    headless Chrome (both get "Just a moment" / "Access denied"). Only a REAL Chrome
    with the user's copied cookies — driven over CDP — passes. The launcher runs it
    `--headless=new`, so NO window ever appears. Best-effort: on failure we fall back
    to whatever `connect_over_cdp` / headless-launch can do.
    """
    import urllib.request
    m = re.search(r":(\d+)", cdp_url or "")
    port = m.group(1) if m else "9334"
    ping = f"http://localhost:{port}/json/version"
    try:
        urllib.request.urlopen(ping, timeout=1)
        return True   # already running
    except Exception:
        pass
    script = os.path.abspath(os.path.join(
        os.path.dirname(__file__), "..", "src", "browser_interaction",
        "launch_chrome_with_cdp.sh"))
    if not os.path.exists(script):
        print(f"[scrape] CDP launcher not found at {script}; Cars.com may be blocked")
        return False
    print(f"[scrape] starting invisible headless CDP engine on :{port} …")
    try:
        subprocess.run(["bash", script, port], timeout=90,
                       capture_output=True, text=True)
    except Exception as e:
        print(f"[scrape] engine launch error: {type(e).__name__}: {e}")
    for _ in range(20):
        try:
            urllib.request.urlopen(ping, timeout=1)
            print(f"[scrape] CDP engine up on :{port}")
            return True
        except Exception:
            _t.sleep(0.5)
    print(f"[scrape] CDP engine did not come up on :{port}; falling back")
    return False


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_price(text):
    m = re.search(r"\$?([\d,]+)", text or "")
    return int(m.group(1).replace(",", "")) if m else None


def _parse_miles(text):
    m = re.search(r"([\d,]+)", (text or "").replace(",", ""))
    return int(m.group(1)) if m else None


def _parse_year(title):
    m = re.match(r"(\d{4})", (title or "").strip())
    return int(m.group(1)) if m else None


def _parse_model_trim(title):
    """Return (model_key, trim_string) from a listing title."""
    t = title.lower()
    # Ford Escape: the fuel word may sit mid-title, be "PHEV", or be absent
    # ("Escape SE Hybrid", "Escape Titanium Plug-In Hybrid", "Escape PHEV",
    # "Escape Titanium"). Cars.com's fuel filter already guarantees every result
    # is a hybrid/PHEV, so treat ANY Escape as such; the trim (Titanium/Platinum =
    # leather) is whatever's left after stripping the fuel designators.
    if "escape" in t:
        is_phev = bool(re.search(r"plug-?in\s+hybrid|phev", t))
        model = "escape plug-in hybrid" if is_phev else "escape hybrid"
        after = t.split("escape", 1)[1]
        trim = re.sub(r"\b(plug-?in\s+hybrid|hybrid|phev)\b", "", after).strip()
        return model, trim
    model_keys = [
        "grand cherokee 4xe", "wrangler 4xe",
        "outlander phev", "xc60 recharge",
        "crosstrek hybrid", "santa fe hybrid", "tucson hybrid",
        "escape plug-in hybrid", "escape hybrid",
        "cr-v hybrid", "rav4 hybrid",
        "cx-50 hybrid", "nx 350h", "ux 250h",
        "murano hybrid", "rogue",
        "venza", "xc40",
    ]
    for key in model_keys:
        if key in t:
            idx = t.find(key) + len(key)
            return key, title[idx:].strip()
    return None, ""


# ---------------------------------------------------------------------------
# Cars.com scraping
# ---------------------------------------------------------------------------

async def _fetch_search_page(page, url):
    """Return listing dicts from one Cars.com search-results URL, paginating if needed."""
    PAGE_SIZE = 50   # Cars.com default; if a full page loads, there may be more
    seen_urls: set = set()
    listings = []
    page_num = 1

    while True:
        paged_url = url if page_num == 1 else f"{url}&page={page_num}"
        # Retry the FIRST page a few times: under concurrency Cloudflare/the engine
        # occasionally times out a load, and silently dropping the whole URL was the
        # Cars.com "regression". A later-page timeout just means no more results.
        loaded = False
        max_tries = 3 if page_num == 1 else 1
        for attempt in range(1, max_tries + 1):
            try:
                await page.goto(paged_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
                await page.wait_for_selector("[data-listing-id]", timeout=25_000)
                loaded = True
                break
            except Exception as e:
                if attempt < max_tries:
                    await page.wait_for_timeout(2500 * attempt)   # back off, then retry
                elif page_num == 1:
                    print(f"    (skip after {max_tries} tries: {type(e).__name__})")
        if not loaded:
            break

        # On page 1, read the total result count to know if we need more pages
        if page_num == 1:
            body_text = await page.inner_text("body")
            m = re.search(r"([\d,]+)\s+results?", body_text[:4000], re.I)
            total = int(m.group(1).replace(",", "")) if m else None
            if total and total > PAGE_SIZE:
                print(f"    ({total} total results — will paginate)")

        cards = await page.query_selector_all("[data-listing-id]")
        new_this_page = 0
        for card in cards:
            try:
                lst = await _extract_card(card)
            except Exception:
                continue
            if lst and lst["url"] not in seen_urls:
                seen_urls.add(lst["url"])
                listings.append(lst)
                new_this_page += 1

        # Stop when a page yields no NEW listings (the previous "< PAGE_SIZE = last
        # page" heuristic broke on the filter-first results, where ~half the cards are
        # sponsored/nationwide with no data-vehicle-details, so new_this_page is always
        # well under PAGE_SIZE). Walk pages until empty, capped for safety.
        if new_this_page == 0:
            break
        if total and len(listings) >= total:
            break
        if page_num >= 8:
            break
        page_num += 1

    if page_num > 1:
        print(f"    (fetched {page_num} pages → {len(listings)} listings)")
    return listings


async def _extract_card(card):
    """Parse a Cars.com [data-listing-id] element.

    data-vehicle-details is a JSON blob on every card with exteriorColor, VIN,
    price, mileage, trim, make, model, year — far more reliable than scraping
    innerText or hitting Cloudflare-blocked detail pages.
    """
    link = await card.query_selector("a[href*='vehicledetail']")
    if not link:
        return None
    href = await link.get_attribute("href") or ""
    url = href if href.startswith("http") else "https://www.cars.com" + href
    if "/vehicledetail/" not in url:
        return None
    url = url.split("?")[0]

    title = (await link.inner_text()).strip()
    title = re.sub(r"^(Used|Certified( Pre-Owned)?)\s+", "", title)

    # Primary: structured JSON in data-vehicle-details attribute.
    # Cards WITHOUT this attribute are the page's "similar / shop nationwide"
    # modules — they carry no seller zip, so out-of-region cars (e.g. NJ, Phoenix)
    # leak past the LA-area filter. Require the structured blob and skip the rest.
    raw_details = await card.get_attribute("data-vehicle-details") or ""
    if not raw_details:
        return None
    try:
        details = json.loads(raw_details)
    except Exception:
        return None

    # Build the title from the structured JSON (always present). The visible link
    # text lazy-loads and is often EMPTY on the filter-first results page, which was
    # dropping real cars; year/make/model/trim in the JSON is reliable.
    j_title = " ".join(str(details.get(k) or "").strip()
                       for k in ("year", "make", "model", "trim")).strip()
    j_title = re.sub(r"\s+", " ", j_title)
    if j_title:
        title = j_title

    price      = int(details["price"])   if details.get("price")   else None
    miles      = int(details["mileage"]) if details.get("mileage") else None
    ext_color  = (details.get("exteriorColor") or "").lower()
    vin        = details.get("vin", "")
    seller_zip = str((details.get("seller") or {}).get("zip", "") or "")
    pt = details.get("primaryThumbnail")
    image = pt if isinstance(pt, str) else ((pt or {}).get("src") or (pt or {}).get("url") or "") if isinstance(pt, dict) else ""

    # Fallback: parse innerText for price/miles/city when card JSON is missing them
    text  = await card.inner_text()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    price_text = f"${price:,}" if price else ""
    dealer, city = "", ""

    for ln in lines:
        if not price and "$" in ln and "/mo" not in ln:
            price = _parse_price(ln)
            price_text = ln
        if not miles and re.search(r"\d[\d,]+ mi\.", ln):
            miles = _parse_miles(ln)
        m = re.search(r"([A-Za-z ]+),\s*CA", ln)
        if m and not city:
            city = m.group(1).strip()

    for i, ln in enumerate(lines):
        if re.search(r"[A-Za-z ]+,\s*CA", ln) and i > 0:
            candidate = lines[i - 1]
            if not re.search(r"^\d|Check Avail|Est\.", candidate):
                dealer = candidate
            break

    return {
        "title": title,
        "url": url,
        "price": price,
        "price_text": price_text or (f"${price:,}" if price else ""),
        "miles": miles,
        "dealer": dealer,
        "city": city,
        "ext_color": ext_color,
        "interior": "",
        "vin": vin,
        "seller_zip": seller_zip,
        "image": image,
        "verified": bool(vin),  # VIN from card JSON is sufficient
    }


_CLOUDFLARE_MARKERS = ("just a moment", "checking your browser", "challenge-platform")

# Allowed 3-digit zip prefixes for the greater LA area (~75mi radius).
# Using prefixes rather than a simple numeric range because LA County extends
# into the 935xx block (Palmdale/Lancaster) while the 933xx and 934xx blocks
# in between are Bakersfield/Visalia (too far).
#
# Covers: LA County (900-918), Inland Empire/San Bernardino/Riverside (923-925),
#         Orange County (926-928), Ventura County (930-931),
#         Palmdale/Lancaster LA County (935).
# Excludes: 919/920/921 (SAN DIEGO County, ~115mi — these wrongly leaked in
#            National-City/Chula-Vista cars on 2026-06-12), 922 (Coachella/Palm
#            Springs ~115mi), 929 (Palm Springs), 932 (Central Coast),
#            933/934 (Bakersfield/Visalia), 936+ (Central Valley),
#            940+ (Bay Area/Northern CA), and all non-CA zips.
_LA_AREA_ZIP_PREFIXES = frozenset({
    "900","901","902","903","904","905","906","907","908","909",
    "910","911","912","913","914","915","916","917","918",
    "923","924","925","926","927","928",
    "930","931",
    "935",  # Palmdale / Lancaster (LA County, ~60mi from downtown)
})


def _is_la_area_zip(zip_str: str) -> bool:
    """Return True if the seller zip is within greater LA (~75mi).
    Unknown zips pass through so we never silently drop unlocatable listings.
    """
    if not zip_str:
        return True
    z = zip_str.strip()
    if len(z) < 3:
        return True
    return z[:3] in _LA_AREA_ZIP_PREFIXES


async def _fetch_detail(page, listing):
    """Attempt to populate interior color + sold-check from the Cars.com detail page.

    VIN and exterior color are now pulled from data-vehicle-details on the search card,
    so this is only needed for interior color and sold-marker detection.
    Skips silently when Cloudflare blocks the page.
    """
    try:
        await page.goto(listing["url"], wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        body = await page.content()
        # Cloudflare challenge — no car data available, skip without modifying listing
        if any(m in body.lower() for m in _CLOUDFLARE_MARKERS):
            listing["detail_error"] = "cloudflare"
            return
        if any(m in body.lower() for m in SOLD_MARKERS):
            listing["gone"] = True
            return

        # VIN + colors: try LD+JSON first (Cars.com embeds full schema on detail pages)
        ld_data = await page.evaluate("""() => {
            return Array.from(document.querySelectorAll('script[type="application/ld+json"]'))
                .map(s => { try { return JSON.parse(s.textContent); } catch { return null; } })
                .filter(x => x && (x.vehicleIdentificationNumber || x.color || x.vehicleInteriorColor));
        }""")
        for block in (ld_data or []):
            if block.get("vehicleIdentificationNumber") and not listing["vin"]:
                listing["vin"] = block["vehicleIdentificationNumber"]
            if block.get("color") and not listing["ext_color"]:
                listing["ext_color"] = block["color"].lower()
            if block.get("vehicleInteriorColor") and not listing["interior"]:
                listing["interior"] = block["vehicleInteriorColor"].lower()

        if not listing["vin"]:
            m = re.search(r"\b([A-HJ-NPR-Z0-9]{17})\b", body)
            if m:
                listing["vin"] = m.group(1)

        # Color: from the specs/overview section (multiple selector attempts)
        spec_text = await page.evaluate("""() => {
            const sels = [
                '[class*="basics"] li', '[class*="specs"] li',
                '[class*="overview"] li', '.vehicle-details li',
                '[data-qa="specs-list"] li',
                '[data-testid*="spec"] li', '[data-testid*="feature"] li',
                '.vehicle-specs li', '.basic-section li',
                '[class*="VehicleOverview"] li', '[class*="vehicle-overview"] li',
            ];
            for (const sel of sels) {
                const items = document.querySelectorAll(sel);
                if (items.length) return Array.from(items).map(i => i.innerText).join('|');
            }
            return '';
        }""")
        for part in spec_text.split("|"):
            pl = part.lower()
            if "exterior" in pl and not listing["ext_color"]:
                listing["ext_color"] = pl.split(":")[-1].strip()
            if "interior" in pl and not listing["interior"]:
                listing["interior"] = pl.split(":")[-1].strip()

        # Current Cars.com renders basics as SUFFIX-labeled lines, e.g.
        # "Silver Sky Metallic exterior color" / "Black interior color" — the
        # selectors above don't catch that, so parse the body text directly.
        body_text = await page.evaluate("() => document.body.innerText")
        if not listing["interior"]:
            m = re.search(r"([^\n]+?)\s+interior color", body_text, re.I)
            if m:
                listing["interior"] = m.group(1).strip().lower()
        if not listing["ext_color"]:
            m = re.search(r"([^\n]+?)\s+exterior color", body_text, re.I)
            if m:
                listing["ext_color"] = m.group(1).strip().lower()

        # HTML regex fallback for color if still missing after LD+JSON + CSS
        if not listing["ext_color"]:
            m = re.search(r'exterior[^<"]{0,30}color[^:"]{0,10}[:"]\s*"?([A-Za-z/ ]+?)(?:"|<|,|\n)', body, re.I)
            if m:
                listing["ext_color"] = m.group(1).strip().lower()
        if not listing["interior"]:
            m = re.search(r'interior[^<"]{0,30}color[^:"]{0,10}[:"]\s*"?([A-Za-z/ ]+?)(?:"|<|,|\n)', body, re.I)
            if m:
                listing["interior"] = m.group(1).strip().lower()

        # Mark as verified — page loaded and car isn't sold
        listing["verified"] = True

    except Exception as e:
        listing["detail_error"] = str(e)


# ---------------------------------------------------------------------------
# VIN verification — must confirm on dealer's OWN site
# ---------------------------------------------------------------------------

async def _verify_vin(page, listing):
    vin = listing.get("vin", "")
    dealer = (listing.get("dealer") or "").lower()
    if not vin:
        return

    if any(u in dealer for u in UNVERIFIABLE_SELLERS):
        listing["unverifiable"] = True
        return

    # 1. Try the dealer's own site link from the detail page
    dealer_site = listing.get("dealer_site", "")
    if dealer_site:
        try:
            await page.goto(dealer_site, wait_until="domcontentloaded", timeout=30_000)
            body = await page.content()
            if vin.upper() in body.upper():
                listing["verified"] = True
                return
        except Exception:
            pass

    # 2. Try a VIN-specific search on the dealer's domain (if we know it)
    if dealer_site:
        domain_m = re.search(r"https?://([^/]+)", dealer_site)
        if domain_m:
            domain = domain_m.group(1)
            search_url = f"https://{domain}/searchused.aspx?searchtext={vin}"
            alt_urls = [
                f"https://{domain}/used-inventory/index.htm?search={vin}",
                f"https://{domain}/used/listings/?q={vin}",
                f"https://{domain}/inventory/used/?vin={vin}",
            ]
            for candidate in [search_url] + alt_urls:
                try:
                    resp = await page.goto(
                        candidate, wait_until="domcontentloaded", timeout=20_000
                    )
                    if resp and resp.ok:
                        body = await page.content()
                        if vin.upper() in body.upper():
                            listing["verified"] = True
                            listing["verified_url"] = candidate
                            return
                except Exception:
                    continue

    # 3. DuckDuckGo VIN search as last resort
    try:
        await page.goto(
            f"https://duckduckgo.com/?q=%22{vin}%22&ia=web",
            wait_until="domcontentloaded",
            timeout=20_000,
        )
        body = await page.content()
        links = re.findall(r'href="(https?://[^"]+)"', body)
        # If a non-Cars.com/non-aggregator link contains the VIN, treat as verified
        for link in links:
            if "cars.com" in link or "autotrader" in link or "carmax" in link:
                continue
            if vin.upper() in link.upper():
                listing["verified"] = True
                listing["verified_url"] = link
                return
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Scoring / ranking / diversity selection
# ---------------------------------------------------------------------------

def _score(listing):
    """Higher = better quality/value.

    Base quality: year (dominant) + mileage (secondary) + price (tiebreaker).
    Multiplied by manufacturer reliability tier × trim level.

    Year pts  : 100 per year above 2019  → 2021=200, 2022=300 … 2026=700
    Mile pts  : up to 100 pts; fewer miles = more pts
    Price pts : up to 10 pts; lower price within the bucket = more pts

    Manufacturer multiplier: Toyota/Lexus 1.10×  …  Jeep 0.90×  (see MANUFACTURER_MULTIPLIER)
    Trim multiplier        : base leather 0.95×  …  top trim 1.10×  (see TRIM_RANKS)
    """
    year  = _parse_year(listing.get("title", "")) or YEAR_MIN
    miles = listing.get("miles") or MILES_MAX
    price = listing.get("price") or PRICE_MAX
    model, trim = _parse_model_trim(listing.get("title", ""))
    make  = _make(listing)

    year_pts  = (year - 2019) * 100
    mile_pts  = (MILES_MAX - miles) / 500
    price_pts = (PRICE_MAX - price) / 2000

    base = year_pts + mile_pts + price_pts

    mfr_mult  = MANUFACTURER_MULTIPLIER.get(make, 1.0)
    trim_mult = trim_score_multiplier(model, trim) if model else 1.0

    return base * mfr_mult * trim_mult


def _make(listing):
    """Extract the make from a listing title (first word after the year)."""
    parts = listing.get("title", "").split()
    return parts[1].lower() if len(parts) > 1 else "unknown"


def _model_id(listing):
    """make + model name from the title (year-stripped) for the hard de-dup cap.
    Works for unrecognized models too, e.g. '2024 Dodge Hornet GT' -> 'dodge hornet'."""
    parts = listing.get("title", "").split()
    return " ".join(parts[1:3]).lower() if len(parts) >= 3 else " ".join(parts[1:2]).lower()


def _select_incremental(listings, top_n=5, brand_penalty=0.12, max_per_model=2):
    """Greedy selection with incremental brand + model diversity penalties.

    Each slot is filled by picking the highest *effective* score from the
    remaining pool, where effective score = raw_score × (1 − total_penalty).

    Penalty per pick:
      • +brand_penalty   for each previously selected car of the same brand
      • +brand_penalty   additionally for same brand AND same model  (2× total)

    Example with brand_penalty=0.12:
      First Toyota:          no penalty   → effective = raw
      Second Toyota (diff model):  −12%   → effective = raw × 0.88
      Second Toyota RAV4:   −12% brand −12% model = −24%  → effective = raw × 0.76
      Third Toyota:         −24% brand + any model penalty

    On top of the soft penalty there is a HARD cap of `max_per_model` per model
    (title-based `_model_id`), so a bucket can't become 3+ identical cars.
    """
    selected = []
    remaining = list(listings)
    brand_counts: dict = {}
    model_counts: dict = {}
    id_counts: dict = {}

    for _ in range(top_n):
        if not remaining:
            break
        best_car, best_eff = None, float("-inf")
        for car in remaining:
            if id_counts.get(_model_id(car), 0) >= max_per_model:
                continue   # hard cap: already have max_per_model of this exact model
            make          = _make(car)
            model, _trim  = _parse_model_trim(car.get("title", ""))
            n_brand       = brand_counts.get(make, 0)
            n_model       = model_counts.get((make, model), 0) if model else 0
            penalty       = n_brand * brand_penalty + n_model * brand_penalty
            effective     = _score(car) * max(0.0, 1.0 - penalty)
            if effective > best_eff:
                best_eff, best_car = effective, car
        if best_car is None:
            break
        selected.append(best_car)
        remaining.remove(best_car)
        make         = _make(best_car)
        model, _trim = _parse_model_trim(best_car.get("title", ""))
        brand_counts[make] = brand_counts.get(make, 0) + 1
        if model:
            model_counts[(make, model)] = model_counts.get((make, model), 0) + 1
        id_counts[_model_id(best_car)] = id_counts.get(_model_id(best_car), 0) + 1

    return selected


# ---------------------------------------------------------------------------
# CarMax / Carvana → scrape.py listing format
# ---------------------------------------------------------------------------

def _safe_scrape(label, fn):
    """Run a browser scraper; on ANY failure (e.g. a zendriver websocket drop)
    log it and return [] so one flaky source never aborts the whole pipeline."""
    try:
        return fn()
    except Exception as e:
        print(f"[scrape]   {label} FAILED ({type(e).__name__}: {e}); continuing without it")
        return []


def _ingest_browser_sources():
    """Run CarMax + Carvana sync scrapers and return listings in scrape.py format.
    Each source is isolated: a crash in one yields [] and the other still runs."""
    print("[scrape] CarMax …")
    cm = _safe_scrape("CarMax", lambda: scrape_carmax(
        zip_code="90012", radius=75, year_min=YEAR_MIN, price_min=PRICE_MIN,
        price_max=PRICE_MAX, miles_max=MILES_MAX, wait_secs=6))
    print(f"[scrape]   {len(cm)} raw CarMax")

    print("[scrape] Carvana …")
    cv = _safe_scrape("Carvana", lambda: scrape_carvana(
        zip_code="90012", year_min=YEAR_MIN, price_min=PRICE_MIN,
        price_max=PRICE_MAX, miles_max=MILES_MAX, wait_secs=6))
    print(f"[scrape]   {len(cv)} raw Carvana")

    out = []
    for c in cm + cv:
        color = c.get("color", "")
        if not is_silver(color):   # catches dark grays Carvana's "Gray" filter includes
            continue

        title = c.get("title", "")
        # Make = first word after the year in the title (else the source's make field).
        parts = title.split()
        make = (parts[1] if len(parts) > 1 else c.get("make", "")).lower()
        if _cs.is_blocked_make(make):   # Jeep / Kia
            continue

        source = c.get("source", "")

        # Carvana cross-make results are leather-verified SERVER-SIDE (cvnaFeatures),
        # so we trust that and skip the local trim gate — this is what lets ALL makes
        # through. CarMax has no such filter, so verify its leather from listing text.
        if not c.get("leather_ok"):
            model_parsed, trim_parsed = _parse_model_trim(title)
            model = model_parsed or c.get("model", "").lower()
            trim  = trim_parsed.lower() if trim_parsed else c.get("trim", "").lower()
            if _cs.is_blocked_model(model):
                continue
            lr = confirms_leather(c.get("interior_type", ""))
            if lr is False:
                continue   # explicit "Cloth Seats"
            if lr is None and not has_leather(model, trim):
                continue

        # Carvana's /cars/filters endpoint honors only the cvnaid blob, ignoring the
        # year/price/mileage URL query — so re-enforce them locally (a 2019 Lexus UX
        # and Mercedes GLC leaked through before this guard).
        year = _parse_year(title)
        if year and year < YEAR_MIN:
            continue
        miles = int(c.get("miles") or 0)
        price = int(c.get("price") or 0)
        if price and not (PRICE_MIN <= price <= PRICE_MAX):
            continue
        if miles and miles > MILES_MAX:
            continue
        out.append({
            "title": title,
            "url": c["url"],
            "price": price,
            "price_text": f"${price:,}",
            "miles": miles,
            "dealer": source.title(),   # "Carmax" / "Carvana"
            "city": source.title(),
            "ext_color": color,
            "interior": c.get("interior", ""),   # "" (non-black) or "Black", tagged at scrape time
            "vin": c.get("vin", ""),
            "verified": bool(c.get("vin") and c.get("url")),
            "source": source,
        })
    print(f"[scrape]   {len(out)} CarMax+Carvana after filters")
    return out


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

async def run(dry_run=False, out_file=None, no_browser=False):
    import time as _time
    all_urls = list(search_urls())
    # Prioritise the highest-value models; cap total to avoid runaway runtimes
    urls = all_urls[:MAX_SEARCH_URLS]
    print(f"[scrape] {len(urls)}/{len(all_urls)} Cars.com URLs (capped at {MAX_SEARCH_URLS})")

    deadline = _time.time() + CARS_COM_DEADLINE_SECS

    # Kick off CarMax + Carvana NOW so they scrape CONCURRENTLY with Cars.com.
    # Each source fans out to its own headless workers (see browser_scraper); this
    # runs in a worker thread because those scrapers drive their own event loops.
    if no_browser:
        print("[scrape] --no-browser: Cars.com only")

    CDP_URL = os.environ.get("SCRAPE_CDP_URL", "http://localhost:9334")
    # Ensure the invisible real-Chrome engine is up (Cars.com needs it; see helper).
    await asyncio.to_thread(_ensure_cdp_engine, CDP_URL)
    async with async_playwright() as pw:
        connected = False
        try:
            # Drive the already-running invisible engine — nothing renders locally.
            browser = await pw.chromium.connect_over_cdp(CDP_URL)
            ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
            connected = True
            print(f"[scrape] driving invisible CDP engine at {CDP_URL}")
        except Exception as e:
            # No engine up — launch headless (Cars.com renders fine headless, stays invisible).
            print(f"[scrape] no CDP engine ({type(e).__name__}); launching headless Chromium")
            browser = await pw.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            ctx = await browser.new_context(
                user_agent=_UA,
                viewport={"width": 1280, "height": 800},
                locale="en-US",
            )
        # Pool of N stealth pages → search + detail fetches run concurrently.
        pages = []
        for _ in range(CARS_COM_CONCURRENCY):
            p = await ctx.new_page()
            await _Stealth().apply_stealth_async(p)
            pages.append(p)

        # -- Step 1: collect raw listings (N workers, round-robin over URLs) --
        async def _search_worker(page, url_chunk, start_delay):
            await asyncio.sleep(start_delay)   # desync workers so all N don't hit Cloudflare at once
            out = []
            for url in url_chunk:
                if _time.time() > deadline:
                    break
                slug = url[url.find('models'):url.find('models') + 30]
                print(f"  search: {slug or url[:50]}...")
                out.extend(await _fetch_search_page(page, url))
            return out

        url_chunks = [urls[i::CARS_COM_CONCURRENCY] for i in range(CARS_COM_CONCURRENCY)]
        worker_out = await asyncio.gather(
            *[_search_worker(pages[i], url_chunks[i], i * 1.5)
              for i in range(CARS_COM_CONCURRENCY)])
        raw, seen = [], set()
        for chunk in worker_out:
            for lst in chunk:
                if lst["url"] not in seen:
                    seen.add(lst["url"])
                    raw.append(lst)
        print(f"[scrape] {len(raw)} unique raw listings")

        # -- Step 2: basic filters (year / price / miles / color / model / leather) --
        # ext_color is now populated from data-vehicle-details JSON on the card,
        # so the color filter is reliable here rather than deferred to detail pages.
        candidates = []
        for lst in raw:
            year = _parse_year(lst["title"])
            if not year or year < YEAR_MIN:
                continue
            if lst["price"] and not (PRICE_MIN <= lst["price"] <= PRICE_MAX):
                continue
            if lst["miles"] and lst["miles"] > MILES_MAX:
                continue
            if lst["ext_color"] and not is_silver(lst["ext_color"]):
                continue
            if not _is_la_area_zip(lst.get("seller_zip", "")):
                print(f"    (skip out-of-area zip {lst.get('seller_zip')} — {lst['title'][:50]})")
                continue
            parts = lst["title"].split()
            make = parts[1].lower() if len(parts) > 1 else ""
            if is_blocked_make(make):   # Jeep / Kia
                continue
            model, trim = _parse_model_trim(lst["title"])
            if not model:
                continue   # unrecognised model — can't confirm leather, reject
            if is_blocked_model(model):
                continue
            if not has_leather(model, trim):
                continue
            candidates.append(lst)
        print(f"[scrape] {len(candidates)} after basic filters")

        # -- Step 3: detail pages for ALL candidates — the card JSON has VIN +
        # exterior color but NOT interior color, and the buyer's "non-black
        # interior" rule is a HARD requirement. Detail pages load fine via the
        # CDP engine, so confirm interior (+ sold-check) on every candidate.
        print(f"[scrape] confirming interior + availability on {len(candidates)} candidates")

        async def _detail_worker(page, cand_chunk):
            for lst in cand_chunk:
                if _time.time() > deadline:
                    break
                await _fetch_detail(page, lst)
                if lst.get("gone"):
                    print(f"    -> sold: {lst['title'][:50]}")
                    continue
                if lst["ext_color"] and not is_silver(lst["ext_color"]):
                    lst["color_fail"] = True
                # NOTE: black interiors are NOT dropped — they're kept and surfaced in
                # the message's "relaxed interior" section (Step 6 partitions by interior).
                if confirms_leather(lst.get("interior", "")) is False:
                    lst["leather_fail"] = True

        cand_chunks = [candidates[i::CARS_COM_CONCURRENCY] for i in range(CARS_COM_CONCURRENCY)]
        await asyncio.gather(
            *[_detail_worker(pages[i], cand_chunks[i]) for i in range(CARS_COM_CONCURRENCY)])

        finalists = [
            lst for lst in candidates
            if not lst.get("gone")
            and not lst.get("color_fail")
            and not lst.get("leather_fail")
        ]
        print(f"[scrape] {len(finalists)} finalists after detail checks")

        for p in pages:
            try:
                await p.close()
            except Exception:
                pass
        if not connected:
            await browser.close()   # never close a CDP-connected engine (would kill it)

    verified = [lst for lst in finalists if lst.get("verified")]
    print(f"[scrape] {len(verified)} Cars.com verified / {len(finalists) - len(verified)} dropped")

    # Run CarMax + Carvana AFTER Cars.com finishes — NOT concurrently. Sharing the
    # machine with the heavy paginated Carvana scrape (Jeep 4xe alone walks ~1,400
    # listings) was starving Cars.com's page loads → Cloudflare timeouts. Cars.com
    # now gets the machine to itself first; total wall-clock is ~unchanged since
    # Carvana is the long pole either way.
    if no_browser:
        browser_listings = []
    else:
        print("[scrape] Cars.com done — now CarMax + Carvana")
        try:
            browser_listings = await asyncio.to_thread(_ingest_browser_sources)
        except Exception as e:
            print(f"[scrape] browser sources failed ({type(e).__name__}); Cars.com only")
            browser_listings = []

    # -- Step 5: merge CarMax + Carvana (already verified from live pages) --
    seen_vins = {lst["vin"] for lst in verified if lst.get("vin")}
    for blst in browser_listings:
        vin = blst.get("vin", "")
        if vin and vin in seen_vins:
            continue   # deduplicate
        seen_vins.add(vin)
        verified.append(blst)
    print(f"[scrape] {len(verified)} total after merging CarMax+Carvana")

    # -- Step 6: 4 buckets = {strict non-black, relaxed black} x {$20-30k, $30-40k},
    # top 5 each by the scoring function. Unknown-interior cars count as non-black.
    strict  = [l for l in verified if has_acceptable_interior(l.get("interior", ""))]
    relaxed = [l for l in verified if not has_acceptable_interior(l.get("interior", ""))]

    def _price_buckets(pool):
        under = [l for l in pool if (l.get("price") or 0) < 30_000]
        over  = [l for l in pool if (l.get("price") or 0) >= 30_000]
        return _select_incremental(under, top_n=5), _select_incremental(over, top_n=5)

    strict_under, strict_over   = _price_buckets(strict)
    relaxed_under, relaxed_over = _price_buckets(relaxed)
    top_strict  = strict_under + strict_over
    top_relaxed = relaxed_under + relaxed_over
    top = top_strict + top_relaxed
    print(f"[scrape] strict {len(strict_under)}+{len(strict_over)} / "
          f"relaxed {len(relaxed_under)}+{len(relaxed_over)} (pools {len(strict)}/{len(relaxed)})")

    # -- Structured log for autonomous spot-checking (images, diversity, anomalies) --
    def _slim(l):
        return {"title": l.get("title"), "price": l.get("price"), "miles": l.get("miles"),
                "ext_color": l.get("ext_color"), "interior": l.get("interior"),
                "city": l.get("city"), "dealer": l.get("dealer"), "seller_zip": l.get("seller_zip"),
                "vin": l.get("vin"), "source": l.get("source", "cars.com"),
                "image": l.get("image", ""), "url": l.get("url")}
    makes = {}
    for l in top:
        makes[_make(l)] = makes.get(_make(l), 0) + 1
    log = {
        "counts": {"verified": len(verified), "strict": len(strict),
                   "relaxed": len(relaxed), "selected": len(top)},
        "make_distribution": makes,
        "selected_strict": [_slim(l) for l in top_strict],
        "selected_relaxed": [_slim(l) for l in top_relaxed],
        "all_verified": [_slim(l) for l in verified],
    }
    with open("/tmp/scrape_log.json", "w") as f:
        json.dump(log, f, indent=2)
    print(f"[scrape] log -> /tmp/scrape_log.json | make distribution: {makes}")

    # -- Step 7: build the two-section message / output --
    def _brief(lst, i):
        miles_str = f"{lst['miles'] // 1000}k mi" if lst.get("miles") else "? mi"
        price_str = lst.get("price_text") or f"${lst['price']:,}"
        color = lst.get("ext_color", "")
        color_part = f" | {color.title()}" if color else ""
        title = lst["title"].replace("Used ", "").replace("Certified ", "")
        return f'{i}. {title} — {price_str} | {miles_str}{color_part} — <a href="{lst["url"]}">view</a>'

    def _section(header, under, over):
        lines = [header]
        lines.append("$20–30k:")
        lines += ([_brief(l, i) for i, l in enumerate(under, 1)] or ["  —"])
        lines.append("$30–40k:")
        lines += ([_brief(l, i) for i, l in enumerate(over, 1)] or ["  —"])
        return lines

    def _build_msg():
        lines = ["<b>Silver/gray leather hybrid/PHEV SUVs, 2021+, &lt;50k mi</b>", ""]
        lines += _section("<b>Strict — non-black interior:</b>", strict_under, strict_over)
        lines.append("")
        lines += _section("<b>Relaxed — black interior also OK:</b>", relaxed_under, relaxed_over)
        return "\n".join(lines)

    if out_file:
        rows = [{"title": l["title"], "price": l.get("price_text", ""),
                 "miles": f"{(l.get('miles') or 0)//1000}k mi", "url": l["url"],
                 "vin": l.get("vin", ""), "verified": True,
                 "section": "relaxed" if l in top_relaxed else "strict"} for l in top]
        with open(out_file, "w") as f:
            json.dump(rows, f, indent=2)
        print(f"[scrape] wrote {len(rows)} listings → {out_file}")
    elif dry_run:
        print("\nDry run:")
        print(_build_msg())
    else:
        from config import telegram_conf
        import requests
        tok, chat = telegram_conf()
        r = requests.get(
            f"https://api.telegram.org/bot{tok}/sendMessage",
            params={"chat_id": chat, "text": _build_msg(), "parse_mode": "HTML",
                    "disable_web_page_preview": "true"},
            timeout=30,
        )
        r.raise_for_status()
        print(f"[scrape] sent {len(top)} listings to Telegram "
              f"({len(top_strict)} strict + {len(top_relaxed)} relaxed)")


def main():
    dry_run = "--dry-run" in sys.argv
    out_file = None
    if "--out" in sys.argv:
        idx = sys.argv.index("--out")
        out_file = sys.argv[idx + 1]
    # Cars.com is the verified main path; --no-browser skips CarMax/Carvana.
    no_browser = "--no-browser" in sys.argv
    asyncio.run(run(dry_run=dry_run, out_file=out_file, no_browser=no_browser))


if __name__ == "__main__":
    main()
