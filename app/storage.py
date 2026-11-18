"""The library: one Markdown file per book (library/books/), person
(library/people/) or topic (library/topics/). The files are the only storage;
this module keeps an in-memory index of them and re-reads any file that
changes on disk.

Each card in a file is a quote (someone's words) or a fact (a piece of
information to remember)."""
from __future__ import annotations

import os
import re
import secrets
import threading
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

import yaml

from .text import ascii_fold, one_line

KIND_DIRS = {"book": "books", "person": "people", "topic": "topics"}
CARD_TYPES = ("quote", "fact")
STATUSES = ("yes", "likely", "reader-posted", "suggestion", "candidate", "not found", "unchecked")

# Order in which quote fields are written below the quote text.
FIELD_ORDER = ("id", "type", "page", "source", "keyword", "tags", "note", "favorite", "lang",
               "added", "verified", "evidence", "suggestion", "original")
EDITABLE = ("text", "type", "page", "source", "keyword", "tags", "note", "favorite", "lang",
            "verified", "evidence", "suggestion", "original")

_FIELD_RE = re.compile(r"^[-*]\s+([a-z_]+)\s*:\s*(.*)$")
_SEPARATORS = {"---", "***", "___"}


@dataclass
class Quote:
    id: str
    text: str
    type: str = "quote"      # "quote" or "fact"
    page: str = ""
    source: str = ""
    keyword: str = ""
    tags: list[str] = field(default_factory=list)
    note: str = ""
    favorite: bool = False
    lang: str = ""
    added: str = ""
    verified: str = "unchecked"
    evidence: str = ""
    suggestion: str = ""
    original: str = ""


@dataclass
class Source:
    kind: str            # "book", "person" or "topic"
    slug: str            # file name without .md
    meta: dict
    quotes: list[Quote] = field(default_factory=list)

    @property
    def title(self) -> str:
        return str(self.meta.get(_name_key(self.kind)) or self.slug)

    @property
    def author(self) -> str:
        """Who the words belong to: the person, or the book's author. A topic has none."""
        if self.kind == "person":
            return self.title
        return str(self.meta.get("author") or "") if self.kind == "book" else ""

    def summary(self) -> dict:
        return {"kind": self.kind, "slug": self.slug, "title": self.title,
                "author": self.author, "meta": self.meta, "count": len(self.quotes)}


def _name_key(kind: str) -> str:
    """The header field that names a file: a book has a title, people and topics a name."""
    return "title" if kind == "book" else "name"


# ---------------------------------------------------------------- file format

def file_stem(name: str) -> str:
    name = unicodedata.normalize("NFC", name or "")
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', " ", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:120] or "Untitled"


def clean_tags(value) -> list[str]:
    if isinstance(value, str):
        value = value.split(",")
    out: list[str] = []
    for t in value or []:
        t = one_line(str(t)).strip("#").lower()
        if t and t not in out:
            out.append(t)
    return out


def _to_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "yes", "1", "y", "evet")


def parse(text: str) -> tuple[dict, list[dict]]:
    """Split a library file into its header and a list of raw quote dicts.
    Forgiving on purpose, because the files may be edited by hand."""
    lines = text.replace("\r\n", "\n").split("\n")
    meta: dict = {}
    body = lines
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                try:
                    loaded = yaml.safe_load("\n".join(lines[1:i]))
                    meta = loaded if isinstance(loaded, dict) else {}
                except yaml.YAMLError:
                    meta = {}
                body = lines[i + 1:]
                break

    blocks: list[list[str]] = [[]]
    for ln in body:
        if ln.strip() in _SEPARATORS:
            blocks.append([])
        else:
            blocks[-1].append(ln)

    quotes = []
    for block in blocks:
        quoted: list[str] = []
        plain: list[str] = []
        fields: dict = {}
        for ln in block:
            s = ln.strip()
            m = _FIELD_RE.match(s)
            if s.startswith(">"):
                quoted.append(re.sub(r"^>\s?", "", s))
            elif m and m.group(1) in FIELD_ORDER:
                fields[m.group(1)] = m.group(2).strip()
            elif s and not s.startswith("#"):
                plain.append(s)
        body_text = "\n".join(quoted).strip()
        loose = " ".join(plain).strip()
        if not body_text:          # a quote typed by hand without the "> " marker
            body_text, loose = loose, ""
        if not body_text:
            continue
        if loose and not fields.get("note"):
            fields["note"] = loose
        fields["text"] = body_text
        quotes.append(fields)
    return meta, quotes


def quote_from_raw(raw: dict) -> Quote:
    verified = raw.get("verified", "unchecked").strip().lower() or "unchecked"
    card_type = raw.get("type", "quote").strip().lower()
    return Quote(
        id=raw.get("id", "").strip(),
        text=raw["text"],
        type=card_type if card_type in CARD_TYPES else "quote",
        page=raw.get("page", ""),
        source=raw.get("source", ""),
        keyword=raw.get("keyword", ""),
        tags=clean_tags(raw.get("tags", "")),
        note=raw.get("note", ""),
        favorite=_to_bool(raw.get("favorite", False)),
        lang=raw.get("lang", "").lower(),
        added=raw.get("added", ""),
        verified=verified if verified in STATUSES else "unchecked",
        evidence=raw.get("evidence", ""),
        suggestion=raw.get("suggestion", ""),
        original=raw.get("original", ""),
    )


def dump(src: Source) -> str:
    meta = dict(src.meta)
    if src.kind != "book":
        meta.pop("type", None)
        meta = {"type": src.kind, **meta}
    head = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True,
                          default_flow_style=False, width=1000).strip()
    out = [f"---\n{head}\n---\n"]
    for q in src.quotes:
        lines = [f"> {ln}".rstrip() for ln in q.text.strip().split("\n")]
        lines.append("")
        for name in FIELD_ORDER:
            value = getattr(q, name)
            if name == "tags":
                value = ", ".join(value)
            elif name == "favorite":
                value = "true" if value else ""
            elif name == "type":
                value = "" if value == "quote" else value      # only facts are marked
            else:
                value = one_line(str(value))
            if name == "verified" and q.type == "fact":
                continue                       # facts are not checked against sources
            if value or name in ("id", "added", "verified"):
                lines.append(f"- {name}: {value}")
        lines += ["", "---", ""]
        out.append("\n".join(lines))
    return "\n".join(out)


# -------------------------------------------------------------------- library

class Library:
    def __init__(self, root: Path):
        self.root = Path(root)
        self._lock = threading.RLock()
        self._sources: dict[tuple[str, str], Source] = {}
        self._mtimes: dict[tuple[str, str], float] = {}
        for sub in KIND_DIRS.values():
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        self.refresh()

    # -- disk ---------------------------------------------------------------

    def path(self, kind: str, slug: str) -> Path:
        return self.root / KIND_DIRS[kind] / f"{slug}.md"

    def refresh(self) -> None:
        """Pick up files that were added, edited or removed outside the app."""
        with self._lock:
            seen = set()
            for kind, sub in KIND_DIRS.items():
                for p in (self.root / sub).glob("*.md"):
                    key = (kind, unicodedata.normalize("NFC", p.stem))
                    seen.add(key)
                    mtime = p.stat().st_mtime
                    if self._mtimes.get(key) != mtime:
                        self._load(kind, key[1], p)
            for key in [k for k in self._sources if k not in seen]:
                del self._sources[key]
                self._mtimes.pop(key, None)

    def _load(self, kind: str, slug: str, p: Path) -> None:
        meta, raws = parse(p.read_text(encoding="utf-8"))
        meta.pop("type", None)
        meta.setdefault(_name_key(kind), slug)
        src = Source(kind, slug, meta, [quote_from_raw(r) for r in raws])
        self._sources[(kind, slug)] = src
        self._mtimes[(kind, slug)] = p.stat().st_mtime
        # Quotes added by hand have no id (or a copied one): give them one.
        dirty = False
        taken = {q.id for s in self._sources.values() if s is not src for q in s.quotes}
        for q in src.quotes:
            if not q.id or q.id in taken:
                q.id = self._new_id(taken)
                dirty = True
            taken.add(q.id)
            if not q.added:
                q.added = date.fromtimestamp(p.stat().st_mtime).isoformat()
                dirty = True
        if dirty:
            self._save(src)

    def _save(self, src: Source) -> None:
        p = self.path(src.kind, src.slug)
        tmp = p.with_suffix(".md.tmp")
        tmp.write_text(dump(src), encoding="utf-8")
        os.replace(tmp, p)
        self._sources[(src.kind, src.slug)] = src
        self._mtimes[(src.kind, src.slug)] = p.stat().st_mtime

    def _new_id(self, taken: set[str] | None = None) -> str:
        if taken is None:
            taken = {q.id for s in self._sources.values() for q in s.quotes}
        while True:
            qid = "q" + secrets.token_hex(3)
            if qid not in taken:
                return qid

    # -- sources ------------------------------------------------------------

    def sources(self) -> list[Source]:
        with self._lock:
            return sorted(self._sources.values(), key=lambda s: ascii_fold(s.title))

    def source(self, kind: str, slug: str) -> Source:
        with self._lock:
            try:
                return self._sources[(kind, unicodedata.normalize("NFC", slug))]
            except KeyError:
                raise KeyError(f"No {kind} called {slug!r}") from None

    def _free_slug(self, kind: str, meta: dict, keep: str | None = None) -> str:
        base = file_stem(str(meta.get(_name_key(kind)) or ""))
        candidates = [base]
        if kind == "book" and meta.get("author"):
            candidates.append(file_stem(f"{base} ({meta['author']})"))
        candidates += [f"{base} {n}" for n in range(2, 100)]
        existing = {ascii_fold(s) for (k, s) in self._sources if k == kind and s != keep}
        for c in candidates:
            if ascii_fold(c) not in existing:
                return c
        raise ValueError("Could not find a free file name")

    def create_source(self, kind: str, meta: dict) -> Source:
        if kind not in KIND_DIRS:
            raise ValueError("kind must be 'book', 'person' or 'topic'")
        meta = _clean_meta(meta)
        key = _name_key(kind)
        if not str(meta.get(key) or "").strip():
            raise ValueError(f"A {kind} needs a {key}")
        with self._lock:
            same = self.find_source(kind, str(meta[key]), str(meta.get("author") or ""))
            if same:
                raise ValueError(f"{same.title} is already in the library")
            src = Source(kind, self._free_slug(kind, meta), meta, [])
            self._save(src)
            return src

    def find_source(self, kind: str, title: str, author: str = "") -> Source | None:
        """An existing book with this title (and author, if both have one),
        or an existing person with this name."""
        for s in self._sources.values():
            if s.kind != kind or ascii_fold(s.title) != ascii_fold(title.strip()):
                continue
            if kind == "book" and author and s.author and ascii_fold(s.author) != ascii_fold(author.strip()):
                continue
            return s
        return None

    def update_source(self, kind: str, slug: str, meta: dict) -> Source:
        with self._lock:
            src = self.source(kind, slug)
            merged = _clean_meta({**src.meta, **meta})
            key = _name_key(kind)
            if not str(merged.get(key) or "").strip():
                raise ValueError(f"A {kind} needs a {key}")
            old_slug, old_title = src.slug, src.title
            src.meta = merged
            if str(merged[key]) != old_title:      # renamed: the file follows the name
                new_slug = self._free_slug(kind, merged, keep=old_slug)
                if new_slug != old_slug:
                    old_path = self.path(kind, old_slug)
                    del self._sources[(kind, old_slug)]
                    self._mtimes.pop((kind, old_slug), None)
                    src.slug = new_slug
                    self._save(src)
                    if old_path.exists() and old_path != self.path(kind, new_slug):
                        old_path.unlink()
                    return src
            self._save(src)
            return src

    def delete_source(self, kind: str, slug: str) -> None:
        with self._lock:
            src = self.source(kind, slug)
            self.path(kind, src.slug).unlink(missing_ok=True)
            del self._sources[(kind, src.slug)]
            self._mtimes.pop((kind, src.slug), None)

    # -- quotes -------------------------------------------------------------

    def _find(self, qid: str) -> tuple[Source, Quote]:
        for s in self._sources.values():
            for q in s.quotes:
                if q.id == qid:
                    return s, q
        raise KeyError(f"No quote with id {qid!r}")

    def quote(self, qid: str) -> dict:
        with self._lock:
            return _view(*self._find(qid))

    def add_quote(self, kind: str, slug: str, fields: dict) -> dict:
        with self._lock:
            src = self.source(kind, slug)
            text = str(fields.get("text") or "").strip()
            if not text:
                raise ValueError("The quote is empty")
            q = Quote(id=self._new_id(), text=text, added=date.today().isoformat())
            _apply(q, fields)
            src.quotes.append(q)
            self._save(src)
            return _view(src, q)

    def update_quote(self, qid: str, fields: dict) -> dict:
        with self._lock:
            src, q = self._find(qid)
            if "text" in fields and not str(fields["text"] or "").strip():
                raise ValueError("The quote is empty")
            _apply(q, fields)
            self._save(src)
            return _view(src, q)

    def delete_quote(self, qid: str) -> None:
        with self._lock:
            src, q = self._find(qid)
            src.quotes.remove(q)
            self._save(src)

    def move_quote(self, qid: str, kind: str, slug: str) -> dict:
        with self._lock:
            src, q = self._find(qid)
            dst = self.source(kind, slug)
            if dst is not src:
                src.quotes.remove(q)
                dst.quotes.append(q)
                self._save(src)
                self._save(dst)
            return _view(dst, q)

    def quotes(self, kind: str | None = None, slug: str | None = None, tag: str | None = None,
               name: str | None = None, favorite: bool | None = None, verified: str | None = None,
               q: str | None = None, card_type: str | None = None) -> list[dict]:
        """Quotes matching every given filter, newest first."""
        with self._lock:
            needle = ascii_fold(q) if q else None
            who = ascii_fold(name) if name else None
            out = []
            for s in self._sources.values():
                if kind and s.kind != kind:
                    continue
                if slug and s.slug != unicodedata.normalize("NFC", slug):
                    continue
                if who and ascii_fold(s.author) != who:
                    continue
                for i, quote in enumerate(s.quotes):
                    if tag and tag.lower() not in quote.tags:
                        continue
                    if card_type and quote.type != card_type:
                        continue
                    if favorite is not None and quote.favorite != favorite:
                        continue
                    if verified and quote.verified != verified:
                        continue
                    if needle:
                        hay = ascii_fold(" ".join([quote.text, quote.keyword, quote.note,
                                                   " ".join(quote.tags), s.title, s.author]))
                        if needle not in hay:
                            continue
                    out.append((quote.added, i, _view(s, quote)))
            out.sort(key=lambda t: (t[0], t[1]), reverse=True)
            return [v for _, _, v in out]

    def tags(self) -> list[dict]:
        with self._lock:
            counts: dict[str, int] = {}
            for s in self._sources.values():
                for quote in s.quotes:
                    for t in quote.tags:
                        counts[t] = counts.get(t, 0) + 1
            return [{"tag": t, "count": c} for t, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]

    def names(self) -> list[dict]:
        """Book authors and people merged by name, so one person appears once."""
        with self._lock:
            merged: dict[str, dict] = {}
            for s in self._sources.values():
                if not s.author:
                    continue
                entry = merged.setdefault(ascii_fold(s.author), {"name": s.author, "count": 0, "books": 0})
                entry["count"] += len(s.quotes)
                if s.kind == "book":
                    entry["books"] += 1
                else:
                    entry["name"] = s.author      # prefer the person file's spelling
            return sorted(merged.values(), key=lambda e: ascii_fold(e["name"]))


def _clean_meta(meta: dict) -> dict:
    out = {}
    for k, v in meta.items():
        if k == "type" or v is None:
            continue
        if isinstance(v, str):
            v = one_line(v)
            if not v:
                continue
            if k in ("year", "born", "died", "pages") and re.fullmatch(r"-?\d{1,4}", v):
                v = int(v)
        out[k] = v
    return out


def _apply(q: Quote, fields: dict) -> None:
    for name in EDITABLE:
        if name not in fields or fields[name] is None:
            continue
        value = fields[name]
        if name == "tags":
            q.tags = clean_tags(value)
        elif name == "favorite":
            q.favorite = _to_bool(value)
        elif name == "type":
            if value not in CARD_TYPES:
                raise ValueError("type must be 'quote' or 'fact'")
            q.type = value
        elif name == "text":
            q.text = "\n".join(ln.rstrip() for ln in str(value).strip().split("\n"))
        elif name == "verified":
            if value not in STATUSES:
                raise ValueError(f"verified must be one of {', '.join(STATUSES)}")
            q.verified = value
        elif name == "lang":
            q.lang = str(value).strip().lower()[:5]
        else:
            setattr(q, name, one_line(str(value)))


def _view(src: Source, q: Quote) -> dict:
    d = asdict(q)
    d.update(kind=src.kind, slug=src.slug, title=src.title, author=src.author,
             year=src.meta.get("year"), cover=src.meta.get("cover"))
    return d
