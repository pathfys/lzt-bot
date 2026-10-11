from decimal import Decimal

import pytest

from offerbot.parser import Offer, ParseError, parse, split_command


def test_documented_form():
    offer = parse(".buy stars 1500 plushpepe 1234 en")
    assert offer == Offer(
        side="buy", currency="stars", amount=Decimal(1500),
        gift_slug="PlushPepe", gift_known=True, gift_number=1234, lang="en",
    )


@pytest.mark.parametrize("command", [
    ".buy stars 1500 plushpepe 1234 en",
    ".buy 1500 stars plushpepe 1234 en",
    ".buy en stars plushpepe 1500 1234",
    ".buy stars 1500 PlushPepe-1234 en",
    ".buy stars 1500 plushpepe #1234 en",
    ".buy 1500stars plushpepe 1234 en",
    ".buy stars 1500 plush pepe 1234 en",
    ".buy ⭐ 1500 plush-pepe 1234 english",
])
def test_tolerant_forms_all_agree(command):
    offer = parse(command)
    assert (offer.currency, offer.amount, offer.gift_slug, offer.gift_number) == (
        "stars", Decimal(1500), "PlushPepe", 1234,
    )


def test_gram_aliases_and_decimals():
    for command in (".buy gram 12.5 santahat 7 ru", ".buy ton 12,5 santahat 7 ru"):
        offer = parse(command)
        assert offer.currency == "gram"
        assert offer.amount == Decimal("12.5")
        assert offer.lang == "ru"


def test_russian_side_words():
    assert parse(".куплю stars 100 lolpop 3 ru").side == "buy"
    assert parse(".продам stars 100 lolpop 3 ru").side == "sell"


def test_language_defaults_and_override():
    assert parse(".buy stars 10 lolpop 1").lang == "en"
    assert parse(".buy stars 10 lolpop 1", default_lang="ru").lang == "ru"
    assert parse(".buy stars 10 lolpop 1 en", default_lang="ru").lang == "en"


def test_currency_default_is_used_only_when_absent():
    assert parse(".buy 10 lolpop 1", default_currency="gram").currency == "gram"
    assert parse(".buy stars 10 lolpop 1", default_currency="gram").currency == "stars"


@pytest.mark.parametrize("command,code", [
    (".buy", "usage"),
    (".buy stars", "usage"),
    (".buy 10 lolpop 1", "no_currency"),
    (".buy stars 1500 plushpepe", "no_number"),
    (".buy stars 12.5 plushpepe 1 en", "stars_fraction"),
    (".buy stars 1500 2000 plushpepe #1 en", "ambiguous_numbers"),
    (".buy stars 0 plushpepe 1 en", "bad_amount"),
    (".buy stars 1500 #1 en", "no_gift"),
    (".buy stars 1500 plushpepe 99999999999 en", "bad_number"),
])
def test_rejections(command, code):
    with pytest.raises(ParseError) as caught:
        parse(command)
    assert caught.value.code == code


def test_fractional_gram_is_allowed_but_fractional_gift_number_is_not():
    assert parse(".buy gram 0.5 lolpop 1 en").amount == Decimal("0.5")
    with pytest.raises(ParseError) as caught:
        parse(".buy gram 0.5 lolpop 1.5 en")
    assert caught.value.code == "bad_number"


def test_split_command_ignores_unrelated_text():
    assert split_command("hello there") is None
    assert split_command(".buyer beware") is None
    assert split_command(".buy stars 1 a 1") == ("buy", "stars 1 a 1")
