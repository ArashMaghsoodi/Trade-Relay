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
3) Install deps (next step will add `requirements.txt`)

## Notes
- `.env` is git-ignored.
- Do not run live mode before dry-run validation.
