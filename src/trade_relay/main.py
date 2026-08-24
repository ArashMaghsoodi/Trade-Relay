from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from telethon import TelegramClient, events

from .config import Settings
from .models import EventType, SignalEvent
from .notifier import Notifier
from .parser import parse_signal_message


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


async def run_listener(settings: Settings) -> None:
    if not settings.vip_channel_ids:
        raise ValueError("VIP_CHANNEL_IDS is empty. Add at least one channel ID to .env")

    log = logging.getLogger("trade_relay.main")
    notifier = Notifier(settings.telegram_bot_token, settings.telegram_allowed_user_id)

    client = TelegramClient(
        settings.telegram_session_name,
        int(settings.telegram_api_id),
        settings.telegram_api_hash,
    )

    @client.on(events.NewMessage(chats=settings.vip_channel_ids))
    async def on_new_message(event: events.NewMessage.Event) -> None:
        text = event.raw_text or ""
        if not text.strip():
            return

        parsed = parse_signal_message(text)
        if parsed is None:
            return

        summary = summarize_event(parsed)
        log.info("%s | msg_id=%s", summary, event.id)
        await notifier.send(summary)

    await client.start(phone=settings.telegram_phone)
    me = await client.get_me()
    username = f"@{me.username}" if getattr(me, "username", None) else "(no username)"

    startup_message = (
        "Trade Relay listener started\n"
        f"Account: {username}\n"
        f"Watching channels: {', '.join(map(str, settings.vip_channel_ids))}"
    )

    log.info(startup_message.replace("\n", " | "))
    await notifier.send(startup_message)

    await client.run_until_disconnected()


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
