# README 中文精翻 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增一份完整、准确并保留关键英文技术术语的 `README_zh.md` 中文译本。

**Architecture:** 以根目录 `README.md` 为唯一内容来源，逐节翻译并保持 Markdown 拓扑一致。译文作为独立文件存在，不修改英文原文、程序代码或课程配置。

**Tech Stack:** Markdown、Git、基础 shell 文本检查工具

**Spec:** `docs/superpowers/specs/2026-09-21-readme-zh-translation-design.md`

## Global Constraints

- 使用自然流畅的中文表达，不采用机械逐词翻译。
- 重要英文术语在首次出现时保留英文并附中文解释。
- 命令、代码块、环境变量、文件路径、模型 ID 和配置值保持原样。
- 保留原 README 的标题层级、段落顺序、列表、表格、引用、代码块和链接目标。
- 不添加原文没有的课程要求、结论或操作步骤。
- 仅新增 `README_zh.md`；不修改 `README.md`。

---

### Task 1: 翻译并校对 README

**Files:**
- Read: `README.md`
- Read: `docs/superpowers/specs/2026-09-21-readme-zh-translation-design.md`
- Create: `README_zh.md`

**Interfaces:**
- Consumes: 英文 README 的 Markdown 结构、链接、代码块和全部正文
- Produces: 可独立阅读且可与英文原文逐节对照的中文 Markdown 文档

- [x] **Step 1: 建立完整文档骨架**

复制原文的标题层级、段落顺序、列表、表格、引用、链接和代码块到 `README_zh.md`，在顶部加入中文译本说明及 `[English](README.md)` 返回链接。

- [x] **Step 2: 逐节完成术语保留型精翻**

翻译导言、课程选择、环境准备、游戏体验、live model provider、GitHub Actions、项目推进、关键文件和故障排查。首次出现的关键术语采用“英文（中文解释）”形式；命令、文件名、环境变量和配置值不翻译。

- [x] **Step 3: 检查结构完整性**

分别运行以下命令，比较两份文档的结构计数：

```bash
rg '^#{1,6} ' README.md README_zh.md
rg '^```' README.md README_zh.md
rg '^\|' README.md README_zh.md
```

预期：两份文档拥有对应的章节层级；代码围栏数量相等且均为偶数；两个 provider 配置表和关键文件表的行数、列数对应。

- [x] **Step 4: 检查不可翻译内容与 Markdown 有效性**

```bash
git diff --check
rg 'COURSE_MODEL|GOOGLE_CLOUD_PROJECT|GOOGLE_CLOUD_LOCATION|ANTHROPIC_API_KEY|OPENAI_API_KEY|WIF_PROVIDER|COURSE_SERVICE_ACCOUNT' README_zh.md
rg 'uv run --frozen|gh auth|export COURSE_MODEL' README_zh.md
```

预期：`git diff --check` 无输出；所有环境变量与关键命令仍可在译文中找到，拼写与原文一致。

- [x] **Step 5: 对照校对要求强度和术语首次解释**

人工逐节对照 `README.md` 与 `README_zh.md`，重点检查 `must`、`required`、`optional`、`only`、`never`、`do not` 的语义强度；确认 `agent`、`provider`、`fixture`、`structured output`、`Setup Verification` 首次出现时含中文解释。

- [x] **Step 6: 检查改动范围并提交**

```bash
git status --short
git diff -- README_zh.md
git add README_zh.md docs/superpowers/plans/2026-09-21-readme-zh-translation.md
git commit -m "docs: add Chinese README translation"
```

预期：不包含 `.idea/` 或其他用户文件；提交只包含中文 README 和本实施计划。
