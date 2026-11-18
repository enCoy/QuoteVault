import pytest

from app.storage import Library, dump, parse


@pytest.fixture
def lib(tmp_path):
    return Library(tmp_path)


def test_book_round_trip(lib, tmp_path):
    book = lib.create_source("book", {"title": "Tutunamayanlar", "author": "Oğuz Atay", "year": "1972",
                                      "isbn": "9789754700114", "language": "tr"})
    q = lib.add_quote("book", book.slug, {
        "text": "Birinci satır.\nİkinci satır.", "page": "142", "keyword": "yalnızlık",
        "tags": ["Solitude", "identity", "solitude"], "note": "my own\nthought", "favorite": True, "lang": "tr",
    })
    path = tmp_path / "books" / "Tutunamayanlar.md"
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "author: Oğuz Atay" in text and "year: 1972" in text
    assert "isbn: '9789754700114'" in text
    assert "> Birinci satır.\n> İkinci satır." in text
    assert "- tags: solitude, identity" in text
    assert "- note: my own thought" in text

    again = Library(tmp_path)                       # fresh read from disk
    got = again.quote(q["id"])
    assert got["text"] == "Birinci satır.\nİkinci satır."
    assert got["tags"] == ["solitude", "identity"]
    assert got["favorite"] is True and got["page"] == "142" and got["verified"] == "unchecked"
    assert got["title"] == "Tutunamayanlar" and got["author"] == "Oğuz Atay" and got["year"] == 1972
    assert dump(again.source("book", "Tutunamayanlar")) == text      # stable when rewritten


def test_person_file(lib, tmp_path):
    p = lib.create_source("person", {"name": "Marcus Aurelius", "born": "121", "died": "180"})
    lib.add_quote("person", p.slug, {"text": "The soul becomes dyed with the colour of its thoughts.",
                                     "source": "Meditations, Book 5"})
    text = (tmp_path / "people" / "Marcus Aurelius.md").read_text(encoding="utf-8")
    assert text.startswith("---\ntype: person\nname: Marcus Aurelius\nborn: 121\n")
    assert "- source: Meditations, Book 5" in text


def test_hand_edited_file_is_read(tmp_path):
    (tmp_path / "books").mkdir()
    (tmp_path / "books" / "Kürk Mantolu Madonna.md").write_text(
        "---\ntitle: Kürk Mantolu Madonna\nauthor: Sabahattin Ali\n---\n\n"
        "# my notes\n\n"
        "> Quote with the marker.\n- page: 12\n- tags: love , Loss\n\n---\n\n"
        "A quote typed with no marker at all.\n\n---\n",
        encoding="utf-8")
    lib = Library(tmp_path)
    quotes = lib.quotes(kind="book", slug="Kürk Mantolu Madonna")
    assert {q["text"] for q in quotes} == {"Quote with the marker.", "A quote typed with no marker at all."}
    assert all(q["id"].startswith("q") and q["added"] for q in quotes)
    assert len({q["id"] for q in quotes}) == 2
    marked = next(q for q in quotes if q["page"] == "12")
    assert marked["tags"] == ["love", "loss"]
    # ids were written back, so they stay the same on the next start
    assert {q["id"] for q in Library(tmp_path).quotes()} == {q["id"] for q in quotes}


def test_edit_on_disk_is_picked_up(lib, tmp_path):
    book = lib.create_source("book", {"title": "Sapiens", "author": "Yuval Noah Harari"})
    q = lib.add_quote("book", book.slug, {"text": "Old wording."})
    path = tmp_path / "books" / "Sapiens.md"
    path.write_text(path.read_text(encoding="utf-8").replace("Old wording.", "New wording."), encoding="utf-8")
    import os
    os.utime(path, (path.stat().st_atime, path.stat().st_mtime + 5))
    lib.refresh()
    assert lib.quote(q["id"])["text"] == "New wording."
    path.unlink()
    lib.refresh()
    assert lib.sources() == []


def test_filters_tags_and_names(lib):
    b = lib.create_source("book", {"title": "Tehlikeli Oyunlar", "author": "Oğuz Atay"})
    p = lib.create_source("person", {"name": "Oğuz Atay"})
    o = lib.create_source("person", {"name": "Seneca"})
    lib.add_quote("book", b.slug, {"text": "Işık yok.", "tags": "loneliness, play"})
    lib.add_quote("person", p.slug, {"text": "Ben buradayım.", "tags": "loneliness", "favorite": True})
    lib.add_quote("person", o.slug, {"text": "Life is long if you know how to use it.", "tags": "time"})

    assert len(lib.quotes(name="oguz atay")) == 2                 # book author + person merged
    assert [q["text"] for q in lib.quotes(tag="time")] == ["Life is long if you know how to use it."]
    assert [q["text"] for q in lib.quotes(favorite=True)] == ["Ben buradayım."]
    assert [q["text"] for q in lib.quotes(q="isik")] == ["Işık yok."]   # search ignores Turkish accents
    assert lib.tags()[0] == {"tag": "loneliness", "count": 2}
    names = {n["name"]: n for n in lib.names()}
    assert names["Oğuz Atay"]["count"] == 2 and names["Oğuz Atay"]["books"] == 1
    assert set(names) == {"Oğuz Atay", "Seneca"}


def test_move_update_delete(lib, tmp_path):
    p = lib.create_source("person", {"name": "Albert Camus"})
    b = lib.create_source("book", {"title": "The Myth of Sisyphus", "author": "Albert Camus"})
    q = lib.add_quote("person", p.slug, {"text": "One must imagine Sisyphus happy."})
    moved = lib.move_quote(q["id"], "book", b.slug)
    assert moved["kind"] == "book" and moved["title"] == "The Myth of Sisyphus"
    assert lib.quotes(kind="person") == []
    upd = lib.update_quote(q["id"], {"verified": "yes", "evidence": "Wikiquote", "tags": ["absurd"]})
    assert upd["verified"] == "yes" and upd["tags"] == ["absurd"]
    with pytest.raises(ValueError):
        lib.update_quote(q["id"], {"verified": "maybe"})
    with pytest.raises(ValueError):
        lib.update_quote(q["id"], {"text": "  "})
    lib.delete_quote(q["id"])
    with pytest.raises(KeyError):
        lib.quote(q["id"])


def test_rename_and_name_clashes(lib, tmp_path):
    a = lib.create_source("book", {"title": "Notes", "author": "Ann"})
    with pytest.raises(ValueError):
        lib.create_source("book", {"title": "notes", "author": "Ann"})       # same book again
    b = lib.create_source("book", {"title": "Notes", "author": "Bob"})        # same title, other author
    assert b.slug == "Notes (Bob)"
    lib.add_quote("book", a.slug, {"text": "kept"})
    renamed = lib.update_source("book", a.slug, {"title": "What is: a/b?", "year": "2001"})
    assert renamed.slug == "What is a b" and renamed.meta["year"] == 2001
    assert not (tmp_path / "books" / "Notes.md").exists()
    assert (tmp_path / "books" / "What is a b.md").exists()
    assert [q["text"] for q in lib.quotes(slug="What is a b")] == ["kept"]


def test_parse_ignores_broken_header():
    meta, quotes = parse("---\ntitle: [unclosed\n---\n> still here\n")
    assert meta == {} and quotes[0]["text"] == "still here"


def test_facts_and_topics(lib, tmp_path):
    topic = lib.create_source("topic", {"name": "World War II", "description": "1939–1945"})
    book = lib.create_source("book", {"title": "Sapiens", "author": "Yuval Noah Harari"})
    fact = lib.add_quote("topic", topic.slug, {"text": "World War II began in 1939.", "type": "fact", "tags": "history"})
    lib.add_quote("book", book.slug, {"text": "Wheat domesticated us.", "tags": "history"})
    lib.add_quote("book", book.slug, {"text": "Homo sapiens appeared about 300,000 years ago.", "type": "fact"})

    text = (tmp_path / "topics" / "World War II.md").read_text(encoding="utf-8")
    assert text.startswith("---\ntype: topic\nname: World War II\n") and "- type: fact" in text
    assert "- type:" not in (tmp_path / "books" / "Sapiens.md").read_text(encoding="utf-8").split("---")[2]  # quotes are unmarked

    again = Library(tmp_path)
    assert again.quote(fact["id"])["type"] == "fact" and again.quote(fact["id"])["author"] == ""
    assert {q["text"] for q in again.quotes(card_type="fact")} == {
        "World War II began in 1939.", "Homo sapiens appeared about 300,000 years ago."}
    assert [q["text"] for q in again.quotes(card_type="quote")] == ["Wheat domesticated us."]
    assert len(again.quotes(card_type="fact", tag="history")) == 1
    assert [n["name"] for n in again.names()] == ["Yuval Noah Harari"]          # a topic is not an author
    changed = again.update_quote(fact["id"], {"type": "quote"})
    assert changed["type"] == "quote"
    with pytest.raises(ValueError):
        again.update_quote(fact["id"], {"type": "rumour"})
