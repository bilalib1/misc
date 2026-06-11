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
import re
import sys

from playwright.async_api import async_playwright
from playwright_stealth import Stealth as _Stealth

import car_search as _cs
from car_search import (
    YEAR_MIN, PRICE_MIN, PRICE_MAX, MILES_MAX,
    is_silver, has_acceptable_interior, has_leather, confirms_leather,
    is_blocked_model,
    MANUFACTURER_MULTIPLIER, trim_score_multiplier,
    search_urls,
    UNVERIFIABLE_SELLERS, SOLD_MARKERS,
)
from browser_scraper import (
    scrape_carmax, scrape_carvana,
    _hide_chromium,
)

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
TOP_N = 10
MIN_MAKES = 4
# Hard deadline for the entire Cars.com phase (seconds). If we hit it, we use
# whatever we have plus the CarMax/Carvana results.
CARS_COM_DEADLINE_SECS = 360   # 6 min ceiling for the whole Cars.com phase
MAX_SEARCH_URLS = 24           # fetch more URLs before hitting the ceiling
NAV_TIMEOUT_MS = 30_000        # 30 s per page (was 20 s; Ford/Santa Fe were timing out)


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
        try:
            await page.goto(paged_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
            await page.wait_for_selector("[data-listing-id]", timeout=20_000)
        except Exception as e:
            if page_num == 1:
                print(f"    (skip: {type(e).__name__})")
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

        # Stop if: no new results, fewer than PAGE_SIZE (last page), or we have everything
        if new_this_page == 0:
            break
        if new_this_page < PAGE_SIZE:
            break
        if total and len(listings) >= total:
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

    # Primary: structured JSON in data-vehicle-details attribute
    details = {}
    raw_details = await card.get_attribute("data-vehicle-details") or ""
    if raw_details:
        try:
            details = json.loads(raw_details)
        except Exception:
            pass

    price      = int(details["price"])   if details.get("price")   else None
    miles      = int(details["mileage"]) if details.get("mileage") else None
    ext_color  = (details.get("exteriorColor") or "").lower()
    vin        = details.get("vin", "")
    seller_zip = str((details.get("seller") or {}).get("zip", "") or "")

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
        "verified": bool(vin),  # VIN from card JSON is sufficient
    }


_CLOUDFLARE_MARKERS = ("just a moment", "checking your browser", "challenge-platform")

# Allowed 3-digit zip prefixes for the greater LA area (~75mi radius).
# Using prefixes rather than a simple numeric range because LA County extends
# into the 935xx block (Palmdale/Lancaster) while the 933xx and 934xx blocks
# in between are Bakersfield/Visalia (too far).
#
# Covers: LA County (900-919), Inland Empire/Riverside (917-925),
#         Orange County (926-928), Ventura County (930-931),
#         Palmdale/Lancaster LA County (935).
# Excludes: 929 (Palm Springs ~100mi), 932 (Central Coast >100mi),
#            933/934 (Bakersfield/Visalia), 936+ (Fresno/Central Valley),
#            940+ (Bay Area/Northern CA), and all non-CA zips.
_LA_AREA_ZIP_PREFIXES = frozenset({
    "900","901","902","903","904","905","906","907","908","909",
    "910","911","912","913","914","915","916","917","918","919",
    "920","921","922","923","924","925","926","927","928",
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


def _select_diverse(listings, top_n=TOP_N, min_makes=MIN_MAKES, max_per_make=2):
    """Return up to top_n listings, best value first, max max_per_make per brand.

    Greedy pass respects the per-make cap. If the result still doesn't cover
    min_makes distinct makes, swap out the worst-value car to pull in the
    best-scoring car from each missing make.
    """
    # Higher score = better; sort descending so index 0 is the best car
    ranked = sorted(listings, key=_score, reverse=True)

    make_counts: dict = {}
    top = []
    remainder = []
    for lst in ranked:
        m = _make(lst)
        if make_counts.get(m, 0) < max_per_make and len(top) < top_n:
            top.append(lst)
            make_counts[m] = make_counts.get(m, 0) + 1
        else:
            remainder.append(lst)

    # Diversity boost: if we still fall short of min_makes, swap in best from missing makes
    makes_in_top = {_make(lst) for lst in top}
    for lst in remainder:
        if len(makes_in_top) >= min_makes:
            break
        m = _make(lst)
        if m not in makes_in_top:
            top.sort(key=_score, reverse=True)
            top.pop()   # drop the last = lowest-scoring car
            top.append(lst)
            make_counts[m] = make_counts.get(m, 0) + 1
            makes_in_top.add(m)

    top.sort(key=_score, reverse=True)
    return top


# ---------------------------------------------------------------------------
# CarMax / Carvana → scrape.py listing format
# ---------------------------------------------------------------------------

def _ingest_browser_sources():
    """Run CarMax + Carvana sync scrapers and return listings in scrape.py format."""
    print("[scrape] CarMax …")
    cm = scrape_carmax(zip_code="90012", radius=75,
                       year_min=YEAR_MIN, price_min=PRICE_MIN,
                       price_max=PRICE_MAX, miles_max=MILES_MAX,
                       wait_secs=6)
    print(f"[scrape]   {len(cm)} raw CarMax")

    print("[scrape] Carvana …")
    cv = scrape_carvana(zip_code="90012",
                        year_min=YEAR_MIN, price_min=PRICE_MIN,
                        price_max=PRICE_MAX, miles_max=MILES_MAX,
                        wait_secs=6)
    print(f"[scrape]   {len(cv)} raw Carvana")

    out = []
    for c in cm + cv:
        color = c.get("color", "")
        if not is_silver(color):
            continue
        interior = c.get("interior", "")
        if not has_acceptable_interior(interior):
            continue

        # Re-parse model/trim from the listing title — the title is the most
        # reliable source across all providers. Carvana's LD+JSON trim field is
        # broken: the regex that extracts it returns "Hybrid" (the fuel-type word
        # in the model name) instead of the actual trim level. Parsing from the
        # full title string ("2024 Toyota RAV4 Hybrid XLE Premium") gives us the
        # correct trim.
        title = c.get("title", "")
        model_parsed, trim_parsed = _parse_model_trim(title)
        model = model_parsed or c.get("model", "").lower()
        trim  = trim_parsed.lower() if trim_parsed else c.get("trim", "").lower()

        if _cs.is_blocked_model(model):
            continue

        source = c.get("source", "")

        # CarMax LD+JSON provides `interior_type` — use confirms_leather() first
        # as it is ground truth from the listing itself.
        interior_type = c.get("interior_type", "")
        leather_result = confirms_leather(interior_type)
        if leather_result is False:
            continue   # explicit "Cloth Seats" — hard reject
        if leather_result is None:
            # No seat-material text: require a confirmed leather trim by spec.
            # Applied uniformly to all sources — no model-level fallback.
            # Listings with unidentifiable or cloth trims are skipped; it is
            # better to miss a few cars than to send cloth interiors.
            if not has_leather(model, trim):
                continue
        # leather_result is True → confirmed leather from listing text

        miles = int(c.get("miles") or 0)
        price = int(c.get("price") or 0)
        if price and not (PRICE_MIN <= price <= PRICE_MAX):
            continue
        if miles and miles > MILES_MAX:
            continue
        out.append({
            "title": c["title"],
            "url": c["url"],
            "price": price,
            "price_text": f"${price:,}",
            "miles": miles,
            "dealer": source.title(),   # "Carmax" / "Carvana"
            "city": source.title(),
            "ext_color": color,
            "interior": interior,
            "vin": c.get("vin", ""),
            "verified": bool(c.get("vin") and c.get("url")),
            "source": source,
        })
    print(f"[scrape]   {len(out)} CarMax+Carvana after filters")
    return out


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

async def run(dry_run=False, out_file=None, browser_listings=None):
    import time as _time
    browser_listings = browser_listings or []
    all_urls = list(search_urls())
    # Prioritise the highest-value models; cap total to avoid runaway runtimes
    urls = all_urls[:MAX_SEARCH_URLS]
    print(f"[scrape] {len(urls)}/{len(all_urls)} Cars.com URLs (capped at {MAX_SEARCH_URLS})")

    deadline = _time.time() + CARS_COM_DEADLINE_SECS

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,  # Cloudflare/Akamai block headless
            args=["--disable-blink-features=AutomationControlled"],
        )
        _hide_chromium()
        ctx = await browser.new_context(
            user_agent=_UA,
            viewport={"width": 1280, "height": 800},
            locale="en-US",
        )
        page = await ctx.new_page()
        await _Stealth().apply_stealth_async(page)

        # -- Step 1: collect raw listings --
        raw, seen = [], set()
        for i, url in enumerate(urls, 1):
            if _time.time() > deadline:
                print(f"[scrape] deadline hit after {i-1} URLs — moving on")
                break
            print(f"  [{i}/{len(urls)}] {url[url.find('models'):url.find('models')+30] or url[:60]}...")
            for lst in await _fetch_search_page(page, url):
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
            model, trim = _parse_model_trim(lst["title"])
            if not model:
                continue   # unrecognised model — can't confirm leather, reject
            if is_blocked_model(model):
                continue
            if not has_leather(model, trim):
                continue
            candidates.append(lst)
        print(f"[scrape] {len(candidates)} after basic filters")

        # -- Step 3: detail pages — only for listings missing VIN from card data.
        # Cards with VIN already have ext_color from data-vehicle-details; detail pages
        # are Cloudflare-blocked for Cars.com anyway, so skip them when not needed.
        needs_detail = [lst for lst in candidates if not lst.get("vin")]
        has_card_vin = [lst for lst in candidates if lst.get("vin")]
        print(f"[scrape] {len(has_card_vin)} have VIN from card, {len(needs_detail)} need detail fetch")
        for i, lst in enumerate(needs_detail, 1):
            if _time.time() > deadline:
                print(f"[scrape] deadline hit during detail phase — skipping remaining")
                break
            print(f"  detail [{i}/{len(needs_detail)}] {lst['title'][:60]}")
            await _fetch_detail(page, lst)
            if lst.get("gone"):
                print("    -> sold (detail page)")
                continue
            if lst["ext_color"] and not is_silver(lst["ext_color"]):
                lst["color_fail"] = True
            if lst["interior"] and not has_acceptable_interior(lst["interior"]):
                lst["interior_fail"] = True
            leather_result = confirms_leather(lst.get("interior", ""))
            if leather_result is False:
                lst["leather_fail"] = True

        # Interior check for card-VIN listings (interior is empty — pass through;
        # trim-spec leather check already applied in step 2)
        for lst in has_card_vin:
            if lst["interior"] and not has_acceptable_interior(lst["interior"]):
                lst["interior_fail"] = True

        finalists = [
            lst for lst in candidates
            if not lst.get("gone")
            and not lst.get("color_fail")
            and not lst.get("interior_fail")
            and not lst.get("leather_fail")
        ]
        print(f"[scrape] {len(finalists)} finalists after detail checks")

        await browser.close()

    verified = [lst for lst in finalists if lst.get("verified")]
    print(f"[scrape] {len(verified)} Cars.com verified / {len(finalists) - len(verified)} dropped")

    # -- Step 5: merge CarMax + Carvana (already verified from live pages) --
    seen_vins = {lst["vin"] for lst in verified if lst.get("vin")}
    for blst in browser_listings:
        vin = blst.get("vin", "")
        if vin and vin in seen_vins:
            continue   # deduplicate
        seen_vins.add(vin)
        verified.append(blst)
    print(f"[scrape] {len(verified)} total after merging CarMax+Carvana")

    # -- Step 6: split into two price buckets, top 5 each --
    under30 = [l for l in verified if (l.get("price") or 0) <  30_000]
    over30  = [l for l in verified if (l.get("price") or 0) >= 30_000]
    top_under = _select_diverse(under30, top_n=5, min_makes=3, max_per_make=2)
    top_over  = _select_diverse(over30,  top_n=5, min_makes=3, max_per_make=2)
    top = top_under + top_over
    print(f"[scrape] {len(top_under)} under $30k / {len(top_over)} $30-40k")

    # -- Step 7: send / output --
    def _brief(lst, i):
        miles_str = f"{lst['miles'] // 1000}k mi" if lst.get("miles") else "? mi"
        price_str = lst.get("price_text") or f"${lst['price']:,}"
        color = lst.get("ext_color", "")
        color_part = f" | {color.title()}" if color else ""
        title = lst["title"].replace("Used ", "").replace("Certified ", "")
        return f'{i}. {title} — {price_str} | {miles_str}{color_part} — <a href="{lst["url"]}">view</a>'

    def _build_msg(top_under, top_over):
        lines = []
        if top_under:
            lines.append("Under $30k:")
            lines += [_brief(lst, i) for i, lst in enumerate(top_under, 1)]
        if top_over:
            if top_under:
                lines.append("")
            lines.append("$30–40k:")
            lines += [_brief(lst, i) for i, lst in enumerate(top_over, 1)]
        return "\n".join(lines)

    if out_file:
        rows = [{"title": l["title"], "price": l.get("price_text",""), "miles": f"{l['miles']//1000}k mi",
                 "url": l["url"], "vin": l.get("vin",""), "verified": True} for l in top]
        with open(out_file, "w") as f:
            json.dump(rows, f, indent=2)
        print(f"[scrape] wrote {len(rows)} listings → {out_file}")
    elif dry_run:
        print(f"\nDry run:")
        print(_build_msg(top_under, top_over))
    else:
        from config import telegram_conf
        import requests, html as _html
        tok, chat = telegram_conf()
        msg = _build_msg(top_under, top_over)
        r = requests.get(
            f"https://api.telegram.org/bot{tok}/sendMessage",
            params={"chat_id": chat, "text": msg, "parse_mode": "HTML",
                    "disable_web_page_preview": "true"},
            timeout=30,
        )
        r.raise_for_status()
        print(f"[scrape] sent {len(top)} listings to Telegram")


def main():
    dry_run = "--dry-run" in sys.argv
    out_file = None
    if "--out" in sys.argv:
        idx = sys.argv.index("--out")
        out_file = sys.argv[idx + 1]
    # Run sync scrapers before the asyncio event loop starts
    browser_listings = _ingest_browser_sources()
    asyncio.run(run(dry_run=dry_run, out_file=out_file,
                    browser_listings=browser_listings))


if __name__ == "__main__":
    main()
