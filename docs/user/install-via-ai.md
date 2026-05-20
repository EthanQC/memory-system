---
title: 让 AI 帮你装
keywords: 安装, AI 安装, prompt, Claude Code, Codex, OpenClaw, 一键, 自动安装
---

# 让 AI 帮你装 memoryd

memoryd 推荐的安装方式：**把下面这段 prompt 复制给你手头任意一个 AI**（Claude Code / Codex / OpenClaw / 其他 MCP 兼容 agent），让 AI 替你执行安装步骤。你不用记命令，也不用排查环境差异 —— AI 跑命令看输出，遇到错误它会自己读错误信息并往下推进。

!!! tip "为什么用这个方式"
    memoryd 的核心功能（capture / search / list 等）**完全本地、零依赖云端**，但安装时要建 venv、装包、配三端 hook、启动守护进程。把这些重复劳动交给 AI，它会比你手工敲更不容易出错。

## 一键 prompt（复制给你的 AI）

```markdown
请帮我安装 memoryd（本地优先的个人记忆系统）。完整流程：

1. git clone https://github.com/EthanQC/memory-system 到我的 ~/memory-system
2. cd ~/memory-system/memoryd
3. 用 uv 创建虚拟环境并安装：
   uv venv && source .venv/bin/activate && uv pip install -e .
4. 跑 memoryd setup auto-install 一键挂三端 hook + cron + 后台守护
5. 验证：
   - memoryd --help 应该列出所有子命令
   - memoryd-mcp --help 应该看到 MCP server 入口
6. 跑一条测试记忆：
   echo '{"session_id":"install-test","transcript_path":"","cwd":"'"$(pwd)"'"}' | memoryd capture --source=manual
7. 列回看：memoryd list --limit=3

如果哪一步报错，把完整错误贴出来，我们一起诊断。

注意：**不需要配 LLM API key**。capture / search / list / show / sync 这些核心功能完全本地工作。
只有以下可选功能才需要 LLM：会话 DURA 评分、知识图谱实体抽取、weekly identity 重写、月度画像变化报告。
想要这些功能 + 不想给云端付费时，可以装 Ollama 本地跑（memoryd 内置 ollama provider）。
```

把上面整段（包括代码块）丢给你的 AI 即可。AI 会按步骤跑命令、贴输出、遇到错误自己排查。

## 它会装哪些东西

| 装到哪 | 内容 | 之后能干嘛 |
|---|---|---|
| `~/memory-system/` | 仓库源码（含 memoryd + plugins + docs） | 升级时 `git pull` 即可 |
| `~/memory-system/memoryd/.venv/` | Python 虚拟环境 | 不污染系统 Python |
| `~/.local/share/memoryd/` | 数据目录（**真正的记忆库**） | Markdown SoT + SQLite 索引 |
| `~/.config/memoryd/config.toml` | 配置文件 | LLM provider / 同步盘 / SMTP 等 |
| `~/.claude/settings.json`（SessionStart/End hook） | Claude Code 集成 | CC 会话自动 capture |
| `~/.codex/config.toml`（notify wrapper） | Codex 集成 | Codex 会话自动 capture |
| OpenClaw plugins 目录 | OpenClaw 集成 | OpenClaw 会话自动 capture |
| 平台守护进程 | macOS launchd / Linux systemd / Windows Task Scheduler | decay 03:00 / weekly digest 周一 09:00 |

数据全部留在本机。卸载时一条命令清干净，见 [卸载](../operations/uninstall.md)。

## 怎么让 AI 用 memoryd

装完后，你正常用 CC / Codex / OpenClaw 即可。需要查回历史时，直接对 AI 说自然语言：

- "我之前怎么决定 X 的？"
- "上次跑 Y 时遇到的错误是什么？"
- "把这次结果记成一条决策："

AI 会自动调 `mem_search` / `mem_save` 等 MCP 工具。整套工具列表见 [MCP 工具参考](../reference/mcp-tools.md)。

## LLM key 是可选的

memoryd 把功能分成两层：

**完全本地、不需要 LLM 的核心层**（90% 日常用得到的）：

- `memoryd capture` —— 写一条记忆
- `memoryd search` —— 关键词 + 向量混合搜索（向量用本地 bge-m3 ONNX）
- `memoryd list` / `show` / `delete`
- `memoryd sync export` / `import`
- `memoryd sensitive` 全套（加密、grant、audit）
- MCP server 大部分工具（`mem_save` / `mem_search` / `mem_get` / `mem_timeline` / `mem_context` / ...）

**可选 LLM 增强层**（想要更智能的画像 / 知识图谱时再开）：

- `memoryd analyze-session` —— DURA 4 准则评分 + KG 实体抽取
- `memoryd profile rewrite` —— weekly identity 重写
- `memoryd profile report --month=...` —— 月度变化报告
- `memoryd kg extract` —— 实体抽取
- MCP `mem_judge` / `mem_compare`

LLM 可以选 4 条路径（**推荐 claude-code** —— 复用你已有的 CC 订阅，零额外成本）：

| provider | 适用场景 | 配置 |
|---|---|---|
| **`claude-code`** ⭐ | 已经在用 Claude Code 订阅，想免费跑 weekly 学习 | `memoryd config set llm.provider claude-code` —— 内部 spawn `claude -p`，用你 CC 已经登陆的账号，零 API key 需要 |
| `anthropic` | 想用 API key 直连 Anthropic | `export ANTHROPIC_API_KEY=...` + `memoryd config set llm.provider anthropic` |
| `openai` | 想用 OpenAI | `export OPENAI_API_KEY=...` + `memoryd config set llm.provider openai` |
| `ollama` | 完全本地 / 离线 | `ollama serve` + `memoryd config set llm.provider ollama` |

不配也行；以上"增强层"功能会自动跳过，core 不受影响。

### claude-code provider 工作方式

> 适合**已经付费 CC 订阅**的用户 —— weekly identity rewrite / 月度报告就用你的订阅 quota 跑，零额外开销。

memoryd 内部 spawn `claude -p --model <m>`，把 prompt 通过 stdin 喂进去、读 stdout 当 LLM 输出。每次冷启动 ~1-3 秒（对周/月级 cron 任务可忽略）。

```bash
# 切到 claude-code provider（推荐）
memoryd config set llm.provider claude-code
memoryd config set llm.model claude-haiku-4-5   # 也可换 sonnet / opus

# 手动触发 weekly 学习（不用等到周一）
memoryd profile rewrite

# 看刚写出来的画像
memoryd profile show
```

### 也可以让 CC 自己在会话里跑学习

不用 cron / 不用 provider 配置，直接在 Claude Code 会话里说：

> "帮我跑一次 weekly identity rewrite，用你自己当 LLM 不要调外部 API"

CC 会调 `mem_search` / `mem_timeline` 等 MCP 工具拿本周数据，自己生成 markdown，再写盘。这是**最显式**的复用方式 —— 你能看到 CC 一边读数据一边写画像。

## 备选：手工安装

如果你不想用 AI 跑、想自己一步步来，见 [详细安装](../getting-started/installation.md)。每一步都有"应该看到什么输出"。

## 装完之后

- [5 分钟开始](../getting-started/quickstart.md) —— 跑通"写一条 → 搜回来 → 浏览器看到"
- [首次运行](../getting-started/first-run.md) —— 三端各做一次完整闭环
- [使用教程](../tutorials/index.md) —— 9 篇实战
