"""
Trade Session Manager.

Owns the message -> classification -> Trade Session -> risk check ->
(maybe) execution pipeline. This is the orchestrator; it delegates parsing
to nlp/, safety decisions to RiskEngine, and exchange actions to the
ExchangeClient interface.

Key behaviors from the spec this enforces:
- messages are aggregated into Trade Sessions across replies, not processed
  independently
- edits update a session only if it hasn't executed yet
- position-management messages are handled with higher priority and can be
  intentionally ignored (e.g. "second entry active")
- duplicate/staleness/confidence protections all flow through RiskEngine
- automation_enabled gates whether anything autonomous happens at all;
  LIVE_TRADING_ENABLED (inside the exchange client) gates real vs dry-run
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from trade_relay.config import Settings
from trade_relay.db.models import ExecutedTrade, ManagementEventLog, MessageLog
from trade_relay.db.models import TradeSession as TradeSessionORM
from trade_relay.domain.enums import ManagementAction, MessageClass, TradeSessionState
from trade_relay.domain.models import IncomingMessage, ParsedSignal
from trade_relay.exchange.base import ExchangeClient
from trade_relay.nlp.ai_parser import AIParserProvider
from trade_relay.nlp.classifier import classify
from trade_relay.nlp.rule_parser import parse_management, parse_signal
from trade_relay.notifications.notifier import Notifier
from trade_relay.trading.automation_state import is_automation_enabled
from trade_relay.trading.risk_engine import RiskEngine

logger = logging.getLogger(__name__)


class TradeSessionManager:
    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker,
        exchange: ExchangeClient,
        risk_engine: RiskEngine,
        notifier: Notifier,
        ai_parser: AIParserProvider,
    ):
        self._settings = settings
        self._session_factory = session_factory
        self._exchange = exchange
        self._risk_engine = risk_engine
        self._notifier = notifier
        self._ai_parser = ai_parser

    async def handle_message(self, msg: IncomingMessage) -> None:
        classification = classify(msg.text)

        with self._session_factory() as db:
            log_entry = MessageLog(
                telegram_message_id=msg.message_id,
                chat_id=msg.chat_id,
                text=msg.text,
                is_edit=msg.is_edit,
                reply_to_message_id=msg.reply_to_message_id,
                message_class=classification.message_class.value,
                classification_confidence=classification.confidence,
            )
            db.add(log_entry)
            db.commit()

            if classification.message_class == MessageClass.POSITION_MANAGEMENT:
                await self._handle_management(db, msg, log_entry)
            elif classification.message_class == MessageClass.SIGNAL:
                await self._handle_signal(db, msg, log_entry)
            else:
                # GENERAL_CHAT and UNKNOWN: log only, no notification, per spec.
                logger.debug("Ignoring message %s classified as %s", msg.message_id, classification.message_class)

    # -- signal handling -------------------------------------------------

    async def _find_session_for_message(self, db: Session, msg: IncomingMessage) -> TradeSessionORM | None:
        """Walk the reply chain to find an existing Trade Session this
        message belongs to. Returns None if this message should start a new
        session instead."""

        if msg.is_edit:
            return db.execute(
                select(TradeSessionORM).where(TradeSessionORM.root_message_id == msg.message_id)
            ).scalar_one_or_none()

        if msg.reply_to_message_id is None:
            return None

        # Look up what the message being replied to belongs to.
        parent_log = db.execute(
            select(MessageLog).where(
                MessageLog.telegram_message_id == msg.reply_to_message_id,
                MessageLog.chat_id == msg.chat_id,
            )
        ).scalar_one_or_none()

        if parent_log is None or parent_log.trade_session_id is None:
            # Could be a reply directly to the root signal message before
            # any session existed at parent-log time, or a reply several
            # levels deep — fall back to searching by root_message_id
            # matching the reply target directly.
            return db.execute(
                select(TradeSessionORM).where(TradeSessionORM.root_message_id == msg.reply_to_message_id)
            ).scalar_one_or_none()

        return db.get(TradeSessionORM, parent_log.trade_session_id)

    async def _handle_signal(self, db: Session, msg: IncomingMessage, log_entry: MessageLog) -> None:
        session_orm = await self._find_session_for_message(db, msg)

        if session_orm is not None and session_orm.state in (
            TradeSessionState.EXECUTED.value,
            TradeSessionState.MANAGED.value,
            TradeSessionState.CLOSED.value,
        ):
            if msg.is_edit:
                # Per spec: don't silently modify an executed trade from an
                # edit. Log it as a management-relevant event instead.
                logger.info(
                    "Message %s edits an already-%s session %s; not auto-modifying the live trade",
                    msg.message_id, session_orm.state, session_orm.id,
                )
                await self._notifier.notify(
                    f"⚠️ Signal for {session_orm.symbol} was edited after execution. "
                    f"Not auto-modifying — review manually.\n\nEdited text: {msg.text}"
                )
            return

        if session_orm is None:
            session_orm = TradeSessionORM(
                root_message_id=msg.message_id,
                chat_id=msg.chat_id,
                state=TradeSessionState.WAITING.value,
                raw_text=msg.text,
            )
            db.add(session_orm)
            db.commit()
            db.refresh(session_orm)
        else:
            session_orm.raw_text = f"{session_orm.raw_text}\n{msg.text}"

        log_entry.trade_session_id = session_orm.id
        db.commit()

        parsed = parse_signal(session_orm.raw_text)

        if not parsed.is_complete() or parsed.confidence < self._settings.min_parser_confidence:
            ai_parsed = await self._ai_parser.parse(session_orm.raw_text)
            if ai_parsed.confidence > parsed.confidence:
                parsed = self._merge_signals(parsed, ai_parsed)

        self._apply_parsed_to_session(session_orm, parsed)

        if not parsed.is_complete():
            session_orm.state = TradeSessionState.WAITING.value
            db.commit()
            logger.debug("Session %s still WAITING on more info", session_orm.id)
            return

        session_orm.state = TradeSessionState.READY.value
        db.commit()

        await self._evaluate_and_maybe_execute(db, session_orm, parsed)

    @staticmethod
    def _merge_signals(base: ParsedSignal, fallback: ParsedSignal) -> ParsedSignal:
        """Fill any fields `base` (rule parser) is missing with values from
        `fallback` (AI parser), preferring rule-parsed fields wherever
        present since they're deterministic and auditable."""
        merged = base.model_copy()
        if merged.symbol is None:
            merged.symbol = fallback.symbol
        if merged.side is None:
            merged.side = fallback.side
        if merged.leverage is None:
            merged.leverage = fallback.leverage
        if merged.wallet_percent is None:
            merged.wallet_percent = fallback.wallet_percent
        if merged.stop_loss is None:
            merged.stop_loss = fallback.stop_loss
        if not merged.take_profits:
            merged.take_profits = fallback.take_profits
        if merged.entry_price is None:
            merged.entry_price = fallback.entry_price
        merged.confidence = max(merged.confidence, fallback.confidence * 0.9)  # slight discount for AI fill-in
        merged.source = "rule+ai" if base.confidence > 0 else fallback.source
        return merged

    @staticmethod
    def _apply_parsed_to_session(session_orm: TradeSessionORM, parsed: ParsedSignal) -> None:
        session_orm.symbol = parsed.symbol
        session_orm.side = parsed.side.value if parsed.side else None
        session_orm.leverage = parsed.leverage
        session_orm.wallet_percent = parsed.wallet_percent
        session_orm.stop_loss = parsed.stop_loss
        session_orm.take_profits = parsed.take_profits
        session_orm.entry_price = parsed.entry_price
        session_orm.parser_confidence = parsed.confidence
        session_orm.parser_source = parsed.source

    async def _evaluate_and_maybe_execute(
        self, db: Session, session_orm: TradeSessionORM, parsed: ParsedSignal
    ) -> None:
        risk_result = await self._risk_engine.evaluate(parsed, session_orm.created_at)

        if not risk_result.passed:
            session_orm.state = TradeSessionState.SKIPPED.value
            session_orm.would_execute = False
            session_orm.skip_reasons = risk_result.failures
            db.commit()
            logger.info("Session %s SKIPPED: %s", session_orm.id, risk_result.failures)
            return

        session_orm.would_execute = True
        db.commit()

        leverage = parsed.leverage or self._settings.default_leverage
        wallet_percent = self._settings.clamp_wallet_percent(parsed.wallet_percent)

        if not is_automation_enabled(db):
            logger.info(
                "Session %s passed all risk checks but automation is disabled — logging only", session_orm.id
            )
            await self._notifier.notify(
                f"✅ Would EXECUTE {session_orm.side} {session_orm.symbol} "
                f"(lev {leverage}x, {wallet_percent}% wallet, SL {parsed.stop_loss}, "
                f"TP {parsed.first_take_profit}) — automation is currently OFF, no action taken."
            )
            return

        order_result = await self._exchange.place_entry_order(
            symbol=session_orm.symbol,
            side=session_orm.side,
            leverage=leverage,
            wallet_percent=wallet_percent,
            stop_loss=parsed.stop_loss,
            take_profit=parsed.first_take_profit,
            entry_price=parsed.entry_price,
        )

        if order_result.success:
            session_orm.state = TradeSessionState.EXECUTED.value
            db.add(
                ExecutedTrade(
                    trade_session_id=session_orm.id,
                    symbol=session_orm.symbol,
                    side=session_orm.side,
                    leverage=leverage,
                    wallet_percent=wallet_percent,
                    stop_loss=parsed.stop_loss,
                    take_profit=parsed.first_take_profit,
                    entry_price=parsed.entry_price,
                    is_live=order_result.is_live,
                    exchange_order_id=order_result.order_id,
                )
            )
            db.commit()
            tag = "LIVE" if order_result.is_live else "SHADOW/DRY-RUN"
            await self._notifier.notify(
                f"✅ [{tag}] Opened {session_orm.side} {session_orm.symbol} "
                f"(lev {leverage}x, {wallet_percent}% wallet, SL {parsed.stop_loss}, TP {parsed.first_take_profit})"
            )
        else:
            session_orm.state = TradeSessionState.SKIPPED.value
            session_orm.skip_reasons = [f"exchange error: {order_result.error}"]
            db.commit()
            await self._notifier.notify(
                f"❌ Failed to open {session_orm.side} {session_orm.symbol}: {order_result.error}"
            )

    # -- position management ---------------------------------------------

    async def _handle_management(self, db: Session, msg: IncomingMessage, log_entry: MessageLog) -> None:
        event = parse_management(msg.text)

        matching_session = None
        if event.symbol:
            matching_session = db.execute(
                select(TradeSessionORM)
                .where(
                    TradeSessionORM.symbol == event.symbol,
                    TradeSessionORM.state.in_(
                        [TradeSessionState.EXECUTED.value, TradeSessionState.MANAGED.value]
                    ),
                )
                .order_by(TradeSessionORM.created_at.desc())
            ).scalars().first()

        acted_on = False

        if event.action == ManagementAction.SECOND_ENTRY:
            # Explicitly ignored per spec — logged for visibility only.
            logger.info("Ignoring 'second entry' management event: %s", msg.text)
        elif event.action == ManagementAction.UNRECOGNIZED:
            logger.info("Unrecognized management message, logging only: %s", msg.text)
        elif matching_session is None:
            logger.info("Management event %s had no matching open session (symbol=%s)", event.action, event.symbol)
            await self._notifier.notify(
                f"ℹ️ Position-management message received but no matching open session found: {msg.text}"
            )
        elif is_automation_enabled(db):
            acted_on = await self._act_on_management(matching_session, event)
        else:
            await self._notifier.notify(
                f"ℹ️ Management message for {event.symbol} ({event.action.value}) received — "
                f"automation is OFF, no action taken.\n\n{msg.text}"
            )

        db.add(
            ManagementEventLog(
                trade_session_id=matching_session.id if matching_session else None,
                action=event.action.value,
                symbol=event.symbol,
                value=event.value,
                acted_on=acted_on,
                raw_text=msg.text,
            )
        )
        db.commit()

    async def _act_on_management(self, session_orm: TradeSessionORM, event) -> bool:
        if event.action == ManagementAction.CLOSE_ALL:
            result = await self._exchange.close_position(session_orm.symbol, percent=100.0)
        elif event.action == ManagementAction.CLOSE_PARTIAL:
            result = await self._exchange.close_position(session_orm.symbol, percent=event.value or 50.0)
        elif event.action == ManagementAction.MOVE_SL:
            result = await self._exchange.move_stop_loss(session_orm.symbol, event.value)
        elif event.action == ManagementAction.MOVE_SL_BREAKEVEN:
            result = await self._exchange.move_stop_loss(session_orm.symbol, session_orm.entry_price or session_orm.stop_loss)
        else:
            return False

        tag = "LIVE" if result.is_live else "SHADOW/DRY-RUN"
        if result.success:
            await self._notifier.notify(f"🔧 [{tag}] {event.action.value} applied to {session_orm.symbol}")
        else:
            await self._notifier.notify(f"❌ [{tag}] {event.action.value} FAILED for {session_orm.symbol}: {result.error}")
        return result.success
