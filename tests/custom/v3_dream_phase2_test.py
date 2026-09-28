"""AutoDream faz 2 — snapshot + geri al kanıtı + Refresh (daraltılmış kapsam).

Spec: docs/specs/2026-09-26-autodream-phase2-snapshot-refresh-plan.md
Yol haritası: docs/specs/2026-09-26-autodream-lite-roadmap.md (§2, §5 adım 2, §5.1, §6)

Faz 1 yalnızca raporlar. Bu faz ilk kez dosya değiştirir; bu yüzden her senaryo
"başka bir şey bozuldu mu" sorusuna değil, "geri alınabilir mi" sorusuna bakar.
"""
import contextlib
import datetime as dt
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / 'template/.claude/scripts'
CLI = ROOT / 'scripts/beyin_v3.py'
ARCHIVE = 'archive/auto-dream'


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(SCRIPTS))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(SCRIPTS))
    return module


def load_engine():
    spec = importlib.util.spec_from_file_location('dream2_engine', SCRIPTS / 'beyin_v3.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class DreamPhase2Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = load_engine()
        cls.dream = load('dream_phase2_subject', 'beyin_v3_dream.py')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='v3-dream-phase2-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.vault = self.root / 'vault'
        self.vault.mkdir()
        self.state = self.root / 'state'
        self.store = self.engine.MemoryStore(self.state, self.vault)
        self.today = '2026-09-26'
        self.moment = dt.datetime.fromisoformat(f'{self.today}T10:00:00+00:00')

    # -- fixtures -------------------------------------------------------
    def note_record(self, source):
        """A synced record: no derived title, the heading lives in the body."""
        return {'id': source.replace('/', '-').replace('.md', ''), 'source': source,
                'text': '# ' + source.rsplit('/', 1)[-1][:-3] + '\n', 'kind': 'note',
                'status': 'active', 'visibility': 'internal', 'revision': 1}

    def write_note(self, relative, text):
        path = self.vault / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def oversize_note(self, relative='knowledge/concepts/buyuk.md'):
        """An oversize legacy note: over the cap *and* carrying what Refresh tidies.

        Both halves matter. A note over the cap with nothing to fix is a refresh
        candidate that correctly changes nothing, which is a different test.
        """
        text = ('---\n{"type": "semantic", "created": "2026-09-01", "updated": "2026-09-20"}\n---\n'
                '# Büyük kavram  \n\n\n\n' + ('gerçek içerik cümlesi. \n' * 700))
        self.write_note(relative, text)
        self.store.ingest(self.note_record(relative) | {'text': text})
        return relative

    def assert_refresh_candidate(self, relative):
        """A fixture that is not over NOTE_CAP_CHARS is not a refresh candidate.

        Written because it happened: a 9.6k note made three tests pass or fail for the
        wrong reason, and one of them trivially.
        """
        chars = len((self.vault / relative).read_text(encoding='utf-8'))
        self.assertGreater(chars, 12000, f'{relative} tavanın altında ({chars}): aday olmaz')

    def seed_receipts(self, count=5, since_iso=None):
        import sqlite3
        db = sqlite3.connect(self.state / 'memory.sqlite3')
        try:
            for i in range(count):
                stamp = since_iso or (self.moment - dt.timedelta(days=2)).isoformat()
                db.execute('INSERT OR REPLACE INTO receipts VALUES (?,?)',
                           (f'r{i}', json.dumps({'event_id': f'r{i}', 'summary': 's',
                                                 'refs': ['knowledge/a.md'], 'harness': 'codex',
                                                 'created_at': stamp})))
            db.commit()
        finally:
            db.close()

    def window(self, **kwargs):
        kwargs.setdefault('now', self.moment)
        return self.dream.window(self.vault, self.state, self.store, **kwargs)

    def sha(self, relative):
        return hashlib.sha256((self.vault / relative).read_bytes()).hexdigest()

    def tree(self):
        return {str(p.relative_to(self.vault).as_posix()): p.read_bytes()
                for p in sorted(self.vault.rglob('*')) if p.is_file()}

    # -- snapshot -------------------------------------------------------
    def test_snapshot_manifest_records_matching_sha256_for_every_file(self):
        first = self.oversize_note('knowledge/concepts/bir.md')
        second = self.oversize_note('knowledge/concepts/iki.md')
        manifest = self.dream.snapshot(self.vault, [first, second], self.moment)
        self.assertEqual(manifest['schema'], 1)
        self.assertEqual(manifest['window'], self.today)
        entries = {entry['source']: entry for entry in manifest['files']}
        self.assertEqual(set(entries), {first, second})
        for source, entry in entries.items():
            archived = self.vault / entry['archive']
            self.assertTrue(archived.is_file(), f'{source} arsivlenmedi')
            self.assertEqual(hashlib.sha256(archived.read_bytes()).hexdigest(), entry['sha256'])
            self.assertEqual(entry['chars'], len(archived.read_text(encoding='utf-8')))

    def test_snapshot_directory_is_outside_the_note_trees(self):
        # Kural: arsiv kopyalari kendi aday listelerine giremez. archive/ kokte ve
        # not agaclarindan (knowledge/, notes/) ayri.
        note = self.oversize_note()
        manifest = self.dream.snapshot(self.vault, [note], self.moment)
        for entry in manifest['files']:
            self.assertTrue(entry['archive'].startswith(ARCHIVE + '/'), entry['archive'])
            self.assertFalse(entry['archive'].startswith('knowledge/'))
            self.assertFalse(entry['archive'].startswith('notes/'))

    # -- restore kanıtı (§6) --------------------------------------------
    def test_restore_returns_the_exact_pre_window_bytes(self):
        note = self.oversize_note()
        before = self.sha(note)
        self.seed_receipts()
        applied = self.window()
        self.assertTrue(applied['wrote'], applied)
        self.dream.restore(self.vault, self.today)
        self.assertEqual(self.sha(note), before, 'geri alma pencere öncesi baytları vermedi')

    def test_restore_rewrites_every_touched_file_not_just_the_first(self):
        first = self.oversize_note('knowledge/concepts/bir.md')
        second = self.oversize_note('knowledge/concepts/iki.md')
        before = {first: self.sha(first), second: self.sha(second)}
        self.seed_receipts()
        self.window()
        self.dream.restore(self.vault, self.today)
        self.assertEqual({first: self.sha(first), second: self.sha(second)}, before)

    def test_restore_rejects_a_manifest_whose_hash_no_longer_matches(self):
        note = self.oversize_note()
        self.seed_receipts()
        self.window()
        manifest_path = self.vault / ARCHIVE / self.today / 'manifest.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        manifest['files'][0]['sha256'] = '0' * 64
        manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
        with self.assertRaises(ValueError):
            self.dream.restore(self.vault, self.today)

    def test_restore_of_an_unknown_window_is_refused(self):
        with self.assertRaises(ValueError):
            self.dream.restore(self.vault, '2020-01-01')

    def test_crash_after_snapshot_still_restores(self):
        # Yarım pencere: snapshot yazildi, hiçbir not yeniden yazilmadi.
        note = self.oversize_note()
        before = self.sha(note)
        self.dream.snapshot(self.vault, [note], self.moment)
        self.dream.restore(self.vault, self.today)
        self.assertEqual(self.sha(note), before)

    # -- gates and lock -------------------------------------------------
    def test_apply_inside_the_gate_writes_nothing_at_all(self):
        self.oversize_note()
        # Kapilar yalniz once bir pencere gecmisten sonra devreye girer; ilk kosuda
        # filigran yoktur ve zaman/receipt kurali gecerli degildir.
        self.store.write_meta('dream.last_run', (self.moment - dt.timedelta(hours=1)).isoformat())
        self.seed_receipts(count=1)          # < 5 receipt: kapali
        before = self.tree()
        result = self.window()
        self.assertFalse(result['gates']['passed'])
        self.assertFalse(result['wrote'])
        self.assertFalse((self.vault / ARCHIVE).exists(), 'kapali pencerede arsiv kuruldu')
        self.assertEqual(self.tree(), before)

    def test_a_locked_state_refuses_a_second_window(self):
        self.oversize_note()
        self.seed_receipts()
        import _portalock
        handle = open(self.state / 'dream.lock', 'a+b')
        try:
            with _portalock.exclusive(handle, blocking=False):
                result = self.window()
            self.assertIn('lock', result['gates']['blocked_by'])
            self.assertFalse(result['wrote'])
            self.assertFalse((self.vault / ARCHIVE).exists())
        finally:
            handle.close()

    def test_the_report_run_still_never_creates_the_lock_file(self):
        # Faz-1 sözü: rapor hiçbir koşulda kilit dosyasi olusturmaz.
        self.store.write_meta('dream.last_run', (self.moment - dt.timedelta(days=2)).isoformat())
        self.dream.report(self.vault, self.state, self.store, now=self.moment)
        self.assertFalse((self.state / 'dream.lock').exists())

    # -- watermark ------------------------------------------------------
    def test_watermark_moves_only_when_something_was_written(self):
        self.seed_receipts()
        self.window()                       # aday yok -> yazma yok
        self.assertIsNone(self.store.read_meta('dream.last_run'),
                          ' hicbir sey yazilmazken filigran ilerledi')

    def test_watermark_moves_after_a_window_that_changed_a_note(self):
        self.oversize_note()
        self.seed_receipts()
        result = self.window()
        self.assertTrue(result['wrote'])
        self.assertIsNotNone(self.store.read_meta('dream.last_run'))

    # -- Refresh kapsamı (§5.1) ------------------------------------------
    def test_refresh_normalises_blank_runs_and_trailing_space(self):
        self.oversize_note()
        path = self.vault / 'knowledge/concepts/buyuk.md'
        self.seed_receipts()
        self.window()
        after = path.read_text(encoding='utf-8')
        self.assertNotIn('\n\n\n\n', after, 'fazla bos satir kalmaliydi')
        self.assertNotIn('# Büyük kavram   \n', after, 'satir sonu bosluk kalmaliydi')
        self.assertIn('# Büyük kavram', after)

    def test_refresh_writes_a_relative_date_in_frontmatter_only(self):
        note = 'knowledge/concepts/tarihli.md'
        self.write_note(note, '---\n{"type": "semantic", "created": "2026-09-01",'
                              ' "updated": "dün"}\n---\n# Tarihli\n\n' + ('içerik. ' * 2000))
        self.store.ingest(self.note_record(note))
        self.assert_refresh_candidate(note)
        self.seed_receipts()
        self.window()
        after = (self.vault / note).read_text(encoding='utf-8')
        self.assertNotIn('"updated": "dün"', after, 'frontmatter tarihi duzeltilmedi')

    def test_refresh_reports_prose_dates_instead_of_rewriting_them(self):
        note = 'knowledge/concepts/anlatim.md'
        body = ('# Anlatım\n\nGeçen hafta müşteri fiyatları değişti.\n\n'
                + ('doldurma cümlesi. ' * 1200))
        self.write_note(note, body)
        self.store.ingest(self.note_record(note))
        self.seed_receipts()
        result = self.window()
        flat = json.dumps(result, ensure_ascii=False)
        self.assertIn('prose_dates', result)
        self.assertIn('Geçen hafta', flat)   # ozgun yazim, katlanmis degil
        self.assertIn('Geçen hafta müşteri fiyatları değişti.', body)
        self.assertIn('Geçen hafta müşteri fiyatları değişti.',
                      (self.vault / note).read_text(encoding='utf-8'),
                      'ajanin metni kod tarafindan degistirildi')

    def test_prose_date_detection_ignores_words_that_merely_start_the_same(self):
        found = self.dream.prose_dates(
            '# Not\n\nDünya çapında dağıtım. Dünleyici not aldı. Öğleden sonra toplandı.\n')
        self.assertEqual(found, [], found)

    def test_refresh_never_touches_generated_projections(self):
        # is_generated korumasi: projeksiyonlar hicbir zaman yeniden yazilmaz.
        for relative in ('knowledge/index.md', 'knowledge/log.md', 'daily/v3/2026-09-20.md'):
            self.write_note(relative, 'x' * 13000)
        self.seed_receipts()
        before = {r: self.sha(r) for r in ('knowledge/index.md', 'knowledge/log.md',
                                           'daily/v3/2026-09-20.md')}
        result = self.window()
        after = {r: self.sha(r) for r in before}
        self.assertEqual(after, before, 'uretilen projeksiyon degistirildi')
        self.assertEqual(result['applied'], [])

    def test_updated_is_untouched_when_the_body_did_not_change(self):
        # Siralama bozulmasi: yalniz gercekten degisen icerikte updated ilerler.
        note = 'knowledge/concepts/sade.md'
        self.write_note(note, '---\n{"type": "semantic", "updated": "2026-09-20"}\n---\n'
                               '# Sade\n\n' + ('temiz icerik. ' * 1200))
        self.store.ingest(self.note_record(note))
        self.seed_receipts()
        self.window()
        self.assertIn('"updated": "2026-09-20"', (self.vault / note).read_text(encoding='utf-8'))

    def test_apply_is_idempotent(self):
        note = 'knowledge/concepts/iki-kez.md'
        self.write_note(note, '---\n{"type": "semantic", "created": "2026-09-01",'
                              ' "updated": "dün"}\n---\n# İki kez\n\n'
                              + ('kalinti. ' * 2000))
        self.store.ingest(self.note_record(note))
        self.assert_refresh_candidate(note)
        self.seed_receipts()
        self.window()
        after_first = self.sha(note)
        self.window(force=True)
        self.assertEqual(self.sha(note), after_first, 'ikinci pencere ayni notu tekrar yazdi')

    # -- cli ------------------------------------------------------------
    def test_cli_apply_then_restore_round_trip(self):
        # Bu tek test gercek CLI'yi, dolayisiyla gercek saati cagirir; sagat geri alinacak
        # gunu `report_path` bildirir, test de duvar saatinden yeniden hesaplamaz. Once
        # `dt.date.today()` ile karsilastiriyordu ve yerel/UTC gunleri arisip kirmiziya
        # duserdi (her gun yerel 00:00-03:00 araliginda). Fixture'lar sabit kalir; bu
        # testin tek gercek saatle baglantisi yazilan yoldur.
        note = 'knowledge/concepts/cli.md'
        self.write_note(note, '# CLI\n\n' + ('icerik. ' * 2000))
        self.store.ingest(self.note_record(note))
        self.seed_receipts()
        self.assert_refresh_candidate(note)
        before = self.sha(note)
        apply = self.run_cli('dream', '--apply')
        self.assertEqual(apply['returncode'], 0, apply['stderr'])
        payload = json.loads(apply['stdout'])
        self.assertTrue(payload['wrote'], payload)
        self.assertIn('--restore', payload['restore_command'])
        report = self.vault / payload['report_path']
        self.assertTrue(report.is_file(), f'rapor beklenen yolda degil: {payload["report_path"]}')
        day = report.parent.name
        # Raporun yazildigi gun, urunun kendi ilan ettigi pencere olmali. Artik tarihi
        # yeniden hesaplamiyoruz, ama bu esitleme "gun secimi bir tesaduf degil" sözlesmesini
        # de sabitliyor: manifest'in ilan ettigi gun ile yazilan dizin ayrilirsa duser.
        manifest = json.loads((report.parent / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(day, manifest['window'], f'rapor {day} gunune yazildi, pencere {manifest["window"]}')
        restored = self.run_cli('dream', '--restore', day)
        self.assertEqual(restored['returncode'], 0, restored['stderr'])
        self.assertEqual(self.sha(note), before, 'CLI geri alimi pencere öncesi baytlari vermedi')

    def test_cli_read_only_dream_is_unaffected_by_the_new_flags(self):
        before = sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*'))
        result = self.run_cli('dream')
        self.assertEqual(result['returncode'], 0, result['stderr'])
        payload = json.loads(result['stdout'])
        self.assertFalse(payload['wrote'])
        self.assertEqual(payload['phase'], 1)
        self.assertEqual(sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*')), before)

    def run_cli(self, *args):
        result = subprocess.run([sys.executable, str(CLI), '--vault', str(self.vault),
                                 '--state', str(self.state), *args],
                                capture_output=True, text=True, timeout=120,
                                env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
        return {'returncode': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}


if __name__ == '__main__':
    unittest.main()
