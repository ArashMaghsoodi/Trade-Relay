"""
Rule-based message classifier.

Deliberately conservative: a message only gets classified as SIGNAL or
POSITION_MANAGEMENT when it matches a recognized pattern with reasonable
confidence. Everything else falls to UNKNOWN and is logged, never acted on.
This mirrors the "never guess" philosophy — the classifier's job is to say
"I don't know" often, not to force a bucket on every message.
"""
from __future__ import annotations

import re

from trade_relay.domain.enums import MessageClass
from trade_relay.domain.models import ClassificationResult
from trade_relay.nlp.normalization import normalize

_SYMBOL_RE = re.compile(r"\b[A-Z]{2,10}(USDT)?\b")
_SIDE_RE = re.compile(r"\b(LONG|SHORT)\b", re.IGNORECASE)
_ENTRY_VERB_RE = re.compile(r"\b(buy|sell|enter)\b", re.IGNORECASE)
_NON_SYMBOL_TOKENS = {"LONG", "SHORT", "SL", "TP", "LEV", "BE", "MOVE_SL", "BREAKEVEN"}


def _has_real_symbol(text: str) -> bool:
    return any(
        match.group(0).rstrip("USDT") not in _NON_SYMBOL_TOKENS and match.group(0) not in _NON_SYMBOL_TOKENS
        for match in _SYMBOL_RE.finditer(text)
    )

_MANAGEMENT_PATTERNS = [
    re.compile(r"\bclose\b", re.IGNORECASE),
    re.compile(r"\bmove\s+sl\b", re.IGNORECASE),
    re.compile(r"\bMOVE_SL\b"),
    re.compile(r"\bBREAKEVEN\b"),
    re.compile(r"\bbe\b", re.IGNORECASE),  # "move SL to BE"
    re.compile(r"\bsecond entry\b", re.IGNORECASE),
    re.compile(r"\bpartial\b", re.IGNORECASE),
]

_GENERAL_CHAT_HINTS = [
    "good morning", "good evening", "gm", "nice trade", "how are you",
    "thanks", "thank you", "congrats", "well done", "gn",
]


def classify(text: str) -> ClassificationResult:
    normalized = normalize(text)
    lower = normalized.lower()

    # Position management takes priority per spec ("higher priority than
    # ordinary signals") when both kinds of pattern could plausibly match.
    for pattern in _MANAGEMENT_PATTERNS:
        if pattern.search(normalized):
            return ClassificationResult(
                message_class=MessageClass.POSITION_MANAGEMENT,
                confidence=0.85,
                reason=f"matched management pattern: {pattern.pattern}",
            )

    if any(hint in lower for hint in _GENERAL_CHAT_HINTS):
        return ClassificationResult(
            message_class=MessageClass.GENERAL_CHAT,
            confidence=0.8,
            reason="matched general chat hint list",
        )

    has_side = bool(_SIDE_RE.search(normalized))
    has_symbol = _has_real_symbol(normalized)
    has_entry_verb = bool(_ENTRY_VERB_RE.search(normalized))

    if has_side and (has_symbol or has_entry_verb):
        confidence = 0.9 if (has_side and has_symbol) else 0.6
        return ClassificationResult(
            message_class=MessageClass.SIGNAL,
            confidence=confidence,
            reason="side keyword plus symbol/entry verb",
        )

    # A short reply carrying only numeric fields (leverage/SL/TP) with no
    # side/symbol of its own is still plausibly part of an active signal —
    # the session manager decides that based on reply-chain context, not the
    # classifier. We surface it as SIGNAL with low confidence so it's at
    # least considered for attachment to an existing session; the risk
    # engine's confidence gate is what actually protects against misuse.
    if re.search(r"\b(lev|leverage|sl|tp|cross|isolated)\b", lower) or re.search(r"\d", normalized):
        if not has_symbol and not has_side and len(normalized) < 40:
            return ClassificationResult(
                message_class=MessageClass.SIGNAL,
                confidence=0.4,
                reason="short numeric-only message, possible follow-up field",
            )

    return ClassificationResult(
        message_class=MessageClass.UNKNOWN,
        confidence=0.0,
        reason="no recognized pattern matched",
    )
