from __future__ import annotations

import datetime as dt
import json
from typing import Optional

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from trade_relay.db.base import Base


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class MessageLog(Base):
    """Every message that arrives, regardless of classification. This is the
    raw audit trail used by /report and for judging parser accuracy during
    the observation period."""

    __tablename__ = "message_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_message_id: Mapped[int] = mapped_column(Integer)
    chat_id: Mapped[str] = mapped_column(String)
    text: Mapped[str] = mapped_column(Text)
    is_edit: Mapped[bool] = mapped_column(default=False)
    reply_to_message_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    message_class: Mapped[str] = mapped_column(String)
    classification_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    trade_session_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    received_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class TradeSession(Base):
    """A signal being aggregated across possibly-multiple messages/replies."""

    __tablename__ = "trade_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    root_message_id: Mapped[int] = mapped_column(Integer, index=True)
    chat_id: Mapped[str] = mapped_column(String)
    state: Mapped[str] = mapped_column(String, default="WAITING")

    symbol: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    side: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    leverage: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    wallet_percent: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    stop_loss: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    take_profits_json: Mapped[str] = mapped_column(String, default="[]")
    entry_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    parser_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    parser_source: Mapped[str] = mapped_column(String, default="rule")

    would_execute: Mapped[Optional[bool]] = mapped_column(nullable=True)
    skip_reasons_json: Mapped[str] = mapped_column(String, default="[]")

    raw_text: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    @property
    def take_profits(self) -> list[float]:
        return json.loads(self.take_profits_json or "[]")

    @take_profits.setter
    def take_profits(self, value: list[float]) -> None:
        self.take_profits_json = json.dumps(value)

    @property
    def skip_reasons(self) -> list[str]:
        return json.loads(self.skip_reasons_json or "[]")

    @skip_reasons.setter
    def skip_reasons(self, value: list[str]) -> None:
        self.skip_reasons_json = json.dumps(value)


class ExecutedTrade(Base):
    """A trade that was actually (or, in observation mode, would have been)
    sent to the exchange. `is_live` distinguishes real fills from
    shadow/dry-run records logged during observation mode."""

    __tablename__ = "executed_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_session_id: Mapped[int] = mapped_column(Integer, index=True)
    symbol: Mapped[str] = mapped_column(String)
    side: Mapped[str] = mapped_column(String)
    leverage: Mapped[int] = mapped_column(Integer)
    wallet_percent: Mapped[float] = mapped_column(Float)
    stop_loss: Mapped[float] = mapped_column(Float)
    take_profit: Mapped[float] = mapped_column(Float)
    entry_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    is_live: Mapped[bool] = mapped_column(default=False)
    exchange_order_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="SUBMITTED")
    closed_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ManagementEventLog(Base):
    """Log of position-management messages (close/move SL/etc.), whether or
    not they were acted on."""

    __tablename__ = "management_event_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_session_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(String)
    symbol: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    acted_on: Mapped[bool] = mapped_column(default=False)
    raw_text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class AppConfigOverride(Base):
    """Optional runtime overrides on top of .env, e.g. automation
    enabled/disabled state, so it survives restarts."""

    __tablename__ = "app_config_overrides"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(String)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
