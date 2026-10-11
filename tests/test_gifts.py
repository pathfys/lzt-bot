import pytest

from offerbot.gifts import gift_link, gift_title, known_slugs, normalize_slug, squash


@pytest.mark.parametrize("spelling", [
    "plushpepe", "Plush Pepe", "PLUSH PEPE", "plush-pepe", "plush_pepe", "PlushPepe",
])
def test_every_spelling_reaches_the_same_slug(spelling):
    assert normalize_slug(spelling) == ("PlushPepe", True)


def test_apostrophes_are_dropped_from_the_slug():
    assert normalize_slug("Durov's Cap") == ("DurovsCap", True)
    assert normalize_slug("durovs cap") == ("DurovsCap", True)


def test_unknown_collection_still_builds_a_link_but_is_flagged():
    slug, known = normalize_slug("brand new drop")
    assert (slug, known) == ("BrandNewDrop", False)
    assert gift_link(slug, 7) == "https://t.me/nft/BrandNewDrop-7"


def test_link_shape():
    assert gift_link("PlushPepe", 1234) == "https://t.me/nft/PlushPepe-1234"


@pytest.mark.parametrize("slug,title", [
    ("PlushPepe", "Plush Pepe"),
    ("DurovsCap", "Durov's Cap"),
    ("BDayCandle", "B-Day Candle"),
    ("SnowGlobe", "Snow Globe"),
])
def test_display_titles(slug, title):
    assert gift_title(slug) == title


def test_squash_is_stable_across_punctuation():
    assert squash("Durov's Cap") == squash("durovs-cap") == "durovscap"


def test_alias_table_has_no_duplicate_squashed_keys():
    slugs = known_slugs()
    assert len({squash(s) for s in slugs}) == len(slugs)
