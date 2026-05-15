---
title: 跨平台 + daemon 自启（Plan 5）设计
date: 2026-05-15
status: 已批准（light brainstorming：原生 GUI + 可选 SMTP）
related:
  - docs/superpowers/specs/2026-05-09-personal-usage-and-boundary-spec.md
  - docs/superpowers/specs/2026-05-14-sensitive-scopes-design.md
role: 设计文档——Plan 5 实施 plan 与 SDD 都引用本文档
---

# Plan 5：跨平台 + daemon 自启 设计

## 0. 这份文档是什么

Plan 1-4 在 macOS 上把整个 capture + 长期记忆 + 敏感作用域跑通了。spec §4.7 #27 要求 v1 同时支持 Mac + Win + Linux：自启 daemon、敏感作用域加密后端、SessionEnd hook 跨平台、digest 周期通知跨平台。Plan 5 把这些缺口补上。

Plan 5 不改 spec；不改 Plan 1-4 已交付的功能层；只加平台抽象 + 三平台具体实现。

## 1. 上游与硬约束（不要破）

| 已交付 | 状态 |
|---|---|
| Plan 4 macOS Keychain 加密 / grants / audit | merged `8ce76aa` + hotfixes |
| Plan 3 LLM provider / DURA / decay / digest | merged `4dac127` |
| launchd plist mirror daemon | install-launchd-mirror，real machine bootstrapped |
| `scripts/cc-session-end-hook.sh` | bash，macOS / Linux 可用，Windows 不可用 |

| 硬约束 | 来源 |
|---|---|
| MCP 工具数 ≤ 12（当前 8 used） | spec §3。本 plan **不加新 MCP 工具** |
| Markdown 是 source of truth；SQLite 只索引 | spec §3 |
| 不接管三端原生记忆机制 | spec §6 / §8 |
| 全本地——SMTP 是 spec §4.7 #24 允许的"用户主动调外部"，且本 plan 默认关闭 | spec §3 |
| 保留 macOS 既有路径不破坏 | Plan 1-4 |

## 2. 范围一览

| 子任务 | 当前状态 | Plan 5 |
|---|---|---|
| 加密 keychain 后端 | 仅 macOS Keychain | 三平台都走 `keyring` autobackend |
| 自启 daemon (mirror) | launchd | 加 systemd user / Win Task Scheduler |
| 自启 cron（decay-sweep / weekly digest） | 仅 macOS launchd 单条 | install-cron 子命令三平台 |
| CC SessionEnd hook | bash .sh | 加 Python .py（三平台通用主路）+ .ps1（Win 兜底）|
| Digest 通知 | macOS osascript | 三平台原生 GUI + 可选 SMTP |
| install 探测平台 | 手动 | `memoryd setup auto-install` |

## 3. 加密层跨平台

### 现状

`memoryd/src/memoryd/enc.py` 已经用 `keyring` PyPI 包，PyPI keyring 0.24+ 在三平台都有官方 backend：

| 平台 | keyring backend | 系统底层 |
|---|---|---|
| macOS | `keyring.backends.macOS.Keyring` | Keychain |
| Windows | `keyring.backends.Windows.WinVaultKeyring` | Windows Credential Manager（DPAPI 包装） |
| Linux | `keyring.backends.SecretService.Keyring` | gnome-keyring / KeePassXC secret-service |

keyring 会自动按平台选——`enc.py` 不需要改算法实现。Plan 5 只加一层 friendly fallback：

```python
def _check_backend_available() -> None:
    """Raise EncError with platform-specific install hint if no usable backend."""
```

Linux 上若用户没装 secret-service daemon（servers 常见），抛错引导：
- Debian/Ubuntu: `apt install gnome-keyring libsecret-tools`
- Fedora: `dnf install gnome-keyring`
- 或：装 KeePassXC 启用 Secret Service Integration

**不引入文件 fallback**（避免"假性加密"误导）。spec §4.5 #17 要求"解密钥匙本地 Keychain / DPAPI / Secret Service **各自适配**"，不允许 plain file 作为密钥本体。

### 测试策略

- macOS 真机 e2e（Plan 4 已有）
- Win / Linux 通过 mock keyring backend 单测——keyring 的 `set_password` / `get_password` 是稳定接口，AESGCM 在三平台行为一致

## 4. Cron 文件生成器

### 设计

新模块 `memoryd/src/memoryd/setup_cron.py`，按 platform.system() 分发：

| 平台 | 自启机制 | 模板位置 |
|---|---|---|
| macOS (Darwin) | launchd plist | `~/Library/LaunchAgents/com.memoryd.<job>.plist` |
| Linux | systemd user unit | `~/.config/systemd/user/memoryd-<job>.{service,timer}` |
| Windows | Task Scheduler XML | `%APPDATA%\memoryd\schtasks-<job>.xml` + `schtasks /create /xml` |

每个 job 两个文件：
- macOS：单 plist（StartCalendarInterval）
- Linux：`.service`（ExecStart memoryd <job>）+ `.timer`（OnCalendar ...）
- Windows：单 XML 走 schtasks

### CLI 接口

```
memoryd setup install-cron --decay        # daily 03:00 decay-sweep
memoryd setup install-cron --digest       # Mon 09:00 weekly digest --notify
memoryd setup install-cron --all          # both
memoryd setup uninstall-cron --decay
memoryd setup list-cron                   # 看现在装了哪些（解析 launchctl/systemctl/schtasks 输出）
```

### 跨平台 schedule 语义

| Job | macOS plist | systemd OnCalendar | Win XML schedule |
|---|---|---|---|
| decay-sweep | hour=3, minute=0 | `*-*-* 03:00:00` | DailyBoundary 03:00 |
| weekly-digest | weekday=2 (Mon), hour=9, minute=0 | `Mon *-*-* 09:00:00` | WeeklyBoundary Mon 09:00 |

用 dataclass `CronSchedule(hour, minute, weekday=None)` 抽掉差异，三个 platform render 各自模板。

## 5. 通知层

### `memoryd/src/memoryd/notify.py`

```python
def notify(title: str, body: str, *, config: NotifyConfig | None = None) -> None:
    """Best-effort cross-platform desktop + optional SMTP notify.

    - Native GUI: macOS osascript / Win PowerShell BurntToast 或 msg / Linux notify-send
    - 若 native 失败且 SMTP 配置完整 → 发邮件
    - native + SMTP 都失败 → 只写 log，不抛错
    """
```

各平台实现：
- **macOS**：`subprocess.run(["osascript", "-e", f'display notification "{body}" with title "{title}"'])`
- **Windows**：试 `powershell -Command "New-BurntToastNotification -Text '<title>','<body>'"`；失败 fallback `msg %username% <body>`；都失败仅 log
- **Linux**：试 `notify-send <title> <body>`；失败仅 log（headless 常见）

### 可选 SMTP

`~/.config/memoryd/config.toml` 加 section：

```toml
[notify.smtp]
enabled = false                    # 默认关
host = "smtp.example.com"
port = 587
use_tls = true
from = "memoryd@me.local"
to = "me@example.com"
username = ""
password_env = "MEMORYD_SMTP_PW"   # 不存密码本体，存 env 名（同 LLM api_key_env）
```

实现走 stdlib `smtplib.SMTP` + `email.message`。`enabled=true` 且 host/from/to 都填了才发；任一缺失静默跳过（log warning）。

`digest --notify` 调 `notify(title="memoryd weekly digest ready", body=...)`，同时走 GUI + SMTP；任一通路失败不阻塞另一个。

## 6. SessionEnd hook 跨平台

### 现状

`scripts/cc-session-end-hook.sh`：bash，2 行，调 `memoryd capture --client claude-code --transcript <path>`。

### 新增

- **`scripts/cc-session-end-hook.py`**：纯 Python，跨平台主路。读 `$CLAUDE_CODE_TRANSCRIPT_PATH` env / argv，调 `python -m memoryd capture ...`
- **`scripts/cc-session-end-hook.ps1`**：Windows PowerShell 兜底（如果用户 ~/.claude/settings.json 里习惯写 .ps1）

### CLI

```
memoryd setup install-cc-hook
  - detect platform
  - choose .py（默认）或 .ps1（Win 显式 --shell powershell）
  - read-mutate-write ~/.claude/settings.json hooks.SessionEnd
  - backup 到 ~/.claude/backups/
```

不删既有 `.sh`；macOS / Linux 用户可继续用 .sh。`.py` 是新机推荐主路。

## 7. install 平台探测

`memoryd setup auto-install`：

```
1. platform.system() → mac / linux / windows
2. install-cron --all
3. install-mirror-daemon（launchd / systemd / Task Scheduler）
4. install-cc-hook（Python wrapper）
5. 打印总结表：每一步成功/失败 + 文件路径
```

旧的 `install-launchd-mirror` 保留向后兼容；新增 `install-systemd-mirror` / `install-task-mirror`。

## 8. 文件结构

### 新建

```
memoryd/src/memoryd/
  notify.py                 # 三平台 GUI + SMTP
  setup_cron.py             # cron 抽象 + 三平台 render
  platforms/
    __init__.py             # detect() → "darwin" | "linux" | "windows"
    macos.py                # plist render / launchctl bootstrap
    linux.py                # systemd unit render / systemctl --user
    windows.py              # Task Scheduler XML + schtasks
  templates/
    systemd-mirror.service.j2
    systemd-decay.service.j2
    systemd-decay.timer.j2
    systemd-digest.service.j2
    systemd-digest.timer.j2
    windows-mirror.xml.j2
    windows-decay.xml.j2
    windows-digest.xml.j2

memoryd/tests/
  test_notify.py
  test_setup_cron.py
  test_platforms.py
  test_enc_cross_platform.py   # mock keyring backend

scripts/
  cc-session-end-hook.py
  cc-session-end-hook.ps1
```

### 修改

```
memoryd/pyproject.toml          # 加 jinja2（模板渲染），不再需要新增大依赖
memoryd/src/memoryd/enc.py      # _check_backend_available + friendly EncError
memoryd/src/memoryd/setup.py    # install-cron / uninstall-cron / install-cc-hook / auto-install
memoryd/src/memoryd/config.py   # NotifyConfig 模型 + [notify.smtp] section
memoryd/src/memoryd/governance/digest.py  # digest --notify 走 notify.notify()
memoryd/README.md               # 跨平台安装章节
```

## 9. 不在 Plan 5 内（边界）

| 不做 | 推迟到 |
|---|---|
| 多电脑同步（敏感密钥 / 记忆文件） | Plan 6 |
| Web Dashboard | Plan 7 |
| 旧记忆导入 / memory-searcher sub-agent | Plan 8 |
| BurntToast PowerShell 模块自动安装（require 用户 Install-Module） | v2 |
| 内嵌 SMTP server（用户必须有外部 SMTP） | v2 |

## 10. 风险与回退

| 风险 | 触发 | 回退 |
|---|---|---|
| keyring 在 Linux 找不到 backend | headless 服务器 | EncError 含安装指令；用户 mark-sensitive 直接失败，spec 允许 |
| BurntToast 未装 | 新 Win 机 | 自动降级 msg.exe；仍失败 → 只 log |
| systemd user mode 未启 | 老 Linux 系统 | 文档建议 `loginctl enable-linger <user>` 或 system-level fallback |
| Win schtasks 权限 | 非管理员 | user-level task 不需要管理员；若用户尝试系统级会报错并提示 |
| SMTP 凭证泄漏 | 用户把 password 写 config | 我们只读 `password_env`，不读 password 本体；config 出现 password 字段 → 拒绝启动并告警 |
| ~/.claude/settings.json 损坏 | install-cc-hook 写错 | 强制先 backup；写完用 json.load 校验，失败回滚 |

## 11. 完成判据

1. ✅ pytest 全绿（预期 161 + 新增 25+ ≈ 186 passed）
2. ✅ keyring 三平台 backend 由 mock 走通；macOS 真机 e2e（Plan 4 既有 sandbox cycle）继续过
3. ✅ install-cron --decay --digest --all 在 macOS 真机生成 plist 并被 launchctl bootstrap
4. ✅ install-cron 渲染出的 Linux systemd / Win XML 与 fixture 字节级匹配
5. ✅ digest --notify 在 macOS 真机出 osascript 桌面通知；SMTP 配置开后 fixtures 比对邮件体
6. ✅ cc-session-end-hook.py 在 macOS 替代 .sh 后 CC SessionEnd 仍正常 capture
7. ✅ auto-install 三平台 dry-run 走通（mock platform.system + mock subprocess）
8. ✅ MCP 工具数仍 8 / 12（不增不减）
9. ✅ Plan 1-4 测试无回归

## 12. 变更记录

| 日期 | 改了什么 | 为什么 |
|---|---|---|
| 2026-05-15 | 初版 | Plan 4 完成；上跨平台 |
