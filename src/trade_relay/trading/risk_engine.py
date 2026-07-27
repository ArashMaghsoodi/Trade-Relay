"""
Risk & Safety Engine.

This is the single place that decides whether a Trade Session is allowed to
execute. The AI parser and rule parser only ever produce structured data —
this module is what actually enforces "never guess". Every check here
appends a human-readable failure reason so /report and notifications can
explain exactly why a signal was skipped.
"""
from __future__ import annotations

import datetime as dt
import logging

from trade_relay.config import Settings
from trade_relay.domain.models import ParsedSignal, RiskCheckResult
from trade_relay.exchange.base import ExchangeClient

logger = logging.getLogger(__name__)

# Extend as needed — deliberately explicit rather than "any uppercase token"
# so an unrecognized ticker fails safe instead of silently trading garbage.
KNOWN_SYMBOLS = {
    "BTC", "BTCUSDT", "ETH", "ETHUSDT", "SOL", "SOLUSDT", "BNB", "BNBUSDT",
    "XRP", "XRPUSDT", "DOGE", "DOGEUSDT", "ENA", "ENAUSDT", "SUI", "SUIUSDT",
    "ADA", "ADAUSDT", "LINK", "LINKUSDT", "AVAX", "AVAXUSDT",
}


class RiskEngine:
    def __init__(self, settings: Settings, exchange: ExchangeClient):
        self._settings = settings
        self._exchange = exchange

    async def evaluate(
        self,
        signal: ParsedSignal,
        session_created_at: dt.datetime,
    ) -> RiskCheckResult:
        result = RiskCheckResult(passed=True)

        # 1. Required fields present
        if not signal.symbol:
            result.add_failure("symbol missing")
        elif signal.symbol.upper() not in KNOWN_SYMBOLS:
            result.add_failure(f"symbol '{signal.symbol}' not in known symbol list")

        if signal.side is None:
            result.add_failure("side missing")

        if signal.stop_loss is None:
            result.add_failure("stop loss missing")

        if not signal.take_profits:
            result.add_failure("take profit missing")

        # 2. Parser confidence
        if signal.confidence < self._settings.min_parser_confidence:
            result.add_failure(
                f"parser confidence {signal.confidence:.2f} below minimum "
                f"{self._settings.min_parser_confidence:.2f}"
            )

        # 3. Signal staleness
        # SQLite doesn't preserve tzinfo on round-trip, so a value read back
        # from the DB may come back naive even though we always write UTC.
        if session_created_at.tzinfo is None:
            session_created_at = session_created_at.replace(tzinfo=dt.timezone.utc)
        age_seconds = (dt.datetime.now(dt.timezone.utc) - session_created_at).total_seconds()
        if age_seconds > self._settings.max_signal_age_seconds:
            result.add_failure(
                f"signal is stale ({age_seconds:.0f}s old, max is "
                f"{self._settings.max_signal_age_seconds}s)"
            )

        # 4. Exchange health — needed before any of the checks below can be trusted
        healthy = await self._exchange.health_check()
        if not healthy:
            result.add_failure("TooBit API health check failed")
            # Can't safely evaluate price-based or duplicate checks without a
            # healthy connection — stop here rather than risk a false pass.
            return result

        # 5. Duplicate position protection
        if signal.symbol and signal.side:
            if await self._exchange.has_open_position(signal.symbol, signal.side.value):
                result.add_failure(
                    f"duplicate: already have an open {signal.side.value} position on {signal.symbol}"
                )

        # 6. SL/TP plausibility vs current mark price — guards against a
        # parser misread (e.g. a misplaced decimal) sailing through just
        # because "a number was present".
        if signal.symbol and signal.stop_loss and signal.first_take_profit:
            mark_price = await self._exchange.get_mark_price(signal.symbol)
            if mark_price is None:
                result.add_failure("could not fetch mark price to validate SL/TP distance")
            else:
                sl_distance_pct = abs(mark_price - signal.stop_loss) / mark_price * 100
                tp_distance_pct = abs(signal.first_take_profit - mark_price) / mark_price * 100
                if sl_distance_pct > self._settings.max_sl_distance_pct:
                    result.add_failure(
                        f"SL is {sl_distance_pct:.1f}% from mark price, exceeds max "
                        f"{self._settings.max_sl_distance_pct}%"
                    )
                if tp_distance_pct > self._settings.max_tp_distance_pct:
                    result.add_failure(
                        f"TP is {tp_distance_pct:.1f}% from mark price, exceeds max "
                        f"{self._settings.max_tp_distance_pct}%"
                    )
                # Directional sanity: for LONG, SL should be below mark and
                # TP above; for SHORT, the reverse. A signal that fails this
                # is almost certainly a parsing error, not a real setup.
                if signal.side is not None:
                    if signal.side.value == "LONG" and not (signal.stop_loss < mark_price < signal.first_take_profit):
                        result.add_failure("LONG SL/TP not on the correct side of mark price")
                    if signal.side.value == "SHORT" and not (signal.first_take_profit < mark_price < signal.stop_loss):
                        result.add_failure("SHORT SL/TP not on the correct side of mark price")

        return result
