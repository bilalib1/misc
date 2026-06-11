"""Run: python test_price.py  (no pytest needed)."""
from price import pick_price


def check(desc, text, expected):
    got = pick_price(text)
    ok = got == expected
    print(f"{'PASS' if ok else 'FAIL'}  {desc}: got {got}, expected {expected}")
    return ok


def main():
    cases = [
        ("out-the-door beats MSRP, deposit ignored",
         "MSRP is $41,000. Your out-the-door price is $36,750. $500 deposit holds it.",
         36750.0),
        ("monthly payment ignored, total picked",
         "We can do $499/mo for 36 months, total $34,210 out the door.",
         34210.0),
        ("no keyword -> max in range",
         "We can sell it at $33,995, plus tax.",
         33995.0),
        ("plain number with comma",
         "Best price $38,500.",
         38500.0),
        ("html-only / no dollar -> None",
         "<p>Thanks for reaching out, we will call you.</p>",
         None),
        ("only out-of-range figures -> None",
         "Doc fee $85, DMV $560, deposit $1,000.",
         None),
        ("two totals, nearest keyword wins",
         "total $39,000 ... unrelated $52,000 elsewhere",
         39000.0),
    ]
    passed = sum(check(*c) for c in cases)
    print(f"\n{passed}/{len(cases)} passed")
    raise SystemExit(0 if passed == len(cases) else 1)


if __name__ == "__main__":
    main()
