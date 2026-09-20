# Decision quality: pre-implementation measurement plan

Base: e112d8af8ec3cc205a2f5aa4994ec337a1460ec8. Date: 2026-09-21 (Europe/Istanbul).

Freeze `tests/fixtures/v3/decision_quality.json` and its digest before editing production code.
The supplied 18 turns are development cases from another prototype, not measured public-main bugs.
New alias/multi-part/negative cases are authored regression cases, not independent holdout.
Do not inspect or modify the existing frozen semantic fixture; execute its development and holdout gates unchanged.

Compare the public baseline and changed runtime with off / shadow / on modes. Use a deterministic
label-driven transport ONLY as an ideal-selector architecture control, never as evidence of Jev accuracy.
Report candidate recall separately from final packed and actually rendered source recall, precision,
missed/extraneous sources, correct abstentions, forbidden sources, p50/p95 total time, provider calls,
cache hits, fallbacks and tokens. Unknown live tokens, bills and model accuracy remain null.
Repeat with original/reversed candidate order and cold caches. Report repeated trials and unique cases separately.
Ablate aliases and session continuity separately; do not credit their gains to the provider.

Regression gates precede implementation: oversized metadata must not consume a slot; aliases must
retrieve after eligibility filtering; no credential/cache/network access while off; disabled feature
must not run secret inspection; source/index/permission/config mutations must invalidate an in-flight
answer; a local-only title must never leave the machine; shadow delivery must match off; re-enabling
must not revive prior cache generations. Memory choices remain advisory; uncertain, tentative,
negated or contradicted proposals must not become a write or completed task. Test full source context,
not a quote lifted from a cancelled plan. Test actual hook output budgets, not just intermediate lists.

Run all V3 offline contracts, frozen retrieval gates, existing POSIX/Windows/platform jobs, and
portable release installation / upgrade / rollback / interrupted-recovery. Do not call a CLI hook
simulation a real Desktop cold-session test. Do not publish a release or merge the PR.
