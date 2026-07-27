from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from trade_relay.db.models import ExecutedTrade, ManagementEventLog, MessageLog
from trade_relay.db.models import TradeSession as TradeSessionORM
from trade_relay.domain.enums import MessageClass, TradeSessionState


@dataclass
class ReportSummary:
    since: dt.datetime
    signals_received: int = 0
    signals_executed: int = 0
    signals_would_execute_shadow: int = 0
    signals_skipped: int = 0
    ignored_messages: int = 0
    unknown_messages: int = 0
    position_management_events: int = 0
    errors: int = 0
    skip_reason_samples: list[str] = field(default_factory=list)

    def render(self) -> str:
        lines = [
            f"📊 Report since {self.since.strftime('%Y-%m-%d %H:%M UTC')}",
            f"Signals received: {self.signals_received}",
            f"Executed: {self.signals_executed}",
            f"Would-execute (shadow/observation): {self.signals_would_execute_shadow}",
            f"Skipped: {self.signals_skipped}",
            f"General chat (ignored): {self.ignored_messages}",
            f"Unknown messages: {self.unknown_messages}",
            f"Position management events: {self.position_management_events}",
            f"Errors: {self.errors}",
        ]
        if self.skip_reason_samples:
            lines.append("\nRecent skip reasons:")
            lines.extend(f"  • {r}" for r in self.skip_reason_samples[:10])
        return "\n".join(lines)


def build_report(session_factory: sessionmaker, since_hours: int = 24) -> ReportSummary:
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=since_hours)
    summary = ReportSummary(since=since)

    with session_factory() as db:
        summary.signals_received = db.execute(
            select(func.count()).select_from(MessageLog).where(
                MessageLog.message_class == MessageClass.SIGNAL.value,
                MessageLog.received_at >= since,
            )
        ).scalar_one()

        summary.ignored_messages = db.execute(
            select(func.count()).select_from(MessageLog).where(
                MessageLog.message_class == MessageClass.GENERAL_CHAT.value,
                MessageLog.received_at >= since,
            )
        ).scalar_one()

        summary.unknown_messages = db.execute(
            select(func.count()).select_from(MessageLog).where(
                MessageLog.message_class == MessageClass.UNKNOWN.value,
                MessageLog.received_at >= since,
            )
        ).scalar_one()

        summary.position_management_events = db.execute(
            select(func.count()).select_from(ManagementEventLog).where(
                ManagementEventLog.created_at >= since
            )
        ).scalar_one()

        summary.signals_executed = db.execute(
            select(func.count()).select_from(ExecutedTrade).where(
                ExecutedTrade.is_live.is_(True), ExecutedTrade.created_at >= since
            )
        ).scalar_one()

        summary.signals_would_execute_shadow = db.execute(
            select(func.count()).select_from(ExecutedTrade).where(
                ExecutedTrade.is_live.is_(False), ExecutedTrade.created_at >= since
            )
        ).scalar_one()

        skipped_sessions = db.execute(
            select(TradeSessionORM).where(
                TradeSessionORM.state == TradeSessionState.SKIPPED.value,
                TradeSessionORM.created_at >= since,
            )
        ).scalars().all()
        summary.signals_skipped = len(skipped_sessions)
        summary.skip_reason_samples = [
            f"{s.symbol or '?'} {s.side or ''}: {', '.join(s.skip_reasons)}" for s in skipped_sessions
        ]

    return summary
