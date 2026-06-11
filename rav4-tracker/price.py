"""Pull one representative price out of a dealer's reply.

A dealer email usually has several dollar figures: MSRP, a discount, doc/DMV
fees, a monthly payment, a deposit. We want the one number that represents the
quote — ideally the all-in "out the door" price.
"""
import re

DOLLAR_RE = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+(?:\.\d{2})?|\d+(?:\.\d{2})?)")
KEYWORDS = re.compile(
    r"(out[\s-]?the[\s-]?door|\bOTD\b|drive[\s-]?off|total|selling price|"
    r"your price|sale price|final price|final number)",
    re.I,
)
LOW, HIGH = 15000, 80000  # plausible RAV4 transaction range; filters fees/payments/deposits


def extract_prices(text):
    """All dollar amounts as (value, start_index, end_index)."""
    out = []
    for m in DOLLAR_RE.finditer(text):
        try:
            out.append((float(m.group(1).replace(",", "")), m.start(), m.end()))
        except ValueError:
            pass
    return out


def pick_price(text):
    """One price for this reply, or None.

    A label like "out the door price is $X" puts the real number *after* the
    keyword, so:
      1. Prefer the in-range amount that starts within 40 chars *after* a
         keyword (nearest wins; ties go to the larger, more all-in number).
      2. Else the in-range amount nearest a keyword on either side (<=40 chars).
      3. Else the largest in-range amount.
    """
    spans = [(v, s, e) for (v, s, e) in extract_prices(text) if LOW <= v <= HIGH]
    if not spans:
        return None
    kw = [(m.start(), m.end()) for m in KEYWORDS.finditer(text)]
    if kw:
        after = []
        for v, s, e in spans:
            gap = min((s - ke for _, ke in kw if 0 <= s - ke <= 40), default=None)
            if gap is not None:
                after.append((gap, -v, v))
        if after:
            return min(after)[2]
        near = []
        for v, s, e in spans:
            d = min(min(abs(s - ks), abs(s - ke), abs(e - ks), abs(e - ke)) for ks, ke in kw)
            if d <= 40:
                near.append((d, -v, v))
        if near:
            return min(near)[2]
    return max(v for v, _, _ in spans)
