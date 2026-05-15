---
title: 旧记忆导入 + memory-searcher（Plan 8）设计
date: 2026-05-15
status: 已批准（无 brainstorming：用户 prompt 已明确启发式按段切；memory-searcher 是 ~/.claude/agents/ 模板）
related:
  - docs/superpowers/specs/2026-05-09-personal-usage-and-boundary-spec.md
  - docs/superpowers/specs/2026-05-14-long-term-memory-governance-design.md
role: 设计文档——Plan 8 实施 plan 与 SDD 都引用本文档
---

# Plan 8：旧记忆导入 + memory-searcher 设计

## 0. 这份文档是什么

spec §4.7 #28 / §4.2 #5：v1 提供 `memory import` 四个子命令把旧记忆导入；提供 `memory-searcher` sub-agent 模板让 CC 智能体能自然调用 memoryd 而不占主 context。Plan 8 落地这两件。

Plan 8 不改 spec；不改 Plan 1-7 既有功能；只加 importers/ 模块 + 一个 sub-agent .md 模板。

## 1. 上游与硬约束

| 已交付 | 状态 |
|---|---|
| Plan 7 web + TUI + Basic Memory schema | merged `3aeef52` |
| Plan 3 6 类型 + SQLite + DURA | merged `4dac127` |
| Plan 4 sensitive scope | merged `8ce76aa` |
| Plan 1-2.5 capture | merged `b140b35` |

| 硬约束 | 来源 |
|---|---|
| MCP 工具数 ≤ 12（当前 8） | spec §3。本 plan **不加新 MCP 工具** |
| 不双向同步 CLAUDE.md / AGENTS.md / auto-memory | spec §6 / §8 |
| import 全单向（旧 → memoryd） | spec §4.7 #28 |
| 不接管三端原生记忆机制 | spec §6 |
| sub-agent 模板严格 ≤ 500 token 输出 | spec §4.2 #5 |

## 2. 总体架构

```
┌────────────────────────────────────────────────────────────┐
│ CLI: memoryd import <kind> <path> [--scope=<hash>]         │
│                                                            │
│ kinds:                                                     │
│   claude-md          单 .md 按 H2/H3 切成 fact/playbook/  │
│                      warning 多条                          │
│   auto-memory        ~/.claude/projects/<proj>/memory/    │
│                      整段拷（保留原 frontmatter），把每个   │
│                      .md wrap 成 memoryd 一条记忆          │
│   agents-md          Codex AGENTS.md 同 claude-md          │
│   mcp-memory-service memories.json 数组迭代                │
└────────────────────────────────────────────────────────────┘
                              ↓
┌────────────────────────────────────────────────────────────┐
│ importers/ 模块                                             │
│   claude_md.py    parse_sections + infer_type             │
│   auto_memory.py  scan_dir + copy_md                      │
│   agents_md.py    复用 claude_md.parse_sections            │
│   mcp_mem.py      json.load + map_entry                   │
│   common.py       slug 派生 / 调 storage.save_memory      │
└────────────────────────────────────────────────────────────┘
                              ↓
┌────────────────────────────────────────────────────────────┐
│ 复用：storage.save_memory（Plan 3）+ SQLite index          │
│   写入到目标 scope（默认 cwd resolve_scope_root；--scope=  │
│   覆盖）；每条带 frontmatter.source = imported-<kind>      │
└────────────────────────────────────────────────────────────┘
                              ┊
┌────────────────────────────────────────────────────────────┐
│ memory-searcher sub-agent                                  │
│   memoryd/templates/memory-searcher.md                     │
│   model: haiku-4-5, tools: Read+Grep, system prompt 严格   │
│   要求输出 JSON ≤ 500 token                                │
│                                                            │
│ memoryd setup install-memory-searcher                      │
│   把模板拷到 ~/.claude/agents/memory-searcher.md           │
│   --force 覆盖；默认拒绝覆盖已存在                          │
└────────────────────────────────────────────────────────────┘
```

## 3. 按段切（heuristic）规则

`importers/claude_md.py` 的 `parse_sections(text: str) -> list[Section]`：

1. 按 `^## ` 和 `^### ` 切。每段 Section 含：
   - `level` (2 / 3)
   - `heading`（不含 `##`）
   - `body`（heading 之后到下一段开始）
2. 推断 type（heuristic）：
   - heading 含 "warning" / "踩坑" / "不要" / "避免" → `warning`
   - heading 含 "playbook" / "流程" / "操作" / "how to" → `playbook`
   - heading 含 "decision" / "决策" / "选" → `decision`
   - heading 含 "preference" / "偏好" / "习惯" → `preference`
   - 默认 → `fact`
3. slug = `imported-<kind>-<heading-kebab-case>-<n>`，n 是同名递增数。
4. triggers = [heading 中的关键名词 ≥ 2]（简单分词；若不足 2 个 → `["imported", heading_slug]`）。
5. body 保留原段文字（≤ 8000 字符；超长截断 + 加 `...` ）。

**LLM 切分**：v1 不做（避免 import 操作绑 LLM 配置）；v2 视用户反馈加 `--llm` opt-in。

## 4. auto-memory 导入

`~/.claude/projects/<proj>/memory/` 含 `MEMORY.md`（index）+ 多个 fact/feedback/project/reference `.md` 文件。Plan 8 行为：

1. 用户跑 `memoryd import auto-memory ~/.claude/projects/<proj>/memory/`
2. 跳过 `MEMORY.md`（它是 index，不是数据）
3. 对每个其他 `.md`：
   - 解析既有 frontmatter（auto-memory 用 `metadata.type` = user / feedback / project / reference 之一）
   - map 到 memoryd type：
     - user → `fact`
     - feedback → `preference`
     - project → `fact`（含 description / why / how to apply）
     - reference → `fact`
   - source = `imported-auto-memory`
   - 复制 body 原样
   - 拼 memoryd frontmatter（保留 auto-memory 原 created_at / description）

## 5. agents-md 导入

复用 `claude_md.parse_sections` + 不同 heading keyword 词典（codex / openai/codex 项目里 AGENTS.md 措辞略不同；可选 keyword 表配置）。简化版直接复用 claude_md 规则；source = `imported-agents-md`。

## 6. mcp-memory-service 导入

mcp-memory-service `memories.json` 是数组，每元素：

```json
{
  "id": "...",
  "content": "...",
  "metadata": {
    "tags": ["..."],
    "type": "memory|note|fact|...",
    "created_at": "ISO"
  }
}
```

Plan 8 行为：
1. `json.load`
2. 遍历每条：
   - slug = `imported-mcpmem-<id|hash(content)[:8]>`
   - body = content
   - triggers = metadata.tags
   - type 推断：metadata.type 含 "fact" → fact；含 "decision" → decision；其他 → fact
   - source = `imported-mcp-memory-service`
   - created_at = metadata.created_at（或 fallback now）

## 7. CLI 命令

```bash
memoryd import claude-md ~/.claude/CLAUDE.md
memoryd import auto-memory ~/.claude/projects/-Users-xxx/memory/
memoryd import agents-md ~/.codex/AGENTS.md
memoryd import mcp-memory-service ~/Documents/mcp-memory-service/memories.json
  # 所有命令支持：
  --scope=<hash>              # 显式落到某 scope；默认 cwd 派生
  --dry-run                   # 不写，只报 plan
  --source-tag=<custom>       # 覆盖 source；默认 imported-<kind>
```

输出（默认）：

```
import: kind=claude-md path=/Users/x/.claude/CLAUDE.md
  parsed 12 sections (8 fact / 2 playbook / 1 warning / 1 decision)
  written 12 memories to scope d8e86b48589e
  dry_run=false
```

## 8. memory-searcher sub-agent template

`memoryd/src/memoryd/templates/memory-searcher.md`：

```markdown
---
name: memory-searcher
description: Fast read-only memory lookup. Use when the user asks about prior conversations, decisions, or context that may be stored in memoryd. Returns ≤ 500 token JSON.
model: claude-haiku-4-5-20251001
tools: Read, Grep
---

You are memoryd's lookup specialist. Your sole job: find relevant memories quickly and return a compact JSON response. Never invent content. Never write or modify files.

# How to find memories

1. The user's working directory determines scope. Read `~/.local/share/memoryd/scopes/<scope_hash>/`.
   - Find scope_hash: run `git rev-parse --show-toplevel` if in a git repo, else use cwd, then compute scope_hash externally (cannot from inside this agent — assume controller provides it or grep all scopes).
2. Use Grep to search `.md` files for the user's query terms.
3. Read at most 5 matching .md files; pull frontmatter (title, type, triggers, created_at) and first ~200 chars of body.

# Sensitive scopes

Never read `.md.enc` files. If you find a `.memoryd-sensitive` marker in the path, report `{"sensitive": true}` for that scope and skip its content.

# Output format

Return a single JSON object, no prose, no markdown fences:

\`\`\`json
{
  "hits": [
    {
      "slug": "2026-05-13-logo-decision",
      "type": "decision",
      "title": "logo direction blue + silver",
      "scope_hash": "d8e8...",
      "created_at": "2026-05-13T...",
      "excerpt": "<= 150 chars from body>"
    }
  ],
  "total": 1,
  "scope_used": "d8e86b48589e",
  "sensitive_skipped": []
}
\`\`\`

Total response must be ≤ 500 tokens. If more hits, return top-5 by recency + truncate excerpts.
```

注意：上面用 \` 是给 spec 文档自己 escape；写到模板文件时 ``` 三反引号原样。

### Install

```bash
memoryd setup install-memory-searcher           # cp template → ~/.claude/agents/memory-searcher.md
memoryd setup install-memory-searcher --force   # 覆盖已存在
memoryd setup install-memory-searcher --target=./.claude/agents/  # 项目级
```

## 9. 不在 Plan 8 内（边界）

| 不做 | 推迟到 |
|---|---|
| LLM 驱动的 import 切分 | v2（视用户反馈） |
| 双向同步 CLAUDE.md / AGENTS.md / auto-memory | 永不（spec §6） |
| Codex / OpenClaw sub-agent 等价物 | v2（Codex / OpenClaw 暂无 sub-agent 概念）|
| memory-searcher 跨 scope 智能选 | v2（需 LLM 判断 user 意图）|
| 自动 cron `memoryd import auto-memory` 增量 | v2 |

## 10. 风险与回退

| 风险 | 触发 | 回退 |
|---|---|---|
| heuristic 切分质量差 | 用户的 CLAUDE.md 不按段写 | --dry-run 先看；用户可手编 .md 再 commit；不强制 |
| 同 slug 已存在 | 重复 import | 默认跳过；--force 覆盖 |
| auto-memory MEMORY.md 误解析 | 跳过逻辑没 catch | 显式 filename check + 测试覆盖 |
| memory-searcher 输出 > 500 token | LLM 不守约 | 测试时检查 model card 不超；CC client 端可 truncate；不在 v1 强制 enforce |
| sub-agent 模板路径冲突 | 已存在同名 | 默认拒；--force 覆盖；--target 项目级 |
| mcp-memory-service JSON schema 不一致 | 旧版导出 | defensive load + skip invalid entries + 报告 |

## 11. 完成判据

1. ✅ pytest 全绿（286 + ~25 ≈ 311 passed）
2. ✅ `memoryd import claude-md` 在 sample .md 上切出 ≥ 3 个不同 type 的条目
3. ✅ `memoryd import auto-memory` 跳过 MEMORY.md；其余条目都 import；type map 正确
4. ✅ `memoryd import agents-md` 工作（heuristic 同 claude-md）
5. ✅ `memoryd import mcp-memory-service` 兼容 memories.json sample
6. ✅ `--dry-run` 输出 plan，不写文件
7. ✅ `--scope=<hash>` 覆盖默认 scope
8. ✅ Sensitive scope 检测：import 到 sensitive scope 时 .md 走加密路径（复用 Plan 4）
9. ✅ memory-searcher 模板 文件在 templates/ + install 子命令工作
10. ✅ Plan 1-7 测试无回归
11. ✅ MCP 工具数仍 8 / 12
12. ✅ README 加 Plan 8 章节；execution-log Phase 1：真机 import + memory-searcher install

## 12. 变更记录

| 日期 | 改了什么 | 为什么 |
|---|---|---|
| 2026-05-15 | 初版 | Plan 7 完成；上 import + sub-agent |
