"""Configuration, read from the environment.

The session string is the one genuinely dangerous value here: it grants full
access to the account without a password or 2FA, so it is read from the
environment (or a file outside the repo) and never logged.
"""

import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from .parser import MAX_TTL, MIN_TTL, parse_duration


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
