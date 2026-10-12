#!/usr/bin/env python3
"""gift_offer_bot — a plain Telegram BOT (Bot API, token only, no account session).

You type, in a chat the bot can see:

    .buy https://t.me/nft/LibertyFigure-181692 stars 1500

and the bot posts:

    Иван предлагает вам 1 500 звёзд за подарок Liberty Figure #181692
    [ Принять ]  [ Отклонить ]

with the gift link preview shown above the text. The gift is given by its
LINK, pasted straight into the command — no account session, just a bot token
from @BotFather. Inline buttons are a bot-only Telegram feature, which is why
this is a bot and not a userbot.

Pressing «Принять» rewrites the message into a hand-over note with a button to
the counterparty's profile; «Отклонить» closes it.

Run:
    pip install aiogram
    BOT_TOKEN=123:abc python gift_offer_bot.py

Preview the text with no token and no network:
    python gift_offer_bot.py check '.buy https://t.me/nft/LibertyFigure-181692 stars 1500'
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
# Command:  .buy  <gift link>  <stars|gram>  <amount>  [en|ru]
#           .sell <gift link>  <stars|gram>  <amount>  [en|ru]
# The link, currency and amount may come in any order.
# ---------------------------------------------------------------------------

COMMAND_RE = re.compile(r"^[.!/](buy|sell|куплю|продам|покупаю|продаю)\b(.*)$", re.IGNORECASE | re.DOTALL)

SIDE = {
    "buy": "buy", "куплю": "buy", "покупаю": "buy",
    "sell": "sell", "продам": "sell", "продаю": "sell",
}

NFT_LINK_RE = re.compile(
    r"(?:https?://)?(?:t\.me|telegram\.me|telegram\.dog)/nft/([A-Za-z0-9]+)-(\d+)",
    re.IGNORECASE,
)

LANGS = {"en": "en", "eng": "en", "english": "en", "ru": "ru", "rus": "ru", "russian": "ru", "рус": "ru"}

CURRENCY = {
    "stars": "stars", "star": "stars", "⭐": "stars", "⭐️": "stars",
    "звезд": "stars", "звёзд": "stars", "звезды": "stars", "звёзды": "stars",
    "gram": "gram", "grams": "gram", "ton": "gram", "toncoin": "gram",
    "💎": "gram", "тон": "gram", "грам": "gram",
}

_NUM_RE = re.compile(r"^\d+(?:[.,]\d+)?$")

# Word for the sentence.  stars -> "звёзд" / "Stars",  gram -> "грам" / "TON".
UNIT_WORD = {
    "ru": {"stars": "звёзд", "gram": "грам"},
    "en": {"stars": "Stars", "gram": "TON"},
}


TEXT = {
    "ru": {
        "accept": "Принять", "decline": "Отклонить", "transfer": "Передать НФТ",
        # (имя) предлагает вам (сумма) (звёзд/грам) за подарок (название #номер)
        "offer": "<b>{name}</b> предлагает вам <b>{amount} {unit}</b> за подарок {gift}",
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
            "Формат: <code>.buy ссылка stars|gram сумма</code>\n"
            "Пример: <code>.buy https://t.me/nft/LibertyFigure-181692 stars 1500</code>"
        ),
        "bad_link": "Не вижу ссылку на подарок вида <code>t.me/nft/Название-номер</code>.",
        "no_currency": "Не указана валюта — добавь <b>stars</b> или <b>gram</b>.",
        "no_amount": "Не указана сумма.",
    },
    "en": {
        "accept": "Accept", "decline": "Decline", "transfer": "Transfer NFT",
        "offer": "<b>{name}</b> offers you <b>{amount} {unit}</b> for the gift {gift}",
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
            "Usage: <code>.buy link stars|gram amount</code>\n"
            "Example: <code>.buy https://t.me/nft/LibertyFigure-181692 stars 1500</code>"
        ),
        "bad_link": "No gift link of the form <code>t.me/nft/Name-number</code> found.",
        "no_currency": "Which currency? Add <b>stars</b> or <b>gram</b>.",
        "no_amount": "No amount in the command.",
    },
}


class ParseError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass
class Offer:
    side: str        # "buy" | "sell"
    slug: str        # "LibertyFigure"
    number: int      # 181692
    currency: str    # "stars" | "gram"
    amount: str      # raw amount as typed, e.g. "1500" / "12.5"
    lang: str        # "ru" | "en"

    @property
    def url(self) -> str:
        return f"https://t.me/nft/{self.slug}-{self.number}"

    @property
    def title(self) -> str:
        spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", self.slug)
        return f"{spaced} #{self.number}"

    def amount_str(self) -> str:
        whole, _, frac = self.amount.replace(",", ".").partition(".")
        sep = " " if self.lang == "ru" else ","
        grouped = ""
        for i, ch in enumerate(reversed(whole)):
            if i and i % 3 == 0:
                grouped = sep + grouped
            grouped = ch + grouped
        return grouped + (((","if self.lang == "ru" else ".") + frac) if frac else "")

    def unit(self) -> str:
        return UNIT_WORD[self.lang][self.currency]


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

    remainder = (rest[: link.start()] + " " + rest[link.end():]).strip()

    currency = None
    amount = None
    lang = "ru"
    for token in remainder.split():
        low = token.lower()
        if low in LANGS:
            lang = LANGS[low]
        elif low in CURRENCY and currency is None:
            currency = CURRENCY[low]
        elif _NUM_RE.match(token) and amount is None:
            amount = token

    if currency is None:
        raise ParseError("no_currency")
    if amount is None:
        raise ParseError("no_amount")

    return Offer(side=side, slug=slug, number=number, currency=currency, amount=amount, lang=lang)


# ---------------------------------------------------------------------------
# Rendering (pure HTML)
# ---------------------------------------------------------------------------

def _gift_ref(offer: Offer) -> str:
    return f'<a href="{escape(offer.url, quote=True)}">{escape(offer.title)}</a>'


def render_offer(offer: Offer, *, name: str) -> str:
    t = TEXT[offer.lang]
    return t["offer"].format(
        name=escape(name),
        amount=offer.amount_str(),
        unit=offer.unit(),
        gift=_gift_ref(offer),
    )


def render_accepted(offer: Offer, *, acceptor: str, receiver: str) -> str:
    t = TEXT[offer.lang]
    return "\n".join([
        f"<b>{t['accepted']}</b>",
        "",
        f"{_gift_ref(offer)} — <b>{offer.amount_str()} {offer.unit()}</b>",
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
        f"{_gift_ref(offer)} — <b>{offer.amount_str()} {offer.unit()}</b>",
        "",
        t["closed_body"],
    ])


# ---------------------------------------------------------------------------
# Offline preview — `python gift_offer_bot.py check '<command>'`
# ---------------------------------------------------------------------------

def check(argv: list[str]) -> int:
    if not argv:
        print("usage: python gift_offer_bot.py check '.buy https://t.me/nft/LibertyFigure-181692 stars 1500'")
        return 2
    try:
        offer = parse(" ".join(argv))
    except ParseError as exc:
        print(TEXT["ru"][exc.code])
        return 1
    t = TEXT[offer.lang]
    print("---------- message ----------")
    print(render_offer(offer, name="Иван" if offer.lang == "ru" else "Ivan"))
    print(f"[ {t['accept']} ] [ {t['decline']} ]")
    print("\n---------- after Accept ----------")
    receiver = "@seller" if offer.side == "buy" else "@buyer"
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
    author_username: str | None = None
    status: str = "open"            # open | accepted | cancelled
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
        url = f"https://t.me/{username}" if username else f"tg://user?id={user_id}"
        return InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=TEXT[lang]["transfer"], url=url),
        ]])

    def preview(offer: Offer) -> LinkPreviewOptions:
        return LinkPreviewOptions(url=offer.url, prefer_large_media=True, show_above_text=True)

    bot = Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    @dp.message(F.text.regexp(COMMAND_RE.pattern))
    async def on_command(message: Message) -> None:
        try:
            offer = parse(message.text)
        except ParseError as exc:
            await message.reply(TEXT["ru"][exc.code], link_preview_options=LinkPreviewOptions(is_disabled=True))
            return

        author = message.from_user
        offer_id = store.add(OfferState(
            offer=offer,
            author_id=author.id,
            author_label=_label(author),
            author_username=author.username,
        ))

        await message.answer(
            render_offer(offer, name=author.first_name or _label(author)),
            link_preview_options=preview(offer),
            reply_markup=offer_keyboard(offer_id, offer.lang),
        )
        try:
            await message.delete()  # tidy the command away if allowed (admin in a group)
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
                receiver_id = state.author_id
                receiver_label = state.author_label
                receiver_name = state.author_username
            else:
                receiver_id = presser.id
                receiver_label = state.acceptor_label
                receiver_name = presser.username

            await query.message.edit_text(
                render_accepted(offer, acceptor=state.acceptor_label, receiver=receiver_label),
                link_preview_options=preview(offer),
                reply_markup=transfer_keyboard(offer.lang, receiver_id, receiver_name),
            )
            await query.answer(t["a_ok_accept"])
            return

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
        log.info("bot @%s is live — type .buy <link> <stars|gram> <amount>", me.username)
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
