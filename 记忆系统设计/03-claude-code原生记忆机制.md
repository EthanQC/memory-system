---
title: Claude Code 原生记忆能力全景
research_date: 2026-04-19
research_type: 第3路深度调研
topics: [CLAUDE.md, MEMORY.md, Hooks, Compaction, Sub-agent, MCP, Skill]
status: 完整
---

# Claude Code 原生记忆能力全景

基于官方文档和源码详查。

## 1. CC 原生记忆能力地图

| 机制 | 作用 | 触发点 | Token 成本 | 自动化水平 |
|------|------|--------|-----------|----------|
| **CLAUDE.md** | 持久化指令 | Session 启动 | 全量载入（每行计费） | 用户手写或 `/init` |
| **auto-memory (MEMORY.md)** | Claude 自学笔记 | 会话中自动写入 | 仅首 200 行或 25KB 载入 | 全自动（有触发决策） |
| **Hooks** | 事件驱动的脚本 | PreToolUse/PostToolUse/SessionEnd 等 | 预处理降低后续开销 | 脚本执行，自定义逻辑 |
| **Compaction** | 上下文压缩 | ~95% 上下文时触发 | 摘要 3-5K tokens | 自动或手动 `/compact` |
| **Sub-agent** | 隔离 context 执行 | Claude 自动或手动调度 | 完全隔离，仅返回摘要 | 自动（基于描述匹配） |
| **Skill** | 按需加载指令 | 用户调用或 Claude 自动 | 描述始终在 context，完整内容按需 | 可配置 |
| **MCP Server** | 外部工具集成 | Tool search 按需加载 | 工具定义延迟加载 | 按需加载 |

## 2. CLAUDE.md 与 auto-memory 的加载机制

### CLAUDE.md 优先级与递归搜索

从 CWD 向上递归搜索（无深度限制）：

1. **企业级**（最高优先级）
   - macOS: `/Library/Application Support/ClaudeCode/CLAUDE.md`
   - Linux: `/etc/claude-code/CLAUDE.md`
2. **项目级** → `./CLAUDE.md` 或 `./.claude/CLAUDE.md`
3. **用户级** → `~/.claude/CLAUDE.md`
4. **本地个人** → `./CLAUDE.local.md`（追加在项目级后）
5. **子目录** → `.claude/rules/` 文件按需加载

**合并策略**：所有发现的文件级联连接（不是覆盖）。
**Token 成本**：每个 CLAUDE.md 全量载入。官方建议 <200 行。

### auto-memory (MEMORY.md) 真实机制

**官方机制**（v2.1.59+）：

- **存储位置**：`~/.claude/projects/<project>/memory/MEMORY.md`（由 git repo 或 project root 自动派生）
- **加载规则**：仅首 **200 行或 25KB**，取决于哪个先达到
- **topic 文件**：`debugging.md` 等详细文件**不在 session 启动时加载**，Claude 按需用 Read 工具召回
- **自动写入**：Claude 在会话中判断值得记忆的内容，自动写入相应 topic 文件

## 3. Hooks 全清单与记忆相关触发点

| Hook 名 | 触发时机 | Payload 包含 | 适合记忆固化? |
|---------|---------|------------|-----------|
| **SessionEnd** | 会话终止 | transcript_path, session_id | ✅ 强（阶段性总结） |
| **SubagentStop** | 子代理完成 | last_assistant_message | ✅ 强（捕获子任务结果） |
| **PostCompact** | compaction 后 | （无特殊数据） | ⚠️ 可（log compaction event） |
| **UserPromptSubmit** | 用户输入前 | 可注入 additionalContext | ✅ 可（历史检索） |
| **PreCompact** | compaction 前 | 可阻止 compact | ⚠️ 可（条件性保护） |
| **Stop** | 每轮回应结束 | last_assistant_message | ⚠️ 频繁（性能开销） |

**Hook 里能否调用 LLM?** 不能直接。hook 脚本是同步 bash/http 命令，**不能直接调用 LLM**。但可以：
- 用 Claude API 调用（通过 subprocess + API key）
- 用 sub-agent 模式处理（hook 的输出可注入 additionalContext）

## 4. Compaction / Context 管理

### 触发与算法
- **触发点**：~95% context 或手动 `/compact`
- **摘要算法**：使用同一模型；摘要包含：主要请求/关键技术概念/已修改文件/错误与修复/当前状态与下一步
- **可自定义**：CLAUDE.md 添加 `# Compact instructions` 段

### 压缩后存活规则
- ✅ Compaction block（摘要本身，3-5K tokens）
- ✅ 摘要**之后**的所有消息
- ✅ 项目根 CLAUDE.md（session 后重新注入）
- ❌ 子目录 CLAUDE.md（未自动重新加载）
- ❌ 摘要**之前**的所有消息

### 落盘位置
- Session JSONL: `~/.claude/projects/<project>/sessions/<session-id>.jsonl`

## 5. Sub-agent 隔离机制

每个 sub-agent：
- 独立 context window（无主会话历史）
- 仅输入通道：Agent tool 的 prompt 字符串
- 仅输出通道：最终总结返回主会话

**零主 token 侵占方案**：
1. 定义 sub-agent（`.claude/agents/memory-retriever.md`）
2. Tool 限制：Read-only + MCP memory server
3. 系统提示：如何解析 MEMORY.md 和 topic 文件，返回精准摘要

## 6. MCP Memory Server 现状

- 官方文档未明确说"官方 memory server"，但提到 "server-memory" 概念
- 社区流行：@modelcontextprotocol/server-memory、mcp-memory-service、Basic Memory MCP

**MCP 返回的数据也进主 context**（通过 tool result），但可用 tool search 延迟加载，减少初始开销。

## 7. Skill 按需加载

- Skill **描述**总在 context（1% 窗口预算，default ~8K char）
- Skill **完整内容**仅在调用时加载
- Skill 不能定义 hooks（hook 在 settings.json）
- Skill 调用后内容留在主 context（贡献摘要预算）
- **比 sub-agent 方案差**：Skill 的输出仍膨胀主 context

## 8. 官方 vs 自定义的边界

### 官方已自带
- ✅ CLAUDE.md（多层级加载、import 支持）
- ✅ auto-memory（自动决策、MEMORY.md 管理）
- ✅ Compaction（自动触发、可自定义指令）
- ✅ Sub-agent（隔离、自动调度、custom 系统提示）
- ✅ Hooks（26 个事件）
- ✅ Skill（按需加载、fork 模式）
- ✅ MCP

### 必须自建或外部引入
- ❌ LLM-驱动的摘要决策 → 需自己在 hook 里调 Claude API
- ❌ 实时语义检索 → 需配置向量 DB + MCP
- ❌ 跨 repo 记忆共享 → 需中央存储
- ❌ 知识图谱 / 联想记忆 → 需 mcp-memory-service 或自建

## 9. "阶段性自动固化"的 3 种官方路径

### 路径 1: SessionEnd Hook + Bash 脚本（简单场景）

```json
// .claude/settings.json
{
  "hooks": {
    "SessionEnd": [{
      "matcher": "*",
      "hooks": [{
        "type": "command",
        "command": "~/.claude/hooks/session-summary.sh"
      }]
    }]
  }
}
```

优点：简洁，完全自主
缺点：无 LLM 智能（需手写摘要逻辑）

### 路径 2: SubagentStop Hook + Claude API 调用（推荐）

```bash
# ~/.claude/hooks/capture-subagent.sh
INPUT=$(cat)
LAST_MSG=$(echo "$INPUT" | jq -r '.last_assistant_message')
curl https://api.anthropic.com/v1/messages \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -d "{...}" | jq -r '.content[0].text' >> ~/.claude/projects/memory/MEMORY.md
```

优点：LLM 驱动摘要质量高
缺点：Hook 执行成本；错误处理复杂

### 路径 3: Pre-Compact Hook + 自定义压缩指令

在 CLAUDE.md 添加：
```markdown
## Compact instructions
当进行 compact 时，重点保留：
- 已修改的代码文件和原因
- 遇到的错误及解决方案
- 当前待办项目
```

优点：Compact 本身是官方高效机制
缺点：仅在 compaction 触发时

## 10. "零主上下文侵占"方案评分

| 方案 | Token 侵占 | 延迟 | 精度 | 实现难度 |
|------|-----------|------|------|--------|
| Sub-agent (Read MEMORY.md) | 1K（摘要） | ~1s | ⭐⭐⭐⭐ | ⭐⭐ |
| MCP + Sub-agent | 500B（列表） | ~1s | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ |
| Skill (context: fork) | 同 Sub-agent | ~1s | ⭐⭐⭐ | ⭐⭐ |
| Direct MEMORY.md 加载 | 25KB | 0s | ⭐⭐⭐⭐ | ⭐ |
| Hook 摘要缓存 | 变量 | 0s | ⭐⭐⭐ | ⭐⭐⭐⭐ |

**推荐最优路线**：Sub-agent + MCP Memory Server

## 11. 核心结论

**用户硬约束能满足**：
- ✅ 不占用主上下文 token：via Sub-agent 或 Skill (context: fork)
- ✅ 阶段性自动固化：via SessionEnd/SubagentStop/PostCompact hooks

**推荐架构**：
```
CLAUDE.md (规则)
  ↓
auto-memory/MEMORY.md (自学笔记，首 200 行)
  ↓
PostCompact/SessionEnd Hook (日志 + 增量备份)
  ↓
Memory-Searcher Sub-agent (按需高精度召回)
  ↓
主会话 (零 token 侵占)
```

## 12. 关键官方文档链接

1. [Memory: How Claude remembers your project](https://code.claude.com/docs/en/memory)
2. [Hooks reference](https://code.claude.com/docs/en/hooks)
3. [How Claude Code works](https://code.claude.com/docs/en/how-claude-code-works)
4. [Create custom subagents](https://code.claude.com/docs/en/sub-agents)
5. [Extend with skills](https://code.claude.com/docs/en/skills)
6. [Manage costs effectively](https://code.claude.com/docs/en/costs)
7. [Connect via MCP](https://code.claude.com/docs/en/mcp)
8. [Compaction](https://platform.claude.com/docs/en/build-with-claude/compaction)
9. [Claude Code context window visualization](https://code.claude.com/docs/en/context-window)
10. [Claude Code GitHub Issues](https://github.com/anthropics/claude-code/issues)
