#!/usr/bin/env bash
# SessionStart hook (Mac): CC 启动时检查 memories.json 是否需要 import
# 如果另一台电脑有更新（坚果云同步过来），自动合并进本机 SQLite

# 不用 set -u，hook 设计原则是静默失败不阻断 CC
# 含中文路径的变量扩展在 set -u 下 bash 解析器有时会报虚假 unbound 错误
set -o pipefail 2>/dev/null || true

# 扩展 PATH（CC hook 默认 PATH 极简）
export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/local/sbin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

# ============ 消费 stdin（C3 修复）============
INPUT=$(cat 2>/dev/null || true)

# ============ 配置 ============
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MEMORY_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
MEMORIES_JSON="$MEMORY_DIR/memories.json"
SYNC_PY="$SCRIPT_DIR/sync.py"
MARKER_FILE="$HOME/Library/Application Support/mcp-memory/.last-import-timestamp"
LOG_FILE="$HOME/Library/Logs/mcp-memory-import.log"

# ============ 日志 ============
mkdir -p "$(dirname "$LOG_FILE")"
mkdir -p "$(dirname "$MARKER_FILE")"
exec >>"$LOG_FILE" 2>&1
echo "━━━ $(date -u '+%Y-%m-%dT%H:%M:%SZ') import-on-start ━━━"

# ============ 早退场景 ============

if [[ ! -f "$SYNC_PY" ]]; then
    echo "[SKIP] sync.py 不存在"
    exit 0
fi

# 自动找 Python 3.11+（CC hook PATH 常常极简，硬编码候选路径）
PYTHON=""
CANDIDATES=(
    "$(command -v python3.13 2>/dev/null)"
    "$(command -v python3.12 2>/dev/null)"
    "$(command -v python3.11 2>/dev/null)"
    /opt/homebrew/bin/python3.13
    /opt/homebrew/bin/python3.12
    /opt/homebrew/bin/python3.11
    /opt/homebrew/opt/python@3.13/bin/python3.13
    /opt/homebrew/opt/python@3.12/bin/python3.12
    /opt/homebrew/opt/python@3.11/bin/python3.11
    /usr/local/bin/python3.13
    /usr/local/bin/python3.12
    /usr/local/bin/python3.11
    "$HOME/.pyenv/shims/python3.12"
    "$HOME/.pyenv/shims/python3.11"
    "$(command -v python3 2>/dev/null)"
)
for c in "${CANDIDATES[@]}"; do
    [[ -n "$c" && -x "$c" ]] || continue
    v=$("$c" -c 'import sys; print(sys.version_info[0]*100+sys.version_info[1])' 2>/dev/null || echo 0)
    if [[ $v -ge 311 ]]; then
        PYTHON="$c"
        break
    fi
done
if [[ -z "$PYTHON" ]]; then
    echo "[SKIP] 找不到 Python >= 3.11"
    exit 0
fi

if [[ ! -f "$MEMORIES_JSON" ]]; then
    echo "[SKIP] memories.json 不存在（首次使用正常）"
    exit 0
fi

SIZE=$(wc -c < "$MEMORIES_JSON" 2>/dev/null | tr -d ' ' || echo 0)
if [[ $SIZE -lt 30 ]]; then
    echo "[SKIP] memories.json 过小 ($SIZE bytes)，视为空"
    exit 0
fi

# mtime 戳对比（Mac 专用：stat -f %m）
MEMORIES_MTIME=$(stat -f %m "$MEMORIES_JSON" 2>/dev/null || echo 0)
LAST_IMPORT=0
[[ -f "$MARKER_FILE" ]] && LAST_IMPORT=$(cat "$MARKER_FILE" 2>/dev/null || echo 0)

if [[ $MEMORIES_MTIME -le $LAST_IMPORT ]]; then
    echo "[SKIP] memories.json 未更新（mtime=$MEMORIES_MTIME, last=$LAST_IMPORT）"
    exit 0
fi

# ============ 执行 import ============
echo "[INFO] 检测到更新，import 中... ($SIZE bytes)"
if "$PYTHON" "$SYNC_PY" import --input "$MEMORIES_JSON" 2>&1; then
    echo "$MEMORIES_MTIME" > "$MARKER_FILE"
    echo "[OK] import 完成"
else
    echo "[FAIL] sync.py import 失败"
fi

exit 0
