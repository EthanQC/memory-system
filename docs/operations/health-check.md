---
title: 健康检查 — memoryd doctor
keywords: doctor, health, 健康检查, 验证, 在不在干活, 诊断
---

# 健康检查：怎么验证 memoryd 在工作

装完 memoryd 之后第一个该跑的命令：

```bash
memoryd doctor
```

一条命令告诉你系统在不在干活 —— 二进制、数据库、CC hook、launchd、LLM、MCP，每一项 OK / WARN / FAIL 一目了然。

## 输出示例

```
memoryd doctor — 健康检查

[OK]   binary                       /Users/abble/memory-system/memoryd/.venv/bin/memoryd
[OK]   python version               3.11.15
[OK]   data root                    /Users/abble/.local/share/memoryd
[OK]   memory counts                session:87  decision:0  fact:0  preference:0  playbook:0  warning:0
[WARN] entities (KG)                0 entities (sessions=87)
       → knowledge graph never ran; trigger `memoryd analyze-session <slug>` or set up an LLM provider so capture spawns it
[WARN] identity.md                  missing (sessions=87)
       → run `memoryd profile rewrite` to bootstrap; needs LLM
[OK]   CC SessionStart              /Users/abble/memory-system/plugins/claude-code/session-start.py
[OK]   CC SessionEnd                /Users/abble/memory-system/plugins/claude-code/session-end.py
[INFO] Codex notify wrapper         Codex installed but not wrapped
       → run `memoryd setup swap-codex-notify --to wrapper` to capture Codex sessions
[OK]   launchd mirror               running (PID 552)
[WARN] launchd decay                not registered
       → run `memoryd setup install-cron --decay`
[WARN] LLM provider                 anthropic but $ANTHROPIC_API_KEY not set
       → set the env var, or switch to claude-code to reuse your local CC subscription
[WARN] MCP server                   legacy memoryd-server: /Users/abble/memory-system/memoryd/.venv/bin/memoryd-server
       → edit ~/.claude.json: change mcpServers.memoryd.command to memoryd-mcp (no args)
[OK]   recent capture (<7d)         55 sessions in last 7d

summary: ok=8  warn=8  fail=0  info=1  →  overall=WARN
tip: run `memoryd setup auto-install` to fix what auto-install can; follow individual hints above for the rest.
```

## 状态分类

| 状态 | 含义 | 你该怎么做 |
|---|---|---|
| `[OK]` | 这块在干活 | 啥都不用 |
| `[WARN]` | 非致命，但功能没启用或配置过期 | 跟着 `→` 后面的命令修 |
| `[FAIL]` | 这块坏了，对应功能不工作 | 必须修 |
| `[INFO]` | 信息项（计数 / 不适用）| 看一眼就行，没问题 |

退出码也对应：`0=ok`、`1=warn`、`2=fail`，可以挂 CI / monitoring。

## 检查项详解

### 核心（必须 OK）

- **binary** — `memoryd` 在不在 `$PATH` 上
- **python version** — Python `>=3.11`
- **data root** — `~/.local/share/memoryd/` 存在且 `index.db` 能打开
- **CC SessionStart / SessionEnd** — `~/.claude/settings.json` 里的两个 hook 都注册了，且脚本文件存在

### 学习层（强烈建议 OK）

- **entities (KG)** — 知识图谱抽过没。0 entities + sessions>0 = LLM 从来没跑过 capture-side 抽取
- **identity.md** — 自学习用户 profile。sessions>=5 还没生成就提示用户跑 `memoryd profile rewrite`
- **launchd weekly-identity / monthly-report** — 自动重写 cron

### 后台守护

- **launchd mirror** — Codex / OpenClaw 监听守护，没在跑就吃不到第三方 harness 的会话
- **launchd decay / digest** — 每日衰减扫 + 每周 digest 邮件

### 集成

- **Codex notify wrapper** — 装了 Codex 但没接通的话标 `[INFO]` 提醒
- **LLM provider** — 选了 `anthropic` 但 `ANTHROPIC_API_KEY` 没设，会建议切到 `claude-code`（复用本地 CC 订阅，省钱）
- **MCP server** — `~/.claude.json` 里 `mcpServers.memoryd.command` 是不是新 `memoryd-mcp`。如果是 legacy `memoryd-server`（单工具），会强烈提示升级到 13-tool 版本
- **recent capture (<7d)** — 最近 7 天有没有新 session 入库；总数>0 但最近 7 天=0 说明 hook 链路断了

## 一键修

大部分 WARN 都能让 `setup auto-install` 自动解决：

```bash
memoryd setup auto-install
memoryd doctor       # 再验证一遍
```

剩下需要手工的（按 hint 操作）：

| WARN | 修法 |
|---|---|
| `entities (KG)` 0 | 配 LLM provider，下一次 SessionEnd 会自动抽取；或手工 `memoryd analyze-session <slug>` |
| `identity.md` missing | `memoryd profile rewrite`（需要 LLM provider） |
| `LLM provider` no key | `memoryd config set llm.provider claude-code` 复用本地 Claude Code |
| `MCP server` legacy | 编辑 `~/.claude.json` 把 `mcpServers.memoryd.command` 改成 `memoryd-mcp` 绝对路径，重启 CC |
| `Codex notify wrapper` not wrapped | `memoryd setup swap-codex-notify --to wrapper` |

## 脚本化 / CI 集成

```bash
# JSON 格式，便于 jq / 监控消费
memoryd doctor --json

# 只看 WARN / FAIL，省 OK 行
memoryd doctor --quiet

# 退出码作为 CI gate（>=1 时 fail）
memoryd doctor || echo "memoryd unhealthy"
```

JSON schema：

```json
{
  "overall": "warn",
  "checks": [
    {
      "id": "binary",
      "label": "binary",
      "status": "ok",
      "value": "/path/to/memoryd",
      "hint": null
    },
    {
      "id": "mcp_registered",
      "label": "MCP server",
      "status": "warn",
      "value": "legacy memoryd-server: ...",
      "hint": "edit ~/.claude.json: change ... to memoryd-mcp"
    }
  ],
  "summary": "ok=8 warn=8 fail=0 info=1"
}
```

## 调试小贴士

- 颜色不喜欢？`NO_COLOR=1 memoryd doctor`
- 怀疑 hook 没触发？跑 doctor 看 `recent capture (<7d)`，0 就是断了，往 [troubleshooting.md](troubleshooting.md) 看日志位置
- 想看每一个具体 launchd label 的状态：`launchctl list | grep memoryd`
- doctor 自己不消耗 LLM，所以网络不通的时候照样跑得动

## 相关命令

- [`memoryd setup auto-install`](../reference/cli.md#setup) — 一键拉满
- [`memoryd config show`](../reference/cli.md#config) — 看当前生效配置
- [troubleshooting.md](troubleshooting.md) — 各模块日志和具体排查脚本
