"""Putting the card into the chat with the gift preview attached.

The whole point of the bot is that the post carries the gift's picture, so the
preview is not left to Telegram's guesswork: the gift URL is attached
explicitly as `InputMediaWebPage`, which

  * pins the preview to that one URL even if the text holds other links,
  * asks for the large image (`force_large_media`),
  * and with `invert_media` puts the picture ABOVE the text.

`optional=True` is what keeps this safe: if Telegram cannot fetch the page —
a gift number that does not exist, a transient failure — the message still
goes out instead of raising.
"""

import asyncio
import logging

from telethon.errors import rpcerrorlist as errors
from telethon.extensions import html as tg_html
from telethon.tl.functions.messages import EditMessageRequest, SendMediaRequest
from telethon.tl.types import InputMediaWebPage

log = logging.getLogger(__name__)

#: Telegram could not build a preview for the URL — post without the picture.
PREVIEW_ERRORS = (
    errors.WebpageCurlFailedError,
    errors.WebpageMediaEmptyError,
    errors.MediaEmptyError,
    errors.MediaInvalidError,
)

#: The original message can no longer be edited — post a fresh one instead.
EDIT_IMPOSSIBLE = (
    errors.MessageIdInvalidError,
    errors.MsgIdInvalidError,
    errors.MessageAuthorRequiredError,
)

#: Nothing will make this chat accept the message.
WRITE_REFUSED = (
    errors.ChatWriteForbiddenError,
    errors.ChatSendPlainForbiddenError,
    errors.UserBannedInChannelError,
)


class DeliveryError(Exception):
    """Delivery failed in a way worth telling the owner about."""

    def __init__(self, reason: str, retry_after: int | None = None):
        super().__init__(reason)
        self.reason = reason
        self.retry_after = retry_after


def web_preview(url: str, *, large: bool = True) -> InputMediaWebPage:
    return InputMediaWebPage(
        url=url,
        force_large_media=True if large else None,
        force_small_media=None if large else True,
        optional=True,
    )


async def deliver(
    client,
    event,
    html_text: str,
    preview_url: str,
    *,
    invert_media: bool = True,
    large_media: bool = True,
    resend_fallback: bool = True,
) -> str:
    """Replace the owner's command with the rendered card.

    Returns a short status for logging: ``edited``, ``edited_no_preview``,
    ``resent`` or ``resent_no_preview``.
    """
    message, entities = tg_html.parse(html_text)
    if not message.strip():
        raise DeliveryError("empty message")

    peer = await event.get_input_chat()
    media = web_preview(preview_url, large=large_media)

    async def edit(with_media):
        await client(EditMessageRequest(
            peer=peer,
            id=event.id,
            message=message,
            entities=entities,
            media=with_media,
            invert_media=invert_media if with_media else None,
        ))

    async def send(with_media):
        # Editing is preferred, but a fresh message is the only way out if the
        # original is gone. The forced preview is kept identical on this path.
        if with_media:
            await client(SendMediaRequest(
                peer=peer,
                media=with_media,
                message=message,
                entities=entities,
                invert_media=invert_media,
            ))
        else:
            await client.send_message(
                peer, message, formatting_entities=entities, link_preview=True,
            )
        try:
            await client.delete_messages(peer, [event.id])
        except Exception as exc:  # the card is already posted; this is cosmetic
            log.warning("could not delete the original command: %s", exc)

    for attempt, (action, with_media, status) in enumerate((
        (edit, media, "edited"),
        (edit, None, "edited_no_preview"),
        (send, media, "resent"),
        (send, None, "resent_no_preview"),
    )):
        if action is send and not resend_fallback:
            break
        try:
            await action(with_media)
            return status
        except errors.MessageNotModifiedError:
            return status  # already says exactly this; nothing to do
        except PREVIEW_ERRORS as exc:
            log.warning("preview rejected for %s: %s", preview_url, exc)
            continue  # same action, no media
        except EDIT_IMPOSSIBLE as exc:
            log.warning("cannot edit message %s: %s", event.id, exc)
            if not resend_fallback:
                raise DeliveryError("message is no longer editable") from exc
            continue
        except errors.SlowModeWaitError as exc:
            # Edits are not slow-mode limited, so this only bites the resend
            # path. Reporting beats silently waiting out a 24h slow mode.
            raise DeliveryError("slow mode", retry_after=exc.seconds) from exc
        except errors.FloodWaitError as exc:
            raise DeliveryError("flood wait", retry_after=exc.seconds) from exc
        except WRITE_REFUSED as exc:
            raise DeliveryError("cannot post in this chat") from exc
        except errors.MessageTooLongError as exc:
            raise DeliveryError("message too long") from exc

    raise DeliveryError("could not deliver the offer")


async def autodelete(client, peer, message_id: int, delay: float) -> None:
    """Remove a transient notice after `delay` seconds, best effort."""
    if delay <= 0:
        return
    await asyncio.sleep(delay)
    try:
        await client.delete_messages(peer, [message_id])
    except Exception as exc:
        log.debug("autodelete failed: %s", exc)
