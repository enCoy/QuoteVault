"""Tag suggestions: instructions for the model and clean-up of what it returns."""
from __future__ import annotations

from .text import ascii_fold, one_line

MAX_TAGS = 3

INSTRUCTIONS = (
    "Also choose the 1 to 3 topic tags that clearly say what the quotation is about; fewer is better. "
    "Tags are always English, lowercase, one or two words, even when the quotation is Turkish. "
    "If a tag in the existing list clearly fits, use it instead of inventing a similar one, but never "
    "add a tag just because it is in the list. "
    "Use general themes (for example: solitude, time, freedom), not names of people or books."
)


def existing_line(existing: list[str]) -> str:
    return "Existing tags: " + (", ".join(existing[:150]) if existing else "(none yet)")


def clean(suggested, existing: list[str]) -> list[str]:
    """Lowercase, drop junk, snap near-duplicates onto existing tags, keep at most three."""
    by_fold = {ascii_fold(t): t for t in existing}
    for t in list(existing):                      # plural of an existing tag counts as that tag
        by_fold.setdefault(ascii_fold(t) + "s", t)
        if t.endswith("s"):
            by_fold.setdefault(ascii_fold(t[:-1]), t)
    out: list[str] = []
    for raw in suggested if isinstance(suggested, list) else []:
        t = one_line(str(raw)).strip("#.,;:\"'").lower()
        if not t or len(t) > 30 or len(t.split()) > 3:
            continue
        t = by_fold.get(ascii_fold(t), t)
        if t not in out:
            out.append(t)
    return out[:MAX_TAGS]
