# Public issue validation

Baseline: public repository avenoxai/avenoxbeyin, commit 2e074cc44df5966543b4c21432cb5a895d141211. Public issue #17/#18/#19/#21 metadata and PR20 diff read on 2026-09-15. No repository changes, installer runs, model calls or real vault access. Synthetic fixtures only. macOS execution; no native Windows claim.

## Evidence matrix

| Finding | Status | Evidence / root cause |
|---|---|---|
| #17 short-line memory silently truncated | Confirmed, actual Bash hook fixture | Last-Session line 49 retained, line 50 omitted (heading consumes first line); rules line 60 retained, 61 omitted; no truncation marker. Extraction windows precede cap helpers. session-start.sh:20-52, 105-114. |
| #21 thread bodies and seventh thread omitted | Confirmed, actual Bash hook fixture | T6 present, T7 and BODY_OWNER_1 absent; no marker. Heading/status-only grep plus 12-line window. session-start.sh:29-33; matching PowerShell algorithm session-start.ps1:68-84 statically confirmed. |
| #17 Journal latest intra-day entry omitted | Confirmed, actual Bash hook fixture | J9 retained, J10/newest sentinel absent. Last heading + first nine lines selects oldest entries within current day. session-start.sh:41-52. |
| #17 legacy Last-Session schema | Confirmed hook interoperability failure; upgrade not executed | Nonempty '# Son Oturum' file remains on disk yet section/content absent in additionalContext. Same legacy fixture in tests/fixtures/v1_vault.sh:129. Exact '## Session:' activation gate has no fallback. |
| #17 CLI missing outside hook PATH | Confirmed isolated resolver behavior | Executable synthetic $HOME/.local/bin/claude exists, sanitized PATH excludes it; actual flush._run_claude returns (None, claude-cli-missing), compile._run_claude returns claude-cli-missing. No CLI invoked. flush.py:384-387; compile.py:553-557. Host app's particular PATH is reporter evidence, not measured here. |
| #17 health not injected | Confirmed actual hook fixture | Synthetic recent health error absent from emitted context. Hook only exposes reflection debt, never reads health.json. |
| #17 stale health / component overwrite | Confirmed writer fixture and static success paths | Flush error overwritten by compile warning, not preserved as active per-component status. flush.py:71-97 and compile.py:127-153 read/modify/overwrite a singleton JSON. Success branches update flush/compile state, not clear health. Reporter 'red forever' is imprecise: old doctor also has age rules; unresolved record remains stale nevertheless. |
| #19 short Windows temp path causes Claude refusal | Reported; path handling gap statically confirmed, native failure not reproduced | _prepare_stage uses raw mkdtemp path at compile.py:336 and passes stage as child cwd. resolve() used for containment check does not replace returned stage. No Windows GetLongPathNameW lane or actual Claude short-path refusal tested. Profile dot does not by itself establish OS/CLI behavior on every Windows install. |
| #19 graph non-UTF8 crash | Confirmed encoding simulation on macOS, not native Windows | Real graf_kontrol.py on synthetic emoji folder exits 1 with UnicodeEncodeError under both PYTHONIOENCODING=cp1254 and cp1252; UTF-8 exits 0. Script directly prints folder names without stream normalization. |
| #19 doctor Windows hook detection | Confirmed against shipped Windows settings | Existing command-only .sh predicate finds zero SessionStart hooks; joining command and args and matching .ps1 finds one. Native doctor not executed. Existing skill also contains POSIX executable/symlink/python checks. |
| #17 pre-commit non-ASCII claim | Exact user hook not available; setup analogue statically present | Repository SETUP.md:256 uses non-NUL git diff --cached --name-only and anchored .bak/.env regex. No tracked pre-commit hook found. Do not label exact reported installed hook reproduced. |
| #18 OpenCode | Confirmed unsupported in current source/docs | docs/PROJECT-WORKFLOW.md:38-44 explicitly excludes automatic OpenCode start/flush. Request is feature work, not an established adapter defect. |

## PR20 independent review

Appropriate scope: adds Windows doctor skill, swaps before .agents skill copy, detects command+args, accounts for copies instead of symlinks, checks pwsh/interpreter, sets PYTHONIOENCODING around graph invocation. Adds CLI authentication check and warning classification to POSIX too. Does not fix compile staging, graph engine encoding, memory slicing, CLI fallback, health lifecycle, or supported upgrade migration. Existing Windows installs do not automatically receive fresh-install-only swap. Claimed Windows test counts belong to PR author and were not rerun here.

**Concrete blocking regression in health check 8:** PR assumes JSONL. Real flush writes compact single JSON, but compile writes indented single JSON (`compile.py:115-116`). Exact Python block extracted from PR diff was executed against real writers with synthetic values:

| Real writer input | PR20 result |
|---|---|
| flush error | Correct: 1 error, exit 0 |
| compile error | False green: 0 errors / 0 warnings, exit 0 |
| compile warning + warnings array | AttributeError, exit 1 |

Each indented object line fails independent json.loads and is skipped; a standalone warning string in the array parses as a string, then `.get` fails. Windows block shares line-by-line assumption but native PowerShell behavior remains untested. Parse whole document first, validate dict and schema, classify unknown/malformed data as unknown/error, never healthy. Support JSONL only as explicitly versioned legacy format if needed.

Additional PR caution: warn prefix does not guarantee recovery. Current engine records `warn:directive-shaped-transcript` as detection, not necessarily a successful retry. Latest singleton record also cannot quantify all errors in a 48-hour window. Avoid 'claude-exit-1 almost always means logged out' as diagnosis; auth, permission, command usage, network and runtime failure need structured distinctions.

## Better architecture and acceptance criteria

1. One Python context extractor with Bash/PowerShell/agent adapters. Parse sections and complete thread blocks, include prose; select newest Journal entries. A single explicit budget operation reports every omitted section/thread/line, source path and omitted amount. Acceptance: 7+ threads, prose decision owner, 51+ Last-Session lines, 61+ rules lines, multibyte text/emoji, current-day appended Journal; content either present or explicit notice. Check 16,000-character contract and identical normalized payloads on macOS/Linux/Windows.
2. Version memory schema with tolerant bounded legacy fallback and warning. Migration verifies effective context availability as well as byte preservation. Acceptance: repository v1 fixture survives full upgrade and legacy sentinel appears in next SessionStart on both platform paths; unknown nonempty schema cannot disappear silently.
3. Shared CLI resolver used by flush and compile: configured validated absolute executable, PATH, platform installation candidates. Installer records executable and runtime identity; doctor tests the same resolution under minimal environment. Missing, non-executable and invocation failure distinct. No need for model tokens to test resolution.
4. Canonical health schema with per-component active state and last_success_at, structured code/severity, resolved event link and separate bounded event history. SessionStart surfaces new/relevant failure succinctly; successful compile must not clear flush failure. Acceptance: fail->success clears only same component; warning cannot hide another component's error; malformed/missing/old state reports unknown appropriately; PR20 writer-reader roundtrip fixtures required.
5. Windows temp normalization validates long canonical staging cwd before invoke, preserves out-of-vault isolation and allowlisted diff validation. Acceptance requires actual Windows with 8.3 enabled, dotted/non-ASCII/space profile paths, failed long-path API, absent 8.3 support; distinguish synthetic path tests from native CLI permission acceptance. Do not reduce permission safeguards to obtain writes.
6. Graph CLI explicitly handles UTF-8 redirected streams and intentional fallback for console output. Acceptance uses real script with emoji orphan and broken links under UTF-8/cp1252/cp1254, --tam and summary; native Windows pipe capture lane.
7. Doctor should be executable structured read-only checks with shared schema, small platform probes; Markdown skills present results instead of copying increasingly divergent scripts. Track actual installed harness binding, executable and auth separately. Malformed settings or unsupported harness means unknown, not green. PR20 merge gate includes compact/pretty JSON and warning-array writer fixtures plus actual Windows and POSIX smoke tests.
8. OpenCode adapter: verify current official event/persistence API before implementing. Translate start/context, prompt count, compaction/end/idle semantics and transcript into shared normalized engine, retain session dedupe, incremental offsets, fork identity, retry/backoff, recursion guard, no external calls in tests. Don't guess hooks named like other harnesses. Acceptance: synthetic real-format transcript roundtrip -> expected daily output once, context delivered once per lifecycle, overlapping sessions isolated, short stop budget survives deferred work, install/uninstall idempotent and preserves user configuration. Separately decide model provider; a harness adapter alone does not eliminate Claude summarizer dependency.

## Kaydedilen kanıt

Sentetik sonuçlar `issue-evidence.json` ve `pr20-health-evidence.json` dosyalarında tutulur. Ajanın geçici test scriptleri bu rapora dahil edilmedi. Bunlar uygulama aşamasında kalıcı regresyon testlerine dönüştürülmelidir. Native Windows, gerçek model ve gerçek istemci lifecycle kanıtı bu tur üretilmedi.
