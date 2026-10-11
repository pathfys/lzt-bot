"""Wiring the command to the chat."""

import asyncio
import logging
import re

from telethon import events

from .config import Config
from .gifts import gift_link
from .parser import ParseError, parse
from .poster import DeliveryError, autodelete, deliver
from .rates import RateProvider
from .render import render_error, render_offer

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
        await client.edit_message(
            await event.get_input_chat(), event.id, html_text,
            parse_mode="html", link_preview=False,
        )
    except Exception as exc:
        log.warning("could not show notice: %s", exc)
        return
    asyncio.create_task(
        autodelete(client, await event.get_input_chat(), event.id, config.error_ttl)
    )


def register(client, config: Config, rates: RateProvider) -> None:
    @client.on(events.NewMessage(outgoing=True, pattern=COMMAND_PATTERN))
    async def on_offer_command(event):
        text = event.raw_text or ""
        try:
            offer = parse(
                text,
                default_lang=config.default_lang,
                default_currency=config.default_currency,
            )
        except ParseError as exc:
            lang = sniff_lang(text, config.default_lang)
            await notice(client, event, render_error(exc.code, lang, **exc.ctx), config)
            return

        snapshot = await rates.get()
        body = render_offer(
            offer, snapshot, contact=config.contact, escrow=config.escrow,
        )
        url = gift_link(offer.gift_slug, offer.gift_number)

        try:
            status = await deliver(
                client, event, body, url,
                invert_media=config.invert_media,
                large_media=config.large_media,
                resend_fallback=config.resend_fallback,
            )
        except DeliveryError as exc:
            wait = f" ({exc.retry_after}s)" if exc.retry_after else ""
            await notice(client, event, f"⚠️ {exc.reason}{wait}", config)
            log.warning("delivery failed in %s: %s%s", event.chat_id, exc.reason, wait)
            return

        log.info(
            "%s %s %s %s-%s -> %s",
            status, offer.side, offer.currency, offer.gift_slug, offer.gift_number,
            event.chat_id,
        )
