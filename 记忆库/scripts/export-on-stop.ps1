# SessionEnd hook (Windows): CC 会话结束时 export memories.json
# 设计原则：幂等 / 静默失败 / 不阻塞 CC 关闭

$ErrorActionPreference = "SilentlyContinue"

# ============ 消费 stdin（C3 修复）============
$null = [Console]::In.ReadToEnd()

# ============ 配置 ============
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$MemoryDir = Split-Path -Parent $ScriptDir
$MemoriesJson = Join-Path $MemoryDir "memories.json"
$SyncPy = Join-Path $ScriptDir "sync.py"
$LogFile = Join-Path $env:LOCALAPPDATA "mcp-memory\export.log"

# ============ 日志 ============
New-Item -ItemType Directory -Force -Path (Split-Path $LogFile -Parent) | Out-Null
function Log($msg) { Add-Content -Path $LogFile -Value "[$(Get-Date -Format o)] $msg" -Encoding UTF8 }
Log "--- export-on-stop ---"

# ============ 前置检查 ============
if (-not (Test-Path $SyncPy)) { Log "[SKIP] sync.py 不存在"; exit 0 }

$Python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $Python) { $Python = (Get-Command py -ErrorAction SilentlyContinue).Source }
if (-not $Python) { Log "[SKIP] python 不在 PATH"; exit 0 }

# ============ export 到临时文件（原子替换）============
$TmpFile = "$MemoriesJson.$([guid]::NewGuid().ToString('N').Substring(0,8))"
try {
    $proc = Start-Process -FilePath $Python `
        -ArgumentList @("`"$SyncPy`"", "export", "--output", "`"$TmpFile`"") `
        -Wait -PassThru -NoNewWindow -RedirectStandardOutput "$LogFile.tmp" -RedirectStandardError "$LogFile.tmp.err"
    if (Test-Path "$LogFile.tmp") { Get-Content "$LogFile.tmp" | ForEach-Object { Log $_ } ; Remove-Item "$LogFile.tmp" }
    if (Test-Path "$LogFile.tmp.err") { Get-Content "$LogFile.tmp.err" | ForEach-Object { Log "STDERR: $_" } ; Remove-Item "$LogFile.tmp.err" }
    if ($proc.ExitCode -ne 0) {
        Log "[FAIL] sync.py export 退出码 $($proc.ExitCode)"
        Remove-Item $TmpFile -Force -ErrorAction SilentlyContinue
        exit 0
    }

    # 验证 JSON 合法
    try {
        Get-Content $TmpFile -Raw -Encoding UTF8 | ConvertFrom-Json | Out-Null
    } catch {
        Log "[FAIL] 输出不是合法 JSON: $_"
        Remove-Item $TmpFile -Force -ErrorAction SilentlyContinue
        exit 0
    }

    $newSize = (Get-Item $TmpFile).Length
    $oldSize = if (Test-Path $MemoriesJson) { (Get-Item $MemoriesJson).Length } else { 0 }

    Move-Item -Path $TmpFile -Destination $MemoriesJson -Force
    Log "[OK] export 完成 ($oldSize → $newSize bytes)"
} catch {
    Log "[FAIL] 异常: $_"
    Remove-Item $TmpFile -Force -ErrorAction SilentlyContinue
    exit 0
}
