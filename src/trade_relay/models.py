from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Side(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class EventType(str, Enum):
    SETUP = "SETUP"
    ENTRY_TRIGGER = "ENTRY_TRIGGER"
    TARGET_HIT = "TARGET_HIT"
    STOPPED_OUT = "STOPPED_OUT"


@dataclass(slots=True)
class SignalSetup:
    symbol: str
    side: Side
    entry_low: float
    entry_high: float
    tp1: float
    tp2: float
    tp3: Optional[float]
    stop_loss: float


@dataclass(slots=True)
class SignalEvent:
    event_type: EventType
    symbol: str
    side: Side
    setup: Optional[SignalSetup] = None
    target_number: Optional[int] = None
