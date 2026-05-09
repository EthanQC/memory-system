---
title: OpenClaw 及强 agent 记忆机制研究报告
research_date: 2026-04-19
research_type: 第1路深度调研
topics: [OpenClaw, Manus, Devin, OpenHands, Cursor, Cline, Memory Bank]
status: 完整
---

# 研究报告：无向量库承载大量记忆的 agent 架构

## 1. OpenClaw 考证结果

**OpenClaw 是真实存在的项目**。关键事实：

- **前身叫 ClawdBot**，定位是"多通道个人 AI 助手框架"（支持 WhatsApp/Telegram/Discord/飞书/企微/钉钉/iMessage），接入 Claude/GPT/DeepSeek/Ollama
- **核心定位**："给 Claude Code 加上灵魂、记忆、技能、主动心跳"的 harness 层——不是独立模型，而是**包在 Claude Code 外面的 workspace 约定 + hook 系统**
- **记忆机制确实不依赖向量库作为主力**，而是用**分层 markdown + sessionKey 会话域 + 队列串行 + 按需工具化检索 + 主动心跳**这五件套
- 核查到的核心参考实现：
  - `voocel/openclaw-mini`（极简版源码可读）
  - `TechNickAI/openclaw-config`（原作者配置层）
  - `win4r/openclaw-workspace`（workspace 维护 Skill）
  - `yoloshii/ClawMem`（记忆增强）

**用户"没用本地向量库但承载大量记忆"判断精准**。OpenClaw mini 当前版本是纯关键词+tag 权重检索；完整版才有 SQLite-vec 可选（70:30 混合向量+BM25 权重），但核心承载靠分层 markdown。

## 2. 强 agent 记忆机制横评

| 系统 | 向量库 | 分层策略 | 自动固化触发 | 特色 |
|---|---|---|---|---|
| **OpenClaw** | 可选（SQLite-vec，非必需） | MEMORY.md（常驻,~100行）+ YYYY-MM-DD.md（昨日/今日）+ memory/people·projects·topics·decisions（按需） | cortex 技能后台摄取；四准则过滤（Durability/Uniqueness/Retrievability/Authority） | **文件角色分工+可见性隔离**（MEMORY.md 禁止进 sub-agent） |
| **Manus** | 有（云端 RAG） | 三文件模式：task_plan.md + notes.md + todo.md + 外部文件归档 | 每个 step 完成后更新 todo.md `[x]`；长文本强制写文件不生成长串输出 | **文件系统=外部记忆**，event stream 只留最近 N 条 |
| **Devin** | 有（codebase 向量快照） | workspace 下有"replay timeline"（每个命令/diff/浏览器 tab） | 长任务自动维护 todo list | 闭源；向量+完整事件回放 |
| **OpenHands** | 微 agent 关键词触发为主 | Memory（微 agent 知识）+ ConversationMemory（事件→LLM 消息） | Context Condenser（线性而非平方增长） | RecallAction/RecallObservation 事件对 |
| **Cline Memory Bank** | **无** | 6 个 markdown：projectbrief/productContext/activeContext/systemPatterns/techContext/progress | 用户说 "update memory bank" / 发现新模式 / 重大变更后；每次 task 开始**全文读** | 靠自定义指令强约束"必读全部" |
| **Cursor Rules** | 无（rules）/有（indexed codebase） | `.cursor/rules/*.mdc`，四种类型：Always/Auto Attached（glob）/Agent Requested（description 触发）/Manual | 不自动固化（rules 是静态的，memories 是另一套 beta） | **frontmatter 元数据驱动按需加载**是精髓 |
| **SWE-agent (ACI)** | 无 | 不存持久记忆；靠 ACI 命令（find_file/search_file/search_dir）做"实时文件系统即记忆" | N/A | 把文件系统本身当长期存储，linter 做输入校验 |
| **Claude Code 原生** | 无 | CLAUDE.md（项目级常驻）+ ~/.claude/CLAUDE.md（用户级）+ Skills（按需）+ Plan mode | 用户显式 `#` 添加；/compact 压缩 | **渐进式披露**：Skill 只有 SKILL.md frontmatter 常驻，正文按需加载 |

## 3. "无向量库承载大量记忆"共性模式（5 条可复用设计）

**① 三层可见性分层（Tier 1/2/3）**

- Tier 1 常驻：MEMORY.md 硬上限 ~100 行（OpenClaw）或 CLAUDE.md（≤200 行经验值）。字符硬上限 20k（openclaw-workspace 明确写了），超出就拆到 `docs/` 按需加载
- Tier 2 当日：`memory/YYYY-MM-DD.md` 只加载今天+昨天
- Tier 3 按需：`memory/{people,projects,topics,decisions}/` 每个实体一个文件，由 LLM 路由检索或 grep 命中才读

**② frontmatter 元数据 + 关键词路由**（Cursor/Claude Skills/OpenClaw Skills 共通）

```yaml
---
triggers: ["客户反馈", "投诉"]
globs: ["marketing/**/*.md"]
description: "处理客户反馈时加载"
alwaysApply: false
---
```

主上下文只放 frontmatter（几十字），正文等触发才注入——**这是"大量记忆小上下文"的核心技巧**。

**③ Hook 驱动的阶段性固化**（ClawMem 最完整）

- `UserPromptSubmit` → 检索相关记忆注入 `<vault-context>`
- `PreCompact` → 压缩前抢救关键决策到 observations/
- `Stop` → 提取决策、生成会话 handoff、更新引用计数
- `SessionStart` → 注入上一次 handoff、浮现维护建议

这些 hooks 由 harness 执行，不消耗主 agent 的决策 token。

**④ 文件系统=外部工作记忆（Manus/SWE-agent 模式）**

task_plan.md / notes.md / todo.md 三件套；agent 每步先读再更新 checkbox，长输出强制写文件不生成到主流。这把"工作记忆"从 context 里踢出去。

**⑤ 分层裁剪三级（OpenClaw Pruning/OpenHands Condenser）**

- L1 删 tool_result 旧行
- L2 assistant 消息压缩为"历史摘要"
- L3 保留最近 N 条完整消息

超阈值自适应分块 → 逐块 LLM 摘要 → 替换原文。线性而非平方增长。

## 4. 对用户场景的启示

**最值得借鉴的 4 条**（筑真营销负责人 / 飞书 + CC + Obsidian / 不想占主上下文）：

1. **采用 OpenClaw 的 Tier 分层 + openclaw-workspace 的硬上限**
   - `MEMORY.md` 只放"铁律型事实"（沃林 4万客单/3500 客资定价、乙方合伙人模式、不接受笼统建议等），<100 行、<10k 字符
   - 其余全部拆到 `memory/people|projects|decisions|topics/` 按需
   - Obsidian 天然支持这套目录+双链，完美契合

2. **用 frontmatter 做关键词路由，grep/ripgrep 做检索**
   - 每个记忆文件顶部写 `triggers / domain / updated_at`，主上下文只装载索引（几百字封顶），LLM 用 Grep 工具按需拉正文
   - 无需本地向量库。规模到一两千文件都跑得动

3. **写一个"阶段性固化" hook**（关键）
   - 参考 ClawMem 的 `Stop` hook：会话结束时自动跑一个子 agent，按四准则（Durability/Uniqueness/Retrievability/Authority）过滤本次对话，把值得留的决策写入 `memory/decisions/YYYY-MM-DD-<topic>.md`，并更新 `MEMORY.md` 的铁律段（如有）
   - 用户不用手动 `#`。这对"战略深度讨论"场景尤其重要——讨论结论自动沉淀

4. **飞书/客户对话走 Manus 三文件模式**
   - 营销项目类任务（比如"给沃林做 Q2 策划"）开一个工作目录：`task_plan.md` + `notes.md` + `todo.md`
   - Claude Code 每步先读再改，长产出写文件。既防遗忘，Obsidian 侧也能直接看进度
   - 这个模式 `.claude/skills/持久规划-planning-with-files` 已经装了，建议作为默认习惯

**不推荐**：给个人场景上 SQLite-vec / 云向量库。规模未到 10k 文件、需要透明可编辑、要进 Git，纯 markdown+grep 就够——这是 Manus/OpenClaw/Claude Code 三家在不同量级上收敛到的共识。

## 5. 关键链接清单（读过的高价值源）

1. https://github.com/voocel/openclaw-mini — OpenClaw 核心架构极简复现，**源码级可读**，最有价值
2. https://github.com/TechNickAI/openclaw-config — OpenClaw 原配置层，Tier 分层来源
3. https://github.com/win4r/openclaw-workspace — 文件字符上限、可见性隔离规则
4. https://github.com/yoloshii/ClawMem — hooks + MCP + 混合 RAG，hook 时机表最全
5. https://github.com/zilliztech/memsearch — Markdown-first 记忆库，受 OpenClaw 启发
6. https://dev.to/imaginex/ai-agent-memory-management-when-markdown-files-are-all-you-need-5ekk — "为什么 markdown 够用"论证最完整
7. https://gist.github.com/renschni/4fbc70b31bad8dd57f3370239dccd58f — Manus 深度技术分析
8. https://e2b.dev/blog/how-manus-uses-e2b-to-provide-agents-with-virtual-computers — Manus + E2B 官方博客
9. https://docs.cline.bot/features/memory-bank — Cline 官方 memory bank 文档
10. https://cline.bot/blog/memory-bank-how-to-make-cline-an-ai-agent-that-never-forgets — Cline memory bank 设计理由
11. https://docs.cursor.com/context/rules — Cursor Rules 四种类型官方文档
12. https://openhands.dev/blog/openhands-context-condensensation-for-more-efficient-ai-agents — Context Condenser 线性增长证明
13. https://deepwiki.com/OpenHands/OpenHands/6.3-agent-configuration — OpenHands Memory + ConversationMemory 分解
14. https://arxiv.org/abs/2405.15793 — SWE-agent ACI 论文
15. https://arxiv.org/html/2505.02024v1 — Manus 架构学术综述
16. https://cognition.ai/blog/introducing-devin — Devin 官方首发
17. https://developer.aliyun.com/article/1714570 — OpenClaw + Claude-Mem 中文实操
18. https://github.com/KimYx0207/Claude-Code-x-OpenClaw-Guide-Zh — OpenClaw 中文教程合集
19. https://github.com/thedotmack/claude-mem — claude-mem 插件，Claude Code 原生压缩方案
20. https://www.zenml.io/llmops-database/building-an-ai-agent-platform-with-cloud-based-virtual-machines-and-extended-context — Manus 平台架构 ZenML 梳理

## 读不透的点（诚实标注）

- `yeasy/openclaw_guide` 的 Chapter 6 "context_memory" 正文没拿到（只拿到目录）；建议直接访问 `yeasy.gitbook.io/openclaw_guide/`
- Manus 的 cursor rules 完整清单、Devin 的内存 schema 都是闭源，只有逆向推测
- Claude-Mem 的语义压缩算法没公开，官方只说"30% 体积"
- OpenClaw "224K stars" 数字来自中文营销文案，非 GitHub 官方数据，未核验
