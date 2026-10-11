"""Entry point.

    python -m offerbot                 run the account trigger and the bot
    python -m offerbot login           sign the account in, print a session string
    python -m offerbot check '.buy …'  render a card offline, no session at all
"""

import asyncio
import logging
import sys
from decimal import Decimal

from .bot import OfferBot
from .config import Config, ConfigError, load_env_file
from .handlers import register, sniff_lang
from .parser import ParseError, parse
from .rates import RateProvider, Rates
from .render import (
    button_label,
    render_accepted,
    render_error,
    render_expired,
    render_offer,
)
from .store import OfferStore

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
