"""Inline keyboards.

Inline keyboards are a bot-only feature of the Telegram API: a user account
cannot attach them, and cannot receive the resulting button presses. That is
why the card is posted by a companion bot rather than by the account itself.
"""

import logging
import re

from telethon.tl.types import (
    InlineButtonTypeCallback,
    InlineButtonTypeUrl,
    InputInlineButtonTypeUserProfile,
    KeyboardInlineButton,
    KeyboardInlineButtonRow,
    ReplyInlineMarkup,
)

from .render import button_label

log = logging.getLogger(__name__)

ACCEPT = "a"
DECLINE = "d"

CALLBACK_RE = re.compile(rb"^o:(\d+):([ad])$")


def callback_data(offer_id: int, action: str) -> bytes:
    """Callback payloads are capped at 64 bytes, so keep this terse."""
    data = f"o:{offer_id}:{action}".encode()
    if len(data) > 64:
        raise ValueError("callback data too long")
    return data


def offer_keyboard(offer_id: int, lang: str) -> ReplyInlineMarkup:
    return ReplyInlineMarkup(rows=[
        KeyboardInlineButtonRow(buttons=[
            KeyboardInlineButton(
                text=button_label("accept", lang),
                type=InlineButtonTypeCallback(data=callback_data(offer_id, ACCEPT)),
            ),
            KeyboardInlineButton(
                text=button_label("decline", lang),
                type=InlineButtonTypeCallback(data=callback_data(offer_id, DECLINE)),
            ),
        ]),
    ])


async def profile_button(
    client, label: str, user_id: int, username: str | None = None
) -> KeyboardInlineButton:
    """A button that takes the presser to `user_id`'s profile.

    Three ways in, most faithful first:

    1. `InputInlineButtonTypeUserProfile` opens the profile card itself, but
       the bot needs the user's access hash — it only has that for users it
       has actually seen (anyone who pressed a button, for instance).
    2. A plain t.me link, which works for anyone with a username.
    3. `tg://user?id=` as a last resort for a hash-less, username-less user.
    """
    try:
        entity = await client.get_input_entity(user_id)
        return KeyboardInlineButton(
            text=label, type=InputInlineButtonTypeUserProfile(user_id=entity),
        )
    except (ValueError, TypeError) as exc:
        log.debug("no cached entity for %s: %s", user_id, exc)

    if username:
        return KeyboardInlineButton(
            text=label,
            type=InlineButtonTypeUrl(url=f"https://t.me/{username.lstrip('@')}"),
        )

    return KeyboardInlineButton(
        text=label, type=InlineButtonTypeUrl(url=f"tg://user?id={user_id}"),
    )


async def transfer_keyboard(
    client, lang: str, user_id: int, username: str | None = None
) -> ReplyInlineMarkup:
    button = await profile_button(
        client, button_label("transfer", lang), user_id, username,
    )
    return ReplyInlineMarkup(rows=[KeyboardInlineButtonRow(buttons=[button])])
