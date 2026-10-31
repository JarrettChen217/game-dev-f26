# Agent configuration (as used)

Copies of the agent roles and reusable skills that ran this project, taken from the development repository's `.agents/`
(Codex) and the Claude Code reviewer definition. Private identifiers (account, project and workspace IDs, local paths)
are replaced with `<redacted>`; nothing else is changed. See [../AGENT-TEAM.md](../AGENT-TEAM.md) for how they were used.

- `roles/`: design, implementation and reviewer roles, plus `claude-tank-reviewer.md`, the independent read-only reviewer subagent.
- `skills/`: `tank-resume`, `tank-handoff`, `tank-verify-change` and `tank-create-pr`, with each skill's `agents/openai.yaml` invocation policy.
