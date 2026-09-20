"""Explicit optional advisor; local retrieval and source authority remain in V3."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json

import beyin_v3_jev_client as client
from beyin_v3_secrets import redact


def _safe(store, value):
    # Reject instead of silently judging redacted evidence. Never persist matches.
    _, count = redact(json.dumps(value, ensure_ascii=False), store.state_dir)
    if count:
        raise ValueError('advisor_sensitive_input')


def _fresh(store, records):
    try:
        for record in records:
            path = store.vault_root / store._source(record['source'])
            if hashlib.sha256(path.read_bytes()).hexdigest() != record['source_sha256']:
                return False
        return True
    except (ValueError, OSError, KeyError):
        return False


def _clear(advice, code):
    return dict(advice, scores={}, facet_scores={}, degraded=True,
                diagnostics=advice.get('diagnostics', []) + [code])


def advise_context(store, query, *, project, audience='internal', statuses=None,
                   limit=5, budget_chars=8000, transport=None):
    """Only rerank the delivered local candidates; never broaden eligibility."""
    if not isinstance(project, str) or not project.strip():
        raise ValueError('advisor_requires_explicit_project')
    if audience not in ('public', 'internal'):
        raise ValueError('advisor_private_audience_not_supported')
    params = dict(project=project, audience=audience, statuses=statuses,
                  limit=limit, budget_chars=budget_chars)
    result = store.retrieve(query, **params)
    records = result['records']
    before = [(r['id'], r['revision'], r['source_sha256']) for r in records]
    mode = client.inspect_config(store.state_dir)
    if not mode['valid'] or mode['mode'] == 'off':
        result['jev'] = dict(mode=mode['mode'], degraded=not mode['valid'],
                             diagnostics=mode.get('diagnostics', []), scores={})
        return result
    try:
        cards = [dict(id=r['id'], title=r.get('title', ''), statement=r['text'],
                      scope='project:' + project, domains=[r.get('kind', 'note')]) for r in records]
        _safe(store, [query, cards])
    except (ValueError, OSError):
        result['jev'] = _clear({'mode': mode['mode']}, 'advisor_sensitive_or_invalid_input')
        return result
    advice = client.evaluate(store.state_dir, query, cards, scope='project:' + project,
                             source_versions={r['id']: [r['source_sha256'], r['revision']] for r in records},
                             transport=transport)
    # Re-run all eligibility gates, including index revisions/supersession, after I/O.
    current = store.retrieve(query, **params)
    after = [(r['id'], r['revision'], r['source_sha256']) for r in current['records']]
    if before != after or not _fresh(store, records):
        result = current
        advice = _clear(advice, 'source_or_index_changed')
    elif client.inspect_config(store.state_dir) != mode:
        advice = _clear(advice, 'configuration_changed')
    elif advice['mode'] == 'on' and not advice['degraded']:
        # Same set, same budget, source citations travel with their records.
        result['records'] = sorted(records, key=lambda r: -advice['scores'].get(r['id'], 0))
        result['citations'] = [dict(id=r['id'], source=r['source']) for r in result['records']]
    result['jev'] = advice
    return result


AUTO_MIN_CHARS = 12  # a one or two word prompt carries no reliable topic
AUTO_PROMPT = 2000
AUTO_EXCERPT = 600
AUTO_POOL = 8
AUTO_LIMIT = 5
# Live synthetic calibration: greetings scored <= 0.16 on the gate and real topics >= 0.39;
# past the gate, off-topic notes stayed <= 0.31 and on-topic ones >= 0.76. A strict local match
# already has lexical evidence, so it is kept unless clearly off topic. A loose match enters
# only when Jev is confident. Shadow mode is how a vault checks these on its own notes.
AUTO_GATE = 0.25
AUTO_KEEP = 0.4
AUTO_RESCUE = 0.6


def auto_context(store, harness, query, context, *, budget_chars, timeout_cap=2.0, transport=None):
    """Per-turn hook path: strict local matches plus a loose lexical pool, judged in one call.

    The strict matcher wants two shared words, so a paraphrased question finds nothing. The
    loose pool passes the same visibility, trust, freshness and supersession gates; only the
    word-overlap bar is lower, and a loose record enters only above AUTO_RESCUE. Any failure
    or doubt returns the strict result untouched.
    """
    mode = client.inspect_config(store.state_dir)
    if (not mode['valid'] or mode['mode'] == 'off' or 'auto_context' not in mode['features']
            or not isinstance(query, str) or len(query.strip()) < AUTO_MIN_CHARS):
        return context
    strict = context.get('records') or []
    known = {r['id'] for r in strict}
    loose = [r for r in store.context_for(harness, query, limit=AUTO_POOL, budget_chars=budget_chars)['records']
             if r['id'] not in known and not str(r.get('source', '')).startswith(store.STRICT_EXCLUDE)]
    records = (strict + loose)[:AUTO_POOL]
    keys = {'k' + str(i): r for i, r in enumerate(records) if str(r.get('text', '')).strip()}
    if not keys or any(r.get('visibility') == 'private' for r in records):
        return context
    cards = [dict(id=k, title=str(r.get('title', '')), excerpt=r['text'][:AUTO_EXCERPT]) for k, r in keys.items()]
    outcome = dict(event='auto_context', mode=mode['mode'], strict=len(strict), loose=len(records) - len(strict))
    try:
        _safe(store, [query, cards])
    except (ValueError, OSError):
        client.log_event(store.state_dir, dict(outcome, outcome='skipped_sensitive'))
        return context
    advice = client.evaluate(store.state_dir, query[:AUTO_PROMPT], cards, scope='auto', purpose='auto_context',
                             source_versions={k: [r['source_sha256'], r['revision']] for k, r in keys.items()},
                             transport=transport, timeout_cap=timeout_cap)
    scores = advice['scores']
    if advice['degraded'] or advice['mode'] == 'off' or not scores:
        return context
    passed = scores['topical'] >= AUTO_GATE
    by_record = {r['id']: scores[k] for k, r in keys.items()}
    keep = [r for r in records if passed and by_record.get(r['id'], 1.0 if r['id'] in known else 0.0)
            >= (AUTO_KEEP if r['id'] in known else AUTO_RESCUE)]
    dropped = len([r for r in strict if r not in keep])
    rescued = len([r for r in keep if r['id'] not in known])
    client.log_event(store.state_dir, dict(outcome, outcome='scored', gate_passed=passed, dropped=dropped, rescued=rescued))
    if advice['mode'] != 'on' or not (dropped or rescued):
        return context
    if not _fresh(store, records) or client.inspect_config(store.state_dir) != mode:
        return context
    keep.sort(key=lambda r: -by_record.get(r['id'], 1.0))
    selected, used = [], 0
    for record in keep[:AUTO_LIMIT]:
        size = len(json.dumps(record, ensure_ascii=False)) + len(record['id']) + len(record['source']) + 24
        if used + size <= budget_chars:
            selected.append(record)
            used += size
    result = dict(context, records=selected, citations=[dict(id=r['id'], source=r['source']) for r in selected],
                  abstained=not selected, used_chars=used, jev=dict(dropped=dropped, added=rescued))
    return result


def _eligible(store, project):
    # Existing runtime gates enforce scope, visibility, trust, freshness and supersession.
    eligible = store._retrieve('', project=project, audience='internal',
                               limit=100000, budget_chars=10000000, snapshot=True)['records']
    return {r['id']: r for r in eligible if not r.get('text_truncated')}


def _verified_evidence(store, evidence, project, by_id=None):
    by_id = _eligible(store, project) if by_id is None else by_id
    refs = []
    for item in evidence:
        if not isinstance(item, dict) or set(item) != {'record_id', 'source_sha256', 'quote'}:
            raise ValueError('invalid_evidence_fields')
        record = by_id.get(item['record_id'])
        quote = item['quote']
        if (record is None or item['source_sha256'] != record['source_sha256']
                or not isinstance(quote, str) or not quote.strip() or quote not in record['text']):
            raise ValueError('evidence_not_current_or_exact')
        raw = (store.vault_root / store._source(record['source'])).read_text(encoding='utf-8')
        if quote not in raw:
            raise ValueError('evidence_not_in_source')
        refs.append(record)
    if not _fresh(store, refs):
        raise ValueError('evidence_changed')
    return refs


def review_candidate(store, proposal, *, project, transport=None):
    """Judge exact source evidence, without ingesting or approving a proposal."""
    if not isinstance(proposal, dict) or set(proposal) != {'status', 'project', 'claim', 'evidence'}:
        raise ValueError('invalid_proposal_fields')
    proposal = json.loads(json.dumps(proposal, ensure_ascii=False))
    if len(json.dumps(proposal, ensure_ascii=False)) > 24000:
        raise ValueError('proposal_too_large')
    if (proposal['status'] != 'proposed' or not isinstance(project, str) or not project.strip()
            or proposal['project'] != project or not isinstance(proposal['claim'], str)
            or not proposal['claim'].strip()):
        raise ValueError('proposal_scope_or_status_invalid')
    evidence = proposal['evidence']
    if not isinstance(evidence, list) or not 1 <= len(evidence) <= 8:
        raise ValueError('proposal_requires_evidence')

    refs = _verified_evidence(store, evidence, project)
    _safe(store, proposal)
    versions = {r['id']: [r['source_sha256'], r['revision']] for r in refs}
    mode = client.inspect_config(store.state_dir)
    card = dict(id='proposal', title='Unapproved proposal', scope='project:' + project, domains=[],
                statement=json.dumps({'stored_claim': proposal['claim'],
                                      'evidence_quotes': [e['quote'] for e in evidence]}, ensure_ascii=False))
    result = client.evaluate(store.state_dir, proposal['claim'], [card], scope='project:' + project,
                             source_versions=versions, purpose='evidence_review',
                             facets=['Do the exact quotes support the entire claim in its original scope?'],
                             transport=transport)
    try:
        now = _verified_evidence(store, evidence, project)
        if versions != {r['id']: [r['source_sha256'], r['revision']] for r in now}:
            raise ValueError('evidence_changed')
        if client.inspect_config(store.state_dir) != mode:
            raise ValueError('configuration_changed')
    except (ValueError, OSError):
        result = _clear(result, 'source_or_configuration_changed')
    return dict(status='advisory_only', approved=False, memory_written=False, jev=result)


BATCH = 8            # claims per request; hard items weaken late in a longer list
CONTEXT_CHARS = 400  # source text kept on each side of a quote
CONTEXT_LIMIT = 4000
CONFIDENCE_GATE = 0.8
VERDICTS = dict(supports='supported', contradicts='contradicted', says_nothing='insufficient')


def _context(refs, citations):
    """Text around each quote. A literal quote can sit in a plan its own note cancels."""
    windows, used = [], 0
    for record, cite in zip(refs, citations):
        text, quote = record['text'], cite['quote']
        at = text.index(quote)
        window = text[max(0, at - CONTEXT_CHARS):at + len(quote) + CONTEXT_CHARS].strip()
        if window != quote.strip() and window not in windows and used + len(window) <= CONTEXT_LIMIT:
            windows.append(window)
            used += len(window)
    return windows


def verify_answer(store, claims, *, project, transport=None):
    """Advisory claim checks; exact local evidence gates precede remote scoring."""
    if not isinstance(project, str) or not project.strip():
        raise ValueError('advisor_requires_explicit_project')
    if not isinstance(claims, list) or not 1 <= len(claims) <= 20:
        raise ValueError('claims_limit_1_20')
    raw = json.dumps(claims, ensure_ascii=False)
    if len(raw) > 32000:
        raise ValueError('claims_too_large')
    claims = json.loads(raw)
    _safe(store, claims)
    # Validate the whole request before any network call.
    for claim in claims:
        if (not isinstance(claim, dict) or set(claim) != {'text', 'citations'}
                or not isinstance(claim['text'], str) or not claim['text'].strip()
                or not isinstance(claim['citations'], list) or len(claim['citations']) > 8):
            raise ValueError('invalid_claim')
        for cite in claim['citations']:
            if (not isinstance(cite, dict) or set(cite) != {'record_id', 'source_sha256', 'quote'}
                    or any(not isinstance(v, str) or not v.strip() for v in cite.values())):
                raise ValueError('invalid_citation')
    results, items, snapshots = [], {}, {}
    by_id = _eligible(store, project)  # one full-index pass per phase, not per claim
    for index, claim in enumerate(claims):
        item = dict(index=index, verdict='insufficient', mechanical_verified=False, diagnostics=[])
        results.append(item)
        if not claim['citations']:
            item['diagnostics'] = ['citation_missing']
            continue
        try:
            refs = _verified_evidence(store, claim['citations'], project, by_id)
        except (ValueError, OSError):
            item['diagnostics'] = ['citation_not_current_or_exact']
            continue
        item['mechanical_verified'] = True
        context = _context(refs, claim['citations'])
        try:
            _safe(store, context)
        except ValueError:
            # The surrounding text goes to the provider too, so it passes the same gate.
            item.update(verdict='degraded', diagnostics=['context_sensitive'])
            continue
        snapshots[index] = {r['id']: [r['source_sha256'], r['revision']] for r in refs}
        items[index] = dict(id='k' + str(index), claim=claim['text'],
                            quotes=[c['quote'] for c in claim['citations']], context=context)
    if items:
        mode = client.inspect_config(store.state_dir)

        def ask(indexes):
            advice = client.evaluate(store.state_dir, '', [items[i] for i in indexes], scope='project:' + project,
                                     source_versions={str(i): snapshots[i] for i in indexes},
                                     purpose='answer_check', transport=transport)
            if 'budget_exceeded' in advice.get('diagnostics', []) and len(indexes) > 1:
                # The budget is checked before any network call; halve and retry.
                half = len(indexes) // 2
                return {**ask(indexes[:half]), **ask(indexes[half:])}
            return {i: advice for i in indexes}
        order = list(items)
        with ThreadPoolExecutor(max_workers=4) as pool:
            advices = {}
            for part in pool.map(ask, [order[i:i + BATCH] for i in range(0, len(order), BATCH)]):
                advices.update(part)
        try:
            by_id = _eligible(store, project)
        except (ValueError, OSError):
            by_id = {}
        for index, versions in snapshots.items():
            item, advice = results[index], advices[index]
            try:
                refs = _verified_evidence(store, claims[index]['citations'], project, by_id)
                if versions != {r['id']: [r['source_sha256'], r['revision']] for r in refs}:
                    raise ValueError('evidence_changed')
                if client.inspect_config(store.state_dir) != mode:
                    raise ValueError('configuration_changed')
            except (ValueError, OSError):
                item.update(verdict='degraded', diagnostics=['source_or_configuration_changed'])
                continue
            if advice.get('degraded'):
                item.update(verdict='degraded', diagnostics=advice.get('diagnostics', []))
            elif advice.get('mode') != 'on':
                item.update(verdict='uncertain', diagnostics=['semantic_' + advice.get('mode', 'unavailable')])
            else:
                relation = advice['relations']['k' + str(index)]
                item.update(relation=relation['choice'], confidence=relation['confidence'])
                if relation['confidence'] >= CONFIDENCE_GATE:
                    item['verdict'] = VERDICTS[relation['choice']]
                else:
                    item.update(verdict='uncertain', diagnostics=['low_confidence'])
    return dict(status='advisory_only', claims=results, approved=False,
                memory_written=False, rewrites=False)
