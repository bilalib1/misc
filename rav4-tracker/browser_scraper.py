"""
Playwright-stealth scraper for CarMax and Carvana.

Both sites use Akamai/Cloudflare bot protection that blocks plain requests.
Playwright with stealth patches passes all fingerprint checks because it runs a
real Chromium with automation signals patched out. HEADLESS MODE IS BLOCKED by
Akamai — CarMax (and Carvana as a precaution) require headless=False.

Both sites embed structured car data in LD+JSON <script> blocks, so we navigate,
wait for the SPA to hydrate, extract the blocks, and close the browser.

CarMax  — full schema: VIN, price, year, make, model, trim, exterior color,
           interior color + type, mileage, fuel type, stock number → listing URL.
Carvana — VIN, price, year, make, model, trim (from description), exterior
           color, mileage, listing URL (in offers.url).

CDP BRIDGE (highest trust): if you start Chrome with --remote-debugging-port=9222,
set_cdp_url("http://localhost:9222") before scraping and Playwright will drive
your REAL Chrome — real cookies, real fingerprint, undetectable.

    /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome \\
        --remote-debugging-port=9222 \\
        --user-data-dir="$HOME/Library/Application Support/Google/Chrome"

Usage:
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

import base64
import json
import re
import subprocess
import time

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

def _hide_chromium():
    """Hide the Chromium window on macOS (Cmd+H equivalent).

    The browser keeps running and rendering — pages load, JS executes, LD+JSON
    is extracted — but no window appears in the foreground or Mission Control.
    Called once right after browser.launch().
    """
    try:
        subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to set visible of every process'
             ' whose name is "Chromium" to false'],
            capture_output=True, timeout=3,
        )
    except Exception:
        pass


_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
)
_STEALTH = Stealth()
_CDP_URL = None  # set via set_cdp_url() to drive your real Chrome


def set_cdp_url(url="http://localhost:9222"):
    """
    Tell browser_scraper to connect to your real Chrome via DevTools Protocol
    instead of launching Playwright's Chromium.

    Start Chrome first:
        /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome \\
            --remote-debugging-port=9222 \\
            --user-data-dir="$HOME/Library/Application Support/Google/Chrome"

    Then call set_cdp_url() once before scraping. Your real browser (with all
    its cookies, fingerprint, and login sessions) is used for every request.
    """
    global _CDP_URL
    _CDP_URL = url


def _chrome_cookies_for(domain):
    """Return cookies from your running Chrome for the given domain, or {}."""
    try:
        from pycookiecheat import chrome_cookies
        return chrome_cookies(f"https://{domain}")
    except Exception:
        return {}


def _make_page(p):
    """
    Return (browser, context, page), applying stealth and injecting Chrome
    cookies when available. Prefers the user's real Chrome via CDP if set.
    """
    if _CDP_URL:
        # Drive the user's real Chrome — the highest-trust path
        browser = p.chromium.connect_over_cdp(_CDP_URL)
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        page = ctx.new_page()
        # Stealth still applied for completeness, even on real Chrome
        _STEALTH.apply_stealth_sync(page)
        return browser, ctx, page

    browser = p.chromium.launch(
        headless=False,  # Akamai blocks headless — headed is required
        args=["--disable-blink-features=AutomationControlled"],
    )
    _hide_chromium()
    ctx = browser.new_context(
        user_agent=_UA,
        viewport={"width": 1280, "height": 800},
        locale="en-US",
    )
    page = ctx.new_page()
    _STEALTH.apply_stealth_sync(page)
    return browser, ctx, page


def _dismiss_cookie_dialogs(page):
    """Click through any cookie consent dialog if present. Returns True if one was dismissed.

    Call AFTER the initial page-load sleep so the dialog has time to render.
    Uses page.click() with a short timeout per candidate — fast no-op when absent.
    """
    candidates = [
        'button:has-text("Accept All")',
        'button:has-text("Accept all")',
        'button:has-text("I Accept")',
        'button:has-text("Accept")',
        'button:has-text("Agree")',
        'button:has-text("Allow All")',
        'button:has-text("Allow all cookies")',
        'button:has-text("Continue")',
        '#onetrust-accept-btn-handler',
        '[data-qa="accept-cookies"]',
        '.cookie-consent-accept',
    ]
    for sel in candidates:
        try:
            page.click(sel, timeout=600)
            time.sleep(0.3)
            print(f"    (dismissed cookie dialog: {sel!r})")
            return True
        except Exception:
            continue
    return False


def _read_result_count(page):
    """Return the total result count shown on the page, or None if not found.

    Matches patterns like '88 Cars', '163 Results', '3,247 vehicles'.
    """
    try:
        text = page.inner_text("body")
        m = re.search(r'([\d,]+)\s+(results?|vehicles?|cars?|listings?)', text[:4000], re.I)
        if m:
            return int(m.group(1).replace(",", ""))
    except Exception:
        pass
    return None


def _inject_cookies(ctx, domain):
    """Pull cookies from the user's real Chrome and inject them into Playwright."""
    cookies = _chrome_cookies_for(domain)
    if not cookies:
        return
    pw_cookies = [
        {"name": k, "value": v, "domain": f".{domain}", "path": "/"}
        for k, v in cookies.items()
    ]
    try:
        ctx.add_cookies(pw_cookies)
    except Exception:
        pass


def _extract_ld_json(page):
    return page.evaluate(
        """() => {
        const scripts = document.querySelectorAll('script[type="application/ld+json"]');
        return Array.from(scripts).map(s => {
            try { return JSON.parse(s.textContent); } catch { return null; }
        }).filter(x => x !== null);
    }"""
    )


def _scroll_until_stable(page, count_js, max_scrolls=25, pause=2.5, stability_rounds=2):
    """Scroll until the count returned by count_js stops growing for stability_rounds rounds.

    count_js is a JS expression like "() => document.querySelectorAll(...).length".
    Stops early once fully loaded; hard-caps at max_scrolls to avoid loops.
    Returns the final count.
    """
    prev = 0
    stable = 0
    for i in range(max_scrolls):
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(pause)
        cur = page.evaluate(count_js)
        if cur == prev:
            stable += 1
            if stable >= stability_rounds:
                print(f"    (scroll stable at {cur} after {i+1} scrolls)")
                break
        else:
            stable = 0
        prev = cur
    return prev


def _get_carmax_stock_urls(page):
    links = page.evaluate(
        """() => {
        const links = document.querySelectorAll('a[href*="/car/"]');
        const seen = new Set();
        const result = {};
        for (const a of links) {
            const m = a.href.match(/carmax\\.com\\/car\\/(\\d+)/);
            if (m && !seen.has(m[1])) {
                seen.add(m[1]);
                result[m[1]] = a.href;
            }
        }
        return result;
    }"""
    )
    return links or {}


# Fuel types we consider "hybrid / EV" for post-fetch filtering.
# CarMax LD+JSON reports: "Hybrid", "Electric", "Gas", "Diesel", "Flex".
# Hybrid = has a combustion engine + electric motor. Pure EVs (Tesla etc.) are excluded.
_HYBRID_FUELS = {"hybrid", "plug-in hybrid", "phev"}
# Also match Lexus/BMW h-suffix designators: 350h, 250h, 450h, 30e, 40e, etc.
_HYBRID_TITLE_RE = re.compile(r"\b(hybrid|phev|plug.?in|\d{2,3}[eh])\b", re.I)

# Carvana URL slugs that differ from the Cars.com model slug convention.
# Used when the direct _ → - conversion produces an unrecognised Carvana slug
# (detected when the page shows the full ~45k catalog instead of model results).
CARVANA_SLUG_OVERRIDES = {
    "lexus-nx-350h":       "lexus-nx",     # Carvana uses just lexus-nx for all NX trims
    "lexus-ux-250h":       "lexus-ux",     # same pattern
    "mazda-cx-50-hybrid":  "mazda-cx-50",  # no fuel-type suffix in Carvana slug
    "volvo-xc60-recharge": "volvo-xc60",   # Recharge is a Volvo sub-brand, not a Carvana slug
}


def _carvana_trim_from_text(name: str, desc: str) -> str:
    """Extract the trim level from Carvana's name or description.

    Carvana LD+JSON name is often just "2024 Toyota RAV4 Hybrid" (no trim).
    The description is more complete: "Used 2024 Toyota RAV4 Hybrid XLE Premium
    with 19,739 miles."  This function grabs whatever comes after the fuel-type
    designator (Hybrid / PHEV / Recharge / 350h / 250h …) and before "with N miles".
    Returns empty string if no trim is identifiable.
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
            # Reject noise: "with", digits-only, single letters
            if t and not re.match(r"^(with\b|\d)", t, re.I) and len(t) > 1:
                return t
    return ""


def _is_hybrid(listing):
    fuel = (listing.get("fuel") or "").lower()
    if fuel in _HYBRID_FUELS:
        return True
    # Carvana doesn't expose fuel in LD+JSON — fall back to title
    title = (listing.get("title") or "").lower()
    return bool(_HYBRID_TITLE_RE.search(title))


def scrape_carmax(zip_code="90012", radius=75, year_min=2022,
                  price_min=20000, price_max=40000, miles_max=50000,
                  only_hybrid=True, wait_secs=8):
    """
    Search CarMax for SUV crossover hybrids. Returns structured listings.

    CarMax's LD+JSON includes: VIN, price, year, make, model, trim, exterior
    color, interior color + type, mileage, and fuel type — all the fields
    needed by car_search.py's filter rules.

    `only_hybrid=True` (default) post-filters to hybrid/EV/PHEV only, since
    CarMax's URL fuel filter is imprecise (comma-separated values don't always
    take). Falls back to title-keyword check for cars without a fuel field.
    """
    # CarMax array-style params are the most reliable
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
    with sync_playwright() as p:
        browser, ctx, page = _make_page(p)
        if not _CDP_URL:
            # Inject real Chrome cookies for carmax.com if we have any
            _inject_cookies(ctx, "carmax.com")

        try:
            page.goto(url, timeout=30_000)
        except Exception:
            pass

        try:
            page.wait_for_selector('[href*="/car/"]', timeout=20_000)
        except Exception:
            pass
        time.sleep(wait_secs)
        _dismiss_cookie_dialogs(page)   # called after sleep so dialog has rendered

        total = _read_result_count(page)

        # Scroll until no new car cards appear (lazy-loaded SPA)
        n_links = _scroll_until_stable(
            page,
            '() => document.querySelectorAll(\'a[href*="/car/"]\').length',
        )
        if total and n_links < total:
            print(f"[carmax] WARNING: {n_links} car links loaded / {total} total — some missed")
        else:
            print(f"[carmax] {n_links} car links loaded" + (f" / {total} total" if total else ""))

        ld_blocks = _extract_ld_json(page)
        stock_urls = _get_carmax_stock_urls(page)
        car_blocks = [b for b in ld_blocks if isinstance(b, dict) and b.get("@type") == "Car"]
        print(f"[carmax] {len(car_blocks)} @type=Car LD+JSON blocks")

        for block in ld_blocks:
            if not isinstance(block, dict) or block.get("@type") != "Car":
                continue
            try:
                odometer = block.get("mileageFromOdometer") or {}
                miles = (
                    odometer.get("value") if isinstance(odometer, dict) else odometer
                )
                img = block.get("image", "")
                stock_match = re.search(r"/assets/(\d+)/", img)
                stock_num = stock_match.group(1) if stock_match else None
                listing_url = stock_urls.get(stock_num) or (
                    f"https://www.carmax.com/car/{stock_num}" if stock_num else ""
                )

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

        browser.close()
    return results


def _carvana_model_slug(cars_com_slug):
    """Convert a Cars.com model slug to a Carvana path segment, applying known overrides."""
    base = cars_com_slug.replace("_", "-")
    return CARVANA_SLUG_OVERRIDES.get(base, base)


def scrape_carvana(zip_code="90012", year_min=2022,
                   price_min=20000, price_max=40000, miles_max=50000,
                   only_hybrid=True, wait_secs=6):
    """Search Carvana per-model (one URL per model in MODELS), reusing one browser session.

    The old single broad search returned thousands of results and _scroll_until_stable
    only loaded the first page-worth. Per-model URLs keep each result set small
    (typically 0–50 per model) and guarantee we see everything.

    Carvana LD+JSON includes: VIN, price, year, make, model, mileage, exterior color,
    listing URL. No interior color or fuel type in the schema — only_hybrid=True
    post-filters by title keyword.
    """
    from car_search import MODELS

    results = []
    seen_vins: set = set()

    with sync_playwright() as p:
        browser, ctx, page = _make_page(p)
        if not _CDP_URL:
            _inject_cookies(ctx, "carvana.com")

        first = True
        for _make, model_slug in MODELS:
            slug = _carvana_model_slug(model_slug)
            url = (f"https://www.carvana.com/cars/{slug}"
                   f"?year={year_min}-2026&price={price_min}-{price_max}&mileage=0-{miles_max}")
            try:
                page.goto(url, timeout=30_000)
            except Exception:
                pass

            time.sleep(wait_secs if first else 3)
            first = False
            _dismiss_cookie_dialogs(page)

            total = _read_result_count(page)

            # If total is suspiciously large (>2000), Carvana didn't recognise the
            # model slug and is showing the full catalog — skip to avoid random cars.
            if total and total > 2000:
                print(f"[carvana/{slug}] SKIP — {total} total suggests unrecognised slug (full catalog)")
                continue

            n_blocks = _scroll_until_stable(
                page,
                '() => document.querySelectorAll(\'script[type="application/ld+json"]\').length',
                max_scrolls=15, pause=2.0,
            )
            ld_blocks = _extract_ld_json(page)
            car_blocks = [b for b in ld_blocks if isinstance(b, dict) and b.get("@type") in ("Car", "Vehicle")]

            if total and len(car_blocks) < total:
                print(f"[carvana/{slug}] WARNING: {len(car_blocks)} loaded / {total} total — scrolled more but capped")
            else:
                print(f"[carvana/{slug}] {len(car_blocks)} listings" + (f" / {total} total" if total else ""))

            # Parse and accumulate results for this model
            for block in ld_blocks:
                if not isinstance(block, dict) or block.get("@type") not in ("Car", "Vehicle"):
                    continue
                try:
                    vin = block.get("vehicleIdentificationNumber", "")
                    if vin in seen_vins:
                        continue
                    seen_vins.add(vin)

                    miles = block.get("mileageFromOdometer")
                    if isinstance(miles, dict):
                        miles = miles.get("value")

                    name = block.get("name", "")
                    desc = block.get("description", "")
                    # Extract trim from name/description; append to title so
                    # _parse_model_trim in scrape.py can confirm leather by trim spec.
                    trim = _carvana_trim_from_text(name, desc)
                    full_title = f"{name} {trim}".strip() if trim and trim.lower() not in name.lower() else name

                    listing_url = (block.get("offers") or {}).get("url", "")
                    if not listing_url:
                        sku = block.get("sku")
                        listing_url = f"https://www.carvana.com/vehicle/{sku}" if sku else ""

                    rec = {
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
                    }
                    if only_hybrid and not _is_hybrid(rec):
                        continue
                    results.append(rec)
                except Exception as e:
                    print(f"[carvana] parse error: {e}")

        browser.close()
    return results


_FUEL_SUFFIX_RE = re.compile(
    r"\s*(plug.?in\s+hybrid|hybrid|phev|electric|ev|recharge)\s*$", re.I
)


def _leather_model_key(model, trim):
    """
    Normalize a (model, trim) pair for has_leather() lookup.

    Carvana LD+JSON embeds the fuel type in the model string (e.g. "Tucson
    Plug-in Hybrid"). Try the full string first, then fall back to stripping
    the suffix — "Tucson Plug-in Hybrid" → "Tucson" — then reattach the
    canonical suffix ("tucson hybrid") so the LEATHER_TRIMS key matches.
    """
    m = model.lower().strip()
    t = trim.lower().strip()
    return m, t


def _model_has_any_leather(model_str, cs):
    """
    Return True if LEATHER_TRIMS has ANY entry for this model family.

    Used for Carvana, where the trim field is unreliable (parsed from a
    short description, often just "Hybrid" or "Plug-in"). If the model is
    known to offer leather in some trims, we pass it through and let the
    user confirm the exact trim on the listing page.
    """
    m = model_str.lower().strip()
    # Direct match
    if m in cs.LEATHER_TRIMS:
        return True
    # Try stripping fuel suffix ("Tucson Plug-in Hybrid" → "Tucson" → "tucson hybrid")
    base = _FUEL_SUFFIX_RE.sub("", m).strip()
    if base in cs.LEATHER_TRIMS:
        return True
    if (base + " hybrid") in cs.LEATHER_TRIMS:
        return True
    if (base + " plug-in hybrid") in cs.LEATHER_TRIMS:
        return True
    return False


def filter_listings(listings, car_search_module, close_misses=False):
    """
    Apply filter rules to browser-scraped listings.

    CarMax LD+JSON includes the actual trim level, so we run the full
    trim-level leather check. Carvana's trim is parsed from a short
    description and is unreliable — we use a model-level check there
    (does this model offer leather in ANY trim?) and let the user verify
    the exact trim on the listing page.

    close_misses=True also returns listings that pass color but fail
    interior — useful to surface "almost" cars (e.g. black-interior RAV4).
    """
    cs = car_search_module
    out = []
    misses = []

    for c in listings:
        if not cs.is_silver(c.get("color", "")):
            continue  # wrong color family entirely — skip

        interior = c.get("interior", "")
        interior_ok = cs.has_acceptable_interior(interior)

        model = c.get("model", "").lower()
        trim = c.get("trim", "").lower()

        if c.get("source") == "carvana":
            # Carvana: trim field is unreliable — model-level leather check
            leather = _model_has_any_leather(model, cs)
        else:
            # CarMax: trim is accurate — use full trim-level check
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
        "verified": bool(c["vin"] and c["url"]),  # from live page = verified
        "color": c.get("color", ""),
        "interior": c.get("interior", ""),
        "source": c.get("source", ""),
    }


if __name__ == "__main__":
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else "carmax"

    if cmd == "cdp":
        # Test connecting to your real Chrome
        # First run: open -a "Google Chrome" --args --remote-debugging-port=9222
        set_cdp_url()
        print("Testing CDP connection to your real Chrome...")
        results = scrape_carmax()
        print(f"Got {len(results)} listings via CDP")
    elif cmd == "carmax":
        print("Scraping CarMax (hybrid SUVs, 2022+, $20-40k, LA 75mi)...")
        results = scrape_carmax()
        print(f"\nGot {len(results)} hybrid CarMax listings:")
        for r in results:
            print(f"  {r['title']} | ${r['price']:,} | {r['miles']}mi | ext:{r['color']} | int:{r['interior']} | {r['interior_type']} | fuel:{r['fuel']}")
    elif cmd == "carvana":
        print("Scraping Carvana (hybrid SUVs, 2022+, $20-40k)...")
        results = scrape_carvana()
        print(f"\nGot {len(results)} hybrid Carvana listings:")
        for r in results:
            print(f"  {r['title']} | ${r['price']:,} | {r['miles']}mi | ext:{r['color']}")
    else:
        print("Usage: python browser_scraper.py [carmax|carvana|cdp]")
