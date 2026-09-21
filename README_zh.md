# AI in Practice: Game Design and Development

> 中文精翻版 · [English](README.md)
>
> `columbia-university-ai-games/game-dev-f26` 的个人 fork（派生仓库）。

这是 COMS E6998 section 014（2026 年秋季学期）课程 **AI in Practice: Game Design and Development** 的学生 starter（起始项目）。这是一门研究生层次课程，也按照课程公布的选课政策接收本科生。课程作业要求以 CourseWorks 上的 syllabus（课程大纲）为准。本 starter 包含原创的三房间游戏 **The Garden Door**、一个可选的 model narrator（模型叙述器）、测试以及 Setup Verification（环境设置验证）工作流。其中不包含任何 Infocom 源代码或素材。

游戏可以完全离线运行。设置诊断程序也可以检查你所选 provider（模型服务提供商）的 live-model access（实时模型访问权限），以及需要手动授权的 live CI（实时持续集成）。在布置 fork 工作流之前，教师必须先确认学生拥有该仓库的访问权限。

**设置准备：** 请争取在 9 月 18 日前达到 offline readiness（离线就绪）状态：环境配置完成、游戏能够运行、Git/gh 可以访问、本地测试通过，并且 deterministic CI（确定性持续集成）正常。学校提供的 Google credits（Google 云额度）和个人 Google Cloud 项目从 9 月 21 日开始使用；请争取在 9 月 28 日前达到 live readiness（实时调用就绪）状态。Setup 没有单独的成绩，也不需要单独提交 verification。若访问权限延迟，请向教师报告以获得支持，同时继续完成 reflection（反思）和设计工作；无需自行购买可选服务。诊断程序中的“Setup Verification”标签描述的是技术检查结果，并不代表一项单独的课程作业。期中和期末项目仍然需要提交项目测试与 live evaluation（实时评估）的证据。

## 课程选择与本示例

快速导航：[设置](#1-prepare-this-examples-environment) · [试玩](#2-play-and-inspect-the-boundary) · [模型 provider](#3-choose-a-live-model-provider) · [GitHub Actions](#4-verify-your-fork-in-github-actions) · [项目推进](#5-carry-this-into-the-projects) · [故障排查](#troubleshooting)

课程项目可以使用任意语言以及 engine/framework（引擎/框架）。本仓库只是一个 Python/Pyxel 示例；其中的安装和引擎检查只适用于这个示例。等效项目可以使用 Three.js、Babylon.js、PlayCanvas 或其他工具。本课程不专门教授某一种引擎，而是聚焦于通过 agentic engineering（智能体式工程）打造优秀游戏。课程结束时，你将拥有一个由 agent（智能体）组成、覆盖游戏开发各个角色的团队；与此同时，你始终担任 Executive Producer（执行制作人）和 Creative Director（创意总监）。你保留对愿景、范围、优先级以及工作验收的控制权；你的 agents 则承担边界明确的职责，并提供可供审查的证据。

如果采用其他技术栈，请记录 runtime/dependencies（运行环境/依赖项）以及 setup/play/test 命令。你需要展示 Git/gh 访问正常、游戏可在本地运行、一次 live model call（实时模型调用）成功，以及有意义的测试在本地和 GitHub Actions 中均通过。请提交同样类型的证据链接。使用其他技术栈时，无需使用 Python 或 Pyxel 也能满足这些要求。

课程教授使用 Cloudflare 进行发布和构建 AI workers。若要使用其他部署平台，必须事先获得教师许可；同时需要证明该平台具备等效的 credential handling（凭据处理）、state isolation（状态隔离）、evaluation（评估）、limits（限制）与 fallback（回退机制）。

<a id="1-prepare-this-examples-environment"></a>

## 1. 准备本示例的环境

安装 Python 3.11 或更高版本、Git、GitHub CLI 和 uv。请使用 [Python](https://www.python.org/downloads/)、[Git](https://git-scm.com/downloads)、[GitHub CLI](https://cli.github.com/) 与 [uv](https://docs.astral.sh/uv/getting-started/installation/) 的官方说明在 macOS、Windows 或 Linux 上安装。然后在终端运行：

```sh
gh auth status
python --version
git --version
gh --version
```

如果 `gh auth status` 确认你已经使用预期账号登录 GitHub.com，请保留现有登录状态。如果尚未登录或凭据无效，请完成认证并再次检查：

```sh
gh auth login
gh auth status
```

如果你的 Python 安装将命令名称暴露为 `python3`，请使用 `python3`。教师确认你拥有仓库访问权限并启用 fork 后，创建 fork 并克隆仓库：

```sh
gh repo fork columbia-university-ai-games/game-dev-f26 --clone
```

如果无法 fork，请联系教师。私有仓库能否 fork 同时取决于 organization（组织）和 repository policy（仓库策略）；重新登录无法解决策略限制。请勿为了绕过限制而更改仓库可见性。

接下来所有命令都应在**克隆得到的文件夹内**打开的终端中运行：

```sh
uv sync --frozen
uv run --frozen python -m unittest discover -s tests -v
uv run --frozen python -m course_game.setup_check --offline --headless
uv run --frozen python -m course_game
```

离线诊断会明确报告这只是部分 Setup Verification。fixture（脚本化测试替身）是预先编写的文本，不是实时模型，也不是某次模型输出的录音或记录。测试和 setup check 都不会创建 commit（提交）或 push（推送）代码。

要确认你的电脑能够显示游戏引擎窗口，请运行：

```sh
uv run --frozen python -m course_game.engine_check
```

Pyxel 窗口会绘制一帧画面，并在大约一秒后关闭。Headless CI（无界面持续集成）会初始化同一个引擎，并在不打开窗口的情况下检查一个已绘制的像素。

<a id="2-play-and-inspect-the-boundary"></a>

## 2. 试玩并观察系统边界

可用命令：`look`、`east`、`west`、`take key`、`unlock door`、`north`、`quit`。通关路径是：east、take key、west、unlock door、north。阅读 `course_game/world.py`，了解为什么没有钥匙就无法通关。

输入 `ask look`，让 narrator 描述当前可见的房间；也可以输入 `ask what is behind the door?`，询问它尚未观察到的信息。请将 narrator 的回答与提供给它的事实进行比较。有效的 JSON 和有效的 fact IDs（事实标识符）并不能保证叙述真实准确。即使 narrator 出错，游戏 action（动作）仍然是 deterministic（确定性的）。

<a id="3-choose-a-live-model-provider"></a>

## 3. 选择 live model provider

你可以通过 Vertex AI 使用 Gemini，也可以使用 Anthropic 模型或 OpenAI 模型。课程资助的默认选项是 Vertex AI。其他 provider 同样符合要求；你只需要让**一个** live provider 正常工作。请选择支持本 adapter（适配器）所需 structured JSON output（结构化 JSON 输出）且符合预算的模型。starter 没有硬编码任何会产生费用的模型，也绝不会在 provider 或模型之间自动切换。

你用于开发代码的 build assistant（开发助手），与游戏在运行时调用的模型，是两个相互独立的选择。请单独配置 runtime API access（运行时 API 访问）。不要假设课程提供的 Google credits 会涵盖其他 provider。

所有 live provider 都要求设置 `COURSE_MODEL`，其值应为你所选 API model ID：

| CLI provider | 其他本地配置 | CI 配置 |
|---|---|---|
| `vertex` | `GOOGLE_CLOUD_PROJECT`、`GOOGLE_CLOUD_LOCATION`、Google Application Default Credentials | 相同变量，另加 `WIF_PROVIDER` 和 `COURSE_SERVICE_ACCOUNT` |
| `anthropic` | `ANTHROPIC_API_KEY` | Actions secret `ANTHROPIC_API_KEY` |
| `openai` | `OPENAI_API_KEY` | Actions secret `OPENAI_API_KEY` |

使用 Vertex AI 时，请使用你自己的课程 Google Cloud 项目，并将其关联至符合资格的课程 credit billing account（额度结算账号）。在第 2 周，教师会提供额度兑换和项目设置说明、支持的 location（区域），以及经过验证、可由课程资助的模型选项。请勿使用其他学生的项目。安装 [Google Cloud CLI](https://cloud.google.com/sdk/docs/install)。对于获批准的个人账号，本地登录通常使用 `gcloud auth application-default login`。AI Studio key 属于另一种访问方式，不能证明你具备使用学校额度的资格。

使用 Anthropic 或 OpenAI 时，请获取经过授权的 API access，并将所选 provider 的 key 安全地加载到本地环境中。绝不要把 key 粘贴到课程提交内容、终端录屏、Asana task 或本仓库中。受版本控制的 `.env.example` 只记录变量名称，不会被自动加载。你可以通过 `uv run --env-file .env ...` 加载被忽略的本地 `.env` 文件；请保持其私密，并避免在演示过程中泄露其中内容。

在 shell 中设置非敏感配置，例如：

```sh
export COURSE_MODEL='YOUR_CHOSEN_MODEL_ID'
# Vertex only:
export GOOGLE_CLOUD_PROJECT='YOUR_COURSE_PROJECT'
export GOOGLE_CLOUD_LOCATION='YOUR_APPROVED_LOCATION'
```

PowerShell 使用 `$env:COURSE_MODEL = 'YOUR_CHOSEN_MODEL_ID'`；Vertex 变量也采用相同语法。请只选择以下一条 live path（实时调用路径）：

```sh
uv run --frozen python -m course_game.setup_check --provider vertex --headless
# OR:
uv run --frozen python -m course_game.setup_check --provider anthropic --headless
# OR:
uv run --frozen python -m course_game.setup_check --provider openai --headless
```

交互式游戏接受同样的 provider 选择，例如 `uv run --frozen python -m course_game --provider openai`。如果省略 play 选项，程序会使用 scripted fixture（脚本化 fixture）。Setup 必须接收 `--offline` 或明确的 `--provider`，之后才会运行任何诊断。

live check（实时检查）会发出一次 inference request（推理请求）。交互式游戏最多允许五次 live attempt（实时尝试），失败的请求也计入次数。每个 provider 的 HTTP timeout 为 20 秒、禁用自动重试，并将输出限制为 1,024 tokens。这些是 request controls（请求控制），并不保证总耗时或费用。有些模型需要更大的 reasoning/output budget（推理/输出预算），可能无法通过这一小型检查；此时请选择兼容模型，或记录你对限制所做的有意调整。程序不会自动进行付费重试或降级模型。

每个 adapter 都会验证相同的 JSON shape（JSON 结构）以及允许使用的 fact IDs。有效的 JSON 并不能证明内容在事实上准确。Setup 会在出现错误、拒绝响应或不可用输出时失败；交互式游戏则会在这种情况下显示权威的游戏文本。报告包含 provider、model identifier（模型标识符）、latency（延迟）和 token usage（token 用量）。不同 provider 的 token 分类和价格各不相同，仅比较总 token 数并不能比较成本。估算费用时，请记录当日的定价。

<a id="4-verify-your-fork-in-github-actions"></a>

## 4. 在 GitHub Actions 中验证你的 fork

每次 push 和 pull request（PR）都会在 Python 3.11 与 3.12 上运行 deterministic checks（确定性检查），其中包括使用 mocked adapter（模拟适配器）、不会产生模型流量的测试。如果系统提示，请在你的 fork 上启用 Actions。检查并 push 一次小型 README 修改，以触发这些检查。

第 2 周的课程资助设置完成后，如需运行手动 live check，请将 repository variable `COURSE_MODEL` 设置为所选 provider 使用的模型，并加入上表列出的该 provider 专属配置。API key 必须存入 Actions **secrets**，绝不能存入 variables。只有被选中 provider 的 step 会收到对应 key。

Vertex CI 使用 GitHub OIDC 和 Google Workload Identity Federation。教师必须配置 trust policy（信任策略），将访问范围限制在经过批准的学生仓库以及预期的 branch/workflow。无需保存 service account key。其他 provider 使用各自的 API secret，不需要 Google Cloud 配置或认证。

在 Actions 中选择 **Setup and deterministic checks**，在受信任的 default branch（默认分支）上选择 **Run workflow**，选择 provider 并启用 `live`。live job 仅允许通过 default branch 上的 manual dispatch（手动触发）运行。在使用凭据运行之前，请审查 workflow 和代码变更。PR 不会获得任何模型凭据。被跳过的 live job 不算 live pass（实时验证通过）。

进行个人 readiness check（就绪检查）时，请确认游戏能在本地运行、确定性测试能在本地和 CI 中通过，并且在获得资助访问权限后，所选 live path 能够成功执行。在项目评估中记录 provider/model 信息。Setup report 可以帮助诊断访问失败，但无需单独提交 verification。教师会为学校访问权限延迟问题提供支持。离线检查不会产生任何付费调用。

<a id="5-carry-this-into-the-projects"></a>

## 5. 将这些方法应用到课程项目中

在 Session 2 中，选择一款 classic game（经典游戏），设计一个范围受控的 reconstruction（重建版本），并为其定义清晰规则、source evidence（来源证据）以及结局或 episode limit（回合上限）。Infocom 只是一个示例集合；课程也鼓励选择其他经典作品和类型。在 Session 3 中，配置负责构建游戏的 agent team，并为能够游玩该游戏的 agent 定义 observation/action interface（观察/动作接口）。在 Session 4 中，加入 scripted baseline（脚本化基线）或 search baseline（搜索基线），以及 deterministic episode tests（确定性回合测试）。在 Session 5 中，将 model-driven player（模型驱动玩家）与 baseline 进行比较，其中包括它们对信息和记忆的需求。

期中项目同时包含一个重建的游戏，以及一个能够游玩它的 agent。starter 中的 narrator 用于演示 model boundary（模型边界）；它是 stateless（无状态）的，也不会选择 action。player agent、episode runner（回合运行器）、reusable skill（可复用技能）和 independent reviewer（独立审查者）属于后续练习内容。NPC 和创意改写是可选内容。self-play（自我对弈）适用于竞技游戏；单人游戏则使用 solver（求解器）。

使用 Asana 管理 task、owner（负责人）、acceptance criteria（验收标准）、dependency（依赖关系）、每周 PPP 和 gate decision（阶段门决策）。在 PR 描述中链接 task URL，并在 task 中链接 PR/CI URL。GitHub 用于保存代码和 release（发布版本）；CourseWorks 用于保存成绩和私密反馈。已经完成的 task 不能代替人批准 gate，也不能代替人 merge PR。

后续用于 Cloudflare 发布和 AI worker 的基础设施是教师另外提供的教学 artifact（教学制品）。本 starter 不会部署服务，也不会创建 Asana project。完整的 course manifest（课程清单）会记录 native artifact path（原生制品路径）、policy、failure mode（失败模式）、测试命令与 CI；不同平台原生的 plugin/skill 格式仍然彼此独立。

## 关键文件

| 文件或文件夹 | 用途 |
|---|---|
| [course_game/world.py](course_game/world.py) | 权威规则与状态 |
| [course_game/narrator.py](course_game/narrator.py) | 可选的 provider adapter 和共享验证逻辑 |
| [course_game/setup_check.py](course_game/setup_check.py) | 明确区分 offline/live 的设置诊断程序 |
| [course_game/engine_check.py](course_game/engine_check.py) | Pyxel 示例的 smoke check（冒烟检查） |
| [agent-config.json](agent-config.json) | 通用 agent 配置与限制 |
| [tests/](tests/) | 确定性规则测试和 mocked-provider 测试 |
| [.github/workflows/setup-check.yml](.github/workflows/setup-check.yml) | CI 和需要手动授权的 live check |
| [pyproject.toml](pyproject.toml) 与 [uv.lock](uv.lock) | 示例依赖项及其可复现版本 |
| [.env.example](.env.example) | 非敏感设置变量指南 |
| [AGENTS.md](AGENTS.md) | 面向 development agent（开发智能体）的指令 |

<a id="troubleshooting"></a>

## 故障排查

- **GitHub auth 失败：** 在本地运行 `gh auth status`，然后运行 `gh auth login`。绝不要将 access token 粘贴到报告中。
- **引擎导入失败：** 确认 `uv sync --frozen` 已成功完成，并使用 `uv run --frozen`。headless check 无法验证你电脑上的显示功能。
- **缺少模型配置：** 设置 `COURSE_MODEL` 以及所选 provider 的凭据。只有 Vertex 需要 Google project 和 location。
- **Live request 失败：** 检查已批准的 identity（身份）、已启用的 API、location、模型访问权限与 quota（配额）。检查程序会报告 exception type（异常类型），但不会输出凭据或 request content（请求内容）。请保留 error category（错误类别），以便寻求支持。
- **CI live job 失败或被跳过：** 检查它是否在受信任 default branch 上手动触发，并确认所选模型与 provider 凭据均已配置；Vertex 还需要 OIDC trust。离线检查显示绿色通过，不能代替这项证据。

参考文档：[Pyxel](https://github.com/kitao/pyxel)、[Google Gen AI SDK](https://github.com/googleapis/python-genai)、[GitHub-to-Google authentication](https://github.com/google-github-actions/auth)、[Asana authentication](https://developers.asana.com/docs/authentication)。

Provider 参考：[OpenAI quickstart](https://developers.openai.com/api/docs/quickstart)、[OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs)、[Anthropic Messages](https://platform.claude.com/docs/en/api/messages/create)、[Anthropic structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)。
