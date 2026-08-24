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

Behavior in Step 2.1:
- Watches `VIP_CHANNEL_IDS` via Telethon user session.
- Parses signal/setup/entry/target/stop messages.
- Logs parsed events to terminal.
- Sends plain-text event summaries to your control bot chat/user ID.
- Does not place exchange orders yet.

## Notes
- `.env` is git-ignored.
- Do not run live mode before dry-run validation.
