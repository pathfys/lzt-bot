"""The bot side: posting the card, handling the buttons, expiring offers.

Everything that involves a button lives here, because inline keyboards and
callback queries are bot-only in the Telegram API. The user account cannot do
either, so it only triggers the command (see handlers.py) and this posts.
"""

import asyncio
import logging
import time

from telethon import events, utils
from telethon.errors import rpcerrorlist as errors
from telethon.extensions import html as tg_html
from telethon.tl.functions.messages import EditMessageRequest, SendMediaRequest
from telethon.tl.types import (
    InputPeerChannel,
    InputPeerChat,
    InputPeerUser,
    PeerChannel,
    PeerChat,
    ReplyInlineMarkup,
    UpdateEditChannelMessage,
    UpdateEditMessage,
    UpdateMessageID,
    UpdateNewChannelMessage,
    UpdateNewMessage,
)

from .buttons import ACCEPT, CALLBACK_RE, offer_keyboard, transfer_keyboard
from .gifts import gift_link
from .poster import web_preview
from .render import (
    alert,
    render_accepted,
    render_declined,
    render_expired,
    render_offer,
)
from .store import CANCELLED, DECLINED, EXPIRED, OfferRecord, OfferStore

log = logging.getLogger(__name__)


def _message_id(result) -> int | None:
    """Dig the new message id out of the Updates a raw send returns."""
    for update in getattr(result, "updates", []) or []:
        if isinstance(update, UpdateMessageID):
            return update.id
        if isinstance(update, (UpdateNewMessage, UpdateNewChannelMessage,
                               UpdateEditMessage, UpdateEditChannelMessage)):
            return update.message.id
    return getattr(result, "id", None)


def label_for(entity, user_id: int) -> str:
    """'@nick' when there is a username, a display name otherwise, id last.

    Reads the attributes directly instead of `utils.get_display_name`, whose
    isinstance check makes it return nothing for anything but a concrete
    Telethon type.
    """
    username = getattr(entity, "username", None)
    if username:
        return f"@{username}"
    parts = [getattr(entity, "first_name", None), getattr(entity, "last_name", None)]
    name = " ".join(part for part in parts if part).strip()
    return name or getattr(entity, "title", None) or str(user_id)


def username_of(label: str | None) -> str | None:
    """Labels are '@nick' when a username exists and a display name otherwise."""
    if label and label.startswith("@") and len(label) > 1:
        return label[1:]
    return None


class OfferBot:
    """Posts offer cards and owns their lifecycle."""

    def __init__(self, client, config, store: OfferStore, rates, clock=time.time):
        self._client = client
        self._config = config
        self._store = store
        self._rates = rates
        #: Injected so expiry is testable without waiting hours.
        self._clock = clock
        self._sweeper: asyncio.Task | None = None

    # ---- posting ----

    async def peer(self, chat_id: int):
        """Resolve a chat for the bot.

        A chat's access hash is per-account, so the user account's copy is
        useless here. Bots may pass 0 for peers they can reach, which is the
        fallback when the bot's own cache has never seen the chat.
        """
        try:
            return await self._client.get_input_entity(chat_id)
        except (ValueError, TypeError):
            real_id, kind = utils.resolve_id(chat_id)
            if kind is PeerChannel:
                return InputPeerChannel(real_id, 0)
            if kind is PeerChat:
                return InputPeerChat(real_id)
            return InputPeerUser(real_id, 0)

    async def post(
        self,
        chat_id: int,
        offer,
        *,
        author_id: int,
        author_label: str,
        target_id: int | None = None,
        target_label: str | None = None,
    ) -> OfferRecord:
        """Create the offer and put its card in the chat. Raises on failure."""
        now = self._clock()
        record = self._store.create(
            offer,
            chat_id=chat_id,
            author_id=author_id,
            author_label=author_label,
            now=now,
            target_id=target_id,
            target_label=target_label,
        )

        body = render_offer(
            offer,
            await self._rates.get(),
            contact=author_label,
            target=target_label,
            escrow=self._config.escrow,
            expires_at=record.expires_at,
            now=now,
        )
        message, entities = tg_html.parse(body)

        try:
            result = await self._client(SendMediaRequest(
                peer=await self.peer(chat_id),
                media=web_preview(
                    gift_link(offer.gift_slug, offer.gift_number),
                    large=self._config.large_media,
                ),
                message=message,
                entities=entities,
                invert_media=self._config.invert_media,
                reply_markup=offer_keyboard(record.id, offer.lang),
            ))
        except Exception:
            # The card is what makes an offer real; a row without one is
            # unresolvable, so it does not get to stay.
            self._store.drop(record.id)
            raise

        message_id = _message_id(result)
        if message_id:
            self._store.attach_message(record.id, message_id)
        else:
            log.warning("posted offer %s but could not read its message id", record.id)
        return self._store.get(record.id)

    # ---- editing a card in place ----

    async def _rewrite(self, record: OfferRecord, body: str, keyboard) -> None:
        """Replace a card's text and keyboard, keeping the gift preview.

        The media is passed again on purpose: an edit that omits it leaves the
        preview up to the server, and the picture is the point of the card.
        """
        if not record.message_id:
            return
        message, entities = tg_html.parse(body)
        media = web_preview(
            gift_link(record.gift_slug, record.gift_number),
            large=self._config.large_media,
        )
        request = EditMessageRequest(
            peer=await self.peer(record.chat_id),
            id=record.message_id,
            message=message,
            entities=entities,
            media=media,
            invert_media=self._config.invert_media,
            reply_markup=keyboard,
        )
        try:
            await self._client(request)
        except errors.MessageNotModifiedError:
            pass
        except errors.RPCError as exc:
            # An empty keyboard is how a closed card drops its buttons; if the
            # server will not take it, the card still reads as closed and the
            # buttons answer "already closed".
            if keyboard is not None and not keyboard.rows:
                log.warning("could not clear buttons on offer %s: %s", record.id, exc)
                request.reply_markup = None
                await self._client(request)
            else:
                raise

    async def _close_card(self, record: OfferRecord, body: str) -> None:
        await self._rewrite(record, body, ReplyInlineMarkup(rows=[]))

    # ---- buttons ----

    def register(self) -> None:
        @self._client.on(events.CallbackQuery(pattern=CALLBACK_RE))
        async def on_press(event):
            match = CALLBACK_RE.match(event.data)
            if not match:
                return
            offer_id = int(match.group(1))
            action = match.group(2).decode()
            await self._handle_press(event, offer_id, action)

    async def _handle_press(self, event, offer_id: int, action: str) -> None:
        record = self._store.get(offer_id)
        if record is None:
            await event.answer(alert("gone", self._config.default_lang), alert=True)
            return

        lang = record.lang
        now = self._clock()

        if not record.is_open:
            code = "expired" if record.status == EXPIRED else "closed"
            await event.answer(alert(code, lang), alert=True)
            return

        if record.expires_at <= now:
            expired = self._store.close_offer(record.id, EXPIRED, now)
            if expired:
                await self._close_card(expired, render_expired(expired.as_offer()))
            await event.answer(alert("expired", lang), alert=True)
            return

        if action == ACCEPT:
            await self._accept(event, record, now)
        else:
            await self._decline(event, record, now)

    async def _accept(self, event, record: OfferRecord, now: float) -> None:
        lang = record.lang
        presser = event.sender_id

        if presser == record.author_id:
            await event.answer(alert("own_offer", lang), alert=True)
            return
        if record.target_id and presser != record.target_id:
            await event.answer(alert("not_addressed", lang), alert=True)
            return

        accepted = self._store.accept(
            record.id,
            acceptor_id=presser,
            acceptor_label=label_for(await event.get_sender(), presser),
            now=now,
        )
        if accepted is None:
            await event.answer(alert("too_late", lang), alert=True)
            return

        receiver_id, receiver_label = accepted.receiver()
        body = render_accepted(
            accepted.as_offer(),
            acceptor=accepted.acceptor_label,
            receiver=receiver_label,
            resolved_at=now,
        )
        keyboard = await transfer_keyboard(
            self._client, lang, receiver_id, username_of(receiver_label),
        )
        await self._rewrite(accepted, body, keyboard)
        await event.answer(alert("accepted_ok", lang))
        log.info(
            "offer %s accepted by %s; %s hands the gift to %s",
            accepted.id, presser, accepted.giver()[1], receiver_label,
        )

    async def _decline(self, event, record: OfferRecord, now: float) -> None:
        lang = record.lang
        presser = event.sender_id
        by_author = presser == record.author_id

        if not by_author and presser != record.target_id:
            # A public offer is not something a bystander can close.
            await event.answer(alert("author_only", lang), alert=True)
            return

        closed = self._store.close_offer(
            record.id, CANCELLED if by_author else DECLINED, now,
        )
        if closed is None:
            await event.answer(alert("closed", lang), alert=True)
            return

        await self._close_card(closed, render_declined(closed.as_offer(), by_author=by_author))
        await event.answer(
            alert("cancelled_ok" if by_author else "declined_ok", lang)
        )
        log.info("offer %s %s by %s", closed.id, closed.status, presser)

    # ---- expiry ----

    async def sweep_once(self) -> int:
        expired = self._store.expire_due(self._clock())
        for record in expired:
            try:
                await self._close_card(record, render_expired(record.as_offer()))
            except errors.RPCError as exc:
                log.warning("could not close expired offer %s: %s", record.id, exc)
        return len(expired)

    def start_sweeper(self) -> None:
        """Expire offers on a timer.

        A sweep rather than a timer per offer: it survives restarts for free
        and cannot leak tasks.
        """
        async def loop():
            while True:
                try:
                    count = await self.sweep_once()
                    if count:
                        log.info("expired %s offer(s)", count)
                except Exception as exc:
                    log.exception("sweep failed: %s", exc)
                await asyncio.sleep(self._config.sweep_interval)

        self._sweeper = asyncio.create_task(loop())
