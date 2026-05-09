# 筑真记忆系统

> 基于 `mcp-memory-service` 的个人 AI 记忆中枢。
> 纯本地运行 + 自动遗忘机制 + 跨平台（Mac/Windows）+ 多电脑同步。

## 为什么有这个

Claude Code 每次新会话都从零开始，你得反复同步背景。这个系统让 AI **跨会话、跨电脑自动记住**你讨论过的决策、人物、项目、方法论——并在信息过期时自动降权。

## 设计原则

1. **纯本地**：数据存在本机 SQLite，无外部 API 调用，无 Docker
2. **自动遗忘**：5 阶段 Dream-inspired consolidation（每日/每周/每月）
3. **跨电脑同步**：坚果云实时同步 `memories.json` + Git 按需提交
4. **双平台对等**：Mac LaunchAgent + Windows Scheduled Task
5. **零 CC 主上下文侵占**：通过 HTTP MCP 按需调用
6. **解耦**：除已有的 `feishu-user-plugin` 外零依赖其他 skill

## 文件说明

```
记忆库/
├── README.md                      本文档
├── memories.json                  ⭐ 记忆数据（坚果云同步 + Git 追踪）
├── .config.yaml                   系统配置
├── .gitignore                     Git 排除规则
├── bootstrap-new-computer.md      换新电脑从零安装指南
│
├── install-mac.sh                 Mac 一键安装
├── install-win.ps1                Windows 一键安装
│
└── scripts/
    ├── sync.py                    ⭐ export/import 核心工具（Python 直连 SQLite）
    ├── export-on-stop.sh/.ps1     SessionEnd hook（Mac/Win）
    └── import-on-start.sh/.ps1    SessionStart hook（Mac/Win）
```

## 安装

### 首次（当前电脑）

**Mac**：
```bash
cd claude-workspace/记忆库
bash install-mac.sh
# 注意：首次会下载 torch/transformers 等依赖，约 2-3GB
```

**Windows**：
```powershell
cd $env:USERPROFILE\claude-workspace\记忆库
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\install-win.ps1
# 注意：首次会下载 torch/transformers 等依赖，约 2-3GB
```

### 换新电脑

见 [bootstrap-new-computer.md](./bootstrap-new-computer.md)。

## 日常使用

**装完后你什么都不用做**：

- 开机：系统自动启动 HTTP server（launchd/Task Scheduler）
- Claude Code 对话：CC 自动调用 memory tools，**记忆静默写入**
- 关闭 CC：SessionEnd hook 自动 `export memories.json`，坚果云自动同步
- 打开 CC（包括换电脑）：SessionStart hook 自动 import 最新数据
- 凌晨 02:00：遗忘 scheduler 自动跑（你在睡觉）

## 手动操作

### 查看记忆

```bash
# Mac/Linux
curl -s http://127.0.0.1:8000/api/memories | python3 -m json.tool | less

# Windows
Invoke-RestMethod http://127.0.0.1:8000/api/memories | ConvertTo-Json -Depth 10
```

### 浏览 Web Dashboard

打开浏览器访问 `http://127.0.0.1:8000`，有记忆列表、标签浏览、搜索、统计。

### Git 按需提交（用户控制）

```bash
cd claude-workspace/记忆库
git add memories.json
git commit -m "memory snapshot: <意义简述>"
git push
```

**什么时候值得 commit**：
- 重要项目/决策后
- 换电脑前（双保险）
- 每周/每月定期快照

### 手动触发 export / import

```bash
# Mac
python3 scripts/sync.py export --output memories.json
python3 scripts/sync.py import --input memories.json

# 或直接跑 hook 脚本（会走跟自动流程相同的原子替换 + 日志）
bash scripts/export-on-stop.sh
bash scripts/import-on-start.sh
```

```powershell
# Windows
python scripts\sync.py export --output memories.json
python scripts\sync.py import --input memories.json
```

### 手动触发 consolidation（不等 02:00）

```bash
curl -X POST http://127.0.0.1:8000/api/consolidation/trigger \
  -H "Content-Type: application/json" \
  -d '{"time_horizon": "weekly", "immediate": true}'
```

## 服务管理

### Mac

```bash
# 查看状态
launchctl list | grep mcp.memory

# 重启
launchctl unload ~/Library/LaunchAgents/com.mcp.memory-service.plist
launchctl load ~/Library/LaunchAgents/com.mcp.memory-service.plist

# 查看日志
tail -f ~/Library/Logs/mcp-memory-http-server.log
tail -f ~/Library/Logs/mcp-memory-http-server.err.log
tail -f ~/Library/Logs/mcp-memory-export.log
tail -f ~/Library/Logs/mcp-memory-import.log
```

### Windows

```powershell
# 查看状态
Get-ScheduledTask -TaskName MCPMemoryHTTPServer
Get-ScheduledTaskInfo -TaskName MCPMemoryHTTPServer

# 重启
Stop-ScheduledTask -TaskName MCPMemoryHTTPServer
Start-ScheduledTask -TaskName MCPMemoryHTTPServer

# 日志
Get-Content $env:LOCALAPPDATA\mcp-memory\export.log -Tail 20
Get-Content $env:LOCALAPPDATA\mcp-memory\import.log -Tail 20
```

## 数据位置

| 资源 | Mac | Windows |
|---|---|---|
| 运行时 SQLite | `~/Library/Application Support/mcp-memory/` | `%LOCALAPPDATA%\mcp-memory\` |
| 同步的 JSON | `claude-workspace/记忆库/memories.json` | 同 |
| 日志 | `~/Library/Logs/mcp-memory-*.log` | `%LOCALAPPDATA%\mcp-memory\*.log` |
| 自启配置 | `~/Library/LaunchAgents/com.mcp.memory-service.plist` | Task Scheduler `MCPMemoryHTTPServer` |

**关键**：SQLite 在本机专属路径，**坚果云绝对不会同步**（避免 WAL 文件损坏）。

## 遗忘机制

采用论文级 5 阶段 Dream-inspired consolidation：

1. **Decay**：按内容类型应用指数衰减（decision 永久、fact 默认 90 天）
2. **Association**：发现记忆间关联，增强高频共现的
3. **Relationship Inference**：推断关系边（supports/contradicts/causes 等）
4. **Compression**：合并低质量相似记忆
5. **Forgetting**：`active=0` 软失效（不真删，可 `searchArchived()` 找回）

时间表：
- Daily 02:00：增量 decay + association
- Weekly Sun 03:00：关系图重建
- Monthly 1st 04:00：深度归档 + 低价值清理

## 团队分发

1. 复制整个 `记忆库/` 目录给团队成员（**不包括** `memories.json`）
2. 新成员跑 `install-mac.sh` 或 `install-win.ps1`
3. 完成

每人有自己的 `memories.json`（在各自私有同步空间，不共享记忆数据）。

## 故障排查

| 症状 | 检查 |
|---|---|
| CC 里看不到 memory 工具 | 重启 CC；`cat ~/.claude/.mcp.json` 看是否有 `mcp-memory` 项 |
| HTTP 500/timeout | 看 `~/Library/Logs/mcp-memory-http-server.err.log` |
| 换电脑后记忆没跟过来 | 确认坚果云同步完成；手动跑 `import-on-start.sh` |
| memories.json 有冲突 | 见 `bootstrap-new-computer.md` § 四 · Q4 |
| 记忆爆炸（几万条）| 手动触发 consolidation 或等 monthly job |

## 参考

- [10-最终方案-mcp-memory-service.md](../10-最终方案-mcp-memory-service.md) — 架构决策全文
- [mcp-memory-service 官方仓库](https://github.com/doobidoo/mcp-memory-service)
- [Memory Consolidation 官方指南](https://github.com/doobidoo/mcp-memory-service/blob/main/docs/guides/memory-consolidation-guide.md)
