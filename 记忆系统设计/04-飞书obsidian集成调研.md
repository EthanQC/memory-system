---
title: 飞书 × Obsidian 记忆系统集成调研
research_date: 2026-04-19
research_type: 第4路深度调研
topics: [lark-cli, feishu-docx, Obsidian MCP, feishu-user-plugin]
status: 完整（含后补团队 plugin 发现）
---

# 飞书 × Obsidian 记忆系统集成调研

## ⚠️ 重要补充（2026-04-19 发现）

调研完成后发现团队已在 `team-skills/plugins/feishu-user-plugin/` 维护了一个**远比外部 lark-cli 成熟的飞书 MCP server**：

- **76 个工具**覆盖消息发送、群聊/单聊读取、文档、Bitable、Wiki、Drive、日历、任务、文件上传
- **三层鉴权**：User Identity (cookie) / Official API (app credentials) / User OAuth UAT
- **自动化 cookie 设置**（通过 Playwright），自动心跳续期（每 4 小时）
- **原生 Claude Code MCP**，不是 CLI
- **9 个内置 Skills**（send/reply/digest/search/doc/table/wiki/drive/status）
- 自我定位："Replaces and extends the official Feishu MCP"
- 文档提及 OpenClaw 集成（`prompts/openclaw-setup.md`）

**结论**：飞书侧**不用 yjwong/lark-cli**，直接复用团队的 `feishu-user-plugin`。以下外部调研内容作为备选参考。

---

## 1. 飞书接入能力表（外部工具调研）

| 能力维度 | 推荐实现 | 成熟度 | 权限 / 限速 |
|---|---|---|---|
| **群/单聊历史消息** | `GET /open-apis/im/v1/messages`（page_token + start_time/end_time） | 高 | `im:message.history:readonly` + `im:message.group_msg`。**50 QPS / 1000 RPM** |
| **消息增量监听** | 事件订阅 `im.message.receive_v1`（webhook 或长连接） | 高 | 机器人需加入群 |
| **单文档 → Markdown** | `larksuite/cli`、`leemysw/feishu-docx`、`Wsine/feishu2md` | 高（表格/图片保真） | `docx:document:readonly` / OAuth user token |
| **Wiki 整站 → Markdown** | `longbridge/feishu-pages`、`feishu-docx export-wiki-space` | 高 | wiki:wiki:readonly |
| **多维表格 Bitable** | `feishu-docx`、官方 MCP、官方 CLI | 高 | `bitable:app:readonly` |
| **妙记文本纪要** | `yjwong/lark-cli minutes`、`bingsanyu/feishu_minutes`（视频下载要 cookie） | 中 | `minutes:minutes:readonly` |
| **文档变更 webhook** | `drive.file.edit_v1`、`comment.created`，无细粒度 diff | 中 | 需订阅对应事件 |
| **云盘文件上传下载** | 官方 CLI drive；官方 MCP **不支持上传下载** | 中 | drive 权限 |

关键：**官方 lark-openapi-mcp v0.5.1（2025-08）只读不可写云文档**。

## 2. 外部飞书工具对比（备选参考）

### A. AI-first 栈（若不用团队 plugin 时）

核心工具：**`yjwong/lark-cli`**（v0.12.0，2026-03-02）
- 专为 Claude Code 设计，返回紧凑 JSON
- 内置 `skills/` 目录（calendar/contacts/documents/messages/mail/minutes 六个 Skill）
- 消息历史：`--start-time --end-time` + 增量逻辑

### B. 完整知识库导出栈

- **`leemysw/feishu-docx`**（v0.2.5，2026-04-11，最新）— CLI + TUI，`export-wiki-space` 递归，支持 OAuth，**自带 Claude Skill 写回能力**
- **`longbridge/feishu-pages`**（v0.7.4，2024-10）— GitHub Actions 定时跑，适配 Docusaurus/VitePress

## 3. Obsidian MCP 现状

### 推荐组合（优先级）

1. **`coddingtonbear/obsidian-local-rest-api`**（v3.6.1，2026-04-09）+ **`MarkusPfundstein/mcp-obsidian`** MCP 封装
   - 完整 CRUD、全文搜索、**Dataview DQL 查询**、JsonLogic、frontmatter 局部编辑、触发 Obsidian 命令
   - HTTPS + API key 鉴权，默认 27124 端口
   - MCP 提供 7 个工具：list/get/search/append/patch/delete

2. **`iansinnott/obsidian-claude-code-mcp`**（v1.1.8，2025-06）— 插件一体化，默认 22360 端口
   - 优点：无需装额外 REST API 插件
   - 缺点：**无访问鉴权**

**安全建议**：装 Local REST API + mcp-obsidian，有 API key 更安全。

## 4. 完整 pipeline 方案图

```
┌──────────────────────────────────────────────────────┐
│ 飞书（源）                                           │
│ • 群聊/单聊    • 云文档/Wiki    • 妙记    • Bitable  │
└──────────────┬───────────────────────────────────────┘
               │ [推荐: feishu-user-plugin MCP（团队维护）]
               │ [备选: 事件订阅长连接 + 定时轮询]
               ▼
┌──────────────────────────────────────────────────────┐
│ 同步层（本地 cron / systemd timer）                  │
│ • read_messages / read_p2p_messages（增量）          │
│ • search_wiki / read_doc                             │
│ • /digest 筛选有价值内容                             │
│ • 记录 last_sync_timestamp.json（幂等 + 去重）       │
└──────────────┬───────────────────────────────────────┘
               │ [写入 Markdown + YAML frontmatter]
               ▼
┌──────────────────────────────────────────────────────┐
│ Obsidian Vault（本地记忆载体）                       │
│ • /inbox/messages/YYYY-MM-DD.md                      │
│ • /wiki/<space>/<slug>.md                            │
│ • /minutes/<meeting-id>.md                           │
│ • frontmatter: source, feishu_id, synced_at, tags    │
│ • [[wiki-link]] 交叉引用                             │
└──────────────┬───────────────────────────────────────┘
               │ [Local REST API :27124, HTTPS + API key]
               ▼
┌──────────────────────────────────────────────────────┐
│ Claude Code（消费）                                  │
│ MCP clients:                                         │
│ • basic-memory（读写 Markdown + 索引）               │
│ • mcp-obsidian（Dataview 查询）                      │
│ • feishu-user-plugin（实时补查未同步数据）           │
└──────────────────────────────────────────────────────┘
```

## 5. 踩坑预警

1. **权限审批**：`im:message.history:readonly` + `im:message.group_msg` 企业版需管理员审批 1-3 工作日；**自建应用**只能读机器人所在群
2. **Rate limit**：默认 tier 1000/min 50/sec 不能自助升级
3. **妙记 transcript**：官方 API 只能拿元数据 + 文本，视频/SRT 下载需要 cookie（SSO 过期）
4. **文档格式丢失**：飞书画板导出到 Markdown 会变空白图片；复杂嵌入块（日程/投票）会降级
5. **官方 MCP 限制**：`larksuite/lark-openapi-mcp` **不支持文件上传下载、不支持直接编辑云文档**
6. **Obsidian 端**：`iansinnott/obsidian-claude-code-mcp` 无鉴权，公网极危险；Local REST API 用自签证书需 `-k`
7. **去重**：飞书 `message_id` 稳定；Wiki `node_token` 稳定；docx 被复制 `document_id` 会变
8. **官方 CLI 很新**：`larksuite/cli` v1.0.0 文档偏薄，生产用建议跟 `feishu-user-plugin`（团队维护）或 `yjwong/lark-cli`

## 6. 关键链接

### 团队内部（优先）
- `team-skills/plugins/feishu-user-plugin/` — 团队维护的 76 工具 MCP server

### 飞书外部备选
- [larksuite/lark-openapi-mcp](https://github.com/larksuite/lark-openapi-mcp) — 官方 MCP v0.5.1
- [larksuite/cli](https://github.com/larksuite/cli) — 官方 CLI v1.0.0
- [yjwong/lark-cli](https://github.com/yjwong/lark-cli) — AI-first CLI，内置 Skills
- [leemysw/feishu-docx](https://github.com/leemysw/feishu-docx) — Wiki 整站导出 + 写回
- [Wsine/feishu2md](https://github.com/Wsine/feishu2md) — Go 写的轻量转换器
- [longbridge/feishu-pages](https://github.com/longbridge/feishu-pages) — GitHub Actions 增量导出
- [bingsanyu/feishu_minutes](https://github.com/bingsanyu/feishu_minutes) — 妙记视频+SRT下载
- [Feishu Get chat history API](https://open.feishu.cn/document/server-docs/im-v1/message/list)
- [Feishu Rate limits](https://open.feishu.cn/document/server-docs/api-call-guide/frequency-control)

### Obsidian
- [coddingtonbear/obsidian-local-rest-api](https://github.com/coddingtonbear/obsidian-local-rest-api) — v3.6.1
- [MarkusPfundstein/mcp-obsidian](https://github.com/MarkusPfundstein/mcp-obsidian) — 推荐 MCP 封装
- [iansinnott/obsidian-claude-code-mcp](https://github.com/iansinnott/obsidian-claude-code-mcp) — 原生插件
- [hancengiz/cc-obsidian-vault-api-skill](https://github.com/hancengiz/cc-obsidian-vault-api-skill) — Claude Code Skill 封装参考

## 7. 核心建议

**直接用团队的 `feishu-user-plugin` MCP**。一周内可跑通；增量同步用 cron 每 15 分钟跑一次 `/digest` skill 写进 vault 的 `/inbox/` 目录，frontmatter 存 `feishu_msg_id` 做幂等。后续有 Wiki 归档需求再加 `search_wiki` + `read_doc` 批量导出脚本。**不要一开始就追求实时 webhook**，轮询模式故障恢复更简单。
