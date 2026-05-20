# memory-system

> 完整文档：**https://EthanQC.github.io/memory-system/**

![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue)
![Docs](https://img.shields.io/badge/docs-MkDocs%20Material-526CFE)

本地优先的个人记忆系统。给 **Claude Code / Codex / OpenClaw** 三端 AI 提供同一份本地、可加密、可同步、会自动学习用户画像的记忆底座。

> **设计目标**：无论今天用哪一个 AI，明天换一个 AI，后天又换设备 —— 记忆都跟着人走，不跟着工具走。

## 装：让 AI 替你跑

推荐方式 —— 把下面这段 prompt 复制给你手头任意一个 AI（CC / Codex / OpenClaw / 其他 MCP 兼容 agent）：

```markdown
请帮我安装 memoryd（本地优先的个人记忆系统）。完整流程：

1. git clone https://github.com/EthanQC/memory-system 到我的 ~/memory-system
2. cd ~/memory-system/memoryd
3. uv venv && source .venv/bin/activate && uv pip install -e .
4. memoryd setup auto-install（一键挂三端 hook + cron + 后台守护）
5. 验证：memoryd --help 应列出所有子命令；memoryd-mcp --help 应看到 MCP server
6. 跑一条测试：
   echo '{"session_id":"install-test","transcript_path":"","cwd":"'"$(pwd)"'"}' | memoryd capture --source=manual
7. 列回看：memoryd list --limit=3

如哪步报错，把完整错误贴出来一起诊断。

注意：**不需要配 LLM API key**。capture / search / list / show / sync 核心功能完全本地工作。
只有想用"自动学习用户画像 + 实体抽取"等可选增强功能时才需要 LLM。4 条路径任选其一：

- **claude-code**（推荐已有 CC 订阅的人）：`memoryd config set llm.provider claude-code`
  内部 spawn `claude -p`，复用你 CC 已登陆账号，**零 API key、零额外费用**
- anthropic / openai：`export <ANTHROPIC|OPENAI>_API_KEY=...`，按 token 计费
- ollama：完全本地、离线
```

详细步骤 + 手工安装路径见 [详细安装](https://EthanQC.github.io/memory-system/getting-started/installation/)。

## 它能做什么

- **三端打通**：CC 用原生 SessionStart/End hook，Codex 用 notify wrapper + 文件系统监听，OpenClaw 用原生 plugin（3 工具 + 2 hook）。三端写入同一记忆库，互相读得到对方写的内容。
- **本地优先**：所有记忆默认存在 `~/.local/share/memoryd/` 下的 Markdown 文件 + SQLite 索引。零云端依赖。
- **会自动学习**：每次会话结束自动抽实体、写关系、检测决策演化；每周 LLM 重写 `identity.md`；每月生成画像变化报告。新会话开场时 SessionStart hook 把画像 + top 实体 + 最近决策注入给 AI，AI 一开始就"认识"你。
- **混合搜索**：ripgrep 关键词 + Milvus Lite 向量（bge-m3 ONNX 本地默认）+ RRF 重排 + 实体加权。
- **跨设备同步**：标准 `memories.json` 格式（向后兼容 mcp-memory-service v5），可经任意云盘同步（iCloud / Dropbox / Syncthing / git 都行）。敏感记忆本地 AES-256-GCM 加密、跨机用 passphrase。
- **可审批**：会话摘要先入"工作记忆"，DURA 4 准则评分 + 用户审批通过后才升为"长期记忆"——避免 AI 自己说的垃圾喂坏画像。
- **敏感保护**：标记敏感的 scope 自动加密 + 授权访问 + SHA256 审计链。

## 如何向 AI 提问

装完后正常用 CC / Codex / OpenClaw 即可，会话结束时会自动 capture。需要查回历史时，**直接用自然语言问**：

- "我之前怎么决定 X 的？"
- "上次跑 Y 时遇到的错误是什么？"
- "记一下这个决策：……"

AI 会自动调 `mem_search` / `mem_save` / `mem_timeline` 等 MCP 工具。完整工具列表见 [MCP 工具](https://EthanQC.github.io/memory-system/reference/mcp-tools/)。

## LLM key 是可选的

| 不需要 LLM | 需要 LLM（可选增强） |
|---|---|
| `capture` / `search` / `list` / `show` | `analyze-session`（DURA 评分 + 实体抽取） |
| `sync export` / `sync import` | `profile rewrite`（weekly identity） |
| `sensitive` 全套（加密、grant、audit） | `profile report --month=...`（月度变化报告） |
| MCP `mem_save` / `mem_search` / `mem_get` / `mem_timeline` / `mem_context` 等 | `kg extract` / MCP `mem_judge` / `mem_compare` |

可选 LLM 三选一：Anthropic Claude / OpenAI / **Ollama**（本地推理，零成本）。

## 文档入口

完整文档站：**https://EthanQC.github.io/memory-system/**

- **给用户**：[让 AI 帮你装](https://EthanQC.github.io/memory-system/user/install-via-ai/) · [5 分钟开始](https://EthanQC.github.io/memory-system/getting-started/quickstart/) · [使用教程](https://EthanQC.github.io/memory-system/tutorials/) · [三端集成](https://EthanQC.github.io/memory-system/integrations/claude-code/) · [日常运维](https://EthanQC.github.io/memory-system/operations/daily/) · [FAQ](https://EthanQC.github.io/memory-system/faq/)
- **给开发者**：[架构全景](https://EthanQC.github.io/memory-system/architecture/overview/) · [CLI](https://EthanQC.github.io/memory-system/reference/cli/) · [MCP 工具](https://EthanQC.github.io/memory-system/reference/mcp-tools/) · [仓库结构](https://EthanQC.github.io/memory-system/development/repo-layout/) · [贡献](https://EthanQC.github.io/memory-system/development/contributing/)

## License

memory-system 自身代码：**MIT**。

各模块按文件 fork 自上游：mem0 (Apache-2.0) / claude-mem (MIT) / memsearch (MIT) / engram (MIT) / claude-context (MIT)。fork 文件头标注上游 path + license。
