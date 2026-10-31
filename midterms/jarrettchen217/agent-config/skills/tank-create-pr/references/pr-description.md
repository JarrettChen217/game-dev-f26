# English PR description template

Start with the concrete problem and resulting behavior. Use the following order; omit optional sections when they add no useful information. Replace all example placeholders before publishing.

```markdown
Implement <delivery result>, so <concrete behavior>. <Important scope boundary or limitation, if applicable.>

## Asana

Primary task: [<task tag and actual title>](<full verified task URL>)

Covered tasks/subtasks:
- [<tag and actual title>](<full verified task URL>): <delivered responsibility; remaining items if partial>.

## Validation

- <Executed check and actual result>.
- <Independent review result, if performed>.
- <Visible/input check result, if relevant; identify anything pending>.

## Dependencies and acceptance

<Prerequisite PR/base and retargeting condition, if stacked.>
<Outstanding review or human acceptance; task status supported by evidence.>

AI-use disclosure: <Actual AI assistance and human responsibility; do not invent models, executions or reviews.>
```

For a compact change, a short opening, primary Asana URL, validation and disclosure suffice. For a parent PR, list only subtasks actually covered. For a subtask PR, use that subtask as primary and link its parent as context. For multiple tasks, explain each contribution and partial coverage. Use full task links, not the project's home/list URL, in the Asana section.

PR #5 illustrates a single S1.1 delivery spanning its three children. PR #2/#3 illustrate workflow changes and explicit integration evidence. Those examples are historical; read their live bodies when accessible and substitute the current diff, task links and executed results.
