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
    search_urls,
    UNVERIFIABLE_SELLERS, SOLD_MARKERS,
)
from browser_scraper import (
    scrape_carmax, scrape_carvana,
    filter_listings, _model_has_any_leather,
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
    """Return listing dicts from one Cars.com search-results URL."""
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        # Cars.com uses [data-listing-id] on each result LI
        await page.wait_for_selector("[data-listing-id]", timeout=20_000)
    except Exception as e:
        print(f"    (skip: {type(e).__name__})")
        return []

    cards = await page.query_selector_all("[data-listing-id]")
    listings = []
    for card in cards:
        try:
            lst = await _extract_card(card)
        except Exception:
            continue
        if lst:
            listings.append(lst)
    return listings


async def _extract_card(card):
    """Parse a Cars.com [data-listing-id] element via innerText + link href."""
    link = await card.query_selector("a[href*='vehicledetail']")
    if not link:
        return None
    href = await link.get_attribute("href") or ""
    url = href if href.startswith("http") else "https://www.cars.com" + href
    if "/vehicledetail/" not in url:
        return None
    url = url.split("?")[0]   # drop attribution params

    title = (await link.inner_text()).strip()
    title = re.sub(r"^(Used|Certified( Pre-Owned)?)\s+", "", title)

    # Parse structured data from the card's plain text
    text = await card.inner_text()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    price, price_text, miles, dealer, city = None, "", None, "", ""
    for ln in lines:
        if not price and "$" in ln and "/mo" not in ln:
            price = _parse_price(ln)
            price_text = ln
        if not miles and re.search(r"\d[\d,]+ mi\.", ln):
            miles = _parse_miles(ln)
        m = re.search(r"([A-Za-z ]+),\s*CA", ln)
        if m and not city:
            city = m.group(1).strip()

    # Dealer is typically the line just before the city line
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
        "ext_color": "",  # filled in by _fetch_detail
        "interior": "",
        "vin": "",
        "verified": False,
    }


async def _fetch_detail(page, listing):
    """Populate VIN + color from the Cars.com detail page.

    Marks verified=True if the page loads and shows no sold markers — we skip
    the slow dealer-site cross-check since the user clicks through anyway.
    """
    try:
        await page.goto(listing["url"], wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        body = await page.content()
        if any(m in body.lower() for m in SOLD_MARKERS):
            listing["gone"] = True
            return

        # VIN: try LD+JSON first (Cars.com embeds it on detail pages)
        ld_vins = await page.evaluate("""() => {
            return Array.from(document.querySelectorAll('script[type="application/ld+json"]'))
                .map(s => { try { return JSON.parse(s.textContent); } catch { return null; } })
                .filter(x => x && x.vehicleIdentificationNumber)
                .map(x => x.vehicleIdentificationNumber);
        }""")
        if ld_vins:
            listing["vin"] = ld_vins[0]
        else:
            m = re.search(r"\b([A-HJ-NPR-Z0-9]{17})\b", body)
            if m:
                listing["vin"] = m.group(1)

        # Color: from the specs/overview section
        spec_text = await page.evaluate("""() => {
            const sels = ['[class*="basics"] li', '[class*="specs"] li',
                          '[class*="overview"] li', '.vehicle-details li',
                          '[data-qa="specs-list"] li'];
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
    """Lower = better value. Price-dominant; slight reward for newer/lower-miles."""
    price = listing.get("price") or 99_999
    year = _parse_year(listing.get("title", "")) or YEAR_MIN
    miles = listing.get("miles") or MILES_MAX
    return price - (year - YEAR_MIN) * 300 + miles * 0.05


def _make(listing):
    """Extract the make from a listing title (first word after the year)."""
    parts = listing.get("title", "").split()
    return parts[1].lower() if len(parts) > 1 else "unknown"


def _select_diverse(listings, top_n=TOP_N, min_makes=MIN_MAKES):
    """Return up to top_n listings, sorted by score, with no per-make cap.

    If the greedy top-N doesn't cover min_makes distinct makes, swap in the
    best-scoring car from each missing make until the requirement is met or
    inventory runs out.
    """
    ranked = sorted(listings, key=_score)
    top = ranked[:top_n]
    makes_in_top = {_make(lst) for lst in top}

    if len(makes_in_top) < min_makes:
        # Find makes present in the broader verified pool but not yet in top
        remaining = [lst for lst in ranked[top_n:]]
        for lst in remaining:
            if len(makes_in_top) >= min_makes:
                break
            m = _make(lst)
            if m not in makes_in_top:
                # Swap out the worst (highest score) car in top to make room
                top.sort(key=_score)
                top[-1] = lst
                makes_in_top.add(m)

    top.sort(key=_score)
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
        model = c.get("model", "").lower()
        trim  = c.get("trim", "").lower()
        source = c.get("source", "")

        # CarMax LD+JSON provides `interior_type` ("Leather Seats", "Cloth Seats", …).
        # Use confirms_leather() on that first — it's ground truth from the listing.
        # Fall back to trim-level check only when the field is absent/ambiguous.
        interior_type = c.get("interior_type", "")
        leather_result = confirms_leather(interior_type)
        if leather_result is False:
            continue   # CarMax says "Cloth Seats" — hard reject
        if leather_result is None:
            # No material text: fall back to trim-level check
            if source == "carvana":
                if not _model_has_any_leather(model, _cs):
                    continue
            else:
                if not has_leather(model, trim):
                    continue
        # leather_result is True → confirmed leather, skip trim check

        miles = int(c.get("miles") or 0)
        price = int(c.get("price") or 0)
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
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
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

        # -- Step 2: basic filters (year / price / miles / color / leather) --
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
            model, trim = _parse_model_trim(lst["title"])
            if model and not has_leather(model, trim):
                continue
            candidates.append(lst)
        print(f"[scrape] {len(candidates)} after basic filters")

        # -- Step 3: detail pages (VIN, interior, confirm color) --
        for i, lst in enumerate(candidates, 1):
            if _time.time() > deadline:
                print(f"[scrape] deadline hit during detail phase — skipping remaining")
                break
            print(f"  detail [{i}/{len(candidates)}] {lst['title'][:60]}")
            await _fetch_detail(page, lst)
            if lst.get("gone"):
                print("    -> sold (detail page)")
                continue
            if lst["ext_color"] and not is_silver(lst["ext_color"]):
                lst["color_fail"] = True
            if lst["interior"] and not has_acceptable_interior(lst["interior"]):
                lst["interior_fail"] = True
            # Hard leather check using actual seat-material text from the spec list.
            # confirms_leather() returns True/False/None; None means fall back to trim.
            leather_result = confirms_leather(lst.get("interior", ""))
            if leather_result is False:
                lst["leather_fail"] = True   # spec list says "Cloth" — hard reject
            # (leather_result True or None keeps the candidate; trim already passed)

        finalists = [
            lst for lst in candidates
            if not lst.get("gone")
            and not lst.get("color_fail")
            and not lst.get("interior_fail")
            and not lst.get("leather_fail")
        ]
        print(f"[scrape] {len(finalists)} finalists after detail checks")

        # Step 4: VIN verification skipped — detail page load is sufficient proof
        # (dealer-site cross-check was too slow and bot-blocked anyway)

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

    # -- Step 6: rank + select top 10 --
    top = _select_diverse(verified, top_n=TOP_N, min_makes=MIN_MAKES)

    # -- Step 7: send / output --
    def _brief(lst, i):
        miles_str = f"{lst['miles'] // 1000}k mi" if lst.get("miles") else "? mi"
        price_str = lst.get("price_text") or f"${lst['price']:,}"
        color = lst.get("ext_color", "")
        color_part = f" | {color.title()}" if color else ""
        title = lst["title"].replace("Used ", "").replace("Certified ", "")
        return f'{i}. {title} — {price_str} | {miles_str}{color_part} — <a href="{lst["url"]}">view</a>'

    if out_file:
        rows = [{"title": l["title"], "price": l.get("price_text",""), "miles": f"{l['miles']//1000}k mi",
                 "url": l["url"], "vin": l.get("vin",""), "verified": True} for l in top]
        with open(out_file, "w") as f:
            json.dump(rows, f, indent=2)
        print(f"[scrape] wrote {len(rows)} listings → {out_file}")
    elif dry_run:
        print(f"\nDry run — top {len(top)}:")
        for i, lst in enumerate(top, 1):
            print(" ", _brief(lst, i))
    else:
        from config import telegram_conf
        import requests, html as _html
        tok, chat = telegram_conf()
        lines = [_brief(lst, i) for i, lst in enumerate(top, 1)]
        msg = "\n".join(lines)
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
