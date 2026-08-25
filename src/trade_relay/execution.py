from __future__ import annotations

from dataclasses import dataclass

from .models import Side


@dataclass(slots=True)
class PaperOrderIntent:
    symbol: str
    side: str
    quantity: float
    leverage: int
    risk_percent: float
    reason: str


def estimate_quantity_from_risk(
    entry_price: float,
    stop_loss: float,
    account_balance_usdt: float,
    risk_percent: float,
    leverage: int,
) -> float:
    risk_amount = account_balance_usdt * (risk_percent / 100.0)
    stop_distance = abs(entry_price - stop_loss)
    if stop_distance <= 0:
        raise ValueError("Invalid stop distance")

    # Very rough dry-run approximation; refined exchange precision handling comes next step.
    raw_qty = (risk_amount / stop_distance) * leverage
    return max(raw_qty, 0.0)


def build_entry_order_intent(
    *,
    symbol: str,
    side: Side,
    entry_price: float,
    stop_loss: float,
    account_balance_usdt: float,
    risk_percent: float,
    leverage: int,
    reason: str,
) -> PaperOrderIntent:
    qty = estimate_quantity_from_risk(
        entry_price=entry_price,
        stop_loss=stop_loss,
        account_balance_usdt=account_balance_usdt,
        risk_percent=risk_percent,
        leverage=leverage,
    )
    return PaperOrderIntent(
        symbol=symbol,
        side=side.value,
        quantity=round(qty, 6),
        leverage=leverage,
        risk_percent=risk_percent,
        reason=reason,
    )
