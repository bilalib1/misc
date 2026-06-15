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
import datetime
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
    ("ford", "ford-escape"),   # base slug: Cars.com has no ford-escape_hybrid slug; the
                               # fuel_slugs=hybrid|plug_in_hybrid filter restricts it (Carvana
                               # base slug is hybrid-keyword-filtered via _carvana_trust_slug=False)
    ("lexus", "lexus-nx_350h"),
    ("lexus", "lexus-ux_250h"),
    ("volvo", "volvo-xc40"),
    ("volvo", "volvo-xc60_recharge"),
    ("mitsubishi", "mitsubishi-outlander_phev"),
    ("subaru", "subaru-crosstrek_hybrid"),
    # Jeep Wrangler/Grand Cherokee 4xe BLACKLISTED 2026-06-14 (buyer request): low
    # reliability + the parentModel color filter still returns 300+ gas Wranglers to
    # walk for a handful of 4xe. Re-add the two lines below to restore them.
    #   ("jeep", "jeep-wrangler_4xe"),
    #   ("jeep", "jeep-grand_cherokee_4xe"),
    # Nissan Rogue/Murano removed 2026-06-14: no US hybrid variant, so they only
    # ever returned gas cars (0 kept) while wasting a full paginated scrape each.
]
# Note: Cars.com has no dedicated hybrid slug for these — they live under the BASE
# model slug (ford-escape, volvo-xc60). build_search_url DOES add
# fuel_slugs[]=hybrid|plug_in_hybrid, so the base slug returns only the hybrids/PHEVs.
# Ford Escape now uses the base slug above; Volvo XC60 Recharge still uses
# volvo-xc60_recharge (switch to base volvo-xc60 if it comes back empty).

# Query both color buckets; many "silver" cars are filed under gray. The buyer
# treats silver synonyms (platinum graphite, steel gray, chrome, stardust, etc.)
# as passing, so we cast the wide net here and let SILVER_SYNONYMS confirm.
COLOR_SLUGS = ["silver", "gray"]

# Exterior: light colors pass; dark/vivid colors are vetoed.
# Root words that imply a light/neutral exterior (silver, gray, white, etc.).
# White is included — buyer may want silver OR white since both are "light."
SILVER_ROOTS = (
    "silver", "gray", "grey", "chrome", "platinum",
    "stardust", "sterling",
    "ingot",      # Mazda "Ingot" / "Ingot Silver" (card JSON sometimes truncates to "Ingot")
)
# NOTE: "titanium" was REMOVED from the allowlist on 2026-06-14 — image spot-check
# caught a Toyota "Titanium Glow" Venza that is actually champagne/GOLD passing as
# silver. Genuine gray-titanium colors (e.g. "Titanium Gray") still pass via "gray".
# Strings that veto a color regardless of root-word matches — dark/blue-leaning.
DARK_COLOR_MARKERS = (
    "graphite", "magnetic", "gunmetal", "charcoal", "granite", "cement",
    "meteorite", "machine gray", "machine grey", "polymetal",
    "urban gray", "urban grey", "mercury", "dark gray", "dark grey",
    "coastal",   # Toyota "Coastal Gray" is a dark blue-gray (confirmed by image 2026-06-12)
    "carbonized",   # Ford "Carbonized Gray" is a dark gunmetal (2026-06-14)
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
    "escape hybrid": {"titanium", "platinum"},             # Titanium (2020-22) + Platinum (2023+) = leather; ActiveX/cloth on lower trims
    "escape plug-in hybrid": {"titanium", "platinum"},     # same: Titanium (<=2022) / Platinum (2023+)
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


def crossmake_search_url(color_slug: str) -> str:
    """FILTER-FIRST Cars.com URL: body=SUV + fuel=hybrid/PHEV + one exterior color,
    NO make/model. Returns every SUV hybrid/PHEV in greater LA of that color; model
    recognition + leather-by-trim are applied locally afterward (Cars.com has no
    working server-side leather filter, and is LA-local so the result set is small)."""
    params = [
        ("stock_type", "used"),
        ("body_style_slugs[]", "suv"),
        ("clean_title", "true"),   # exclude salvage/rebuilt/branded titles server-side
                                   # (Cars.com is the only of our 3 sources that lists them;
                                   #  Carvana/CarMax are clean-title by policy)
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
        ("page_size", 100),
        ("sort", "list_price_asc"),
    ]
    return "https://www.cars.com/shopping/results/?" + urlencode(params)


def search_urls():
    """One filter-first URL per exterior color (silver, gray) — no per-model loop."""
    for color in COLOR_SLUGS:
        yield crossmake_search_url(color)


# ---------------------------------------------------------------------------
# Reliability / quality scoring tables
# ---------------------------------------------------------------------------

# Brand reputation multiplier (top reliability/resale = 1.0). Rescaled 2026-06-14 per
# the buyer's guidance — Toyota/Lexus/Honda ~1.0, Mazda ~0.92, Jeep ~0.70 — and widened
# to cover EVERY make the filter-first search can surface; unknown makes use the default.
MANUFACTURER_MULTIPLIER = {
    "toyota": 1.00, "lexus": 1.00, "honda": 1.00, "acura": 0.98,
    "mazda": 0.92, "subaru": 0.90,
    "hyundai": 0.88, "genesis": 0.88, "kia": 0.86, "buick": 0.86,
    "ford": 0.84, "chevrolet": 0.84, "gmc": 0.84, "nissan": 0.84,
    "infiniti": 0.84, "lincoln": 0.84, "cadillac": 0.82, "mitsubishi": 0.82,
    "bmw": 0.80, "volvo": 0.80, "porsche": 0.80, "mini": 0.80, "volkswagen": 0.80,
    "audi": 0.78, "mercedes-benz": 0.78,
    "dodge": 0.74, "chrysler": 0.74, "ram": 0.74,
    "jeep": 0.70, "jaguar": 0.70, "land": 0.68, "alfa": 0.68, "fiat": 0.66,
    "maserati": 0.66,
}
MANUFACTURER_DEFAULT = 0.82   # unknown make


def get_brand_multiplier(make: str) -> float:
    return MANUFACTURER_MULTIPLIER.get((make or "").lower().strip(), MANUFACTURER_DEFAULT)


# Approx US annual unit sales per model — used ONLY to normalize NHTSA complaint counts
# by volume (a popular model has more complaints just from selling more). Rough figures
# are fine for a relative nudge; models not listed use SALES_DEFAULT. Keyed by the
# primary model word (lowercased), e.g. 'rav4', 'cr-v', 'cx-90', 'santa' (Santa Fe).
MODEL_ANNUAL_SALES = {
    "rav4": 430000, "cr-v": 360000, "tucson": 180000, "santa": 110000,
    "cx-50": 45000, "cx-90": 55000, "cx-5": 150000, "cx-30": 60000,
    "escape": 130000, "outlander": 90000, "crosstrek": 150000, "forester": 165000,
    "nx": 60000, "ux": 25000, "rx": 110000, "venza": 35000,
    "xc40": 25000, "xc60": 45000, "xc90": 35000, "q5": 65000, "q3": 30000,
    "x5": 65000, "x3": 55000, "glc": 55000, "gle": 50000, "macan": 30000,
    "hornet": 15000, "tonale": 8000, "highlander": 230000, "sequoia": 45000,
    "sorento": 100000, "sportage": 130000, "telluride": 100000, "rogue": 250000,
    "murano": 35000, "wrangler": 180000, "cherokee": 110000,
}
SALES_DEFAULT = 35000

_CURRENT_YEAR = datetime.date.today().year
_complaint_cache: dict = {}


def _nhtsa_complaints(make: str, model: str, year):
    """Live NHTSA complaint count for a make/model/year, cached. None on failure."""
    if not (make and model and year):
        return None
    key = (make.lower(), model.lower(), int(year))
    if key in _complaint_cache:
        return _complaint_cache[key]
    n = None
    try:
        r = requests.get(
            "https://api.nhtsa.gov/complaints/complaintsByVehicle",
            params={"make": make, "model": model, "modelYear": int(year)},
            timeout=8,
        )
        if r.ok:
            n = int(r.json().get("count") or 0)
    except Exception:
        n = None
    _complaint_cache[key] = n
    return n


def reliability_multiplier(make: str, model: str, year, want_detail=False):
    """Combined reliability = brand reputation × a per-car NHTSA factor.

    The NHTSA factor blends three ideas, all SECONDARY to the brand multiplier:
      • complaints / sales, normalized to complaints per 10k vehicle-years (so a
        high-volume model isn't penalized just for selling more), vs a ~2.0 baseline.
      • data CONFIDENCE w = exposure / 300k vehicle-years — a brand-new, low-volume
        model has little data, so its statistically-weak complaint signal is damped.
      • FIRST-GEN / unproven-platform risk: low-confidence (new + low-volume) cars take
        a small penalty, so a 0-complaint first-year Mazda does NOT outscore a proven
        Toyota; a same-year Toyota always edges a Mazda slightly.
    """
    brand = get_brand_multiplier(make)
    n = _nhtsa_complaints(make, model, year)
    sales = MODEL_ANNUAL_SALES.get((model or "").lower().strip(), SALES_DEFAULT)
    years = max(1, _CURRENT_YEAR - int(year) + 1) if year else 1
    exposure = sales * years                      # vehicle-years on the road
    w = min(1.0, exposure / 300_000)              # data confidence
    if n is None:
        factor = 1.0                              # no NHTSA data → brand only
    else:
        rate = n / (exposure / 10_000)            # complaints per 10k vehicle-years
        dev = max(-2.0, min(4.0, rate - 2.0))     # deviation from baseline
        complaint_adj = -w * dev * 0.015          # good rate → +, bad rate → −
        firstgen_risk = (1.0 - w) * 0.04          # new/low-volume → small penalty
        factor = max(0.90, min(1.03, 1.0 + complaint_adj - firstgen_risk))
    rel = brand * factor
    if want_detail:
        return rel, {"brand": brand, "complaints": n, "sales": sales, "years": years,
                     "factor": round(factor, 3), "reliability": round(rel, 4)}
    return rel

# Trim hierarchy per model: rank 1 = base leather trim, higher = better equipped.
# Normalized to a 0.95×–1.10× multiplier (15 pp spread) in trim_score_multiplier().
# Only trims already in LEATHER_TRIMS are listed — no cloth trims here.
TRIM_RANKS = {
    "rav4 hybrid": {
        "xle premium": 1,   # SofTex, base leather; same MSRP tier as XSE
        "xse":         2,   # SofTex + sport styling; slight premium over XLE Prem
        "limited":     3,   # SofTex + panoramic roof + head-up display; top trim
    },
    "venza": {
        "le":      1,   # SofTex standard on all Venza; LE is base
        "xle":     2,   # adds tech/JBL
        "limited": 3,   # panoramic glass roof + premium audio
    },
    "cr-v hybrid": {
        "ex-l":          1,   # leather + heated seats
        "sport-l":       2,   # adds 12\" infotainment + more driver assists
        "sport touring": 3,   # top; HUD + Bose + wireless charging
    },
    "tucson hybrid": {
        "limited": 1,   # only leather trim offered
    },
    "tucson plug-in hybrid": {
        "limited": 1,
    },
    "santa fe hybrid": {
        "limited":    1,
        "calligraphy": 2,   # adds Nappa leather + quilted seats
    },
    "cx-50 hybrid": {
        "premium":      1,
        "premium plus": 2,   # adds Bose + larger sunroof + ventilated seats
    },
    "escape hybrid": {
        "titanium": 1,   # leather (2020-22 top trim)
        "platinum": 2,   # leather (2023+ top trim); adds B&O audio, 360 cam
    },
    "escape plug-in hybrid": {
        "titanium": 1,
        "platinum": 2,
    },
    "nx 350h": {
        "base":              1,   # NuLuxe standard across all NX 350h
        "premium":           2,   # adds 14\" screen + panoramic roof
        "luxury":            3,   # adds semi-aniline leather + real wood trim
        "f sport":           3,   # sport-tuned suspension; same tech tier as Luxury
        "f sport handling":  4,   # adaptive suspension + torque vectoring; top
    },
    "ux 250h": {
        "base":    1,   # NuLuxe; compact entry luxury
        "premium": 2,   # adds moonroof + 10.3\" screen
        "luxury":  3,   # adds heated/ventilated + real wood
        "f sport": 3,   # sport-tuned; same tier as Luxury
    },
    "xc40": {
        "plus":        1,   # leather-like Tailored Wool / Microtech
        "inscription": 2,   # pre-2024 name for Ultimate; full leather
        "r-design":    2,   # sport variant of Inscription tier
        "ultimate":    3,   # Nappa leather + panoramic roof + B&W audio
    },
    "xc60 recharge": {
        "plus":        1,
        "inscription": 2,
        "r-design":    2,
        "ultimate":    3,
    },
    "outlander phev": {
        "sel": 1,   # leather + 10.8\" HUD + 12-speaker Bose
        "gt":  2,   # adds ventilated seats + power running boards
    },
    "crosstrek hybrid": {
        "hybrid":  1,   # base Crosstrek Hybrid
        "limited": 2,   # leather + navigation
    },
    "wrangler 4xe": {
        "sahara":       1,   # leather-wrapped interior; comfort-focused
        "rubicon x":    2,   # off-road focused + leather option
        "high altitude": 3,  # luxury off-road; full leather + sky one-touch roof
    },
    "grand cherokee 4xe": {
        "limited":   1,
        "trailhawk": 2,   # off-road + leather
        "overland":  3,   # luxury leather + real wood
        "summit":    4,   # McEvoy leather + 19-speaker McIntosh; top trim
    },
    "murano hybrid": {
        "sl":       1,
        "platinum": 2,   # semi-aniline leather + premium audio
    },
    "rogue": {
        "sl":       1,
        "platinum": 2,
    },
    "corolla cross hybrid": {
        "xle": 1,
    },
    "mustang mach-e": {
        "premium":           1,
        "california route 1": 2,
        "first edition":     2,
        "gt":                3,   # performance + MagneRide
    },
}


def trim_score_multiplier(model: str, trim: str) -> float:
    """Return a trim-level quality multiplier in [0.95, 1.10].

    Unknown / unrecognised trims return 1.0 (neutral).
    Matching uses substring search so partial trim strings work.
    When multiple trim keys match (e.g. 'premium' inside 'premium plus'),
    the highest rank wins.
    """
    ranks = TRIM_RANKS.get((model or "").lower())
    if not ranks:
        return 1.0
    t = (trim or "").lower()
    best = None
    for key, rank in ranks.items():
        if key in t:
            if best is None or rank > best:
                best = rank
    if best is None:
        return 1.0
    max_rank = max(ranks.values())
    if max_rank <= 1:
        return 1.05   # only one tier → slight boost over unknown
    normalized = (best - 1) / (max_rank - 1)   # 0.0 → 1.0
    return 0.95 + normalized * 0.15             # 0.95 → 1.10


# ---------------------------------------------------------------------------
# Models excluded regardless of other filters — sedans/non-SUVs that slipped
# into LEATHER_TRIMS for reference but don't fit the buyer's "SUV/crossover" requirement.
BLOCKED_MODELS = {
    "elantra",
    "elantra hybrid",
}

# Makes excluded entirely (buyer preference). Applied after the filter-first
# cross-make fetch, which surfaces every make. Jeep blacklisted 2026-06-14;
# Kia excluded throughout the project.
BLOCKED_MAKES = {"jeep", "kia"}


def is_blocked_make(make: str) -> bool:
    return (make or "").lower().strip() in BLOCKED_MAKES


def is_blocked_model(model: str) -> bool:
    m = (model or "").lower().strip()
    return any(b in m for b in BLOCKED_MODELS)


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
