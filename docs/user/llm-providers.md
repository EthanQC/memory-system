---
title: LLM provider 选项
keywords: LLM, provider, claude-code, anthropic, openai, ollama, API key, 可选, 增强
---

# LLM provider 选项 —— 什么场景才需要 LLM

memoryd 把功能分成两层：

- **核心层**（90% 日常）：完全本地、不需要任何 LLM。`capture` / `search` / `list` / `show` / `sync` / `sensitive` / SessionStart 注入 / 大部分 MCP 工具都在这一层。
- **增强层**（可选）：会话评分、知识图谱实体抽取、画像自学习、月度报告 —— 需要一个 LLM provider 当大脑。

这篇文档说清楚：**哪条命令用 LLM、不用 LLM、跳过会怎样、4 个 provider 各自的 trade-off**。

## 一图速览：哪些命令用 LLM

| 命令 / 工具 | 用 LLM 吗 | 跳过会怎样 |
|---|---|---|
| `memoryd capture` | 不用 | —— 这是基础写入，永远本地 |
| `memoryd search` | 不用 | 关键词 + 本地 ONNX 向量 + RRF 重排，无任何外部调用 |
| `memoryd list` / `show` / `delete` | 不用 | 纯查 SQLite + Markdown |
| `memoryd sync export` / `sync import` | 不用 | 文件级 mirror，零 LLM |
| `memoryd sensitive mark/unmark/grant/revoke` | 不用 | AES-256-GCM 本地加密 |
| `memoryd inject`（SessionStart 注入） | 不用 | 只读已有 `identity.md` + top 实体表，不重新生成 |
| `memoryd analyze-session` | **用** | 跳过 → 该 session 不抽实体、不入 KG。但 session 本身已经被 `capture` 写入了，搜索仍能搜到；只是失去"实体加权"和"关系图"两层智能 |
| `memoryd profile rewrite` | **用** | 跳过 → `identity.md` 维持上次版本不更新。新会话 SessionStart 注入用的还是旧画像 |
| `memoryd profile report --month=...` | **用** | 跳过 → 没有月度变化报告。可以手工读原始记忆代替 |
| `memoryd kg extract` | **用** | 跳过 → 当次实体抽取不发生；旧图谱仍在 |
| MCP `mem_judge` | **用** | 跳过 → 无法让 LLM 评"这条新记忆是不是覆盖旧的" |
| MCP `mem_compare` | **用** | 跳过 → 无法做 LLM 驱动的 supersedes 自动检测 |
| 其余 MCP（`mem_save` / `mem_search` / `mem_get` / `mem_timeline` / `mem_context` / `mem_recent` 等） | 不用 | 这些是数据访问层，LLM 用 prompt 调用它们 —— LLM 是调用方，不是被调方 |

> 设计原则：**LLM 帮你"学习记忆"，不参与"读写记忆"**。这样断网 / 没 key / 不想付费时，核心闭环依然完整。

## 4 个 provider 怎么选

| provider | 适合什么人 | 配置 | 成本 | 离线 |
|---|---|---|---|---|
| **`claude-code`** | 已经在用 Claude Code 订阅、不想为 memoryd 单独付费 | `memoryd config set llm.provider claude-code` —— 内部 spawn `claude -p` 复用已登录账号，零 API key | $0（吃 CC 订阅 quota） | 不（要联网） |
| `anthropic` | 想用 Anthropic 官方 API 直连、不依赖 CC 客户端 | `export ANTHROPIC_API_KEY=sk-ant-...` + `memoryd config set llm.provider anthropic` | 按 token | 不 |
| `openai` | 习惯 OpenAI 生态 | `export OPENAI_API_KEY=...` + `memoryd config set llm.provider openai` | 按 token | 不 |
| `ollama` | 完全本地 / 离线 / 不让数据离开机器 | `ollama serve` + `memoryd config set llm.provider ollama` + 配 `llm.model` | $0 | **是** |

什么都不配也行 —— 增强层功能会自动跳过，core 不受影响。

## `claude-code` provider 工作原理

> 给已经付费 CC 订阅的人：weekly identity rewrite / 月度报告就用你的订阅 quota 跑，零额外开销。

memoryd 内部 spawn `claude -p --model <m>`：

1. 把 prompt 通过 stdin 喂给 `claude` 子进程
2. 读 stdout 当 LLM 输出
3. 子进程退出后回收

每次冷启动 ~1-3 秒。对于"周/月级 cron 任务"完全可忽略；对于实时 MCP 工具（`mem_judge` / `mem_compare`）会稍慢于直接 API，但仍在可接受范围。

```bash
# 切到 claude-code provider
memoryd config set llm.provider claude-code
memoryd config set llm.model claude-haiku-4-5    # 也可换 sonnet / opus

# 手动触发 weekly 学习（不用等到周一）
memoryd profile rewrite

# 看刚写出来的画像
memoryd profile show
```

### 也可以让 CC 自己在会话里跑学习

不用 cron、不用 provider 配置，直接在 Claude Code 会话里说：

> "帮我跑一次 weekly identity rewrite，用你自己当 LLM 不要调外部 API。"

CC 会调 `mem_search` / `mem_timeline` 拿本周数据，自己生成 markdown，再写盘。这是**最显式**的复用方式 —— 能看到 CC 一边读数据一边写画像。

## `ollama` 完全本地路径

```bash
# 1. 装 ollama（macOS：brew install ollama；Linux：见 ollama.com）
ollama serve

# 2. 拉一个能 follow JSON-schema 的小模型
ollama pull qwen2.5:7b-instruct

# 3. 切 provider
memoryd config set llm.provider ollama
memoryd config set llm.model qwen2.5:7b-instruct
memoryd config set llm.base_url http://127.0.0.1:11434

# 4. 跑一次画像重写验证
memoryd profile rewrite
```

7B 级别模型在 M 系列 Mac 上一次 weekly rewrite 大约 30-90 秒，离线、不付费、不出本机。质量比 Claude / GPT 弱，但够用来"自学习画像"。

## 切 provider 不丢数据

memoryd 的所有数据（Markdown + SQLite + Milvus）都跟 provider 无关。今天用 `claude-code`，明天换 `ollama`，已经写出来的 `identity.md` / KG 关系 / 会话评分都仍然有效，下一次 LLM 任务用新 provider 接着写。

## 跳过 LLM 也能用的工作流

如果你完全不想配 LLM：

1. 正常 `capture` / `search` —— memoryd 已经是一个能用的 grep + 向量搜索引擎
2. 手动写 `~/.local/share/memoryd/profile/identity.md`，下次 SessionStart 就会注入
3. 想"学习"时，临时切到 CC 会话里说"读最近一周的 `mem_recent`，帮我重写 `identity.md`" —— CC 当场跑

这就是为什么 memoryd 把 LLM 设计成可选的：**画像自学习是锦上添花，本地记忆 + 跨端共享才是底座**。

## 排查：增强层突然不工作

```bash
# 看当前 provider 配置
memoryd config show | grep -A2 '"llm"'

# claude-code provider：测一下 claude CLI 是否能跑
claude -p --model claude-haiku-4-5 <<< "say hi"

# anthropic / openai：测 key
echo $ANTHROPIC_API_KEY    # 不该是空
echo $OPENAI_API_KEY

# ollama：测服务
curl http://127.0.0.1:11434/api/tags
```

更详细的故障排查见 [故障排查](../operations/troubleshooting.md)。
