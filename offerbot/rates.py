"""Price conversion for the offer card.

Only ever used to decorate a post with an approximate fiat figure, so every
failure path degrades to None and the card is rendered without that line.
A rate lookup must never be the reason a trade offer fails to post.

Uses urllib in a worker thread rather than adding an HTTP client dependency:
one request every few minutes does not justify it.
"""

import asyncio
import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

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
