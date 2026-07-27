"""
Telethon client that reads the private VIP channel using the user's own
Telegram account (required for private channels the account isn't an admin
bot in). Subscribes to new messages, edits, and relies on Telegram's native
reply metadata for replies (no separate subscription needed — replies just
arrive as NewMessage events with reply_to set).
"""
from __future__ import annotations

import logging
from datetime import timezone

from telethon import TelegramClient, events

from trade_relay.config import Settings
from trade_relay.domain.models import IncomingMessage
from trade_relay.trading.session_manager import TradeSessionManager

logger = logging.getLogger(__name__)


class TelethonListener:
    def __init__(self, settings: Settings, session_manager: TradeSessionManager):
        self._settings = settings
        self._session_manager = session_manager
        self._client = TelegramClient(
            settings.telethon_session_name,
            settings.telegram_api_id,
            settings.telegram_api_hash,
        )

    def _register_handlers(self) -> None:
        channel = self._settings.vip_channel_id

        @self._client.on(events.NewMessage(chats=channel))
        async def _on_new_message(event):  # noqa: ANN001
            await self._handle_event(event, is_edit=False)

        @self._client.on(events.MessageEdited(chats=channel))
        async def _on_edit(event):  # noqa: ANN001
            await self._handle_event(event, is_edit=True)

    async def _handle_event(self, event, is_edit: bool) -> None:  # noqa: ANN001
        try:
            text = event.message.message or ""
            if not text.strip():
                return  # ignore media-only messages with no caption for now

            msg = IncomingMessage(
                message_id=event.message.id,
                chat_id=str(event.chat_id),
                text=text,
                date=event.message.date.astimezone(timezone.utc),
                reply_to_message_id=event.message.reply_to_msg_id,
                is_edit=is_edit,
            )
            await self._session_manager.handle_message(msg)
        except Exception:  # noqa: BLE001
            logger.exception("Error handling Telegram event %s", getattr(event.message, "id", "?"))

    async def start(self) -> None:
        self._register_handlers()
        await self._client.start()
        logger.info("Telethon listener connected and watching channel %s", self._settings.vip_channel_id)

    async def run_until_disconnected(self) -> None:
        await self._client.run_until_disconnected()

    async def stop(self) -> None:
        await self._client.disconnect()
