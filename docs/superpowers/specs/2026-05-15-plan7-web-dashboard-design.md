---
title: 浏览界面（Plan 7）设计
date: 2026-05-15
status: 已批准（light brainstorming：127.0.0.1:<random> + token URL / Web 先 TUI 后 / 本 plan 顺手做 schema 对齐）
related:
  - docs/superpowers/specs/2026-05-09-personal-usage-and-boundary-spec.md
  - docs/superpowers/specs/2026-05-14-long-term-memory-governance-design.md
  - docs/superpowers/specs/2026-05-14-sensitive-scopes-design.md
  - docs/superpowers/specs/2026-05-15-plan6-multi-device-sync-design.md
role: 设计文档——Plan 7 实施 plan 与 SDD 都引用本文档
---

# Plan 7：浏览界面 设计

## 0. 这份文档是什么

spec §4.3 #11 / §4.8 #30-#32：v1 需要 CLI（已有）+ TUI（交互式 digest 审核）+ 轻量 Web Dashboard（本机 127.0.0.1，浏览-only）+ Markdown schema 主动对齐 Basic Memory。Plan 7 落地这三件。

Plan 7 不改 spec；不改 Plan 1-6 既有功能；新增 web 模块 + tui 模块 + frontmatter 字段（向后兼容）。

## 1. 上游与硬约束

| 已交付 | 状态 |
|---|---|
| Plan 6 sync + passphrase | merged `de97325` |
| Plan 5 跨平台 + install-cron + auto-install | merged `79b533c` |
| Plan 4 敏感作用域 + audit log | merged `8ce76aa` |
| Plan 3 SQLite index + 6 类型 + promotions table | merged `4dac127` |

| 硬约束 | 来源 |
|---|---|
| MCP 工具数 ≤ 12（当前 8） | spec §3。本 plan **不加新 MCP 工具** |
| Web 仅浏览，不可编辑 | spec §6 |
| 全本地——不联网 | spec §3 |
| 不接管三端原生记忆机制 | spec §6 |
| 默认静默——Web 不开则不开 | spec §3 |

## 2. 总体架构

```
┌───────────────────────────────────────────────────────────────┐
│ CLI: memoryd web                                              │
│   → 启动 uvicorn 跑 FastAPI app                                │
│   → 随机选 127.0.0.1:<port>                                    │
│   → 生成 256-bit secret token                                  │
│   → stderr 打印 `http://127.0.0.1:<port>/?token=<token>`       │
│   → 用户复制 URL 到浏览器；token 不复制无法访问                 │
└───────────────────────────────────────────────────────────────┘
                              ↓
┌───────────────────────────────────────────────────────────────┐
│ FastAPI app                                                   │
│   middleware: token check（query string ?token= 或 cookie 或    │
│              Authorization: Bearer <token>）                  │
│   routes:                                                     │
│     GET /                  index.html（搜索框 + 最近 list）   │
│     GET /memories          list（filter type/scope）          │
│     GET /memories/{slug}   detail（含 frontmatter + body）    │
│     GET /search?q=&type=   search HTMX fragment               │
│     GET /audit             audit page（filter scope/since）   │
│     GET /digest            pending promotions（read-only）    │
│     GET /healthz           liveness                           │
│   templates: Jinja2，HTMX 交互；零 npm                         │
│   static: 单 .css（≤ 5KB）                                     │
└───────────────────────────────────────────────────────────────┘
                              ↓ 复用既有
┌───────────────────────────────────────────────────────────────┐
│ 数据层：复用 Plan 1-6                                          │
│   storage.list_memories / load_session / load_memory          │
│   search.search_sessions                                      │
│   governance.audit.read_audit_log                             │
│   governance.analyze.list_promotions                          │
└───────────────────────────────────────────────────────────────┘
                              ┊
┌───────────────────────────────────────────────────────────────┐
│ Sensitive scope 处理（v1）                                      │
│   Web 不显示 sensitive scope 内容；列表中显 🔒 占位 +          │
│   "use CLI memoryd grant <scope> + memoryd show <slug>"        │
│   detail page 直接 403                                         │
└───────────────────────────────────────────────────────────────┘
                              ┊
┌───────────────────────────────────────────────────────────────┐
│ TUI（Plan 7 后半）                                              │
│   memoryd digest --tui                                        │
│   textual app: 3 panes (promotions / merge candidates /       │
│                          decay reminders)                     │
│   keybinds: a=approve, r=reject, m=merge, s=skip, q=quit      │
│   approve/reject 改 promotions table status；merge 调          │
│   merge_duplicates                                            │
└───────────────────────────────────────────────────────────────┘
```

## 3. Web 安全模型（spec §3 数据观）

- **绑定**：`127.0.0.1:<random port>`，端口由 `socket.socket().bind(("127.0.0.1", 0))` 取 OS 派发。
- **Token**：256-bit `secrets.token_urlsafe(32)`；进程内存中，每次启动新生成；不持久化。
- **传递**：query string 或 cookie 或 Authorization header；middleware 三个都接受。
- **stderr URL**：启动后第一行 stderr 打印 `http://127.0.0.1:<port>/?token=<token>`；用户可见。
- **拒绝**：缺/错 token → 401 JSON `{"error": "unauthorized"}`；不重定向到登录页（无登录页）。
- **CORS**：默认拒绝。
- **HTTPS**：v1 不做（本机 loopback；v2 视需要加 `--cert` flag）。
- **CSRF**：无 cookie POST 操作（Web 仅 GET）；GET 自身无 CSRF。

## 4. Web 路由清单

| Path | Method | 用途 | Auth required |
|---|---|---|---|
| `/healthz` | GET | 探活；不返回数据 | No（便于探针）|
| `/` | GET | 主页（搜索框 + 最近 20 memory）| Yes |
| `/memories` | GET | list；`?type=&scope=&page=` | Yes |
| `/memories/{slug}` | GET | detail（frontmatter + body）；sensitive 403 | Yes |
| `/search` | GET | HTMX fragment；`?q=&type=`；返回 `<ul>` partial | Yes |
| `/audit` | GET | audit page；`?scope=&since=&event_type=` | Yes |
| `/digest` | GET | pending promotions list（read-only）| Yes |
| `/static/{file}` | GET | CSS / JS（HTMX 1.9 minified） | Yes |

不暴露 `POST` / `PUT` / `DELETE`——Web 浏览-only。

## 5. 模板与样式

`memoryd/src/memoryd/web/templates/`：
- `base.html` — 含 HTMX `<script>` from CDN（v1 内置 HTMX 1.9 minified 到 static/）；nav + search box
- `index.html` — 主页
- `list.html` — `/memories`
- `detail.html` — `/memories/{slug}`
- `search_fragment.html` — HTMX search result `<ul>`
- `audit.html` — `/audit`
- `digest.html` — `/digest`
- `error.html` — 401/403/500 通用页

`memoryd/src/memoryd/web/static/`：
- `base.css` — 单文件，≤ 5KB；mono font；简洁灰阶
- `htmx.min.js` — HTMX 1.9，本地引入避免 CDN 依赖

## 6. CLI 子命令

```
memoryd web                       # 启动；占 stdin（直到 Ctrl+C）
memoryd web --port=8088           # 显式端口（覆盖 random）
memoryd web --no-browser          # 不自动 open（默认会 open URL with token）
memoryd web --read-only           # 兼容现有 sensitive guard（其实没区别因 Web 不写）
```

启动序：
```
1. detect platform
2. bind 127.0.0.1:0 → 拿 port
3. gen token = secrets.token_urlsafe(32)
4. stderr: f"memoryd web on http://127.0.0.1:{port}/?token={token}"
5. if not --no-browser: webbrowser.open(url) [delay 0.5s]
6. uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
```

退出：Ctrl+C SIGINT 优雅停 uvicorn。

## 7. textual TUI（Plan 7 后半）

`memoryd/src/memoryd/tui/digest.py` — textual App 子类。

界面（参考 engram TUI）：

```
┌── memoryd digest ─────────────────────────────────────────────┐
│ ▼ 候选提升 (12)          ▼ 重复合并 (3)        ▼ TTL 到期 (5) │
│ ──────────────────       ─────────────         ──────────────  │
│ ▸ [decision] logo blue   ▸ logo-blue-04~       ▸ session 02-12 │
│   D=0.85 U=0.91 R=0.80     logo-blue-05          → dim (180d)  │
│   A=0.95 (haiku-4-5)       sim=0.92                            │
│ ▸ [preference] PR merge  ...                   ...             │
│ ...                                                            │
│                                                                │
│ [a]all-approve [r]eject [m]erge [s]kip [q]uit                 │
└────────────────────────────────────────────────────────────────┘
```

接 promotions / merge_duplicates / decay_state 既有数据层。`a` 全部 approve 之后真把 .md 文件按类型分发到对应目录 + SQLite index 同步。

### TUI vs Web 重叠避免

- Web `/digest` 仅显示 pending promotions（read-only）
- TUI `digest --tui` 是 approve / reject 主交互入口
- 现有 `memoryd digest`（无 flag）保持文本输出（适合 ssh 远程 / cron job）
- 加 `memoryd digest --tui` 进 textual；不加保留现状

## 8. Basic Memory schema 对齐（spec §4.8 #32）

读 Basic Memory 文档（开源仓 README）确认 v1 frontmatter 关键字段：
- `tags: list[str]`（≈ memoryd `triggers`）
- `category: str | None`（高层分类，可 None）
- `observations: list[str]`（小条目状的事实附加）
- `relations: list[str]`（关联其他 note slug）
- 其它（permalink, type）已有近似映射

`memoryd/src/memoryd/schema.py` `Frontmatter` Pydantic 加：

```python
class Frontmatter(BaseModel):
    # ...既有字段...
    tags: list[str] = Field(default_factory=list)            # NEW Plan 7；与 triggers 共存
    category: str | None = None                              # NEW Plan 7
    observations: list[str] = Field(default_factory=list)    # NEW Plan 7
    relations: list[str] = Field(default_factory=list)       # NEW Plan 7（覆盖既有 relations? 看现状）
```

注意：Plan 3 已有 `relations: list[str]`（关联 slug）；Plan 7 复用，不重复定义。

兼容性：四字段全部 optional + default empty；Plan 1-6 已存 .md 不需要 migration。

**不**改：`triggers` 字段保留为 memoryd 主路（4 准则的 R 维度依赖它）。`tags` 是 Basic Memory 兼容别名；新 .md 写入时同时写 triggers + tags（同值）；读取允许两者任一存在。

## 9. 不在 Plan 7 内（边界）

| 不做 | 推迟到 |
|---|---|
| Web 编辑（POST / PUT） | v2（spec §10 #7） |
| Web HTTPS | v2 |
| Obsidian Local REST API 双向 | v2 |
| Web 多用户 | 永不（spec §6） |
| TUI 浏览界面 | textual 内置 list + 搜索，仅 digest 实现 |
| MCP 工具数变更 | 不增不减 |

## 10. 风险与回退

| 风险 | 触发 | 回退 |
|---|---|---|
| FastAPI/uvicorn 新依赖大 | pip install 慢 | 都是稳定包；Pin minimum versions；用户已在 jinja2 安装链上 |
| HTMX CDN 依赖 | 用户离线 | static/htmx.min.js 内置；不走 CDN |
| Port 已占 | bind 失败 | 重试 5 次；失败提示用户 --port 显式指定 |
| Token 泄漏（屏幕被截图等） | 同机攻击 | 重启换 token；建议用户 `memoryd web` 后台跑前 lock screen |
| sensitive scope 误显 | Web 没认到 .memoryd-sensitive marker | Detail 默认 403；list 显 🔒 占位；audit 任何 sensitive 访问都进日志（既有 gate 行为） |
| textual import 失败（Win 终端兼容） | 用户 Win Console 老版 | 提示用 Windows Terminal；fallback `memoryd digest`（文本版） |
| schema migration 误判 Plan 1-6 .md | 新字段 required | 都 default empty/None，向后兼容 |

## 11. 完成判据

1. ✅ pytest 全绿（250 + ~40 ≈ 290 passed）
2. ✅ `memoryd web` 在 macOS 真机启动 → stderr 出 URL → curl GET / with token=200，without=401
3. ✅ Sensitive scope: list 显 🔒，detail 403
4. ✅ /search?q=<term> 返回 HTMX fragment，含 memoryd 现有 search 命中
5. ✅ /audit 渲染 audit.jsonl 最近 50 行
6. ✅ /digest 渲染 promotions(status=pending) 列表
7. ✅ textual `memoryd digest --tui` 启动；键盘 a/r/m/s/q 都响应；approve 真改 promotions
8. ✅ Frontmatter 加 tags / category / observations；Plan 1-6 已存 .md load 不破
9. ✅ MCP 工具数仍 8 / 12（不增）
10. ✅ README 加 Web Dashboard + TUI 章节
11. ✅ execution-log Phase 1 用户手册：本机启动 web、token URL 复制粘贴流程、TUI 启动

## 12. 变更记录

| 日期 | 改了什么 | 为什么 |
|---|---|---|
| 2026-05-15 | 初版 | Plan 6 完成；上 Web + TUI |
