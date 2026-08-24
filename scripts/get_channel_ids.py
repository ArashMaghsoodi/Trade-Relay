"""List all Telegram chats/channels the logged-in user is a member of,
with their numeric IDs, so you can copy the VIP channel ID into `.env`.

Usage:
    python scripts/get_channel_ids.py

Notes:
- Uses TELEGRAM_API_ID / TELEGRAM_API_HASH / TELEGRAM_PHONE / TELEGRAM_SESSION_NAME
  from your `.env`.
- On first run Telegram sends you a login code (in-app or SMS); enter it in the
  terminal. If you have 2FA, it will also ask for your password.
- Creates/reuses the same session file as the relay, so you won't need to log
  in again later.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

from trade_relay.config import Settings  # noqa: E402
from telethon import TelegramClient  # noqa: E402


async def main() -> None:
    settings = Settings.from_env(PROJECT_ROOT / ".env")

    async with TelegramClient(
        settings.telegram_session_name,
        int(settings.telegram_api_id),
        settings.telegram_api_hash,
    ) as client:
        print("\nYour dialogs (chats/groups/channels):\n")
        print(f"{'ID':<20} {'TYPE':<10} TITLE")
        print("-" * 70)

        async for dialog in client.iter_dialogs():
            entity = dialog.entity
            kind = getattr(entity, "kind", None)
            if kind is None:
                if getattr(entity, "broadcast", False):
                    kind = "channel"
                elif getattr(entity, "megagroup", False):
                    kind = "supergroup"
                else:
                    kind = "chat"

            marker = " <-- VIP?" if kind == "channel" else ""
            print(f"{dialog.id:<20} {kind:<10} {dialog.name}{marker}")

        print("\nCopy the ID of your VIP channel into `.env`:")
        print("VIP_CHANNEL_IDS=-1001234567890")
        print("(multiple channels: comma-separated)\n")


if __name__ == "__main__":
    load_dotenv(dotenv_path=PROJECT_ROOT / ".env", override=False)
    asyncio.run(main())
