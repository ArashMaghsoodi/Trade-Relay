"""
Deterministic, regex/keyword based extraction of signal fields from the
aggregated text of a Trade Session (original message + all its replies,
concatenated in chronological order).

This runs BEFORE the AI parser and is preferred whenever it manages to
extract a complete, confident result — it's cheap, fast, has no external
dependency, and its behavior is exactly auditable. The AI parser is only
consulted as a fallback for text this can't confidently handle (see
nlp/ai_parser.py).
"""
from __future__ import annotations

import re

from trade_relay.domain.enums import ManagementAction, Side
from trade_relay.domain.models import ManagementEvent, ParsedSignal
from trade_relay.nlp.normalization import normalize

# A conservative, explicit allow-list keeps "symbol recognition" honest —
# extend as needed. Doing this instead of "any 2-10 uppercase letters" avoids
# false-positive symbols from acronyms in chat noise.
KNOWN_QUOTE_SUFFIXES = ("USDT", "USD", "USDC")

_SIDE_RE = re.compile(r"\b(LONG|SHORT)\b", re.IGNORECASE)
_SYMBOL_RE = re.compile(r"\b([A-Z]{2,10})(USDT|USD|USDC)?\b")
_LEVERAGE_RE = re.compile(r"\b(?:LEVERAGE|LEV|CROSS|ISOLATED)\D{0,4}(\d{1,3})x?\b", re.IGNORECASE)
_WALLET_PCT_RE = re.compile(r"\b(\d{1,3}(?:\.\d+)?)\s*%")
_SL_RE = re.compile(r"\bSL\D{0,4}(\d+(?:\.\d+)?)\b", re.IGNORECASE)
_TP_RE = re.compile(r"\bTP\d?\D{0,4}(\d+(?:\.\d+)?)\b", re.IGNORECASE)
_ENTRY_RE = re.compile(r"\bENTRY\D{0,4}(\d+(?:\.\d+)?)\b", re.IGNORECASE)

_MANAGEMENT_CLOSE_ALL_RE = re.compile(r"\bclose\b(?!\s*\d{1,3}\s*%)", re.IGNORECASE)
_MANAGEMENT_CLOSE_PARTIAL_RE = re.compile(r"\bclose\s*(\d{1,3})\s*%", re.IGNORECASE)
_MANAGEMENT_MOVE_SL_BE_RE = re.compile(r"\bmove\s+sl\s+to\s+be\b|\bsl\s+to\s+be\b|\bBREAKEVEN\b", re.IGNORECASE)
_MANAGEMENT_MOVE_SL_RE = re.compile(r"\b(?:move\s+sl|MOVE_SL)\D{0,6}(\d+(?:\.\d+)?)\b", re.IGNORECASE)
_MANAGEMENT_SECOND_ENTRY_RE = re.compile(r"\bsecond entry\b", re.IGNORECASE)


def _extract_symbol(text: str) -> str | None:
    for match in _SYMBOL_RE.finditer(text):
        token, suffix = match.group(1), match.group(2)
        if token in {"LONG", "SHORT", "SL", "TP", "LEV", "BE"}:
            continue
        return token + (suffix or "")
    return None


def parse_signal(aggregated_text: str) -> ParsedSignal:
    """Parse a Trade Session's full aggregated text (all messages/replies
    concatenated) into whatever structured fields can be confidently
    extracted right now. Missing fields are left None — the caller decides
    whether that's enough to reach READY."""

    normalized = normalize(aggregated_text)

    side_match = _SIDE_RE.search(normalized)
    side = Side(side_match.group(1).upper()) if side_match else None

    symbol = _extract_symbol(normalized)

    lev_match = _LEVERAGE_RE.search(normalized)
    leverage = int(lev_match.group(1)) if lev_match else None

    wallet_match = _WALLET_PCT_RE.search(normalized)
    wallet_percent = float(wallet_match.group(1)) if wallet_match else None

    sl_match = _SL_RE.search(normalized)
    stop_loss = float(sl_match.group(1)) if sl_match else None

    take_profits = [float(m.group(1)) for m in _TP_RE.finditer(normalized)]

    entry_match = _ENTRY_RE.search(normalized)
    entry_price = float(entry_match.group(1)) if entry_match else None

    fields_found = sum(
        1 for v in (symbol, side, stop_loss, take_profits, leverage) if v
    )
    # Confidence scales with how many distinct fields were confidently
    # extracted via explicit keyword anchors (SL/TP/LEV), not just "a number
    # appeared somewhere" — this keeps the confidence signal meaningful for
    # the risk engine's MIN_PARSER_CONFIDENCE gate.
    confidence = min(1.0, fields_found / 5.0 + (0.2 if symbol and side else 0.0))

    return ParsedSignal(
        symbol=symbol,
        side=side,
        leverage=leverage,
        wallet_percent=wallet_percent,
        stop_loss=stop_loss,
        take_profits=take_profits,
        entry_price=entry_price,
        confidence=confidence,
        source="rule",
        raw_text=aggregated_text,
    )


def parse_management(text: str) -> ManagementEvent:
    """Parse a single position-management message. Unlike signals, these are
    usually self-contained in one message rather than aggregated."""

    normalized = normalize(text)
    symbol = _extract_symbol(normalized)

    if _MANAGEMENT_SECOND_ENTRY_RE.search(normalized):
        # Per spec: some management actions are intentionally ignored.
        return ManagementEvent(action=ManagementAction.SECOND_ENTRY, symbol=symbol, raw_text=text)

    if _MANAGEMENT_MOVE_SL_BE_RE.search(normalized):
        return ManagementEvent(action=ManagementAction.MOVE_SL_BREAKEVEN, symbol=symbol, raw_text=text)

    move_sl_match = _MANAGEMENT_MOVE_SL_RE.search(normalized)
    if move_sl_match:
        return ManagementEvent(
            action=ManagementAction.MOVE_SL,
            symbol=symbol,
            value=float(move_sl_match.group(1)),
            raw_text=text,
        )

    partial_match = _MANAGEMENT_CLOSE_PARTIAL_RE.search(normalized)
    if partial_match:
        return ManagementEvent(
            action=ManagementAction.CLOSE_PARTIAL,
            symbol=symbol,
            value=float(partial_match.group(1)),
            raw_text=text,
        )

    if _MANAGEMENT_CLOSE_ALL_RE.search(normalized):
        return ManagementEvent(action=ManagementAction.CLOSE_ALL, symbol=symbol, raw_text=text)

    return ManagementEvent(action=ManagementAction.UNRECOGNIZED, symbol=symbol, raw_text=text)
