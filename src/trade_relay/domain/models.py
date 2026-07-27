from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from trade_relay.domain.enums import ManagementAction, MessageClass, Side


class IncomingMessage(BaseModel):
    """Normalized representation of a Telegram message, independent of
    Telethon's own event types, so the rest of the app never touches
    Telethon objects directly."""

    message_id: int
    chat_id: str
    text: str
    date: datetime
    reply_to_message_id: Optional[int] = None
    is_edit: bool = False


class ClassificationResult(BaseModel):
    message_class: MessageClass
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = ""


class ParsedSignal(BaseModel):
    """Structured fields extracted from a Trade Session's aggregated text.
    Any field may be None if it hasn't appeared yet (or couldn't be parsed).
    """

    symbol: Optional[str] = None
    side: Optional[Side] = None
    leverage: Optional[int] = None
    wallet_percent: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profits: list[float] = Field(default_factory=list)
    entry_price: Optional[float] = None  # None => market entry
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source: str = "rule"  # "rule" or "ai"
    raw_text: str = ""

    @property
    def first_take_profit(self) -> Optional[float]:
        """Per spec: always use the FIRST take profit only, ignore TP2+."""
        return self.take_profits[0] if self.take_profits else None

    def is_complete(self) -> bool:
        return self.symbol is not None and self.side is not None and self.stop_loss is not None and bool(self.take_profits)


class ManagementEvent(BaseModel):
    action: ManagementAction
    symbol: Optional[str] = None
    value: Optional[float] = None  # e.g. new SL price, or % to close
    raw_text: str = ""


class RiskCheckResult(BaseModel):
    passed: bool
    failures: list[str] = Field(default_factory=list)

    def add_failure(self, reason: str) -> None:
        self.passed = False
        self.failures.append(reason)
