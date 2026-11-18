"""Small text helpers shared by storage, correction and verification."""
from __future__ import annotations

import re
import unicodedata

_TR_MAP = str.maketrans({
    "ı": "i", "İ": "i", "I": "i",
    "ş": "s", "Ş": "s",
    "ğ": "g", "Ğ": "g",
    "ü": "u", "Ü": "u",
    "ö": "o", "Ö": "o",
    "ç": "c", "Ç": "c",
    "â": "a", "Â": "a", "î": "i", "Î": "i", "û": "u", "Û": "u",
    "’": "'", "‘": "'", "“": '"', "”": '"',
})


def ascii_fold(s: str) -> str:
    """Lowercase and map Turkish letters to their ASCII base, so that
    'Işık', 'ışık' and 'isik' all compare equal."""
    s = unicodedata.normalize("NFC", s).translate(_TR_MAP).lower()
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


_WORD_RE = re.compile(r"[^\W_]+(?:['’][^\W_]+)*", re.UNICODE)


def words(s: str) -> list[str]:
    """Words of s with punctuation dropped, original spelling kept."""
    return _WORD_RE.findall(s)


def fold_words(s: str) -> list[str]:
    return [ascii_fold(w) for w in words(s)]


def one_line(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()
