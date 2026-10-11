"""Command parsing.

Documented form:
    .buy <stars|gram> <amount> <gift> <number> <en|ru> [3h|6h|12h]

Parsing is deliberately tolerant, because the command is typed by hand on a
phone in the middle of a trade: currency and language may sit anywhere,
the gift may be one or several words, and the gift number may be glued to the
name ("PlushPepe-1234") or marked with a hash ("#1234").

The one genuine ambiguity is that both the price and the gift number are bare
numbers. It is resolved positionally, following the documented order: the
first number is the price, the last is the gift number. "#" removes the
ambiguity explicitly.
"""

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from .gifts import normalize_slug

SIDES = {
    "buy": "buy", "b": "buy", "куплю": "buy", "покупаю": "buy",
    "sell": "sell", "s": "sell", "продам": "sell", "продаю": "sell",
}

CURRENCIES = {
    "stars": "stars", "star": "stars", "s": "stars", "⭐": "stars", "⭐️": "stars",
    "звезды": "stars", "звёзды": "stars", "звезд": "stars", "звёзд": "stars",
    "gram": "gram", "grams": "gram", "ton": "gram", "toncoin": "gram",
    "💎": "gram", "тон": "gram", "грам": "gram",
}

LANGS = {
    "en": "en", "eng": "en", "english": "en", "енг": "en",
    "ru": "ru", "rus": "ru", "russian": "ru", "рус": "ru",
}

#: Stars are an integer unit; a fractional star cannot be paid.
INTEGER_ONLY = {"stars"}

MAX_GIFT_NUMBER = 10_000_000

#: How long an offer may stay open. Anything shorter than a few minutes is a
#: typo; anything longer than a week is not an offer any more.
MIN_TTL = 5 * 60
MAX_TTL = 7 * 24 * 3600

_DURATION_UNITS = {
    "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
    "м": 60, "мин": 60,
    "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
    "ч": 3600, "час": 3600, "часа": 3600, "часов": 3600,
    "d": 86400, "day": 86400, "days": 86400,
    "д": 86400, "дн": 86400, "день": 86400,
}

_COMMAND_RE = re.compile(r"^[.!/](\w+)(?:\s+(.*))?$", re.IGNORECASE | re.DOTALL)
_NUMBER_RE = re.compile(r"^\d+(?:[.,]\d+)?$")
_HASH_NUMBER_RE = re.compile(r"^#(\d+)$")
_GLUED_AMOUNT_RE = re.compile(r"^(\d+(?:[.,]\d+)?)\s*(stars?|ton|grams?|⭐️?|💎)$", re.IGNORECASE)
_GIFT_WITH_NUMBER_RE = re.compile(r"^([A-Za-zА-Яа-яЁё][\w'’]*)[-#](\d+)$")
_DURATION_RE = re.compile(
    r"^(\d+)\s*(" + "|".join(sorted(_DURATION_UNITS, key=len, reverse=True)) + r")$",
    re.IGNORECASE,
)


class ParseError(Exception):
    """A user-facing parse failure. `code` selects the localized message."""

    def __init__(self, code: str, **ctx):
        super().__init__(code)
        self.code = code
        self.ctx = ctx


@dataclass(frozen=True)
class Offer:
    side: str
    currency: str
    amount: Decimal
    gift_slug: str
    gift_known: bool
    gift_number: int
    lang: str
    ttl_seconds: int

    @property
    def is_integer_currency(self) -> bool:
        return self.currency in INTEGER_ONLY


def parse_duration(token: str) -> int | None:
    """'6h' -> 21600. None when the token is not a duration at all."""
    match = _DURATION_RE.match(token)
    if not match:
        return None
    return int(match.group(1)) * _DURATION_UNITS[match.group(2).lower()]


def _to_decimal(token: str) -> Decimal:
    try:
        return Decimal(token.replace(",", "."))
    except InvalidOperation:
        raise ParseError("bad_amount", value=token)


def split_command(text: str) -> tuple[str, str] | None:
    """Return (side, rest) if `text` opens with a known offer command."""
    match = _COMMAND_RE.match(text.strip())
    if not match:
        return None
    side = SIDES.get(match.group(1).lower())
    if side is None:
        return None
    return side, (match.group(2) or "").strip()


def parse(
    text: str,
    *,
    default_lang: str = "en",
    default_currency: str | None = None,
    default_ttl: int = 6 * 3600,
) -> Offer:
    head = split_command(text)
    if head is None:
        raise ParseError("usage")
    side, rest = head
    if not rest:
        raise ParseError("usage")

    currency: str | None = None
    lang: str | None = None
    ttl: int | None = None
    explicit_number: int | None = None
    gift_from_token: str | None = None
    numbers: list[Decimal] = []
    words: list[str] = []

    for token in rest.split():
        lowered = token.lower()

        if lowered in LANGS and lang is None:
            lang = LANGS[lowered]
            continue

        if lowered in CURRENCIES and currency is None:
            # A bare "s" is ambiguous with a side alias; only treat it as a
            # currency when it stands among other tokens, which it does here.
            currency = CURRENCIES[lowered]
            continue

        if ttl is None:
            duration = parse_duration(token)
            if duration is not None:
                # Checked before the bare-number branch so "6h" is a lifetime
                # and not a price.
                if not MIN_TTL <= duration <= MAX_TTL:
                    raise ParseError("bad_ttl", value=token)
                ttl = duration
                continue

        glued = _GLUED_AMOUNT_RE.match(token)
        if glued:
            numbers.append(_to_decimal(glued.group(1)))
            if currency is None:
                suffix = glued.group(2).lower()
                currency = CURRENCIES.get(suffix) or CURRENCIES.get(suffix.rstrip("s"))
            continue

        hashed = _HASH_NUMBER_RE.match(token)
        if hashed:
            explicit_number = int(hashed.group(1))
            continue

        with_number = _GIFT_WITH_NUMBER_RE.match(token)
        if with_number:
            gift_from_token = with_number.group(1)
            explicit_number = int(with_number.group(2))
            continue

        if _NUMBER_RE.match(token):
            numbers.append(_to_decimal(token))
            continue

        words.append(token)

    if currency is None:
        currency = default_currency
    if currency is None:
        raise ParseError("no_currency")
    if lang is None:
        lang = default_lang
    if ttl is None:
        ttl = default_ttl

    # ---- split the numbers into price and gift number ----
    if explicit_number is not None:
        gift_number = explicit_number
        if len(numbers) > 1:
            raise ParseError("ambiguous_numbers")
        amount = numbers[0] if numbers else None
    elif len(numbers) >= 2:
        amount, gift_number = numbers[0], numbers[-1]
        if gift_number != gift_number.to_integral_value():
            raise ParseError("bad_number", value=str(gift_number))
        gift_number = int(gift_number)
    elif len(numbers) == 1:
        raise ParseError("no_number")
    else:
        raise ParseError("usage")

    if amount is None:
        raise ParseError("no_amount")
    if amount <= 0:
        raise ParseError("bad_amount", value=str(amount))
    if currency in INTEGER_ONLY and amount != amount.to_integral_value():
        raise ParseError("stars_fraction", value=str(amount))
    if not 0 < gift_number <= MAX_GIFT_NUMBER:
        raise ParseError("bad_number", value=str(gift_number))

    raw_gift = gift_from_token or " ".join(words)
    if not raw_gift.strip():
        raise ParseError("no_gift")

    slug, known = normalize_slug(raw_gift)
    if not slug:
        raise ParseError("no_gift")

    return Offer(
        side=side,
        currency=currency,
        amount=amount,
        gift_slug=slug,
        gift_known=known,
        gift_number=gift_number,
        lang=lang,
        ttl_seconds=ttl,
    )
