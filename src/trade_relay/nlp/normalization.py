"""
Normalization helpers for bilingual (English/Persian) signal text.

Keep this module dumb and purely textual — it should never make judgment
calls about what a message *means*, only make it easier for the classifier
and parser downstream to recognize patterns consistently.
"""
from __future__ import annotations

import re

_PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_ARABIC_INDIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
_ASCII_DIGITS = "0123456789"

_DIGIT_TRANSLATION = str.maketrans(
    _PERSIAN_DIGITS + _ARABIC_INDIC_DIGITS,
    _ASCII_DIGITS + _ASCII_DIGITS,
)

# Persian trading vocabulary -> canonical English tokens. This is
# intentionally a flat keyword map rather than anything clever — new
# provider phrasing gets added here as it's observed, and every new entry is
# a one-line, auditable change.
_PERSIAN_KEYWORD_MAP: dict[str, str] = {
    "لانگ": "LONG",
    "خرید": "LONG",
    "شورت": "SHORT",
    "فروش": "SHORT",
    "سل": "SHORT",
    "اهرم": "LEVERAGE",
    "لوریج": "LEVERAGE",
    "حد سود": "TP",
    "تارگت": "TP",
    "هدف": "TP",
    "حد ضرر": "SL",
    "استاپ": "SL",
    "استاپ لاس": "SL",
    "ببندید": "CLOSE",
    "بستن": "CLOSE",
    "ببند": "CLOSE",
    "انتقال حد ضرر": "MOVE_SL",
    "حد ضرر رو ببرید": "MOVE_SL",
    "نقطه سر به سر": "BREAKEVEN",
    "سر به سر": "BREAKEVEN",
    # common asset names — extend as new symbols show up in the channel
    "بیتکوین": "BTC",
    "اتریوم": "ETH",
    "اتر": "ETH",
    "سولانا": "SOL",
    "ریپل": "XRP",
    "دوج": "DOGE",
    "بایننس کوین": "BNB",
}


def normalize_digits(text: str) -> str:
    """Convert Persian/Arabic-Indic digits to ASCII digits."""
    return text.translate(_DIGIT_TRANSLATION)


def normalize_keywords(text: str) -> str:
    """Replace known Persian trading vocabulary with canonical English
    tokens, longest phrase first so multi-word phrases aren't shadowed by
    single-word ones (e.g. 'حد ضرر' before a lone 'ضرر')."""
    result = text
    for phrase in sorted(_PERSIAN_KEYWORD_MAP, key=len, reverse=True):
        if phrase in result:
            result = result.replace(phrase, _PERSIAN_KEYWORD_MAP[phrase])
    return result


def normalize(text: str) -> str:
    """Full normalization pipeline applied before classification/parsing."""
    text = normalize_digits(text)
    text = normalize_keywords(text)
    # collapse whitespace, keep case as-is (symbols are usually uppercase already)
    text = re.sub(r"\s+", " ", text).strip()
    return text
