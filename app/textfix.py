"""Language detection, Turkish character restoration and typo fixing.

The model proposes a corrected text; merge_safe() then accepts only changes
that are letter-level (accents, small typos) and keeps the user's own words
everywhere else, so the model can never rewrite a quote."""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from rapidfuzz.distance import DamerauLevenshtein

from . import llm, tagging
from .text import ascii_fold, fold_words

_TR_CHARS = set("çğıöşüÇĞİÖŞÜ")
_TR_WORDS = set("""ve bir bu da de icin ile gibi ama cok daha en ne ben sen biz siz onlar her hic kadar sonra
degil var yok mi mu ki ya olan olarak insan hayat zaman sey kendi diye bile ise hem ancak cunku nasil neden
icinde butun baska simdi bana beni onu onun seni bizim gore once iki olur olmak etmek yapmak eger hep artik
yalniz sadece hicbir herkes kimse cunku fakat veya yani oyle boyle gun yil dunya iyi kotu buyuk kucuk yeni
insanlar seyler zaten belki bazen hala nerede burada orada benim senin kendini kendine degildir vardir
olmayan olmaz olsa oldu olan etti eder ister bilir gelir gider yoktur lazim gerek uzere dogru karsi""".split())
_EN_WORDS = set("""the and of to a in is that it for was with as be on not are this but by from or have an they
which you we all were when there can what who will more if no out so his her he she i my me one do has had
than their them been would our us into only most any how its about those these your never always nothing
every must should could being because through life people time man world without does did too very""".split())


_TR_ENDINGS = ("lar", "ler", "mak", "mek", "dir", "tir", "dur", "tur", "yor", "mis", "mus", "nin", "nun",
               "dan", "den", "tan", "lik", "luk", "siz", "suz", "ini", "ani", "unu", "ine", "ina", "sini",
               "ecek", "acak", "arak", "erek", "ince", "larin", "lerin", "ligi", "lugu", "rir", "lir", "nir",
               "ydi", "mez", "maz", "miz", "muz")
_EN_ENDINGS = ("ing", "tion", "ed", "ly", "ness", "ment", "ous", "ght", "ould")


def detect_lang(text: str) -> str:
    """'tr' or 'en'. Works on Turkish typed without Turkish letters."""
    if any(c in _TR_CHARS for c in text):
        return "tr"
    tr = en = 0
    for w in fold_words(text):
        if w in _TR_WORDS:
            tr += 2
        elif w in _EN_WORDS:
            en += 2
        elif len(w) > 3:        # word shape: Turkish suffixes against English spellings
            tr += w.endswith(_TR_ENDINGS)
            en += w.endswith(_EN_ENDINGS) or "th" in w or any(c in w for c in "wxq")
    if abs(tr - en) > 1:
        return "tr" if tr > en else "en"
    # Too close to call: Turkish text gains Turkish letters in many of its words, English in few.
    old, new = text.split(), restore_letters(text).split()
    changed = sum(o != n for o, n in zip(old, new))
    if len(old) == len(new) and old:
        return "tr" if changed / len(old) >= 0.4 else "en"
    return "tr" if tr > en else "en"


def _join(tokens: list[str]) -> str:
    return ascii_fold("".join(tokens))


def _letter_level(a: list[str], b: list[str]) -> bool:
    """True if replacing tokens a with tokens b is an accent fix or a small typo fix."""
    x, y = _join(a), _join(b)
    if x == y:
        return True
    core_x, core_y = re.sub(r"[\W_]+", "", x), re.sub(r"[\W_]+", "", y)
    if len(core_x) <= 2 and core_x != core_y:      # two-letter words: any change is a new word
        return False
    limit = 1 if len(core_x) <= 7 else 2
    return DamerauLevenshtein.distance(x, y) <= limit


def merge_safe(original: str, proposed: str) -> tuple[str, bool]:
    """Apply the letter-level changes from `proposed` to `original`.
    Returns the merged text and whether any proposed change was refused."""
    parts = re.split(r"(\s+)", original.strip())
    a, seps = parts[0::2], parts[1::2] + [""]
    b = proposed.split()
    if not a or not b:
        return original.strip(), bool(a) != bool(b)
    sm = SequenceMatcher(None, [ascii_fold(t) for t in a], [ascii_fold(t) for t in b], autojunk=False)
    out: list[str] = []
    refused = False
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "insert":
            refused = True
            continue
        take_b = op == "equal" or (op == "replace" and _letter_level(a[i1:i2], b[j1:j2]))
        if take_b and (i2 - i1) == (j2 - j1):
            for k in range(i2 - i1):
                out += [b[j1 + k], seps[i1 + k]]
        elif take_b:                                # words were split or joined
            out += [" ".join(b[j1:j2]), seps[i2 - 1]]
        else:
            refused = True
            for k in range(i1, i2):
                out += [a[k], seps[k]]
    merged = "".join(out).strip()
    # A full stop the model added at the very end is not the user's.
    if merged[-1:] in ".!?…" and original.strip()[-1:] not in ".!?…":
        merged = merged[:-1]
    return merged, refused


def restore_letters(text: str) -> str:
    """Put Turkish letters back with a rule-based library (instant, no model needed).
    Words the user already typed with Turkish letters are left exactly as typed."""
    try:
        from turkish.deasciifier import Deasciifier
    except ImportError:
        return text
    converted, _ = merge_safe(text, Deasciifier(text).convert_to_turkish())
    old, new = re.split(r"(\s+)", text.strip()), re.split(r"(\s+)", converted)
    if len(old) != len(new):
        return text
    return "".join(o if not o.isascii() else n for o, n in zip(old, new))


_SCHEMA = {
    "type": "object",
    "properties": {"corrected": {"type": "string"}, "tags": {"type": "array", "items": {"type": "string"}}},
    "required": ["corrected", "tags"],
}

_FIX = {
    "tr": ("The user gives a Turkish quotation that was typed on an English keyboard. Its Turkish letters "
           "(ç, ğ, ı, İ, ö, ş, ü) were put back automatically, and a few of them may be wrong or missing. "
           "Correct any wrong letters, choosing the word that fits the sentence, and fix obvious spelling "
           "mistakes. Keep every word, the word order and the punctuation exactly as they are. "
           "Never translate, paraphrase, complete or shorten the quotation."),
    "en": ("The user gives an English quotation. Fix obvious spelling mistakes only. Keep every word, "
           "the word order and the punctuation exactly as they are. Never paraphrase, complete or "
           "shorten the quotation."),
}


def process(text: str, lang: str = "auto", existing_tags: list[str] | None = None) -> dict:
    """Detect the language, propose a corrected text and suggest tags."""
    text = text.strip()
    existing_tags = existing_tags or []
    lang = lang if lang in ("tr", "en") else detect_lang(text)
    result = {"lang": lang, "original": text, "corrected": text, "changed": False,
              "refused": False, "tags": [], "llm": False}
    if not text:
        return result
    base = restore_letters(text) if lang == "tr" else text       # works even when the model is off
    result.update(corrected=base, changed=base != text)
    system = (f"{_FIX[lang]} {tagging.INSTRUCTIONS} "
              'Answer with JSON: {"corrected": "<the quotation>", "tags": ["<tag>", ...]}.')
    answer = llm.chat_json(system, f"{tagging.existing_line(existing_tags)}\n\nQuotation:\n{base}", _SCHEMA)
    if answer is None:
        return result
    result["llm"] = True
    proposed = str(answer.get("corrected") or "").strip()
    if proposed:
        merged, refused = merge_safe(base, proposed)
        result.update(corrected=merged, changed=merged != text, refused=refused)
    result["tags"] = tagging.clean(answer.get("tags"), existing_tags)
    return result
