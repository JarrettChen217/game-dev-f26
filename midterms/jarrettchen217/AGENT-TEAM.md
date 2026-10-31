# Agent team

> **DRAFT by the agents, 2026-10-31. jarrettchen217 will rewrite this page in their own words before submission**,
> drawing on the peer notes.

I acted as Executive Producer and Creative Director. I chose the route (reconstruct Tank Trouble, then train a player
rather than prompt one), and I accepted or rejected every gate. Agents wrote most of the code. None of them merged a PR or approved a gate.

## Roles and what each produced

| Role | Agent | Configuration | Produced |
| --- | --- | --- | --- |
| Design | Codex, design role | [`agent-config/roles/design.md`](agent-config/roles/design.md) | Rule source map, observation boundary, held-out suite design |
| Implementation | Codex executors working in separate git worktrees: game/UI, training, browser build, archive | [`agent-config/roles/implementation.md`](agent-config/roles/implementation.md) | 60 Hz engine port, Pyxel game and tutorial, PPO training runs, browser build |
| Independent review | Codex reviewer role; Claude Code `tank-reviewer` subagent (read-only, never the code's author) | [`agent-config/roles/reviewer.md`](agent-config/roles/reviewer.md), [`agent-config/roles/claude-tank-reviewer.md`](agent-config/roles/claude-tank-reviewer.md) | Review findings on the model registry (e.g. a hard-coded model label and malformed manifests that crashed), each fixed before merge |
| Submission and integration | Claude Code | the skills below | Branch consolidation, manifest-based model swap, this folder, its tests and CI |

## Reusable skills (used by name in multiple sessions)

- [`tank-resume`](agent-config/skills/tank-resume/SKILL.md): rebuild context from the repo, handoff and task tracker before acting.
- [`tank-handoff`](agent-config/skills/tank-handoff/SKILL.md): leave evidence-backed state for the next session.
- [`tank-verify-change`](agent-config/skills/tank-verify-change/SKILL.md): run the checks and hand the diff to an independent reviewer.
- [`tank-create-pr`](agent-config/skills/tank-create-pr/SKILL.md): task-linked PR titles and bodies.

## What worked, what did not

- TODO (own words): e.g. separate worktrees per executor avoided collisions; freezing a protocol before each training run kept results honest; a 10-22 plan for an LLM player was abandoned for a learned policy.
- TODO (own words): limitations of the agents, and where I had to step in.
