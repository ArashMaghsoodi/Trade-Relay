# Trade-Relay

Telegram-to-Toobit trade relay (Python).

Current status: Milestone 1 / Step 1 scaffold completed.

## Planned behavior
- Read VIP signals from Telegram user account (Telethon)
- Enter futures positions on Toobit when entry trigger message arrives
- Report and control via Telegram bot (logs + commands)

## Safety defaults
- Dry-run mode by default (`TRADING_MODE=dry_run`)
- One position per symbol
- Skip entry if setup was not seen/cached

## Setup
1) Create and fill `.env` from `.env.example`
2) Use Python 3.11+
3) Install dependencies:
   - `python -m pip install -r requirements.txt`

## Run the Step 2.1 listener (Telegram ingest + parsing + bot notification)
- Config validation only:
  - `PYTHONPATH=src python -m trade_relay.main --check-config`
- Start live listener:
  - `PYTHONPATH=src python -m trade_relay.main`

Behavior in current MVP:
- Watches `VIP_CHANNEL_IDS` via Telethon user session.
- Parses signal/setup/entry/target/stop messages.
- Applies in-memory state engine (dedup, setup cache, one-position-per-symbol).
- Persists state to SQLite for restart recovery (`STATE_DB_PATH`).
- Supports relay pause/resume for new entries.
- Tracks virtual positions (dry-run lifecycle): TP1 partial + BE, TP2 close, SL close.
- Tracks closed position history with close reason and timestamps.
- In `paper`/`live` modes, creates order intents on accepted entries.
- Paper sizing uses live demo wallet balance fetched from Toobit account endpoint.
- `live` mode is intentionally blocked to intent-only (no real orders yet).
- Logs parsed events + decisions to terminal.
- Sends plain-text event summaries + decisions to your control bot chat/user ID.

## Bot test commands (temporary)
- `/ping`
- `/last [count]`
- `/mode`
- `/set_leverage [x]`
- `/status`
- `/recent [count]`
- `/replaylast [count]`
- `/positions`
- `/orders [count]`
- `/summary`
- `/history [count]`
- `/dbstats`
- `/toobit_ping`
- `/test_order` (select newest setup from the last 15 messages and test execution; existing tracked positions are retained)
- `/pause`
- `/resume`

## Notes
- `.env` is git-ignored.
- Do not run live mode before dry-run validation.
