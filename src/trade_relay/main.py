from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from telethon import TelegramClient, events
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from trade_relay.config import Settings
    from trade_relay.models import EventType, SignalEvent
    from trade_relay.notifier import Notifier
    from trade_relay.parser import parse_signal_message
    from trade_relay.runtime_state import RuntimeState, process_signal_event
    from trade_relay.state_repo import StateRepository
else:
    from .config import Settings
    from .models import EventType, SignalEvent
    from .notifier import Notifier
    from .parser import parse_signal_message
    from .runtime_state import RuntimeState, process_signal_event
    from .state_repo import StateRepository


@dataclass(slots=True)
class RelayRuntime:
    settings: Settings
    telethon_client: TelegramClient
    notifier: Notifier
    state: RuntimeState
    repo: StateRepository


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def summarize_event(event: SignalEvent) -> str:
    if event.event_type == EventType.SETUP and event.setup is not None:
        s = event.setup
        return (
            f"SETUP {s.symbol} {s.side.value} | entry {s.entry_low:.8f}-{s.entry_high:.8f} | "
            f"tp1 {s.tp1:.8f} tp2 {s.tp2:.8f} sl {s.stop_loss:.8f}"
        )

    if event.event_type == EventType.ENTRY_TRIGGER:
        return f"ENTRY_TRIGGER {event.symbol} {event.side.value}"

    if event.event_type == EventType.TARGET_HIT:
        return f"TARGET_HIT {event.symbol} {event.side.value} target={event.target_number}"

    if event.event_type == EventType.STOPPED_OUT:
        return f"STOPPED_OUT {event.symbol} {event.side.value}"

    return f"UNKNOWN_EVENT {event.symbol} {event.side.value}"


def classify_message(text: str) -> str:
    parsed = parse_signal_message(text)
    if parsed is not None:
        return summarize_event(parsed)

    upper = text.upper()
    if any(k in upper for k in ["UPDATE", "NEWS", "ANNOUNCE", "NOTICE"]):
        return "UPDATE/NOTICE"
    if any(k in upper for k in ["WELCOME", "HELLO", "GOOD MORNING", "GOOD EVENING"]):
        return "GREETING"
    if re.search(r"\b(RESULT|RECAP|SUMMARY)\b", upper):
        return "PERFORMANCE_UPDATE"

    return "NON_SIGNAL"


def trim_one_line(text: str, limit: int = 120) -> str:
    single = " ".join((text or "").split())
    if len(single) <= limit:
        return single
    return single[: limit - 3] + "..."


async def safe_reply(update: Update, text: str) -> None:
    if update.effective_message is None:
        return

    max_len = 3500
    chunks = [text[i : i + max_len] for i in range(0, len(text), max_len)] or [text]
    for chunk in chunks:
        await update.effective_message.reply_text(chunk)


def is_allowed(update: Update, settings: Settings) -> bool:
    user = update.effective_user
    return bool(user and user.id == settings.telegram_allowed_user_id)


async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    runtime: RelayRuntime = context.bot_data["runtime"]
    if not is_allowed(update, runtime.settings):
        return
    await safe_reply(update, "pong")


async def cmd_last(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    runtime: RelayRuntime = context.bot_data["runtime"]
    if not is_allowed(update, runtime.settings):
        return

    n = 15
    if context.args:
        try:
            n = max(1, min(50, int(context.args[0])))
        except ValueError:
            await safe_reply(update, "Usage: /last [count]  (count must be an integer, max 50)")
            return

    if not runtime.settings.vip_channel_ids:
        await safe_reply(update, "VIP_CHANNEL_IDS is empty")
        return

    channel_id = runtime.settings.vip_channel_ids[0]
    lines: list[str] = [f"Last {n} messages from {channel_id}:"]

    rows: list[str] = []
    async for msg in runtime.telethon_client.iter_messages(channel_id, limit=n):
        raw = msg.raw_text or ""
        if not raw.strip():
            continue
        classification = classify_message(raw)
        rows.append(f"[{msg.id}] {classification}\n  {trim_one_line(raw)}")

    if not rows:
        lines.append("(No text messages found in this range)")
    else:
        rows.reverse()
        lines.extend(rows)

    await safe_reply(update, "\n".join(lines))


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    runtime: RelayRuntime = context.bot_data["runtime"]
    if not is_allowed(update, runtime.settings):
        return

    state = runtime.state
    await safe_reply(
        update,
        "Relay status:\n"
        f"mode={runtime.settings.trading_mode}\n"
        f"paused={state.paused}\n"
        f"one_position_per_symbol={state.one_position_per_symbol}\n"
        f"setups_cached={len(state.setups_by_symbol)}\n"
        f"open_symbols={len(state.open_symbols)} ({', '.join(sorted(state.open_symbols)) if state.open_symbols else '-'})\n"
        f"tracked_positions={len(state.positions_by_symbol)}\n"
        f"closed_history={len(state.closed_positions)}\n"
        f"recent_decisions={len(state.recent_decisions)}\n"
        f"state_db_path={runtime.settings.state_db_path}",
    )


async def cmd_recent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    runtime: RelayRuntime = context.bot_data["runtime"]
    if not is_allowed(update, runtime.settings):
        return

    n = 15
    if context.args:
        try:
            n = max(1, min(50, int(context.args[0])))
        except ValueError:
            await safe_reply(update, "Usage: /recent [count]  (count must be an integer, max 50)")
            return

    decisions = list(runtime.state.recent_decisions)[-n:]
    if not decisions:
        await safe_reply(update, "No decisions yet.")
        return

    lines = [f"Last {len(decisions)} decisions:"]
    for item in decisions:
        lines.append(f"- {item}")

    await safe_reply(update, "\n".join(lines))


async def cmd_replaylast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    runtime: RelayRuntime = context.bot_data["runtime"]
    if not is_allowed(update, runtime.settings):
        return

    n = 15
    if context.args:
        try:
            n = max(1, min(50, int(context.args[0])))
        except ValueError:
            await safe_reply(update, "Usage: /replaylast [count]  (count must be an integer, max 50)")
            return

    if not runtime.settings.vip_channel_ids:
        await safe_reply(update, "VIP_CHANNEL_IDS is empty")
        return

    channel_id = runtime.settings.vip_channel_ids[0]
    messages = []
    async for msg in runtime.telethon_client.iter_messages(channel_id, limit=n):
        if (msg.raw_text or "").strip():
            messages.append(msg)

    if not messages:
        await safe_reply(update, "No text messages found in this range.")
        return

    messages.reverse()
    rows: list[str] = []
    processed = 0
    for msg in messages:
        text = msg.raw_text or ""
        parsed = parse_signal_message(text)
        if parsed is None:
            continue
        key = f"replay:{channel_id}:{msg.id}"
        decision = process_signal_event(runtime.state, parsed, key)
        rows.append(f"[{msg.id}] {summarize_event(parsed)} => {decision}")
        processed += 1

    if processed == 0:
        await safe_reply(update, "No parseable signal events found in selected range.")
        return

    header = f"Replayed {processed} signal event(s) from last {n} messages:"
    await safe_reply(update, "\n".join([header] + rows))


async def cmd_positions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    runtime: RelayRuntime = context.bot_data["runtime"]
    if not is_allowed(update, runtime.settings):
        return

    state = runtime.state
    if not state.positions_by_symbol:
        await safe_reply(update, "No tracked positions yet.")
        return

    lines = ["Tracked positions:"]
    for symbol, pos in sorted(state.positions_by_symbol.items()):
        lines.append(
            f"- {symbol} {pos.side} | status={pos.entry_status} | open={pos.size_percent_open:.1f}% "
            f"| tp1_hit={pos.tp1_hit} | sl_be={pos.sl_moved_to_breakeven}"
        )

    await safe_reply(update, "\n".join(lines))


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    runtime: RelayRuntime = context.bot_data["runtime"]
    if not is_allowed(update, runtime.settings):
        return

    n = 15
    if context.args:
        try:
            n = max(1, min(50, int(context.args[0])))
        except ValueError:
            await safe_reply(update, "Usage: /history [count]  (count must be an integer, max 50)")
            return

    history = list(runtime.state.closed_positions)[-n:]
    if not history:
        await safe_reply(update, "No closed position history yet.")
        return

    lines = [f"Closed position history (last {len(history)}):"]
    for rec in reversed(history):
        lines.append(
            f"- {rec.symbol} {rec.side} | status={rec.final_status} | reason={rec.close_reason} | "
            f"tp1_hit={rec.tp1_hit} | sl_be={rec.sl_moved_to_breakeven} | closed_at={rec.closed_at}"
        )
    await safe_reply(update, "\n".join(lines))


async def cmd_dbstats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    runtime: RelayRuntime = context.bot_data["runtime"]
    if not is_allowed(update, runtime.settings):
        return

    counts = runtime.repo.table_counts()
    lines = ["DB table counts:"] + [f"- {k}: {v}" for k, v in counts.items()]
    await safe_reply(update, "\n".join(lines))


async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    runtime: RelayRuntime = context.bot_data["runtime"]
    if not is_allowed(update, runtime.settings):
        return

    decision = runtime.state.pause()
    runtime.repo.persist_state_snapshot(runtime.state)
    await safe_reply(update, f"OK: {decision}")


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    runtime: RelayRuntime = context.bot_data["runtime"]
    if not is_allowed(update, runtime.settings):
        return

    decision = runtime.state.resume()
    runtime.repo.persist_state_snapshot(runtime.state)
    await safe_reply(update, f"OK: {decision}")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    runtime: RelayRuntime = context.bot_data["runtime"]
    if not is_allowed(update, runtime.settings):
        return

    await safe_reply(
        update,
        "Commands:\n"
        "/ping - health check\n"
        "/last - classify last 15 messages from first VIP channel\n"
        "/last 30 - classify last 30 messages (max 50)\n"
        "/status - show runtime state counters\n"
        "/recent - show last 15 state decisions\n"
        "/replaylast - reprocess last 15 channel messages through state engine\n"
        "/replaylast 30 - reprocess last 30 messages (max 50)\n"
        "/positions - show tracked virtual positions\n"
        "/history - show closed position history\n"
        "/dbstats - show SQLite table row counts\n"
        "/pause - pause new entry acceptance\n"
        "/resume - resume new entry acceptance\n"
        "/help - show this help",
    )


async def run_listener(settings: Settings) -> None:
    if not settings.vip_channel_ids:
        raise ValueError("VIP_CHANNEL_IDS is empty. Add at least one channel ID to .env")

    log = logging.getLogger("trade_relay.main")
    notifier = Notifier(settings.telegram_bot_token, settings.telegram_allowed_user_id)
    repo = StateRepository(settings.state_db_path)
    repo.init_db()
    loaded_state = repo.load_state(one_position_per_symbol=settings.one_position_per_symbol)

    telethon_client = TelegramClient(
        settings.telegram_session_name,
        int(settings.telegram_api_id),
        settings.telegram_api_hash,
    )

    runtime = RelayRuntime(
        settings=settings,
        telethon_client=telethon_client,
        notifier=notifier,
        state=loaded_state,
        repo=repo,
    )

    @telethon_client.on(events.NewMessage(chats=settings.vip_channel_ids))
    async def on_new_message(event: events.NewMessage.Event) -> None:
        text = event.raw_text or ""
        if not text.strip():
            return

        parsed = parse_signal_message(text)
        if parsed is None:
            return

        summary = summarize_event(parsed)
        message_key = f"live:{event.chat_id}:{event.id}"
        decision = process_signal_event(runtime.state, parsed, message_key)
        runtime.repo.persist_state_snapshot(runtime.state)
        log.info("%s | %s | msg_id=%s", summary, decision, event.id)
        await runtime.notifier.send(f"{summary}\n{decision}")

    await telethon_client.start(phone=settings.telegram_phone)

    bot_app = Application.builder().token(settings.telegram_bot_token).build()
    bot_app.bot_data["runtime"] = runtime
    bot_app.add_handler(CommandHandler("ping", cmd_ping))
    bot_app.add_handler(CommandHandler("last", cmd_last))
    bot_app.add_handler(CommandHandler("status", cmd_status))
    bot_app.add_handler(CommandHandler("recent", cmd_recent))
    bot_app.add_handler(CommandHandler("replaylast", cmd_replaylast))
    bot_app.add_handler(CommandHandler("positions", cmd_positions))
    bot_app.add_handler(CommandHandler("history", cmd_history))
    bot_app.add_handler(CommandHandler("dbstats", cmd_dbstats))
    bot_app.add_handler(CommandHandler("pause", cmd_pause))
    bot_app.add_handler(CommandHandler("resume", cmd_resume))
    bot_app.add_handler(CommandHandler("help", cmd_help))

    await bot_app.initialize()
    await bot_app.start()
    if bot_app.updater is None:
        raise RuntimeError("Telegram bot updater is unavailable")
    await bot_app.updater.start_polling(drop_pending_updates=True)

    me = await telethon_client.get_me()
    username = f"@{me.username}" if getattr(me, "username", None) else "(no username)"

    startup_message = (
        "Trade Relay listener started\n"
        f"Account: {username}\n"
        f"Watching channels: {', '.join(map(str, settings.vip_channel_ids))}\n"
        "Bot commands: /ping /last /status /recent /replaylast /positions /history /dbstats /pause /resume /help"
    )

    log.info(startup_message.replace("\n", " | "))
    await runtime.notifier.send(startup_message)

    try:
        await telethon_client.run_until_disconnected()
    finally:
        await bot_app.updater.stop()
        await bot_app.stop()
        await bot_app.shutdown()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Trade Relay Telegram listener")
    parser.add_argument(
        "--env-file",
        default=".env",
        help="Path to .env file (default: .env)",
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Validate config and print a safe summary without connecting to Telegram",
    )
    return parser.parse_args()


def print_safe_config_summary(settings: Settings) -> None:
    print("Config OK")
    print(f"Session name: {settings.telegram_session_name}")
    print(f"VIP channel count: {len(settings.vip_channel_ids)}")
    print(f"Allowed bot user ID: {settings.telegram_allowed_user_id}")
    print(f"Trading mode: {settings.trading_mode}")
    print(f"Default leverage: {settings.default_leverage}")


async def async_main() -> None:
    args = parse_args()
    settings = Settings.from_env(Path(args.env_file))
    setup_logging(settings.log_level)

    if args.check_config:
        print_safe_config_summary(settings)
        return

    await run_listener(settings)


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
