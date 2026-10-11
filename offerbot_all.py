#!/usr/bin/env python3
"""offerbot — a single-file Telegram gift-offer bot.

Type a command from your own account in any chat:

    .buy stars 1500 plushpepe 1234 en 6h

and a companion bot replaces it with an offer card carrying the gift's
t.me/nft preview and [Accept] / [Decline] buttons. Accepting rewrites the
card into hand-over instructions under a button that opens the recipient's
profile. Offers carry a lifetime (3h/6h/12h/...) and expire on their own.

Inline buttons are bot-only in the Telegram API, so the user account is only
the trigger and a companion bot posts the card. Without BOT_TOKEN the account
posts the card itself, without buttons.

This file is generated from the offerbot package; the package is the source of
truth and ships the test suite. See the README.

Run:
    python offerbot_all.py check '.buy stars 1500 plushpepe 1234 ru 6h'
    python offerbot_all.py login
    python offerbot_all.py
"""


import asyncio
import json
import logging
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from html import escape
from pathlib import Path

from telethon import events, utils
from telethon.errors import rpcerrorlist as errors
from telethon.extensions import html as tg_html
from telethon.tl.functions.messages import EditMessageRequest, SendMediaRequest
from telethon.tl.types import (
    InlineButtonTypeCallback,
    InlineButtonTypeUrl,
    InputInlineButtonTypeUserProfile,
    InputMediaWebPage,
    InputPeerChannel,
    InputPeerChat,
    InputPeerUser,
    KeyboardInlineButton,
    KeyboardInlineButtonRow,
    PeerChannel,
    PeerChat,
    ReplyInlineMarkup,
    UpdateEditChannelMessage,
    UpdateEditMessage,
    UpdateMessageID,
    UpdateNewChannelMessage,
    UpdateNewMessage,
)


__version__ = "0.1.0"

# ======================================================================
# module: offerbot.money
# ======================================================================
# Locale-free money formatting.
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

# ======================================================================
# module: offerbot.gifts
# ======================================================================
# Gift slug handling and public link building.
NFT_LINK_BASE = "https://t.me/nft/"

# Canonical slugs of known collections, keyed by their squashed form.
# Extend at runtime with GIFT_ALIASES_FILE (a JSON {"<any spelling>": "<Slug>"}).
_KNOWN_SLUGS = [
    "PlushPepe", "DurovsCap", "PreciousPeach", "EternalRose", "HeartLocket",
    "LootBag", "SwissWatch", "ScaredCat", "NekoHelmet", "ToyBear",
    "JellyBunny", "MadPumpkin", "HypnoLollipop", "DeskCalendar", "BDayCandle",
    "RecordPlayer", "JesterHat", "SantaHat", "SignetRing", "SpyAgaric",
    "HomemadeCake", "GenieLamp", "LunarSnake", "PartySparkler", "WitchHat",
    "HangingStar", "LoveCandle", "CookieHeart", "SakuraFlower", "SleighBell",
    "GingerCookie", "SpicedWine", "SnowMittens", "WinterWreath", "SnowGlobe",
    "ElectricSkull", "VoodooDoll", "DiamondRing", "CrystalBall", "EternalCandle",
    "BerryBox", "VintageCigar", "MagicPotion", "KissedFrog", "HexPot",
    "EvilEye", "SharpTongue", "TrappedHeart", "SkullFlower", "TopHat",
    "BunnyMuffin", "AstralShard", "FlyingBroom", "CandyCane", "LightSword",
    "RestlessJar", "NailBracelet", "HeroicHelmet", "BondedRing", "PetSnake",
    "SnakeBox", "XmasStocking", "BigYear", "GemSignet", "LowRider",
    "IonGem", "PerfumeBottle", "JoyfulBundle", "WhipCupcake", "StarNotepad",
    "LolPop", "IonicDryer", "StellarRocket", "MoonPendant", "TamaGadget",
    "MiniOscar", "LovePotion", "ToyTrain", "GingerBread", "CupidCharm",
    "ValentineBox", "SnoopDogg", "SnoopCigar", "SwagBag", "WestsideSign",
    "PlushPepeCap",
]


def squash(raw: str) -> str:
    """Collapse any spelling to a comparable key: 'Durov's Cap' -> 'durovscap'."""
    return re.sub(r"[^a-z0-9]", "", raw.lower())


_ALIASES = {squash(slug): slug for slug in _KNOWN_SLUGS}


def _load_extra_aliases() -> None:
    path = os.environ.get("GIFT_ALIASES_FILE")
    if not path:
        return
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return  # a broken alias file must never stop the bot from posting
    for spelling, slug in data.items():
        if isinstance(spelling, str) and isinstance(slug, str) and slug:
            _ALIASES[squash(spelling)] = slug


_load_extra_aliases()


def normalize_slug(raw: str) -> tuple[str, bool]:
    """Return (canonical_slug, is_known).

    An unknown name still produces a best-effort slug so the bot stays usable
    the day a new collection drops — the caller decides whether to warn.
    """
    key = squash(raw)
    if key in _ALIASES:
        return _ALIASES[key], True

    words = re.split(r"[^A-Za-z0-9]+", raw.strip())
    words = [w for w in words if w]
    if len(words) > 1:
        # Multi-word input carries its own boundaries: "plush pepe" -> PlushPepe
        return "".join(w[:1].upper() + w[1:] for w in words), False
    if words and not words[0].islower():
        # Already CamelCase or mixed case — trust what was typed.
        return words[0], False
    return (words[0][:1].upper() + words[0][1:]) if words else "", False


def gift_link(slug: str, number: int) -> str:
    return f"{NFT_LINK_BASE}{slug}-{number}"


#: Names that CamelCase splitting cannot reconstruct (apostrophes, hyphens).
_DISPLAY_OVERRIDES = {
    "DurovsCap": "Durov's Cap",
    "BDayCandle": "B-Day Candle",
    "SnoopDogg": "Snoop Dogg",
    "LolPop": "Lol Pop",
    "XmasStocking": "Xmas Stocking",
}


def gift_title(slug: str) -> str:
    """'PlushPepe' -> 'Plush Pepe' for display inside the post."""
    if slug in _DISPLAY_OVERRIDES:
        return _DISPLAY_OVERRIDES[slug]
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", slug)
    return re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", spaced)


def known_slugs() -> list[str]:
    return sorted(set(_ALIASES.values()))

# ======================================================================
# module: offerbot.parser
# ======================================================================
# Command parsing.
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

# ======================================================================
# module: offerbot.rates
# ======================================================================
# Price conversion for the offer card.
log = logging.getLogger(__name__)

_TIMEOUT = 8
_USER_AGENT = "offerbot/0.1 (+https://t.me)"

#: Telegram does not publish a Stars->fiat rate anywhere machine-readable.
#: This is the in-app purchase price per star, roughly, and is configurable
#: because it drifts with store pricing and region.
DEFAULT_STAR_USD = Decimal(os.environ.get("STAR_USD_RATE", "0.015"))

_COINGECKO = (
    "https://api.coingecko.com/api/v3/simple/price"
    "?ids=the-open-network&vs_currencies=usd,rub"
)
_BINANCE = "https://api.binance.com/api/v3/ticker/price?symbol=TONUSDT"


@dataclass
class Rates:
    """A snapshot of conversion rates. Any field may be None."""

    ton_usd: Decimal | None = None
    ton_rub: Decimal | None = None
    star_usd: Decimal | None = None

    def convert(self, currency: str, amount: Decimal) -> tuple[Decimal | None, Decimal | None]:
        """Return (usd, rub) for `amount` of `currency`, each possibly None."""
        if currency == "gram":
            usd = self.ton_usd * amount if self.ton_usd else None
            rub = self.ton_rub * amount if self.ton_rub else None
            return usd, rub
        if currency == "stars":
            usd = self.star_usd * amount if self.star_usd else None
            if usd is not None and self.ton_usd and self.ton_rub:
                return usd, usd / self.ton_usd * self.ton_rub
            return usd, None
        return None, None


def _fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def _decimal(value) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _from_coingecko() -> Rates:
    payload = _fetch_json(_COINGECKO)["the-open-network"]
    return Rates(ton_usd=_decimal(payload.get("usd")), ton_rub=_decimal(payload.get("rub")))


def _from_binance() -> Rates:
    return Rates(ton_usd=_decimal(_fetch_json(_BINANCE)["price"]))


def _fetch_blocking() -> Rates:
    """CoinGecko first (gives RUB directly), Binance as a USD-only fallback."""
    for source in (_from_coingecko, _from_binance):
        try:
            rates = source()
        except (urllib.error.URLError, OSError, KeyError, ValueError, TypeError) as exc:
            log.warning("rate source %s failed: %s", source.__name__, exc)
            continue
        if rates.ton_usd:
            return rates
    return Rates()


class RateProvider:
    """Caches a snapshot for `ttl` seconds; serializes concurrent refreshes."""

    def __init__(self, ttl: float = 300.0, star_usd: Decimal | None = None):
        self.ttl = ttl
        self.star_usd = star_usd if star_usd is not None else DEFAULT_STAR_USD
        self._cached = Rates()
        self._fetched_at: float | None = None
        self._lock = asyncio.Lock()

    def _is_fresh(self, now: float) -> bool:
        return self._fetched_at is not None and now - self._fetched_at < self.ttl

    async def get(self) -> Rates:
        now = asyncio.get_running_loop().time()
        if self._is_fresh(now):
            return self._cached

        async with self._lock:
            now = asyncio.get_running_loop().time()
            if self._is_fresh(now):
                return self._cached

            fetched = await asyncio.to_thread(_fetch_blocking)
            fetched.star_usd = self.star_usd
            if fetched.ton_usd:
                self._cached = fetched
                self._fetched_at = now
            else:
                # Keep serving the last good snapshot rather than nothing.
                self._cached.star_usd = self.star_usd
                log.warning("all rate sources failed; serving stale/empty rates")
            return self._cached

# ======================================================================
# module: offerbot.render
# ======================================================================
# Rendering the offer card, its follow-up states and the user-facing errors.
CURRENCY_WORD = {"stars": "Stars", "gram": "TON"}

SIDE_LABEL = {
    "en": {"buy": "BUY", "sell": "SELL"},
    "ru": {"buy": "КУПЛЮ", "sell": "ПРОДАМ"},
}

STATE_TITLE = {
    "en": {
        "accepted": "OFFER ACCEPTED",
        "declined": "OFFER DECLINED",
        "cancelled": "OFFER CANCELLED",
        "expired": "OFFER EXPIRED",
    },
    "ru": {
        "accepted": "ОФФЕР ПРИНЯТ",
        "declined": "ОФФЕР ОТКЛОНЁН",
        "cancelled": "ОФФЕР ОТМЕНЁН",
        "expired": "ОФФЕР ИСТЁК",
    },
}

LINES = {
    "en": {
        "price": "Price:",
        "valid": "Valid for:",
        "until": "until",
        "escrow": "Escrow / hold: fine",
        "from": "From:",
        "to": "To:",
        "unknown_gift": "Unknown collection — check the link before paying.",
        "accepted_by": "{who} accepted the offer.",
        "hand_over": "Hand the gift over to {who}.",
        "hand_over_how": (
            "Open the recipient's profile with the button below and send the "
            "NFT from the gift menu. Confirm the deal in DM once it is done."
        ),
        "accepted_at": "Accepted at {when}",
        "declined_body": "The offer is no longer active.",
        "cancelled_body": "Cancelled by the author. The offer is no longer active.",
        "expired_body": "The {ttl} window has run out. The offer is no longer active.",
    },
    "ru": {
        "price": "Цена:",
        "valid": "Действует:",
        "until": "до",
        "escrow": "Гарант / холд: ок",
        "from": "От:",
        "to": "Кому:",
        "unknown_gift": "Коллекция не из списка — проверь ссылку перед оплатой.",
        "accepted_by": "{who} принял оффер.",
        "hand_over": "Передайте подарок пользователю {who}.",
        "hand_over_how": (
            "Откройте профиль получателя кнопкой ниже и отправьте NFT через "
            "меню подарка. После передачи подтвердите сделку в личных сообщениях."
        ),
        "accepted_at": "Принято в {when}",
        "declined_body": "Оффер больше не действует.",
        "cancelled_body": "Оффер отменён автором и больше не действует.",
        "expired_body": "Время оффера вышло ({ttl}). Оффер больше не действует.",
    },
}

BUTTONS = {
    "en": {"accept": "Accept", "decline": "Decline", "transfer": "Transfer NFT"},
    "ru": {"accept": "Принять", "decline": "Отклонить", "transfer": "Передать НФТ"},
}

ALERTS = {
    "en": {
        "own_offer": "This is your own offer.",
        "not_addressed": "This offer is addressed to someone else.",
        "too_late": "Someone accepted it first.",
        "closed": "This offer is already closed.",
        "expired": "This offer has expired.",
        "author_only": "Only the author can cancel this offer.",
        "gone": "This offer is no longer in the bot's records.",
        "accepted_ok": "Accepted. Check the message for what to do next.",
        "declined_ok": "Declined.",
        "cancelled_ok": "Cancelled.",
    },
    "ru": {
        "own_offer": "Это твой собственный оффер.",
        "not_addressed": "Этот оффер адресован другому пользователю.",
        "too_late": "Кто-то принял его раньше.",
        "closed": "Оффер уже закрыт.",
        "expired": "Срок оффера истёк.",
        "author_only": "Отменить оффер может только его автор.",
        "gone": "Этого оффера больше нет в базе бота.",
        "accepted_ok": "Принято. В сообщении написано, что делать дальше.",
        "declined_ok": "Отклонено.",
        "cancelled_ok": "Отменено.",
    },
}

ERRORS = {
    "en": {
        "usage": (
            "Usage: <code>.buy stars 1500 plushpepe 1234 en 6h</code>\n"
            "<code>.buy &lt;stars|gram&gt; &lt;price&gt; &lt;gift&gt; &lt;number&gt; "
            "&lt;en|ru&gt; [3h|6h|12h]</code>"
        ),
        "no_currency": "Which currency? Add <b>stars</b> or <b>gram</b>.",
        "no_amount": "No price in the command.",
        "no_number": "Missing the gift number — add it, or write it as <code>#1234</code>.",
        "no_gift": "No gift name in the command.",
        "ambiguous_numbers": "Too many numbers — leave one price and one <code>#number</code>.",
        "bad_amount": "Price <code>{value}</code> is not a positive number.",
        "bad_number": "Gift number <code>{value}</code> is not valid.",
        "stars_fraction": "Stars are whole units — <code>{value}</code> cannot be paid.",
        "bad_ttl": "Offer lifetime <code>{value}</code> is out of range — use 5m to 7d.",
    },
    "ru": {
        "usage": (
            "Формат: <code>.buy stars 1500 plushpepe 1234 ru 6h</code>\n"
            "<code>.buy &lt;stars|gram&gt; &lt;цена&gt; &lt;подарок&gt; &lt;номер&gt; "
            "&lt;en|ru&gt; [3h|6h|12h]</code>"
        ),
        "no_currency": "Не указана валюта — добавь <b>stars</b> или <b>gram</b>.",
        "no_amount": "В команде нет цены.",
        "no_number": "Нет номера подарка — укажи его или напиши как <code>#1234</code>.",
        "no_gift": "В команде нет названия подарка.",
        "ambiguous_numbers": "Слишком много чисел — оставь одну цену и один <code>#номер</code>.",
        "bad_amount": "Цена <code>{value}</code> — не положительное число.",
        "bad_number": "Номер подарка <code>{value}</code> некорректен.",
        "stars_fraction": "Stars — целые, <code>{value}</code> не оплатить.",
        "bad_ttl": "Срок оффера <code>{value}</code> вне диапазона — от 5m до 7d.",
    },
}

_DURATION_SUFFIX = {
    "en": {"d": "d", "h": "h", "m": "m"},
    "ru": {"d": "д", "h": "ч", "m": "м"},
}


def fmt_duration(seconds: int, lang: str = "en") -> str:
    """21600 -> '6h' / '6ч'. Compound values read as '1h 30m'."""
    suffix = _DURATION_SUFFIX.get(lang, _DURATION_SUFFIX["en"])
    days, rest = divmod(int(seconds), 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    parts = [
        f"{value}{suffix[unit]}"
        for value, unit in ((days, "d"), (hours, "h"), (minutes, "m"))
        if value
    ]
    return " ".join(parts) or f"0{suffix['m']}"


def fmt_deadline(expires_at: float, *, now: float | None = None) -> str:
    """'18:40 UTC', or '12.10 18:40 UTC' when it falls on another day."""
    moment = datetime.fromtimestamp(expires_at, tz=timezone.utc)
    reference = datetime.fromtimestamp(now, tz=timezone.utc) if now else None
    if reference and moment.date() != reference.date():
        return moment.strftime("%d.%m %H:%M UTC")
    return moment.strftime("%H:%M UTC")


def _price(offer: Offer, rates: Rates | None) -> str:
    amount = fmt_amount(
        offer.amount, offer.lang, max_dp=0 if offer.is_integer_currency else 2,
    )
    text = f"<b>{amount} {CURRENCY_WORD[offer.currency]}</b>"
    if rates is None:
        return text

    usd, rub = rates.convert(offer.currency, offer.amount)
    approx = []
    if usd:
        approx.append(f"≈ {fmt_usd(usd, offer.lang)}")
    if rub and offer.lang == "ru":
        approx.append(f"{fmt_amount(rub, 'ru', max_dp=0)} ₽")
    if approx:
        text += f" <i>({' · '.join(approx)})</i>"
    return text


def _gift_ref(offer: Offer) -> str:
    title = escape(f"{gift_title(offer.gift_slug)} #{offer.gift_number}")
    link = escape(gift_link(offer.gift_slug, offer.gift_number), quote=True)
    return f'<a href="{link}">{title}</a>'


def render_offer(
    offer: Offer,
    rates: Rates | None = None,
    *,
    contact: str | None = None,
    target: str | None = None,
    escrow: bool = True,
    expires_at: float | None = None,
    now: float | None = None,
) -> str:
    """The open offer card."""
    lines = LINES[offer.lang]
    body = [
        f"<b>{SIDE_LABEL[offer.lang][offer.side]}</b> · {_gift_ref(offer)}",
        "",
        f"{lines['price']} {_price(offer, rates)}",
    ]

    validity = fmt_duration(offer.ttl_seconds, offer.lang)
    if expires_at:
        validity += f" · {lines['until']} {fmt_deadline(expires_at, now=now)}"
    body.append(f"{lines['valid']} {validity}")

    if escrow:
        body.append(lines["escrow"])
    if contact:
        body.append(f"{lines['from']} {escape(contact)}")
    if target:
        body.append(f"{lines['to']} {escape(target)}")
    if not offer.gift_known:
        body.append(f"<i>{lines['unknown_gift']}</i>")
    return "\n".join(body)


def _closed_header(offer: Offer, state: str) -> list[str]:
    return [
        f"<b>{STATE_TITLE[offer.lang][state]}</b>",
        "",
        f"{_gift_ref(offer)} — {_price(offer, None)}",
        "",
    ]


def render_accepted(
    offer: Offer,
    *,
    acceptor: str,
    receiver: str,
    resolved_at: float | None = None,
) -> str:
    """The card after someone pressed Accept.

    `receiver` is whoever must end up holding the gift: the offer's author on a
    buy, the acceptor on a sell. The text addresses the other side.
    """
    lines = LINES[offer.lang]
    body = _closed_header(offer, "accepted")
    body.append(lines["accepted_by"].format(who=escape(acceptor)))
    body.append("")
    body.append(f"<b>{lines['hand_over'].format(who=escape(receiver))}</b>")
    body.append(lines["hand_over_how"])
    if resolved_at:
        body.append("")
        body.append(
            f"<i>{lines['accepted_at'].format(when=fmt_deadline(resolved_at))}</i>"
        )
    return "\n".join(body)


def render_declined(offer: Offer, *, by_author: bool = False) -> str:
    state = "cancelled" if by_author else "declined"
    body = _closed_header(offer, state)
    body.append(LINES[offer.lang][f"{state}_body"])
    return "\n".join(body)


def render_expired(offer: Offer) -> str:
    body = _closed_header(offer, "expired")
    body.append(
        LINES[offer.lang]["expired_body"].format(
            ttl=fmt_duration(offer.ttl_seconds, offer.lang)
        )
    )
    return "\n".join(body)


def button_label(kind: str, lang: str) -> str:
    return BUTTONS.get(lang, BUTTONS["en"])[kind]


def alert(code: str, lang: str) -> str:
    table = ALERTS.get(lang, ALERTS["en"])
    return table.get(code, code)


def render_error(code: str, lang: str, **ctx) -> str:
    table = ERRORS.get(lang, ERRORS["en"])
    template = table.get(code) or table["usage"]
    safe = {key: escape(str(value)) for key, value in ctx.items()}
    try:
        return template.format(**safe)
    except (KeyError, IndexError):
        return template

# ======================================================================
# module: offerbot.config
# ======================================================================
# Configuration, read from the environment.
class ConfigError(RuntimeError):
    pass


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number, got {raw!r}")


@dataclass(frozen=True)
class Config:
    api_id: int
    api_hash: str
    session: str
    session_is_string: bool

    #: Without a bot token the card is posted by the account itself and has no
    #: buttons: inline keyboards are a bot-only feature of the Telegram API.
    bot_token: str | None = None
    db_path: str = "offers.db"

    default_lang: str = "en"
    default_currency: str | None = None
    contact: str | None = None
    escrow: bool = True

    invert_media: bool = True
    large_media: bool = True
    resend_fallback: bool = True

    error_ttl: float = 12.0
    rate_ttl: float = 300.0
    default_ttl: int = 6 * 3600
    sweep_interval: float = 30.0
    star_usd: Decimal = Decimal("0.015")
    flood_sleep_threshold: int = 60

    @classmethod
    def from_env(cls) -> "Config":
        api_id = os.environ.get("TG_API_ID", "").strip()
        api_hash = os.environ.get("TG_API_HASH", "").strip()
        if not api_id or not api_hash:
            raise ConfigError(
                "TG_API_ID and TG_API_HASH are required — create them at "
                "https://my.telegram.org/apps"
            )
        try:
            api_id_int = int(api_id)
        except ValueError:
            raise ConfigError(f"TG_API_ID must be an integer, got {api_id!r}")

        session_string = os.environ.get("TG_SESSION", "").strip()
        session = session_string or os.environ.get("TG_SESSION_NAME", "offerbot").strip()

        lang = os.environ.get("DEFAULT_LANG", "en").strip().lower()
        if lang not in {"en", "ru"}:
            raise ConfigError(f"DEFAULT_LANG must be en or ru, got {lang!r}")

        currency = os.environ.get("DEFAULT_CURRENCY", "").strip().lower() or None
        if currency not in {None, "stars", "gram"}:
            raise ConfigError(f"DEFAULT_CURRENCY must be stars or gram, got {currency!r}")

        ttl_raw = os.environ.get("DEFAULT_TTL", "6h").strip() or "6h"
        default_ttl = parse_duration(ttl_raw)
        if default_ttl is None:
            try:
                default_ttl = int(ttl_raw)
            except ValueError:
                raise ConfigError(
                    f"DEFAULT_TTL must look like 3h, 90m or a number of seconds, "
                    f"got {ttl_raw!r}"
                )
        if not MIN_TTL <= default_ttl <= MAX_TTL:
            raise ConfigError(
                f"DEFAULT_TTL must be between {MIN_TTL}s and {MAX_TTL}s, "
                f"got {default_ttl}s"
            )

        star_usd_raw = os.environ.get("STAR_USD_RATE", "0.015").strip()
        try:
            star_usd = Decimal(star_usd_raw)
        except InvalidOperation:
            raise ConfigError(f"STAR_USD_RATE must be a number, got {star_usd_raw!r}")

        return cls(
            api_id=api_id_int,
            api_hash=api_hash,
            session=session,
            session_is_string=bool(session_string),
            bot_token=os.environ.get("BOT_TOKEN", "").strip() or None,
            db_path=os.environ.get("DB_PATH", "offers.db").strip() or "offers.db",
            default_lang=lang,
            default_currency=currency,
            contact=os.environ.get("CONTACT", "").strip() or None,
            escrow=_bool("SHOW_ESCROW", True),
            invert_media=_bool("INVERT_MEDIA", True),
            large_media=_bool("LARGE_MEDIA", True),
            resend_fallback=_bool("RESEND_FALLBACK", True),
            error_ttl=_float("ERROR_TTL", 12.0),
            rate_ttl=_float("RATE_TTL", 300.0),
            default_ttl=default_ttl,
            sweep_interval=_float("SWEEP_INTERVAL", 30.0),
            star_usd=star_usd,
            flood_sleep_threshold=int(_float("FLOOD_SLEEP_THRESHOLD", 60)),
        )


def load_env_file(path: str = ".env") -> None:
    """Load KEY=VALUE lines into os.environ without overriding real env vars.

    A three-line dependency is not worth a package; this covers the format
    people actually write in a .env.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.readlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value

# ======================================================================
# module: offerbot.store
# ======================================================================
# Persistent offer state.
PENDING = "pending"
ACCEPTED = "accepted"
DECLINED = "declined"
CANCELLED = "cancelled"
EXPIRED = "expired"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS offers (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id       INTEGER NOT NULL,
    message_id    INTEGER,
    author_id     INTEGER NOT NULL,
    author_label  TEXT    NOT NULL,
    target_id     INTEGER,
    target_label  TEXT,
    side          TEXT    NOT NULL,
    currency      TEXT    NOT NULL,
    amount        TEXT    NOT NULL,
    gift_slug     TEXT    NOT NULL,
    gift_known    INTEGER NOT NULL,
    gift_number   INTEGER NOT NULL,
    lang          TEXT    NOT NULL,
    ttl_seconds   INTEGER NOT NULL,
    created_at    REAL    NOT NULL,
    expires_at    REAL    NOT NULL,
    status        TEXT    NOT NULL,
    acceptor_id   INTEGER,
    acceptor_label TEXT,
    resolved_at   REAL
);
CREATE INDEX IF NOT EXISTS offers_open ON offers (status, expires_at);
"""


@dataclass(frozen=True)
class OfferRecord:
    id: int
    chat_id: int
    message_id: int | None
    author_id: int
    author_label: str
    target_id: int | None
    target_label: str | None
    side: str
    currency: str
    amount: Decimal
    gift_slug: str
    gift_known: bool
    gift_number: int
    lang: str
    ttl_seconds: int
    created_at: float
    expires_at: float
    status: str
    acceptor_id: int | None
    acceptor_label: str | None
    resolved_at: float | None

    def as_offer(self) -> Offer:
        """The pure value object the renderer works with."""
        return Offer(
            side=self.side,
            currency=self.currency,
            amount=self.amount,
            gift_slug=self.gift_slug,
            gift_known=bool(self.gift_known),
            gift_number=self.gift_number,
            lang=self.lang,
            ttl_seconds=self.ttl_seconds,
        )

    @property
    def is_open(self) -> bool:
        return self.status == PENDING

    def receiver(self) -> tuple[int, str]:
        """Who must end up holding the gift, as (user_id, label).

        On a buy the author is paying, so the gift goes to them; on a sell the
        author owns it and the acceptor receives it.
        """
        if self.side == "buy":
            return self.author_id, self.author_label
        return self.acceptor_id, self.acceptor_label

    def giver(self) -> tuple[int, str]:
        """The counterparty of `receiver` — the one who hands the gift over."""
        if self.side == "buy":
            return self.acceptor_id, self.acceptor_label
        return self.author_id, self.author_label


def _record(row: sqlite3.Row) -> OfferRecord:
    data = dict(row)
    data["amount"] = Decimal(data["amount"])
    data["gift_known"] = bool(data["gift_known"])
    return OfferRecord(**data)


class OfferStore:
    def __init__(self, path: str = "offers.db"):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.executescript(_SCHEMA)

    def close(self) -> None:
        self._db.close()

    # ---- writes ----

    def create(
        self,
        offer: Offer,
        *,
        chat_id: int,
        author_id: int,
        author_label: str,
        now: float,
        target_id: int | None = None,
        target_label: str | None = None,
    ) -> OfferRecord:
        cursor = self._db.execute(
            """
            INSERT INTO offers (
                chat_id, author_id, author_label, target_id, target_label,
                side, currency, amount, gift_slug, gift_known, gift_number,
                lang, ttl_seconds, created_at, expires_at, status
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                chat_id, author_id, author_label, target_id, target_label,
                offer.side, offer.currency, str(offer.amount), offer.gift_slug,
                int(offer.gift_known), offer.gift_number, offer.lang,
                offer.ttl_seconds, now, now + offer.ttl_seconds, PENDING,
            ),
        )
        return self.get(cursor.lastrowid)

    def drop(self, offer_id: int) -> None:
        """Remove an offer whose card never reached the chat.

        Without this, every command typed in a chat the bot cannot post to
        would leave a pending row behind that nothing can ever resolve.
        """
        self._db.execute("DELETE FROM offers WHERE id = ?", (offer_id,))

    def attach_message(self, offer_id: int, message_id: int) -> None:
        self._db.execute(
            "UPDATE offers SET message_id = ? WHERE id = ?", (message_id, offer_id)
        )

    def accept(
        self, offer_id: int, *, acceptor_id: int, acceptor_label: str, now: float
    ) -> OfferRecord | None:
        """Atomic first-come-wins. None means someone else got there first."""
        cursor = self._db.execute(
            """
            UPDATE offers
               SET status = ?, acceptor_id = ?, acceptor_label = ?, resolved_at = ?
             WHERE id = ? AND status = ? AND expires_at > ?
            """,
            (ACCEPTED, acceptor_id, acceptor_label, now, offer_id, PENDING, now),
        )
        if cursor.rowcount != 1:
            return None
        return self.get(offer_id)

    def close_offer(self, offer_id: int, status: str, now: float) -> OfferRecord | None:
        cursor = self._db.execute(
            """
            UPDATE offers SET status = ?, resolved_at = ?
             WHERE id = ? AND status = ?
            """,
            (status, now, offer_id, PENDING),
        )
        if cursor.rowcount != 1:
            return None
        return self.get(offer_id)

    def expire_due(self, now: float) -> list[OfferRecord]:
        """Mark every overdue pending offer expired and return those rows."""
        rows = self._db.execute(
            "SELECT id FROM offers WHERE status = ? AND expires_at <= ?",
            (PENDING, now),
        ).fetchall()
        expired = []
        for row in rows:
            record = self.close_offer(row["id"], EXPIRED, now)
            if record:
                expired.append(record)
        return expired

    # ---- reads ----

    def get(self, offer_id: int) -> OfferRecord | None:
        row = self._db.execute(
            "SELECT * FROM offers WHERE id = ?", (offer_id,)
        ).fetchone()
        return _record(row) if row else None

    def open_offers(self) -> list[OfferRecord]:
        rows = self._db.execute(
            "SELECT * FROM offers WHERE status = ? ORDER BY expires_at", (PENDING,)
        ).fetchall()
        return [_record(row) for row in rows]

# ======================================================================
# module: offerbot.buttons
# ======================================================================
# Inline keyboards.
log = logging.getLogger(__name__)

ACCEPT = "a"
DECLINE = "d"

CALLBACK_RE = re.compile(rb"^o:(\d+):([ad])$")


def callback_data(offer_id: int, action: str) -> bytes:
    """Callback payloads are capped at 64 bytes, so keep this terse."""
    data = f"o:{offer_id}:{action}".encode()
    if len(data) > 64:
        raise ValueError("callback data too long")
    return data


def offer_keyboard(offer_id: int, lang: str) -> ReplyInlineMarkup:
    return ReplyInlineMarkup(rows=[
        KeyboardInlineButtonRow(buttons=[
            KeyboardInlineButton(
                text=button_label("accept", lang),
                type=InlineButtonTypeCallback(data=callback_data(offer_id, ACCEPT)),
            ),
            KeyboardInlineButton(
                text=button_label("decline", lang),
                type=InlineButtonTypeCallback(data=callback_data(offer_id, DECLINE)),
            ),
        ]),
    ])


async def profile_button(
    client, label: str, user_id: int, username: str | None = None
) -> KeyboardInlineButton:
    """A button that takes the presser to `user_id`'s profile.

    Three ways in, most faithful first:

    1. `InputInlineButtonTypeUserProfile` opens the profile card itself, but
       the bot needs the user's access hash — it only has that for users it
       has actually seen (anyone who pressed a button, for instance).
    2. A plain t.me link, which works for anyone with a username.
    3. `tg://user?id=` as a last resort for a hash-less, username-less user.
    """
    try:
        entity = await client.get_input_entity(user_id)
        return KeyboardInlineButton(
            text=label, type=InputInlineButtonTypeUserProfile(user_id=entity),
        )
    except (ValueError, TypeError) as exc:
        log.debug("no cached entity for %s: %s", user_id, exc)

    if username:
        return KeyboardInlineButton(
            text=label,
            type=InlineButtonTypeUrl(url=f"https://t.me/{username.lstrip('@')}"),
        )

    return KeyboardInlineButton(
        text=label, type=InlineButtonTypeUrl(url=f"tg://user?id={user_id}"),
    )


async def transfer_keyboard(
    client, lang: str, user_id: int, username: str | None = None
) -> ReplyInlineMarkup:
    button = await profile_button(
        client, button_label("transfer", lang), user_id, username,
    )
    return ReplyInlineMarkup(rows=[KeyboardInlineButtonRow(buttons=[button])])

# ======================================================================
# module: offerbot.poster
# ======================================================================
# Putting the card into the chat with the gift preview attached.
log = logging.getLogger(__name__)

#: Telegram could not build a preview for the URL — post without the picture.
PREVIEW_ERRORS = (
    errors.WebpageCurlFailedError,
    errors.WebpageMediaEmptyError,
    errors.MediaEmptyError,
    errors.MediaInvalidError,
)

#: The original message can no longer be edited — post a fresh one instead.
EDIT_IMPOSSIBLE = (
    errors.MessageIdInvalidError,
    errors.MsgIdInvalidError,
    errors.MessageAuthorRequiredError,
)

#: Nothing will make this chat accept the message.
WRITE_REFUSED = (
    errors.ChatWriteForbiddenError,
    errors.ChatSendPlainForbiddenError,
    errors.UserBannedInChannelError,
)


class DeliveryError(Exception):
    """Delivery failed in a way worth telling the owner about."""

    def __init__(self, reason: str, retry_after: int | None = None):
        super().__init__(reason)
        self.reason = reason
        self.retry_after = retry_after


def web_preview(url: str, *, large: bool = True) -> InputMediaWebPage:
    return InputMediaWebPage(
        url=url,
        force_large_media=True if large else None,
        force_small_media=None if large else True,
        optional=True,
    )


async def deliver(
    client,
    event,
    html_text: str,
    preview_url: str,
    *,
    invert_media: bool = True,
    large_media: bool = True,
    resend_fallback: bool = True,
) -> str:
    """Replace the owner's command with the rendered card.

    Returns a short status for logging: ``edited``, ``edited_no_preview``,
    ``resent`` or ``resent_no_preview``.
    """
    message, entities = tg_html.parse(html_text)
    if not message.strip():
        raise DeliveryError("empty message")

    peer = await event.get_input_chat()
    media = web_preview(preview_url, large=large_media)

    async def edit(with_media):
        await client(EditMessageRequest(
            peer=peer,
            id=event.id,
            message=message,
            entities=entities,
            media=with_media,
            invert_media=invert_media if with_media else None,
        ))

    async def send(with_media):
        # Editing is preferred, but a fresh message is the only way out if the
        # original is gone. The forced preview is kept identical on this path.
        if with_media:
            await client(SendMediaRequest(
                peer=peer,
                media=with_media,
                message=message,
                entities=entities,
                invert_media=invert_media,
            ))
        else:
            await client.send_message(
                peer, message, formatting_entities=entities, link_preview=True,
            )
        try:
            await client.delete_messages(peer, [event.id])
        except Exception as exc:  # the card is already posted; this is cosmetic
            log.warning("could not delete the original command: %s", exc)

    for attempt, (action, with_media, status) in enumerate((
        (edit, media, "edited"),
        (edit, None, "edited_no_preview"),
        (send, media, "resent"),
        (send, None, "resent_no_preview"),
    )):
        if action is send and not resend_fallback:
            break
        try:
            await action(with_media)
            return status
        except errors.MessageNotModifiedError:
            return status  # already says exactly this; nothing to do
        except PREVIEW_ERRORS as exc:
            log.warning("preview rejected for %s: %s", preview_url, exc)
            continue  # same action, no media
        except EDIT_IMPOSSIBLE as exc:
            log.warning("cannot edit message %s: %s", event.id, exc)
            if not resend_fallback:
                raise DeliveryError("message is no longer editable") from exc
            continue
        except errors.SlowModeWaitError as exc:
            # Edits are not slow-mode limited, so this only bites the resend
            # path. Reporting beats silently waiting out a 24h slow mode.
            raise DeliveryError("slow mode", retry_after=exc.seconds) from exc
        except errors.FloodWaitError as exc:
            raise DeliveryError("flood wait", retry_after=exc.seconds) from exc
        except WRITE_REFUSED as exc:
            raise DeliveryError("cannot post in this chat") from exc
        except errors.MessageTooLongError as exc:
            raise DeliveryError("message too long") from exc

    raise DeliveryError("could not deliver the offer")


async def autodelete(client, peer, message_id: int, delay: float) -> None:
    """Remove a transient notice after `delay` seconds, best effort."""
    if delay <= 0:
        return
    await asyncio.sleep(delay)
    try:
        await client.delete_messages(peer, [message_id])
    except Exception as exc:
        log.debug("autodelete failed: %s", exc)

# ======================================================================
# module: offerbot.bot
# ======================================================================
# The bot side: posting the card, handling the buttons, expiring offers.
log = logging.getLogger(__name__)


def _message_id(result) -> int | None:
    """Dig the new message id out of the Updates a raw send returns."""
    for update in getattr(result, "updates", []) or []:
        if isinstance(update, UpdateMessageID):
            return update.id
        if isinstance(update, (UpdateNewMessage, UpdateNewChannelMessage,
                               UpdateEditMessage, UpdateEditChannelMessage)):
            return update.message.id
    return getattr(result, "id", None)


def label_for(entity, user_id: int) -> str:
    """'@nick' when there is a username, a display name otherwise, id last.

    Reads the attributes directly instead of `utils.get_display_name`, whose
    isinstance check makes it return nothing for anything but a concrete
    Telethon type.
    """
    username = getattr(entity, "username", None)
    if username:
        return f"@{username}"
    parts = [getattr(entity, "first_name", None), getattr(entity, "last_name", None)]
    name = " ".join(part for part in parts if part).strip()
    return name or getattr(entity, "title", None) or str(user_id)


def username_of(label: str | None) -> str | None:
    """Labels are '@nick' when a username exists and a display name otherwise."""
    if label and label.startswith("@") and len(label) > 1:
        return label[1:]
    return None


class OfferBot:
    """Posts offer cards and owns their lifecycle."""

    def __init__(self, client, config, store: OfferStore, rates, clock=time.time):
        self._client = client
        self._config = config
        self._store = store
        self._rates = rates
        #: Injected so expiry is testable without waiting hours.
        self._clock = clock
        self._sweeper: asyncio.Task | None = None

    # ---- posting ----

    async def peer(self, chat_id: int):
        """Resolve a chat for the bot.

        A chat's access hash is per-account, so the user account's copy is
        useless here. Bots may pass 0 for peers they can reach, which is the
        fallback when the bot's own cache has never seen the chat.
        """
        try:
            return await self._client.get_input_entity(chat_id)
        except (ValueError, TypeError):
            real_id, kind = utils.resolve_id(chat_id)
            if kind is PeerChannel:
                return InputPeerChannel(real_id, 0)
            if kind is PeerChat:
                return InputPeerChat(real_id)
            return InputPeerUser(real_id, 0)

    async def post(
        self,
        chat_id: int,
        offer,
        *,
        author_id: int,
        author_label: str,
        target_id: int | None = None,
        target_label: str | None = None,
    ) -> OfferRecord:
        """Create the offer and put its card in the chat. Raises on failure."""
        now = self._clock()
        record = self._store.create(
            offer,
            chat_id=chat_id,
            author_id=author_id,
            author_label=author_label,
            now=now,
            target_id=target_id,
            target_label=target_label,
        )

        body = render_offer(
            offer,
            await self._rates.get(),
            contact=author_label,
            target=target_label,
            escrow=self._config.escrow,
            expires_at=record.expires_at,
            now=now,
        )
        message, entities = tg_html.parse(body)

        try:
            result = await self._client(SendMediaRequest(
                peer=await self.peer(chat_id),
                media=web_preview(
                    gift_link(offer.gift_slug, offer.gift_number),
                    large=self._config.large_media,
                ),
                message=message,
                entities=entities,
                invert_media=self._config.invert_media,
                reply_markup=offer_keyboard(record.id, offer.lang),
            ))
        except Exception:
            # The card is what makes an offer real; a row without one is
            # unresolvable, so it does not get to stay.
            self._store.drop(record.id)
            raise

        message_id = _message_id(result)
        if message_id:
            self._store.attach_message(record.id, message_id)
        else:
            log.warning("posted offer %s but could not read its message id", record.id)
        return self._store.get(record.id)

    # ---- editing a card in place ----

    async def _rewrite(self, record: OfferRecord, body: str, keyboard) -> None:
        """Replace a card's text and keyboard, keeping the gift preview.

        The media is passed again on purpose: an edit that omits it leaves the
        preview up to the server, and the picture is the point of the card.
        """
        if not record.message_id:
            return
        message, entities = tg_html.parse(body)
        media = web_preview(
            gift_link(record.gift_slug, record.gift_number),
            large=self._config.large_media,
        )
        request = EditMessageRequest(
            peer=await self.peer(record.chat_id),
            id=record.message_id,
            message=message,
            entities=entities,
            media=media,
            invert_media=self._config.invert_media,
            reply_markup=keyboard,
        )
        try:
            await self._client(request)
        except errors.MessageNotModifiedError:
            pass
        except errors.RPCError as exc:
            # An empty keyboard is how a closed card drops its buttons; if the
            # server will not take it, the card still reads as closed and the
            # buttons answer "already closed".
            if keyboard is not None and not keyboard.rows:
                log.warning("could not clear buttons on offer %s: %s", record.id, exc)
                request.reply_markup = None
                await self._client(request)
            else:
                raise

    async def _close_card(self, record: OfferRecord, body: str) -> None:
        await self._rewrite(record, body, ReplyInlineMarkup(rows=[]))

    # ---- buttons ----

    def register(self) -> None:
        @self._client.on(events.CallbackQuery(pattern=CALLBACK_RE))
        async def on_press(event):
            match = CALLBACK_RE.match(event.data)
            if not match:
                return
            offer_id = int(match.group(1))
            action = match.group(2).decode()
            await self._handle_press(event, offer_id, action)

    async def _handle_press(self, event, offer_id: int, action: str) -> None:
        record = self._store.get(offer_id)
        if record is None:
            await event.answer(alert("gone", self._config.default_lang), alert=True)
            return

        lang = record.lang
        now = self._clock()

        if not record.is_open:
            code = "expired" if record.status == EXPIRED else "closed"
            await event.answer(alert(code, lang), alert=True)
            return

        if record.expires_at <= now:
            expired = self._store.close_offer(record.id, EXPIRED, now)
            if expired:
                await self._close_card(expired, render_expired(expired.as_offer()))
            await event.answer(alert("expired", lang), alert=True)
            return

        if action == ACCEPT:
            await self._accept(event, record, now)
        else:
            await self._decline(event, record, now)

    async def _accept(self, event, record: OfferRecord, now: float) -> None:
        lang = record.lang
        presser = event.sender_id

        if presser == record.author_id:
            await event.answer(alert("own_offer", lang), alert=True)
            return
        if record.target_id and presser != record.target_id:
            await event.answer(alert("not_addressed", lang), alert=True)
            return

        accepted = self._store.accept(
            record.id,
            acceptor_id=presser,
            acceptor_label=label_for(await event.get_sender(), presser),
            now=now,
        )
        if accepted is None:
            await event.answer(alert("too_late", lang), alert=True)
            return

        receiver_id, receiver_label = accepted.receiver()
        body = render_accepted(
            accepted.as_offer(),
            acceptor=accepted.acceptor_label,
            receiver=receiver_label,
            resolved_at=now,
        )
        keyboard = await transfer_keyboard(
            self._client, lang, receiver_id, username_of(receiver_label),
        )
        await self._rewrite(accepted, body, keyboard)
        await event.answer(alert("accepted_ok", lang))
        log.info(
            "offer %s accepted by %s; %s hands the gift to %s",
            accepted.id, presser, accepted.giver()[1], receiver_label,
        )

    async def _decline(self, event, record: OfferRecord, now: float) -> None:
        lang = record.lang
        presser = event.sender_id
        by_author = presser == record.author_id

        if not by_author and presser != record.target_id:
            # A public offer is not something a bystander can close.
            await event.answer(alert("author_only", lang), alert=True)
            return

        closed = self._store.close_offer(
            record.id, CANCELLED if by_author else DECLINED, now,
        )
        if closed is None:
            await event.answer(alert("closed", lang), alert=True)
            return

        await self._close_card(closed, render_declined(closed.as_offer(), by_author=by_author))
        await event.answer(
            alert("cancelled_ok" if by_author else "declined_ok", lang)
        )
        log.info("offer %s %s by %s", closed.id, closed.status, presser)

    # ---- expiry ----

    async def sweep_once(self) -> int:
        expired = self._store.expire_due(self._clock())
        for record in expired:
            try:
                await self._close_card(record, render_expired(record.as_offer()))
            except errors.RPCError as exc:
                log.warning("could not close expired offer %s: %s", record.id, exc)
        return len(expired)

    def start_sweeper(self) -> None:
        """Expire offers on a timer.

        A sweep rather than a timer per offer: it survives restarts for free
        and cannot leak tasks.
        """
        async def loop():
            while True:
                try:
                    count = await self.sweep_once()
                    if count:
                        log.info("expired %s offer(s)", count)
                except Exception as exc:
                    log.exception("sweep failed: %s", exc)
                await asyncio.sleep(self._config.sweep_interval)

        self._sweeper = asyncio.create_task(loop())

# ======================================================================
# module: offerbot.handlers
# ======================================================================
# The user account side: catching the command the owner types.
log = logging.getLogger(__name__)

#: Only an exact command head triggers the bot. The rendered card never starts
#: like this, so the bot cannot re-trigger on its own output.
COMMAND_PATTERN = re.compile(
    r"^[.!/](buy|sell|b|s|куплю|покупаю|продам|продаю)(\s|$)",
    re.IGNORECASE,
)

_LANG_SNIFF = re.compile(r"(?:^|\s)(en|eng|english|ru|rus|russian|рус)(?:\s|$)", re.IGNORECASE)


def sniff_lang(text: str, default: str) -> str:
    """Best-effort language for an error message about an unparseable command."""
    match = _LANG_SNIFF.search(text)
    if not match:
        return default
    return "ru" if match.group(1).lower() in {"ru", "rus", "russian", "рус"} else "en"


async def notice(client, event, html_text: str, config: Config) -> None:
    """Turn the command into a short notice and clean it up afterwards."""
    try:
        peer = await event.get_input_chat()
        await client.edit_message(
            peer, event.id, html_text, parse_mode="html", link_preview=False,
        )
    except Exception as exc:
        log.warning("could not show notice: %s", exc)
        return
    asyncio.create_task(autodelete(client, peer, event.id, config.error_ttl))


async def _target_of(event, own_id: int) -> tuple[int | None, str | None]:
    """An offer sent as a reply is addressed to that person, and only they may
    accept or decline it. Without a reply the offer is public."""
    if not event.is_reply:
        return None, None
    replied = await event.get_reply_message()
    if replied is None or not replied.sender_id or replied.sender_id == own_id:
        return None, None
    return replied.sender_id, label_for(await replied.get_sender(), replied.sender_id)


def register(client, config: Config, rates: RateProvider, offer_bot=None) -> None:
    identity: dict = {}

    async def me():
        if "me" not in identity:
            account = await client.get_me()
            identity["me"] = account
            identity["label"] = config.contact or label_for(account, account.id)
        return identity["me"], identity["label"]

    @client.on(events.NewMessage(outgoing=True, pattern=COMMAND_PATTERN))
    async def on_offer_command(event):
        text = event.raw_text or ""
        try:
            offer = parse(
                text,
                default_lang=config.default_lang,
                default_currency=config.default_currency,
                default_ttl=config.default_ttl,
            )
        except ParseError as exc:
            lang = sniff_lang(text, config.default_lang)
            await notice(client, event, render_error(exc.code, lang, **exc.ctx), config)
            return

        account, author_label = await me()
        target_id, target_label = await _target_of(event, account.id)

        if offer_bot is not None:
            try:
                record = await offer_bot.post(
                    event.chat_id, offer,
                    author_id=account.id,
                    author_label=author_label,
                    target_id=target_id,
                    target_label=target_label,
                )
            except Exception as exc:
                # Most often: the bot is not a member of this chat. The offer
                # is worth more than its buttons, so fall through.
                log.warning("bot could not post in %s (%s); posting without buttons",
                            event.chat_id, exc)
            else:
                try:
                    await event.delete()
                except Exception as exc:
                    log.warning("card posted but the command stayed: %s", exc)
                log.info(
                    "offer %s posted with buttons in %s (%s %s %s-%s, %ss)",
                    record.id, event.chat_id, offer.side, offer.currency,
                    offer.gift_slug, offer.gift_number, offer.ttl_seconds,
                )
                return

        now = time.time()
        body = render_offer(
            offer, await rates.get(),
            contact=author_label,
            target=target_label,
            escrow=config.escrow,
            expires_at=now + offer.ttl_seconds,
            now=now,
        )
        try:
            status = await deliver(
                client, event, body,
                gift_link(offer.gift_slug, offer.gift_number),
                invert_media=config.invert_media,
                large_media=config.large_media,
                resend_fallback=config.resend_fallback,
            )
        except DeliveryError as exc:
            wait = f" ({exc.retry_after}s)" if exc.retry_after else ""
            await notice(client, event, f"{exc.reason}{wait}", config)
            log.warning("delivery failed in %s: %s%s", event.chat_id, exc.reason, wait)
            return

        log.info(
            "%s (no buttons) %s %s %s-%s -> %s",
            status, offer.side, offer.currency, offer.gift_slug,
            offer.gift_number, event.chat_id,
        )

# ======================================================================
# module: offerbot.__main__
# ======================================================================
# Entry point.
log = logging.getLogger(__name__)


def _user_client(config: Config):
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    session = StringSession(config.session) if config.session_is_string else config.session
    client = TelegramClient(session, config.api_id, config.api_hash)
    client.flood_sleep_threshold = config.flood_sleep_threshold
    return client


async def run(config: Config) -> int:
    from telethon import TelegramClient

    store = OfferStore(config.db_path)
    rates = RateProvider(ttl=config.rate_ttl, star_usd=config.star_usd)

    user = _user_client(config)
    await user.start()
    account = await user.get_me()

    bot_client = None
    offer_bot = None
    if config.bot_token:
        # The bot needs its own session: a bot and a user cannot share one.
        bot_client = TelegramClient(
            f"{config.session}-bot" if not config.session_is_string else "offerbot-bot",
            config.api_id,
            config.api_hash,
        )
        bot_client.flood_sleep_threshold = config.flood_sleep_threshold
        await bot_client.start(bot_token=config.bot_token)
        bot_account = await bot_client.get_me()

        offer_bot = OfferBot(bot_client, config, store, rates)
        offer_bot.register()
        offer_bot.start_sweeper()
        log.info(
            "bot @%s is live — add it to a chat and offers there get buttons",
            bot_account.username,
        )
    else:
        log.warning(
            "BOT_TOKEN is not set: cards will be posted without buttons "
            "(inline keyboards are bot-only in the Telegram API)"
        )

    register(user, config, rates, offer_bot=offer_bot)
    log.info(
        "signed in as %s — type .buy stars 1500 plushpepe 1234 en 6h in any chat",
        account.username or account.first_name,
    )

    waiters = [user.run_until_disconnected()]
    if bot_client is not None:
        waiters.append(bot_client.run_until_disconnected())
    try:
        await asyncio.gather(*waiters)
    finally:
        store.close()
    return 0


async def login(config: Config) -> int:
    """Interactive sign-in that prints a session string for deployment."""
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    async with TelegramClient(StringSession(), config.api_id, config.api_hash) as client:
        account = await client.get_me()
        print(f"\nSigned in as {account.username or account.first_name} (id {account.id})\n")
        print("Put this in TG_SESSION — it is full access to the account, "
              "treat it like a password:\n")
        print(client.session.save())
    return 0


def check(argv: list[str], config: Config) -> int:
    """Render every state of a card without touching Telegram."""
    if not argv:
        print("usage: python -m offerbot check '.buy stars 1500 plushpepe 1234 en 6h'")
        return 2

    command = " ".join(argv)
    rates = Rates(ton_usd=Decimal("2.84"), ton_rub=Decimal("265.40"), star_usd=config.star_usd)
    try:
        offer = parse(
            command,
            default_lang=config.default_lang,
            default_currency=config.default_currency,
            default_ttl=config.default_ttl,
        )
    except ParseError as exc:
        print(render_error(exc.code, sniff_lang(command, config.default_lang), **exc.ctx))
        return 1

    author = config.contact or "@you"
    expires_at = 1760000000 + offer.ttl_seconds
    lang = offer.lang

    print("---------- posted card ----------")
    print(render_offer(offer, rates, contact=author, escrow=config.escrow,
                       expires_at=expires_at, now=1760000000))
    print(f"[ {button_label('accept', lang)} ] [ {button_label('decline', lang)} ]")

    print("\n---------- after Accept ----------")
    receiver = author if offer.side == "buy" else "@buyer"
    print(render_accepted(offer, acceptor="@buyer", receiver=receiver,
                          resolved_at=1760000000))
    print(f"[ {button_label('transfer', lang)} ]  -> opens {receiver}'s profile")

    print("\n---------- after expiry ----------")
    print(render_expired(offer))

    print(f"\npreview url: https://t.me/nft/{offer.gift_slug}-{offer.gift_number}")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    load_env_file()

    try:
        config = Config.from_env()
    except ConfigError as exc:
        if argv and argv[0] == "check":
            # Rendering needs no credentials; let people try the card first.
            config = Config(api_id=0, api_hash="", session="", session_is_string=False)
        else:
            print(f"config error: {exc}", file=sys.stderr)
            return 2

    command = argv[0] if argv else "run"
    if command == "check":
        return check(argv[1:], config)
    if command == "login":
        return asyncio.run(login(config))
    if command == "run":
        return asyncio.run(run(config))

    print(f"unknown command: {command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
