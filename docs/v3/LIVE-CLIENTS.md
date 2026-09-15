# Real client checks, 16 September 2026

These checks launch the installed clients against a temporary, synthetic vault. They do not read the operator's real notes or copy account settings into the repository. Raw CLI output remains in private temporary files. [Sanitized machine evidence](evidence/live-clients.json).

## What was exercised

1. Install the shared runtime into the temporary vault and index a synthetic fact. Add a private-visibility sentinel which must be absent from injected context.
2. Start a new client process. Ask for the fact using only injected context, with file/tool reading prohibited by the prompt (Claude additionally has tools disabled). Compare the final answer with the expected value; process exit 0 alone is insufficient.
3. Invoke a synthetic skill whose expected response exists only in its `SKILL.md`. Codex reads `.agents/skills`; Claude reads its linked `.claude/skills` entry.
4. Change an already indexed source without increasing its declared frontmatter revision. Start a new session and check that the hook refreshes the answer to the new source value.

These are narrow end-to-end canaries. They do not measure general model accuracy or prevent an independently authorized agent from reading a private file with other tools. Visibility filtering governs this runtime's injected context.

## Results

| Client | Injected fact | Shared skill | Source edit, new session |
|---|---|---|---|
| Codex CLI | Exact match, trusted project hooks | Exact match | Updated value returned |
| Claude Code | Exact match | Exact match | Updated value returned |
| Antigravity | Exact match, explicit workspace | Exact match on second attempt | Covered by shared offline sync tests; no separate live edit test |

All final responses passed the synthetic private-sentinel check. Antigravity's first skill response contained the correct marker plus prose, failing strict equality; a second prompt explicitly requesting only the skill response passed. Both outcomes are retained in the evidence. No expected value was included in the model prompts.

## Client launch details

Claude Code **2.1.271**, model `sonnet`: `claude -p PROMPT --model sonnet --setting-sources project,local --strict-mcp-config --mcp-config '{"mcpServers":{}}' --tools '' --output-format json`. Skill checks allow `Read,Skill` and use `/beyin-smoke`. Project/local settings load the installed lifecycle definitions. `--bare` is unsuitable because it skips hooks and subscription authentication.

Codex CLI **0.153.3**, model `gpt-5.6-sol`, low reasoning, read-only sandbox: use a dedicated test CODEX_HOME with access to existing local authentication, trust the synthetic folder interactively, and review the installed definitions using `/hooks`. Then run `codex exec --skip-git-repo-check -C VAULT -m gpt-5.6-sol -c model_reasoning_effort='"low"' --sandbox read-only --json PROMPT`. The successful project-discovery run uses no hook trust bypass and no inline hook substitution. A preliminary `--ignore-user-config` run omitted project hooks; it is not counted as installation proof. A separate invocation-only bypass diagnosis passed but is superseded by the trusted run.

Antigravity, model `claude-sonnet-4-6`: trust the synthetic folder, then use `agy --add-dir VAULT --mode plan --model claude-sonnet-4-6 --sandbox --output-format json --print-timeout 90s -p PROMPT`. **Headless mode requires explicit workspace attachment with `--add-dir`; changing shell cwd alone did not load workspace hooks.** The installed `.agents/hooks.json` definitions produce actual `SessionStart` and `Stop` queue acknowledgements.

For all CLI automation, close stdin explicitly and capture raw output privately. Parse the client's final response field, not a search across logs or echoed prompts. These commands are validation recipes, not daemon launchers.

## Failure-driven improvements

- Real Claude startup exposed a missing-context bug for ordinary facts without task status. A regression failed before the fix; startup snapshots now include eligible statusless notes/facts and still exclude completed tasks and unknown-status tasks.
- Antigravity workspace attachment was corrected in the headless recipe; its adapter schema did not require a speculative change.
- Windows redirected output was checked under a non-UTF-8 encoding. The failure led to portable JSON output and a regression. Native Windows CI subsequently passed; see the separate platform evidence.

## Boundaries

Real client checks here run on macOS. Offline Linux containers exercise source, queue, skills and installer behavior. Native Windows and a cold Codex Desktop UI session are not established by these CLI results. Compaction and actual client crashes were not forced in paid model sessions; corresponding adapter/queue contracts have synthetic failure-injection tests.

Official contracts: [Codex hooks](https://learn.chatgpt.com/docs/hooks) and [Claude hooks](https://code.claude.com/docs/en/hooks). Antigravity's installed CLI help, changelog and runtime observations supplied its workspace behavior.
