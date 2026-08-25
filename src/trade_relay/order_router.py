from __future__ import annotations

from .config import Settings
from .execution import build_entry_order_intent
from .models import EventType, SignalEvent
from .runtime_state import RuntimeState


def maybe_create_order_intent(settings: Settings, state: RuntimeState, event: SignalEvent, decision: str) -> str | None:
    if settings.trading_mode not in {"paper", "live"}:
        return None

    if event.event_type != EventType.ENTRY_TRIGGER:
        return None

    if not decision.startswith("ENTRY_ACCEPTED_DRYRUN"):
        return None

    setup = state.setups_by_symbol.get(event.symbol)
    if setup is None:
        return None

    entry_reference = (setup.entry_low + setup.entry_high) / 2.0
    intent = build_entry_order_intent(
        symbol=event.symbol,
        side=event.side,
        entry_price=entry_reference,
        stop_loss=setup.stop_loss,
        account_balance_usdt=settings.paper_account_balance_usdt,
        risk_percent=settings.risk_per_trade_percent,
        leverage=settings.default_leverage,
        reason=f"{settings.trading_mode}:entry_trigger",
    )
    state.add_order_intent(intent)

    if settings.trading_mode == "live":
        return f"LIVE_BLOCKED_INTENT_ONLY {intent.symbol} qty={intent.quantity} lev={intent.leverage}"

    return f"PAPER_ORDER_INTENT {intent.symbol} {intent.side} qty={intent.quantity} lev={intent.leverage}"
