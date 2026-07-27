# trade-relay

Cloud-hosted assistant that watches a private VIP Telegram trading channel and
copies its signals into a TooBit futures account — **only while you're
unavailable**. You trade manually whenever you can; this exists to catch what
you'd otherwise miss.

Core philosophy: **never guess**. Anything ambiguous is logged and skipped,
never traded. Missing a trade is always preferable to opening a wrong one.

## Current status: observation mode only

This is a fresh checkout. **No real orders will ever be placed** until you
explicitly flip `LIVE_TRADING_ENABLED=true` in `.env` — this is a hard kill
switch checked inside the exchange client itself (not just in the business
logic), so even a bug elsewhere in the app can't cause a live order.

While `LIVE_TRADING_ENABLED=false` (the default), the full pipeline still
runs end-to-end:

- Telethon reads the VIP channel
- messages are classified, parsed, aggregated into Trade Sessions
- the Risk Engine evaluates each session and decides WOULD_EXECUTE or
  SKIPPED (with a reason)
- everything is logged to the database and summarized in `/report`

This is the intended way to spend your "few days validating accuracy" period:
run it for real, look at `/report` and the logs, and compare what the bot
*would* have done against what you actually did manually. Only flip the
switch once you trust the parser and risk checks.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# fill in .env, see comments in the file for where each value comes from
python main.py
```

You'll need:

- **Telegram API ID/hash** for your own account (my.telegram.org) — used by
  Telethon to read the private VIP channel (this must be a user account,
  not a bot, since bots can't join/read private channels they aren't admins
  of in the way we need).
- **A bot token from @BotFather** — this is the separate control bot you
  already created, used as your dashboard (commands, notifications).
- **Your own numeric Telegram user ID** — so the control bot only ever
  responds to you.
- **TooBit API key/secret** — from TooBit account settings. Read-only scope
  is enough during observation mode; you'll need trade scope once you go
  live.
- Optionally an AI API key (used only for parsing/classification assist,
  never for trading decisions — see `nlp/ai_parser.py`).

## Architecture

```
src/trade_relay/
  config.py            Pydantic settings loaded from .env
  domain/               Enums + Pydantic domain models (ParsedSignal, etc.)
  db/                   SQLAlchemy models + session factory (SQLite by default)
  nlp/
    normalization.py    Persian digit/keyword normalization
    classifier.py       Message classification (signal / management / chat / unknown)
    rule_parser.py       Deterministic regex/keyword based field extraction
    ai_parser.py         Pluggable AI-assisted parser (fallback only)
  trading/
    session_manager.py  Trade Session lifecycle, reply/edit aggregation
    risk_engine.py       All pre-trade safety checks
  exchange/
    base.py              Exchange-agnostic interface (for DI / swapping exchanges)
    toobit_client.py      TooBit REST implementation, HMAC signing, dry-run gate
  telegram/
    listener.py           Telethon client (reads the VIP channel)
    control_bot.py         aiogram control bot (/status, /report, /panic, etc.)
  notifications/          Notifier interface + Telegram implementation
  scheduler/               APScheduler-based delayed enable/disable
  reports/                 Report generation from DB state
  app.py                   Wires everything together (manual DI), run loop
main.py                    Entrypoint
```

Every component is defined behind a small interface (`exchange/base.py`,
`notifications/`, the parser split into rule-based + AI) so any of them can
be swapped later without touching the rest of the system.

## A note on the TooBit client

The TooBit REST implementation in `exchange/toobit_client.py` is built from
TooBit's public API docs (HMAC-SHA256 signing over `X-BB-APIKEY`, futures
symbol format `BASE-SWAP-USDT`, `BUY_OPEN`/`SELL_OPEN`/`BUY_CLOSE`/`SELL_CLOSE`
sides). **Verify every endpoint path and payload shape against the current
docs at https://api-docs.toobit.com/ before going live** — exchange APIs
change, and this hasn't been tested against a live account yet since trading
is intentionally disabled right now.

## Safety checks before you flip the switch

See `trading/risk_engine.py` for the full list, but at minimum, confirm:

1. `/report` shows the parser correctly reading a good sample of real
   signals from your channel (symbol/side/SL/TP/leverage all correct).
2. You've reviewed the SL/TP plausibility bounds in `.env`
   (`MAX_SL_DISTANCE_PCT`, `MAX_TP_DISTANCE_PCT`) against how this provider
   actually sets stops.
3. You've tested `/dryrun`, `/panic`, and the delayed `/enable`/`/disable`
   commands.
4. Your TooBit API key has trade permissions (it won't need withdrawal
   permissions — never enable those).
