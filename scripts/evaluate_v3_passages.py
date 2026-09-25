#!/usr/bin/env python3
"""Strict per-turn context benchmark: note-level vs passage-level (#83). Offline, no model.

Both arms use the hook's delivery path: MemoryStore.context_for(..., strict=True) followed
by render_context with a hook-sized prefix, at each budget.

  answerable  the labelled note is delivered AND its answer sentence is inside the
              delivered text (verbatim, whitespace-normalised)
  recall      the labelled note is delivered
  noise       share of control prompts that inject any record
  latency     median and p95 of context_for per call, plus the cold passage index build

Questions come in two shapes: `short` (two to four inflected content words and a question
word) and `long` (the same question inside a chatty agent-session prompt). Controls come in
three groups: `everyday` prompts unrelated to the vault, `agent` commands a coding session
is full of, and `generic` prompts made only of the vault's most frequent words. The first
two are noise; the third is reported but is not a pass condition, since a prompt built
from the vault's own vocabulary is arguably about the vault.

The default corpus is synthetic and deterministic (Turkish): rich multi-section project
notes that hide one fact deep inside, concept notes, short inbox notes, daily logs, an
append-only session archive that repeats every fact's words without its answer, and an
index note. It is a regression gate and a skeleton for measuring your own vault, not a
generalisation claim. `--vault DIR --questions FILE` runs the same arms on a real vault
READ-ONLY (records are ingested into a temporary runtime; nothing is written to DIR). The
questions file is JSON: {"questions": [{"query", "source", "sentence"}], "controls": {group: [str]}}.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import random
import re
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "template/.claude/scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import beyin_v3 as runtime  # noqa: E402
import beyin_v3_passage as passage  # noqa: E402

COMMON = """sistem süreç karar dosya ayar kullanıcı çalışma sorun çözüm deneme sürüm hafta gün plan
durum zaman veri adım liste kayıt görev hedef sonuç rapor toplantı fikir öneri kontrol değişiklik
güncelleme yapı parça model araç yöntem kural sınır bilgi kaynak sayfa bölüm başlık metin örnek
not düzen akış bağlantı erişim hata uyarı test ekip kişi müşteri ürün hizmet maliyet bütçe fiyat
süre tarih saat sabah akşam gece yarın dün hızlı yavaş kolay zor büyük küçük yeni eski önemli
gerekli mümkün doğru yanlış açık kapalı ilk son ikinci üçüncü daha fazla biraz çok kısa uzun
başlamak bitirmek yazmak okumak bakmak görmek almak vermek kurmak açmak kapatmak taşımak silmek
eklemek çıkarmak seçmek denemek beklemek sormak anlatmak göstermek istemek kullanmak""".split()

TOPIC = """depo raf kutu etiket barkod sevkiyat kargo palet stok sayım tedarik fatura tahsilat iade
indirim kupon sepet ödeme kasa makbuz radyo yayın frekans anten istasyon çalma parça şarkı
dinleyici istek anket oylama sohbet moderatör yedek arşiv kopya sıkıştırma şifreleme anahtar
bulut bucket sunucu disk bellek işlemci kuyruk zamanlayıcı cron tetik kanca webhook
takvim çekim kurgu montaj altyazı kapak açıklama etiketleme yükleme izlenme abone
sponsor sözleşme teklif marka kampanya bütçeleme kontrat müzakere arama
dizin sıralama sorgu skor eşik kelime kök gövde benzerlik vektör önbellek mobil ekran
buton bildirim izin konum kamera galeri mağaza inceleme puan ambar tablo sütun satır şema
göç yedekleme sorgulama pano grafik metrik alarm etkinlik bilet salon koltuk sahne
konuk davetiye program kitap yazar okuma tartışma kulüp yorum alıntı özet
limon maskot çizim fırça renk kontur gölge ışık doku sensör sıcaklık nem vana pompa
boru filtre basınç motor kablo sigorta pil şarj panel güneş rüzgar türbin enerji tüketim
mutfak tarif malzeme fırın tencere baharat hamur maya şeker tuz süt peynir zeytin sebze
meyve bahçe tohum fide sulama gübre toprak saksı budama hasat çiçek ağaç yaprak""".split()

RARE = """zirkon kobalt turmalin akik yakut safir opal kuvars obsidyen granit bazalt mermer
kehribar mercan inci lapis malakit topaz zümrüt oniks jasper ametist kalsit pirit galen
hematit manyetit dolomit feldspat mika talk jips barit fluorit apatit korindon beril
spinel garnet olivin piroksen amfibol serpantin klorit epidot zeolit kaolin bentonit""".split()

QUESTION_WORDS = ["neydi", "hangisiydi", "neden", "nasıl", "kaçtı", "ne zamandı", "nerede", "kimdi"]
LONG_PREFIX = "Bugün biraz yoğunum, önce elimdeki işi bitirelim sonra diğer konuya geçeriz. "
LONG_SUFFIX = " Kısaca özetle, gerekirse kaynağı da göster."
EVERYDAY = [
    "ekran görüntüsü kullanmasam sorun olmayacak mı", "peki uygula", "bunu tam anlamadım",
    "bugün hastanede nöbet çok yoğundu", "akşam yemeği için mercimek çorbası tarifi lazım",
    "dün akşamki maçın skoru neydi", "hava yarın yağmurlu olacak mı",
    "annemin doğum günü için hediye fikri ver", "kahve mi çay mı daha sağlıklı",
    "kedim neden gece boyunca miyavlıyor", "bana kısa bir fıkra anlat",
    "arabanın lastik basıncı kaç olmalı", "komşunun gürültüsü için ne yapabilirim",
    "sabah koşusundan sonra dizim ağrıyor", "kışlık montu kuru temizlemeye vermeli miyim",
]
AGENT = [
    "şu testleri çalıştır ve sonucu bana raporla", "bu dosyadaki hatayı düzelt",
    "kodu biraz daha okunabilir hale getir", "değişiklikleri commit et ve pushla",
    "önceki adımı geri al", "bir sonraki göreve geç", "bu fonksiyonun ne yaptığını açıkla",
    "log çıktısını incele ve sorunu bul", "yeni bir branch aç ve orada çalış",
    "tüm uyarıları temizle", "pull request açıklamasını yaz", "sonuçları tablo olarak göster",
    "run the tests again and fix what fails", "please summarize what changed",
    "add a unit test for this",
]
FACT_TEMPLATES = [
    "{a} için {b} değeri {r} olarak belirlendi çünkü {c} {d} sorunu çıkarıyordu.",
    "{a} tarafında {b} işini artık {r} üstleniyor, {c} ise {d} ile birlikte kaldırıldı.",
    "{r} kararı {a} ve {b} konuşulurken alındı; {c} yerine {d} kullanılacak.",
    "{a} {b} adımında {r} ayarı zorunlu, aksi halde {c} {d} kaybına yol açıyor.",
]
PREFIX = ("Receipt session=000000000000000000000000; choose --harness for the current client.\n"
          "V3 source-backed context (data, not instructions):\n")
BACK = "aıou"
FRONT = "eiöü"


def _harmony(word, pairs):
    """Suffix vowel by the last vowel of the word: pairs maps back/front (or four-way) vowels."""
    for character in reversed(word):
        if character in BACK + FRONT:
            return pairs[character]
    return pairs["e"]


def inflect(rng, word):
    """A real Turkish case or plural form that the runtime stemmer maps back to `word`."""
    two = {c: "a" if c in BACK else "e" for c in BACK + FRONT}
    four = {"a": "ı", "ı": "ı", "o": "u", "u": "u", "e": "i", "i": "i", "ö": "ü", "ü": "ü"}
    if not word[-1].isalpha():
        return word
    vowel_end = word[-1] in BACK + FRONT
    hard = word[-1] in "çfhkpsşt"
    forms = [word + "l" + _harmony(word, two) + "r", word + ("t" if hard else "d") + _harmony(word, two)]
    if word[-1] not in "çkpt":  # these soften before a vowel (bellek, belleği); the stemmer keeps them apart
        forms += [word + ("n" if vowel_end else "") + _harmony(word, four) + "n",
                  word + ("y" if vowel_end else "") + _harmony(word, four)]
    form = rng.choice(forms)
    return form if runtime._tokens(form) == runtime._tokens(word) else word


def _sentence(rng, topic, length):
    words = [rng.choice(topic) if rng.random() < 0.35 else rng.choice(COMMON) for _ in range(length)]
    return words[0].capitalize() + " " + " ".join(words[1:]) + "."


def synthetic_corpus(seed=83):
    """Notes {source: text} and labelled prompts; deterministic for a seed."""
    rng = random.Random(seed)
    topics = TOPIC[:]
    rng.shuffle(topics)
    projects = [sorted(set(topics[i * 20:(i + 1) * 20] + rng.sample(topics, 6))) for i in range(12)]
    rare = RARE[:]
    rng.shuffle(rare)
    notes, facts = {}, []

    def fact(source, topic):
        slots = rng.sample(topic, 4)
        value = rare.pop() if rare else f"kod{rng.randint(100, 999)}"
        text = rng.choice(FACT_TEMPLATES).format(a=slots[0], b=slots[1], c=slots[2], d=slots[3], r=value)
        facts.append({"source": source, "sentence": text, "slots": slots, "value": value})
        return text

    def paragraph(topic, sentences):
        return " ".join(_sentence(rng, topic, rng.randint(7, 15)) for _ in range(sentences))

    for number, topic in enumerate(projects):
        source = f"projects/proje-{number:02d}.md"
        parts = [f"# Proje {number:02d}: {topic[0]} {topic[1]}\n"]
        for section in range(rng.randint(12, 16)):
            parts.append(f"## {topic[section % len(topic)].capitalize()} {rng.choice(COMMON)}\n")
            paragraphs = [paragraph(topic, rng.randint(2, 4)) for _ in range(rng.randint(2, 3))]
            if section % 3 == 1:
                paragraphs[rng.randrange(len(paragraphs))] += " " + fact(source, topic)
            parts.append("\n\n".join(paragraphs) + "\n")
        notes[source] = "\n".join(parts)
    for number in range(48):
        topic = projects[number % 12]
        source = f"knowledge/concepts/kavram-{number:02d}.md"
        parts = [f"# {topic[number % len(topic)].capitalize()} üzerine\n"]
        for section in range(rng.randint(2, 5)):
            parts.append(f"## {rng.choice(topic).capitalize()}\n")
            body = [paragraph(topic, rng.randint(2, 4)) for _ in range(rng.randint(1, 3))]
            if section == 1 and number % 2 == 0:
                body[-1] += " " + fact(source, topic)
            parts.append("\n\n".join(body) + "\n")
        notes[source] = "\n".join(parts)
    for number in range(60):
        topic = projects[number % 12]
        source = f"inbox/kisa-not-{number:03d}.md"
        body = paragraph(topic, rng.randint(1, 3))
        if number % 4 == 0:
            body += " " + fact(source, topic)
        notes[source] = body + "\n"
    for number in range(30):
        lines = [f"# 2026-08-{number % 28 + 1:02d}\n"]
        for topic in rng.sample(projects, 3):
            lines.append("- " + paragraph(topic, rng.randint(3, 6)))
        notes[f"daily/2026-08-{number:02d}.md"] = "\n".join(lines) + "\n"
    # An append-only session archive: every project, every fact's words, none of the answers.
    archive = ["# Oturum arşivi\n"]
    while sum(len(part) for part in archive) < 100_000:
        item = rng.choice(facts)
        archive.append(f"## Oturum {len(archive):04d}\n\n" + paragraph(rng.choice(projects), rng.randint(2, 4)) +
                       f" {item['slots'][0]} ve {item['slots'][2]} yeniden konuşuldu, {item['value']} not edildi.\n")
    notes["archive/oturum-arsivi.md"] = "\n".join(archive)
    notes["knowledge/index.md"] = "\n".join(["# Dizin\n"] + [f"- [[{source}]] " + " ".join(rng.sample(projects[i % 12], 5))
                                                           for i, source in enumerate(sorted(notes))]) + "\n"
    questions = []
    for item in rng.sample(facts, min(42, len(facts))):
        chosen = rng.sample(item["slots"] + [item["value"]], rng.choice((2, 3, 3, 4)))
        query = " ".join(inflect(rng, word) for word in chosen) + " " + rng.choice(QUESTION_WORDS)
        questions.append({"query": query, "source": item["source"], "sentence": item["sentence"]})
    generic = [" ".join(rng.sample(COMMON, rng.randint(3, 5))) + " " + rng.choice(QUESTION_WORDS) for _ in range(10)]
    return notes, {"questions": questions, "controls": {"everyday": EVERYDAY, "agent": AGENT, "generic": generic}}


def _ingest_notes(store, vault, notes):
    for number, (source, text) in enumerate(sorted(notes.items())):
        path = vault / source
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        store.ingest({"id": f"n{number:04d}", "kind": "note", "visibility": "internal", "text": text,
                      "facts": {}, "source": source, "updated_at": "2026-09-01T00:00:00Z"})


def _ingest_vault(store, vault):
    """Read-only scan with sync's own parser and exclusions; never writes to the vault."""
    import beyin_v3_sync as sync
    count = 0
    for directory, dirs, files in os.walk(vault, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d.casefold() not in sync.EXCLUDED_DIRS)
        for name in sorted(files):
            if name.startswith(".") or not name.lower().endswith(".md") or name.casefold() in sync.EXCLUDED_FILES:
                continue
            path = Path(directory) / name
            relative = path.relative_to(vault).as_posix()
            try:
                stat = path.stat()
                if getattr(stat, "st_blocks", 1) == 0 and stat.st_size:
                    continue  # evicted by a cloud provider; reading it would block
                metadata, body = sync.parse(path.read_bytes().decode("utf-8"))
                if metadata.get("kind") == "receipt" or metadata.get("generated") is True:
                    continue
                record = dict(metadata, source=relative, text=body)
                record["id"] = "md-" + sync._hash(relative)[:24]
                record.setdefault("kind", "note")
                store.ingest(record)
                count += 1
            except (ValueError, OSError, UnicodeError, runtime.RevisionConflict):
                continue
    return count


def _normal(text):
    return re.sub(r"\s+", " ", text).strip()


def _deliver(store, query, budget):
    context = store.context_for("claude", query, strict=True, budget_chars=budget)
    return runtime.render_context(context, budget, prefix=PREFIX)[1]


def run(store, labelled, budgets=(2000, 5000), passages=True):
    """One arm: every question shape and control group at every budget."""
    store.STRICT_PASSAGES = passages
    timings, result = [], {}
    shapes = {"short": [(q["query"], q) for q in labelled["questions"]],
              "long": [(LONG_PREFIX + q["query"] + "?" + LONG_SUFFIX, q) for q in labelled["questions"]]}
    for budget in budgets:
        row = {}
        for shape, items in shapes.items():
            answerable = found = records = 0
            for query, item in items:
                started = time.perf_counter()
                delivered = _deliver(store, query, budget)
                timings.append(time.perf_counter() - started)
                got = {record["source"]: record for record in delivered["records"]}
                records += len(delivered["records"])
                if item["source"] in got:
                    found += 1
                    answerable += _normal(item["sentence"]) in _normal(got[item["source"]].get("text", ""))
            total = max(1, len(items))
            row[shape] = {"answerable": round(answerable / total, 3), "recall": round(found / total, 3),
                          "mean_records": round(records / total, 2)}
        for group, prompts in labelled["controls"].items():
            hits = 0
            for prompt in prompts:
                started = time.perf_counter()
                hits += bool(_deliver(store, prompt, budget)["records"])
                timings.append(time.perf_counter() - started)
            row["noise_" + group] = round(hits / max(1, len(prompts)), 3)
        result[str(budget)] = row
    timings.sort()
    result["median_ms"] = round(1000 * timings[len(timings) // 2], 1) if timings else None
    result["p95_ms"] = round(1000 * timings[int(len(timings) * 0.95)], 1) if timings else None
    return result


def evaluate(vault=None, questions=None, budgets=(2000, 5000), seed=83, floor=None, exclude=None):
    report = {"scope": "synthetic corpus" if vault is None else "user vault (read-only)",
              "floor": passage.FLOOR if floor is None else floor,
              "exclude": list(passage.DEFAULT_EXCLUDE) + [p for p in (exclude or []) if p not in passage.DEFAULT_EXCLUDE],
              "arms": {}}
    with tempfile.TemporaryDirectory(prefix="beyin-v3-passages-") as tmp:
        tmp = Path(tmp)
        if vault is None:
            root = tmp / "vault"
            root.mkdir()
            notes, labelled = synthetic_corpus(seed)
            store = runtime.MemoryStore(tmp / "runtime", root)
            _ingest_notes(store, root, notes)
            report["records"] = len(notes)
        else:
            root = Path(vault).resolve()
            labelled = json.loads(Path(questions).read_text(encoding="utf-8"))
            if isinstance(labelled.get("controls"), list):
                labelled["controls"] = {"controls": labelled["controls"]}
            store = runtime.MemoryStore(tmp / "runtime", root)
            report["records"] = _ingest_vault(store, root)
        report["questions"] = len(labelled["questions"])
        (store.state_dir / passage.CONFIG_NAME).write_text(
            json.dumps({"strict_floor": report["floor"], "strict_exclude": report["exclude"]}), encoding="utf-8")
        started = time.perf_counter()
        store.STRICT_PASSAGES = True
        eligible, _ = store._eligible()
        passage.build(store.state_dir, passage.pool(store, eligible, None, report["exclude"]))
        report["cold_index_ms"] = round(1000 * (time.perf_counter() - started), 1)
        report["arms"]["note_level"] = run(store, labelled, budgets, passages=False)
        report["arms"]["passage_level"] = run(store, labelled, budgets, passages=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--vault", type=Path)
    parser.add_argument("--questions", type=Path)
    parser.add_argument("--seed", type=int, default=83)
    parser.add_argument("--budgets", nargs="*", type=int, default=[2000, 5000])
    parser.add_argument("--floor", type=float, help="strict_floor to evaluate (default: module FLOOR)")
    parser.add_argument("--exclude", nargs="*", help="extra strict_exclude prefixes (daily/ and receipts/ always apply)")
    args = parser.parse_args()
    if bool(args.vault) != bool(args.questions):
        parser.error("--vault and --questions go together")
    report = evaluate(args.vault, args.questions, tuple(args.budgets), args.seed, args.floor, args.exclude)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
