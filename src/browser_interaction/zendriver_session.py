"""Hardened anti-bot scraping, FULLY HEADLESS, via zendriver (bare-CDP, no Playwright).

This is the proven path for Cloudflare/Akamai/DataDome sites — CarMax (Akamai),
Carvana + KBB/Autotrader (Cloudflare) — that the rest of this toolkit's logged-in
`ChromeCDPSession` layer isn't aimed at. It launches its OWN throwaway headless
Chrome (no login needed, no window ever) and drives it over a bare WebSocket CDP
connection.

WHY zendriver and not Playwright: the decisive 2026 anti-bot signal is
automation-PROTOCOL fingerprinting — chiefly the `Runtime.enable` CDP command that
Playwright/Puppeteer issue (the whole reason `patchright` / `rebrowser-patches`
exist). zendriver (a maintained `nodriver` fork) never calls it, so it passes while
staying headless. Headed-vs-headless is NOT the signal — so a headed browser buys
nothing and is banned on macOS (it steals focus/Space). See
plans/browser_interaction.md "Headless strategy" / "Research".

This module centralizes the techniques that grew up in car-sales-scraping
(`browser_scraper.py`, `kbb_scraper.py`) as reusable helpers:
  • start a headless zendriver browser            -> start_browser()
  • detect + clear a Cloudflare interstitial       -> is_blocked() / clear_cloudflare()
  • pin geo/session cookies BEFORE loading         -> set_cookies()
  • read LD+JSON (handles @graph / arrays)         -> read_ld_json() / car_blocks()
  • call a private JSON API from inside the page   -> fetch_json_in_page()
  • sync one-call convenience wrappers             -> scrape_ld_json() / fetch_site_api()

Requires `zendriver` (pip install zendriver); imported lazily so the rest of the
toolkit works without it.
"""
from __future__ import annotations

import asyncio
import json

# Substrings that mark a Cloudflare/Akamai "are you human" interstitial (title+body).
CF_MARKERS = ("just a moment", "checking your browser", "performing security verification",
              "verify you are human", "needs to review the security", "attention required")

# Parse every <script type="ld+json">, drop the ones that don't parse. Returns a
# real array — zendriver hands it back as a Python list via return_by_value.
_LD_JSON_JS = """
Array.from(document.querySelectorAll('script[type="application/ld+json"]'))
  .map(s => { try { return JSON.parse(s.textContent); } catch { return null; } })
  .filter(x => x !== null)
"""


def _zd():
    """Lazy import so importing this module never hard-fails when zendriver is absent."""
    try:
        import zendriver as zd
        return zd
    except ImportError as e:  # pragma: no cover
        raise SystemExit("zendriver is required: pip install zendriver") from e


async def start_browser(headless: bool = True):
    """Start a fully-headless zendriver Chrome (no window, no focus steal)."""
    return await _zd().start(headless=headless)


async def is_blocked(page) -> bool:
    """True if the page is currently showing a Cloudflare/Akamai interstitial."""
    title = (await page.evaluate("document.title", return_by_value=True)) or ""
    body = (await page.evaluate(
        "document.body ? document.body.innerText.slice(0,300) : ''",
        return_by_value=True)) or ""
    blob = f"{title}\n{body}".lower()
    return any(m in blob for m in CF_MARKERS)


async def clear_cloudflare(page, attempts: int = 3) -> bool:
    """If a Cloudflare interstitial is up, solve/wait it out. Returns True if clear.

    Two cases, both handled headless: the common "Just a moment…" JS challenge
    auto-clears on a wait/reload, and the rarer interactive Turnstile checkbox is
    solved by zendriver's `verify_cf()`. We try verify_cf() (short timeout — fail
    fast since the checkbox is rare), then wait, then reload between attempts.
    """
    for _ in range(attempts):
        if not await is_blocked(page):
            return True
        try:
            await page.verify_cf(timeout=4)
        except Exception:
            pass
        await page.sleep(6)
        if not await is_blocked(page):
            return True
        try:
            await page.reload()
        except Exception:
            pass
        await page.sleep(5)
    return not await is_blocked(page)


async def set_cookies(browser, pairs: dict, domain: str, path: str = "/") -> None:
    """Pin cookies (e.g. a location/zip or session) BEFORE loading results.

    Many sites compute server-side output from a cookie — e.g. Carvana keeps the
    shopper's location in CVCurrentZip/City/State and derives each car's shipping
    fee + delivery days from it; pinning it to your area turns "shipped from afar"
    into a clean local/non-local signal. Sets them at the CDP layer; the site reads
    `document.cookie` too, so also writing them via JS on a warm-up page is a sound
    belt-and-suspenders (see car-sales-scraping `_set_carvana_location`).
    """
    net = __import__("zendriver.cdp.network", fromlist=["CookieParam"])
    await browser.cookies.set_all([
        net.CookieParam(name=n, value=str(v), domain=domain, path=path)
        for n, v in pairs.items()
    ])


async def read_ld_json(page, scrolls: int = 0, scroll_pause: float = 2.0) -> list:
    """Return parsed LD+JSON blocks from `page`. For a lazy results grid pass
    scrolls>0 to trigger hydration; 0 for a static detail page."""
    prev = -1
    for _ in range(scrolls):
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.sleep(scroll_pause)
        cur = await page.evaluate(
            "document.querySelectorAll('script[type=\\\"application/ld+json\\\"]').length",
            return_by_value=True) or 0
        if cur == prev:
            break
        prev = cur
    blocks = await page.evaluate(_LD_JSON_JS, return_by_value=True)
    return blocks or []


def car_blocks(ld_blocks: list, types=("Car", "Vehicle")) -> list[dict]:
    """Flatten LD+JSON (handles @graph and arrays) to the @type-matching dicts."""
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


async def fetch_json_in_page(page, url: str) -> dict:
    """Same-origin fetch from inside the (anti-bot-cleared) page — inherits cookies
    + TLS + Origin so a private JSON API that blocks bare requests returns data.
    Returns {"status": int, "body": str} or {"status": 0, "error": str}."""
    js = """
    (async () => {
      try {
        const r = await fetch(%s, {headers: {'accept': 'application/json'}, credentials: 'include'});
        const txt = await r.text();
        return JSON.stringify({status: r.status, body: txt});
      } catch (e) { return JSON.stringify({status: 0, error: String(e)}); }
    })()
    """ % json.dumps(url)
    out = await page.evaluate(js, return_by_value=True, await_promise=True)
    try:
        return json.loads(out)
    except Exception:
        return {"status": 0, "error": "unparseable envelope"}


# ---------------------------------------------------------------------------
# Sync one-call convenience wrappers (match the rest of the toolkit's style)
# ---------------------------------------------------------------------------

async def _scrape_ld_json_async(url, settle, scrolls, scroll_pause, headless, cookies, domain):
    browser = await start_browser(headless=headless)
    try:
        if cookies and domain:
            await set_cookies(browser, cookies, domain)
        page = await browser.get(url)
        await page.sleep(settle)
        await clear_cloudflare(page)
        return await read_ld_json(page, scrolls=scrolls, scroll_pause=scroll_pause)
    finally:
        await browser.stop()


def scrape_ld_json(url: str, settle: float = 6.0, scrolls: int = 8,
                   scroll_pause: float = 2.0, headless: bool = True,
                   cookies: dict | None = None, domain: str | None = None) -> list:
    """Open `url` headless, clear Cloudflare, scroll, return parsed LD+JSON blocks.
    Optionally pin `cookies` on `domain` first (e.g. a location zip)."""
    return asyncio.run(_scrape_ld_json_async(
        url, settle, scrolls, scroll_pause, headless, cookies, domain))


async def _fetch_site_api_async(api_url, warmup_url, settle, headless, cookies, domain):
    browser = await start_browser(headless=headless)
    try:
        if cookies and domain:
            await set_cookies(browser, cookies, domain)
        page = await browser.get(warmup_url)
        await page.sleep(settle)
        await clear_cloudflare(page)
        return await fetch_json_in_page(page, api_url)
    finally:
        await browser.stop()


def fetch_site_api(api_url: str, warmup_url: str, settle: float = 6.0,
                   headless: bool = True, cookies: dict | None = None,
                   domain: str | None = None) -> dict:
    """Load `warmup_url` (same origin) to clear Cloudflare + set cookies, then call
    `api_url` via an in-page same-origin fetch. Returns the {status, body} envelope.
    This is the KBB/Autotrader LSC pattern: a bare request to the API is blocked, but
    an in-page fetch after the SRP loads inherits the cleared context and succeeds."""
    return asyncio.run(_fetch_site_api_async(
        api_url, warmup_url, settle, headless, cookies, domain))


if __name__ == "__main__":
    import sys

    if len(sys.argv) >= 2 and sys.argv[1] == "api":
        # zenapi <api_url> <warmup_url>
        print(json.dumps(fetch_site_api(sys.argv[2], sys.argv[3]), indent=2)[:8000])
    else:
        # zenldjson <url>
        print(json.dumps(scrape_ld_json(sys.argv[1]), indent=2)[:8000])
