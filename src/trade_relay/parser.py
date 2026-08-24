from __future__ import annotations

import re
from typing import Optional

from .models import EventType, Side, SignalEvent, SignalSetup

_SYMBOL_SIDE_RE = re.compile(r"#\s*([A-Z0-9_\-]+/[A-Z0-9_\-]+)\s*\((LONG|SHORT)\)", re.IGNORECASE)
_SYMBOL_ONLY_RE = re.compile(r"#\s*([A-Z0-9_\-]+/[A-Z0-9_\-]+)", re.IGNORECASE)
_SIDE_RE = re.compile(r"\b(LONG|SHORT)\b", re.IGNORECASE)
_FLOAT_RE = r"([0-9]+(?:\.[0-9]+)?)"
# Delimiter between two numeric values in provider messages can be '-', '~', '–', emojis,
# replacement chars (�), or mixed symbols.
_RANGE_DELIM_RE = r"[^0-9\n]{1,12}"


def _to_side(value: str) -> Side:
    return Side(value.upper())


def _extract_symbol_and_side(text: str) -> tuple[Optional[str], Optional[Side]]:
    match = _SYMBOL_SIDE_RE.search(text)
    if match:
        symbol = match.group(1).upper()
        side = _to_side(match.group(2))
        return symbol, side

    symbol_match = _SYMBOL_ONLY_RE.search(text)
    side_match = _SIDE_RE.search(text)
    symbol = symbol_match.group(1).upper() if symbol_match else None
    side = _to_side(side_match.group(1)) if side_match else None
    return symbol, side


def parse_signal_message(text: str) -> Optional[SignalEvent]:
    cleaned = (
        text.replace("\u200f", " ")
        .replace("\u200e", " ")
        .replace("\ufeff", " ")
    )
    upper = cleaned.upper()

    if "ENTRY 1 ACHIEVED" in upper:
        symbol, side = _extract_symbol_and_side(cleaned)
        if symbol and side:
            return SignalEvent(event_type=EventType.ENTRY_TRIGGER, symbol=symbol, side=side)
        return None

    target_match = re.search(r"TARGET\s*\(\s*([0-9]+)\s*\)\s*REACHED", upper)
    if target_match:
        symbol, side = _extract_symbol_and_side(cleaned)
        if symbol and side:
            return SignalEvent(
                event_type=EventType.TARGET_HIT,
                symbol=symbol,
                side=side,
                target_number=int(target_match.group(1)),
            )
        return None

    if "STOPPED OUT" in upper:
        symbol, side = _extract_symbol_and_side(cleaned)
        if symbol and side:
            return SignalEvent(event_type=EventType.STOPPED_OUT, symbol=symbol, side=side)
        return None

    setup = parse_setup_message(cleaned)
    if setup:
        return SignalEvent(event_type=EventType.SETUP, symbol=setup.symbol, side=setup.side, setup=setup)

    return None


def parse_setup_message(text: str) -> Optional[SignalSetup]:
    symbol, side = _extract_symbol_and_side(text)
    if not symbol or not side:
        return None

    upper = text.upper()
    # Provider marks setup posts with #Signal at the bottom; this is a strong setup hint.
    has_signal_tag = "#SIGNAL" in upper

    entry_match = re.search(
        rf"ENTER\s*PRICE\s*:\s*{_FLOAT_RE}\s*{_RANGE_DELIM_RE}\s*{_FLOAT_RE}",
        text,
        re.IGNORECASE,
    )
    tp1_match = re.search(rf"TP\s*1\s*:\s*{_FLOAT_RE}", text, re.IGNORECASE)
    tp2_match = re.search(rf"TP\s*2\s*:\s*{_FLOAT_RE}", text, re.IGNORECASE)
    tp3_match = re.search(rf"TP\s*3\s*:\s*{_FLOAT_RE}", text, re.IGNORECASE)
    sl_match = re.search(rf"STOP\s*LOSS\s*:\s*{_FLOAT_RE}", text, re.IGNORECASE)

    # For robustness: setup must always include #Signal and core numeric fields.
    if not (has_signal_tag and entry_match and tp1_match and tp2_match and sl_match):
        return None

    entry_low = float(entry_match.group(1))
    entry_high = float(entry_match.group(2))

    return SignalSetup(
        symbol=symbol,
        side=side,
        entry_low=min(entry_low, entry_high),
        entry_high=max(entry_low, entry_high),
        tp1=float(tp1_match.group(1)),
        tp2=float(tp2_match.group(1)),
        tp3=float(tp3_match.group(1)) if tp3_match else None,
        stop_loss=float(sl_match.group(1)),
    )
