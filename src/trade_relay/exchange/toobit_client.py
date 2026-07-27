"""
TooBit futures REST client.

Built from TooBit's public API docs (api-docs.toobit.com):
  - Signed endpoints use HMAC-SHA256 over the concatenated query string
    (+ JSON body for /api/v2 routes), sent as a lowercase hex `signature`
    param, with the API key in the `X-BB-APIKEY` header.
  - Futures symbols use the format `BASE-SWAP-USDT` (e.g. `BTC-SWAP-USDT`),
    NOT the spot format `BTCUSDT`.
  - Order `side` values are BUY_OPEN / SELL_OPEN / BUY_CLOSE / SELL_CLOSE.

VERIFY endpoint paths and payload shapes against the current docs before
going live — this hasn't been exercised against a real account yet since
LIVE_TRADING_ENABLED defaults to false. Treat the exact paths below
(`/api/v1/futures/...`) as a best-effort starting point, not gospel.

Safety: every method that would place, modify, or close a real order checks
`settings.live_trading_enabled` FIRST, inside this client — not just in the
business logic above it. When false, those calls are logged and return a
non-live OrderResult without making any network request. Read-only calls
(balance, positions, mark price, health) always hit the real API, since the
risk engine and /status need real data even during observation mode.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from typing import Optional
from urllib.parse import urlencode

import httpx

from trade_relay.config import Settings
from trade_relay.exchange.base import Balance, OrderResult, Position

logger = logging.getLogger(__name__)


def _to_futures_symbol(symbol: str) -> str:
    """Convert a plain symbol like 'BTCUSDT' or 'BTC' into TooBit's futures
    format 'BTC-SWAP-USDT'."""
    symbol = symbol.upper()
    if "-SWAP-" in symbol:
        return symbol
    for quote in ("USDT", "USDC", "USD"):
        if symbol.endswith(quote) and symbol != quote:
            base = symbol[: -len(quote)]
            return f"{base}-SWAP-{quote}"
    return f"{symbol}-SWAP-USDT"


class TooBitClient:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._client = httpx.AsyncClient(base_url=settings.toobit_base_url, timeout=10.0)

    # -- signing -------------------------------------------------------

    def _sign(self, params: dict) -> str:
        total_params = urlencode(params)
        return hmac.new(
            self._settings.toobit_api_secret.encode(),
            total_params.encode(),
            hashlib.sha256,
        ).hexdigest()

    async def _signed_request(self, method: str, path: str, params: Optional[dict] = None) -> dict:
        params = dict(params or {})
        params["timestamp"] = int(time.time() * 1000)
        params.setdefault("recvWindow", 5000)
        params["signature"] = self._sign(params)
        headers = {"X-BB-APIKEY": self._settings.toobit_api_key}

        if method == "GET":
            response = await self._client.get(path, params=params, headers=headers)
        else:
            response = await self._client.request(method, path, params=params, headers=headers)
        response.raise_for_status()
        return response.json()

    # -- read-only: always live, needed even during observation mode ----

    async def health_check(self) -> bool:
        try:
            await self._client.get("/api/v1/time", timeout=5.0)
            return True
        except Exception:  # noqa: BLE001
            logger.exception("TooBit health check failed")
            return False

    async def get_balance(self) -> Balance:
        data = await self._signed_request("GET", "/api/v1/futures/balance")
        # NOTE: field names below are a best-effort guess pending
        # verification against a real account response; adjust once
        # you've inspected the live payload shape.
        assets = data.get("data") or data.get("balances") or []
        wallet = sum(float(a.get("balance", 0)) for a in assets) if isinstance(assets, list) else float(data.get("balance", 0))
        available = sum(float(a.get("availableBalance", 0)) for a in assets) if isinstance(assets, list) else float(data.get("availableBalance", 0))
        return Balance(wallet_balance=wallet, available_balance=available)

    async def get_positions(self) -> list[Position]:
        data = await self._signed_request("GET", "/api/v1/futures/positions")
        raw_positions = data.get("data") or []
        positions: list[Position] = []
        for p in raw_positions:
            qty = float(p.get("positionAmt", 0) or 0)
            if qty == 0:
                continue
            positions.append(
                Position(
                    symbol=p.get("symbol", ""),
                    side="LONG" if qty > 0 else "SHORT",
                    quantity=abs(qty),
                    entry_price=float(p.get("entryPrice", 0) or 0),
                    mark_price=float(p.get("markPrice", 0) or 0),
                    unrealized_pnl=float(p.get("unrealizedProfit", 0) or 0),
                    roi_pct=float(p.get("roi", 0) or 0),
                    leverage=int(p.get("leverage", 0) or 0),
                )
            )
        return positions

    async def get_mark_price(self, symbol: str) -> Optional[float]:
        futures_symbol = _to_futures_symbol(symbol)
        try:
            response = await self._client.get(
                "/api/v1/futures/premiumIndex", params={"symbol": futures_symbol}
            )
            response.raise_for_status()
            data = response.json()
            price = (data.get("data") or data).get("markPrice")
            return float(price) if price is not None else None
        except Exception:  # noqa: BLE001
            logger.exception("Failed to fetch mark price for %s", futures_symbol)
            return None

    async def has_open_position(self, symbol: str, side: str) -> bool:
        futures_symbol = _to_futures_symbol(symbol)
        positions = await self.get_positions()
        return any(p.symbol == futures_symbol and p.side == side for p in positions)

    # -- write: gated behind LIVE_TRADING_ENABLED -----------------------

    def _dry_run_result(self, action: str, **details) -> OrderResult:
        logger.info("[DRY RUN] would execute %s: %s", action, details)
        return OrderResult(success=True, is_live=False, raw={"action": action, **details})

    async def place_entry_order(
        self,
        symbol: str,
        side: str,
        leverage: int,
        wallet_percent: float,
        stop_loss: float,
        take_profit: float,
        entry_price: Optional[float] = None,
    ) -> OrderResult:
        futures_symbol = _to_futures_symbol(symbol)
        if not self._settings.live_trading_enabled:
            return self._dry_run_result(
                "place_entry_order",
                symbol=futures_symbol,
                side=side,
                leverage=leverage,
                wallet_percent=wallet_percent,
                stop_loss=stop_loss,
                take_profit=take_profit,
                entry_price=entry_price,
            )

        try:
            balance = await self.get_balance()
            notional = balance.available_balance * (wallet_percent / 100.0) * leverage
            order_side = "BUY_OPEN" if side == "LONG" else "SELL_OPEN"
            params = {
                "symbol": futures_symbol,
                "side": order_side,
                "type": "MARKET" if entry_price is None else "LIMIT",
                "quantity": notional,  # NOTE: verify quote-vs-base sizing convention before going live
            }
            if entry_price is not None:
                params["price"] = entry_price
            result = await self._signed_request("POST", "/api/v1/futures/order", params)
            order_id = str(result.get("orderId") or result.get("data", {}).get("orderId", ""))

            # Attach SL/TP as separate conditional orders, per TooBit's
            # trigger-order model.
            await self._signed_request(
                "POST",
                "/api/v1/futures/order",
                {
                    "symbol": futures_symbol,
                    "side": "SELL_CLOSE" if side == "LONG" else "BUY_CLOSE",
                    "type": "STOP_MARKET",
                    "stopPrice": stop_loss,
                    "closePosition": True,
                },
            )
            await self._signed_request(
                "POST",
                "/api/v1/futures/order",
                {
                    "symbol": futures_symbol,
                    "side": "SELL_CLOSE" if side == "LONG" else "BUY_CLOSE",
                    "type": "TAKE_PROFIT_MARKET",
                    "stopPrice": take_profit,
                    "closePosition": True,
                },
            )
            return OrderResult(success=True, order_id=order_id, is_live=True, raw=result)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to place entry order for %s", futures_symbol)
            return OrderResult(success=False, is_live=True, error=str(exc))

    async def move_stop_loss(self, symbol: str, new_sl: float) -> OrderResult:
        futures_symbol = _to_futures_symbol(symbol)
        if not self._settings.live_trading_enabled:
            return self._dry_run_result("move_stop_loss", symbol=futures_symbol, new_sl=new_sl)
        try:
            await self.cancel_all_orders(symbol)  # cancel prior SL/TP triggers first
            result = await self._signed_request(
                "POST",
                "/api/v1/futures/order",
                {"symbol": futures_symbol, "type": "STOP_MARKET", "stopPrice": new_sl, "closePosition": True},
            )
            return OrderResult(success=True, is_live=True, raw=result)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to move SL for %s", futures_symbol)
            return OrderResult(success=False, is_live=True, error=str(exc))

    async def close_position(self, symbol: str, percent: float = 100.0) -> OrderResult:
        futures_symbol = _to_futures_symbol(symbol)
        if not self._settings.live_trading_enabled:
            return self._dry_run_result("close_position", symbol=futures_symbol, percent=percent)
        try:
            positions = await self.get_positions()
            match = next((p for p in positions if p.symbol == futures_symbol), None)
            if match is None:
                return OrderResult(success=False, is_live=True, error="no open position found")
            qty = match.quantity * (percent / 100.0)
            close_side = "SELL_CLOSE" if match.side == "LONG" else "BUY_CLOSE"
            result = await self._signed_request(
                "POST",
                "/api/v1/futures/order",
                {"symbol": futures_symbol, "side": close_side, "type": "MARKET", "quantity": qty},
            )
            return OrderResult(success=True, is_live=True, raw=result)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to close position for %s", futures_symbol)
            return OrderResult(success=False, is_live=True, error=str(exc))

    async def cancel_all_orders(self, symbol: str) -> OrderResult:
        futures_symbol = _to_futures_symbol(symbol)
        if not self._settings.live_trading_enabled:
            return self._dry_run_result("cancel_all_orders", symbol=futures_symbol)
        try:
            result = await self._signed_request(
                "DELETE", "/api/v1/futures/allOpenOrders", {"symbol": futures_symbol}
            )
            return OrderResult(success=True, is_live=True, raw=result)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to cancel orders for %s", futures_symbol)
            return OrderResult(success=False, is_live=True, error=str(exc))

    async def aclose(self) -> None:
        await self._client.aclose()
