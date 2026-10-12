#!/usr/bin/env python3
"""gift_offer_bot — a plain Telegram BOT (Bot API, token only, no account session).

You type, in a chat the bot can see (or in your own DMs via a Telegram Business
connection):

    .buy https://t.me/nft/HappyBrownie-51899 stars 1500 6h

and the bot posts a tidy offer card: the gift link with its preview, who offers
what, how long the offer lasts, and two buttons — «Принять» / «Отклонить».

The offer duration is REQUIRED (3h / 6h / 12h …). When it runs out the card
closes itself. You cannot accept your own offer.

Run:
    pip install aiogram
    BOT_TOKEN=123:abc python gift_offer_bot.py

Preview the card with no token and no network:
    python gift_offer_bot.py check '.buy https://t.me/nft/HappyBrownie-51899 stars 1500 6h'
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import escape

log = logging.getLogger("gift_offer_bot")

# ---------------------------------------------------------------------------
# Command:  .buy  <gift link>  <stars|gram>  <amount>  <3h|6h|12h>  [en|ru]
#           .sell <gift link>  <stars|gram>  <amount>  <3h|6h|12h>  [en|ru]
# Link, currency, amount, duration and language may come in any order.
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

# Duration: 3h / 6h / 12h / 30m / 1d, Cyrillic units too. Required.
MIN_TTL, MAX_TTL = 5 * 60, 7 * 24 * 3600
_DUR_UNITS = {
    "m": 60, "min": 60, "м": 60, "мин": 60,
    "h": 3600, "hr": 3600, "ч": 3600, "час": 3600, "часа": 3600, "часов": 3600,
    "d": 86400, "д": 86400, "дн": 86400, "день": 86400,
}
_DUR_RE = re.compile(r"^(\d+)\s*(" + "|".join(sorted(_DUR_UNITS, key=len, reverse=True)) + r")$", re.IGNORECASE)

UNIT_WORD = {
    "ru": {"stars": "звёзд", "gram": "грам"},
    "en": {"stars": "Stars", "gram": "TON"},
}
DUR_SUFFIX = {"ru": {"d": "д", "h": "ч", "m": "м"}, "en": {"d": "d", "h": "h", "m": "m"}}


TEXT = {
    "ru": {
        "accept": "Принять", "decline": "Отклонить", "transfer": "Передать НФТ",
        "offer_line": "<b>{name}</b> предлагает вам <b>{amount} {unit}</b> за подарок {gift}",
        "valid_line": "Действует: {dur}",
        "accepted": "ОФФЕР ПРИНЯТ",
        "declined": "ОФФЕР ОТКЛОНЁН",
        "cancelled": "ОФФЕР ОТМЕНЁН",
        "expired": "ОФФЕР ИСТЁК",
        "accepted_by": "{who} принял оффер.",
        "hand_over": "Передайте подарок пользователю {who}.",
        "hand_over_how": "Откройте его профиль кнопкой ниже и отправьте NFT через меню подарка.",
        "closed_body": "Оффер больше не активен.",
        "expired_body": "Время оффера ({dur}) вышло. Оффер больше не активен.",
        "a_own": "Нельзя принять свой собственный оффер.",
        "a_taken": "Оффер уже закрыт.",
        "a_expired": "Оффер истёк.",
        "a_author_only": "Отклонить оффер может только автор.",
        "a_gone": "Этого оффера больше нет.",
        "a_ok_accept": "Принято. Смотри сообщение.",
        "a_ok_decline": "Отклонено.",
        "usage": (
            "Формат: <code>.buy ссылка stars|gram сумма 3h|6h|12h</code>\n"
            "Пример: <code>.buy https://t.me/nft/HappyBrownie-51899 stars 1500 6h</code>"
        ),
        "bad_link": "Не вижу ссылку на подарок вида <code>t.me/nft/Название-номер</code>.",
        "no_currency": "Не указана валюта — добавь <b>stars</b> или <b>gram</b>.",
        "no_amount": "Не указана сумма.",
        "no_ttl": "Укажи срок оффера: <b>3h</b>, <b>6h</b> или <b>12h</b>.",
        "bad_ttl": "Срок <code>{value}</code> вне диапазона — от 5m до 7d.",
    },
    "en": {
        "accept": "Accept", "decline": "Decline", "transfer": "Transfer NFT",
        "offer_line": "<b>{name}</b> offers you <b>{amount} {unit}</b> for the gift {gift}",
        "valid_line": "Valid for: {dur}",
        "accepted": "OFFER ACCEPTED",
        "declined": "OFFER DECLINED",
        "cancelled": "OFFER CANCELLED",
        "expired": "OFFER EXPIRED",
        "accepted_by": "{who} accepted the offer.",
        "hand_over": "Hand the gift over to {who}.",
        "hand_over_how": "Open their profile with the button below and send the NFT from the gift menu.",
        "closed_body": "The offer is no longer active.",
        "expired_body": "The {dur} window has run out. The offer is no longer active.",
        "a_own": "You cannot accept your own offer.",
        "a_taken": "This offer is already closed.",
        "a_expired": "This offer has expired.",
        "a_author_only": "Only the author can decline this offer.",
        "a_gone": "This offer no longer exists.",
        "a_ok_accept": "Accepted. Check the message.",
        "a_ok_decline": "Declined.",
        "usage": (
            "Usage: <code>.buy link stars|gram amount 3h|6h|12h</code>\n"
            "Example: <code>.buy https://t.me/nft/HappyBrownie-51899 stars 1500 6h</code>"
        ),
        "bad_link": "No gift link of the form <code>t.me/nft/Name-number</code> found.",
        "no_currency": "Which currency? Add <b>stars</b> or <b>gram</b>.",
        "no_amount": "No amount in the command.",
        "no_ttl": "Set the offer duration: <b>3h</b>, <b>6h</b> or <b>12h</b>.",
        "bad_ttl": "Duration <code>{value}</code> is out of range — 5m to 7d.",
    },
}


class ParseError(Exception):
    def __init__(self, code: str, value: str = ""):
        super().__init__(code)
        self.code = code
        self.value = value


def parse_duration(token: str) -> int | None:
    m = _DUR_RE.match(token)
    if not m:
        return None
    return int(m.group(1)) * _DUR_UNITS[m.group(2).lower()]


def fmt_duration(seconds: int, lang: str) -> str:
    sfx = DUR_SUFFIX.get(lang, DUR_SUFFIX["en"])
    days, rest = divmod(int(seconds), 86400)
    hours, rest = divmod(rest, 3600)
    mins = rest // 60
    parts = [f"{v}{sfx[u]}" for v, u in ((days, "d"), (hours, "h"), (mins, "m")) if v]
    return " ".join(parts) or f"0{sfx['m']}"


def fmt_deadline(expires_at: float) -> str:
    return datetime.fromtimestamp(expires_at, tz=timezone.utc).strftime("%H:%M UTC")


@dataclass
class Offer:
    side: str
    slug: str
    number: int
    currency: str
    amount: str
    ttl_seconds: int
    lang: str

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

    currency = amount = ttl = None
    lang = "ru"
    for token in remainder.split():
        low = token.lower()
        if low in LANGS:
            lang = LANGS[low]
            continue
        if low in CURRENCY and currency is None:
            currency = CURRENCY[low]
            continue
        dur = parse_duration(token)
        if dur is not None and ttl is None:
            if not MIN_TTL <= dur <= MAX_TTL:
                raise ParseError("bad_ttl", token)
            ttl = dur
            continue
        if _NUM_RE.match(token) and amount is None:
            amount = token

    if currency is None:
        raise ParseError("no_currency")
    if amount is None:
        raise ParseError("no_amount")
    if ttl is None:
        raise ParseError("no_ttl")

    return Offer(side=side, slug=slug, number=number, currency=currency, amount=amount, ttl_seconds=ttl, lang=lang)


# ---------------------------------------------------------------------------
# Rendering (pure HTML)
# ---------------------------------------------------------------------------

def _gift_ref(offer: Offer) -> str:
    return f'<a href="{escape(offer.url, quote=True)}">{escape(offer.title)}</a>'


def _price(offer: Offer) -> str:
    return f"{offer.amount_str()} {offer.unit()}"


def render_offer(offer: Offer, *, name: str, expires_at: float | None = None) -> str:
    t = TEXT[offer.lang]
    return "\n".join([
        t["offer_line"].format(name=escape(name), amount=offer.amount_str(), unit=offer.unit(), gift=_gift_ref(offer)),
        t["valid_line"].format(dur=fmt_duration(offer.ttl_seconds, offer.lang)),
    ])


def _closed_head(offer: Offer, state_key: str) -> list[str]:
    t = TEXT[offer.lang]
    return [
        f"<b>{t[state_key]}</b>",
        "",
        f"{_gift_ref(offer)} — <b>{_price(offer)}</b>",
        "",
    ]


def render_accepted(offer: Offer, *, acceptor: str, receiver: str) -> str:
    t = TEXT[offer.lang]
    return "\n".join(_closed_head(offer, "accepted") + [
        t["accepted_by"].format(who=escape(acceptor)),
        "",
        f"<b>{t['hand_over'].format(who=escape(receiver))}</b>",
        t["hand_over_how"],
    ])


def render_closed(offer: Offer, *, by_author: bool) -> str:
    t = TEXT[offer.lang]
    return "\n".join(_closed_head(offer, "cancelled" if by_author else "declined") + [t["closed_body"]])


def render_expired(offer: Offer) -> str:
    t = TEXT[offer.lang]
    return "\n".join(_closed_head(offer, "expired") + [
        t["expired_body"].format(dur=fmt_duration(offer.ttl_seconds, offer.lang)),
    ])


# ---------------------------------------------------------------------------
# Offline preview — `python gift_offer_bot.py check '<command>'`
# ---------------------------------------------------------------------------

def check(argv: list[str]) -> int:
    if not argv:
        print("usage: python gift_offer_bot.py check '.buy https://t.me/nft/HappyBrownie-51899 stars 1500 6h'")
        return 2
    try:
        offer = parse(" ".join(argv))
    except ParseError as exc:
        print(TEXT["ru"][exc.code].format(value=exc.value))
        return 1
    t = TEXT[offer.lang]
    base = 1_760_000_000
    print("---------- card ----------")
    print(render_offer(offer, name="Иван" if offer.lang == "ru" else "Ivan", expires_at=base + offer.ttl_seconds))
    print(f"[ {t['accept']} ] [ {t['decline']} ]")
    print("\n---------- after Accept ----------")
    receiver = "@seller" if offer.side == "buy" else "@buyer"
    print(render_accepted(offer, acceptor="@buyer", receiver=receiver))
    print(f"[ {t['transfer']} ]  -> opens {receiver}")
    print("\n---------- after expiry ----------")
    print(render_expired(offer))
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
    chat_id: int | None = None
    card_message_id: int | None = None
    business_connection_id: str | None = None
    expires_at: float = 0.0
    status: str = "open"            # open | accepted | cancelled | expired
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

    def open_states(self) -> list[tuple[int, OfferState]]:
        return [(i, s) for i, s in self._by_id.items() if s.status == "open"]


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
    SWEEP_INTERVAL = 20.0

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

    async def edit_card(state: OfferState, text: str, markup) -> None:
        await bot.edit_message_text(
            text,
            chat_id=state.chat_id,
            message_id=state.card_message_id,
            business_connection_id=state.business_connection_id,
            link_preview_options=preview(state.offer),
            reply_markup=markup,
        )

    async def post_offer(message: Message, bcid: str | None) -> None:
        try:
            offer = parse(message.text)
        except ParseError as exc:
            try:
                await bot.send_message(
                    message.chat.id, TEXT["ru"][exc.code].format(value=exc.value),
                    business_connection_id=bcid,
                    link_preview_options=LinkPreviewOptions(is_disabled=True),
                )
            except Exception as err:
                log.warning("could not send usage hint: %s", err)
            return

        author = message.from_user
        now = time.time()
        state = OfferState(
            offer=offer,
            author_id=author.id,
            author_label=_label(author),
            author_username=author.username,
            chat_id=message.chat.id,
            business_connection_id=bcid,
            expires_at=now + offer.ttl_seconds,
        )
        offer_id = store.add(state)

        card = await bot.send_message(
            message.chat.id,
            render_offer(offer, name=author.first_name or _label(author), expires_at=state.expires_at),
            business_connection_id=bcid,
            link_preview_options=preview(offer),
            reply_markup=offer_keyboard(offer_id, offer.lang),
        )
        state.card_message_id = card.message_id

        try:
            if bcid:
                await bot.delete_business_messages(bcid, [message.message_id])
            else:
                await bot.delete_message(message.chat.id, message.message_id)
        except Exception:
            pass

    @dp.message(F.text.regexp(COMMAND_RE.pattern))
    async def on_command(message: Message) -> None:
        await post_offer(message, None)

    @dp.business_message(F.text.regexp(COMMAND_RE.pattern))
    async def on_business_command(message: Message) -> None:
        await post_offer(message, message.business_connection_id)

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

        if time.time() >= state.expires_at:
            state.status = "expired"
            try:
                await edit_card(state, render_expired(offer), None)
            except Exception as exc:
                log.warning("could not close expired offer: %s", exc)
            await query.answer(t["a_expired"], show_alert=True)
            return

        if callback_data.action == "a":
            if presser.id == state.author_id:
                await query.answer(t["a_own"], show_alert=True)
                return
            state.status = "accepted"
            state.acceptor_label = _label(presser)

            if offer.side == "buy":
                receiver_id, receiver_label, receiver_name = (
                    state.author_id, state.author_label, state.author_username,
                )
            else:
                receiver_id, receiver_label, receiver_name = (
                    presser.id, state.acceptor_label, presser.username,
                )

            await edit_card(
                state,
                render_accepted(offer, acceptor=state.acceptor_label, receiver=receiver_label),
                transfer_keyboard(offer.lang, receiver_id, receiver_name),
            )
            await query.answer(t["a_ok_accept"])
            return

        if presser.id != state.author_id:
            await query.answer(t["a_author_only"], show_alert=True)
            return
        state.status = "cancelled"
        await edit_card(state, render_closed(offer, by_author=True), None)
        await query.answer(t["a_ok_decline"])

    async def sweeper() -> None:
        while True:
            now = time.time()
            for _id, state in store.open_states():
                if now >= state.expires_at:
                    state.status = "expired"
                    try:
                        await edit_card(state, render_expired(state.offer), None)
                    except Exception as exc:
                        log.warning("could not expire offer %s: %s", _id, exc)
            await asyncio.sleep(SWEEP_INTERVAL)

    async def main() -> None:
        me = await bot.get_me()
        log.info(
            "bot @%s is live — groups/DM-with-bot and Telegram Business DMs. "
            "Type .buy <link> <stars|gram> <amount> <3h|6h|12h>", me.username,
        )
        asyncio.create_task(sweeper())
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
