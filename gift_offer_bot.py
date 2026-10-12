#!/usr/bin/env python3
"""gift_offer_bot — a plain Telegram BOT (Bot API, token only, no account session).

You type, in a chat the bot can see:

    .buy https://t.me/nft/LibertyFigure-181692 1500 stars

and the bot posts an offer card: the gift link with its preview, the price,
and two buttons under it — «Принять» / «Отклонить» (or Accept / Decline).

The gift is given by its LINK, pasted straight into the command — no name
lookup, no account session. This is "automation" the simple way: a bot with a
token from @BotFather. Inline buttons are a bot-only Telegram feature, which is
exactly why this is a bot and not a userbot.

Pressing «Принять» rewrites the card into a hand-over instruction with a button
that opens the counterparty's profile; «Отклонить» closes it.

Run:
    pip install aiogram
    BOT_TOKEN=123:abc python gift_offer_bot.py

Try the rendering with no token and no network:
    python gift_offer_bot.py check '.buy https://t.me/nft/LibertyFigure-181692 1500 stars ru'
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from html import escape

log = logging.getLogger("gift_offer_bot")

# ---------------------------------------------------------------------------
# Command grammar
#
#   .buy  <gift link> <price...> [en|ru]
#   .sell <gift link> <price...> [en|ru]
#
# The gift is a t.me/nft/<Slug>-<number> link pasted into the command. The
# price is whatever you type after it (a number plus an optional unit word);
# the last bare en/ru token, if any, picks the language.
# ---------------------------------------------------------------------------

COMMAND_RE = re.compile(r"^[.!/](buy|sell|куплю|продам|покупаю|продаю)\b(.*)$", re.IGNORECASE | re.DOTALL)

SIDE = {
    "buy": "buy", "куплю": "buy", "покупаю": "buy",
    "sell": "sell", "продам": "sell", "продаю": "sell",
}

# t.me/nft/<Slug>-<number>, however it was pasted (with https://, @, tg:// …).
NFT_LINK_RE = re.compile(
    r"(?:https?://)?(?:t\.me|telegram\.me|telegram\.dog)/nft/([A-Za-z0-9]+)-(\d+)",
    re.IGNORECASE,
)

LANGS = {
    "en": "en", "eng": "en", "english": "en",
    "ru": "ru", "rus": "ru", "russian": "ru", "рус": "ru",
}

# Optional currency unit, only to prettify the price line.
CURRENCY_WORD = {
    "stars": "Stars", "star": "Stars", "⭐": "Stars", "⭐️": "Stars",
    "звезд": "Stars", "звёзд": "Stars", "звезды": "Stars", "звёзды": "Stars",
    "ton": "TON", "toncoin": "TON", "gram": "TON", "💎": "TON", "тон": "TON",
}

_PRICE_RE = re.compile(r"^(\d+(?:[.,]\d+)?)\s*(.*)$", re.DOTALL)


# ---------------------------------------------------------------------------
# Texts (ru default — the buttons the owner asked for are Принять / Отклонить)
# ---------------------------------------------------------------------------

TEXT = {
    "ru": {
        "buy": "ПОКУПАЮ", "sell": "ПРОДАЮ",
        "price": "Цена:",
        "accept": "Принять", "decline": "Отклонить", "transfer": "Передать НФТ",
        "accepted": "ОФФЕР ПРИНЯТ",
        "declined": "ОФФЕР ОТКЛОНЁН",
        "cancelled": "ОФФЕР ОТМЕНЁН",
        "accepted_by": "{who} принял оффер.",
        "hand_over": "Передайте подарок пользователю {who}.",
        "hand_over_how": "Откройте его профиль кнопкой ниже и отправьте NFT через меню подарка.",
        "closed_body": "Оффер больше не активен.",
        "a_own": "Это твой собственный оффер.",
        "a_taken": "Оффер уже закрыт.",
        "a_author_only": "Отклонить оффер может только автор.",
        "a_gone": "Этого оффера больше нет.",
        "a_ok_accept": "Принято. Смотри сообщение.",
        "a_ok_decline": "Отклонено.",
        "usage": (
            "Формат: <code>.buy ссылка цена [en|ru]</code>\n"
            "Пример: <code>.buy https://t.me/nft/LibertyFigure-181692 1500 stars</code>"
        ),
        "bad_link": "Не вижу ссылку на подарок вида <code>t.me/nft/Название-номер</code>.",
        "no_price": "Не указана цена.",
    },
    "en": {
        "buy": "BUYING", "sell": "SELLING",
        "price": "Price:",
        "accept": "Accept", "decline": "Decline", "transfer": "Transfer NFT",
        "accepted": "OFFER ACCEPTED",
        "declined": "OFFER DECLINED",
        "cancelled": "OFFER CANCELLED",
        "accepted_by": "{who} accepted the offer.",
        "hand_over": "Hand the gift over to {who}.",
        "hand_over_how": "Open their profile with the button below and send the NFT from the gift menu.",
        "closed_body": "The offer is no longer active.",
        "a_own": "This is your own offer.",
        "a_taken": "This offer is already closed.",
        "a_author_only": "Only the author can decline this offer.",
        "a_gone": "This offer no longer exists.",
        "a_ok_accept": "Accepted. Check the message.",
        "a_ok_decline": "Declined.",
        "usage": (
            "Usage: <code>.buy link price [en|ru]</code>\n"
            "Example: <code>.buy https://t.me/nft/LibertyFigure-181692 1500 stars</code>"
        ),
        "bad_link": "No gift link of the form <code>t.me/nft/Name-number</code> found.",
        "no_price": "No price in the command.",
    },
}


class ParseError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass
class Offer:
    side: str            # "buy" | "sell"
    slug: str            # "LibertyFigure"
    number: int          # 181692
    price: str           # rendered price line, HTML-safe, e.g. "1,500 Stars"
    lang: str            # "ru" | "en"

    @property
    def url(self) -> str:
        return f"https://t.me/nft/{self.slug}-{self.number}"

    @property
    def title(self) -> str:
        spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", self.slug)
        return f"{spaced} #{self.number}"


def _fmt_price(raw: str, lang: str) -> str:
    """Prettify '1500 stars' -> '1,500 Stars' / '1 500 Stars'. Falls back to
    the text as typed, so the owner can write anything."""
    raw = raw.strip()
    match = _PRICE_RE.match(raw)
    if not match:
        return escape(raw)
    number, tail = match.group(1), match.group(2).strip()

    whole, _, frac = number.replace(",", ".").partition(".")
    sep = " " if lang == "ru" else ","
    grouped = ""
    for i, ch in enumerate(reversed(whole)):
        if i and i % 3 == 0:
            grouped = sep + grouped
        grouped = ch + grouped
    shown = grouped + ((("," if lang == "ru" else ".") + frac) if frac else "")

    unit = CURRENCY_WORD.get(tail.lower())
    if unit:
        return f"{shown} {unit}"
    if tail:
        return f"{shown} {escape(tail)}"
    return shown


def parse(text: str) -> Offer:
    head = COMMAND_RE.match(text.strip())
    if not head:
        raise ParseError("usage")
    side = SIDE[head.group(1).lower()]
    rest = head.group(2).strip()
    if not rest:
        raise ParseError("usage")

    link = NFT_LINK_RE.search(rest)
    if not link:
        raise ParseError("bad_link")
    slug, number = link.group(1), int(link.group(2))

    # Everything except the link is price text; a trailing en/ru token is the
    # language, not the price.
    remainder = (rest[: link.start()] + " " + rest[link.end():]).strip()
    tokens = remainder.split()

    lang = "ru"
    if tokens and tokens[-1].lower() in LANGS:
        lang = LANGS[tokens.pop().lower()]
    elif tokens and tokens[0].lower() in LANGS:
        lang = LANGS[tokens.pop(0).lower()]

    price_raw = " ".join(tokens).strip()
    if not price_raw:
        raise ParseError("no_price")

    return Offer(
        side=side,
        slug=slug,
        number=number,
        price=_fmt_price(price_raw, lang),
        lang=lang,
    )


# ---------------------------------------------------------------------------
# Rendering (pure; returns HTML strings)
# ---------------------------------------------------------------------------

def _gift_ref(offer: Offer) -> str:
    return f'<a href="{escape(offer.url, quote=True)}">{escape(offer.title)}</a>'


def render_offer(offer: Offer) -> str:
    t = TEXT[offer.lang]
    return "\n".join([
        f"<b>{t[offer.side]}</b> · {_gift_ref(offer)}",
        "",
        f"{t['price']} <b>{offer.price}</b>",
    ])


def render_accepted(offer: Offer, *, acceptor: str, receiver: str) -> str:
    t = TEXT[offer.lang]
    return "\n".join([
        f"<b>{t['accepted']}</b>",
        "",
        f"{_gift_ref(offer)} — <b>{offer.price}</b>",
        "",
        t["accepted_by"].format(who=escape(acceptor)),
        "",
        f"<b>{t['hand_over'].format(who=escape(receiver))}</b>",
        t["hand_over_how"],
    ])


def render_closed(offer: Offer, *, by_author: bool) -> str:
    t = TEXT[offer.lang]
    state = "cancelled" if by_author else "declined"
    return "\n".join([
        f"<b>{t[state]}</b>",
        "",
        f"{_gift_ref(offer)} — <b>{offer.price}</b>",
        "",
        t["closed_body"],
    ])


# ---------------------------------------------------------------------------
# Offline preview — `python gift_offer_bot.py check '<command>'`
# ---------------------------------------------------------------------------

def check(argv: list[str]) -> int:
    if not argv:
        print("usage: python gift_offer_bot.py check '.buy https://t.me/nft/LibertyFigure-181692 1500 stars'")
        return 2
    try:
        offer = parse(" ".join(argv))
    except ParseError as exc:
        print(TEXT["ru"][exc.code])
        return 1
    t = TEXT[offer.lang]
    print("---------- card ----------")
    print(render_offer(offer))
    print(f"[ {t['accept']} ] [ {t['decline']} ]")
    print("\n---------- after Accept ----------")
    receiver = "@you" if offer.side == "buy" else "@buyer"
    print(render_accepted(offer, acceptor="@buyer", receiver=receiver))
    print(f"[ {t['transfer']} ]  -> opens {receiver}")
    print(f"\npreview url: {offer.url}")
    return 0


# ---------------------------------------------------------------------------
# The bot (Bot API via aiogram)
# ---------------------------------------------------------------------------

@dataclass
class OfferState:
    offer: Offer
    author_id: int
    author_label: str
    status: str = "open"            # open | accepted | declined | cancelled
    acceptor_label: str | None = None


@dataclass
class Store:
    """In-memory offers. A restart forgets open offers; their buttons then
    answer 'offer no longer exists' instead of acting on stale state."""
    _by_id: dict[int, OfferState] = field(default_factory=dict)
    _seq: int = 0

    def add(self, state: OfferState) -> int:
        self._seq += 1
        self._by_id[self._seq] = state
        return self._seq

    def get(self, offer_id: int) -> OfferState | None:
        return self._by_id.get(offer_id)


def _label(user) -> str:
    if getattr(user, "username", None):
        return f"@{user.username}"
    name = " ".join(p for p in (user.first_name, user.last_name) if p)
    return name or str(user.id)


def run() -> int:
    token = os.environ.get("BOT_TOKEN", "").strip()
    if not token:
        print("config error: set BOT_TOKEN (from @BotFather)", file=sys.stderr)
        return 2

    from aiogram import Bot, Dispatcher, F
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode
    from aiogram.filters.callback_data import CallbackData
    from aiogram.types import (
        CallbackQuery,
        InlineKeyboardButton,
        InlineKeyboardMarkup,
        LinkPreviewOptions,
        Message,
    )

    store = Store()

    class OfferCB(CallbackData, prefix="of"):
        id: int
        action: str  # "a" accept | "d" decline

    def offer_keyboard(offer_id: int, lang: str) -> InlineKeyboardMarkup:
        t = TEXT[lang]
        return InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=t["accept"], callback_data=OfferCB(id=offer_id, action="a").pack()),
            InlineKeyboardButton(text=t["decline"], callback_data=OfferCB(id=offer_id, action="d").pack()),
        ]])

    def transfer_keyboard(lang: str, user_id: int, username: str | None) -> InlineKeyboardMarkup:
        t = TEXT[lang]
        url = f"https://t.me/{username}" if username else f"tg://user?id={user_id}"
        return InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=t["transfer"], url=url),
        ]])

    def preview(offer: Offer) -> LinkPreviewOptions:
        # Pin the preview to the gift link, large, above the text.
        return LinkPreviewOptions(url=offer.url, prefer_large_media=True, show_above_text=True)

    bot = Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    @dp.message(F.text.regexp(COMMAND_RE.pattern))
    async def on_command(message: Message) -> None:
        try:
            offer = parse(message.text)
        except ParseError as exc:
            lang = "ru"
            await message.reply(TEXT[lang][exc.code], link_preview_options=LinkPreviewOptions(is_disabled=True))
            return

        author = message.from_user
        state = OfferState(offer=offer, author_id=author.id, author_label=_label(author))
        offer_id = store.add(state)

        await message.answer(
            render_offer(offer),
            link_preview_options=preview(offer),
            reply_markup=offer_keyboard(offer_id, offer.lang),
        )
        # Tidy the command away if the bot is allowed to (admin in a group).
        try:
            await message.delete()
        except Exception:
            pass

    @dp.callback_query(OfferCB.filter())
    async def on_press(query: CallbackQuery, callback_data: OfferCB) -> None:
        state = store.get(callback_data.id)
        if state is None:
            await query.answer(TEXT["ru"]["a_gone"], show_alert=True)
            return
        offer, t = state.offer, TEXT[state.offer.lang]
        presser = query.from_user

        if state.status != "open":
            await query.answer(t["a_taken"], show_alert=True)
            return

        if callback_data.action == "a":
            if presser.id == state.author_id:
                await query.answer(t["a_own"], show_alert=True)
                return
            state.status = "accepted"
            state.acceptor_label = _label(presser)

            # On a buy the author receives the gift; on a sell the acceptor does.
            if offer.side == "buy":
                receiver_id, receiver_label, receiver_name = (
                    state.author_id, state.author_label, state.author_label.lstrip("@") if state.author_label.startswith("@") else None,
                )
            else:
                receiver_id, receiver_label, receiver_name = (
                    presser.id, state.acceptor_label, presser.username,
                )

            await query.message.edit_text(
                render_accepted(offer, acceptor=state.acceptor_label, receiver=receiver_label),
                link_preview_options=preview(offer),
                reply_markup=transfer_keyboard(offer.lang, receiver_id, receiver_name),
            )
            await query.answer(t["a_ok_accept"])
            return

        # decline
        by_author = presser.id == state.author_id
        if not by_author:
            await query.answer(t["a_author_only"], show_alert=True)
            return
        state.status = "cancelled"
        await query.message.edit_text(
            render_closed(offer, by_author=True),
            link_preview_options=preview(offer),
            reply_markup=None,
        )
        await query.answer(t["a_ok_decline"])

    async def main() -> None:
        me = await bot.get_me()
        log.info("bot @%s is live — type .buy <link> <price> where it can read messages", me.username)
        await dp.start_polling(bot)

    asyncio.run(main())
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    if argv and argv[0] == "check":
        return check(argv[1:])
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
