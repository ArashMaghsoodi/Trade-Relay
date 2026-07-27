"""
Automation on/off state (the /enable, /disable commands), persisted in the
DB so it survives restarts. This is deliberately separate from
LIVE_TRADING_ENABLED:

- `automation_enabled=False` (the default until you run /enable): the app
  parses and risk-checks every signal but takes NO autonomous action at all
  — not even a dry-run call to the exchange client. This is the state you
  want during the multi-day accuracy-observation period.
- `automation_enabled=True` + `LIVE_TRADING_ENABLED=false`: full pipeline
  runs including calls into the exchange client, which itself no-ops/logs
  instead of placing real orders (shadow mode — useful once you trust the
  parser and want to see "would have executed" order-shaped output).
- `automation_enabled=True` + `LIVE_TRADING_ENABLED=true`: real trading.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from trade_relay.db.models import AppConfigOverride

_KEY = "automation_enabled"


def is_automation_enabled(db: Session) -> bool:
    row = db.get(AppConfigOverride, _KEY)
    return row is not None and row.value == "true"


def set_automation_enabled(db: Session, enabled: bool) -> None:
    row = db.get(AppConfigOverride, _KEY)
    if row is None:
        row = AppConfigOverride(key=_KEY, value="true" if enabled else "false")
        db.add(row)
    else:
        row.value = "true" if enabled else "false"
    db.commit()
