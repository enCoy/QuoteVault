"""Compare local models on the jobs Quote Vault gives them.

    .venv/bin/python scripts/eval_models.py gemma4:e4b qwen3.5:9b aya-expanse:8b

For each model it reports how many test sentences come out exactly right after
the app's own safety check, how long a sentence takes, and prints the tags and
translations so they can be judged by eye."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import crosscheck, llm, textfix          # noqa: E402
from app.config import SETTINGS                   # noqa: E402

# (what was typed, what it should become). Lowercase and without capitals on purpose:
# only letters are judged.
TURKISH = [
    ("hayatta en hakiki mursit ilimdir", "hayatta en hakiki mürşit ilimdir"),
    ("dunyanin en guzel seyi ozgurluktur", "dünyanın en güzel şeyi özgürlüktür"),
    ("insan yalniz dogar yalniz olur", "insan yalnız doğar yalnız ölür"),
    ("cocuklugumun gectigi sehir artik cok degismis", "çocukluğumun geçtiği şehir artık çok değişmiş"),
    ("butun mutlu aileler birbirine benzer, her mutsuz ailenin ise kendine ozgu bir mutsuzlugu vardir",
     "bütün mutlu aileler birbirine benzer, her mutsuz ailenin ise kendine özgü bir mutsuzluğu vardır"),
    ("okudugum her kitap bana yeni bir dunyanin kapisini acti", "okuduğum her kitap bana yeni bir dünyanın kapısını açtı"),
    ("gercek yalnizlik insanin kendi icinde hissettigi bosluktur", "gerçek yalnızlık insanın kendi içinde hissettiği boşluktur"),
    ("sabahin kor karanliginda uyanip yola ciktik", "sabahın kör karanlığında uyanıp yola çıktık"),
    ("bir insani sevmekle baslar her sey", "bir insanı sevmekle başlar her şey"),
    ("ne icindeyim zamanin ne de busbutun disinda", "ne içindeyim zamanın ne de büsbütün dışında"),
    ("yasamak bir agac gibi tek ve hur ve bir orman gibi kardescesine", "yaşamak bir ağaç gibi tek ve hür ve bir orman gibi kardeşçesine"),
    ("en guzel deniz henuz gidilmemis olandir", "en güzel deniz henüz gidilmemiş olandır"),
    ("kitaplar olmasaydi cocuklugum cok sikici gecerdi", "kitaplar olmasaydı çocukluğum çok sıkıcı geçerdi"),
    ("dusunuyorum, oyleyse varim", "düşünüyorum, öyleyse varım"),
    ("ogrenmek icin sormak, anlamak icin dinlemek gerekir", "öğrenmek için sormak, anlamak için dinlemek gerekir"),
    ("aci cekmeden olgunlasilmaz", "acı çekmeden olgunlaşılmaz"),
    ("bu acidan bakinca her sey farkli gorunuyor", "bu açıdan bakınca her şey farklı görünüyor"),
    ("yasli adam gecen kis oldu ve koy sessizlige gomuldu", "yaşlı adam geçen kış öldü ve köy sessizliğe gömüldü"),
    ("gozlerimi kaparim, vazifemi yaparim", "gözlerimi kaparım, vazifemi yaparım"),
    ("kitap okumak insani ozgurlestirir", "kitap okumak insanı özgürleştirir"),
    # typos as well as missing letters
    ("hersey cok guzle olacak", "her şey çok güzel olacak"),
    ("yanliz kalmak bazen iyi gelir", "yalnız kalmak bazen iyi gelir"),
    # already correct: must come back unchanged
    ("ne içindeyim zamanın, ne de büsbütün dışında.", "ne içindeyim zamanın, ne de büsbütün dışında."),
]
ENGLISH = [
    ("the unexamined life is not worht living", "the unexamined life is not worth living"),
    ("we sufer more often in imagination than in reality", "we suffer more often in imagination than in reality"),
    ("it is not death that a man should fear, but he should fear never beginning to live.",
     "it is not death that a man should fear, but he should fear never beginning to live."),
]
TRANSLATE = [
    "Tarihin en büyük sahtekârlığı tarım devrimidir.",
    "Ruh, düşüncelerinin rengine boyanır.",
    "İnsan özgür olmaya mahkûmdur.",
]


def lower_tr(s: str) -> str:
    return s.replace("İ", "i").lower().strip()


def run(model: str) -> None:
    SETTINGS["llm_model"] = model
    llm._state["checked"] = 0
    if not llm.available():
        print(f"\n## {model}: not installed\n")
        return
    print(f"\n## {model}")
    textfix.process("isinma turu", "tr", [])                 # load the model before timing
    right = wrong = 0
    started = time.time()
    tags_seen = []
    for lang, cases in (("tr", TURKISH), ("en", ENGLISH)):
        for typed, want in cases:
            r = textfix.process(typed, lang, ["solitude", "time", "freedom", "knowledge", "love"])
            got = lower_tr(r["corrected"])
            tags_seen.append((typed[:44], r["tags"]))
            if got == lower_tr(want):
                right += 1
            else:
                wrong += 1
                print(f"   WRONG  {got}\n   wanted {want}{'  (a change was refused)' if r['refused'] else ''}")
    total = right + wrong
    print(f"   correct: {right}/{total}   {(time.time() - started) / total:.1f}s per sentence")
    print("   tags:")
    for text, tags in tags_seen[:8]:
        print(f"     {text:<46} {', '.join(tags)}")
    print("   translations:")
    for t in TRANSLATE:
        print(f"     {t}  ->  {crosscheck.translate(t)}")


if __name__ == "__main__":
    names = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--no-think" in sys.argv:              # for models that reason out loud before answering
        SETTINGS["llm_think"] = False
    for name in names:
        run(name)
