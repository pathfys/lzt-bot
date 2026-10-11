import re
from decimal import Decimal

from telethon.extensions import html as tg_html

from offerbot.parser import parse
from offerbot.rates import Rates
from offerbot.render import (
    button_label,
    fmt_deadline,
    fmt_duration,
    render_accepted,
    render_declined,
    render_error,
    render_expired,
    render_offer,
)

RATES = Rates(ton_usd=Decimal("2.84"), ton_rub=Decimal("265.40"), star_usd=Decimal("0.015"))

#: Emoji and pictographs. The cards are meant to read like a trade ticket.
EMOJI = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F0FF⬀-⯿️]"
)


def shown(command, **kwargs):
    """What the chat actually shows, after Telegram's HTML is parsed off."""
    body = render_offer(parse(command), RATES, **kwargs)
    return tg_html.parse(body)


def test_card_carries_the_gift_link_as_an_entity():
    _, entities = shown(".buy stars 1500 plushpepe 1234 en")
    urls = [getattr(e, "url", None) for e in entities]
    assert "https://t.me/nft/PlushPepe-1234" in urls


def test_english_card_contents():
    text, _ = shown(".buy stars 1500 plushpepe 1234 en 6h", contact="@trader")
    assert "BUY" in text
    assert "Plush Pepe #1234" in text
    assert "1,500 Stars" in text
    assert "$23" in text
    assert "Valid for: 6h" in text
    assert "@trader" in text


def test_russian_card_contents():
    text, _ = shown(".buy gram 12.5 durovscap 777 ru 12h", contact="@trader")
    assert "КУПЛЮ" in text
    assert "Durov's Cap #777" in text
    assert "12,5 TON" in text
    assert "₽" in text
    assert "Действует: 12ч" in text


def test_no_emoji_anywhere_in_any_state():
    offer = parse(".buy stars 1500 plushpepe 1234 ru 6h")
    bodies = [
        render_offer(offer, RATES, contact="@trader", target="@someone"),
        render_accepted(offer, acceptor="@buyer", receiver="@trader", resolved_at=1760000000),
        render_declined(offer),
        render_declined(offer, by_author=True),
        render_expired(offer),
        render_error("usage", "ru"),
        render_error("stars_fraction", "en", value="1.5"),
    ]
    for body in bodies:
        text, _ = tg_html.parse(body)
        found = EMOJI.findall(text)
        assert not found, f"emoji {found} leaked into: {text!r}"


def test_sell_and_buy_are_told_apart_by_words_not_symbols():
    buy, _ = shown(".buy stars 10 lolpop 1 en")
    sell, _ = shown(".sell stars 10 lolpop 1 en")
    assert buy.startswith("BUY")
    assert sell.startswith("SELL")


def test_deadline_is_shown_when_known():
    text, _ = shown(".buy stars 10 lolpop 1 en 6h", expires_at=1760000000, now=1760000000)
    assert "until" in text
    assert "UTC" in text


def test_addressed_offer_names_its_target():
    text, _ = shown(".buy stars 10 lolpop 1 en", target="@owner")
    assert "To: @owner" in text


def test_unknown_collection_gets_a_warning_line():
    text, _ = shown(".buy stars 10 brandnewdrop 1 ru")
    assert "проверь ссылку" in text


def test_missing_rates_simply_drop_the_approximate_price():
    body = render_offer(parse(".buy gram 12.5 santahat 7 en"), Rates())
    text, _ = tg_html.parse(body)
    assert "12.5 TON" in text
    assert "≈" not in text


def test_apostrophes_survive_html_escaping():
    text, _ = shown(".buy stars 10 durovscap 1 en")
    assert "Durov's Cap" in text
    assert "&#x27;" not in text


# ---- the accepted card ----

def test_accepted_card_tells_the_giver_whom_to_hand_the_gift_to():
    offer = parse(".buy gram 12.5 durovscap 777 ru 6h")
    text, _ = tg_html.parse(
        render_accepted(offer, acceptor="@buyer", receiver="@author", resolved_at=1760000000)
    )
    assert "ОФФЕР ПРИНЯТ" in text
    assert "@buyer принял оффер" in text
    assert "Передайте подарок пользователю @author" in text
    assert "Принято в" in text


def test_accepted_card_in_english():
    offer = parse(".sell stars 2000 lolpop 55 en 3h")
    text, _ = tg_html.parse(render_accepted(offer, acceptor="@buyer", receiver="@buyer"))
    assert "OFFER ACCEPTED" in text
    assert "Hand the gift over to @buyer" in text


def test_accepted_card_keeps_the_gift_link():
    offer = parse(".buy stars 10 plushpepe 1234 en")
    _, entities = tg_html.parse(
        render_accepted(offer, acceptor="@b", receiver="@a")
    )
    assert "https://t.me/nft/PlushPepe-1234" in [getattr(e, "url", None) for e in entities]


def test_declined_and_cancelled_read_differently():
    offer = parse(".buy stars 10 lolpop 1 ru")
    declined, _ = tg_html.parse(render_declined(offer))
    cancelled, _ = tg_html.parse(render_declined(offer, by_author=True))
    assert "ОТКЛОНЁН" in declined
    assert "ОТМЕНЁН" in cancelled


def test_expired_card_names_the_window():
    offer = parse(".buy stars 10 lolpop 1 ru 3h")
    text, _ = tg_html.parse(render_expired(offer))
    assert "ИСТЁК" in text
    assert "3ч" in text


# ---- small helpers ----

def test_button_labels_follow_the_offer_language():
    assert button_label("accept", "ru") == "Принять"
    assert button_label("decline", "ru") == "Отклонить"
    assert button_label("transfer", "ru") == "Передать НФТ"
    assert button_label("transfer", "en") == "Transfer NFT"
    assert button_label("accept", "de") == "Accept"


def test_duration_formatting():
    assert fmt_duration(6 * 3600, "en") == "6h"
    assert fmt_duration(6 * 3600, "ru") == "6ч"
    assert fmt_duration(90 * 60, "en") == "1h 30m"
    assert fmt_duration(86400, "ru") == "1д"


def test_deadline_adds_the_date_only_when_it_is_another_day():
    same_day = fmt_deadline(1760000000, now=1760000000 - 60)
    next_day = fmt_deadline(1760000000 + 86400, now=1760000000)
    assert same_day.endswith("UTC") and len(same_day.split()) == 2
    assert len(next_day.split()) == 3


def test_errors_are_localized():
    assert "Stars are whole units" in render_error("stars_fraction", "en", value="1.5")
    assert "Stars — целые" in render_error("stars_fraction", "ru", value="1.5")
    assert "5m to 7d" in render_error("bad_ttl", "en", value="99d")


def test_unknown_error_code_falls_back_to_usage():
    assert ".buy" in render_error("nonsense_code", "en")
