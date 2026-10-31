---
name: tank-handoff
description: Use when pausing or handing off Tank project work, submitting a PR, or finishing an authorized branch integration. Records verified state and synchronizes affected documentation and Asana descriptions without declaring unfinished work complete.
---

# Hand off the Tank project

AI-use disclosure: Codex authored this repository-local skill under Hao's direction.

Make the next session able to continue from evidence. Run at a meaningful task stop, PR handoff, or after an authorized merge. An unfinished task can be handed off. This is a session workflow, not a timer or background automation.

## Capture and reconcile

Read `AGENTS.md`, `docs/HANDOFF.md`, the current progress table, assigned task and working-tree diff. Record the actual branch/worktree, relevant commit/base, PR state, checks that really ran, human decisions, blockers and first next action. Scope every statement to its source/branch; never copy another branch's test count into main's README. Do not repeat tests just to refresh a timestamp when no code or unresolved issue changed.

Update the shared handoff's current snapshot and only your own active-work row. Retain other owners, dirty files and worktree paths; reread changed shared documents before saving to avoid replacing concurrent updates. Use stable task/branch links and timestamped observations, not sensitive logs or credentials. Move durable detailed evidence into `PROGRESS.md`/task records so HANDOFF remains short.

## Update affected sources

- `docs/HANDOFF.md`: short snapshot, active work (owner/task, branch, files, dependencies), validation gaps, blockers, next action and source links. Use its existing headings; replace the snapshot instead of appending endless recaps.
- `docs/PROGRESS.md`: current task row and actual execution evidence. Preserve historical entries as history.
- `README.md`: current behavior, controls, startup and limitations only if changed. State which checkout/version it describes; do not advertise unmerged features as main.
- `AGENTS.md`: durable project instructions only when an accepted workflow or constraint changed. Do not insert per-session state, silently rewrite Hao's rules, or update it merely to show activity.
- `agent-config.json`, task plans or `DECISIONS.md`: only when their configuration, accepted execution state or decisions changed. Keep links and declared paths valid.
- Asana: update the relevant task's description when task reporting is authorized. Prefer the available Asana MCP tools; authorized Chrome access is a fallback for unavailable or unsupported operations. Use the verified personal account/project and preservation workflow in `tank-create-pr`; retain scope, owner, dates, dependencies and other contributors' notes. Write complete English, standalone `---`, and matching Chinese. Include real PR/CI links and remaining human checks. Re-read saved content and verify the native PR attachment before claiming either. An unavailable connection leaves a clearly reported pending sync; complete local work without inventing remote success. Do not create tasks, change completion, dates, collaborators or dependencies without scope authorization.

Select only documents that need an actual update; report unchanged sources briefly. Documentation should describe implementation/verification/review/acceptance/merge separately. A passing CI is not a human playtest or course-gate approval.

## Finish without expanding authority

Integrate this checklist into finishing-development-branch: before PR publication preserve the branch-local state; after an authorized merge re-check the actual merge/branch evidence and synchronize remaining local/remote status where authorized. Do not claim a merge before it happens. Never make a merge, push, branch/worktree deletion, external message or scheduled automation happen solely because this skill was invoked. Respect authorization already given in this session; do not ask again for an authorized routine action. Preserve unfinished work and do not stash/reset another checkout.

Commit only the requested task's changes when authorized; link the actual Asana task in the PR through `tank-create-pr`. If post-merge local documents still need edits, commit through the normal authorized review workflow, not by silently writing main. Report updated sources, evidence, pending synchronization and the next action. This ends with a handoff, not a false completion claim.

Example: “Use $tank-handoff to save today's progress and synchronize the relevant task description.”
