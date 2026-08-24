from __future__ import annotations

import logging

from telegram import Bot


class Notifier:
    """Sends plain-text reports to the owner via the control bot."""

    def __init__(self, bot_token: str, chat_id: int) -> None:
        self._bot = Bot(token=bot_token)
        self._chat_id = chat_id
        self._log = logging.getLogger(__name__)

    async def send(self, text: str) -> None:
        try:
            await self._bot.send_message(chat_id=self._chat_id, text=text)
        except Exception:
            # Never crash the relay because a notification failed.
            self._log.exception("Failed to send Telegram notification")
