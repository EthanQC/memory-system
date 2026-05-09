#!/usr/bin/env bash
# mcp-memory-service Mac 一键安装（审查修复版）
# 使用：cd claude-workspace/记忆库 && bash install-mac.sh
# 幂等：可重复运行

set -euo pipefail

# ============ 配置 ============
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MEMORY_DIR="$SCRIPT_DIR"                                            # claude-workspace/记忆库/
SYNC_SCRIPTS_DIR="$SCRIPT_DIR/scripts"
MEMORIES_JSON="$MEMORY_DIR/memories.json"
SYNC_PY="$SYNC_SCRIPTS_DIR/sync.py"

APP_SUPPORT="$HOME/Library/Application Support/mcp-memory"
LAUNCH_AGENT="$HOME/Library/LaunchAgents/com.mcp.memory-service.plist"
LOG_DIR="$HOME/Library/Logs"
PLIST_LABEL="com.mcp.memory-service"

CC_CONFIG="$HOME/.claude/settings.json"
# 项目级 .mcp.json（CC v2.1.x 只读项目级不读用户级，教训记录在 10-最终方案.md）
# MEMORY_DIR=claude-workspace/记忆库，workspace 根是 claude-workspace
CC_MCP="$(cd "$MEMORY_DIR/.." && pwd)/.mcp.json"

HTTP_PORT=8000
HTTP_HOST="127.0.0.1"

# 继承当前 shell 的代理设置（如果有），写入 plist 让 launchd 启动时也走代理
# 这对首次启动从 HuggingFace 下载 embedding 模型至关重要
SHELL_HTTP_PROXY="${HTTP_PROXY:-${http_proxy:-}}"
SHELL_HTTPS_PROXY="${HTTPS_PROXY:-${https_proxy:-}}"

# 失败回滚记录（H7）
ROLLBACK_ACTIONS=()

# ============ 颜色 ============
C_GREEN='\033[0;32m'; C_YELLOW='\033[0;33m'; C_RED='\033[0;31m'
C_BLUE='\033[0;34m'; C_RESET='\033[0m'
info()  { echo -e "${C_BLUE}[INFO]${C_RESET} $*"; }
ok()    { echo -e "${C_GREEN}[OK]${C_RESET} $*"; }
warn()  { echo -e "${C_YELLOW}[WARN]${C_RESET} $*"; }
fail()  { echo -e "${C_RED}[FAIL]${C_RESET} $*" >&2; rollback; exit 1; }
step()  { echo; echo -e "${C_BLUE}━━━ $* ━━━${C_RESET}"; }

rollback() {
    if [[ ${#ROLLBACK_ACTIONS[@]} -eq 0 ]]; then return; fi
    warn "执行回滚..."
    for action in "${ROLLBACK_ACTIONS[@]}"; do
        info "  $action"
        eval "$action" 2>/dev/null || true
    done
}

# ============ 前置检查 ============
step "1/9 前置依赖检查"

[[ "$(uname)" == "Darwin" ]] || fail "此脚本仅用于 macOS"

# 自动寻找 Python 3.11+（系统 python3 可能是 3.9）
find_python() {
    for c in python3.13 python3.12 python3.11 python3; do
        if command -v "$c" >/dev/null 2>&1; then
            local v=$("$c" -c 'import sys; print(sys.version_info[0]*100+sys.version_info[1])' 2>/dev/null || echo 0)
            if [[ $v -ge 311 ]]; then
                command -v "$c"
                return 0
            fi
        fi
    done
    return 1
}
PYTHON=$(find_python) || fail "需要 Python >= 3.11。brew install python@3.12"
PY_VER=$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")')
ok "Python $PY_VER 于 $PYTHON"

command -v git >/dev/null 2>&1 || fail "未装 Git"
"$PYTHON" -m pip --version >/dev/null 2>&1 || fail "pip 不可用"
ok "Git + pip 就绪"

# 端口占用预检（H5）
if lsof -nP -iTCP:$HTTP_PORT -sTCP:LISTEN >/dev/null 2>&1; then
    LSOF_WHO=$(lsof -nP -iTCP:$HTTP_PORT -sTCP:LISTEN 2>/dev/null | tail -1 | awk '{print $1, "(PID", $2")"}')
    fail "端口 $HTTP_PORT 被占用: $LSOF_WHO。请先释放或改本脚本中的 HTTP_PORT"
fi
ok "端口 $HTTP_PORT 空闲"

# 必需文件检查
[[ -f "$SYNC_PY" ]] || fail "缺少 sync.py: $SYNC_PY"
[[ -f "$SYNC_SCRIPTS_DIR/export-on-stop.sh" ]] || fail "缺少 export-on-stop.sh"
[[ -f "$SYNC_SCRIPTS_DIR/import-on-start.sh" ]] || fail "缺少 import-on-start.sh"
ok "实施包文件完整"

# ============ 安装 mcp-memory-service ============
step "2/9 安装 mcp-memory-service"

if "$PYTHON" -c "import mcp_memory_service" 2>/dev/null; then
    INSTALLED_VER=$("$PYTHON" -c "import mcp_memory_service; print(mcp_memory_service._version.__version__)" 2>/dev/null || echo "unknown")
    ok "已安装 v$INSTALLED_VER"
else
    warn "首次安装：pip 会下载 torch/transformers/onnx 等，约 2-3GB。请保持网络畅通"

    if ! "$PYTHON" -m pip install --user "mcp-memory-service[sqlite]" 2>&1 | tee /tmp/pip-install.log; then
        if grep -q "externally-managed-environment" /tmp/pip-install.log; then
            warn "遇到 PEP 668。重试加 --break-system-packages"
            "$PYTHON" -m pip install --user --break-system-packages "mcp-memory-service[sqlite]" || fail "pip 安装失败"
        else
            fail "pip 安装失败，查看 /tmp/pip-install.log"
        fi
    fi
    ok "pip 安装完成"
fi

# 定位 memory CLI（主要用于 `memory server --http`，仍是唯一需要的 CLI 入口）
MEMORY_CLI="$(command -v memory 2>/dev/null || true)"
if [[ -z "$MEMORY_CLI" ]]; then
    USER_BIN="$("$PYTHON" -c 'import site; print(site.USER_BASE)' 2>/dev/null)/bin"
    [[ -x "$USER_BIN/memory" ]] && MEMORY_CLI="$USER_BIN/memory"
fi
[[ -n "$MEMORY_CLI" && -x "$MEMORY_CLI" ]] || fail "找不到 memory CLI。把 $USER_BIN 加入 PATH 后重跑"
ok "memory CLI: $MEMORY_CLI"

# ============ 创建数据目录 ============
step "3/9 本机专属数据目录"

mkdir -p "$APP_SUPPORT" "$LOG_DIR"
ok "$APP_SUPPORT"

# ============ LaunchAgent plist ============
step "4/9 写入 launchd 配置"

# 幂等：已存在先 unload（用新老两种语法）
if [[ -f "$LAUNCH_AGENT" ]]; then
    info "已有 LaunchAgent，先移除"
    launchctl bootout "gui/$(id -u)/$PLIST_LABEL" 2>/dev/null || \
        launchctl unload "$LAUNCH_AGENT" 2>/dev/null || true
    launchctl list | grep -q "$PLIST_LABEL" && launchctl remove "$PLIST_LABEL" 2>/dev/null || true
fi

mkdir -p "$(dirname "$LAUNCH_AGENT")"

# 构造代理环境段（仅当当前 shell 有代理时才加）
PROXY_ENV_BLOCK=""
if [[ -n "$SHELL_HTTP_PROXY" ]]; then
    PROXY_ENV_BLOCK+="
        <key>HTTP_PROXY</key>
        <string>$SHELL_HTTP_PROXY</string>"
fi
if [[ -n "$SHELL_HTTPS_PROXY" ]]; then
    PROXY_ENV_BLOCK+="
        <key>HTTPS_PROXY</key>
        <string>$SHELL_HTTPS_PROXY</string>"
fi
if [[ -n "$SHELL_HTTP_PROXY" || -n "$SHELL_HTTPS_PROXY" ]]; then
    PROXY_ENV_BLOCK+="
        <key>NO_PROXY</key>
        <string>localhost,127.0.0.1,::1</string>"
    info "检测到代理配置，写入 plist（launchd 启动时也走代理）"
fi

# 写 plist（标记回滚动作）
cat > "$LAUNCH_AGENT" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$PLIST_LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$MEMORY_CLI</string>
        <string>server</string>
        <string>--http</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$APP_SUPPORT</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$HOME/.local/bin</string>
        <key>HOME</key>
        <string>$HOME</string>
        <key>MCP_HTTP_HOST</key>
        <string>$HTTP_HOST</string>
        <key>MCP_HTTP_PORT</key>
        <string>$HTTP_PORT</string>
        <key>MCP_MEMORY_STORAGE_BACKEND</key>
        <string>sqlite_vec</string>
        <key>MCP_MEMORY_SQLITE_PRAGMAS</key>
        <string>journal_mode=WAL,busy_timeout=15000,cache_size=20000</string>
        <key>MCP_CONSOLIDATION_ENABLED</key>
        <string>true</string>
        <key>MCP_ALLOW_ANONYMOUS_ACCESS</key>
        <string>true</string>$PROXY_ENV_BLOCK
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <dict>
        <key>Crashed</key>
        <true/>
        <key>SuccessfulExit</key>
        <false/>
    </dict>
    <key>ThrottleInterval</key>
    <integer>30</integer>
    <key>StandardOutPath</key>
    <string>$LOG_DIR/mcp-memory-http-server.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/mcp-memory-http-server.err.log</string>
</dict>
</plist>
EOF
ROLLBACK_ACTIONS+=("rm -f \"$LAUNCH_AGENT\"")
ok "LaunchAgent: $LAUNCH_AGENT"

# ============ 加载并启动 ============
step "5/9 启动 HTTP server"

launchctl bootstrap "gui/$(id -u)" "$LAUNCH_AGENT" 2>/dev/null || \
    launchctl load "$LAUNCH_AGENT" || \
    fail "launchctl 加载失败，查看 $LOG_DIR/mcp-memory-http-server.err.log"
ROLLBACK_ACTIONS+=("launchctl bootout gui/$(id -u)/$PLIST_LABEL 2>/dev/null || launchctl unload \"$LAUNCH_AGENT\" 2>/dev/null")

sleep 3

# 健康检查 20 秒窗口
HEALTH_OK=0
for i in {1..10}; do
    if curl -sf --max-time 2 "http://$HTTP_HOST:$HTTP_PORT/api/health" >/dev/null 2>&1; then
        HEALTH_OK=1; break
    fi
    sleep 2
done

if [[ $HEALTH_OK -eq 1 ]]; then
    ok "HTTP server 就绪 http://$HTTP_HOST:$HTTP_PORT"
else
    warn "HTTP server 健康检查失败，但 LaunchAgent 已注册。查日志："
    warn "  tail -f $LOG_DIR/mcp-memory-http-server.log"
    warn "  tail -f $LOG_DIR/mcp-memory-http-server.err.log"
fi

# ============ 首次 import（C1 修复：改用 sync.py）============
step "6/9 检查记忆数据导入"

if [[ -f "$MEMORIES_JSON" ]]; then
    SIZE=$(wc -c < "$MEMORIES_JSON" | tr -d ' ')
    if [[ $SIZE -gt 30 ]]; then
        info "发现 memories.json ($SIZE bytes)，import 中..."
        if "$PYTHON" "$SYNC_PY" import --input "$MEMORIES_JSON"; then
            ok "Import 完成"
        else
            warn "Import 失败（非致命，可稍后手动跑: $PYTHON $SYNC_PY import --input $MEMORIES_JSON）"
        fi
    else
        info "memories.json 为空（首次安装正常）"
    fi
else
    info "memories.json 不存在（首次使用将在 SessionEnd 时创建）"
fi

# ============ 配置 .mcp.json（H1 修复：env 传参避免插值）============
step "7/9 Claude Code MCP 配置"

mkdir -p "$(dirname "$CC_MCP")"
[[ -f "$CC_MCP" ]] || printf '{"mcpServers": {}}\n' > "$CC_MCP"

PY_CFG_PATH="$CC_MCP" \
PY_MCP_URL="http://$HTTP_HOST:$HTTP_PORT/mcp" \
"$PYTHON" <<'PYEOF'
import os, json
from pathlib import Path
p = Path(os.environ["PY_CFG_PATH"])
cfg = json.loads(p.read_text(encoding="utf-8") or "{}")
cfg.setdefault("mcpServers", {})
cfg["mcpServers"]["mcp-memory"] = {
    "type": "http",
    "url": os.environ["PY_MCP_URL"],
}
p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
print("OK: mcp-memory 已写入", p)
PYEOF
ok ".mcp.json 已注册"

# ============ CC hooks（H1+H2 修复）============
step "8/9 CC SessionEnd / SessionStart hooks"

mkdir -p "$(dirname "$CC_CONFIG")"
[[ -f "$CC_CONFIG" ]] || printf '{}\n' > "$CC_CONFIG"

PY_CFG_PATH="$CC_CONFIG" \
PY_EXPORT_CMD="$SYNC_SCRIPTS_DIR/export-on-stop.sh" \
PY_IMPORT_CMD="$SYNC_SCRIPTS_DIR/import-on-start.sh" \
"$PYTHON" <<'PYEOF'
import os, json
from pathlib import Path
p = Path(os.environ["PY_CFG_PATH"])
cfg = json.loads(p.read_text(encoding="utf-8") or "{}")
cfg.setdefault("hooks", {})

def upsert(event, cmd):
    """幂等插入 hook：通过 command 里的脚本完整路径去重，不污染 hook 对象 schema"""
    arr = cfg["hooks"].setdefault(event, [])
    # 找出所有"嵌套 hooks 里 command == cmd"的条目，先删
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
    kept.append({
        "matcher": "*",
        "hooks": [{"type": "command", "command": cmd}],
    })
    cfg["hooks"][event] = kept

upsert("SessionEnd",   os.environ["PY_EXPORT_CMD"])
upsert("SessionStart", os.environ["PY_IMPORT_CMD"])
p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
print("OK: hooks 已注册")
PYEOF
ok "hooks 注册完成"

# ============ 完成 ============
step "9/9 安装完成"
ROLLBACK_ACTIONS=()  # 走到这一步清空回滚表，视为成功

# 用 echo 分段输出避免 heredoc 在 set -u 下对含中文变量展开的诡异行为
echo
echo -e "${C_GREEN}✓${C_RESET} mcp-memory-service 已装好"
echo
echo "下一步："
echo "  1. 重启 Claude Code（让 .mcp.json 生效）"
echo "  2. 在 CC 对话里验证：\"列出当前可用的 MCP 工具\""
echo "  3. Web Dashboard: http://${HTTP_HOST}:${HTTP_PORT}"
echo
echo "常用命令："
echo "  查看日志:       tail -f ${LOG_DIR}/mcp-memory-http-server.log"
echo "                 tail -f ${LOG_DIR}/mcp-memory-export.log"
echo "                 tail -f ${LOG_DIR}/mcp-memory-import.log"
echo "  重启服务:       launchctl unload ${LAUNCH_AGENT} && launchctl load ${LAUNCH_AGENT}"
echo "  停止服务:       launchctl unload ${LAUNCH_AGENT}"
echo "  手动 export:    ${PYTHON} ${SYNC_PY} export --output ${MEMORIES_JSON}"
echo "  手动 import:    ${PYTHON} ${SYNC_PY} import --input ${MEMORIES_JSON}"
echo "  查看记忆列表:   curl -s http://${HTTP_HOST}:${HTTP_PORT}/api/memories"
echo
echo "数据位置："
echo "  SQLite:         ${APP_SUPPORT}/"
echo "  memories.json:  ${MEMORIES_JSON}（坚果云实时同步）"
echo
