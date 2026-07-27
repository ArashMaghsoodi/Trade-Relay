from __future__ import annotations

import enum


class MessageClass(str, enum.Enum):
    SIGNAL = "SIGNAL"
    POSITION_MANAGEMENT = "POSITION_MANAGEMENT"
    GENERAL_CHAT = "GENERAL_CHAT"
    UNKNOWN = "UNKNOWN"


class Side(str, enum.Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class TradeSessionState(str, enum.Enum):
    WAITING = "WAITING"     # collecting info, not enough to execute yet
    READY = "READY"          # all required fields present, passed risk checks pending
    EXECUTED = "EXECUTED"    # order placed on the exchange
    MANAGED = "MANAGED"      # open position being actively managed (SL/TP moved, partials)
    CLOSED = "CLOSED"        # position closed
    SKIPPED = "SKIPPED"      # deliberately not executed (risk check failed, stale, duplicate, etc.)


class ManagementAction(str, enum.Enum):
    CLOSE_ALL = "CLOSE_ALL"
    CLOSE_PARTIAL = "CLOSE_PARTIAL"
    MOVE_SL = "MOVE_SL"
    MOVE_SL_BREAKEVEN = "MOVE_SL_BREAKEVEN"
    MOVE_TP = "MOVE_TP"
    SECOND_ENTRY = "SECOND_ENTRY"  # intentionally ignored per spec, kept for logging
    UNRECOGNIZED = "UNRECOGNIZED"


class RiskCheckStatus(str, enum.Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"
