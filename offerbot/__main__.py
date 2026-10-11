"""Entry point.

    python -m offerbot                 run the userbot
    python -m offerbot login           sign in once and print a session string
    python -m offerbot check '.buy …'  render a command offline, no session
"""

import asyncio
import logging
import sys
from decimal import Decimal

from .config import Config, ConfigError, load_env_file
from .handlers import register, sniff_lang
from .parser import ParseError, parse
from .rates import RateProvider, Rates
from .render import render_error, render_offer


def _client(config: Config):
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    session = StringSession(config.session) if config.session_is_string else config.session
    client = TelegramClient(session, config.api_id, config.api_hash)
    client.flood_sleep_threshold = config.flood_sleep_threshold
    return client


async def run(config: Config) -> int:
    client = _client(config)
    rates = RateProvider(ttl=config.rate_ttl, star_usd=config.star_usd)

    await client.start()
    me = await client.get_me()
    register(client, config, rates)

    logging.info(
        "signed in as %s (id %s) — type .buy stars 1500 plushpepe 1234 en in any chat",
        me.username or me.first_name, me.id,
    )
    await client.run_until_disconnected()
    return 0


async def login(config: Config) -> int:
    """Interactive sign-in that prints a session string for deployment."""
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    async with TelegramClient(StringSession(), config.api_id, config.api_hash) as client:
        me = await client.get_me()
        print(f"\nSigned in as {me.username or me.first_name} (id {me.id})\n")
        print("Put this in TG_SESSION — it is full access to the account, "
              "treat it like a password:\n")
        print(client.session.save())
    return 0


def check(argv: list[str], config: Config) -> int:
    """Render a command without touching Telegram — useful for tuning templates."""
    if not argv:
        print("usage: python -m offerbot check '.buy stars 1500 plushpepe 1234 en'")
        return 2

    command = " ".join(argv)
    rates = Rates(ton_usd=Decimal("2.84"), ton_rub=Decimal("265.40"), star_usd=config.star_usd)
    try:
        offer = parse(
            command,
            default_lang=config.default_lang,
            default_currency=config.default_currency,
        )
    except ParseError as exc:
        print(render_error(exc.code, sniff_lang(command, config.default_lang), **exc.ctx))
        return 1

    print(render_offer(offer, rates, contact=config.contact, escrow=config.escrow))
    print(f"\npreview url: https://t.me/nft/{offer.gift_slug}-{offer.gift_number}")
    print(f"rates used:  TON=${rates.ton_usd} (sample), star=${rates.star_usd}")
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
