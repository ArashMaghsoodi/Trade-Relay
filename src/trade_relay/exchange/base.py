"""
Exchange-agnostic interface. Everything upstream (risk engine, session
manager, control bot) talks to this interface only, never to a concrete
exchange SDK — so TooBit can be swapped or supplemented with another
exchange later without touching business logic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol


@dataclass
class Position:
    symbol: str
    side: str  # "LONG" | "SHORT"
    quantity: float
    entry_price: float
    mark_price: float
    unrealized_pnl: float
    roi_pct: float
    leverage: int


@dataclass
class Balance:
    wallet_balance: float
    available_balance: float


@dataclass
class OrderResult:
    success: bool
    order_id: Optional[str] = None
    is_live: bool = False  # False when this was a dry-run / shadow record
    error: Optional[str] = None
    raw: dict = field(default_factory=dict)


class ExchangeClient(Protocol):
    async def health_check(self) -> bool: ...

    async def get_balance(self) -> Balance: ...

    async def get_positions(self) -> list[Position]: ...

    async def get_mark_price(self, symbol: str) -> Optional[float]: ...

    async def has_open_position(self, symbol: str, side: str) -> bool: ...

    async def place_entry_order(
        self,
        symbol: str,
        side: str,
        leverage: int,
        wallet_percent: float,
        stop_loss: float,
        take_profit: float,
        entry_price: Optional[float] = None,
    ) -> OrderResult: ...

    async def move_stop_loss(self, symbol: str, new_sl: float) -> OrderResult: ...

    async def close_position(self, symbol: str, percent: float = 100.0) -> OrderResult: ...

    async def cancel_all_orders(self, symbol: str) -> OrderResult: ...
