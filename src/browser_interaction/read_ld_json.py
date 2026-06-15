"""Read structured car/product data out of a page WITHOUT Playwright.

Most listing sites (CarMax, Carvana, Cars.com detail pages, dealer sites) embed
the full record -- VIN, price, year, color, mileage, listing URL -- in
`<script type="application/ld+json">` blocks. This opens the URL in a background
tab on the CDP Chrome, lets the SPA hydrate, scrolls to trigger lazy loading,
then returns the parsed LD+JSON blocks as plain Python objects.

WHY THIS INSTEAD OF browser_scraper.py's Playwright path: Playwright/Puppeteer
call `Runtime.enable`, the single biggest automation tell that Cloudflare/Akamai/
DataDome look for (the whole reason patchright + rebrowser-patches exist). Our
bare CDP layer only uses `Runtime.evaluate`, which needs no `Runtime.enable`, so
it never trips that signal -- and it drives the already-running, logged-in,
invisible Chrome instead of launching a second browser. See
plans/browser_interaction.md "Headless strategy".
"""
from __future__ import annotations

import json
import time

from chrome_cdp_session import ChromeCDPSession

_EXTRACT_JS = """
(function(){
  var out=[];
  var s=document.querySelectorAll('script[type="application/ld+json"]');
  for(var i=0;i<s.length;i++){
    try{ out.push(JSON.parse(s[i].textContent)); }catch(e){}
  }
  return JSON.stringify(out);
})()
"""


def read_ld_json(
    url: str,
    port: int = 9222,
    settle_seconds: float = 6.0,
    scrolls: int = 12,
    scroll_pause: float = 2.0,
    keep_tab: bool = False,
) -> list:
    """Open url in a background tab, hydrate + scroll, return parsed LD+JSON blocks.

    Returns a flat list of whatever JSON objects the page declared. Set
    scrolls=0 for a static detail page; keep the default for a lazy-loading
    results grid. keep_tab=True leaves the tab open for follow-up reads.
    """
    tab = ChromeCDPSession.for_new_tab(url, port)
    try:
        tab.call("Page.enable")
        try:
            tab.wait_for_event("Page.loadEventFired", timeout=20)
        except TimeoutError:
            pass
        time.sleep(settle_seconds)

        prev = -1
        for _ in range(scrolls):
            tab.call("Runtime.evaluate",
                     {"expression": "window.scrollTo(0, document.body.scrollHeight)"})
            time.sleep(scroll_pause)
            cur = tab.call(
                "Runtime.evaluate",
                {"expression": "document.querySelectorAll('script[type=\\\"application/ld+json\\\"]').length",
                 "returnByValue": True},
            ).get("result", {}).get("value", 0)
            if cur == prev:
                break
            prev = cur

        raw = tab.call(
            "Runtime.evaluate",
            {"expression": _EXTRACT_JS, "returnByValue": True, "awaitPromise": True},
        ).get("result", {}).get("value", "[]")
    finally:
        if not keep_tab:
            tab.close()
    try:
        return json.loads(raw)
    except Exception:
        return []


def read_cars(url: str, **kw) -> list[dict]:
    """Like read_ld_json but flattened to just @type Car/Vehicle records."""
    out = []
    for block in read_ld_json(url, **kw):
        items = block if isinstance(block, list) else [block]
        for it in items:
            if isinstance(it, dict) and it.get("@type") in ("Car", "Vehicle"):
                out.append(it)
    return out


if __name__ == "__main__":
    import sys

    print(json.dumps(read_ld_json(sys.argv[1]), indent=2)[:8000])
