# Public V3 infrastructure audit

Scope: approved infrastructure source and test source only. No personal notes, registry data, transcripts, credentials, account configs, or live runtime state read. No production changes. A synthetic temporary Runtime was used for one targeted test.

## Confirmed structural benefits

- Canonical Markdown tasks feed deterministic generated views; expected revisions protect cooperating edits and evidence is reset to user_report on task updates. `.claude/hooks/vault_runtime/engine.py:555-592`.
- Shared engine and thin CLI support both harnesses; transcript adapters exclude tool output and duplicate Codex response_item records. `scripts/vault_runtime.py:1-8`; engine `103-119`.
- Atomic fsync/replace, local flock, SQLite journal recovery, stable event IDs, retry/dead-letter state implement durable local processing. Engine `49-68`, `135-172`, `222-265`, `517-553`.
- Runtime state remains outside synced content; hash ownership preserves detected manual edits. Engine `122-145`, `222-240`.
- Compiler runs separately from hooks, excludes current-day/conflict-copy inputs, records source hashes, and claims a bounded daily run. `scripts/vault_compiler_job.py:16-57`.

## Confirmed defect: receipt success despite missing receipt artifact

Engine receipt() ignores owned_write(False), records receipt-session completion and clears pending state. The event then succeeds. Engine `340-369`, `537-543`.

Synthetic test on a new temporary vault/state created an untracked preexisting manual file at the expected receipt path, enqueued one receipt, and ran the temporary worker. Result: event_state=succeeded; receipt_marked_complete=true; artifact_contains_receipt=false; manual_artifact_preserved=true; conflict_recorded=true. Assertion passed. Exact process exit code: 0. Evidence: `/tmp/beyin-receipt-test.json`.

This demonstrates inconsistent completion semantics, not destruction of the manual artifact. Required change: propagate per-artifact conflict outcomes; do not mark receipt complete until required artifacts persist and read back correctly. This test did not simulate a concurrent daily-file write, so that additional manifestation remains a code-based inference.

## Confirmed portability limitations

- Timezone, taxonomy, persona, owner and runtime location are hardcoded. Engine `20-28`, `124`, `194`, `583`.
- Service installer uses macOS launchctl. `scripts/manage_vault_service.py:17-32`.
- Installer embeds a historical one-time migration and fixed archive name. `scripts/install_vault_automation.py:33-69`.
- Privacy filtering catches only selected credential-shaped strings; generated context includes recent receipt and task text. Engine `94-100`, `428-438`. Public export needs a separate allowlisted boundary, not a claim of comprehensive redaction.
- Local locks do not serialize remote editors. Hash checks leave a check-to-replace interval. Engine `235-240`, `555-592`. Remote edits require reconciliation; actual data loss was not observed.
- Worker/hook enforce writer_host, while task-create/update do not. Source contribution from other hosts is documented, so this is a boundary to specify rather than a proven unintended defect.
- Compiler chooses newest eligible closed day and handles at most one daily source. `scripts/vault_compiler_job.py:16-24`, `38-44`. Older backlog starvation is a possible consequence under continuous arrivals, not an observed production outcome.
- Task reference/priority validation is incomplete, and receipt refs establish path existence rather than proof of an asserted result. Engine `314-350`.
- Missing receipt detection uses assistant-message length and a narrow opt-out expression. Engine `299-310`.

## Verification boundary and public V3 requirements

Test source covers deduplication, revision conflicts, local concurrent updates, recovery, partial transcripts, path rejection and view preservation (`tests/test_vault_runtime.py:17-166`). The full suite was not run in this audit. Only the isolated receipt-conflict test above was executed.

Current client lifecycle health, real Desktop/CLI/Claude parity and live service operation are unverified. Documentation correctly requires cold-client verification separately; current hook records distinguish harness but not Desktop versus CLI surface. Engine `174-182`, `470-485`; `scripts/VAULT-AUTOMATION.md:63-67`.

V3 requirements: generic manifest for paths/timezone/identity; platform service adapters; separate migration and installation; strict receipt durability; synthetic-only public fixtures; private/public data classification and allowlisted export; explicit local-single-writer boundary; fair compiler backlog policy; schema validation; cold-client compatibility matrix.

Recommended positioning: local-first, source-backed second-brain runtime with agent adapters. Source structure is promising; portable public readiness is not established by this audit.
