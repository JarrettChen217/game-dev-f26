---
name: tank-create-pr
description: Use when creating or updating a Tank Trouble reconstruction pull request, selecting its Asana task or subtask, or checking PR attachment evidence with gh. Repository-local PR workflow and English description template.
---

# Create a task-linked Tank Trouble PR

AI-use disclosure: Codex authored this local skill under Hao's direction.

## Destination and account

- Repository: `JarrettChen217/tank-trouble-reconstruction`.
- Asana account: **`<redacted personal account>`**, as corrected by Hao. Use this personal account's project, not the university account's workspace. The project name alone is insufficient to identify the destination.
- Project: **COMS E6998 — Hao Chen — Game Studio**.
- Project ID: `<redacted>`; workspace/organization ID: `<redacted>`.
- Project URL: `<redacted>`

Use the existing signed-in account/connection. If the UI or connector shows a different account or project, resolve that mismatch before editing tasks. This skill does not grant account-switching, integration, push, merge or task-completion authorization; follow the current user request. Never read or print integration secrets.

## Find the actual task

1. Read `AGENTS.md`, the assigned work, diff, relevant README/spec and `docs/PROGRESS.md`. Identify what the PR actually delivers.
2. Search the local task index, using the exact task tag and meaningful terms:

   ```sh
   rg -n -F '[S1.2]' docs/ASANA_BACKLOG.md
   rg -n 'movement|collision' docs/ASANA_BACKLOG.md
   ```

   Adapt these example searches to the actual scope. `docs/ASANA_BACKLOG.md` and `docs/asana-backlog-content.json` are discovery aids, not current status/description authorities.
3. Read the candidate task using the available Asana MCP connection and its current tool definitions; use the authorized Chrome session only when MCP is unavailable or cannot cover the operation. Search/filter the project above by task tag and title as needed. Verify the actual title, project, scope, acceptance criteria and parent/subtask relationship. Use the task's permalink returned by MCP or copied from the live page. Do not construct a task ID from its label or confuse a project/list URL with a task URL.
4. If no index match exists, search the live project by responsibility and synonyms. If multiple tasks plausibly match, use their acceptance criteria and the actual diff to decide. Ask Hao only if that leaves a material ambiguity. Do not create or move Asana tasks just to make a PR fit.
5. If live access is unavailable, retain the known candidate and prepare a local description with the limitation recorded; do not claim live verification or successful attachment. Do not publish against a guessed destination. A task explicitly supplied/confirmed by Hao can be used with the remaining verification gap disclosed.

## Decide the PR boundary

Choose a coherent responsibility that a reviewer can assess and accept independently. Importance, scope, risk and dependencies matter; a threshold such as “fewer than five commits” does not determine this.

- Related small subtasks serving one delivery result: one PR linked primarily to the parent, with covered subtasks listed. Example: S1.1 fixed map, tank state and public interfaces.
- A subtask with a substantial independent responsibility or acceptance boundary: its own PR, linked primarily to that subtask; identify its parent for context.
- Several tasks contributing to one inseparable change: one PR can cover them. State each task's concrete contribution and which acceptance items remain; do not imply all linked tasks are fully completed.
- Independent responsibilities: split PRs. Record sequencing/base dependencies when one genuinely builds on another.

## Prepare and create/update with gh

Read [the description template](references/pr-description.md) when writing the body. Use English and scale its detail to the change. Include full verified Asana task URLs in the **body**, with the primary task first; commit messages alone do not trigger attachment.

Check the current branch, working tree, diff and base before publishing. Do not switch another agent's checkout, rewrite published history, merge prerequisite PRs or delete a worktree as part of ordinary PR creation.

```sh
git status --short
git branch --show-current
git diff --stat BASE...HEAD
gh pr list --repo JarrettChen217/tank-trouble-reconstruction --state all --head BRANCH --json number,title,url,state,baseRefName,headRefName
gh pr view PR_NUMBER --repo JarrettChen217/tank-trouble-reconstruction --json title,body,url,baseRefName,headRefName
```

Replace symbolic arguments with observed values. Check for an existing open PR for this branch/scope and update it rather than duplicating it. Past PR #5 is the foundation example; #2/#3 are integration examples. Retrieve their actual bodies with `gh pr view` when accessible; `docs/ASANA_INTEGRATION.md` records historical results. Borrow structure, not stale claims, task destinations or test counts.

Commit subjects and PR titles follow `[task-id] type: description`, e.g. `[S1.2] feat: add speed-limited tank movement`; use `type!:` only for an actual breaking change. A parent PR may contain commits tagged with their narrower subtasks.

Run relevant verification before publication; use the project's `tank-verify-change` skill for implemented changes. Record executed results, independent review when available and uncovered human checks separately. Preserve uncommitted work not covered by this request.

Write the exact body to a UTF-8 temporary file, then use `--body-file` to preserve newlines without shell interpolation of prose:

```sh
git push -u origin BRANCH
gh pr create --repo JarrettChen217/tank-trouble-reconstruction --base BASE --head BRANCH --draft --title '[S1.2] feat: add speed-limited tank movement' --body-file tank-pr-body.md
# For an existing PR:
gh pr edit PR_NUMBER --repo JarrettChen217/tank-trouble-reconstruction --title '[S1.2] feat: add speed-limited tank movement' --body-file tank-pr-body.md
```

Choose the observed integration base; a stacked PR needs its prerequisite PR and retargeting condition stated in the body. Keep draft when implementation review or acceptance remains pending. Use ready-for-review when actually ready and consistent with Hao's request. Attach every created PR to the current Codex chat with `attach_artifact` when that tool is available; also attach existing PRs being updated.

## Verify GitHub → Asana and report

Read `docs/ASANA_INTEGRATION.md` and the actual workflow files for current configuration. At authoring time, attachment triggers are `opened/reopened/edited`; notification triggers are `opened/reopened/closed`. A push or body edit does not inherently produce a notification comment.

1. Verify the published title, body, branch/base and task URLs with `gh pr view`; inspect relevant checks using `gh pr checks` / `gh run view`.
2. Read the **primary Asana task's** attachments through MCP (or the authorized Chrome fallback) and verify the actual GitHub card/attachment points to this repository and PR. If multiple task URLs are present, inspect covered tasks before claiming that each received a native attachment; a URL in a description is not proof of an attached GitHub card.
3. If attachment has not appeared, inspect the workflow result, URL/project allowlist and event. Correct a concrete mismatch within authorization and re-check. Do not recreate PRs or retry edits blindly.
4. When Asana updates are authorized, write actual PR/commit/CI links and remaining acceptance items to the appropriate tasks. Retain existing descriptions, owner, dates and dependencies. Descriptions require complete English, `---`, then matching complete Chinese. PR creation/CI success alone does not complete a task, establish gameplay acceptance or approve a course gate.
5. Report the PR URL, mapped task(s), actual verification and attachment outcome, plus any remaining acceptance/base dependency. Distinguish code implemented, review pending, merged and task accepted. Do not automatically merge.
