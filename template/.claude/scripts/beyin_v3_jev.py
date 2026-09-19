"""Explicit optional advisor; local retrieval and source authority remain in V3."""
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

    def verified():
        # Existing runtime gates enforce scope, visibility, trust, freshness and supersession.
        eligible = store._retrieve('', project=project, audience='internal',
                                   limit=100000, budget_chars=10000000, snapshot=True)['records']
        by_id = {r['id']: r for r in eligible if not r.get('text_truncated')}
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

    refs = verified()
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
        now = verified()
        if versions != {r['id']: [r['source_sha256'], r['revision']] for r in now}:
            raise ValueError('evidence_changed')
        if client.inspect_config(store.state_dir) != mode:
            raise ValueError('configuration_changed')
    except (ValueError, OSError):
        result = _clear(result, 'source_or_configuration_changed')
    return dict(status='advisory_only', approved=False, memory_written=False, jev=result)
