---
name: tank-verify-change
description: Verify an implemented Tank Trouble change against its task and game rules, run project checks, and report reproducible failures. Use for code or workflow changes, not open-ended brainstorming.
---

AI-use disclosure: Codex authored this project skill under Hao's direction.

# Verify a Tank Trouble change

Read the task, relevant spec section and diff. Focus on the changed behavior; do not re-audit the whole design or invent future requirements.

Use only the project `.venv`: `uv sync --frozen`, then `uv run --frozen ruff check .`, `uv run --frozen python scripts/check_setup.py` and `uv run --frozen python scripts/run_tests.py`. Never install globally. These commands make no model calls. Inspect actual exit codes and output.

For gameplay changes, select the relevant collision, reflection, lifetime, self-hit, action-boundary or restart cases. Preserve a reproduction for real defects. Require a visible play check for input/render changes; headless success alone is insufficient. If there is no gameplay code yet, report setup-only evidence, not a completed game milestone.

Report task/scope, actual commands and results, uncovered checks, failures with reproduction and the next necessary action. Give this evidence to an independent reviewer and Hao. Do not approve course gates, merge PRs, publish builds or authorize external integrations. Retry only after a concrete fix or changed condition, not to seek a lucky pass.

Configuration and handoff policy: [agent-config.json](../../../agent-config.json). Update the current progress entry with evidence; do not mark planned work complete. The student may replace the model or revise this skill as real failures emerge.
