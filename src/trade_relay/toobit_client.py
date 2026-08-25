from __future__ import annotations

import hmac
import hashlib
import time
from dataclasses import dataclass
from typing import Any

import httpx


class ToobitAPIError(RuntimeError):
    pass


@dataclass(slots=True)
class ToobitClient:
    api_key: str
    api_secret: str
    base_url: str
    futures_base_url: str

    def _signed_params(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        data = dict(params or {})
        data["timestamp"] = int(time.time() * 1000)
        query = "&".join(f"{k}={data[k]}" for k in sorted(data))
        signature = hmac.new(self.api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        data["signature"] = signature
        return data

    def _headers(self) -> dict[str, str]:
        return {
            "X-MBX-APIKEY": self.api_key,
        }

    async def ping_futures(self) -> dict[str, Any]:
        url = f"{self.futures_base_url.rstrip('/')}/fapi/v1/ping"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json() if resp.content else {"ok": True}

    async def account_info_futures(self) -> dict[str, Any]:
        url = f"{self.futures_base_url.rstrip('/')}/fapi/v1/account"
        params = self._signed_params()
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, params=params, headers=self._headers())
        if resp.status_code >= 400:
            raise ToobitAPIError(f"Toobit account_info error {resp.status_code}: {resp.text}")
        return resp.json()

    async def position_risk_futures(self) -> list[dict[str, Any]]:
        url = f"{self.futures_base_url.rstrip('/')}/fapi/v1/positionRisk"
        params = self._signed_params()
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, params=params, headers=self._headers())
        if resp.status_code >= 400:
            raise ToobitAPIError(f"Toobit position_risk error {resp.status_code}: {resp.text}")
        data = resp.json()
        if not isinstance(data, list):
            raise ToobitAPIError(f"Unexpected position_risk payload: {type(data).__name__}")
        return data


def extract_summary_snapshot(
    account: dict[str, Any],
    positions: list[dict[str, Any]],
    today_realized_pnl: float = 0.0,
) -> dict[str, Any]:
    total_wallet_balance = float(account.get("totalWalletBalance", 0.0) or 0.0)
    total_unrealized_profit = float(account.get("totalUnrealizedProfit", 0.0) or 0.0)

    open_positions: list[dict[str, Any]] = []
    for row in positions:
        amt = float(row.get("positionAmt", 0.0) or 0.0)
        if amt == 0:
            continue

        symbol = str(row.get("symbol", ""))
        side = "Long" if amt > 0 else "Short"
        leverage = int(float(row.get("leverage", 0) or 0))
        entry_price = float(row.get("entryPrice", 0.0) or 0.0)
        mark_price = float(row.get("markPrice", 0.0) or 0.0)
        isolated_margin = float(row.get("isolatedMargin", 0.0) or 0.0)
        unrealized = float(row.get("unRealizedProfit", 0.0) or 0.0)

        pnl_percent = 0.0
        if isolated_margin > 0:
            pnl_percent = (unrealized / isolated_margin) * 100.0

        open_positions.append(
            {
                "symbol": symbol,
                "side": side,
                "leverage": leverage,
                "entry_price": entry_price,
                "mark_price": mark_price,
                "margin_usdt": isolated_margin,
                "unrealized_pnl": unrealized,
                "unrealized_pnl_percent": pnl_percent,
            }
        )

    return {
        "current_balance": total_wallet_balance,
        "today_realized_pnl": today_realized_pnl,
        "unrealized_pnl_total": total_unrealized_profit,
        "open_positions": open_positions,
    }
