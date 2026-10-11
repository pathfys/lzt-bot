"""The button flow, exercised against a fake client — no Telegram involved."""

import asyncio

import pytest
from telethon.extensions import html as tg_html
from telethon.tl.functions.messages import EditMessageRequest
from telethon.tl.types import (
    InlineButtonTypeCallback,
    InputPeerChannel,
    InputPeerUser,
)

from offerbot.bot import OfferBot
from offerbot.config import Config
from offerbot.parser import parse
from offerbot.rates import Rates
from offerbot.store import ACCEPTED, CANCELLED, DECLINED, EXPIRED, OfferStore

NOW = 1_760_000_000.0
AUTHOR, OWNER, BYSTANDER = 10, 20, 30


class FakeRates:
    async def get(self):
        return Rates()


class FakeClient:
    def __init__(self):
        self.requests = []
        self.sent_message_id = 555

    async def get_input_entity(self, peer_id):
        if isinstance(peer_id, int) and peer_id < 0:
            return InputPeerChannel(abs(peer_id), 0)
        return InputPeerUser(peer_id, 0)

    async def __call__(self, request):
        self.requests.append(request)

        class Result:
            id = self.sent_message_id

        return Result()

    def on(self, event):  # the flow tests call the handler directly
        return lambda func: func


class FakeSender:
    def __init__(self, username):
        self.username = username
        self.first_name = ""
        self.last_name = ""


class FakeEvent:
    def __init__(self, data: bytes, sender_id: int, username: str = "presser"):
        self.data = data
        self.sender_id = sender_id
        self.answers = []
        self._sender = FakeSender(username)

    async def answer(self, text=None, alert=False):
        self.answers.append((text, alert))

    async def get_sender(self):
        return self._sender


def config():
    return Config(
        api_id=0, api_hash="", session="", session_is_string=False,
        escrow=True, invert_media=True, large_media=True,
    )


@pytest.fixture
def setup():
    store = OfferStore(":memory:")
    client = FakeClient()
    bot = OfferBot(client, config(), store, FakeRates(), clock=lambda: NOW + 60)
    yield bot, client, store
    store.close()


def make_offer(store, command=".buy stars 1500 plushpepe 1234 ru 6h", **kwargs):
    defaults = dict(chat_id=-1001, author_id=AUTHOR, author_label="@author", now=NOW)
    record = store.create(parse(command), **{**defaults, **kwargs})
    store.attach_message(record.id, 555)
    return store.get(record.id)


def press(bot, record, who, action="a", username="owner"):
    event = FakeEvent(f"o:{record.id}:{action}".encode(), who, username)
    asyncio.run(bot._handle_press(event, record.id, action))
    return event


def last_edit(client) -> str:
    edits = [r for r in client.requests if isinstance(r, EditMessageRequest)]
    assert edits, "no edit was sent"
    return edits[-1].message


# ---- posting ----

def test_post_stores_the_card_and_attaches_its_message_id(setup):
    bot, client, store = setup
    record = asyncio.run(bot.post(
        -1001, parse(".buy stars 1500 plushpepe 1234 en 6h"),
        author_id=AUTHOR, author_label="@author",
    ))
    assert record.message_id == 555
    sent = client.requests[-1]
    assert sent.media.url == "https://t.me/nft/PlushPepe-1234"
    assert sent.media.optional is True
    assert sent.invert_media is True
    buttons = sent.reply_markup.rows[0].buttons
    assert [b.text for b in buttons] == ["Accept", "Decline"]
    assert all(isinstance(b.type, InlineButtonTypeCallback) for b in buttons)


# ---- accepting ----

def test_a_stranger_accepting_closes_the_offer_and_names_the_receiver(setup):
    bot, client, store = setup
    record = make_offer(store)
    event = press(bot, record, OWNER)

    assert store.get(record.id).status == ACCEPTED
    text, _ = tg_html.parse(last_edit(client))
    assert "ОФФЕР ПРИНЯТ" in text
    assert "Передайте подарок пользователю @author" in text
    assert event.answers[-1][1] is False  # a toast, not an alarming alert


def test_the_accepted_card_gets_a_single_profile_button(setup):
    bot, client, store = setup
    press(bot, make_offer(store), OWNER)
    markup = [r for r in client.requests if isinstance(r, EditMessageRequest)][-1].reply_markup
    assert len(markup.rows) == 1
    assert markup.rows[0].buttons[0].text == "Передать НФТ"


def test_the_accepted_card_keeps_the_gift_preview(setup):
    bot, client, store = setup
    press(bot, make_offer(store), OWNER)
    edit = [r for r in client.requests if isinstance(r, EditMessageRequest)][-1]
    assert edit.media.url == "https://t.me/nft/PlushPepe-1234"


def test_the_author_cannot_accept_their_own_offer(setup):
    bot, client, store = setup
    record = make_offer(store)
    event = press(bot, record, AUTHOR)
    assert store.get(record.id).status == "pending"
    assert event.answers == [("Это твой собственный оффер.", True)]


def test_only_the_addressee_may_accept_an_addressed_offer(setup):
    bot, client, store = setup
    record = make_offer(store, target_id=OWNER, target_label="@owner")

    rejected = press(bot, record, BYSTANDER)
    assert store.get(record.id).status == "pending"
    assert rejected.answers == [("Этот оффер адресован другому пользователю.", True)]

    accepted = press(bot, record, OWNER)
    assert store.get(record.id).status == ACCEPTED
    assert accepted.answers[-1][1] is False


def test_the_second_presser_is_told_someone_was_faster(setup):
    bot, client, store = setup
    record = make_offer(store)
    press(bot, record, OWNER)
    late = press(bot, record, BYSTANDER)
    assert late.answers == [("Оффер уже закрыт.", True)]


# ---- declining ----

def test_the_author_cancels_their_own_offer(setup):
    bot, client, store = setup
    record = make_offer(store)
    event = press(bot, record, AUTHOR, action="d")
    assert store.get(record.id).status == CANCELLED
    text, _ = tg_html.parse(last_edit(client))
    assert "ОФФЕР ОТМЕНЁН" in text
    assert event.answers[-1] == ("Отменено.", False)


def test_the_addressee_declines(setup):
    bot, client, store = setup
    record = make_offer(store, target_id=OWNER, target_label="@owner")
    press(bot, record, OWNER, action="d")
    assert store.get(record.id).status == DECLINED
    text, _ = tg_html.parse(last_edit(client))
    assert "ОФФЕР ОТКЛОНЁН" in text


def test_a_bystander_cannot_close_a_public_offer(setup):
    bot, client, store = setup
    record = make_offer(store)
    event = press(bot, record, BYSTANDER, action="d")
    assert store.get(record.id).status == "pending"
    assert event.answers == [("Отменить оффер может только его автор.", True)]


def test_a_closed_card_drops_its_buttons(setup):
    bot, client, store = setup
    press(bot, make_offer(store), AUTHOR, action="d")
    markup = [r for r in client.requests if isinstance(r, EditMessageRequest)][-1].reply_markup
    assert markup.rows == []


# ---- expiry ----

def test_pressing_an_overdue_offer_expires_it_in_place(setup):
    bot, client, store = setup
    record = store.create(
        parse(".buy stars 10 lolpop 1 ru 30m"),
        chat_id=-1001, author_id=AUTHOR, author_label="@author", now=NOW - 7200,
    )
    store.attach_message(record.id, 555)
    event = press(bot, record, OWNER)

    assert store.get(record.id).status == EXPIRED
    assert event.answers == [("Срок оффера истёк.", True)]
    text, _ = tg_html.parse(last_edit(client))
    assert "ОФФЕР ИСТЁК" in text


def test_the_sweep_expires_overdue_offers_and_rewrites_their_cards(setup):
    bot, client, store = setup
    record = store.create(
        parse(".buy stars 10 lolpop 1 en 30m"),
        chat_id=-1001, author_id=AUTHOR, author_label="@author", now=NOW - 7200,
    )
    store.attach_message(record.id, 555)
    assert asyncio.run(bot.sweep_once()) == 1
    assert store.get(record.id).status == EXPIRED
    text, _ = tg_html.parse(last_edit(client))
    assert "OFFER EXPIRED" in text


def test_pressing_a_forgotten_offer_says_so(setup):
    bot, client, store = setup
    event = FakeEvent(b"o:999:a", OWNER)
    asyncio.run(bot._handle_press(event, 999, "a"))
    assert event.answers[0][1] is True
    assert "records" in event.answers[0][0] or "базе" in event.answers[0][0]


# ---- failure to post ----

class RefusingClient(FakeClient):
    async def __call__(self, request):
        raise RuntimeError("CHAT_WRITE_FORBIDDEN")


def test_a_card_that_cannot_be_posted_leaves_no_row_behind():
    store = OfferStore(":memory:")
    bot = OfferBot(RefusingClient(), config(), store, FakeRates(), clock=lambda: NOW)
    try:
        with pytest.raises(RuntimeError):
            asyncio.run(bot.post(
                -1001, parse(".buy stars 10 lolpop 1 en 6h"),
                author_id=AUTHOR, author_label="@author",
            ))
        assert store.open_offers() == []
    finally:
        store.close()
