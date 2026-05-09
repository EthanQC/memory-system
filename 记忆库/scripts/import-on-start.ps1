# SessionStart hook (Windows): CC 启动时检查 memories.json 是否需要 import

$ErrorActionPreference = "SilentlyContinue"

# ============ 消费 stdin（C3 修复）============
$null = [Console]::In.ReadToEnd()

# ============ 配置 ============
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$MemoryDir = Split-Path -Parent $ScriptDir
$MemoriesJson = Join-Path $MemoryDir "memories.json"
$SyncPy = Join-Path $ScriptDir "sync.py"
$MarkerFile = Join-Path $env:LOCALAPPDATA "mcp-memory\.last-import-timestamp"
$LogFile = Join-Path $env:LOCALAPPDATA "mcp-memory\import.log"

# ============ 日志 ============
New-Item -ItemType Directory -Force -Path (Split-Path $LogFile -Parent) | Out-Null
function Log($msg) { Add-Content -Path $LogFile -Value "[$(Get-Date -Format o)] $msg" -Encoding UTF8 }

# 无 BOM UTF-8 写文件（H3/H4 修复）
function Write-Utf8NoBom($path, $content) {
    $utf8 = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($path, $content, $utf8)
}

Log "--- import-on-start ---"

# ============ 早退场景 ============
if (-not (Test-Path $SyncPy)) { Log "[SKIP] sync.py 不存在"; exit 0 }
if (-not (Test-Path $MemoriesJson)) { Log "[SKIP] memories.json 不存在"; exit 0 }

$size = (Get-Item $MemoriesJson).Length
if ($size -lt 30) { Log "[SKIP] memories.json 过小 ($size bytes)"; exit 0 }

$Python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $Python) { $Python = (Get-Command py -ErrorAction SilentlyContinue).Source }
if (-not $Python) { Log "[SKIP] python 不在 PATH"; exit 0 }

$mtime = (Get-Item $MemoriesJson).LastWriteTimeUtc.Ticks
$lastImport = 0
if (Test-Path $MarkerFile) {
    $markerRaw = Get-Content $MarkerFile -Raw -Encoding UTF8 -ErrorAction SilentlyContinue
    if ($markerRaw) {
        $markerTrim = $markerRaw.Trim() -replace "[^\d-]",""  # 剥离 BOM / 空白 / 非数字
        if ($markerTrim) { $lastImport = [int64]$markerTrim }
    }
}

if ($mtime -le $lastImport) {
    Log "[SKIP] memories.json 未更新 (mtime=$mtime, last=$lastImport)"
    exit 0
}

# ============ 执行 import ============
Log "[INFO] 检测到更新, import 中... ($size bytes)"
try {
    $proc = Start-Process -FilePath $Python `
        -ArgumentList @("`"$SyncPy`"", "import", "--input", "`"$MemoriesJson`"") `
        -Wait -PassThru -NoNewWindow -RedirectStandardOutput "$LogFile.tmp" -RedirectStandardError "$LogFile.tmp.err"
    if (Test-Path "$LogFile.tmp") { Get-Content "$LogFile.tmp" | ForEach-Object { Log $_ } ; Remove-Item "$LogFile.tmp" }
    if (Test-Path "$LogFile.tmp.err") { Get-Content "$LogFile.tmp.err" | ForEach-Object { Log "STDERR: $_" } ; Remove-Item "$LogFile.tmp.err" }

    if ($proc.ExitCode -eq 0) {
        Write-Utf8NoBom $MarkerFile $mtime.ToString()
        Log "[OK] import 完成"
    } else {
        Log "[FAIL] sync.py import 退出码 $($proc.ExitCode)"
    }
} catch {
    Log "[FAIL] 异常: $_"
}
