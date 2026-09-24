# OMP (Oh My Pi) harness

OMP is the sixth supported client after Codex, Claude Code, Antigravity, Hermes and OpenCode.
It loads project hooks from `<project>/.omp/hooks/pre/*.ts` when a session starts in that
directory. The installer therefore writes one managed file, `.omp/hooks/pre/beyin-v3.ts`, from
`template/.claude/scripts/beyin_v3_omp.py`. There is no link or enable step: open OMP in the
vault. Rollback and uninstall remove the hook like every other managed file.

Do not copy the hook into the global agent directory (`~/.omp/agent/hooks/pre/`). It adds
nothing: outside the vault the hook does nothing, inside the vault the project file of the same
name takes precedence, and the installer never updates or removes a global copy.

The hook pins the vault and interpreter at install time, like the Hermes shim;
`BEYIN_VAULT` and `BEYIN_PYTHON` override them. The runtime directory comes from
`.beyin-runtime.json` and must be absolute, exactly like the OpenCode plugin. Every event runs
`beyin_v3_hook.py --harness omp` with a 6 second bound (20 seconds on Windows). A missing
interpreter, timeout, non-zero exit or invalid output returns no context and never fails the
OMP turn. A vault without a valid runtime file registers no hooks.

## Lifecycle mapping

`session_start` is `SessionStart`; `before_agent_start` is `UserPromptSubmit` with `event.prompt`
as the prompt and is the only request-time injection channel, so the `SessionStart` context is
pinned and carried into the first prompt, while each later prompt gets its own turn context.
`tool_result` for the `edit`, `write` and `ast_edit` tools is `PostToolUse`, `session_stop` is
`Stop`, `session_before_compact` is `PreCompact`, and `session_shutdown` is `SessionEnd`. Like
Claude, the first prompt queues both `SessionStart` and a real `UserPromptSubmit` event.

Sessions whose `ctx.cwd` is not the vault inject and queue nothing. Both paths are compared after
symlink resolution, because OMP reports the cwd without the macOS `/private` prefix and without
resolving symlinks. Task sub-agents reuse the parent's hooks and emit their own `session_start`;
OMP records a `session_init` entry in a sub-agent session before that event, and such sessions
are ignored like OpenCode child sessions: they never submit receipts, so tracking them would
only duplicate context and report false receipt gaps. Agents running in OMP submit receipts with
`--harness omp`; retrieval output is byte-equal to Claude for the same query.

## Validation boundary

`tests/v3_omp_test.py` installs a synthetic vault, imports the generated hook in Bun with a
fake OMP `pi` object and drives every mapped handler; the Bun cases skip when `bun` is absent.
One real OMP 18.2.8 session in a temporary synthetic vault returned a canary fact from
injected context with tool use prohibited by the prompt, and the queue acknowledged the
lifecycle events with no hook error. This does not establish other OMP delivery surfaces.
