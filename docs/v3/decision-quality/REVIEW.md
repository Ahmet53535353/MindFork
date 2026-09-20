# PR 69 review and evidence

Reviewed 2026-09-21. Baseline: `e112d8af8ec3cc205a2f5aa4994ec337a1460ec8`.
Initial contributor head: `28eb9d1bd776b91c85157b31f05f9f8b884cf950`.
Review corrections: `882feba` (separate commit; original authorship retained).

## Product flow and decision boundaries

Markdown remains canonical; SQLite is a rebuildable index. The hook synchronizes
sources, applies visibility/trust/project/freshness/supersession gates, retrieves
local candidates, optionally resolves a source-bound continuation, optionally
calls the enabled Jev selector, then packs complete JSON for the active agent.
Only actually delivered records can establish continuity. Jev cannot retrieve a
source absent from the eligible local candidate pool.

The agent can explicitly submit a proposed memory via `jev-memory`. Mechanical
source checks precede one bounded request containing independent support,
commitment, kind and prior-relation questions. Code composes answers and checks
time ordering; the agent still owns source inspection and authorized writes.
`jev-answer` separately checks claims against complete bounded source context.
Neither path marks a task complete or establishes real-world truth.

Useful local changes include aliases, source-slot packing, session continuity,
and complete delivery envelopes. Semantic selection, multi-facet relevance and
typed memory advice use the existing optional provider. General transcript
summarization, learned ranking weights, automatic canonical-memory writes and
global cross-project contradiction detection were deliberately not added: no
validated training corpus or authority contract supports them here.

## Primary-source check

Sources accessed 2026-09-21. These are provider descriptions, not our measurements.

| Source | Documented mechanism | Implementation implication |
| --- | --- | --- |
| [Choice](https://docs.typesafe.ai/primitives/choice) | Fixed categories with per-option probabilities; named question IDs return separately. | Versioned independent questions for support, commitment, kind and each prior relation. Unknown categories remain available. |
| [Score](https://docs.typesafe.ai/primitives/score) | Weighted position on described ordinal levels; score is not accuracy. | Manual relevance uses an ordinal rubric; do not present its cutoff as a correctness probability. |
| [Confidence](https://docs.typesafe.ai/confidence) | Confidence summarizes distribution shape; thresholds depend on application evidence. | Confidence below 0.8 routes memory proposals to source inspection. This is an uncalibrated application threshold. |
| [Speculative fan-out](https://docs.typesafe.ai/patterns/fan-out) | Ask independent questions together and combine useful answers in code. | One memory request, bounded priors, no fabricated dependency between question answers. Extra questions still consume tokens. |
| [Patterns](https://docs.typesafe.ai/patterns) | Discrete decisions, confidence routing and composite analysis fit inside a larger application. | Retain deterministic permissions, hashes, dates and write authorization outside the model. |

No new price, live latency, model accuracy or universal batching advantage is
claimed. The fixed contract also tells the model to treat supplied text as data;
that instruction alone is not a prompt-injection or semantic-correctness proof.

## Review corrections

1. A high-confidence `contradiction` against an existing record previously still
   returned `candidate_for_agent_review`. It now returns `inspect_sources` with
   `prior_conflict`. No canonical write was possible in either version.
2. Repacking an already clipped context erased its top-level truncation and
   omitted-source counts. Both are now preserved through the final envelope;
   additional omissions are counted too. IDs and citations remain intact.
3. Relation questions previously said to use only proposal/evidence, then asked
   about a prior record. The shared instruction now permits the state fields
   explicitly addressed by each question.

Two regression tests failed on the submitted implementation and pass with these
corrections. The relation instruction correction is not a live-quality claim.
The Jev guide was updated for the widened candidate pool, complete context,
new command, local-only metadata and source-reference continuity.

## Optionality and data boundary

| Mode | Jev credentials/cache/transport | Delivered local context | Canonical write |
| --- | --- | --- | --- |
| off / feature disabled | None for the disabled purpose | Local retrieval and continuity | Never by Jev |
| shadow | Permitted for explicitly enabled features | Same membership/order as off | Never by Jev |
| on | Permitted for explicitly enabled features | Bounded semantic selection may change membership | Never by Jev |

Clean installs remain off. Update preserves saved off/shadow/on and advanced
settings. `auto_context` always requires a separate opt-in. Update metadata checks
are independent of Jev network calls. Source or policy changes around calls/cache
reuse discard advice. Disabling then re-enabling through the mode command changes
the policy generation. Logs retain sanitized counters, not source or query text.
`remote_allowed: false`, private visibility and sensitive classifications block
provider exposure, including titles; the local system can still use eligible
local-only records. Secret-pattern scanning is an additional limited guard.

## Reproduced evidence

The frozen new corpus has 18 conversational turns and 8 manual cases. Each runs
three times in two candidate orders (108 turn trials, 48 manual trials per mode).
The provider transport is **label-driven ideal selection**, not live Jev. Repeats
are not independent examples, and this corpus is development/regression data,
not an unseen holdout. Latency is an in-process offline measurement.

| Runtime/mode | Turn required-source hits | Turn extra sources | Manual required-source hits | Manual extra sources |
| --- | --- | --- | --- | --- |
| Baseline off / shadow | 60/90 | 18 | 30/42 | 42 |
| Baseline on, ideal selector | 72/90 | 0 | 30/42 | 42 |
| Reviewed off / shadow | 90/90 | 6 | 42/42 | 42 |
| Reviewed on, ideal selector | 90/90 | 0 | 42/42 | 0 |

With continuity removed, reviewed off-mode turn hits return to 60/90. With aliases
removed, manual hits return to 30/42. Thus the measured recall improvements are
local-code gains, not demonstrated Jev gains. Manual local precision remains
0.50 and extra sources remain in off mode; do not hide this limitation.
The ideal selector proves selection/delivery plumbing, not model intelligence.

Raw runs: [baseline](evidence/review-baseline.json),
[reviewed](evidence/review-changed.json). Each includes per-case source IDs,
candidate exposure, delivered membership, ordering/repetition checks and timing.
Private vault data was not used. Raw `source` locations are normalized to commit
identifiers for portability; source identity is also pinned above.

The unchanged existing frozen retrieval benchmark passed all 16 development and
holdout cases: [result](evidence/review-frozen-retrieval.json). Initial submitted
code passed 373 V3 tests locally; the reviewed code adds two regressions.
CI runs the V3 suite and installed ZIP checks on Linux, macOS and Windows with
Python 3.11 and 3.13. Consult the [PR checks](https://github.com/avenoxai/avenoxbeyin/pull/69/checks)
for the final commit's status; an earlier green run is not proof for a later head.

```sh
python3 -m unittest discover -s tests -p 'v3_*test.py'
python3 scripts/evaluate_v3.py --output frozen.json
python3 scripts/evaluate_v3_decisions.py --source /path/to/baseline --output baseline.json
python3 scripts/evaluate_v3_decisions.py --output changed.json --check
python3 scripts/build_v3_release.py --version 3.1.1 --output candidate/beyin-v3-3.1.1.zip
python3 scripts/verify_v3_jev_package.py --package candidate/beyin-v3-3.1.1.zip --baseline baseline/beyin-v3-3.1.0.zip
```

The candidate version is a local test package, not a published release. The
installer proof exercises clean install, actual released 3.1.0 upgrade, saved
preferences, installed command and Markdown roundtrip, disable, rollback,
re-update and interrupted-operation recovery. Existing release CI additionally
checks the released 3.0.2 upgrade path.

## User rollout and remaining limits

See [Jev usage](../JEV.md) and [update/rollback](../UPDATE.md). No vault schema
migration, new pip dependency or required account is added. This PR does not
publish a release; standard `beyin.py update` receives these changes only after
a later stable release includes them. For a trusted local candidate use
`python3 beyin.py update --package /path/to/candidate.zip`, then `jev status`;
`python3 beyin.py rollback` restores the preceding managed installation.

No live-provider regression or real Desktop cold-session was run for this PR
review. Historical live numbers in JEV.md describe earlier code, not these new
contracts. Turkish/English continuity heuristics have finite vocabulary, lexical
search still misses synonyms absent from aliases, long evidence deliberately
falls back, and semantic confidence is not calibrated on a representative
unseen corpus. These limits justify keeping the provider optional and automatic
calls opt-in; further model-quality claims need separately measured live data.
