from app import tagging
from app.textfix import detect_lang, merge_safe
from app.verify import compare, probes


# ---- language detection ---------------------------------------------------

def test_detects_turkish_typed_without_turkish_letters():
    assert detect_lang("Hayatta en hakiki mursit ilimdir") == "tr"
    assert detect_lang("insan ne kadar cok sey bilirse o kadar yalniz kalir") == "tr"
    assert detect_lang("Gözlerimi kaparım, vazifemi yaparım") == "tr"
    assert detect_lang("The unexamined life is not worth living") == "en"
    assert detect_lang("We suffer more often in imagination than in reality") == "en"
    # no common words to go by: decided by word shape and by how many words gain Turkish letters
    assert detect_lang("sabahin kor karanliginda uyanip yola ciktik") == "tr"
    assert detect_lang("gozlerimi kaparim, vazifemi yaparim") == "tr"
    assert detect_lang("Know thyself") == "en"
    assert detect_lang("Fortune favors the bold") == "en"


# ---- correction safety check ----------------------------------------------

def test_accepts_restored_turkish_letters():
    out, refused = merge_safe("Dunyanin en guzel seyi ozgurluktur", "Dünyanın en güzel şeyi özgürlüktür")
    assert out == "Dünyanın en güzel şeyi özgürlüktür" and not refused


def test_accepts_small_typos_and_joined_words():
    out, refused = merge_safe("hersey cok guzle olacak", "her şey çok güzel olacak")
    assert out == "her şey çok güzel olacak" and not refused
    out, refused = merge_safe("Teh unexamined life is not worht living", "The unexamined life is not worth living")
    assert out == "The unexamined life is not worth living" and not refused


def test_refuses_replaced_added_or_dropped_words():
    out, refused = merge_safe("hayat cok guzel", "ölüm çok güzel")
    assert out == "hayat çok güzel" and refused            # accents taken, the swapped word is not
    out, refused = merge_safe("insan yalnizdir", "insan her zaman yalnızdır")
    assert out == "insan yalnızdır" and refused
    out, refused = merge_safe("ben ve sen buradayiz", "ben buradayız")
    assert out == "ben ve sen buradayız" and refused
    out, refused = merge_safe("o da geldi", "o de geldi")       # two-letter words are never changed
    assert out == "o da geldi" and refused


def test_refuses_a_translation_or_rewrite():
    original = "hayatta en hakiki mursit ilimdir"
    out, refused = merge_safe(original, "The truest guide in life is science")
    assert out == original and refused


def test_keeps_line_breaks_and_spacing():
    out, _ = merge_safe("birinci satir\nikinci  satir", "birinci satır ikinci satır")
    assert out == "birinci satır\nikinci  satır"


# ---- comparing a quote with a source --------------------------------------

def test_exact_match_inside_longer_source_text():
    m = compare("The unexamined life is not worth living",
                "It is Socrates who said, “The unexamined life is not worth living.” This course offers")
    assert m.exact and m.same_spelling and m.coverage == 1.0


def test_misquote_gets_the_source_wording():
    m = compare("Be the change you want to see in the world.",
                "Gandhi: Be the change that you wish to see in the world. — often quoted")
    assert not m.exact and m.close
    assert m.suggestion == "Be the change that you wish to see in the world."


def test_wrong_last_word_is_replaced_from_the_source():
    m = compare("The unexamined life is not worth having", "the unexamined life is not worth living for a man")
    assert not m.exact and m.close
    assert m.suggestion == "The unexamined life is not worth living"      # keeps the card's capital


def test_accent_difference_is_exact_but_not_same_spelling():
    m = compare("Hayatta en hakiki mursit ilimdir", "“Hayatta en hakiki mürşit ilimdir” diye söylenen")
    assert m.exact and not m.same_spelling
    assert m.suggestion == "Hayatta en hakiki mürşit ilimdir"


def test_unrelated_text_does_not_match():
    m = compare("The unexamined life is not worth living", "A life of the mind is worth all the trouble in the world")
    assert m is None or not m.close


def test_probes_are_short_phrases_from_different_places():
    text = "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen"
    ps = probes(text)
    assert ps[0] == "one two three four five six seven" and ps[-1].endswith("sixteen") and len(ps) == 3
    assert probes("just three words") == ["just three words"] and probes("too short") == []
    assert probes("the unexamined life is not worth having") == [
        "the unexamined life is not worth having", "the unexamined life is not", "life is not worth having"]


# ---- tags -----------------------------------------------------------------

def test_tags_are_cleaned_and_snapped_to_existing():
    existing = ["solitude", "free will", "books"]
    assert tagging.clean(["Solitude", "#Free Will", "book", "a very long tag that says too much", "time", "love"],
                         existing) == ["solitude", "free will", "books"]
    assert tagging.clean("not a list", existing) == []


# ---- rule-based Turkish letters -------------------------------------------

def test_restore_letters_leaves_typed_turkish_words_and_spacing_alone():
    from app.textfix import restore_letters
    assert restore_letters("dunyanin en guzel seyi ozgurluktur") == "dünyanın en güzel şeyi özgürlüktür"
    assert restore_letters("birinci satir\nikinci  satir") == "birinci satır\nikinci  satır"
    already = "Ne içindeyim zamanın, ne de büsbütün dışında."
    assert restore_letters(already) == already


def test_process_restores_letters_without_the_model(monkeypatch):
    from app import llm, textfix
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: None)
    r = textfix.process("kitap okumak insani ozgurlestirir", "auto", [])
    assert r["lang"] == "tr" and r["corrected"] == "kitap okumak insanı özgürleştirir"
    assert r["changed"] and not r["llm"]
    r = textfix.process("The unexamined life is not worth living", "auto", [])
    assert r["lang"] == "en" and not r["changed"]


def test_shorter_piece_of_the_quote_is_not_a_different_wording():
    m = compare("Be the change you want to see in the world", "”be the change you want to see")
    assert m.close and not m.exact and not m.differs
    m = compare("Be the change you want to see in the world", "be the change we wish to see in the world")
    assert m.differs and not m.exact


def test_snippet_cut_one_word_short_does_not_verify_a_short_quote():
    m = compare("The unexamined life is not worth having", "he said the unexamined life is not worth")
    assert not m.exact and not m.differs
