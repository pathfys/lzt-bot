"""Rendering the offer card, its follow-up states and the user-facing errors.

HTML is used rather than Markdown: gift names and nicknames routinely contain
characters that silently break Markdown v1, and HTML has one honest escape
function.

Deliberately free of emoji — the card is meant to read like a trade ticket.
"""

from datetime import datetime, timezone
from html import escape

from .gifts import gift_link, gift_title
from .money import fmt_amount, fmt_usd
from .parser import Offer
from .rates import Rates

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
