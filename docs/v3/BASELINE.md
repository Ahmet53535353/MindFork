# V3 offline evaluation baseline

Frozen fixture: `tests/fixtures/v3/semantic_scenarios.json`, SHA256 `26755d6fb2ab368f5c7b5882cb2dd33ef651404f366bce45a4632deae57099bc`.

Initial observation before this test lane began: `template/.claude/scripts/beyin_v3.py` did not exist. Foundation status was **not implemented**. Development and holdout quality metrics were **not measured (null)**; assigning a numeric recall/accuracy to an absent implementation would be misleading. The implementation arrived concurrently while the evaluator was being authored; the first executable evaluation hit an adapter-signature mismatch, so no quality metrics were produced by that attempt either.

This benchmark measures synthetic source retrieval, structured facts, privacy boundaries and shared harness adapters. It does not evaluate free-form model answers, embeddings, broad natural-language generalization or a real user's vault. Holdout expectations are frozen and are not sent to the implementation lane. Precision is diagnostic: relevant returned records divided by records returned within the first five, averaged across cases; correct empty abstention contributes 1. Required recall is micro-averaged across required IDs. Empty-required cases are assessed by abstention. Source citation preservation, uniqueness and result limit are additional correctness gates.

Run from repository root, with no model or network access:

```sh
python3 scripts/evaluate_v3.py
python3 -m unittest discover -s tests -p 'v3_*test.py'
```

The evaluator reports development (10 cases) and holdout (6 cases) separately. Missing module, malformed response, or adapter error is an explicit failure, never a green skipped test. The harness gate invokes production `shared_context` for both harness names and compares its normalized payload to retrieval output. A negative-control test intentionally breaks one harness response and requires the equality gate to reject it.

Runtime tests use temporary vault source fixtures with an external temporary SQLite runtime. They cover disk reopen/integrity, duplicate receipts/collisions, optimistic revision conflict including competing writers, source-reference/path containment, private/untrusted isolation, clipping markers and citations, omission reporting, out-of-order supersession, deleted-source invalidation and disabled optional-provider behavior. No fixture expectations are modified for an implementation.

## Measured results (2026-09-15)

The first executable quality run, after signature alignment, produced development 8/10 and holdout 6/6. Development recall was 0.8571428571, abstention accuracy 0.8 and fact retention 0.9; forbidden results and privacy leakage were zero. Feedback to the implementation lane was restricted to the two development failures (public project summary and untrusted-query abstention). No holdout query, record answer or expected ID was shared, and no holdout failure guided tuning. A full-score holdout was nevertheless observed during that initial run, so this is a frozen independent expectation set, not a benchmark never previously executed. Subsequent tuning used `--split development`.

Final frozen runtime SHA256: `c7a81e9a73813a3237b985a27262e7ecbd2a2c96bcd0880f80ea7986c1d0b854`.

| Metric | Development (10) | Holdout (6) |
|---|---:|---:|
| Cases passing all gates | 10/10 | 6/6 |
| Required recall@5 | 1.0 | 1.0 |
| Precision@5, diagnostic | 0.95 | 1.0 |
| Forbidden results | 0 | 0 |
| Abstention accuracy | 1.0 | 1.0 |
| Required structured-fact retention | 1.0 | 1.0 |
| Privacy canary leaks | 0 | 0 |
| Codex/Claude adapter equality | true | true |

`python3 scripts/evaluate_v3.py` passed with the runtime hash above. `python3 -m unittest discover -s tests -p 'v3_*test.py'` passed **17/17** (14 runtime tests and 3 semantic/evaluator tests). Both final runs completed without errors. The frozen fixture hash was unchanged. Actual `codex_context` and `claude_context` wrappers are invoked, and a negative-control test verifies that divergence through shared_context makes evaluation fail.

Runtime checks also reject reuse of one state database with a different vault and omit content whose source hash changed, reporting `stale_count`. Clipping tests use a 1,000-character serialized record-plus-citation budget: small budgets can be insufficient to hold required structured metadata, so the gate requires useful marked clipping when metadata fits rather than forcing loss of facts. Serialized size and engine-reported `used_chars` must agree.

These green results establish this small offline foundation contract only. Existing shell/PowerShell lifecycle deployment, real model quality, native Windows execution and a production vault migration were not established by this suite.

## Append-only history reliability extension

A separate reliability extension added six tests before the history API was implemented. The initial focused run failed because `MemoryStore.history` was absent; the semantic fixture and all expected answers remained unchanged.

`history(record_id)` must return ordered `{sequence,event_type,record_id,revision,record}` snapshots with `ingest` or `update` event types. Tests cover immutable nested snapshots, record-scoped persisted history after reopening SQLite, no event on identical ingest/revision conflict/invalid source/ID collision, and one winning event under concurrent revision updates. A real SQLite trigger aborts event INSERTs to prove both new-ingest and update projections roll back when their event cannot be appended.

Final extension runtime SHA256: `9b71a57156799fa95de3a85e2bf59ddaa4cb0d7e5e2eb6fd5e6d686e2e9be6bd`. Independent frozen-source rerun passed **23/23 tests** (20 runtime and 3 semantic/evaluator), plus the evaluator's development **10/10** and holdout **6/6** cases. All metrics in the table above remain unchanged. No holdout-directed tuning occurred. The earlier 17-test measurement and source hash are retained above as historical evidence, not current test counts.
