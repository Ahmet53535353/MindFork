"""Synthetic evidence checks with the real client and an offline transport."""
import json
import unittest
import v3_jev_test as fixtures


class AnswerTest(unittest.TestCase):
    setUp = fixtures.AdvisorTest.setUp
    record = fixtures.AdvisorTest.record
    config = fixtures.AdvisorTest.config
    proposal = fixtures.AdvisorTest.proposal

    def claims(self):
        return [dict(text='Use short notes for Quartz.', citations=self.proposal()['evidence'])]

    def verify(self, claims=None, scores=(2, 0), mutate=None):
        import beyin_v3_jev as advisor
        def transport(url, body, key, timeout):
            self.calls.append(body)
            if mutate:
                mutate()
            return {'answers': {q: {'type': 'score', 'score': scores[int(q[1])]}
                                for q in body['questions']}}
        return advisor.verify_answer(self.store, self.claims() if claims is None else claims,
                                     project='quartz', transport=transport)

    def test_real_client_verdicts_and_no_canonical_writes(self):
        self.config('on')
        before = self.store.database.read_bytes()
        for scores, expected in [((2, 0), 'supported'), ((0, 2), 'contradicted'),
                                 ((0, 0), 'insufficient'), ((2, 2), 'uncertain')]:
            claims = self.claims()
            claims[0]['text'] += str(scores)  # separate cache keys
            result = self.verify(claims, scores)
            self.assertEqual(result['claims'][0]['verdict'], expected)
            self.assertTrue(result['claims'][0]['mechanical_verified'])
            self.assertFalse(result['approved'])
            self.assertFalse(result['memory_written'])
            self.assertFalse(result['rewrites'])
        self.assertEqual(before, self.store.database.read_bytes())

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
        result = self.verify(mutate=lambda: self.config('off'), scores=(0, 2),
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
        self.assertEqual(self.calls[0]['state']['candidates'][0]['id'], 'claim-1')
        self.verify(claims)
        self.assertEqual(len(self.calls), 1)

    def many(self, count):
        return [dict(text='Use short notes for Quartz, variant %d.' % i,
                     citations=self.proposal()['evidence']) for i in range(count)]

    def test_each_claim_travels_alone_so_twenty_fit_the_default_budget(self):
        self.config('on')
        result = self.verify(self.many(20))
        self.assertEqual([r['verdict'] for r in result['claims']], ['supported'] * 20)
        self.assertEqual(len(self.calls), 20)
        for body in self.calls:
            self.assertEqual(len(body['state']['candidates']), 1)
            self.assertEqual(sorted(body['questions']), ['f0_c0', 'f1_c0'])

    def test_conflict_is_asked_on_its_own_compatibility_scale(self):
        import beyin_v3_jev_client as client
        self.config('on')
        self.verify()
        support, conflict = (self.calls[0]['questions'][k] for k in ('f0_c0', 'f1_c0'))
        self.assertEqual(support['criteria'], client.REVIEW_CRITERIA)
        self.assertEqual(conflict['criteria'], client.CONFLICT_CRITERIA)
        self.assertIn('both be true', conflict['instructions'])
        self.assertIn('negation', conflict['instructions'])

    def test_middle_band_scores_never_become_a_clear_verdict(self):
        self.config('on')
        for number, (scores, expected) in enumerate([((1.6, 1.2), 'uncertain'), ((1.2, 1.6), 'uncertain'),
                                                     ((1.2, 0), 'uncertain'), ((0.4, 1.4), 'uncertain'),
                                                     ((0.9, 0.9), 'insufficient'), ((1.5, 0.99), 'supported'),
                                                     ((0.99, 1.5), 'contradicted')]):
            claims = self.claims()
            claims[0]['text'] += ' case %d' % number  # separate cache keys
            self.assertEqual(self.verify(claims, scores)['claims'][0]['verdict'], expected, scores)

    def test_one_failed_request_degrades_only_its_own_claim(self):
        import beyin_v3_jev as advisor
        self.config('on')
        def transport(url, body, key, timeout):
            if 'variant 1.' in body['state']['candidates'][0]['statement']:
                raise TimeoutError('PRIVATE provider error')
            return {'answers': {q: {'type': 'score', 'score': (2, 0)[int(q[1])]} for q in body['questions']}}
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
