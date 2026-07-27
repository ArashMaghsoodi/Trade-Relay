"""
Telegram control bot — the owner's dashboard. Separate bot (created via
@BotFather) from the Telethon client that reads the VIP channel.

Only ever responds to OWNER_TELEGRAM_ID; every other chat is ignored
entirely (not even an error reply, to avoid confirming the bot's existence
to strangers who find it).
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from trade_relay.config import Settings
from trade_relay.db.base import build_session_factory
from trade_relay.exchange.base import ExchangeClient
from trade_relay.reports.report_service import build_report
from trade_relay.scheduler.delay_scheduler import DelayScheduler, InvalidDelayError, parse_delay
from trade_relay.trading.automation_state import is_automation_enabled, set_automation_enabled

logger = logging.getLogger(__name__)

_PANIC_CONFIRM_TIMEOUT_SECONDS = 30


def build_control_bot(
    settings: Settings,
    exchange: ExchangeClient,
    scheduler: DelayScheduler,
    bot: Bot,
) -> Dispatcher:
    dp = Dispatcher()
    router = Router()
    dp.include_router(router)

    session_factory = build_session_factory(settings.database_url)

    def owner_only(message: Message) -> bool:
        return message.from_user is not None and message.from_user.id == settings.owner_telegram_id

    router.message.filter(owner_only)

    # -- basic automation control -----------------------------------------

    @router.message(Command("enable"))
    async def cmd_enable(message: Message, command: CommandObject) -> None:
        if command.args:
            try:
                delay = parse_delay(command.args)
            except InvalidDelayError as exc:
                await message.answer(str(exc))
                return

            async def _do_enable() -> None:
                with session_factory() as db:
                    set_automation_enabled(db, True)
                await bot.send_message(settings.owner_telegram_id, "✅ Automation is now ENABLED (delayed).")

            scheduler.schedule_once(_do_enable, delay, job_id="enable_disable_toggle")
            await message.answer(f"Automation will be enabled in {command.args}.")
            return

        with session_factory() as db:
            set_automation_enabled(db, True)
        await message.answer("✅ Automation ENABLED immediately.")

    @router.message(Command("disable"))
    async def cmd_disable(message: Message, command: CommandObject) -> None:
        if command.args:
            try:
                delay = parse_delay(command.args)
            except InvalidDelayError as exc:
                await message.answer(str(exc))
                return

            async def _do_disable() -> None:
                with session_factory() as db:
                    set_automation_enabled(db, False)
                await bot.send_message(settings.owner_telegram_id, "🛑 Automation is now DISABLED (delayed).")

            scheduler.schedule_once(_do_disable, delay, job_id="enable_disable_toggle")
            await message.answer(f"Automation will be disabled in {command.args}.")
            return

        with session_factory() as db:
            set_automation_enabled(db, False)
        await message.answer("🛑 Automation DISABLED immediately.")

    @router.message(Command("dryrun"))
    async def cmd_dryrun(message: Message) -> None:
        state = "ON (LIVE_TRADING_ENABLED=true)" if settings.live_trading_enabled else "OFF — all orders are simulated"
        await message.answer(
            f"Dry-run mode is controlled by LIVE_TRADING_ENABLED in .env.\nCurrently: {state}\n\n"
            "The full pipeline (classify → parse → risk-check) always runs regardless; this only "
            "affects whether the exchange client sends real orders."
        )

    # -- status / reports / health / config --------------------------------

    @router.message(Command("status"))
    async def cmd_status(message: Message) -> None:
        with session_factory() as db:
            automation_state = "ENABLED" if is_automation_enabled(db) else "DISABLED"

        try:
            balance = await exchange.get_balance()
            positions = await exchange.get_positions()
        except Exception as exc:  # noqa: BLE001
            await message.answer(f"⚠️ Could not fetch live TooBit data: {exc}")
            return

        lines = [
            f"Automation: {automation_state}",
            f"Live trading: {'YES' if settings.live_trading_enabled else 'NO (dry-run)'}",
            f"Wallet balance: {balance.wallet_balance:.2f}",
            f"Available balance: {balance.available_balance:.2f}",
            "",
            "Open positions:" if positions else "No open positions.",
        ]
        total_pnl = 0.0
        for p in positions:
            total_pnl += p.unrealized_pnl
            lines.append(
                f"  {p.symbol} {p.side} x{p.leverage} qty={p.quantity} "
                f"entry={p.entry_price} mark={p.mark_price} "
                f"ROI={p.roi_pct:.1f}% PnL={p.unrealized_pnl:.2f}"
            )
        if positions:
            lines.append(f"\nTotal unrealized PnL: {total_pnl:.2f}")

        await message.answer("\n".join(lines))

    @router.message(Command("report"))
    async def cmd_report(message: Message, command: CommandObject) -> None:
        hours = 24
        if command.args and command.args.strip().isdigit():
            hours = int(command.args.strip())
        summary = build_report(session_factory, since_hours=hours)
        await message.answer(summary.render())

    @router.message(Command("config"))
    async def cmd_config(message: Message) -> None:
        lines = [
            f"Default wallet %: {settings.default_wallet_percent}",
            f"Wallet % range: {settings.min_wallet_percent}–{settings.max_wallet_percent}",
            f"Default leverage: {settings.default_leverage}x",
            f"Max signal age: {settings.max_signal_age_seconds}s",
            f"Max SL distance: {settings.max_sl_distance_pct}%",
            f"Max TP distance: {settings.max_tp_distance_pct}%",
            f"Min parser confidence: {settings.min_parser_confidence}",
            f"AI parser enabled: {settings.ai_parser_enabled}",
            f"Live trading enabled: {settings.live_trading_enabled}",
        ]
        await message.answer("\n".join(lines))

    @router.message(Command("health"))
    async def cmd_health(message: Message) -> None:
        exchange_healthy = await exchange.health_check()
        with session_factory() as db:
            automation_state = "ENABLED" if is_automation_enabled(db) else "DISABLED"
        lines = [
            "Telethon connection: (see logs / check for recent messages via /report)",
            "Telegram control bot: OK (you're talking to it)",
            f"TooBit API: {'OK' if exchange_healthy else 'UNREACHABLE'}",
            f"Automation: {automation_state}",
            f"Live trading: {'YES' if settings.live_trading_enabled else 'NO (dry-run)'}",
        ]
        await message.answer("\n".join(lines))

    # -- panic -------------------------------------------------------------

    _panic_confirmations: dict[int, dt.datetime] = {}

    @router.message(Command("panic"))
    async def cmd_panic(message: Message) -> None:
        expires_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=_PANIC_CONFIRM_TIMEOUT_SECONDS)
        _panic_confirmations[message.chat.id] = expires_at
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(text="⚠️ Confirm", callback_data="panic_confirm"),
                InlineKeyboardButton(text="Cancel", callback_data="panic_cancel"),
            ]]
        )
        await message.answer(
            "⚠️ WARNING — this will:\n"
            "• Disable automation\n"
            "• Close every open position\n"
            "• Cancel pending orders\n\n"
            f"Confirm within {_PANIC_CONFIRM_TIMEOUT_SECONDS} seconds.",
            reply_markup=keyboard,
        )

    @router.callback_query(F.data == "panic_confirm")
    async def on_panic_confirm(callback: CallbackQuery) -> None:
        if callback.from_user.id != settings.owner_telegram_id:
            await callback.answer()
            return

        expires_at = _panic_confirmations.get(callback.message.chat.id)
        if expires_at is None or dt.datetime.now(dt.timezone.utc) > expires_at:
            await callback.message.edit_text("Panic confirmation expired. Run /panic again if still needed.")
            await callback.answer()
            return

        _panic_confirmations.pop(callback.message.chat.id, None)
        await callback.message.edit_text("🚨 Executing panic sequence...")

        with session_factory() as db:
            set_automation_enabled(db, False)

        try:
            positions = await exchange.get_positions()
        except Exception as exc:  # noqa: BLE001
            await callback.message.answer(f"⚠️ Could not fetch positions to close: {exc}")
            positions = []

        results = []
        for p in positions:
            close_result = await exchange.close_position(p.symbol, percent=100.0)
            cancel_result = await exchange.cancel_all_orders(p.symbol)
            results.append(f"{p.symbol}: close={'ok' if close_result.success else close_result.error}, "
                            f"cancel={'ok' if cancel_result.success else cancel_result.error}")

        summary = "\n".join(results) if results else "No open positions to close."
        await callback.message.answer(f"🚨 Panic sequence complete.\nAutomation disabled.\n\n{summary}")
        await callback.answer()

    @router.callback_query(F.data == "panic_cancel")
    async def on_panic_cancel(callback: CallbackQuery) -> None:
        _panic_confirmations.pop(callback.message.chat.id, None)
        await callback.message.edit_text("Panic cancelled — no action taken.")
        await callback.answer()

    return dp
