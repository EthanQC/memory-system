# mcp-memory-service Windows 一键安装（审查修复版）
# 使用：
#   cd $env:USERPROFILE\claude-workspace\记忆库
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#   .\install-win.ps1
# 幂等：可重复运行

#Requires -Version 5.1
$ErrorActionPreference = "Stop"

# ============ 配置 ============
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$MemoryDir = $ScriptDir                                         # 记忆库根目录
$SyncScriptsDir = Join-Path $ScriptDir "scripts"
$MemoriesJson = Join-Path $MemoryDir "memories.json"
$SyncPy = Join-Path $SyncScriptsDir "sync.py"

$AppData = Join-Path $env:LOCALAPPDATA "mcp-memory"
$TaskName = "MCPMemoryHTTPServer"
$TaskDescription = "MCP Memory Service HTTP Server"

$CCConfig = Join-Path $env:USERPROFILE ".claude\settings.json"
$CCMcp    = Join-Path $env:USERPROFILE ".claude\.mcp.json"

$HttpPort = 8000
$HttpHost = "127.0.0.1"

# ============ Helper ============
function Info($msg) { Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "[OK]   $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Fail($msg) { Write-Host "[FAIL] $msg" -ForegroundColor Red; exit 1 }
function Step($msg) { Write-Host ""; Write-Host "=== $msg ===" -ForegroundColor Cyan }

# H3/H4 修复：PowerShell 5.1 写无 BOM UTF-8（标准 JSON 要求）
function Write-Utf8NoBom($path, $content) {
    $utf8 = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($path, $content, $utf8)
}

# ============ 前置检查 ============
Step "1/9 前置依赖检查"

$Python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $Python) { $Python = (Get-Command py -ErrorAction SilentlyContinue).Source }
if (-not $Python) { Fail "未检测到 Python。安装：winget install Python.Python.3.12" }

$pyVer = (& $Python --version 2>&1).ToString()
if (-not ($pyVer -match "Python (\d+)\.(\d+)")) { Fail "无法解析 Python 版本: $pyVer" }
$major = [int]$Matches[1]; $minor = [int]$Matches[2]
if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 11)) {
    Fail "Python >= 3.11 required, 当前: $pyVer"
}
Ok $pyVer

try { git --version | Out-Null; Ok "Git 已装" } catch { Fail "未装 Git。winget install Git.Git" }
try { & $Python -m pip --version | Out-Null; Ok "pip 就绪" } catch { Fail "pip 不可用" }

# 端口占用预检（H5）
$portBusy = Get-NetTCPConnection -LocalPort $HttpPort -State Listen -ErrorAction SilentlyContinue
if ($portBusy) {
    Fail "端口 $HttpPort 已被占用。释放端口或修改本脚本中的 `$HttpPort"
}
Ok "端口 $HttpPort 空闲"

# 必需文件检查
if (-not (Test-Path $SyncPy)) { Fail "缺少 sync.py: $SyncPy" }
if (-not (Test-Path (Join-Path $SyncScriptsDir "export-on-stop.ps1"))) { Fail "缺少 export-on-stop.ps1" }
if (-not (Test-Path (Join-Path $SyncScriptsDir "import-on-start.ps1"))) { Fail "缺少 import-on-start.ps1" }
Ok "实施包文件完整"

# ============ 安装 mcp-memory-service ============
Step "2/9 安装 mcp-memory-service"

$Installed = & $Python -c "import mcp_memory_service; print(mcp_memory_service._version.__version__)" 2>$null
if ($Installed) {
    Ok "已安装 v$Installed"
} else {
    Warn "首次安装：pip 会下载 torch/transformers/onnx 等，约 2-3GB"
    & $Python -m pip install --user "mcp-memory-service[sqlite]"
    if ($LASTEXITCODE -ne 0) { Fail "pip 安装失败" }
    Ok "pip 安装完成"
}

# 定位 memory CLI
$MemoryCli = (Get-Command memory -ErrorAction SilentlyContinue).Source
if (-not $MemoryCli) {
    $UserBase = & $Python -c "import site; print(site.USER_BASE)"
    $candidate = Join-Path $UserBase "Scripts\memory.exe"
    if (Test-Path $candidate) { $MemoryCli = $candidate }
}
if (-not $MemoryCli) { Fail "找不到 memory CLI。把 $UserBase\Scripts 加入 PATH 后重跑" }
Ok "memory CLI: $MemoryCli"

# ============ 数据目录 ============
Step "3/9 本机专属数据目录"
New-Item -ItemType Directory -Force -Path $AppData | Out-Null
Ok $AppData

# ============ Scheduled Task ============
Step "4/9 注册 Windows Scheduled Task"

# 幂等
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Info "已有同名任务，先移除"
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# Wrapper：前台运行 memory server（Medium 4 修复：让 Task 正确识别运行中）
$WrapperScript = Join-Path $AppData "run-http-server.ps1"
$wrapperContent = @"
`$ErrorActionPreference = 'Continue'
`$env:MCP_HTTP_HOST = '$HttpHost'
`$env:MCP_HTTP_PORT = '$HttpPort'
`$env:MCP_MEMORY_STORAGE_BACKEND = 'sqlite_vec'
`$env:MCP_MEMORY_SQLITE_PRAGMAS = 'journal_mode=WAL,busy_timeout=15000,cache_size=20000'
`$env:MCP_CONSOLIDATION_ENABLED = 'true'

# 前台运行（Task Scheduler 才能正确识别进程存活状态 + 崩溃重启）
& '$MemoryCli' server --http *>&1 | Out-File -FilePath '$AppData\server.log' -Append -Encoding UTF8
"@
Write-Utf8NoBom $WrapperScript $wrapperContent

$Action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$WrapperScript`""

# C4 修复：RepetitionInterval 必须配 RepetitionDuration 才重复
$Trigger1 = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$Trigger2 = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -RepetitionDuration ([TimeSpan]::FromDays(365 * 10))   # 10 年，够用

$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero)   # 任务不超时

$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

try {
    Register-ScheduledTask -TaskName $TaskName `
        -Action $Action -Trigger @($Trigger1, $Trigger2) `
        -Settings $Settings -Principal $Principal `
        -Description $TaskDescription | Out-Null
    Ok "Scheduled Task 注册成功（登录启动 + 5 分钟 watchdog）"
} catch {
    Fail "注册 Task 失败: $_"
}

Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 3

# ============ 健康检查 ============
Step "5/9 健康检查"
$HealthOk = $false
for ($i=1; $i -le 10; $i++) {
    try {
        $resp = Invoke-WebRequest -Uri "http://$HttpHost`:$HttpPort/api/health" -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
        if ($resp.StatusCode -eq 200) { $HealthOk = $true; break }
    } catch { Start-Sleep -Seconds 2 }
}

if ($HealthOk) { Ok "HTTP server 就绪 http://$HttpHost`:$HttpPort" }
else {
    Warn "HTTP server 健康检查失败，但 Task 已注册。查日志："
    Warn "  Get-Content $AppData\server.log -Tail 50"
    Warn "  Get-ScheduledTaskInfo -TaskName $TaskName"
}

# ============ 首次 import（C1 修复）============
Step "6/9 检查记忆数据导入"
if ((Test-Path $MemoriesJson) -and ((Get-Item $MemoriesJson).Length -gt 30)) {
    $size = (Get-Item $MemoriesJson).Length
    Info "发现 memories.json ($size bytes)，import 中..."
    & $Python $SyncPy import --input $MemoriesJson
    if ($LASTEXITCODE -eq 0) { Ok "Import 完成" }
    else { Warn "Import 失败（非致命，可稍后手动跑 python $SyncPy import --input $MemoriesJson）" }
} else {
    Info "memories.json 不存在或为空（首次安装正常）"
}

# ============ .mcp.json 配置（H3/H4 无 BOM）============
Step "7/9 Claude Code MCP 配置"

$CCMcpDir = Split-Path -Parent $CCMcp
New-Item -ItemType Directory -Force -Path $CCMcpDir | Out-Null
if (-not (Test-Path $CCMcp)) { Write-Utf8NoBom $CCMcp '{"mcpServers": {}}' }

# 用 Python 做 JSON merge（避免 PowerShell JSON 类型系统折腾）
$env:PY_CFG_PATH = $CCMcp
$env:PY_MCP_URL  = "http://$HttpHost`:$HttpPort/mcp"
$pyScript = @'
import os, json
from pathlib import Path
p = Path(os.environ["PY_CFG_PATH"])
cfg = json.loads(p.read_text(encoding="utf-8") or "{}")
cfg.setdefault("mcpServers", {})
cfg["mcpServers"]["mcp-memory"] = {"type": "http", "url": os.environ["PY_MCP_URL"]}
p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
print("OK")
'@
$pyResult = & $Python -c $pyScript
if ($LASTEXITCODE -ne 0) { Fail ".mcp.json 写入失败: $pyResult" }
Ok ".mcp.json 已注册"

# ============ hooks 配置（H1+H2 修复）============
Step "8/9 CC SessionEnd / SessionStart hooks"

$CCConfigDir = Split-Path -Parent $CCConfig
New-Item -ItemType Directory -Force -Path $CCConfigDir | Out-Null
if (-not (Test-Path $CCConfig)) { Write-Utf8NoBom $CCConfig '{}' }

$exportPs1 = Join-Path $SyncScriptsDir "export-on-stop.ps1"
$importPs1 = Join-Path $SyncScriptsDir "import-on-start.ps1"

$env:PY_CFG_PATH = $CCConfig
$env:PY_EXPORT_CMD = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$exportPs1`""
$env:PY_IMPORT_CMD = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$importPs1`""
$pyScript2 = @'
import os, json
from pathlib import Path
p = Path(os.environ["PY_CFG_PATH"])
cfg = json.loads(p.read_text(encoding="utf-8") or "{}")
cfg.setdefault("hooks", {})

def upsert(event, cmd):
    arr = cfg["hooks"].setdefault(event, [])
    kept = []
    for h in arr:
        if not isinstance(h, dict):
            kept.append(h); continue
        inner = h.get("hooks") or []
        has_our_cmd = any(
            isinstance(x, dict) and x.get("command") == cmd for x in inner
        )
        if not has_our_cmd:
            kept.append(h)
    kept.append({"matcher": "*",
                 "hooks": [{"type": "command", "command": cmd}]})
    cfg["hooks"][event] = kept

upsert("SessionEnd",   os.environ["PY_EXPORT_CMD"])
upsert("SessionStart", os.environ["PY_IMPORT_CMD"])
p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
print("OK")
'@
$pyResult2 = & $Python -c $pyScript2
if ($LASTEXITCODE -ne 0) { Fail "hooks 写入失败: $pyResult2" }
Ok "hooks 注册完成"

# ============ 完成 ============
Step "9/9 安装完成"

@"

mcp-memory-service 已装好

下一步：
  1. 重启 Claude Code（让 .mcp.json 生效）
  2. 对话里验证："列出当前可用的 MCP 工具"
  3. Dashboard: http://$HttpHost`:$HttpPort

常用命令：
  任务状态:      Get-ScheduledTask -TaskName $TaskName | Format-List
  启动任务:      Start-ScheduledTask -TaskName $TaskName
  停止任务:      Stop-ScheduledTask -TaskName $TaskName
  卸载任务:      Unregister-ScheduledTask -TaskName $TaskName -Confirm:`$false
  查看日志:      Get-Content $AppData\server.log -Tail 50
  手动 export:   & "$Python" "$SyncPy" export --output "$MemoriesJson"
  手动 import:   & "$Python" "$SyncPy" import --input "$MemoriesJson"

数据位置：
  SQLite:        $AppData
  memories.json: $MemoriesJson（坚果云实时同步）

"@ | Write-Host -ForegroundColor Green
