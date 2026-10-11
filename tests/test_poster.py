from offerbot.poster import web_preview


def test_preview_is_pinned_to_the_url_and_degrades_gracefully():
    media = web_preview("https://t.me/nft/PlushPepe-1234")
    assert media.url == "https://t.me/nft/PlushPepe-1234"
    assert media.force_large_media is True
    # `optional` is what keeps a dead gift number from blocking the post.
    assert media.optional is True


def test_small_media_variant():
    media = web_preview("https://t.me/nft/PlushPepe-1", large=False)
    assert media.force_large_media is None
    assert media.force_small_media is True
