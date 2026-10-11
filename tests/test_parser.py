from decimal import Decimal

import pytest

from offerbot.parser import Offer, ParseError, parse, parse_duration, split_command


def test_documented_form():
    offer = parse(".buy stars 1500 plushpepe 1234 en 6h")
    assert offer == Offer(
        side="buy", currency="stars", amount=Decimal(1500),
        gift_slug="PlushPepe", gift_known=True, gift_number=1234, lang="en",
        ttl_seconds=6 * 3600,
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


# ---- offer lifetime ----

@pytest.mark.parametrize("token,seconds", [
    ("3h", 3 * 3600),
    ("6h", 6 * 3600),
    ("12h", 12 * 3600),
    ("30m", 30 * 60),
    ("1d", 86400),
    ("3ч", 3 * 3600),
    ("90мин", 90 * 60),
])
def test_duration_tokens(token, seconds):
    assert parse_duration(token) == seconds
    assert parse(f".buy stars 100 lolpop 3 en {token}").ttl_seconds == seconds


def test_duration_may_sit_anywhere():
    for command in (
        ".buy stars 100 lolpop 3 en 12h",
        ".buy 12h stars 100 lolpop 3 en",
        ".buy stars 12h 100 lolpop 3 en",
    ):
        assert parse(command).ttl_seconds == 12 * 3600


def test_duration_falls_back_to_the_configured_default():
    assert parse(".buy stars 100 lolpop 3 en").ttl_seconds == 6 * 3600
    assert parse(".buy stars 100 lolpop 3 en", default_ttl=1800).ttl_seconds == 1800


def test_a_duration_is_not_mistaken_for_a_price():
    offer = parse(".buy stars 1500 plushpepe 1234 en 6h")
    assert offer.amount == Decimal(1500)
    assert offer.gift_number == 1234
    assert offer.ttl_seconds == 6 * 3600


@pytest.mark.parametrize("token", ["1m", "99d", "0h"])
def test_out_of_range_lifetimes_are_rejected(token):
    with pytest.raises(ParseError) as caught:
        parse(f".buy stars 100 lolpop 3 en {token}")
    assert caught.value.code == "bad_ttl"


def test_non_duration_tokens_are_not_swallowed():
    assert parse_duration("plushpepe") is None
    assert parse_duration("1234") is None
