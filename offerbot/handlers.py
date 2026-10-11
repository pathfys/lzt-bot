"""The user account side: catching the command the owner types.

The account is only the trigger. It cannot post buttons — inline keyboards are
bot-only — so when a bot is configured the card is handed to it; when there is
no bot, or the bot cannot reach the chat, the account posts the card itself
without buttons rather than failing.
"""

import asyncio
import logging
import re
import time

from telethon import events

from .bot import label_for
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
