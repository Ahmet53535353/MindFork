"""Hızlandırılmış bir aylık gerçekçi insan kullanımı E2E'si.

Amaç: ürünü komut birim testi gibi sınamak değil, bir insanın bir ay boyunca
projeyi nasıl kullandığını taklit etmek. Persona: Zeynep, serbest web geliştirici,
proje "Kahve Dükkani" (musteri: Demir Kahve). Gunler tek oturumlarla ilerler,
tatil haftasi bos kalir, ay sonunda birikmis dosyalar konsolide edilir.

Zaman hizlandirmasi: gercek kod yolu (kurulu vault + `beyin.py` CLI + hook alt
sureci) bugunun saatinde calisir; her sanal gunun sonunda o gunun uretilmis
artefaktlarinin tarihi geri alinir:

* notlar: `updated_at` desteklenen bir metadata alani oldugu icin olusturma
  aninda verilir (dosya sonradan elle degistirilmez);
* receipt'ler: dosyanin `created_at` alani geri alinir ve yerel state'ten
  silinerek urunun kendi "state reset -> diskten benimse" kurtarma yolu
  kullanilir; `daily/v3/<tarih>.md` projection'i gercekten o sanal tarihe
  duser, sync temiz gecer;
* gunluk log: bloklar `<!-- beyin-session:... -->` isaretine gore gunlere
  bolunur (dosya adlari sanal tarihe yazilir);
* `dream.last_run`: meta verisi elle yazilir (faz-2 mutating window henuz yok;
  kapi mantigi olculur).

Boylece ay sonunda motor gercekten yaslanmis bir vault gorur: recency siralamasi,
prune yas hesabi ve gunluk log takvimi gercek tarihlerle calisir.

Spec/rapor: docs/specs/2026-09-26-human-month-e2e.md
"""
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests'))

from v3_package_helpers import install, isolated_env, snapshot  # noqa: E402

DAY_ONE = dt.date(2026, 8, 27)          # sanal ay: 30 gun, 2026-09-25'te biter
TZ = '+03:00'
PERSON = 'zeynep'
PROJECT = 'Kahve Dukkani'
PRIVATE_MARK = 'GIZLI-FIYAT-2026-SIR'
# GitHub push protection reddetmesin diye ağacın hiçbir yerinde bitişik, gerçek
# biçimli bir anahtar bulunmaz: test anahtarı parçalardan ve sentetik olarak üretilir.
API_KEY = 'sk_' + 'live_' + 'T3stKey' + '0' * 16
DRAFT_AGE_DAYS = 120


def vday(offset):
    return (DAY_ONE + dt.timedelta(days=offset)).isoformat()


def vstamp(offset, hour=10, minute=0):
    return f'{vday(offset)}T{hour:02d}:{minute:02d}:00{TZ}'


def big_text(paragraphs, marker):
    """Gunluk buyuyen ozet notunun gercekci govdesi (bir paragraf ~1.2 karakter bin)."""
    return '\n\n'.join(f'## {marker} {i + 1}\n\n' + ' '.join([f'{marker}-{i + 1}-{j} cumle icerigi.' for j in range(30)])
                       for i in range(paragraphs))


class Month:
    """Bir insanin ay boyunca kullandigi vault: gercek cikti yollari, sanal takvim."""

    def __init__(self, root):
        self.root = Path(root)
        self.vault = self.root / 'vault'
        self.state = self.root / 'state'
        self.home = self.root / 'home'
        self.vault.mkdir(parents=True, exist_ok=True)
        self.state.mkdir(parents=True, exist_ok=True)
        self.home.mkdir(parents=True, exist_ok=True)
        self.env = isolated_env(self.home)
        result = install(self.vault, self.state, self.env)
        if result.returncode:
            raise AssertionError('install failed: ' + result.stderr.decode('utf-8', 'replace')[-400:])
        self.entry = self.vault / 'beyin.py'
        self.hook_script = self.vault / '.claude/scripts/beyin_v3_hook.py'
        self.session_days = {}
        self.log_bodies = {}
        self.events = []
        self.start_contexts = []   # her SessionStart ciktisi (gunluk log uyarisi bir kez olmali)
        self.json_dir = self.root / 'json'
        self.json_dir.mkdir(exist_ok=True)
        self.db = self.state / 'memory.sqlite3'

    # --- gercek kullanim yollari -------------------------------------------------
    def cli(self, *args, ok=True):
        result = subprocess.run([sys.executable, str(self.entry), *[str(a) for a in args]], cwd=self.vault,
                                env=self.env, capture_output=True, text=True, timeout=120)
        out = (result.stdout or '').strip()
        payload = {}
        if out:
            for candidate in (out, out.splitlines()[-1]):
                try:
                    payload = json.loads(candidate)
                    break
                except ValueError:
                    continue
            else:
                payload = {'raw': out}
        if result.returncode and not payload:
            # Hata akisi stderr'a yaziliyor; test de gormeli.
            err = (result.stderr or '').strip()
            for candidate in (err, err.splitlines()[-1] if err else ''):
                if not candidate:
                    continue
                try:
                    payload = json.loads(candidate)
                    break
                except ValueError:
                    continue
        if ok and result.returncode:
            raise AssertionError(f'beyin.py {" ".join(map(str, args))} -> rc={result.returncode} '
                                 f'{payload or out} STDERR={result.stderr[-600:]}')
        self.events.append(('cli', ' '.join(map(str, args)), result.returncode))
        return payload

    def hook(self, event, session, harness='codex', **fields):
        payload = {'hook_event_name': event, 'session_id': session, 'event_id': f'{event}-{session}',
                   'cwd': str(self.vault), 'prompt': '', 'tool_name': 'Write'}
        payload.update(fields)
        result = subprocess.run([sys.executable, str(self.hook_script), '--vault', str(self.vault),
                                 '--state', str(self.state), '--harness', harness],
                                input=json.dumps(payload), text=True, capture_output=True,
                                cwd=self.vault, env=self.env, timeout=120)
        self.events.append(('hook', event, result.returncode))
        if result.returncode:
            raise AssertionError(f'hook {event} rc={result.returncode} {result.stdout} {result.stderr}')
        output = json.loads(result.stdout.strip().splitlines()[-1]) if result.stdout.strip() else {}
        if event == 'SessionStart':
            self.start_contexts.append(str(output))
        return output

    def write_json(self, name, payload):
        path = self.json_dir / name
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
        return path

    def note(self, name, source, text, offset, **meta):
        meta.setdefault('kind', 'fact')
        meta.setdefault('project', PROJECT)
        meta.setdefault('visibility', 'internal')
        meta.setdefault('type', 'semantic')
        meta['updated_at'] = vday(offset)
        return self.cli('note-create', '--file', self.write_json(name, {'source': source, 'text': text,
                                                                         'metadata': meta}))

    def task(self, name, task_id, title, text, offset, **meta):
        meta.setdefault('kind', 'task')
        meta.setdefault('revision', 1)
        meta.setdefault('status', 'active')
        meta.setdefault('owner', PERSON)
        meta.setdefault('visibility', 'internal')
        meta.setdefault('project', PROJECT)
        meta['updated_at'] = vday(offset)
        meta['id'] = task_id
        meta['title'] = title
        return self.cli('task-create', '--file', self.write_json(name, {'source': f'tasks/{task_id}.md',
                                                                         'text': text, 'metadata': meta}))

    def patch(self, name, task_id, revision, changes):
        return self.cli('task-update', '--file', self.write_json(name, {'id': task_id, 'expected_revision': revision,
                                                                       'changes': changes}), ok=False)

    def receipt(self, name, event_id, summary, refs, offset, harness='codex', session=None):
        payload = {'event_id': event_id, 'summary': summary, 'refs': refs, 'harness': harness}
        if session:
            payload['session'] = session
        out = self.cli('receipt', '--file', self.write_json(name, payload), '--harness', harness)
        self.backdate_receipt(event_id, vstamp(offset, 18, 5))
        return out

    def preferences(self, *args):
        return self.cli('preferences', *args)

    def context(self, query, *args):
        out = self.cli('context', query, '--no-sync', *args)
        return out

    # --- tarih geri alma ----------------------------------------------------------
    def backdate_receipt(self, event_id, stamp):
        """Receipt'i geriye tarihle ve urunun kendi kurtarma yoluyla yeniden indeksle."""
        digest = hashlib.sha256(event_id.encode()).hexdigest()
        source = self.vault / 'receipts' / f'{digest}.md'
        text = source.read_text(encoding='utf-8')
        source.write_text(re.sub(r'"created_at": "[^"]+"', f'"created_at": "{stamp}"', text), encoding='utf-8')
        with sqlite3.connect(self.db) as db:
            db.execute('DELETE FROM receipts WHERE id=?', (event_id,))
        for generated in ('daily/v3', 'knowledge/v3'):
            shutil.rmtree(self.vault / generated, ignore_errors=True)
        self.cli('sync')
        with sqlite3.connect(self.db) as db:
            row = db.execute('SELECT payload FROM receipts WHERE id=?', (event_id,)).fetchone()
        if not row or json.loads(row[0]).get('created_at') != stamp:
            raise AssertionError(f'receipt backdate/adopt failed for {event_id}')

    def fill_log(self, session, body):
        """Oturum bitmeden once ajanin gunluk log Ozet bolumunu doldurmasi."""
        self.log_bodies[hashlib.sha256(str(session).encode()).hexdigest()[:24]] = body

    def redistribute_logs(self):
        """Tek gunlik log dosyasini sanal gunlere bol."""
        today = self.vault / 'daily/log' / f'{dt.date.today().isoformat()}.md'
        if not today.exists():
            return
        text = today.read_text(encoding='utf-8')
        header, _, rest = text.partition('\n<!-- beyin-session:')
        blocks = {}
        order = []
        for chunk in rest.split('\n<!-- beyin-session:'):
            key = chunk.split('-->', 1)[0].strip()
            blocks[key] = '<!-- beyin-session:' + chunk.rstrip() + '\n'
            order.append(key)
        by_day = {}
        for key in order:
            by_day.setdefault(self.session_days[key], []).append(key)
        for day, keys in by_day.items():
            body = '\n'.join(blocks[key].rstrip() for key in keys) + '\n'
            for key in keys:
                if key in self.log_bodies:
                    body = body.replace('### Özet\n', '### Özet\n\n' + self.log_bodies[key].rstrip() + '\n', 1)
            title = re.sub(r'# .*', f'# {day} oturum günlüğü', header.rstrip('\n'))
            (self.vault / 'daily/log' / f'{day}.md').write_text(title + '\n\n' + body, encoding='utf-8')
        today.unlink()

    def set_dream_last_run(self, stamp):
        with sqlite3.connect(self.db) as db:
            if stamp is None:
                db.execute("DELETE FROM metadata WHERE key='dream.last_run'")
            else:
                db.execute("INSERT OR REPLACE INTO metadata VALUES ('dream.last_run',?)", (stamp,))

    def records(self):
        with sqlite3.connect(self.db) as db:
            return {json.loads(p)['source']: json.loads(p) for (p,) in db.execute('SELECT payload FROM records')}

    def context_sources(self, query, *args):
        out = self.context(query, *args)
        return [r['source'] for r in out.get('records', [])]

    def raw_key_in_state(self, needle):
        hits = []
        for path in sorted(self.state.rglob('*')):
            if path.is_file():
                try:
                    if needle in path.read_text(encoding='utf-8', errors='ignore'):
                        hits.append(path.name)
                except OSError:
                    pass
        return hits

    # --- insanin gercekten yazdigi seed: onceki hayattan kalan dosyalar -----------
    def seed_legacy(self):
        """Kurulumdan once zaten var olan, Obsidian'dan tasinan bir kullanicinin dosyalari."""
        draft_day = (dt.date.fromisoformat(vday(0)) - dt.timedelta(days=DRAFT_AGE_DAYS)).isoformat()
        (self.vault / 'notes').mkdir(exist_ok=True)
        (self.vault / 'notes/eski-menu-taslak.md').write_text(
            '---\n{"kind": "note", "status": "draft", "updated_at": "%s"}\n---\n'
            '# Eski menu taslagi\n\n2026-04 icin yarim kalmis menu notu. Siparisler gelince guncellenecek.\n' % draft_day,
            encoding='utf-8')
        (self.vault / 'notes/telefon-notu.md').write_text(
            '# Telefon numaralari\n\n- Muzisyen: 0555 000 00 00\n- Pastane: 0212 000 00 00\n', encoding='utf-8')
        (self.vault / 'notes/ozet-notu.md').write_text(
            '---\n{"kind": "note", "project": "%s", "updated_at": "%s"}\n---\n'
            '# Proje ozeti\n\nDemir Kahve sitesi 2026-08 basinda acildi. Bu not her hafta buyutulur.\n\n%s\n'
            % (PROJECT, vday(0), big_text(2, 'ozet')), encoding='utf-8')
        self.cli('sync')

    # --- ajanin dosya araclariyla yazdigi seyler (SKILL: sync sonrasi) -----------
    def write_core_identity(self):
        core = self.vault / '🔮 850-Companion/Core.md'
        text = core.read_text(encoding='utf-8')
        core.write_text(text.rstrip() + (
            '\n\n## Kullanici\n\n- Zeynep, serbest web geliştirici (2026-08-27)\n'
            '- Türkçe konuşmayı ve Türkçe cevap tercih ediyor\n'
            '- Düşünme ortağı olarak samimi ama doğrudan bir ton istiyor\n'), encoding='utf-8')
        self.cli('sync')

    def threads_bump(self, section):
        threads = self.vault / '🔮 850-Companion/Threads.md'
        text = threads.read_text(encoding='utf-8') if threads.exists() else '# Konu dosyası\n'
        threads.write_text(text.rstrip() + '\n\n' + section.strip() + '\n', encoding='utf-8')
        self.cli('sync')

    def write_threads(self, section):
        threads = self.vault / '🔮 850-Companion/Threads.md'
        body = ['# Konu dosyası', '']
        for topic in ('Menü sayfası', 'Ödeme sayfası', 'Müşteri iletişimi', 'Blog bölümü',
                      'Yönetim paneli', 'Performans', 'SEO', 'Yayınlama', 'Alan adı', 'SSL',
                      'Yedekleme', 'Fiyatlandırma'):
            body.append(f'## {topic}\n\n- Sahip: zeynep. Durum: aktif. Sonraki adım: ilerleme kaydı.\n'
                        + '- '.join([''] + [f'{topic} için {i}. madde notu, 2026-08-27 tarihinde yazıldı.\n'
                                          for i in range(1, 9)]))
        threads.write_text('\n'.join(body), encoding='utf-8')
        self.cli('sync')

    def write_last_session(self, next_step):
        """Devir kartı tek karttır: her oturumda baştan yeniden yazılır (SKILL)."""
        path = self.vault / '🔮 850-Companion/Last-Session.md'
        text = path.read_text(encoding='utf-8') if path.exists() else '# Son oturum\n'
        head = text.split('\n## Previous')[0].split('\n## Önceki')[0]
        head = re.split(r'\n## ', head)[0]
        path.write_text(head.rstrip() + (
            f'\n\n## Devir kartı ({vday(29)})\n\n- Yapılan: {next_step}\n'
            f'- Sonraki somut adım: {next_step}\n'
            '- Kaynak: daily/log/, knowledge/concepts/, tasks/\n'), encoding='utf-8')
        self.cli('sync')

    def append_rule(self, number):
        date, text = RULES[number]
        path = self.vault / '🔮 850-Companion/Kurallar.md'
        current = path.read_text(encoding='utf-8') if path.exists() else '# Kurallar\n'
        path.write_text(current.rstrip() + f'\n\n- {date}: {text}\n', encoding='utf-8')
        self.cli('sync')

    def grow_ozet(self, offset, added):
        path = self.vault / 'notes/ozet-notu.md'
        text = path.read_text(encoding='utf-8')
        text = text.rstrip() + '\n\n' + big_text(added, f'ozet-{vday(offset)}') + '\n'
        text = re.sub(r'"updated_at": "[^"]+"', f'"updated_at": "{vday(offset)}"', text)
        path.write_text(text, encoding='utf-8')
        self.cli('sync')

    def task_done_without_evidence(self):
        """Kapı: strict görev kanıtsız done olamaz."""
        self.menudone_rejected = self.patch('g11-done-yok', 'menu-sayfasi', 1, {'status': 'done'})
        done = self.patch('g11-done-var', 'menu-sayfasi', 1,
                          {'status': 'done', 'evidence_refs': ['notes/ozet-notu.md']})
        self.menudone_accepted = done

    def reject_preference(self):
        """Kullanici tercihi geri aldi: kayit reddedildi olarak isaretlenir, silinmez."""
        path = self.vault / 'knowledge/concepts/sunum-tercihi.md'
        text = path.read_text(encoding='utf-8')
        text = text.replace('"visibility": "internal",',
                            '"visibility": "internal", "validity": "rejected", '
                            '"rejected_reason": "kullanici 2026-09-07 tarihinde geri aldi", '
                            f'"rejected_at": "{vday(11)}",')
        path.write_text(text, encoding='utf-8')
        self.cli('sync')

    def consolidate(self):
        """Dream raporundaki adayi ajan elle uygular (faz-2 otomatik apply henuz yok)."""
        draft = self.vault / 'notes/eski-menu-taslak.md'
        text = draft.read_text(encoding='utf-8')
        draft.write_text(text.replace('"status": "draft"', '"status": "closed"').rstrip() +
                         f'\n\n2026-09-25 konsolidasyonu: eski taslak kapatildi; gecerli menu icerigi '
                         f'knowledge/concepts/menu-icerigi.md icinde.\n', encoding='utf-8')
        main_note = self.vault / 'knowledge/concepts/odeme-yontemi.md'
        extra = self.vault / 'knowledge/concepts/odeme-yontemi-ek.md'
        main_text = main_note.read_text(encoding='utf-8')
        main_text = main_text.rstrip() + (
            '\n\n2026-09-16 ek notu: Stripe Checkout kullanilacak, webhook idempotency anahtari ile '
            'korunacak, aylik rapor panelden alinacak.\n')
        main_note.write_text(re.sub(r'"updated_at": "[^"]+"', f'"updated_at": "{vday(29)}"', main_text),
                             encoding='utf-8')
        # Yinelenen not kaldirilir: icerigi birlestirilmis notta duruyor. Bir isaretci
        # (pointer) notu bırakmak adayi temizlemez, cunku aday dosya adina bakar.
        extra.unlink()
        ozet = self.vault / 'notes/ozet-notu.md'
        text = ozet.read_text(encoding='utf-8')
        parts = text.split('\n\n## ozet-')
        head, tail = parts[0], parts[1:]
        keep, overflow = [], []
        for chunk in tail:
            (keep if sum(len(p) for p in keep) < 7200 else overflow).append(chunk)
        ozet.write_text(head.rstrip() + ''.join('\n\n## ozet-' + c for c in keep) + '\n', encoding='utf-8')
        if overflow:
            (self.vault / 'notes/ozet-notu-devam.md').write_text(
                '---\n{"kind": "note", "project": "%s", "updated_at": "%s"}\n---\n'
                '# Proje ozeti (devam)\n\n2026-09-25 konsolidasyonunda notes/ozet-notu.md dosyasindan '
                'ayrilmistir.\n\n%s\n' % (PROJECT, vday(30), ''.join('## ozet-' + c for c in overflow)),
                encoding='utf-8')
        self.cli('sync')


import shutil  # noqa: E402  (Month.redistribute_logs icin)


HUMAN = dict(Core=("Core.md", "Beynin kurulum sonrasi ilk konusma: kullanicinin tercihleri."))

RULES = {
    1: ("2026-08-28", "Notlarda göreli zaman yazma; mutlak tarih kullan. Kullanıcı 2026-08-28'de "
                     "düzeltme yaptı: 'dün yazdım' değil, mutlak tarih."),
    2: ("2026-09-05", "Müşterinin gizli verisi otomatik bağlama hiç girmesin; gizli notlarda "
                     "visibility: private kullan."),
    3: ("2026-09-20", "Müşteri toplantıları her perşembe 10:00'da yapılır; çelişen eski saat notu geçersiz."),
}


class HumanMonthE2ETest(unittest.TestCase):
    """30 sanal gun, ~12 oturum. Her test metodu bir insan sorusuna cevap verir."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='v3-human-month-')
        cls.month = Month(cls.tmp.name)
        cls.run_month(cls.month)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    # =====================================================================
    # Ayin akisi
    # =====================================================================
    @staticmethod
    def run_month(m):
        m.seed_legacy()
        m.snap_install = snapshot(m.vault)   # kullanicinin zaten var olan dosyalari

        # ---------------- G1 (2026-08-27) tanisma ------------------------
        s1 = f'{PERSON}-g1'
        m.session_days[hashlib.sha256(s1.encode()).hexdigest()[:24]] = vday(0)
        m.first_context = str(m.hook('SessionStart', s1))   # gunluk log uyarisi burada olmali
        m.hook('UserPromptSubmit', s1, prompt='Beyin skill, beni tanimak icin kisa sorular sor')
        m.write_core_identity()
        m.note('g1-proje', 'knowledge/concepts/kahve-dukkani-projesi.md',
               'Demir Kahve icin kahve dükkanı sitesi. Kapsam: menu sayfasi, iletisim, blog, '
               "yönetim paneli. Müşteri 2026-08-27'de teklifi onayladi; ilk ödeme %30 peşin alindi.", 0)
        m.task('g1-menu', 'menu-sayfasi', 'Menü sayfasını yayına al',
               'Menü içeriğini gir ve sayfayı yayına al.', 0, type='episodic',
               completion_contract='strict', completion_criterion='Menü sayfası yayında ve içerik girilmiş')
        m.write_threads('## Menü sayfası\n\n- Sahip: zeynep. Sonraki adım: içerik girilecek. Durum: aktif.\n')
        m.write_last_session('Menü sayfası içeriği girilecek. Proje tanıtıldı, ilk görev açıldı.')
        m.receipt('g1-r', f'{PERSON}-g1-acilis',
                  'Kahve Dükkanı projesi tanıtıldı, kimlik tercihleri kaydedildi, menü sayfası görevi açıldı.\n'
                  'Öğrenilen: yok',
                  ['knowledge/concepts/kahve-dukkani-projesi.md', 'tasks/menu-sayfasi.md'], 0, session=_session(s1))
        m.hook('Stop', s1)
        # Gunluk log varsayilan acik: kullanici hicbir sey yapmiyor. Ilk oturumda
        # ajana kapatma yolu anlatilir (keşfedilebilirlik olcumu, m.first_context).
        m.fill_log(s1, '## Bağlam\nKahve Dükkanı projesi ilk kez konuşuldu.\n\n'
                       '## Alınan Kararlar\nMenü sayfası ilk iş olacak.\n\n'
                       '## Yapılacaklar\nMenü içeriği girilecek.')
        m.hook('SessionEnd', s1)

        # ---------------- G2 (2026-08-28) menu + Kural 1 -------------------
        s2 = f'{PERSON}-g2'
        m.session_days[hashlib.sha256(s2.encode()).hexdigest()[:24]] = vday(1)
        m.hook('SessionStart', s2)
        m.hook('UserPromptSubmit', s2, prompt='menu icerigini gir, bir de notlarda tarih kullanmada hata var')
        m.note('g2-menu', 'knowledge/concepts/menu-icerigi.md',
               'Menü içeriği 2026-08-28\'de girildi: 12 içecek, 8 tatlı. Fiyatlar 2026-08-28 itibarıyle '
               'demek 45 TL, filtre 40 TL.', 1)
        m.append_rule(1)
        m.threads_bump('## Menü sayfası\n\n- Sahip: zeynep. Sonraki adım: fiyat güncellemesi. Durum: aktif.\n')
        m.receipt('g2-r', f'{PERSON}-g2-menu',
                  'Menü içeriği girildi ve kullanıcı tarih kuralını düzeltti.\n'
                  'Öğrenilen: Notlarda göreli zaman yazma, mutlak tarih yaz', ['knowledge/concepts/menu-icerigi.md'], 1,
                  session=_session(s2))
        m.hook('Stop', s2)
        m.fill_log(s2, '## Bağlam\nMenü içeriği girildi.\n\n## Öğrenilenler\nNotlarda mutlak tarih yazılır.\n\n'
                       '## Yapılacaklar\nFiyatlar ilk kez girildi, güncelleme gerekebilir.')
        m.hook('SessionEnd', s2)
        m.cli('sync')

        # ---------------- G4 (2026-08-31) odeme karari --------------------
        s4 = f'{PERSON}-g4'
        m.session_days[hashlib.sha256(s4.encode()).hexdigest()[:24]] = vday(4)
        m.hook('SessionStart', s4)
        m.hook('UserPromptSubmit', s4, prompt='odeme icin stripe mi havale mi, karar verelim')
        m.note('g4-odeme', 'knowledge/concepts/odeme-yontemi.md',
               'Ödeme yöntemi kararı (2026-08-31): kredi kartı için Stripe, havale/EFT için banka havalesi. '
               'Stripe komisyonu '
               '%2,9 + 0,25 TL; müşteri komisyonu kabul etti. Kaynak: 2026-08-31 müşteri e-postası.', 4)
        m.task('g4-odeme', 'odeme-sayfasi', 'Ödeme sayfasını Stripe\'a taşı',
               'Stripe Checkout entegrasyonunu ödeme sayfasına ekle.', 4, type='semantic',
               completion_contract='strict', completion_criterion='Test ödeme başarıyla tamamlandı')
        m.threads_bump('## Ödeme sayfası\n\n- Sahip: zeynep. Sonraki adım: Stripe entegrasyonu. Durum: aktif.\n')
        m.receipt('g4-r', f'{PERSON}-g4-odeme',
                  'Ödeme yöntemi kararlaştırıldı (Stripe + havale) ve görev açıldı.\nÖğrenilen: yok', ['knowledge/concepts/odeme-yontemi.md', 'tasks/odeme-sayfasi.md'], 4,
                  session=_session(s4))
        m.hook('Stop', s4)
        m.fill_log(s4, '## Alınan Kararlar\nKart için Stripe, havale için banka havalesi.\n\n'
                       '## Yapılacaklar\nStripe entegrasyonu yapılacak.')
        m.hook('SessionEnd', s4)
        m.cli('sync')

        # ---------------- G6 (2026-09-02) webhook ogrenimi ----------------
        s6 = f'{PERSON}-g6'
        m.session_days[hashlib.sha256(s6.encode()).hexdigest()[:24]] = vday(6)
        m.hook('SessionStart', s6)
        m.hook('UserPromptSubmit', s6, prompt='stripe webhook odemeleri iki kez isledi, duzelt')
        m.note('g6-webhook', 'knowledge/concepts/stripe-webhook-retry.md',
               'Stripe webhook işlerken iki kez ödeme kaydı oluşturdu. Yöntem: idempotency anahtarı '
               '(event id) zorunlu, iş başlamadan önce kontrol edilir; hata durumunda 3 deneme ve '
               '1sn/2sn/4sn üstel geri çekilme; işlenmiş event id tekrar gelirse 200 dönülür.', 6, type='procedural')
        m.receipt('g6-r', f'{PERSON}-g6-webhook',
                  'Webhook çift işleme hatası giderildi ve yöntem notu yazıldı.\n'
                  'Öğrenilen: Stripe webhook idempotency anahtarı (event id) olmadan iki kez işleniyor', ['knowledge/concepts/stripe-webhook-retry.md'], 6,
                  session=_session(s6))
        m.hook('Stop', s6)
        m.fill_log(s6, '## Bağlam\nWebhook ödemeyi iki kez işledi.\n\n'
                       '## Öğrenilenler\nIdempotency anahtarı olmadan webhook çift işliyor.\n\n'
                       '## Yapılacaklar\n3 denemeli geri çekilme eklendi.')
        m.hook('SessionEnd', s6)
        m.cli('sync')

        # ---------------- G8 (2026-09-04) geri cagirma #1 + buyuk not -----
        s8 = f'{PERSON}-g8'
        m.session_days[hashlib.sha256(s8.encode()).hexdigest()[:24]] = vday(8)
        m.hook('SessionStart', s8)
        m.hook('UserPromptSubmit', s8, prompt='onceki hafta ne konusmusduk, odeme icin ne karar vermistik')
        m.grow_ozet(offset=8, added=3)
        m.threads_bump('## Ödeme sayfası\n\n- Sahip: zeynep. Sonraki adım: test ödemesi. Durum: aktif.\n')
        m.receipt('g8-r', f'{PERSON}-g8-hatirlama',
                  'Geçen haftanın kararları hatırlandı ve özet notu büyütüldü.\nÖğrenilen: yok', ['knowledge/concepts/odeme-yontemi.md', 'notes/ozet-notu.md'], 8,
                  session=_session(s8))
        m.hook('Stop', s8)
        m.fill_log(s8, '## Bağlam\nGeçen haftanın kararları soruldu.\n\n'
                       '## Önemli Konuşmalar\nÖdeme yöntemi kararı hatırlandı.')
        m.hook('SessionEnd', s8)
        m.cli('sync')

        # ---------------- G9 (2026-09-05) Kural 2 + private + sir süzgeci -
        s9 = f'{PERSON}-g9'
        m.session_days[hashlib.sha256(s9.encode()).hexdigest()[:24]] = vday(9)
        m.hook('SessionStart', s9)
        m.hook('UserPromptSubmit', s9, prompt='musteri fiyatlarini gizli tutalim, bir de sunum tercihi')
        m.note('g9-gizlilik', 'knowledge/concepts/musteri-gizlilik.md',
               '2026-09-05: müşteri fiyat listesi ve ciro tahminleri gizli; yalnız Zeynep ve müşteri '
               'görebilmeli. Bu kayıtlar otomatik bağlama girmez.', 9)
        m.note('g9-private', 'notes/musteri-fiyatlari.md',
               f'Gizli fiyat listesi 2026-09-05: {PRIVATE_MARK} etiketli kalemler yalnız zeynep ve '
               f'müşteri tarafından görülebilir. Ciro tahmini 2026-Q3: 1.2 milyon TL.', 9, visibility='private')
        m.append_rule(2)
        m.preferences('--secret-filter', 'on')
        m.receipt('g9-r', f'{PERSON}-g9-gizlilik',
                  'Müşteri gizlilik kuralı yazıldı, gizli fiyat notu private olarak kaydedildi.\n'
                  'Öğrenilen: Gizli müşteri verisi otomatik bağlama girmez', ['knowledge/concepts/musteri-gizlilik.md'], 9,
                  session=_session(s9))
        m.hook('Stop', s9)
        m.fill_log(s9, '## Alınan Kararlar\nFiyat listesi gizli notta tutulacak.\n\n'
                       '## Yapılacaklar\nSunumda fiyat gösterilmeyecek.')
        m.hook('SessionEnd', s9)
        m.cli('sync')

        # ---------------- G11 (2026-09-07) gorev lifecycle + geri alma ---
        s11 = f'{PERSON}-g11'
        m.session_days[hashlib.sha256(s11.encode()).hexdigest()[:24]] = vday(11)
        m.hook('SessionStart', s11)
        m.hook('UserPromptSubmit', s11, prompt='odeme sayfasi bitti, sunum tercihini de degistirdim')
        m.task_done_without_evidence()
        m.note('g11-sunum-pref', 'knowledge/concepts/sunum-tercihi.md',
               '2026-09-07: müşteri sunumlarında emoji kullanma tercihi (kullanıcı beyanı).', 11,
               kind='preference', type='semantic')
        m.reject_preference()
        m.receipt('g11-r', f'{PERSON}-g11-onay',
                  'Menü görevi kanıtla kapatıldı; sunum tercihi geri çekildi.\nÖğrenilen: yok', ['tasks/menu-sayfasi.md', 'knowledge/concepts/sunum-tercihi.md'], 11,
                  session=_session(s11))
        m.hook('Stop', s11)
        m.fill_log(s11, '## Alınan Kararlar\nEmoji tercihi geri çekildi, kayıt reddedildi olarak işaretlendi.\n\n'
                        '## Yapılacaklar\nStripe test ödemesi yapılacak.')
        m.hook('SessionEnd', s11)
        m.cli('sync')

        # ---------------- G12 (2026-09-08) anahtar sizintisi + tatil -----
        s12 = f'{PERSON}-g12'
        m.session_days[hashlib.sha256(s12.encode()).hexdigest()[:24]] = vday(12)
        m.hook('SessionStart', s12)
        m.hook('UserPromptSubmit', s12, prompt='test odemesi icin anahtari kullan, sonra izleyim')
        m.preferences('--profile', 'economical')
        m.receipt('g12-r', f'{PERSON}-g12-anahtar',
                  f'Test ödemesi için Stripe anahtarı {API_KEY} kullanıldı; sır süzgeci çalıştı.\n'
                  'Öğrenilen: Sır süzgeci açıkken anahtarlar [REDACTED] olarak yazılır', ['knowledge/concepts/odeme-yontemi.md'], 12,
                  session=_session(s12))
        m.hook('Stop', s12)
        m.fill_log(s12, '## Bağlam\nTatil öncesi test ödemesi yapıldı.\n\n## Yapılacaklar\nEkonomik moda geçildi.')
        m.hook('SessionEnd', s12)
        m.cli('sync')
        # G13-G19: tatil, oturum yok

        # ---------------- G20 (2026-09-16) donus + geri cagirma #2 -------
        s20 = f'{PERSON}-g20'
        m.session_days[hashlib.sha256(s20.encode()).hexdigest()[:24]] = vday(20)
        m.hook('SessionStart', s20)
        m.startup_economical = m.hook('UserPromptSubmit', s20,
                                      prompt='bir haftalık tatilden donduk, neler yapmistik')
        m.preferences('--profile', 'normal')
        m.startup = m.hook('UserPromptSubmit', s20, prompt='bir haftalık tatilden donduk, neler yapmistik')
        m.note('g20-odeme-tekrar', 'knowledge/concepts/odeme-yontemi-ek.md',
               'Ödeme tekrar notu (2026-09-16): Stripe Checkout kullanılacak, webhook idempotency '
               'anahtarı ile korunacak. Stripe panelinden aylık rapor alınacak.', 20)
        m.grow_ozet(offset=20, added=4)
        m.threads_bump('## Müşteri toplantıları\n\n- Sahip: zeynep. Sonraki adım: perşembe 10:00 toplantısı. Durum: beklemede.\n')
        m.receipt('g20-r', f'{PERSON}-g20-donus',
                  'Tatilden dönüldü, ödeme notu tazelendi ve tercihler normale döndü.\nÖğrenilen: yok', ['knowledge/concepts/odeme-yontemi-ek.md'], 20,
                  session=_session(s20))
        m.hook('Stop', s20)
        m.fill_log(s20, '## Bağlam\nBir haftalık tatil sonrası dönüş.\n\n'
                        '## Önemli Konuşmalar\nÖdeme notu tazelendi.\n\n## Yapılacaklar\nAylık rapor alınacak.')
        m.hook('SessionEnd', s20)
        m.cli('sync')

        # ---------------- G21 (2026-09-17) dream -------------------------
        s21 = f'{PERSON}-g21'
        m.session_days[hashlib.sha256(s21.encode()).hexdigest()[:24]] = vday(21)
        m.hook('SessionStart', s21)
        m.hook('UserPromptSubmit', s21, prompt='aylik olarak bakiyimiz ne durumda, bir goz atalim')
        m.dream_first = m.cli('dream')
        m.set_dream_last_run(vstamp(28, 9, 0))          # 2 gün önce: 5'ten az yeni receipt
        m.dream_receipt_gate = m.cli('dream')
        m.set_dream_last_run(dt.datetime.now(dt.timezone.utc).isoformat())  # bugün: cooldown
        m.dream_cooldown = m.cli('dream')
        m.set_dream_last_run(None)
        m.receipt('g21-r', f'{PERSON}-g21-dream',
                  'Konsolidasyon penceresi raporu alındı (ilk kez yazmadan).\nÖğrenilen: yok', ['notes/ozet-notu.md'], 21,
                  session=_session(s21))
        m.hook('Stop', s21)
        m.fill_log(s21, '## Bağlam\nAyın ilk konsolidasyon raporu alındı.\n\n## Yapılacaklar\nAdaylar gözden geçirilecek.')
        m.hook('SessionEnd', s21)
        m.cli('sync')

        # ---------------- G24 (2026-09-20) Kural 3 + arsiv --------------
        s24 = f'{PERSON}-g24'
        m.session_days[hashlib.sha256(s24.encode()).hexdigest()[:24]] = vday(24)
        m.hook('SessionStart', s24)
        m.hook('UserPromptSubmit', s24, prompt='toplanti saatini degistirdim, threads cok uzadi')
        m.append_rule(3)
        m.threads_bump('## Fiyatlandırma\n\n- Sahip: zeynep. Sonraki adım: Q4 fiyat listesi. Durum: beklemede.\n')
        m.receipt('g24-r', f'{PERSON}-g24-kural',
                  'Toplantı saati kuralı güncellendi ve konu dosyası arşivlendi.\nÖğrenilen: yok', ['knowledge/concepts/musteri-gizlilik.md'], 24,
                  session=_session(s24))
        m.hook('Stop', s24)
        m.fill_log(s24, '## Alınan Kararlar\nToplantılar perşembe 10:00.\n\n## Yapılacaklar\nQ4 fiyat listesi hazırlanacak.')
        m.hook('SessionEnd', s24)
        m.cli('sync')

        # ---------------- G27 (2026-09-23) buyuk not siniri -------------
        s27 = f'{PERSON}-g27'
        m.session_days[hashlib.sha256(s27.encode()).hexdigest()[:24]] = vday(27)
        m.hook('SessionStart', s27)
        m.hook('UserPromptSubmit', s27, prompt='ozet notu cok buyudu, bir bak')
        m.grow_ozet(offset=27, added=3)
        m.threads_bump('## Q4 fiyatlandırma\n\n- Sahip: zeynep. Sonraki adım: müşteri onayı. Durum: beklemede.\n')
        m.receipt('g27-r', f'{PERSON}-g27-buyuk',
                  'Özet notu 12000 karakter sınırını aştı; doktör uyarısı bekleniyor.\nÖğrenilen: yok', ['notes/ozet-notu.md'], 27,
                  session=_session(s27))
        m.hook('Stop', s27)
        m.fill_log(s27, '## Bağlam\nÖzet notu büyüdü.\n\n## Yapılacaklar\nNot bölünecek.')
        m.hook('SessionEnd', s27)
        m.cli('sync')

        # ---------------- G30 (2026-09-25) ay sonu konsolidasyonu -------
        s30 = f'{PERSON}-g30'
        m.session_days[hashlib.sha256(s30.encode()).hexdigest()[:24]] = vday(29)
        m.hook('SessionStart', s30)
        m.hook('UserPromptSubmit', s30, prompt='ay sonu: rapordaki adayi uygula, sonra kontrol et')
        m.dream_pre = m.cli('dream')          # ay sonu "bir goze atalim" raporu
        m.snap_pre_consolidation = snapshot(m.vault)
        m.consolidate()
        m.cli('sync')
        m.dream_after = m.cli('dream')
        m.write_last_session('Ay sonu konsolidasyonu yapıldı. Eylül için menü ve ödeme üzerine çalışılacak.')
        m.receipt('g30-r', f'{PERSON}-g30-konsolidasyon',
                  'Dream raporundaki adaylar uygulandı: iki ödeme notu birleşti, eski taslak kapatıldı, '
                  'büyük özet notu bölündü.\nÖğrenilen: Konsolidasyon faz-1 raporu yazmadan çalışır', ['knowledge/concepts/odeme-yontemi.md', 'notes/ozet-notu.md'], 30,
                  session=_session(s30))
        m.hook('Stop', s30)
        m.fill_log(s30, '## Bağlam\nAy sonu konsolidasyonu.\n\n## Alınan Kararlar\nAdaylar rapora göre uygulandı.\n\n'
                        '## Yapılacaklar\nEylül: menü ve ödeme çalışması.')
        m.hook('SessionEnd', s30)
        m.cli('sync')
        m.redistribute_logs()
        m.snap_month_end = snapshot(m.vault)
        m.doctor_final = m.cli('doctor')
        m.recall1 = m.context_sources('odeme icin ne karar vermistik')
        m.recall2 = m.context_sources('webhook kac kez deniyordu')
        m.recall3 = m.context_sources('musteri fiyatlari gizli mi')
        m.recall_rule = m.context_sources('toplanti saati ne')
        m.dream_post = m.cli('dream')

    # =====================================================================
    # Bir insanin sorulari: ay boyunca olusan gercek davranis
    # =====================================================================
    def _installed_engine(self):
        """Kurulu vault'un motorunu yukler (insanin gördugu yapi)."""
        import importlib.util
        scripts = self.month.vault / '.claude/scripts'
        saved = list(sys.path)
        sys.path.insert(0, str(scripts))
        try:
            spec = importlib.util.spec_from_file_location('month_engine', scripts / 'beyin_v3.py')
            engine = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(engine)
        finally:
            sys.path.remove(str(scripts))
        return engine

    def test_q1_notes_are_saved(self):
        """Notlarim kaydedildi mi? Her not diskte, tarihli ve aramada."""
        m = self.month
        for rel in ('knowledge/concepts/kahve-dukkani-projesi.md', 'knowledge/concepts/menu-icerigi.md',
                    'knowledge/concepts/odeme-yontemi.md', 'knowledge/concepts/stripe-webhook-retry.md',
                    'notes/musteri-fiyatlari.md', 'notes/ozet-notu.md', 'tasks/odeme-sayfasi.md'):
            self.assertTrue((m.vault / rel).is_file(), f'{rel} yazilmadi')
        for rel, day in (('knowledge/concepts/kahve-dukkani-projesi.md', 0),
                         ('knowledge/concepts/menu-icerigi.md', 1),
                         ('knowledge/concepts/stripe-webhook-retry.md', 6),
                         ('knowledge/concepts/musteri-gizlilik.md', 9),
                         ('notes/musteri-fiyatlari.md', 9)):
            record = m.records()[rel]
            self.assertEqual(record.get('updated_at'), vday(day), f'{rel} tarihi {record.get("updated_at")}')
        # Ay sonunda birlestirilen not gercekten guncellendi; tarih geriye gitmemeli.
        self.assertEqual(m.records()['knowledge/concepts/odeme-yontemi.md'].get('updated_at'), vday(29))
        self.assertIn('knowledge/concepts/odeme-yontemi.md', m.recall1)
        self.assertIn('knowledge/concepts/stripe-webhook-retry.md', m.recall2)

    def test_q2_rules_persist_and_are_recalled(self):
        """Kurallarim yerinde mi, yeni oturumda hatirlaniyor mu?"""
        m = self.month
        rules = (m.vault / '🔮 850-Companion/Kurallar.md').read_text(encoding='utf-8')
        for number, (date, text) in RULES.items():
            self.assertIn(date, rules, f'Kural {number} tarihi eksik')
            self.assertIn(text.split(':', 1)[-1].strip()[:35], rules.replace('\n', ' '), f'Kural {number} metni yok')
        context = json.dumps(m.startup, ensure_ascii=False)
        for number in (1, 2):
            self.assertIn(RULES[number][0], context, f'oturum basinda Kural {number} yok')
        self.assertIn('Kurallar.md', context)
        self.assertTrue(any('Kurallar' in s for s in m.recall_rule)
                        or any('850-Companion' in s for s in m.recall_rule), m.recall_rule)

    def test_q3_remembered_after_a_week(self):
        """Bir hafta sonra hatirladi mi? (tatil sonrasi donus oturumu)"""
        m = self.month
        self.assertIn('knowledge/concepts/odeme-yontemi.md', m.recall1)
        self.assertIn('knowledge/concepts/stripe-webhook-retry.md', m.recall2)
        self.assertIn('knowledge/concepts/musteri-gizlilik.md', m.recall3)

    def test_q4_consolidated_only_on_request(self):
        """Dagınıklık istendiğinde derlendi mi, izinsiz sey yazilmadi mi?"""
        m = self.month
        first = m.dream_first
        self.assertTrue(first['gates']['passed'], first['gates'])
        self.assertFalse(first['wrote'])
        self.assertEqual(first['model_calls'], False)
        self.assertEqual(first['network'], False)
        # Ay sonunda adaylar gercekten vardi: eski taslak, yinelenen not, devasa not.
        kinds = {'prune': 'notes/eski-menu-taslak.md',
                 'merge': 'knowledge/concepts/odeme-yontemi-ek.md',
                 'refresh': 'notes/ozet-notu.md'}
        for kind, expected in kinds.items():
            flat = json.dumps(m.dream_pre['candidates'][kind], ensure_ascii=False)
            self.assertIn(expected, flat, f'{kind} adayi yok: {flat}')
        # D21'de (not henuz buyumedigi icin) yalniz iki aday vardi.
        self.assertEqual(m.dream_first['candidates']['refresh'], [])
        # Kapilar: 5'ten az yeni receipt ve 24 saatten kisa sure reddeder.
        self.assertIn('min_receipts', m.dream_receipt_gate['gates']['blocked_by'])
        self.assertIn('min_hours', m.dream_cooldown['gates']['blocked_by'])
        # Rapor disinda hicbir dosya degismedi.
        changed = {p for p in m.snap_pre_consolidation
                   if p in m.snap_month_end and m.snap_pre_consolidation[p] != m.snap_month_end[p]}
        allowed = {'notes/ozet-notu.md', 'knowledge/concepts/odeme-yontemi.md',
                   'notes/eski-menu-taslak.md', 'knowledge/v3/outcomes.md',
                   '🔮 850-Companion/Last-Session.md'}
        self.assertEqual(changed - allowed, set(), f'raporda olmayan dosya degisti: {sorted(changed - allowed)}')
        # daily/log/ dosyalari testin takvim yeniden dagitimiyla yer degistirir (sanal
        # tarihe yazilir); urun yazimi degildir, q9 sonucu dogrular.
        removed = {p for p in set(m.snap_pre_consolidation) - set(m.snap_month_end)
                   if not p.startswith('daily/log/')}
        self.assertEqual(removed, {'knowledge/concepts/odeme-yontemi-ek.md'},
                         f'beklenmeyen dosya silindi: {sorted(removed)}')
        # Uygulama sonrasi adaylar temizlendi ve rapor yine bir sey yazmadi.
        self.assertEqual(m.dream_post['wrote'], False)
        for kind in ('prune', 'merge', 'refresh'):
            self.assertEqual(m.dream_post['candidates'][kind], [], f'{kind} adayi kalmadi')

    def test_q5_seed_files_intact(self):
        """Tohum dosyalarim duruyor mu? Kurallar/aynisip el degmedi mi?"""
        m = self.month
        for rel in ('notes/telefon-notu.md', 'notes/eski-menu-taslak.md'):
            self.assertIn(rel, m.snap_install, f'{rel} tohumda yok')
        self.assertEqual(m.snap_install['notes/telefon-notu.md'],
                         m.snap_month_end.get('notes/telefon-notu.md'), 'eski not degisti')
        companions = {p for p in m.snap_install if p.startswith('🔮 850-Companion/')}
        touched = {p for p in companions if m.snap_install[p] != m.snap_month_end.get(p)}
        self.assertEqual(touched, {'🔮 850-Companion/Kurallar.md', '🔮 850-Companion/Core.md',
                                   '🔮 850-Companion/Threads.md', '🔮 850-Companion/Last-Session.md'},
                         f'beklenmeyen companion degisimi: {sorted(touched)}')
        code = {p for p in m.snap_install if p.startswith(('.claude/', '.codex/', '.omp/', '.agents/'))}
        self.assertEqual({p for p in code if m.snap_install[p] != m.snap_month_end.get(p)}, set(),
                         'kurulu kod/skill dosyalari degisti')

    def test_q6_private_and_secret_no_leak(self):
        """Gizli veri sizmadi mi, anahtar ham kalmadi mi?"""
        m = self.month
        for query in ('fiyat listesi', 'musteri fiyatlari', 'gizli fiyat'):
            self.assertFalse([s for s in m.context_sources(query) if 'musteri-fiyatlari' in s], query)
        self.assertNotIn(PRIVATE_MARK, json.dumps(m.startup, ensure_ascii=False))
        self.assertEqual(m.raw_key_in_state(API_KEY), [], 'ham anahtar yerel durumda kaldi')
        stored = (m.vault / 'receipts' / (hashlib.sha256(f'{PERSON}-g12-anahtar'.encode()).hexdigest() + '.md'))
        body = stored.read_text(encoding='utf-8')
        self.assertNotIn(API_KEY, body, 'receipt dosyasinda ham anahtar var')
        self.assertIn('[REDACTED]', body)
        # Kayit gecerli sayilir, ama icerik indeksinde de ham olmamali.
        self.assertFalse([s for s in m.context_sources('stripe anahtari test odemesi')
                          if any(API_KEY in str(r) for r in m.cli('context', 'stripe anahtari test odemesi',
                                                                 '--no-sync').get('records', []))])

    def test_q7_no_model_or_network(self):
        """Sistem kendi basina model/ag cagridi mi?"""
        m = self.month
        self.assertEqual(m.doctor_final['automatic_model_calls'], False)
        self.assertEqual(m.doctor_final['jev']['mode'], 'off')
        self.assertFalse(m.doctor_final['jev']['configured'])
        for report in (m.dream_first, m.dream_after, m.dream_post):
            self.assertEqual(report['model_calls'], False)
            self.assertEqual(report['network'], False)

    def test_q8_turkish_natural_queries(self):
        """Insanin dogal sorulari calisiyor mu? (diakritikli, kisa, günlük dille)"""
        m = self.month
        for query, expected in (
                ('odeme icin ne karar vermistik', 'knowledge/concepts/odeme-yontemi.md'),
                ('webhook kac kez deniyordu', 'knowledge/concepts/stripe-webhook-retry.md'),
                ('menu fiyatlari ne', 'knowledge/concepts/menu-icerigi.md'),
                ('müşteri fiyat listesi gizli mi', 'knowledge/concepts/musteri-gizlilik.md'),
        ):
            self.assertIn(expected, m.context_sources(query), query)

    def test_q9_daily_log_calendar(self):
        """Gunluk log ay takvimine yayildi mi, ozet bolumleri durdu mu?"""
        m = self.month
        logs = sorted(p.name for p in (m.vault / 'daily/log').glob('*.md'))
        self.assertNotIn(f'{dt.date.today().isoformat()}.md', logs, 'gercek tarihli gunluk log kaldi')
        for day in (vday(1), vday(4), vday(6), vday(20), vday(29)):
            self.assertIn(f'{day}.md', logs)
        self.assertNotIn(vday(13), logs, 'tatil gununde oturum logu olmamali')
        text = (m.vault / 'daily/log' / f'{vday(6)}.md').read_text(encoding='utf-8')
        self.assertIn('Idempotency anahtarı', text, 'ajanin doldurdugu Ozet korunmadi')
        daily = sorted(p.name for p in (m.vault / 'daily/v3').glob('*.md'))
        self.assertIn(f'{vday(6)}.md', daily, 'receipt projectioni geriye tarihlemedi')
        self.assertNotIn(f'{dt.date.today().isoformat()}.md', daily)
        # Gun 1: kullanici hicbir sey yapmadi ve gunluk log yine yazildi (varsayilan acik).
        self.assertIn(f'{vday(0)}.md', logs, 'varsayilan acikken ilk gun gunluk logu olusmadi')
        # Kesfedilebilirlik: ajan ilk oturumda kapatma yolunu ogrendi, sonraki oturumlarda
        # tekrar etmedi (uyari bir kez).
        self.assertIn('--daily-log off', m.first_context)
        self.assertEqual([c for c in m.start_contexts if '--daily-log off' in c], [m.first_context],
                         'gunluk log uyarisi birden fazla oturumda tekrarlandi')

    def test_q10_strict_task_gate_rejects_unevidenced_done(self):
        """Kanitsiz strict done reddedildi, kanitli kabul edildi."""
        m = self.month
        self.assertEqual(m.menudone_rejected.get('error'), 'ValueError')
        self.assertIn('evidence_refs', m.menudone_rejected.get('message', ''))
        self.assertEqual(m.menudone_accepted.get('status'), 'done')
        self.assertEqual(m.menudone_accepted.get('revision'), 2)

    def test_q11_rejected_preference_is_history_not_context(self):
        """Reddedilen tercih silinmez, guncel baglama da girmez."""
        m = self.month
        sources = m.context_sources('sunumda emoji')
        self.assertNotIn('knowledge/concepts/sunum-tercihi.md', sources, sources)
        record = m.records()['knowledge/concepts/sunum-tercihi.md']
        self.assertEqual(record.get('validity'), 'rejected')
        self.assertEqual(record.get('rejected_at'), vday(11))
        self.assertIn('emoji', json.dumps(m.cli('history', record['id']), ensure_ascii=False))

    def test_q12_semantic_plug_is_empty_and_reranks_only(self):
        """Vektor saglayicisi bagli degil; fiş yalniz aday havuzunu yeniden siralar.

        Olculen mimari: `semantic_searcher` yalniz lexikal olarak gelen adaylari gorur,
        yani siralayabilir ama yeni bir kaydi aday havuzuna ekleyemez. Saf semantic
        hatirlama bugun bu yuzden mumkun degildir; faz-2 icin on kosuldur.
        """
        engine = self._installed_engine()
        store = engine.MemoryStore(self.month.state, self.month.vault, read_only=True)
        self.assertIsNone(store.semantic_searcher, 'kullanici kurulumunda vektor saglayicisi bagli')
        query = 'odeme icin ne karar vermistik'
        lexical_only = [r['source'] for r in store._retrieve(query, limit=5)['records']]
        seen = {}

        def searcher(q, candidates):
            seen['candidates'] = [c['source'] for c in candidates]
            return [c['id'] for c in sorted(candidates,
                    key=lambda c: 0 if 'webhook' in c.get('text', '').lower() else 1)]

        store.semantic_searcher = searcher
        fused = [r['source'] for r in store._retrieve(query, limit=5)['records']]
        self.assertEqual(sorted(seen['candidates']), sorted(lexical_only), 'aday havuzu lexikal sonuclardan farkli')
        self.assertTrue(fused, 'birlestirilmis sira bos dondu')
        self.assertEqual(sorted(fused), sorted(lexical_only), 'RRF yalniz sirayi degistirmeli, kumesi degil')

        def broken(q, candidates):
            raise RuntimeError('saglayici coktu')

        store.semantic_searcher = broken
        degraded = [r['source'] for r in store._retrieve(query, limit=5)['records']]
        self.assertEqual(degraded, lexical_only, 'semantik arama bozulunca kelimesel sira korunmali')

    def test_q13_current_search_limits_are_pinned(self):
        """Bilinen sinirlar olculuyor: govde sozcukleridir, birlestirme (stem) yoktur."""
        engine = self._installed_engine()
        store = engine.MemoryStore(self.month.state, self.month.vault, read_only=True)
        found = [r['source'] for r in store._retrieve('musteri fiyatlari gizli mi', limit=5)['records']]
        self.assertIn('knowledge/concepts/musteri-gizlilik.md', found)
        # Sozcuk temellidir, birlestirme yoktur: "gizlilik" ile "gizli" ayni kavram degildir.
        self.assertNotIn('knowledge/concepts/musteri-gizlilik.md',
                         [r['source'] for r in store._retrieve('gizlilik', limit=5)['records']])
        # Tip filtresi motor seviyesinde calisir (CLI bayragi hala yok: roadmap isi).
        self.assertIn('knowledge/concepts/stripe-webhook-retry.md',
                      [r['source'] for r in store._retrieve('webhook kac kez deniyordu', types=['procedural'],
                                                          limit=5)['records']])

    def test_q14_economical_profile_suppresses_per_turn_context(self):
        """Ekonomik profilde mesaj basina baglam gelmez; normal profilde gelir."""
        m = self.month
        self.assertEqual(m.startup_economical, {}, 'ekonomik profilde mesaj basina baglam geldi')
        self.assertIn('Kurallar.md', json.dumps(m.startup, ensure_ascii=False))


def _session(session_id):
    """Hook'un oturum anahtari: sha256(session_id)[:24]."""
    return hashlib.sha256(str(session_id).encode()).hexdigest()[:24]


if __name__ == '__main__':
    unittest.main()
