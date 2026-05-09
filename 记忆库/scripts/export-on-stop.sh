#!/usr/bin/env bash
# SessionEnd hook (Mac): CC 会话结束时 export memories.json
# 注册在 ~/.claude/settings.json，由 CC 自动调用
# 设计原则：幂等 / 静默失败 / 不阻塞 CC 关闭

# 不用 set -u（与 import-on-start.sh 一致，避免含中文路径的解析 bug）
set -o pipefail 2>/dev/null || true

# 扩展 PATH（CC hook 默认 PATH 极简）
export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/local/sbin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

# ============ 消费 stdin（C3 修复）============
# CC 会通过 stdin pipe 一段 JSON payload，不读会阻塞 pipe buffer
INPUT=$(cat 2>/dev/null || true)
# INPUT 目前不使用，但必须读完释放 pipe

# ============ 配置 ============
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MEMORY_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
MEMORIES_JSON="$MEMORY_DIR/memories.json"
SYNC_PY="$SCRIPT_DIR/sync.py"
LOG_FILE="$HOME/Library/Logs/mcp-memory-export.log"

# ============ 日志 ============
mkdir -p "$(dirname "$LOG_FILE")"
exec >>"$LOG_FILE" 2>&1
echo "━━━ $(date -u '+%Y-%m-%dT%H:%M:%SZ') export-on-stop ━━━"

# ============ 前置检查 ============
if [[ ! -f "$SYNC_PY" ]]; then
    echo "[SKIP] sync.py 不存在: $SYNC_PY"
    exit 0
fi

# 自动找 Python 3.11+（系统 python3 可能是 3.9）
# CC 给 hook 的 PATH 可能很精简（只有 /usr/bin:/bin），必须硬编码常见路径 fallback
PYTHON=""
# 候选路径：PATH 里的 + macOS brew 常见位置 + 用户级 pip 路径
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
    echo "[SKIP] 找不到 Python >= 3.11（CC hook 的 PATH 太窄时常见，请把 python 加入硬编码候选）"
    exit 0
fi

# ============ export 到临时文件（原子替换）============
# 用 mktemp 避免 PID 复用冲突（Medium 2）
TMP_FILE=$(mktemp "${MEMORIES_JSON}.XXXXXX")
trap 'rm -f "$TMP_FILE"' EXIT

# 调 Python sync.py，失败不报错只记日志
if ! "$PYTHON" "$SYNC_PY" export --output "$TMP_FILE" 2>&1; then
    echo "[FAIL] sync.py export 失败"
    exit 0
fi

# 验证生成的 JSON 合法（用 argv 传参避免引号 / 中文路径注入，H1 修复）
if ! "$PYTHON" -c 'import sys,json; json.load(open(sys.argv[1]))' "$TMP_FILE" 2>/dev/null; then
    echo "[FAIL] 输出不是合法 JSON: $TMP_FILE"
    exit 0
fi

SIZE_NEW=$(wc -c < "$TMP_FILE" 2>/dev/null | tr -d ' ' || echo 0)
SIZE_OLD=0
[[ -f "$MEMORIES_JSON" ]] && SIZE_OLD=$(wc -c < "$MEMORIES_JSON" 2>/dev/null | tr -d ' ' || echo 0)

# 原子替换
mv "$TMP_FILE" "$MEMORIES_JSON"
trap - EXIT
echo "[OK] export 完成 ($SIZE_OLD → $SIZE_NEW bytes)"

# 坚果云自动同步。Git 按需手动提交。
exit 0
