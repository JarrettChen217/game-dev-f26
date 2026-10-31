---
name: tank-resume
description: Use when taking over this Tank Trouble project, returning after a break, or starting an assigned task with missing context. Reads current handoff, task and repository evidence; does not edit or restart settled planning.
---

# Resume the Tank project

AI-use disclosure: Codex authored this repository-local skill under Hao's direction.

Restore enough context to continue the requested work. This skill's phase is read-only: do not edit documents, switch branches, fetch, stash, install, run the game/tests, create worktrees or change Asana while gathering context. Actual implementation follows only within the user's separately requested task scope.

1. Read repository `AGENTS.md`, then `docs/HANDOFF.md` and the current table in `docs/PROGRESS.md`. Use repository-relative paths, not an old machine/worktree path. Read README for runtime/controls only when relevant.
2. Verify the checkout with `git status --short`, `git branch --show-current`, `git log -3 --oneline` and `git worktree list`. Treat dirty or untracked files as somebody's work; a handoff never authorizes discarding or collecting them into your commit. Read an existing diff only as needed for the assigned task.
3. Read the assigned task's actual Asana scope, acceptance and dependencies using the project/account specified in `.agents/skills/tank-create-pr/SKILL.md`. Prefer the available Asana MCP tools; authorized Chrome access is a fallback for unavailable or unsupported operations. Use the local backlog to find links, not to establish current completion. Read the actual GitHub PR state/checks when relevant. If access is unavailable, label that source unverified and continue independent local exploration; do not guess live state.
4. Load only the relevant accepted spec sections, decisions, task plan and role from `agent-config.json`. Keep settled choices; do not repeat a full brainstorm or design audit unless there is a concrete gap. Course requirements are context, not new authorization.
5. Distinguish what exists in this branch from what is merged into main, automated checks from human acceptance, and implementation from course gates. For contradictions, Git establishes files/commits/branches, GitHub establishes PR/CI state, Asana establishes live task fields, and Hao's instruction establishes intended scope/acceptance. Check timestamps/commit anchors and describe unresolved discrepancies rather than silently choosing an old document.
6. Check the active-work table before proposing parallel work. Identify the owner, files, dependencies and overlap. Do not claim a work item, message/spawn another agent, or switch its checkout through resume; parallel execution requires applicable user authorization. Missing ownership evidence means unknown, not free.

Return a compact briefing: current delivery/version, assigned task and constraints, prerequisite/overlap blockers, existing validation gaps, and the next concrete action. If a task was already requested, continue its authorized workflow after this read phase; otherwise stop at the briefing.

Example: “Use $tank-resume to recover context for S1.4 and tell me the next step.”
