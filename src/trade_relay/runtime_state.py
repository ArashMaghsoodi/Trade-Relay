from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from .models import EventType, SignalEvent, SignalSetup


@dataclass(slots=True)
class RuntimeState:
    one_position_per_symbol: bool = True
    setups_by_symbol: dict[str, SignalSetup] = field(default_factory=dict)
    open_symbols: set[str] = field(default_factory=set)
    processed_message_keys: deque[str] = field(default_factory=lambda: deque(maxlen=2000))
    _processed_lookup: set[str] = field(default_factory=set)
    recent_decisions: deque[str] = field(default_factory=lambda: deque(maxlen=100))

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
        if symbol not in state.setups_by_symbol:
            decision = f"ENTRY_SKIPPED_NO_SETUP {symbol} {event.side.value}"
            state.add_recent(decision)
            return decision

        if state.one_position_per_symbol and symbol in state.open_symbols:
            decision = f"ENTRY_SKIPPED_ALREADY_OPEN {symbol}"
            state.add_recent(decision)
            return decision

        state.open_symbols.add(symbol)
        decision = f"ENTRY_ACCEPTED_DRYRUN {symbol} {event.side.value}"
        state.add_recent(decision)
        return decision

    if event.event_type == EventType.TARGET_HIT:
        target = event.target_number or 0
        if symbol not in state.open_symbols:
            decision = f"TARGET_IGNORED_NO_OPEN_POSITION {symbol} target={target}"
            state.add_recent(decision)
            return decision

        if target <= 1:
            decision = f"TP1_PLAN {symbol} close=50% sl=breakeven"
            state.add_recent(decision)
            return decision

        state.open_symbols.discard(symbol)
        decision = f"TP2_CLOSE_REMAINING {symbol} close=100%"
        state.add_recent(decision)
        return decision

    if event.event_type == EventType.STOPPED_OUT:
        if symbol in state.open_symbols:
            state.open_symbols.discard(symbol)
            decision = f"STOPPED_OUT_CLOSED {symbol}"
            state.add_recent(decision)
            return decision

        decision = f"STOPPED_OUT_NO_OPEN_POSITION {symbol}"
        state.add_recent(decision)
        return decision

    decision = f"IGNORED_EVENT {symbol} {event.event_type.value}"
    state.add_recent(decision)
    return decision
