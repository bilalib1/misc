"""Call a site's internal JSON API from INSIDE a loaded page (same-origin fetch).

Many SPAs render their grid/detail from a private JSON endpoint (KBB's
`/rest/lsc/listing`, store locators, search APIs). Hitting that endpoint with a
bare `requests`/`urllib` call is usually blocked — it lacks the page's cookies,
TLS fingerprint, `Origin`/`Referer`, and anti-bot context. The fix: run the
`fetch()` from inside a real, already-loaded tab on that origin, so the request
INHERITS all of it (`credentials: 'include'`).

This drives the already-running, logged-in, invisible CDP Chrome over bare CDP
(`Runtime.evaluate` only — never `Runtime.enable`, the #1 automation tell), so it
stays invisible and passes the origin's own checks. For a HARDENED public anti-bot
site you don't have a logged-in tab for (CarMax/Carvana/KBB cold), use the
zendriver variant in `zendriver_session.fetch_json_in_page` instead, which clears
Cloudflare first. See plans/browser_interaction.md.

Proven: KBB/Autotrader LSC listing API, paginated, in car-sales-scraping
(`kbb_scraper._fetch_json_in_page`).
"""
from __future__ import annotations

import json
import time
from urllib.parse import urlsplit

from chrome_cdp_session import ChromeCDPSession, DEFAULT_PORT

# A self-contained async IIFE: fetch the URL same-origin and hand back a JSON
# envelope {status, body} (or {status:0, error}) so a network/parse failure never
# throws across the CDP boundary — the caller inspects status.
_FETCH_JS = """
(async () => {
  try {
    const r = await fetch(%s, {headers: {'accept': 'application/json'}, credentials: 'include'});
    const txt = await r.text();
    return JSON.stringify({status: r.status, body: txt});
  } catch (e) {
    return JSON.stringify({status: 0, error: String(e)});
  }
})()
"""


def _origin(url: str) -> str:
    p = urlsplit(url)
    return f"{p.scheme}://{p.netloc}/"


def fetch_json_in_page(
    api_url: str,
    on_url: str | None = None,
    open_origin: bool = True,
    port: int = DEFAULT_PORT,
    settle_seconds: float = 2.0,
    keep_tab: bool = False,
) -> dict:
    """Fetch `api_url` from inside a same-origin tab; return the parsed envelope.

    Tab selection, in priority order:
      • on_url set        -> attach to the first OPEN tab whose URL contains it
                             (reuse a logged-in page you already have on the origin).
      • open_origin=True  -> open a fresh background tab at api_url's origin root,
                             let it settle (cookies/anti-bot), then fetch.

    Returns {"status": int, "body": str} on success (HTTP status + raw response
    text), or {"status": 0, "error": str} if the in-page fetch threw. Use
    `fetch_json(...)` for the decoded JSON body directly.
    """
    if on_url:
        tab = ChromeCDPSession.for_url(on_url, port)
        close = not keep_tab
    elif open_origin:
        tab = ChromeCDPSession.for_new_tab(_origin(api_url), port)
        close = not keep_tab
    else:
        raise ValueError("pass on_url=<substr> or keep open_origin=True")

    try:
        try:
            tab.call("Page.enable")
            tab.wait_for_event("Page.loadEventFired", timeout=20)
        except Exception:
            pass
        time.sleep(settle_seconds)
        raw = tab.call(
            "Runtime.evaluate",
            {"expression": _FETCH_JS % json.dumps(api_url),
             "returnByValue": True, "awaitPromise": True},
        ).get("result", {}).get("value", '{"status": 0, "error": "no value"}')
    finally:
        if close:
            tab.close()
    try:
        return json.loads(raw)
    except Exception:
        return {"status": 0, "error": "unparseable envelope"}


def fetch_json(api_url: str, **kw) -> object:
    """Convenience: return the decoded JSON body, or None if the call failed / the
    body wasn't JSON (e.g. an anti-bot HTML interstitial came back instead)."""
    env = fetch_json_in_page(api_url, **kw)
    if env.get("status") != 200:
        return None
    try:
        return json.loads(env.get("body", ""))
    except Exception:
        return None


if __name__ == "__main__":
    import sys

    # python3 -m browser_interaction fetchjson <api_url> [on_url_substr]
    on = sys.argv[2] if len(sys.argv) > 2 else None
    print(json.dumps(fetch_json_in_page(sys.argv[1], on_url=on), indent=2)[:8000])
