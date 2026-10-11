"""Persistent offer state.

An offer lives for hours, so in-memory state is not enough: a restart during a
6h window would leave cards in chats whose buttons answer "unknown offer", and
would silently stop their expiry. SQLite keeps it honest and gives the one
thing this really needs — an atomic first-come-wins accept.
"""

import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from .parser import Offer

PENDING = "pending"
ACCEPTED = "accepted"
DECLINED = "declined"
CANCELLED = "cancelled"
EXPIRED = "expired"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS offers (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id       INTEGER NOT NULL,
    message_id    INTEGER,
    author_id     INTEGER NOT NULL,
    author_label  TEXT    NOT NULL,
    target_id     INTEGER,
    target_label  TEXT,
    side          TEXT    NOT NULL,
    currency      TEXT    NOT NULL,
    amount        TEXT    NOT NULL,
    gift_slug     TEXT    NOT NULL,
    gift_known    INTEGER NOT NULL,
    gift_number   INTEGER NOT NULL,
    lang          TEXT    NOT NULL,
    ttl_seconds   INTEGER NOT NULL,
    created_at    REAL    NOT NULL,
    expires_at    REAL    NOT NULL,
    status        TEXT    NOT NULL,
    acceptor_id   INTEGER,
    acceptor_label TEXT,
    resolved_at   REAL
);
CREATE INDEX IF NOT EXISTS offers_open ON offers (status, expires_at);
"""


@dataclass(frozen=True)
class OfferRecord:
    id: int
    chat_id: int
    message_id: int | None
    author_id: int
    author_label: str
    target_id: int | None
    target_label: str | None
    side: str
    currency: str
    amount: Decimal
    gift_slug: str
    gift_known: bool
    gift_number: int
    lang: str
    ttl_seconds: int
    created_at: float
    expires_at: float
    status: str
    acceptor_id: int | None
    acceptor_label: str | None
    resolved_at: float | None

    def as_offer(self) -> Offer:
        """The pure value object the renderer works with."""
        return Offer(
            side=self.side,
            currency=self.currency,
            amount=self.amount,
            gift_slug=self.gift_slug,
            gift_known=bool(self.gift_known),
            gift_number=self.gift_number,
            lang=self.lang,
            ttl_seconds=self.ttl_seconds,
        )

    @property
    def is_open(self) -> bool:
        return self.status == PENDING

    def receiver(self) -> tuple[int, str]:
        """Who must end up holding the gift, as (user_id, label).

        On a buy the author is paying, so the gift goes to them; on a sell the
        author owns it and the acceptor receives it.
        """
        if self.side == "buy":
            return self.author_id, self.author_label
        return self.acceptor_id, self.acceptor_label

    def giver(self) -> tuple[int, str]:
        """The counterparty of `receiver` — the one who hands the gift over."""
        if self.side == "buy":
            return self.acceptor_id, self.acceptor_label
        return self.author_id, self.author_label


def _record(row: sqlite3.Row) -> OfferRecord:
    data = dict(row)
    data["amount"] = Decimal(data["amount"])
    data["gift_known"] = bool(data["gift_known"])
    return OfferRecord(**data)


class OfferStore:
    def __init__(self, path: str = "offers.db"):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.executescript(_SCHEMA)

    def close(self) -> None:
        self._db.close()

    # ---- writes ----

    def create(
        self,
        offer: Offer,
        *,
        chat_id: int,
        author_id: int,
        author_label: str,
        now: float,
        target_id: int | None = None,
        target_label: str | None = None,
    ) -> OfferRecord:
        cursor = self._db.execute(
            """
            INSERT INTO offers (
                chat_id, author_id, author_label, target_id, target_label,
                side, currency, amount, gift_slug, gift_known, gift_number,
                lang, ttl_seconds, created_at, expires_at, status
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                chat_id, author_id, author_label, target_id, target_label,
                offer.side, offer.currency, str(offer.amount), offer.gift_slug,
                int(offer.gift_known), offer.gift_number, offer.lang,
                offer.ttl_seconds, now, now + offer.ttl_seconds, PENDING,
            ),
        )
        return self.get(cursor.lastrowid)

    def drop(self, offer_id: int) -> None:
        """Remove an offer whose card never reached the chat.

        Without this, every command typed in a chat the bot cannot post to
        would leave a pending row behind that nothing can ever resolve.
        """
        self._db.execute("DELETE FROM offers WHERE id = ?", (offer_id,))

    def attach_message(self, offer_id: int, message_id: int) -> None:
        self._db.execute(
            "UPDATE offers SET message_id = ? WHERE id = ?", (message_id, offer_id)
        )

    def accept(
        self, offer_id: int, *, acceptor_id: int, acceptor_label: str, now: float
    ) -> OfferRecord | None:
        """Atomic first-come-wins. None means someone else got there first."""
        cursor = self._db.execute(
            """
            UPDATE offers
               SET status = ?, acceptor_id = ?, acceptor_label = ?, resolved_at = ?
             WHERE id = ? AND status = ? AND expires_at > ?
            """,
            (ACCEPTED, acceptor_id, acceptor_label, now, offer_id, PENDING, now),
        )
        if cursor.rowcount != 1:
            return None
        return self.get(offer_id)

    def close_offer(self, offer_id: int, status: str, now: float) -> OfferRecord | None:
        cursor = self._db.execute(
            """
            UPDATE offers SET status = ?, resolved_at = ?
             WHERE id = ? AND status = ?
            """,
            (status, now, offer_id, PENDING),
        )
        if cursor.rowcount != 1:
            return None
        return self.get(offer_id)

    def expire_due(self, now: float) -> list[OfferRecord]:
        """Mark every overdue pending offer expired and return those rows."""
        rows = self._db.execute(
            "SELECT id FROM offers WHERE status = ? AND expires_at <= ?",
            (PENDING, now),
        ).fetchall()
        expired = []
        for row in rows:
            record = self.close_offer(row["id"], EXPIRED, now)
            if record:
                expired.append(record)
        return expired

    # ---- reads ----

    def get(self, offer_id: int) -> OfferRecord | None:
        row = self._db.execute(
            "SELECT * FROM offers WHERE id = ?", (offer_id,)
        ).fetchone()
        return _record(row) if row else None

    def open_offers(self) -> list[OfferRecord]:
        rows = self._db.execute(
            "SELECT * FROM offers WHERE status = ? ORDER BY expires_at", (PENDING,)
        ).fetchall()
        return [_record(row) for row in rows]
