# 换新电脑：从零到记忆系统可用

> 用途：无论换新 Mac 还是新 Windows，从一台"空机器"到记忆系统完全可用。
> 前提：你的 `claude-workspace/` 已通过坚果云 + Git 同步好，包含 `记忆库/memories.json`。

## 步骤概览

1. 装系统工具（Python、Git、坚果云）
2. 等坚果云同步完 `claude-workspace/`
3. 跑一键安装脚本
4. 打开 Claude Code 验证

全程 **约 15-30 分钟**（取决于网速和坚果云同步速度）。

---

## 一、Mac 新机器流程

### 1. 系统准备（如果是完全全新 Mac）

```bash
# 装 Homebrew（如果没有）
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 装 Python 3.12（mcp-memory-service 需要 >= 3.11）
brew install python@3.12

# 装 Git
brew install git

# 装坚果云客户端
# https://www.jianguoyun.com/s/downloads/mac
```

### 2. 登录坚果云并同步 claude-workspace

- 坚果云登录后，把 `claude-workspace/` 加入同步列表
- **等同步完成**（看托盘图标变绿）
- 验证：`ls ~/claude-workspace/记忆库/memories.json` 能看到文件

### 3. 一键安装

```bash
cd ~/claude-workspace/记忆库
bash install-mac.sh
```

脚本会自动：
- 检查前置依赖（Python 3.11+、Git、pip、端口 8000 是否空闲）
- `pip install --user mcp-memory-service[sqlite]`（注意：会下载 torch/transformers 等依赖，总计 2-3GB，首次安装耐心等）
- 创建 `~/Library/Application Support/mcp-memory/` 本机数据目录
- 生成并加载 launchd plist（开机自启 + 崩溃自动重启）
- 启动 HTTP server（`127.0.0.1:8000`）
- **自动 import `memories.json`**（通过 `scripts/sync.py` 直连 SQLite，跨机器记忆恢复的关键！）
- 配置 `~/.claude/.mcp.json` 注册 mcp-memory HTTP client
- 配置 `~/.claude/settings.json` 注册 SessionStart/SessionEnd hooks

### 4. 重启 Claude Code 验证

```bash
# 关闭再打开 Claude Code
# 在对话里测试
```

对话中说："列出当前可用的 MCP 工具"——应该看到 `mcp-memory` 系列工具。

然后问："我之前关于 X 的决策是什么？"——应该能召回 `memories.json` 里导入的历史记忆。

---

## 二、Windows 新机器流程

### 1. 系统准备

```powershell
# 用 PowerShell 管理员身份运行
winget install Python.Python.3.12
winget install Git.Git
winget install Jianguoyun.Nutstore   # 坚果云，名字可能变
```

关闭 PowerShell 重开（让 PATH 生效）。

### 2. 登录坚果云同步

- 登录坚果云
- 同步 `claude-workspace/`
- 等同步完，确认 `$env:USERPROFILE\claude-workspace\记忆库\memories.json` 存在

### 3. 一键安装

```powershell
cd $env:USERPROFILE\claude-workspace\记忆库

# 允许当前会话跑脚本
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

.\install-win.ps1
```

脚本会自动：
- 检查 Python/Git/pip
- `pip install --user mcp-memory-service[sqlite]`
- 创建 `%LOCALAPPDATA%\mcp-memory\` 本机数据目录
- 注册 Windows Scheduled Task `MCPMemoryHTTPServer`（登录自启 + 5 分钟 watchdog）
- 启动 HTTP server
- **自动 import `memories.json`**
- 配置 `%USERPROFILE%\.claude\.mcp.json`
- 配置 hooks

### 4. 重启 Claude Code 验证

同 Mac。

---

## 三、验证清单

装完后跑这些命令确认健康：

### Mac

```bash
# 1. HTTP server 运行中
curl http://127.0.0.1:8000/api/health

# 2. launchd 状态
launchctl list | grep mcp.memory

# 3. 数据库存在
ls -lh ~/Library/Application\ Support/mcp-memory/

# 4. 日志无严重错误
tail -20 ~/Library/Logs/mcp-memory-http-server.log

# 5. 记忆数量
curl -s http://127.0.0.1:8000/api/memories | python3 -c "import json,sys; d=json.load(sys.stdin); print('memories count:', len(d.get('memories', [])))"
```

### Windows

```powershell
# 1. HTTP server 运行中
Invoke-RestMethod http://127.0.0.1:8000/api/health

# 2. Scheduled Task 状态
Get-ScheduledTask -TaskName MCPMemoryHTTPServer

# 3. 数据库存在
ls $env:LOCALAPPDATA\mcp-memory\

# 4. 记忆数量
(Invoke-RestMethod http://127.0.0.1:8000/api/memories).memories.Count
```

---

## 四、常见问题

### Q: 第 3 步安装脚本报 "memory CLI 找不到"

**原因**：pip 装的 `memory` 命令在 user site-packages bin 目录，不在 PATH。

**Mac 修复**：
```bash
# 查看 user bin 路径
python3 -c "import site; print(site.USER_BASE)"
# 通常是 ~/Library/Python/3.12/bin

# 加入 PATH（添加到 ~/.zshrc）
echo 'export PATH="$HOME/Library/Python/3.12/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

**Windows 修复**：
```powershell
# 找到 user Scripts 路径
python -c "import site; print(site.USER_BASE)"
# 通常是 C:\Users\<name>\AppData\Roaming\Python\Python312\Scripts

# 加入 PATH
$userScripts = "$env:APPDATA\Python\Python312\Scripts"
[Environment]::SetEnvironmentVariable("PATH", "$env:PATH;$userScripts", "User")
# 重开 PowerShell
```

### Q: 坚果云还没同步完怎么办

- 打开坚果云客户端，看同步进度
- 如果大量冲突，先解决（通常跟着提示点"使用较新"）
- 不着急，装系统服务和装脚本不需要 `memories.json` 已经存在，只是没有初始数据

### Q: memories.json 很大（几十 MB）import 失败

- 默认 HTTP 超时 60 秒，大文件可能超时
- 解决：分批 import，或者临时改 install 脚本里 `--max-time 60` 为 `600`

### Q: 两台电脑 memories.json 同时被修改了

- 坚果云会产生 `memories.sync-conflict-...json` 冲突文件
- 解决：
  ```bash
  # 两个文件都 import 一遍（sync.py 内置 content hash 去重）
  python3 scripts/sync.py import --input memories.json
  python3 scripts/sync.py import --input memories.sync-conflict-xxx.json

  # 重新 export 合并后版本
  python3 scripts/sync.py export --output memories.json
  rm memories.sync-conflict-*.json
  ```

### Q: HTTP server 一直拉不起来

- Mac 查日志：`tail -f ~/Library/Logs/mcp-memory-http-server.err.log`
- Windows 查 Task Scheduler 历史：`Get-ScheduledTaskInfo -TaskName MCPMemoryHTTPServer`
- 常见原因：端口 8000 被占 → 改 `$HttpPort`，或杀占用进程

### Q: 我不想让它开机自启，只在需要时手动启

**Mac**：
```bash
launchctl unload ~/Library/LaunchAgents/com.mcp.memory-service.plist
# 以后需要时再 load
```

**Windows**：
```powershell
Disable-ScheduledTask -TaskName MCPMemoryHTTPServer
# 需要时 Start-ScheduledTask
```

---

## 五、卸载

### Mac

```bash
launchctl unload ~/Library/LaunchAgents/com.mcp.memory-service.plist
rm ~/Library/LaunchAgents/com.mcp.memory-service.plist
pip3 uninstall mcp-memory-service
# 数据保留在 ~/Library/Application Support/mcp-memory/，需要手动删
```

### Windows

```powershell
Unregister-ScheduledTask -TaskName MCPMemoryHTTPServer -Confirm:$false
pip uninstall mcp-memory-service
# 数据保留在 %LOCALAPPDATA%\mcp-memory\
```
