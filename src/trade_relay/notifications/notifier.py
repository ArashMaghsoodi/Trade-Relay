"""
Notifier interface, so the notification channel can be swapped (Telegram
today, email/Slack/etc. later) without touching business logic.

Per spec, notifications are sent for: trade opened/closed, SL/TP changes,
API failures, risk failures worth surfacing, and position-management
events. General chat and unknown messages are NEVER notified — they go to
logs/reports only.
"""
from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger(__name__)


class Notifier(Protocol):
    async def notify(self, text: str) -> None: ...


class LoggingNotifier:
    """Fallback notifier used before the control bot is wired up (e.g. in
    tests or early startup) — just logs instead of sending Telegram
    messages."""

    async def notify(self, text: str) -> None:
        logger.info("[NOTIFY] %s", text)


class TelegramNotifier:
    """Sends notifications to the owner via the control bot. Constructed
    with a reference to the aiogram Bot instance rather than owning its own
    bot connection, so there's only ever one bot session."""

    def __init__(self, bot, owner_telegram_id: int):
        self._bot = bot
        self._owner_telegram_id = owner_telegram_id

    async def notify(self, text: str) -> None:
        try:
            await self._bot.send_message(self._owner_telegram_id, text)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to send Telegram notification")
