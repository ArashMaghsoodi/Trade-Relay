from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .execution import PaperOrderIntent
from .models import EventType, SignalEvent, SignalSetup


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class VirtualPosition:
    symbol: str
    side: str
    entry_status: str = "OPEN"
    size_percent_open: float = 100.0
    tp1_hit: bool = False
    sl_moved_to_breakeven: bool = False
    opened_at: str = field(default_factory=_utc_now_iso)
    last_event_at: str = field(default_factory=_utc_now_iso)
    closed_at: str | None = None
    close_reason: str | None = None


@dataclass(slots=True)
class ClosedPositionRecord:
    symbol: str
    side: str
    final_status: str
    opened_at: str
    closed_at: str
    close_reason: str
    tp1_hit: bool
    sl_moved_to_breakeven: bool


@dataclass(slots=True)
class RuntimeState:
    one_position_per_symbol: bool = True
    paused: bool = False
    setups_by_symbol: dict[str, SignalSetup] = field(default_factory=dict)
    open_symbols: set[str] = field(default_factory=set)
    positions_by_symbol: dict[str, VirtualPosition] = field(default_factory=dict)
    closed_positions: deque[ClosedPositionRecord] = field(default_factory=lambda: deque(maxlen=400))
    order_intents: deque[PaperOrderIntent] = field(default_factory=lambda: deque(maxlen=400))
    processed_message_keys: deque[str] = field(default_factory=lambda: deque(maxlen=2000))
    _processed_lookup: set[str] = field(default_factory=set)
    recent_decisions: deque[str] = field(default_factory=lambda: deque(maxlen=300))

    def seen_message(self, message_key: str) -> bool:
        if message_key in self._processed_lookup:
            return True

        if len(self.processed_message_keys) == self.processed_message_keys.maxlen:
            oldest = self.processed_message_keys[0]
            self._processed_lookup.discard(oldest)

        self.processed_message_keys.append(message_key)
        self._processed_lookup.add(message_key)
        return False

    def add_recent(self, value: str) -> None:
        self.recent_decisions.append(value)

    def pause(self) -> str:
        self.paused = True
        decision = "RELAY_PAUSED"
        self.add_recent(decision)
        return decision

    def resume(self) -> str:
        self.paused = False
        decision = "RELAY_RESUMED"
        self.add_recent(decision)
        return decision

    def add_order_intent(self, intent: PaperOrderIntent) -> None:
        self.order_intents.append(intent)


def _close_position(state: RuntimeState, symbol: str, final_status: str, close_reason: str) -> None:
    state.open_symbols.discard(symbol)
    position = state.positions_by_symbol.get(symbol)
    if position is None:
        return

    now = _utc_now_iso()
    position.size_percent_open = 0.0
    position.entry_status = final_status
    position.last_event_at = now
    position.closed_at = now
    position.close_reason = close_reason

    state.closed_positions.append(
        ClosedPositionRecord(
            symbol=position.symbol,
            side=position.side,
            final_status=position.entry_status,
            opened_at=position.opened_at,
            closed_at=position.closed_at,
            close_reason=position.close_reason,
            tp1_hit=position.tp1_hit,
            sl_moved_to_breakeven=position.sl_moved_to_breakeven,
        )
    )


def process_signal_event(state: RuntimeState, event: SignalEvent, message_key: str) -> str:
    if state.seen_message(message_key):
        decision = f"DEDUP_SKIPPED key={message_key}"
        state.add_recent(decision)
        return decision

    symbol = event.symbol

    if event.event_type == EventType.SETUP and event.setup is not None:
        state.setups_by_symbol[symbol] = event.setup
        decision = f"SETUP_CACHED {symbol} {event.side.value}"
        state.add_recent(decision)
        return decision

    if event.event_type == EventType.ENTRY_TRIGGER:
        if state.paused:
            decision = f"ENTRY_SKIPPED_RELAY_PAUSED {symbol} {event.side.value}"
            state.add_recent(decision)
            return decision

        if symbol not in state.setups_by_symbol:
            decision = f"ENTRY_SKIPPED_NO_SETUP {symbol} {event.side.value}"
            state.add_recent(decision)
            return decision

        if state.one_position_per_symbol and symbol in state.open_symbols:
            decision = f"ENTRY_SKIPPED_ALREADY_OPEN {symbol}"
            state.add_recent(decision)
            return decision

        state.open_symbols.add(symbol)
        state.positions_by_symbol[symbol] = VirtualPosition(symbol=symbol, side=event.side.value)
        decision = f"ENTRY_ACCEPTED_DRYRUN {symbol} {event.side.value}"
        state.add_recent(decision)
        return decision

    if event.event_type == EventType.TARGET_HIT:
        target = event.target_number or 0
        if symbol not in state.open_symbols:
            decision = f"TARGET_IGNORED_NO_OPEN_POSITION {symbol} target={target}"
            state.add_recent(decision)
            return decision

        position = state.positions_by_symbol.get(symbol)
        if position is not None:
            position.last_event_at = _utc_now_iso()

        if target <= 1:
            if position is not None:
                position.tp1_hit = True
                position.sl_moved_to_breakeven = True
                position.size_percent_open = 50.0
                position.entry_status = "OPEN_PARTIAL"
            decision = f"TP1_PLAN {symbol} close=50% sl=breakeven"
            state.add_recent(decision)
            return decision

        _close_position(state, symbol, final_status="CLOSED_TP2", close_reason="TARGET_2_PLUS_REACHED")
        decision = f"TP2_CLOSE_REMAINING {symbol} close=100%"
        state.add_recent(decision)
        return decision

    if event.event_type == EventType.STOPPED_OUT:
        if symbol in state.open_symbols:
            _close_position(state, symbol, final_status="CLOSED_SL", close_reason="STOPPED_OUT")
            decision = f"STOPPED_OUT_CLOSED {symbol}"
            state.add_recent(decision)
            return decision

        decision = f"STOPPED_OUT_NO_OPEN_POSITION {symbol}"
        state.add_recent(decision)
        return decision

    decision = f"IGNORED_EVENT {symbol} {event.event_type.value}"
    state.add_recent(decision)
    return decision
