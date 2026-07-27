"""
Optional AI-assisted parsing, used only as a fallback when the deterministic
rule parser can't confidently extract a complete signal.

Important: this module ONLY produces a ParsedSignal (structured data). It
never decides whether to trade — the Risk Engine independently validates
everything this returns, exactly as it validates rule-parsed output, before
anything can execute. If this module is misconfigured, disabled, or the
provider is down, the system simply falls back to "not enough info yet /
UNKNOWN" — never to guessing.

Implemented against a generic OpenAI-compatible chat-completions endpoint so
it can point at any free-tier provider (OpenRouter, Groq, etc.) by just
setting AI_PROVIDER_BASE_URL / AI_PROVIDER_API_KEY / AI_PROVIDER_MODEL.
"""
from __future__ import annotations

import json
import logging
from typing import Protocol

import httpx

from trade_relay.config import Settings
from trade_relay.domain.enums import Side
from trade_relay.domain.models import ParsedSignal

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You extract structured trading-signal fields from raw
Telegram messages (English or Persian, already digit-normalized). Respond
with ONLY a compact JSON object, no prose, no markdown fences, matching:

{"symbol": string|null, "side": "LONG"|"SHORT"|null, "leverage": int|null,
 "wallet_percent": number|null, "stop_loss": number|null,
 "take_profits": number[], "entry_price": number|null,
 "confidence": number between 0 and 1}

Rules:
- If a field genuinely does not appear in the text, use null (or [] for
  take_profits) rather than guessing a value.
- confidence should reflect how certain you are of the fields you DID fill
  in, not overall completeness.
- Never include any field not listed above.
"""


class AIParserProvider(Protocol):
    async def parse(self, aggregated_text: str) -> ParsedSignal: ...


class NullAIParser:
    """Used when AI parsing is disabled — always defers to 'not enough
    info', keeping behavior identical to having no AI parser at all."""

    async def parse(self, aggregated_text: str) -> ParsedSignal:
        return ParsedSignal(confidence=0.0, source="ai_disabled", raw_text=aggregated_text)


class HttpAIParser:
    """Generic OpenAI-compatible chat-completions client."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._client = httpx.AsyncClient(timeout=15.0)

    async def parse(self, aggregated_text: str) -> ParsedSignal:
        if not self._settings.ai_parser_enabled:
            return ParsedSignal(confidence=0.0, source="ai_disabled", raw_text=aggregated_text)

        try:
            response = await self._client.post(
                f"{self._settings.ai_provider_base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {self._settings.ai_provider_api_key}"},
                json={
                    "model": self._settings.ai_provider_model,
                    "messages": [
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": aggregated_text},
                    ],
                    "temperature": 0,
                },
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            data = json.loads(content)
        except Exception:  # noqa: BLE001 - any failure here must degrade to "no info", never raise
            logger.exception("AI parser call failed; treating message as unparsed")
            return ParsedSignal(confidence=0.0, source="ai_error", raw_text=aggregated_text)

        side = None
        if data.get("side") in ("LONG", "SHORT"):
            side = Side(data["side"])

        return ParsedSignal(
            symbol=data.get("symbol"),
            side=side,
            leverage=data.get("leverage"),
            wallet_percent=data.get("wallet_percent"),
            stop_loss=data.get("stop_loss"),
            take_profits=data.get("take_profits") or [],
            entry_price=data.get("entry_price"),
            # Cap AI-reported confidence: it should never single-handedly
            # clear a session on its own say-so as confidently as a full
            # rule-based match would. Adjust only if experience shows
            # otherwise during the observation period.
            confidence=min(0.85, float(data.get("confidence") or 0.0)),
            source="ai",
            raw_text=aggregated_text,
        )

    async def aclose(self) -> None:
        await self._client.aclose()


def build_ai_parser(settings: Settings) -> AIParserProvider:
    if settings.ai_parser_enabled:
        return HttpAIParser(settings)
    return NullAIParser()
