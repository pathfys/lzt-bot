from decimal import Decimal

import pytest

from offerbot.money import fmt_amount, fmt_usd


@pytest.mark.parametrize("value,en,ru", [
    ("1500", "1,500", "1 500"),
    ("1234.5", "1,234.5", "1 234,5"),
    ("1234567.891", "1,234,567.89", "1 234 567,89"),
    ("12.00", "12", "12"),
    ("0.5", "0.5", "0,5"),
    ("999", "999", "999"),
])
def test_grouping_and_decimal_separators(value, en, ru):
    assert fmt_amount(Decimal(value), "en") == en
    assert fmt_amount(Decimal(value), "ru") == ru


def test_integer_rendering_drops_the_fraction():
    assert fmt_amount(Decimal("1500.4"), "en", max_dp=0) == "1,500"


def test_usd_keeps_cents_only_for_small_values():
    assert fmt_usd(Decimal("1234.56")) == "$1,235"
    assert fmt_usd(Decimal("4.219")) == "$4.22"


def test_unknown_language_falls_back_to_english_separators():
    assert fmt_amount(Decimal("1500"), "de") == "1,500"
