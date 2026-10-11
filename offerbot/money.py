"""Locale-free money formatting.

Deliberately does not use the `locale` module: it needs system locales to be
generated, which they are not on a slim container, and it is process-global.
"""

from decimal import Decimal, ROUND_HALF_UP

# ru groups with a non-breaking space so the number never wraps mid-way.
_SEPARATORS = {
    "en": (",", "."),
    "ru": (" ", ","),
}


def _group(digits: str, sep: str) -> str:
    out = []
    for i, ch in enumerate(reversed(digits)):
        if i and i % 3 == 0:
            out.append(sep)
        out.append(ch)
    return "".join(reversed(out))


def fmt_amount(value: Decimal, lang: str = "en", max_dp: int = 2) -> str:
    """1234.5 -> '1,234.5' (en) / '1 234,5' (ru). Trailing zeros are dropped."""
    group_sep, decimal_sep = _SEPARATORS.get(lang, _SEPARATORS["en"])

    quantized = Decimal(value).quantize(Decimal(1).scaleb(-max_dp), rounding=ROUND_HALF_UP)
    sign = "-" if quantized < 0 else ""
    whole, _, frac = format(abs(quantized), "f").partition(".")
    frac = frac.rstrip("0")

    grouped = _group(whole, group_sep)
    return f"{sign}{grouped}{decimal_sep}{frac}" if frac else f"{sign}{grouped}"


def fmt_usd(value: Decimal, lang: str = "en") -> str:
    """Round to whole dollars above $10, keep cents below — reads better in a post."""
    value = Decimal(value)
    if abs(value) >= 10:
        return "$" + fmt_amount(value, lang, max_dp=0)
    return "$" + fmt_amount(value, lang, max_dp=2)
