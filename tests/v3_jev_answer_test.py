"""Synthetic evidence checks with the real client and an offline transport."""
import json
import unittest
from unittest.mock import patch
import v3_jev_test as fixtures


class AnswerTest(unittest.TestCase):
    setUp = fixtures.AdvisorTest.setUp
    record = fixtures.AdvisorTest.record
    config = fixtures.AdvisorTest.config
    proposal = fixtures.AdvisorTest.proposal

    def claims(self):
        return [dict(text='Use short notes for Quartz.', citations=self.proposal()['evidence'])]

    def answer(self, relation):
        choice, confidence = relation
        rest = round((1 - confidence) / 2, 4)
        return dict(type='choice', choice=choice, confidence=confidence,
                    probabilities={k: confidence if k == choice else rest
                                   for k in ('supports', 'contradicts', 'says_nothing')})

    def verify(self, claims=None, relation=('supports', 0.95), mutate=None):
        import beyin_v3_jev as advisor
        def transport(url, body, key, timeout):
            self.calls.append(body)
            if mutate:
                mutate()
            return {'answers': {q: self.answer(relation) for q in body['questions']}}
        return advisor.verify_answer(self.store, self.claims() if claims is None else claims,
                                     project='quartz', transport=transport)

    def note(self, ident, text):
        path = self.vault / (ident + '.md')
        path.write_text(text, encoding='utf-8')
        return self.store.ingest(dict(id=ident, text=text, source=path.name, project='quartz'))

    def many(self, count):
        return [dict(text='Use short notes for Quartz, variant %d.' % i,
                     citations=self.proposal()['evidence']) for i in range(count)]

    def test_real_client_verdicts_and_no_canonical_writes(self):
        self.config('on')
        before = self.store.database.read_bytes()
        for relation, expected in [(('supports', 0.95), 'supported'), (('contradicts', 0.95), 'contradicted'),
                                   (('says_nothing', 0.95), 'insufficient'), (('supports', 0.8), 'supported')]:
            claims = self.claims()
            claims[0]['text'] += str(relation)  # separate cache keys
            result = self.verify(claims, relation)
            self.assertEqual(result['claims'][0]['verdict'], expected)
            self.assertEqual(result['claims'][0]['relation'], relation[0])
            self.assertEqual(result['claims'][0]['confidence'], relation[1])
            self.assertTrue(result['claims'][0]['mechanical_verified'])
            self.assertFalse(result['approved'])
            self.assertFalse(result['memory_written'])
            self.assertFalse(result['rewrites'])
        self.assertEqual(before, self.store.database.read_bytes())

    def test_low_confidence_never_becomes_a_clear_verdict(self):
        self.config('on')
        for number, choice in enumerate(('supports', 'contradicts', 'says_nothing')):
            claims = self.claims()
            claims[0]['text'] += ' case %d' % number
            item = self.verify(claims, (choice, 0.79))['claims'][0]
            self.assertEqual((item['verdict'], item['relation'], item['diagnostics']),
                             ('uncertain', choice, ['low_confidence']))

    def test_off_and_shadow_cannot_verify_semantics(self):
        self.assertEqual(self.verify()['claims'][0]['verdict'], 'uncertain')
        self.assertFalse(self.calls)
        self.assertFalse((self.store.state_dir / '.cache').exists())
        self.config('shadow')
        self.assertEqual(self.verify()['claims'][0]['verdict'], 'uncertain')
        self.assertEqual(len(self.calls), 1)

    def test_invalid_evidence_is_not_sent(self):
        self.config('on')
        for field, value in [('record_id', 'absent'), ('source_sha256', 'wrong'), ('quote', 'invented')]:
            claims = self.claims()
            claims[0]['citations'][0][field] = value
            self.assertEqual(self.verify(claims)['claims'][0]['verdict'], 'insufficient')
        claims = self.claims()
        claims[0]['citations'] = []
        self.assertEqual(self.verify(claims)['claims'][0]['diagnostics'], ['citation_missing'])
        self.assertFalse(self.calls)

    def test_ineligible_sources_are_not_sent(self):
        self.config('on')
        for ident, fields in [('foreign', {'project': 'other'}), ('private', {'visibility': 'private'}),
                              ('untrusted', {'trust': 'untrusted'})]:
            row = self.record(ident, **fields)
            claims = self.claims()
            claims[0]['citations'][0].update(record_id=ident, source_sha256=row['source_sha256'])
            self.assertEqual(self.verify(claims)['claims'][0]['verdict'], 'insufficient')
        self.assertFalse(self.calls)

    def test_request_validated_before_any_call(self):
        self.config('on')
        for claims in [[], self.claims() * 21, self.claims() + [{'text': 'bad'}],
                       [dict(text='x' * 32001, citations=[])],
                       [dict(text='password=123456789012', citations=[])]]:
            with self.assertRaises(ValueError):
                self.verify(claims)
        self.assertFalse(self.calls)

    def test_source_and_config_races_drop_verdicts(self):
        self.config('on')
        result = self.verify(mutate=lambda: (self.vault / 'a.md').write_text('changed', encoding='utf-8'))
        self.assertEqual(result['claims'][0]['verdict'], 'degraded')
        self.record('a')
        result = self.verify(mutate=lambda: self.config('off'), relation=('contradicts', 0.95),
                             claims=[dict(text='Different claim.', citations=self.proposal()['evidence'])])
        self.assertEqual(result['claims'][0]['verdict'], 'degraded')

    def test_visibility_revoked_during_call_drops_verdict(self):
        self.config('on')
        result = self.verify(mutate=lambda: self.record('a', visibility='private'))
        self.assertEqual(result['claims'][0]['verdict'], 'degraded')

    def test_failure_is_degraded_and_diagnostics_are_sanitized(self):
        self.config('on')
        def fail():
            raise TimeoutError('PRIVATE provider error')
        result = self.verify(mutate=fail)
        self.assertEqual(result['claims'][0]['verdict'], 'degraded')
        self.assertNotIn('PRIVATE', json.dumps(result))

    def test_mixed_claims_batch_only_valid_evidence_and_cache(self):
        self.config('on')
        claims = [dict(text='No citation.', citations=[])] + self.claims()
        result = self.verify(claims)
        self.assertEqual([r['verdict'] for r in result['claims']], ['insufficient', 'supported'])
        self.assertEqual(list(self.calls[0]['state']['items']), ['k1'])
        self.verify(claims)
        self.assertEqual(len(self.calls), 1)

    def test_twenty_claims_fit_in_batches_of_eight(self):
        self.config('on')
        result = self.verify(self.many(20))
        self.assertEqual([r['verdict'] for r in result['claims']], ['supported'] * 20)
        self.assertEqual(sorted(len(body['questions']) for body in self.calls), [4, 8, 8])
        for body in self.calls:
            self.assertEqual(set(body['questions']), set(body['state']['items']))

    def test_text_around_the_quote_travels_with_it(self):
        self.config('on')
        row = self.note('plan', 'Old plan: the newsletter goes out on Monday. That plan was cancelled in March.')
        claims = [dict(text='The newsletter goes out on Monday.', citations=[dict(
            record_id='plan', source_sha256=row['source_sha256'], quote='the newsletter goes out on Monday')])] + self.claims()
        self.verify(claims)
        sent = self.calls[0]['state']['items']
        self.assertEqual(sent['k0']['evidence']['quotes'], ['the newsletter goes out on Monday'])
        self.assertIn('cancelled in March', sent['k0']['evidence']['source_context'][0])
        # A quote that is the whole record has nothing around it to add.
        self.assertNotIn('source_context', sent['k1']['evidence'])

    def test_long_sources_send_a_window_not_the_note(self):
        self.config('on')
        row = self.note('long', 'START ' + 'filler words ' * 200 + 'Quartz keeps notes short. ' + 'more filler ' * 200 + 'END')
        self.verify([dict(text='Quartz notes are short.', citations=[dict(
            record_id='long', source_sha256=row['source_sha256'], quote='Quartz keeps notes short.')])])
        window = self.calls[0]['state']['items']['k0']['evidence']['source_context'][0]
        self.assertLessEqual(len(window), 2 * 400 + len('Quartz keeps notes short.'))
        self.assertNotIn('START', window)
        self.assertNotIn('END', window)

    def test_sensitive_text_around_a_quote_is_never_sent(self):
        self.config('on')
        row = self.note('keys', 'Quartz keeps notes short. password=123456789012')
        claims = [dict(text='Quartz notes are short.', citations=[dict(
            record_id='keys', source_sha256=row['source_sha256'], quote='Quartz keeps notes short.')])] + self.claims()
        result = self.verify(claims)
        self.assertEqual([(r['verdict'], r['diagnostics']) for r in result['claims']],
                         [('degraded', ['context_sensitive']), ('supported', [])])
        self.assertNotIn('password', json.dumps(self.calls))
        self.assertEqual(list(self.calls[0]['state']['items']), ['k1'])

    def test_a_batch_over_the_input_budget_is_halved_not_dropped(self):
        (self.store.state_dir / 'jev.json').write_text(json.dumps({'mode': 'on', 'max_input_chars': 2600}), encoding='utf-8')
        result = self.verify(self.many(8))
        self.assertEqual([r['verdict'] for r in result['claims']], ['supported'] * 8)
        self.assertGreater(len(self.calls), 1)
        self.assertEqual(sum(len(body['questions']) for body in self.calls), 8)

    def test_one_failed_request_degrades_only_its_own_batch(self):
        import beyin_v3_jev as advisor
        self.config('on')
        def transport(url, body, key, timeout):
            if 'k1' in body['questions']:
                raise TimeoutError('PRIVATE provider error')
            return {'answers': {q: self.answer(('supports', 0.95)) for q in body['questions']}}
        with patch.object(advisor, 'BATCH', 1):
            result = advisor.verify_answer(self.store, self.many(3), project='quartz', transport=transport)
        self.assertEqual([r['verdict'] for r in result['claims']], ['supported', 'degraded', 'supported'])
        self.assertNotIn('PRIVATE', json.dumps(result))

    def test_eligibility_is_read_once_per_phase_not_per_claim(self):
        self.config('on')
        seen = []
        original = self.store._retrieve
        def counting(*args, **kwargs):
            seen.append(1)
            return original(*args, **kwargs)
        self.store._retrieve = counting
        self.verify(self.many(8))
        self.assertEqual(len(seen), 2)


if __name__ == '__main__':
    unittest.main()
