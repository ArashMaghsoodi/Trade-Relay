from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

import httpx

from trade_relay.toobit_client import ToobitClient


class TestToobitClient(unittest.IsolatedAsyncioTestCase):
    async def test_futures_ping_uses_reachable_toobit_api_gateway(self):
        response = httpx.Response(
            200,
            json={},
            request=httpx.Request("GET", "https://api.toobit.com/api/v1/ping"),
        )
        client = ToobitClient("key", "secret", "https://api.toobit.com", "https://api.toobit.com")

        with patch("trade_relay.toobit_client.httpx.AsyncClient") as async_client:
            async_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=response)

            result = await client.ping_futures()

        self.assertEqual(result, {})
        request = async_client.return_value.__aenter__.return_value.get.call_args
        self.assertEqual(request.args[0], "https://api.toobit.com/api/v1/ping")

    async def test_signed_account_uses_toobit_access_key_header(self):
        response = httpx.Response(
            200,
            json={"totalWalletBalance": "10"},
            request=httpx.Request("GET", "https://api.toobit.com/api/v1/account"),
        )
        client = ToobitClient("key", "secret", "https://api.toobit.com", "https://api.toobit.com")

        with patch("trade_relay.toobit_client.httpx.AsyncClient") as async_client:
            async_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=response)

            result = await client.account_info_futures()

        self.assertEqual(result["totalWalletBalance"], "10")
        request = async_client.return_value.__aenter__.return_value.get.call_args
        self.assertEqual(request.args[0], "https://api.toobit.com/api/v1/account")
        self.assertEqual(request.kwargs["headers"], {"X-BB-APIKEY": "key"})


if __name__ == "__main__":
    unittest.main()