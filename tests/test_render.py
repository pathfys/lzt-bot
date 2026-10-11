from decimal import Decimal

from telethon.extensions import html as tg_html

from offerbot.parser import parse
from offerbot.rates import Rates
from offerbot.render import render_error, render_offer

RATES = Rates(ton_usd=Decimal("2.84"), ton_rub=Decimal("265.40"), star_usd=Decimal("0.015"))


def rendered_text(command, **kwargs):
    """What the chat actually shows, after Telegram's HTML is parsed off."""
    body = render_offer(parse(command), RATES, **kwargs)
    text, entities = tg_html.parse(body)
    return text, entities


def test_card_carries_the_gift_link_as_an_entity():
    _, entities = rendered_text(".buy stars 1500 plushpepe 1234 en")
    urls = [getattr(e, "url", None) for e in entities]
    assert "https://t.me/nft/PlushPepe-1234" in urls


def test_english_card_contents():
    text, _ = rendered_text(".buy stars 1500 plushpepe 1234 en", contact="@trader")
    assert "BUY" in text
    assert "Plush Pepe #1234" in text
    assert "1,500 ⭐" in text
    assert "$23" in text
    assert "@trader" in text


def test_russian_card_contents():
    text, _ = rendered_text(".buy gram 12.5 durovscap 777 ru", contact="@trader")
    assert "КУПЛЮ" in text
    assert "Durov's Cap #777" in text
    assert "12,5 💎" in text
    assert "₽" in text


def test_sell_side_marker_differs():
    buy, _ = rendered_text(".buy stars 10 lolpop 1 en")
    sell, _ = rendered_text(".sell stars 10 lolpop 1 en")
    assert buy.startswith("🟢")
    assert sell.startswith("🔴")


def test_unknown_collection_gets_a_warning_line():
    text, _ = rendered_text(".buy stars 10 brandnewdrop 1 ru")
    assert "проверь ссылку" in text


def test_missing_rates_simply_drop_the_approximate_price():
    body = render_offer(parse(".buy gram 12.5 santahat 7 en"), Rates())
    text, _ = tg_html.parse(body)
    assert "12,5" not in text and "12.5 💎" in text
    assert "≈" not in text


def test_apostrophes_survive_html_escaping():
    text, _ = rendered_text(".buy stars 10 durovscap 1 en")
    assert "Durov's Cap" in text
    assert "&#x27;" not in text


def test_errors_are_localized():
    assert "Stars are whole units" in render_error("stars_fraction", "en", value="1.5")
    assert "Stars — целые" in render_error("stars_fraction", "ru", value="1.5")


def test_unknown_error_code_falls_back_to_usage():
    assert ".buy" in render_error("nonsense_code", "en")
