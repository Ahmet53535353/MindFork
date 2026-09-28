"""Offline preference and hook behavior contracts; synthetic vaults only."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'template/.claude/scripts'))
import beyin_v3_preferences as prefs


class PreferencesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.vault = self.root / 'Örnek Vault'; self.vault.mkdir()
        self.state = self.root / 'state'

    def cli(self, *args):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/beyin_v3.py'),
            '--vault', str(self.vault), '--state', str(self.state), *args],
            capture_output=True, text=True, encoding='utf-8', timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def hook(self, event, harness='codex', extra=(), prompt=''):
        payload = {'hook_event_name': event, 'session_id': 'synthetic', 'event_id': event,
                   'conversationId': 'synthetic', 'invocationNum': 0, 'fullyIdle': True,
                   'prompt': prompt}
        r = subprocess.run([sys.executable, str(ROOT / 'template/.claude/scripts/beyin_v3_hook.py'),
            '--vault', str(self.vault), '--state', str(self.state), '--harness', harness, *extra],
            input=json.dumps(payload), capture_output=True, text=True, encoding='utf-8',
            env=dict(os.environ, BEYIN_V3_NO_SPAWN='1'), timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_default_and_custom_roundtrip(self):
        self.assertEqual(prefs.read(self.vault), prefs.PROFILES['normal'])
        self.cli('preferences', '--profile', 'economical', '--interval-minutes', '30')
        result = self.cli('preferences')
        self.assertEqual(result['preferences']['interval_minutes'], 30)
        self.assertEqual(result['preferences']['context_chars'], 2000)
        self.assertFalse(result['model_calls'])
        self.assertFalse(result['timer_installed'])

    def test_daily_log_is_on_by_default_in_every_profile(self):
        # Insan kullanimi E2E'si: gunluk log en gorunur hatirlatma ozelligiydi ama
        # hicbir profilde varsayilan kapaliydi, o yuzden hic kimse bulamadi. Secim makine
        # yerel durumda duruyor ama her profilde acik.
        self.assertTrue(prefs.DEFAULT_DAILY_LOG)
        self.assertTrue(prefs.read_daily_log(self.state, self.vault)[0])
        self.assertTrue(self.cli('preferences')['daily_log'])

    def test_daily_log_opt_out_survives_profile_changes_and_stays_off(self):
        # Ayar artik belirlendigi icin profil degisimi onu sifirlamamali.
        self.assertFalse(self.cli('preferences', '--daily-log', 'off')['daily_log'])
        for name in ('economical', 'manual', 'normal'):
            self.assertFalse(self.cli('preferences', '--profile', name)['daily_log'], name)
        self.assertFalse(self.cli('preferences')['daily_log'])
        self.assertFalse(prefs.read_daily_log(self.state, self.vault)[0])

    def test_daily_log_chosen_is_false_until_the_user_sets_it(self):
        # The notice goes only to a user who never stated a choice, and reading it writes
        # nothing. Unlike the old key-presence proxy, an unrelated preference no longer counts
        # as an answer: the state file is the answer, and it holds this setting alone.
        self.assertFalse(prefs.daily_log_chosen(self.state, self.vault))
        self.cli('preferences')
        self.assertFalse(prefs.daily_log_chosen(self.state, self.vault))
        self.assertFalse((self.state / 'daily-log.json').exists())
        self.cli('preferences', '--context-chars', '6000')
        self.assertFalse(prefs.daily_log_chosen(self.state, self.vault),
                         'ilgisiz bir tercih bu soruyu yanitlamamali')
        self.cli('preferences', '--daily-log', 'off')
        self.assertTrue(prefs.daily_log_chosen(self.state, self.vault))
        self.cli('preferences', '--context-chars', '7000')
        self.assertTrue(prefs.daily_log_chosen(self.state, self.vault), 'kayit durmali')

    def test_daily_log_never_enters_the_vault_preference_schema(self):
        # Upstream #132 found this trap: a key in .beyin-preferences.json that the build you
        # rolled back to does not know makes validate() reject the file, and doctor,
        # preferences and the SessionStart hook all fail behind it. So the opt-in lives in the
        # runtime state and does not even create the file; a file saved before the move is
        # still honoured, and the next save drops the key, which leaves it as a rolled-back
        # build expects.
        self.cli('preferences', '--daily-log', 'off')
        self.assertFalse((self.vault / '.beyin-preferences.json').exists(),
                         'gunluk log tercihi vault tercih dosyasini olusturmamali')
        self.cli('preferences', '--context-chars', '6000')
        stored = json.loads((self.vault / '.beyin-preferences.json').read_text(encoding='utf-8'))
        self.assertEqual(set(stored), {'auto_sync', 'interval_minutes', 'context_mode',
                                        'context_chars', 'secret_filter'})
        self.vault.joinpath('.beyin-preferences.json').write_text(
            json.dumps(dict(stored, daily_log=False)), encoding='utf-8')
        (self.state / 'daily-log.json').unlink()
        self.assertFalse(prefs.read_daily_log(self.state, self.vault)[0], 'eski dosyadaki secim kaybolmamali')
        self.cli('preferences', '--context-chars', '7000')
        healed = json.loads((self.vault / '.beyin-preferences.json').read_text(encoding='utf-8'))
        self.assertNotIn('daily_log', healed, 'bir sonraki kayit eski anahtari temizlemeli')
        self.assertTrue((self.state / 'daily-log.json').exists(), 'eski secim duruma tasinmali')
        self.assertFalse(prefs.read_daily_log(self.state, self.vault)[0],
                         'anahtar temizlendi ama secim geri donmemeli')

    def test_secret_filter_is_explicit_and_survives_profile_changes(self):
        self.assertFalse(self.cli('preferences')['preferences']['secret_filter'])
        self.assertTrue(self.cli('preferences', '--secret-filter', 'on')['preferences']['secret_filter'])
        self.assertTrue(self.cli('preferences', '--profile', 'economical')['preferences']['secret_filter'])
        self.assertFalse(self.cli('preferences', '--secret-filter', 'off')['preferences']['secret_filter'])

    def test_invalid_settings_do_not_replace_user_preferences(self):
        prefs.save(self.vault, {}, 'economical')
        before = (self.vault / '.beyin-preferences.json').read_bytes()
        for changes in ({'interval_minutes': -1}, {'interval_minutes': True}, {'context_chars': 999},
                        {'context_mode': 'unknown'}, {'unknown': 1}, {'auto_sync': 'false'},
                        {'secret_filter': 'true'}):
            with self.assertRaises(ValueError):
                prefs.save(self.vault, changes)
        self.assertEqual(before, (self.vault / '.beyin-preferences.json').read_bytes())

    def test_manual_hooks_do_not_enqueue_or_inject_across_clients(self):
        prefs.save(self.vault, {}, 'manual')
        for harness in ('codex', 'claude', 'antigravity'):
            event = 'PreInvocation' if harness == 'antigravity' else 'SessionStart'
            result = self.hook(event, harness)
            self.assertNotIn('hookSpecificOutput', result)
            self.assertNotIn('injectSteps', result)
            self.hook('Stop', harness)
        self.assertEqual(list((self.state / 'hook-queue').glob('*.json')), [])

    def test_economical_still_answers_a_returning_user_mid_session(self):
        # Insan kullanimi E2E'si: ekonomik profilde oturum ortasinda "tatilden
        # donduk, neler yapmistik" yazan kullaniciya HICBIR sey gelmiyordu;
        # profil normal olunca ayni cumle companion kaynaklarini getiriyordu.
        prefs.save(self.vault, {}, 'economical')
        self.hook('SessionStart')            # araligi bu oturumda tuketir
        for prompt in ('bir hafta once ne yapmistik', 'neler yapmistik', 'we just got back, what did we do',
                       'neredeydik', 'kaldigimiz yer nerede'):
            result = self.hook('UserPromptSubmit', prompt=prompt)
            text = result.get('hookSpecificOutput', {}).get('additionalContext', '')
            self.assertIn('Receipt session=', text, prompt)
            self.assertLessEqual(len(text), 2000, prompt)
        # Ilgisiz mesaj ekonomik profilde sessiz kalmaya devam eder.
        self.assertEqual(self.hook('UserPromptSubmit', prompt='bugun hava nasil'), {})

    def test_economical_continuity_turn_says_memory_may_be_stale(self):
        # Aralik kapisi gecildigi icin otomatik kontrol yapilmadi; teslim edilen
        # baglamda indeksli hafizanin bayat olabilecegi soylenmeli.
        prefs.save(self.vault, {}, 'economical')
        self.hook('SessionStart')
        text = self.hook('UserPromptSubmit', prompt='neredeydik') \
            .get('hookSpecificOutput', {}).get('additionalContext', '')
        self.assertIn('may be stale', text)
        # Normal profilde her tur senkronlandigi icin bu uyari gelmez.
        prefs.save(self.vault, {'context_mode': 'turn', 'interval_minutes': 0})
        self.hook('SessionStart')
        self.hook('UserPromptSubmit', prompt='menu icerigi')
        self.assertNotIn('may be stale', str(self.hook('UserPromptSubmit', prompt='neredeydik')))

    def test_economical_injects_only_start_and_caps_entire_context(self):
        prefs.save(self.vault, {}, 'economical')
        self.assertEqual(self.hook('UserPromptSubmit'), {})
        result = self.hook('SessionStart')
        text = result['hookSpecificOutput']['additionalContext']
        self.assertIn('Receipt session=', text)
        self.assertLessEqual(len(text), 2000)

    def test_interval_atomic_and_new_session_or_failure_refreshes(self):
        settings = prefs.PROFILES['economical']
        self.assertTrue(prefs.claim_check(self.state, settings, 'Stop', now=1000))
        self.assertFalse(prefs.claim_check(self.state, settings, 'Stop', now=1899))
        with ThreadPoolExecutor(max_workers=4) as pool:
            claimed = list(pool.map(lambda _: prefs.claim_check(self.state, settings, 'Stop', now=1900), range(4)))
        self.assertEqual(sum(claimed), 1)
        self.assertTrue(prefs.claim_check(self.state, settings, 'SessionStart', now=1901))
        (self.state / 'hook-error.json').write_text('{}')
        self.assertTrue(prefs.claim_check(self.state, settings, 'Stop', now=1902))
        self.assertFalse(prefs.claim_check(self.state, prefs.PROFILES['manual'], 'SessionStart', now=2900))

    def test_manual_explicit_context_still_refreshes_current_source(self):
        prefs.save(self.vault, {}, 'manual')
        (self.vault / 'choice.md').write_text('Synthetic project format CSV.', encoding='utf-8')
        self.cli('sync')
        (self.vault / 'choice.md').write_text('Synthetic project format JSON.', encoding='utf-8')
        result = self.cli('context', 'Synthetic project format')
        self.assertIn('JSON', json.dumps(result))
        self.assertNotIn('CSV', json.dumps(result))

    def test_started_worker_respects_disable_but_explicit_drain_is_available(self):
        self.hook('Stop')
        prefs.save(self.vault, {}, 'manual')
        self.assertTrue(self.hook('Stop', extra=('--worker',))['paused'])
        self.assertEqual(len(list((self.state / 'hook-queue').glob('*.json'))), 1)
        self.assertEqual(self.hook('Stop', extra=('--drain-queue',))['pending'], 0)

    def test_install_preserves_preferences_and_ships_working_command(self):
        prefs.save(self.vault, {}, 'economical')
        before = (self.vault / '.beyin-preferences.json').read_bytes()
        r = subprocess.run([sys.executable, str(ROOT / 'scripts/install_v3.py'), '--vault',
                            str(self.vault), '--state', str(self.state)], capture_output=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(before, (self.vault / '.beyin-preferences.json').read_bytes())
        r = subprocess.run([sys.executable, str(self.vault / 'beyin.py'), 'preferences', '--human'],
                           capture_output=True, text=True, encoding='utf-8', timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('2000 karakter', r.stdout)
        self.assertIn('preferences', self.cli('doctor'))

    def test_project_context_preference_is_machine_local_and_rollback_safe(self):
        self.assertEqual(self.cli('preferences')['project_context'], 'off')
        self.assertFalse((self.vault / '.beyin-preferences.json').exists())
        saved = self.cli('preferences', '--project-context', 'on')
        self.assertEqual(saved['status'], 'saved')
        self.assertEqual(saved['project_context'], 'on')
        self.assertFalse((self.vault / '.beyin-preferences.json').exists(), 'must not modify vault preference schema')
        self.assertTrue((self.state / 'project-context.json').exists())
        self.cli('preferences', '--project-context', 'off')
        self.assertEqual(self.cli('preferences')['project_context'], 'off')

    def test_hygiene_opt_ins_are_machine_local_and_rollback_safe(self):
        # V3.5.1 and older validate() reject any other .beyin-preferences.json key, so a
        # rollback after enabling hygiene must find only these keys (maintainer change).
        released_keys = {'auto_sync', 'interval_minutes', 'context_mode', 'context_chars', 'secret_filter'}
        current = self.cli('preferences')
        self.assertEqual(current['hygiene'], {'word_cap_warning': False, 'max_words': 500,
                                              'folder_questions': False, 'promotion': False})
        saved = self.cli('preferences', '--word-cap-warning', 'on', '--max-words', '800',
                         '--folder-questions', 'on', '--promotion', 'on')
        self.assertEqual(saved['status'], 'saved')
        self.assertEqual(saved['hygiene'], {'word_cap_warning': True, 'max_words': 800,
                                            'folder_questions': True, 'promotion': True})
        self.assertFalse((self.vault / '.beyin-preferences.json').exists(), 'must not modify vault preference schema')
        self.cli('preferences', '--profile', 'economical', '--context-chars', '3000')
        self.assertEqual(set(json.loads((self.vault / '.beyin-preferences.json').read_text(encoding='utf-8'))), released_keys)
        self.assertTrue(self.cli('preferences')['hygiene']['word_cap_warning'], 'a profile switch leaves hygiene alone')
        before = (self.state / 'hygiene.json').read_bytes()
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/beyin_v3.py'), '--vault', str(self.vault),
                                 '--state', str(self.state), 'preferences', '--max-words', '5', '--promotion', 'off'],
                                capture_output=True, text=True, encoding='utf-8', timeout=20)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(before, (self.state / 'hygiene.json').read_bytes(), 'an invalid value changes nothing')
        (self.state / 'hygiene.json').write_text('{"word_cap_warning": "yes"}', encoding='utf-8')
        damaged = self.cli('preferences')
        self.assertFalse(damaged['hygiene']['word_cap_warning'])
        self.assertIn('hygiene_notice', damaged)
        self.assertNotIn('Soru sirasi', json.dumps(self.hook('SessionStart', 'claude')))


if __name__ == '__main__':
    unittest.main()
