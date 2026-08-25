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
