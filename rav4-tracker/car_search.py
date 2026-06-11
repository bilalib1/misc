"""Silver hybrid finder — helper for the used-car search workflow.

This script does the deterministic parts of the workflow: it builds the
Cars.com filtered-search URLs to scrape, encodes the "what counts as silver"
and "which trims have leather" rules, and formats + sends a ranked shortlist to
Telegram. The listing *extraction* itself (reading each results page into
structured rows) is done by a Claude agent / WebFetch step, because Cars.com
renders results client-side — see the workflow notes in the plan doc.

Availability: a listing is only "in stock" if its exact VIN is confirmed for
sale on the SELLING DEALER'S OWN site. Cars.com is NOT authoritative — it keeps
sold cars live in both search results and the detail page (we shipped a sold car
once because we trusted it). `send_ranked` refuses any listing lacking a `vin`
and a truthy `verified` flag, so only dealer-confirmed cars can go out.

Usage:
  python car_search.py urls                 # print the Cars.com URLs to fetch
  python car_search.py send shortlist.json  # send a ranked list to Telegram

shortlist.json is a JSON array of objects, best value first. Every object MUST
carry the VIN and a verified flag set once the dealer-site check passes:
  [{"title": "2022 Toyota RAV4 Hybrid XLE Premium", "price": "$27,995",
    "miles": "33k mi", "city": "Glendale", "url": "https://www.cars.com/...",
    "vin": "JTM...1234", "verified": true}]
"""
import html
import json
import sys
from urllib.parse import urlencode

import re
import requests

from config import telegram_conf

# Greater-LA search defaults.
ZIP = "90012"
DISTANCE = 75
PRICE_MIN, PRICE_MAX = 20000, 40000
MILES_MAX = 50000
YEAR_MIN = 2021

# RAV4 Hybrid and its closest hybrid-crossover relatives. (make, model slug)
# Kia is excluded per buyer preference. Spread across makes so a ranked top-N
# can hit >=7 brands with no brand repeated 3x.
MODELS = [
    ("toyota", "toyota-rav4_hybrid"),
    ("toyota", "toyota-venza"),
    ("honda", "honda-cr_v_hybrid"),
    ("hyundai", "hyundai-tucson_hybrid"),
    ("hyundai", "hyundai-santa_fe_hybrid"),
    ("mazda", "mazda-cx_50_hybrid"),
    ("ford", "ford-escape_hybrid"),
    ("ford", "ford-escape_plug_in_hybrid"),
    ("lexus", "lexus-nx_350h"),
    ("lexus", "lexus-ux_250h"),
    ("volvo", "volvo-xc40"),
    ("volvo", "volvo-xc60_recharge"),
    ("mitsubishi", "mitsubishi-outlander_phev"),
    ("subaru", "subaru-crosstrek_hybrid"),
    ("jeep", "jeep-wrangler_4xe"),
    ("jeep", "jeep-grand_cherokee_4xe"),
    ("nissan", "nissan-murano"),       # Murano Hybrid; discontinued after 2020 — results likely sparse
    ("nissan", "nissan-rogue"),        # no full hybrid in US market; included for completeness
]
# Note: Ford Escape / Volvo XC60 Recharge PHEVs aren't reachable by a dedicated
# model slug on Cars.com — they live under the base model slug (ford-escape,
# volvo-xc60) behind a `fuel_slugs[]=hybrid|plug_in_hybrid` filter this builder
# doesn't add, so those URLs come back empty. Query them by hand if needed.

# Query both color buckets; many "silver" cars are filed under gray. The buyer
# treats silver synonyms (platinum graphite, steel gray, chrome, stardust, etc.)
# as passing, so we cast the wide net here and let SILVER_SYNONYMS confirm.
COLOR_SLUGS = ["silver", "gray"]

# Exterior: light colors pass; dark/vivid colors are vetoed.
# Root words that imply a light/neutral exterior (silver, gray, white, etc.).
# White is included — buyer may want silver OR white since both are "light."
SILVER_ROOTS = (
    "silver", "gray", "grey", "chrome", "platinum", "titanium",
    "stardust", "sterling",
)
# Strings that veto a color regardless of root-word matches — dark/blue-leaning.
DARK_COLOR_MARKERS = (
    "graphite", "magnetic", "gunmetal", "charcoal", "granite", "cement",
    "meteorite", "machine gray", "machine grey", "polymetal",
    "urban gray", "urban grey", "mercury", "dark gray", "dark grey",
)
# Vivid/dark colors that should never pass even if they contain no dark marker.
_BLOCKED_COLORS = {"black", "blue", "red", "green", "orange", "yellow",
                   "purple", "brown", "maroon", "pink", "gold", "bronze",
                   "copper", "violet", "indigo", "teal", "navy", "burgundy"}

# Interior: rule is simply "not solid black." Flip to a negative blocklist so
# white, cream, gray, beige, and any unlisted color all pass automatically.
_BLACK_INTERIORS = {"black", "jet black", "ebony", "noir", "onyx"}

# Trims whose STANDARD seat is leather or leather-like (SofTex/SynTex/H-Tex/
# NuLuxe). Verified against authoritative trim specs (manufacturer / Edmunds /
# U.S. News), NOT a listing's "Leather Seats" tag, which dealers set loosely.
# Anything not listed (RAV4 LE/XLE/SE, CR-V Sport, Tucson SEL, Sorento S/LX) is
# cloth and gets dropped. Re-check specs per model year before trusting this.
LEATHER_TRIMS = {
    "rav4 hybrid": {"xle premium", "xse", "limited"},   # SE is FABRIC — excluded
    "venza": {"le", "xle", "limited"},                   # SofTex standard on all
    "cr-v hybrid": {"ex-l", "sport-l", "sport touring"},
    "tucson hybrid": {"limited"},               # N Line is sport cloth, not leather
    "tucson plug-in hybrid": {"limited"},       # same — N Line is cloth on PHEV too
    "santa fe hybrid": {"limited", "calligraphy"},
    "elantra hybrid": {"limited"},                    # Limited only; Blue/SE are cloth
    "cx-50 hybrid": {"premium", "premium plus"},          # both CX-50 Hybrid trims are leather
    "escape hybrid": {"titanium"},                         # ActiveX on lower trims is cloth-ish; Titanium = leather
    "escape plug-in hybrid": {"titanium"},
    "nx 350h": {"base", "premium", "luxury", "f sport", "f sport handling"},  # NuLuxe standard across NX 350h
    "ux 250h": {"base", "premium", "luxury", "f sport"},  # NuLuxe standard across UX 250h
    "xc40": {"inscription", "r-design", "ultimate", "plus"},  # leather/leather-like; Momentum base is City Weave cloth
    "xc60 recharge": {"plus", "ultimate", "inscription", "r-design"},  # Nappa/leather standard on Recharge trims
    "outlander phev": {"sel", "gt"},                       # leather on SEL/GT; ES/SE are cloth
    "crosstrek hybrid": {"hybrid", "limited"},             # leather-trimmed; base/Sport are cloth
    "wrangler 4xe": {"high altitude", "rubicon x", "sahara"},  # leather standard/optional; CONFIRM per listing — many are cloth
    "grand cherokee 4xe": {"limited", "overland", "summit", "trailhawk"},  # base 4xe is cloth
    "murano hybrid": {"sl", "platinum"},   # SV is cloth; SL/Platinum have leather
    "rogue": {"sl", "platinum"},           # SV is cloth; no hybrid exists in US — won't match fuel filter
    # Corolla Cross Hybrid: XLE has SofTex; S/SE are fabric
    "corolla cross hybrid": {"xle"},
    # Mustang Mach-E: Premium, First Edition, GT; Select is cloth
    "mustang mach-e": {"premium", "first edition", "gt", "california route 1"},
}


def is_silver(color: str) -> bool:
    """Pass light/neutral exteriors; veto dark, vivid, or unknown colors."""
    c = (color or "").lower().strip()
    if not c:
        return False
    if any(d in c for d in DARK_COLOR_MARKERS):
        return False
    if c in _BLOCKED_COLORS:
        return False
    return any(s in c for s in SILVER_ROOTS)


def has_acceptable_interior(interior: str) -> bool:
    """Pass anything that is not a black interior. Empty = unknown = pass."""
    c = (interior or "").lower().strip()
    if not c:
        return True   # unknown interior — don't veto
    return not any(b in c for b in _BLACK_INTERIORS)


def has_leather(model: str, trim: str) -> bool:
    trims = LEATHER_TRIMS.get((model or "").lower())
    if not trims:
        return False
    t = (trim or "").lower()
    return any(t.startswith(x) or x in t for x in trims)


_LEATHER_RE = re.compile(
    r"\b(leather|leatherette|sofTex|syntex|nuluxe|h-tex|prima-tex|sensatec)\b", re.I
)
_CLOTH_RE = re.compile(r"\b(cloth|fabric|vinyl|canvas|microfiber|suede)\b", re.I)


def confirms_leather(interior_text: str):
    """
    Check actual seat-material text (e.g. from a spec list or LD+JSON field).

    Returns True  — text explicitly mentions leather/leatherette/synthetic-leather.
    Returns False — text explicitly mentions cloth/fabric/vinyl.
    Returns None  — text is empty or ambiguous; caller falls back to has_leather().

    Use this as a hard gate BEFORE has_leather() when the listing gives you real
    interior-type data (CarMax LD+JSON `vehicleInteriorType`, Cars.com spec list,
    Carvana detail page). The trim-name lookup in has_leather() is only a fallback
    for when no material text is available.
    """
    t = (interior_text or "").strip()
    if not t:
        return None
    if _LEATHER_RE.search(t):
        return True
    if _CLOTH_RE.search(t):
        return False
    return None


def build_search_url(make: str, model_slug: str, color_slug: str) -> str:
    params = [
        ("stock_type", "used"),
        ("makes[]", make),
        ("models[]", model_slug),
        ("list_price_min", PRICE_MIN),
        ("list_price_max", PRICE_MAX),
        ("mileage_max", MILES_MAX),
        ("year_min", YEAR_MIN),
        ("year_max", 2026),
        ("exterior_color_slugs[]", color_slug),
        ("fuel_slugs[]", "hybrid"),
        ("fuel_slugs[]", "plug_in_hybrid"),
        ("zip", ZIP),
        ("maximum_distance", DISTANCE),
        ("page_size", 50),
        ("sort", "list_price_asc"),
    ]
    return "https://www.cars.com/shopping/results/?" + urlencode(params)


def search_urls():
    for make, model_slug in MODELS:
        for color in COLOR_SLUGS:
            yield build_search_url(make, model_slug, color)


# Dealers/sellers whose sites hard-block automated VIN verification (Akamai 403),
# so we can't prove a car is still in stock. Treat their listings as unverifiable
# and drop them rather than risk texting a sold car.
UNVERIFIABLE_SELLERS = ("carmax",)

# Substrings that mean a listing page is dead (sold / pulled / not found).
SOLD_MARKERS = (
    "no longer available", "this vehicle has been sold", "vehicle not found",
    "no longer in our inventory", "is no longer available", "vehicle has been sold",
)
_BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def check_listing_available(url, timeout=20):
    """Best-effort probe of a listing URL: 'available' / 'gone' / 'unknown'.

    A 404, a redirect off the detail page, or a sold-marker => 'gone'. Many
    sites (Cars.com, CarMax/Akamai) answer non-browser clients with 403/429 —
    then we can't tell, so 'unknown' (verify by VIN on the dealer's own site).
    Even a reachable Cars.com 'available' is NOT proof; confirm by VIN.
    """
    try:
        r = requests.get(url, headers={"User-Agent": _BROWSER_UA},
                         timeout=timeout, allow_redirects=True)
    except requests.RequestException:
        return "unknown"
    if r.status_code in (403, 429):
        return "unknown"
    if r.status_code == 404:
        return "gone"
    if "/vehicledetail/" in url and "/vehicledetail/" not in r.url:
        return "gone"  # redirected away from the single-car page
    if any(m in r.text.lower() for m in SOLD_MARKERS):
        return "gone"
    return "available" if r.ok else "unknown"


def send_ranked(listings, header=None, require_verified=True):
    """listings: iterable of dicts with title/price/miles/city/url, best first.

    Each listing must also carry `vin` and a truthy `verified` (set only after
    confirming the VIN is live on the selling dealer's OWN site). Refuses to send
    otherwise — this is the guard that stops sold/unverified cars going out.
    """
    if require_verified:
        bad = [d.get("title", "?") for d in listings
               if not d.get("vin") or not d.get("verified")]
        if bad:
            raise SystemExit(
                "Refusing to send unverified listings (missing vin/verified): "
                + "; ".join(bad)
                + "\nConfirm each VIN is in stock on the SELLING DEALER'S OWN site "
                  "(Cars.com lags and shows sold cars), then set vin + verified.")
    tok, chat = telegram_conf()
    header = header or "Silver/light-gray leather hybrids, 2022+, under 50k mi, $20-40k:"
    lines = [header, ""]
    for i, d in enumerate(listings, 1):
        title = html.escape(d["title"])  # "<year> <make> <model> <trim>"
        lines.append(f'{i}. {title} - {d["price"]} | {d["miles"]} - '
                     f'<a href="{d["url"]}">view</a>')
    msg = "\n".join(lines)
    r = requests.get(
        f"https://api.telegram.org/bot{tok}/sendMessage",
        params={"chat_id": chat, "text": msg, "parse_mode": "HTML",
                "disable_web_page_preview": "true"},
        timeout=30,
    )
    r.raise_for_status()
    if not r.json().get("ok"):
        raise SystemExit(f"Telegram error: {r.text}")
    print(f"Sent {len(listings)} listing(s).")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "urls"
    if cmd == "urls":
        for u in search_urls():
            print(u)
    elif cmd == "send":
        listings = json.loads(open(sys.argv[2]).read())
        send_ranked(listings)
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
