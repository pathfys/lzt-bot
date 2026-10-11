from decimal import Decimal

import pytest

from offerbot.parser import parse
from offerbot.store import ACCEPTED, CANCELLED, EXPIRED, PENDING, OfferStore

NOW = 1_760_000_000.0


@pytest.fixture
def store():
    db = OfferStore(":memory:")
    yield db
    db.close()


def make(store, command=".buy stars 1500 plushpepe 1234 en 6h", **kwargs):
    defaults = dict(chat_id=-1001, author_id=10, author_label="@author", now=NOW)
    return store.create(parse(command), **{**defaults, **kwargs})


def test_round_trip_preserves_the_offer(store):
    record = make(store)
    offer = record.as_offer()
    assert offer.amount == Decimal(1500)
    assert offer.gift_slug == "PlushPepe"
    assert offer.gift_number == 1234
    assert offer.ttl_seconds == 6 * 3600
    assert offer.gift_known is True
    assert record.status == PENDING
    assert record.expires_at == NOW + 6 * 3600


def test_accept_is_first_come_wins(store):
    record = make(store)
    first = store.accept(record.id, acceptor_id=20, acceptor_label="@first", now=NOW + 10)
    second = store.accept(record.id, acceptor_id=30, acceptor_label="@second", now=NOW + 11)
    assert first is not None
    assert second is None
    assert store.get(record.id).acceptor_label == "@first"
    assert store.get(record.id).status == ACCEPTED


def test_an_expired_offer_cannot_be_accepted(store):
    record = make(store)
    assert store.accept(
        record.id, acceptor_id=20, acceptor_label="@late", now=record.expires_at + 1
    ) is None
    assert store.get(record.id).status == PENDING  # the sweep marks it, not accept


def test_expire_due_only_touches_overdue_pending_offers(store):
    soon = make(store, command=".buy stars 10 lolpop 1 en 30m")
    later = make(store, command=".buy stars 10 lolpop 2 en 12h")
    expired = store.expire_due(NOW + 3600)
    assert [r.id for r in expired] == [soon.id]
    assert store.get(soon.id).status == EXPIRED
    assert store.get(later.id).status == PENDING


def test_closing_twice_is_refused(store):
    record = make(store)
    assert store.close_offer(record.id, CANCELLED, NOW + 5) is not None
    assert store.close_offer(record.id, CANCELLED, NOW + 6) is None


def test_open_offers_survive_a_reopen(tmp_path):
    path = str(tmp_path / "offers.db")
    first = OfferStore(path)
    record = make(first)
    first.close()

    second = OfferStore(path)
    try:
        assert [r.id for r in second.open_offers()] == [record.id]
        assert second.get(record.id).author_label == "@author"
    finally:
        second.close()


def test_buy_sends_the_gift_to_the_author(store):
    record = make(store, command=".buy stars 1500 plushpepe 1234 en")
    accepted = store.accept(record.id, acceptor_id=20, acceptor_label="@owner", now=NOW + 1)
    assert accepted.receiver() == (10, "@author")
    assert accepted.giver() == (20, "@owner")


def test_sell_sends_the_gift_to_the_acceptor(store):
    record = make(store, command=".sell stars 1500 plushpepe 1234 en")
    accepted = store.accept(record.id, acceptor_id=20, acceptor_label="@buyer", now=NOW + 1)
    assert accepted.receiver() == (20, "@buyer")
    assert accepted.giver() == (10, "@author")


def test_an_addressed_offer_remembers_its_target(store):
    record = make(store, target_id=99, target_label="@owner")
    assert record.target_id == 99
    assert record.target_label == "@owner"


def test_message_id_is_attached_after_posting(store):
    record = make(store)
    assert record.message_id is None
    store.attach_message(record.id, 4242)
    assert store.get(record.id).message_id == 4242


def test_drop_removes_an_unposted_offer(store):
    record = make(store)
    store.drop(record.id)
    assert store.get(record.id) is None
    assert store.open_offers() == []
