"""
Wires every component together (manual dependency injection — no DI
framework, just explicit construction so it's obvious what depends on
what) and runs the app: Telethon listener + control bot polling,
concurrently, until interrupted.
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot

from trade_relay.config import Settings, load_settings
from trade_relay.db.base import build_session_factory
from trade_relay.exchange.toobit_client import TooBitClient
from trade_relay.nlp.ai_parser import build_ai_parser
from trade_relay.notifications.notifier import TelegramNotifier
from trade_relay.reports.report_service import build_report  # noqa: F401 - re-exported for convenience
from trade_relay.scheduler.delay_scheduler import DelayScheduler
from trade_relay.telegram.control_bot import build_control_bot
from trade_relay.telegram.listener import TelethonListener
from trade_relay.trading.risk_engine import RiskEngine
from trade_relay.trading.session_manager import TradeSessionManager

logger = logging.getLogger(__name__)


def _configure_logging(settings: Settings) -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


class Application:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or load_settings()
        _configure_logging(self.settings)

        self.session_factory = build_session_factory(self.settings.database_url)
        self.exchange = TooBitClient(self.settings)
        self.risk_engine = RiskEngine(self.settings, self.exchange)
        self.ai_parser = build_ai_parser(self.settings)

        self.bot = Bot(token=self.settings.control_bot_token) if self.settings.control_bot_token else None
        notifier = (
            TelegramNotifier(self.bot, self.settings.owner_telegram_id)
            if self.bot is not None
            else _NullNotifierFallback()
        )

        self.session_manager = TradeSessionManager(
            settings=self.settings,
            session_factory=self.session_factory,
            exchange=self.exchange,
            risk_engine=self.risk_engine,
            notifier=notifier,
            ai_parser=self.ai_parser,
        )

        self.listener = TelethonListener(self.settings, self.session_manager)
        self.scheduler = DelayScheduler()
        self.dispatcher = (
            build_control_bot(self.settings, self.exchange, self.scheduler, self.bot)
            if self.bot is not None
            else None
        )

    async def run(self) -> None:
        self.scheduler.start()
        await self.listener.start()

        tasks = [asyncio.create_task(self.listener.run_until_disconnected())]
        if self.dispatcher is not None and self.bot is not None:
            tasks.append(asyncio.create_task(self.dispatcher.start_polling(self.bot)))
        else:
            logger.warning("CONTROL_BOT_TOKEN not set — running with no control bot / notifications")

        try:
            await asyncio.gather(*tasks)
        finally:
            self.scheduler.shutdown()
            await self.listener.stop()
            if hasattr(self.exchange, "aclose"):
                await self.exchange.aclose()


class _NullNotifierFallback:
    async def notify(self, text: str) -> None:
        logger.info("[NOTIFY - no bot configured] %s", text)


def main() -> None:
    app = Application()
    asyncio.run(app.run())
