---
title: Firia 个人记忆系统设计文档集
created_at: 2026-04-19
owner: firia
status: 决策对齐阶段（未实施）
---

# Firia 个人记忆系统设计

## 目的

为 Firia（筑真营销负责人）设计一套个人 AI 记忆系统，让 Claude Code 能跨 session 无损保留决策/背景/飞书工作流，主上下文零侵占，后期可平移至团队。

## 文档导航

1. [01-openclaw-强agent记忆机制.md](./01-openclaw-强agent记忆机制.md) — OpenClaw/Manus/Devin/Cline 等强 agent 的记忆机制横评与 5 条共性设计模式
2. [02-开源记忆系统横评.md](./02-开源记忆系统横评.md) — Mem0/Letta/Zep/Cognee/Basic Memory/A-MEM/LangMem/Memary/MemoryOS 九方案对比
3. [03-claude-code原生记忆机制.md](./03-claude-code原生记忆机制.md) — CLAUDE.md/MEMORY.md/Hooks/Compaction/Sub-agent/MCP/Skill 全景
4. [04-飞书obsidian集成调研.md](./04-飞书obsidian集成调研.md) — 飞书接入方案（含团队 `feishu-user-plugin` 发现）+ Obsidian MCP 生态
5. [05-方案B深度设计.md](./05-方案B深度设计.md) — **决策辅助文档**，完整架构/token 预算/实施路线

## 核心结论

- **纯 Markdown + frontmatter + grep 足够承载个人记忆量级**（不上向量库）
- **方案 B（Basic Memory 主力）是推荐起点**（Obsidian 原生，团队化友好）
- **OpenClaw 的 Tier 分层**和**Claude Code 原生 hooks**共同构成架构骨架
- **团队已有的 `feishu-user-plugin`** 是飞书接入的现成答案，不用外部工具

## 5 条跨方案共识（决策锚点）

1. 纯 Markdown + frontmatter + grep 足够
2. 不引入本地向量库
3. 三层可见性强制分层（常驻/当日/按需）
4. "阶段性自动固化"= Hook 驱动（SessionEnd/PostCompact/SubagentStop）
5. 记忆检索用 Sub-agent，主会话零侵占

## 下一步

见 `05-方案B深度设计.md` §12 决策问题清单。
