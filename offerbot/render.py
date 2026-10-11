"""Rendering the offer card and the user-facing errors.

HTML is used rather than Markdown: gift names and nicknames routinely contain
characters that silently break Markdown v1, and HTML has one honest escape
function.
"""

from html import escape

from .gifts import gift_link, gift_title
from .money import fmt_amount, fmt_usd
from .parser import Offer
from .rates import Rates

CURRENCY_SYMBOL = {"stars": "⭐", "gram": "💎"}
CURRENCY_NAME = {
    "en": {"stars": "Stars", "gram": "TON"},
    "ru": {"stars": "Stars", "gram": "TON"},
}

SIDE_LABEL = {
    "en": {"buy": "BUY", "sell": "SELL"},
    "ru": {"buy": "КУПЛЮ", "sell": "ПРОДАМ"},
}
SIDE_MARK = {"buy": "🟢", "sell": "🔴"}

LINES = {
    "en": {
        "price": "💵 Price:",
        "escrow": "🤝 Escrow / hold — fine",
        "contact": "✍️ DM:",
        "unknown_gift": "⚠️ unknown collection — check the link",
    },
    "ru": {
        "price": "💵 Цена:",
        "escrow": "🤝 Гарант / холд — ок",
        "contact": "✍️ ЛС:",
        "unknown_gift": "⚠️ коллекция не из списка — проверь ссылку",
    },
}

ERRORS = {
    "en": {
        "usage": (
            "Usage: <code>.buy stars 1500 plushpepe 1234 en</code>\n"
            "<code>.buy &lt;stars|gram&gt; &lt;price&gt; &lt;gift&gt; &lt;number&gt; &lt;en|ru&gt;</code>"
        ),
        "no_currency": "Which currency? Add <b>stars</b> or <b>gram</b>.",
        "no_amount": "No price in the command.",
        "no_number": "Missing the gift number — add it, or write it as <code>#1234</code>.",
        "no_gift": "No gift name in the command.",
        "ambiguous_numbers": "Too many numbers — leave one price and one <code>#number</code>.",
        "bad_amount": "Price <code>{value}</code> is not a positive number.",
        "bad_number": "Gift number <code>{value}</code> is not valid.",
        "stars_fraction": "Stars are whole units — <code>{value}</code> cannot be paid.",
    },
    "ru": {
        "usage": (
            "Формат: <code>.buy stars 1500 plushpepe 1234 ru</code>\n"
            "<code>.buy &lt;stars|gram&gt; &lt;цена&gt; &lt;подарок&gt; &lt;номер&gt; &lt;en|ru&gt;</code>"
        ),
        "no_currency": "Не указана валюта — добавь <b>stars</b> или <b>gram</b>.",
        "no_amount": "В команде нет цены.",
        "no_number": "Нет номера подарка — укажи его или напиши как <code>#1234</code>.",
        "no_gift": "В команде нет названия подарка.",
        "ambiguous_numbers": "Слишком много чисел — оставь одну цену и один <code>#номер</code>.",
        "bad_amount": "Цена <code>{value}</code> — не положительное число.",
        "bad_number": "Номер подарка <code>{value}</code> некорректен.",
        "stars_fraction": "Stars — целые, <code>{value}</code> не оплатить.",
    },
}


def _price_line(offer: Offer, rates: Rates) -> str:
    symbol = CURRENCY_SYMBOL[offer.currency]
    amount = fmt_amount(offer.amount, offer.lang, max_dp=0 if offer.is_integer_currency else 2)
    price = f"<b>{amount} {symbol}</b>"

    usd, rub = rates.convert(offer.currency, offer.amount)
    approx = []
    if usd:
        approx.append(f"≈ {fmt_usd(usd, offer.lang)}")
    if rub and offer.lang == "ru":
        approx.append(f"{fmt_amount(rub, 'ru', max_dp=0)} ₽")
    if approx:
        price += f" <i>({' · '.join(approx)})</i>"
    return f"{LINES[offer.lang]['price']} {price}"


def render_offer(
    offer: Offer,
    rates: Rates | None = None,
    *,
    contact: str | None = None,
    escrow: bool = True,
) -> str:
    """Build the HTML body of the offer card."""
    rates = rates or Rates()
    lang, lines = offer.lang, LINES[offer.lang]

    title = escape(f"{gift_title(offer.gift_slug)} #{offer.gift_number}")
    link = gift_link(offer.gift_slug, offer.gift_number)
    header = (
        f"{SIDE_MARK[offer.side]} <b>{SIDE_LABEL[lang][offer.side]}</b> — "
        f'<a href="{escape(link, quote=True)}">{title}</a>'
    )

    body = [header, _price_line(offer, rates)]
    if escrow:
        body.append(lines["escrow"])
    if contact:
        body.append(f"{lines['contact']} {escape(contact)}")
    if not offer.gift_known:
        body.append(f"<i>{lines['unknown_gift']}</i>")
    return "\n".join(body)


def render_error(code: str, lang: str, **ctx) -> str:
    table = ERRORS.get(lang, ERRORS["en"])
    template = table.get(code) or table["usage"]
    safe = {key: escape(str(value)) for key, value in ctx.items()}
    try:
        return template.format(**safe)
    except (KeyError, IndexError):
        return template
