import asyncio

from telethon.tl.types import (
    InlineButtonTypeCallback,
    InlineButtonTypeUrl,
    InputInlineButtonTypeUserProfile,
    InputPeerUser,
)

from offerbot.bot import label_for, username_of
from offerbot.buttons import (
    ACCEPT,
    CALLBACK_RE,
    DECLINE,
    callback_data,
    offer_keyboard,
    profile_button,
    transfer_keyboard,
)


class FakeClient:
    """Stands in for a bot client: either it knows the user, or it does not."""

    def __init__(self, entity=None):
        self._entity = entity

    async def get_input_entity(self, user_id):
        if self._entity is None:
            raise ValueError("could not find the input entity")
        return self._entity


class FakeUser:
    def __init__(self, username=None, first_name="", last_name=""):
        self.username = username
        self.first_name = first_name
        self.last_name = last_name


def test_offer_keyboard_has_exactly_two_callback_buttons():
    markup = offer_keyboard(7, "ru")
    buttons = markup.rows[0].buttons
    assert [b.text for b in buttons] == ["Принять", "Отклонить"]
    assert all(isinstance(b.type, InlineButtonTypeCallback) for b in buttons)
    assert len(markup.rows) == 1


def test_callback_data_round_trips():
    for action in (ACCEPT, DECLINE):
        data = callback_data(123, action)
        match = CALLBACK_RE.match(data)
        assert match
        assert int(match.group(1)) == 123
        assert match.group(2).decode() == action


def test_callback_data_stays_inside_the_64_byte_limit():
    assert len(callback_data(9_999_999_999, ACCEPT)) <= 64


def test_callback_pattern_rejects_foreign_payloads():
    assert CALLBACK_RE.match(b"o:1:x") is None
    assert CALLBACK_RE.match(b"other:1:a") is None
    assert CALLBACK_RE.match(b"o:abc:a") is None


def run(coro):
    """These helpers are async only because they may ask the client for an
    entity; running them directly keeps the tests session-free."""
    return asyncio.run(coro)


def test_profile_button_prefers_the_real_profile_type():
    client = FakeClient(InputPeerUser(user_id=5, access_hash=7))
    button = run(profile_button(client, "Передать НФТ", 5, "nick"))
    assert isinstance(button.type, InputInlineButtonTypeUserProfile)
    assert button.text == "Передать НФТ"


def test_profile_button_falls_back_to_a_username_link():
    button = run(profile_button(FakeClient(None), "Transfer NFT", 5, "@nick"))
    assert isinstance(button.type, InlineButtonTypeUrl)
    assert button.type.url == "https://t.me/nick"


def test_profile_button_last_resort_is_a_tg_user_link():
    button = run(profile_button(FakeClient(None), "Transfer NFT", 5, None))
    assert isinstance(button.type, InlineButtonTypeUrl)
    assert button.type.url == "tg://user?id=5"


def test_transfer_keyboard_is_a_single_button():
    markup = run(transfer_keyboard(FakeClient(None), "ru", 5, "nick"))
    assert len(markup.rows) == 1
    assert len(markup.rows[0].buttons) == 1
    assert markup.rows[0].buttons[0].text == "Передать НФТ"


def test_username_of_reads_labels_back():
    assert username_of("@nick") == "nick"
    assert username_of("Имя Фамилия") is None
    assert username_of("@") is None
    assert username_of(None) is None


def test_label_for_prefers_username_then_name_then_id():
    assert label_for(FakeUser(username="nick"), 5) == "@nick"
    assert label_for(FakeUser(first_name="Иван", last_name="Петров"), 5) == "Иван Петров"
    assert label_for(FakeUser(first_name="Иван"), 5) == "Иван"
    assert label_for(FakeUser(), 5) == "5"
    assert label_for(None, 5) == "5"
