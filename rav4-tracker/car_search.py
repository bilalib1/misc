"""Silver hybrid finder — helper for the used-car search workflow.

This script does the deterministic parts of the workflow: it builds the
Cars.com filtered-search URLs to scrape, encodes the "what counts as silver"
and "which trims have leather" rules, and formats + sends a ranked shortlist to
Telegram. The listing *extraction* itself (reading each results page into
structured rows) is done by a Claude agent / WebFetch step, because Cars.com
renders results client-side — see the workflow notes in the plan doc.

Usage:
  python car_search.py urls                 # print the Cars.com URLs to fetch
  python car_search.py send shortlist.json  # send a ranked list to Telegram

shortlist.json is a JSON array of objects, best value first:
  [{"title": "2022 Toyota RAV4 Hybrid XLE Premium", "price": "$27,995",
    "miles": "33k mi", "city": "Glendale", "url": "https://www.cars.com/..."}]
"""
import html
import json
import sys
from urllib.parse import urlencode

import requests

from config import telegram_conf

# Greater-LA search defaults.
ZIP = "90012"
DISTANCE = 75
PRICE_MIN, PRICE_MAX = 20000, 40000
MILES_MAX = 50000
YEAR_MIN = 2022

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
]
# Note: Ford Escape / Volvo XC60 Recharge PHEVs aren't reachable by a dedicated
# model slug on Cars.com — they live under the base model slug (ford-escape,
# volvo-xc60) behind a `fuel_slugs[]=hybrid|plug_in_hybrid` filter this builder
# doesn't add, so those URLs come back empty. Query them by hand if needed.

# Query both color buckets; many "silver" cars are filed under gray. The buyer
# treats silver synonyms (platinum graphite, steel gray, chrome, stardust, etc.)
# as passing, so we cast the wide net here and let SILVER_SYNONYMS confirm.
COLOR_SLUGS = ["silver", "gray"]

# Substrings (lowercased) that count as "silver" for this buyer.
SILVER_SYNONYMS = (
    "silver", "gray", "grey", "graphite", "steel", "chrome", "stardust",
    "platinum", "magnetic", "celestial", "silky", "lunar", "atomic",
    "shimmering", "cement", "titanium",
)

# Trims whose STANDARD seat is leather or leather-like (SofTex/SynTex/H-Tex/
# NuLuxe). Verified against authoritative trim specs (manufacturer / Edmunds /
# U.S. News), NOT a listing's "Leather Seats" tag, which dealers set loosely.
# Anything not listed (RAV4 LE/XLE/SE, CR-V Sport, Tucson SEL, Sorento S/LX) is
# cloth and gets dropped. Re-check specs per model year before trusting this.
LEATHER_TRIMS = {
    "rav4 hybrid": {"xle premium", "xse", "limited"},   # SE is FABRIC — excluded
    "venza": {"le", "xle", "limited"},                   # SofTex standard on all
    "cr-v hybrid": {"ex-l", "sport-l", "sport touring"},
    "tucson hybrid": {"limited", "n line"},
    "santa fe hybrid": {"limited", "calligraphy"},
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
}


def is_silver(color: str) -> bool:
    c = (color or "").lower()
    return any(s in c for s in SILVER_SYNONYMS)


def has_leather(model: str, trim: str) -> bool:
    trims = LEATHER_TRIMS.get((model or "").lower())
    if not trims:
        return False
    t = (trim or "").lower()
    return any(t.startswith(x) or x in t for x in trims)


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


def send_ranked(listings, header=None):
    """listings: iterable of dicts with title/price/miles/city/url, best first."""
    tok, chat = telegram_conf()
    header = header or ("Top silver/grey hybrids near LA - leather, 2022+, "
                        "under 50k mi, $20-40k. Best value first:")
    lines = [header, ""]
    for i, d in enumerate(listings, 1):
        title = html.escape(d["title"])
        lines.append(f'{i}. {title} - {d["price"]} | {d["miles"]} | '
                     f'{d["city"]} - <a href="{d["url"]}">view</a>')
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
