# 跨平台 + daemon 自启（Plan 5）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** spec §4.7 #27 三平台支持落地——把 Plan 4 的 macOS-only 加密、launchd 自启、osascript 通知、bash SessionEnd hook 全部扩到 Windows + Linux；增加 install-cron 子命令统一调度 decay-sweep / weekly-digest；digest 通知层支持原生 GUI + 可选 SMTP。

**Architecture:** 三层抽象——(1) `platforms/` 包按 `platform.system()` 选 macOS/Linux/Windows 三个实现；(2) `setup_cron.py` 用 `CronSchedule` dataclass + Jinja2 模板渲染三平台 cron 文件；(3) `notify.py` GUI + SMTP 双通路，任一通路失败不阻塞另一个。`enc.py` 不改算法，只加 friendly backend detection，让 `keyring` 自动选 backend。

**Tech Stack:** Python 3.11+；新增依赖 `jinja2`（模板渲染）；既有 `keyring>=24` 已经多平台。spec: `docs/superpowers/specs/2026-05-15-plan5-cross-platform-design.md`。

**Decomposition Note:** 8 plan 中的第 5 个。上游 Plan 1-4 全 merged（`9740a61` 之前）。下游 Plan 6 多电脑同步、Plan 7 Web Dashboard、Plan 8 旧记忆导入。

---

## 文件结构

| 路径 | 责任 | 操作 |
|---|---|---|
| `memoryd/pyproject.toml` | 加 `jinja2>=3.1` | Modify |
| `memoryd/src/memoryd/platforms/__init__.py` | `detect()` + `Platform` Literal + dispatch | Create |
| `memoryd/src/memoryd/platforms/macos.py` | plist render + launchctl bootstrap | Create |
| `memoryd/src/memoryd/platforms/linux.py` | systemd unit + systemctl --user | Create |
| `memoryd/src/memoryd/platforms/windows.py` | Task Scheduler XML + schtasks | Create |
| `memoryd/src/memoryd/templates/__init__.py` | Jinja2 env loader（package data） | Create |
| `memoryd/src/memoryd/templates/systemd-decay.service.j2` | systemd service unit | Create |
| `memoryd/src/memoryd/templates/systemd-decay.timer.j2` | systemd timer unit | Create |
| `memoryd/src/memoryd/templates/systemd-digest.service.j2` | systemd service unit | Create |
| `memoryd/src/memoryd/templates/systemd-digest.timer.j2` | systemd timer unit | Create |
| `memoryd/src/memoryd/templates/windows-decay.xml.j2` | Task Scheduler XML | Create |
| `memoryd/src/memoryd/templates/windows-digest.xml.j2` | Task Scheduler XML | Create |
| `memoryd/src/memoryd/templates/launchd-decay.plist.j2` | macOS plist | Create |
| `memoryd/src/memoryd/templates/launchd-digest.plist.j2` | macOS plist | Create |
| `memoryd/src/memoryd/setup_cron.py` | `CronSchedule` + `install_cron` / `uninstall_cron` / `list_cron` | Create |
| `memoryd/src/memoryd/enc.py` | `_check_backend_available` + friendly EncError | Modify |
| `memoryd/src/memoryd/notify.py` | `notify(title, body)` GUI + SMTP | Create |
| `memoryd/src/memoryd/config.py` | `NotifyConfig` + `[notify.smtp]` section | Modify |
| `memoryd/src/memoryd/setup.py` | install-cron / uninstall-cron / install-cc-hook / auto-install 函数 | Modify |
| `memoryd/src/memoryd/cli.py` | 加 5 个新子命令 wire-up | Modify |
| `memoryd/src/memoryd/governance/digest.py` | `digest --notify` 走 `notify.notify()` | Modify |
| `scripts/cc-session-end-hook.py` | 跨平台 Python wrapper | Create |
| `scripts/cc-session-end-hook.ps1` | Windows PowerShell wrapper | Create |
| `memoryd/tests/test_platforms.py` | detect + dispatch 测试 | Create |
| `memoryd/tests/test_setup_cron.py` | 三平台 render + roundtrip 测试 | Create |
| `memoryd/tests/test_notify.py` | GUI mock + SMTP mock | Create |
| `memoryd/tests/test_enc_cross_platform.py` | mock keyring backend 三平台 | Create |
| `memoryd/tests/test_setup_cross_platform.py` | install-cron CLI 集成 | Create |
| `memoryd/tests/fixtures/cron/` | render 字节级 fixture | Create |
| `memoryd/README.md` | 加 Cross-platform 章节 | Modify |
| `docs/superpowers/plans/2026-05-15-plan5-cross-platform.execution-log.txt` | Phase 1 用户手册 | Create |

---

## 风险与不确定性

1. **Jinja2 是新依赖**：之前 Plan 4 templates 是 f-string；Plan 5 跨平台模板太多用 f-string 会乱。Jinja2 是 Python 生态共识，小（240KB），添加是合理的。
2. **`keyring` Linux backend**：headless 服务器没有 secret-service daemon → `keyring.get_password()` 抛 `keyring.errors.NoKeyringError`。Task 1 把这个 catch 成 `EncError` 含安装指令；CI/单测用 `keyring.set_keyring(keyring.backends.fail.Keyring())` 强制 fail backend 测错误路径。
3. **schtasks XML 行尾**：Windows Task Scheduler 要 UTF-16 LE BOM；Jinja2 渲染默认 UTF-8。Task 4 渲染后用 `text.encode("utf-16")`（含 BOM）写文件。fixture 比对走 bytes。
4. **systemd user mode 在某些 Linux 不启**：老 Linux / Docker container 用 system mode。Plan 5 默认 user mode + 文档建议 `loginctl enable-linger`；不在 v1 自动切换。
5. **smtplib + Gmail/Office365**：现代 SMTP 要 OAuth2，spec §4.7 #24 允许"主动外发"但只想要简单 SMTP-with-password 用户场景。本 plan 仅支持 username/password + STARTTLS；OAuth2 推迟到 v2。
6. **测试 platform.system() mock**：用 `unittest.mock.patch("platform.system", return_value="Linux")` 即可，但要小心 module-level cache：把 `detect()` 实现成函数（每次调用 query），不要做 module 级 const。
7. **subprocess 在 mock 下**：Task 2/3 通知 + 安装 cron 都调 subprocess；mock 用 `monkeypatch.setattr("subprocess.run", fake_run)` 接 capture argv，不真 exec。

---

## Task 1：platforms/ + enc.py friendly backend check

**Files:**
- Create: `memoryd/src/memoryd/platforms/__init__.py`
- Modify: `memoryd/src/memoryd/enc.py`
- Create: `memoryd/tests/test_platforms.py`
- Create: `memoryd/tests/test_enc_cross_platform.py`

平台 detect + enc.py 加 backend friendly check（不改算法）。

### `platforms/__init__.py`

```python
"""Platform detection + dispatch.

Three supported: darwin (macOS), linux, windows. Anything else raises
UnsupportedPlatform when a platform-specific helper is invoked.
"""
from __future__ import annotations

import platform
from typing import Literal

PlatformName = Literal["darwin", "linux", "windows"]


class UnsupportedPlatform(Exception):
    """Raised when running on a platform memoryd does not support."""


def detect() -> PlatformName:
    """Return the current platform name as PlatformName."""
    name = platform.system().lower()
    if name == "darwin":
        return "darwin"
    if name == "linux":
        return "linux"
    if name == "windows":
        return "windows"
    raise UnsupportedPlatform(f"unsupported platform: {platform.system()}")


def is_macos() -> bool:
    return detect() == "darwin"


def is_linux() -> bool:
    return detect() == "linux"


def is_windows() -> bool:
    return detect() == "windows"
```

### `enc.py` 改造（加在文件末尾）

```python
def _check_backend_available() -> None:
    """Raise EncError with platform-specific install hint if no keyring backend."""
    kr = _keyring()
    backend = kr.get_keyring()
    # keyring.backends.fail.Keyring is the no-op fallback when nothing usable
    if backend.__class__.__module__.endswith(".fail"):
        from .platforms import detect
        plat = detect()
        if plat == "linux":
            hint = (
                "No usable keyring backend. Install one:\n"
                "  Debian/Ubuntu: sudo apt install gnome-keyring libsecret-tools\n"
                "  Fedora:        sudo dnf install gnome-keyring\n"
                "  Or install KeePassXC and enable Secret Service Integration."
            )
        elif plat == "windows":
            hint = "Windows Credential Manager unavailable — check user session not headless."
        else:
            hint = "macOS Keychain unavailable — unlock keychain and retry."
        raise EncError(hint)
```

`get_or_create_scope_key` 头部加一行 `_check_backend_available()`。

### Tests `test_platforms.py`

```python
from unittest.mock import patch

import pytest

from memoryd.platforms import (
    PlatformName,
    UnsupportedPlatform,
    detect,
    is_linux,
    is_macos,
    is_windows,
)


@pytest.mark.parametrize(
    "system,expected",
    [
        ("Darwin", "darwin"),
        ("Linux", "linux"),
        ("Windows", "windows"),
        ("darwin", "darwin"),
    ],
)
def test_detect_known_platforms(system, expected):
    with patch("platform.system", return_value=system):
        assert detect() == expected


def test_detect_unknown_raises():
    with patch("platform.system", return_value="Plan9"):
        with pytest.raises(UnsupportedPlatform):
            detect()


def test_helpers_dispatch():
    with patch("platform.system", return_value="Darwin"):
        assert is_macos() and not is_linux() and not is_windows()
    with patch("platform.system", return_value="Linux"):
        assert is_linux() and not is_macos() and not is_windows()
    with patch("platform.system", return_value="Windows"):
        assert is_windows() and not is_macos() and not is_linux()
```

### Tests `test_enc_cross_platform.py`

```python
from unittest.mock import patch

import keyring
import keyring.backend
import pytest

from memoryd import enc


class _FailKeyring(keyring.backend.KeyringBackend):
    """Marks itself with .fail module path to mimic fallback."""
    priority = -1
    @classmethod
    def get_priority(cls): return -1
    def get_password(self, service, account): return None
    def set_password(self, service, account, password): pass
    def delete_password(self, service, account): pass


def test_no_backend_raises_friendly_on_linux(monkeypatch):
    fail_kr = _FailKeyring()
    monkeypatch.setattr(keyring, "get_keyring", lambda: fail_kr)
    monkeypatch.setattr(fail_kr.__class__, "__module__", "keyring.backends.fail")
    monkeypatch.setattr("platform.system", lambda: "Linux")
    with pytest.raises(enc.EncError) as exc:
        enc._check_backend_available()
    assert "gnome-keyring" in str(exc.value)


def test_no_backend_raises_friendly_on_windows(monkeypatch):
    fail_kr = _FailKeyring()
    monkeypatch.setattr(keyring, "get_keyring", lambda: fail_kr)
    monkeypatch.setattr(fail_kr.__class__, "__module__", "keyring.backends.fail")
    monkeypatch.setattr("platform.system", lambda: "Windows")
    with pytest.raises(enc.EncError) as exc:
        enc._check_backend_available()
    assert "Windows Credential Manager" in str(exc.value)


def test_real_backend_does_not_raise(monkeypatch):
    """On the test machine (macOS) the real Keychain is available; this should not raise."""
    # 仅在 mac/linux 真有 backend 时跑；CI 上无所谓
    enc._check_backend_available()
```

### Steps

- [ ] **Step 1: Create platforms/__init__.py with detect/helpers**

写上面 platforms/__init__.py 全文。

- [ ] **Step 2: Write test_platforms.py and run RED**

```bash
cd memoryd && uv run pytest tests/test_platforms.py -v
```
Expected: PASS（platforms/__init__.py 已写）。

- [ ] **Step 3: Add `_check_backend_available` to enc.py + call it from `get_or_create_scope_key`**

- [ ] **Step 4: Write test_enc_cross_platform.py and run**

```bash
cd memoryd && uv run pytest tests/test_enc_cross_platform.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Verify full suite still green**

```bash
cd memoryd && uv run pytest -v 2>&1 | tail -10
```
Expected: 161 + 3 + ~3 = ~167 passed.

- [ ] **Step 6: Commit**

```bash
git add memoryd/src/memoryd/platforms/ memoryd/src/memoryd/enc.py memoryd/tests/test_platforms.py memoryd/tests/test_enc_cross_platform.py
git commit -m "$(cat <<'EOF'
plan5/task1: platforms module + enc backend friendly check

- platforms.detect() / is_macos/is_linux/is_windows
- enc._check_backend_available raises EncError with platform-specific install hint
- 3 new tests for platforms; 3 for enc fail-backend path
EOF
)"
```

---

## Task 2：notify.py + NotifyConfig

**Files:**
- Create: `memoryd/src/memoryd/notify.py`
- Modify: `memoryd/src/memoryd/config.py`
- Create: `memoryd/tests/test_notify.py`

GUI + SMTP 双通路。

### `notify.py`

```python
"""Cross-platform desktop notification + optional SMTP fallback.

`notify(title, body, config=None)` is best-effort:
- Try native GUI for the current platform.
- If SMTP config is enabled and complete, also send an email.
- Failures on either channel are logged but never raised.
"""
from __future__ import annotations

import logging
import os
import smtplib
import subprocess
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Optional

from .platforms import detect

log = logging.getLogger(__name__)


@dataclass
class SMTPConfig:
    enabled: bool = False
    host: str = ""
    port: int = 587
    use_tls: bool = True
    from_addr: str = ""
    to_addr: str = ""
    username: str = ""
    password_env: str = ""  # name of env var holding the password

    def is_complete(self) -> bool:
        return bool(
            self.enabled
            and self.host
            and self.from_addr
            and self.to_addr
        )


def notify(title: str, body: str, smtp: Optional[SMTPConfig] = None) -> None:
    """Best-effort dual-channel notify; never raises."""
    _notify_native(title, body)
    if smtp is not None and smtp.is_complete():
        _notify_smtp(title, body, smtp)


def _notify_native(title: str, body: str) -> None:
    try:
        plat = detect()
    except Exception:
        log.warning("notify: unknown platform, skipping native")
        return
    try:
        if plat == "darwin":
            script = f'display notification "{_esc(body)}" with title "{_esc(title)}"'
            subprocess.run(["osascript", "-e", script], check=False, timeout=5)
        elif plat == "linux":
            r = subprocess.run(
                ["notify-send", title, body], check=False, timeout=5
            )
            if r.returncode != 0:
                log.info("notify-send unavailable; skipping")
        elif plat == "windows":
            ps = (
                "try { "
                "Import-Module BurntToast -ErrorAction Stop; "
                f"New-BurntToastNotification -Text '{_esc(title)}','{_esc(body)}' "
                "} catch { "
                f"msg * /TIME:60 '{_esc(title)}: {_esc(body)}' "
                "}"
            )
            subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                          check=False, timeout=10)
    except Exception as e:
        log.warning("notify native failed: %s", e)


def _notify_smtp(title: str, body: str, c: SMTPConfig) -> None:
    try:
        password = os.environ.get(c.password_env, "") if c.password_env else ""
        msg = EmailMessage()
        msg["Subject"] = title
        msg["From"] = c.from_addr
        msg["To"] = c.to_addr
        msg.set_content(body)
        with smtplib.SMTP(c.host, c.port, timeout=15) as s:
            if c.use_tls:
                s.starttls()
            if c.username and password:
                s.login(c.username, password)
            s.send_message(msg)
    except Exception as e:
        log.warning("notify smtp failed: %s", e)


def _esc(s: str) -> str:
    """Escape shell single-quotes / AppleScript double-quotes."""
    return s.replace("'", "'\\''").replace('"', '\\"')
```

### `config.py` 加 NotifyConfig section

读 spec §5；config.py 现有 `LLMConfig`，按相同模式：

```python
# 加到 config.py 现有 dataclass 集合后
@dataclass
class NotifyConfig:
    smtp: SMTPConfig = field(default_factory=SMTPConfig)


# load_config 改造：从 toml 读 [notify.smtp]
```

具体改 config.py 时按现有 `_load_llm` 模式加 `_load_notify(data: dict) -> NotifyConfig`。`from .notify import SMTPConfig` 避免循环（notify.py 不引 config）。

### Tests `test_notify.py`

```python
from unittest.mock import MagicMock, patch

import pytest

from memoryd.notify import SMTPConfig, _notify_native, _notify_smtp, notify


def test_smtp_config_is_complete_requires_all():
    assert not SMTPConfig().is_complete()
    c = SMTPConfig(enabled=True, host="h", from_addr="a@b", to_addr="c@d")
    assert c.is_complete()
    assert not SMTPConfig(enabled=False, host="h", from_addr="a", to_addr="b").is_complete()


def test_native_macos_invokes_osascript(monkeypatch):
    run = MagicMock()
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    monkeypatch.setattr("subprocess.run", run)
    _notify_native("hello", "world")
    run.assert_called_once()
    args = run.call_args.args[0]
    assert args[0] == "osascript"
    assert "world" in args[-1]
    assert "hello" in args[-1]


def test_native_linux_invokes_notify_send(monkeypatch):
    run = MagicMock(return_value=MagicMock(returncode=0))
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr("subprocess.run", run)
    _notify_native("t", "b")
    args = run.call_args.args[0]
    assert args == ["notify-send", "t", "b"]


def test_native_windows_uses_powershell(monkeypatch):
    run = MagicMock()
    monkeypatch.setattr("platform.system", lambda: "Windows")
    monkeypatch.setattr("subprocess.run", run)
    _notify_native("t", "b")
    args = run.call_args.args[0]
    assert args[0] == "powershell"
    assert "BurntToast" in args[-1]


def test_native_swallows_errors(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    monkeypatch.setattr("subprocess.run", MagicMock(side_effect=RuntimeError("boom")))
    # must not raise
    _notify_native("t", "b")


def test_smtp_sends(monkeypatch):
    smtp_inst = MagicMock()
    smtp_class = MagicMock(return_value=smtp_inst)
    smtp_inst.__enter__ = MagicMock(return_value=smtp_inst)
    smtp_inst.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr("smtplib.SMTP", smtp_class)
    cfg = SMTPConfig(enabled=True, host="smtp.x", port=587, use_tls=True,
                     from_addr="me@x", to_addr="you@y",
                     username="u", password_env="PW")
    monkeypatch.setenv("PW", "secret")
    _notify_smtp("t", "b", cfg)
    smtp_inst.starttls.assert_called_once()
    smtp_inst.login.assert_called_once_with("u", "secret")
    smtp_inst.send_message.assert_called_once()


def test_smtp_swallows_errors(monkeypatch):
    monkeypatch.setattr("smtplib.SMTP", MagicMock(side_effect=ConnectionRefusedError()))
    cfg = SMTPConfig(enabled=True, host="x", from_addr="a", to_addr="b")
    # must not raise
    _notify_smtp("t", "b", cfg)


def test_notify_dispatches_both(monkeypatch):
    monkeypatch.setattr("memoryd.notify._notify_native", MagicMock())
    smtp = MagicMock()
    monkeypatch.setattr("memoryd.notify._notify_smtp", smtp)
    cfg = SMTPConfig(enabled=True, host="x", from_addr="a", to_addr="b")
    notify("t", "b", cfg)
    smtp.assert_called_once()


def test_notify_skips_smtp_when_disabled(monkeypatch):
    monkeypatch.setattr("memoryd.notify._notify_native", MagicMock())
    smtp = MagicMock()
    monkeypatch.setattr("memoryd.notify._notify_smtp", smtp)
    cfg = SMTPConfig(enabled=False)
    notify("t", "b", cfg)
    smtp.assert_not_called()
```

### Steps

- [ ] **Step 1: Write notify.py**

- [ ] **Step 2: Write test_notify.py and run**

```bash
cd memoryd && uv run pytest tests/test_notify.py -v
```
Expected: all pass.

- [ ] **Step 3: Add NotifyConfig section to config.py**

读 `memoryd/src/memoryd/config.py` 确认现有 `LLMConfig` 风格；按相同模式加 `_load_notify` + `NotifyConfig` 包装 `SMTPConfig`。

- [ ] **Step 4: Add config.py test snippets to test_config.py**

加 `test_load_notify_smtp_section`：写 toml `[notify.smtp] host="x" from="a" to="b" enabled=true` 然后 load，验证字段读到位。

- [ ] **Step 5: Run full suite**

```bash
cd memoryd && uv run pytest -v 2>&1 | tail -10
```
Expected: prev + ~9 notify + 1 config = ~177 passed.

- [ ] **Step 6: Commit**

```bash
git add memoryd/src/memoryd/notify.py memoryd/src/memoryd/config.py memoryd/tests/test_notify.py memoryd/tests/test_config.py
git commit -m "$(cat <<'EOF'
plan5/task2: notify module + NotifyConfig

- notify.py 双通路：原生 GUI（osascript / notify-send / powershell+BurntToast 兜底 msg）+ 可选 SMTP
- config.py [notify.smtp] section
- 失败两路都不抛错，只 log warning
EOF
)"
```

---

## Task 3：模板 + setup_cron + 三平台实现

**Files:**
- Create: `memoryd/src/memoryd/templates/__init__.py`
- Create: `memoryd/src/memoryd/templates/*.j2`（8 个模板）
- Create: `memoryd/src/memoryd/platforms/{macos,linux,windows}.py`
- Create: `memoryd/src/memoryd/setup_cron.py`
- Create: `memoryd/tests/test_setup_cron.py`
- Create: `memoryd/tests/fixtures/cron/*`
- Modify: `memoryd/pyproject.toml`（加 jinja2 依赖 + package-data 包含 templates）

跨平台 cron 文件渲染。

### `pyproject.toml` 依赖增量

```toml
[project]
dependencies = [
  # ... existing ...
  "jinja2>=3.1",
]

[tool.hatch.build.targets.wheel.force-include]
"src/memoryd/templates" = "memoryd/templates"
```

（具体 build backend 看现状；用 `tool.setuptools.package-data` 也行）

### `templates/__init__.py`

```python
"""Jinja2 environment for cron / unit / plist templates packaged with memoryd."""
from __future__ import annotations

from importlib.resources import files
from pathlib import Path

from jinja2 import Environment, FileSystemLoader


def _template_dir() -> Path:
    return Path(str(files("memoryd").joinpath("templates")))


def render(template_name: str, **ctx) -> str:
    env = Environment(
        loader=FileSystemLoader(_template_dir()),
        keep_trailing_newline=True,
        autoescape=False,
    )
    return env.get_template(template_name).render(**ctx)
```

### 模板 `launchd-decay.plist.j2`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{{ label }}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{{ memoryd_bin }}</string>
    <string>decay-sweep</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key><integer>{{ hour }}</integer>
    <key>Minute</key><integer>{{ minute }}</integer>
  </dict>
  <key>StandardOutPath</key><string>{{ log_dir }}/{{ label }}.out.log</string>
  <key>StandardErrorPath</key><string>{{ log_dir }}/{{ label }}.err.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>MEMORYD_DATA_ROOT</key><string>{{ data_root }}</string>
  </dict>
</dict>
</plist>
```

### 模板 `launchd-digest.plist.j2`

与 decay 类似，但 `ProgramArguments` 是 `[memoryd_bin, "digest", "--notify"]`，`StartCalendarInterval` 多一个 `<key>Weekday</key><integer>{{ weekday }}</integer>`。

### 模板 `systemd-decay.service.j2`

```ini
[Unit]
Description=memoryd daily decay sweep
After=default.target

[Service]
Type=oneshot
ExecStart={{ memoryd_bin }} decay-sweep
Environment="MEMORYD_DATA_ROOT={{ data_root }}"
StandardOutput=append:{{ log_dir }}/{{ label }}.out.log
StandardError=append:{{ log_dir }}/{{ label }}.err.log
```

### 模板 `systemd-decay.timer.j2`

```ini
[Unit]
Description=memoryd daily decay timer

[Timer]
OnCalendar=*-*-* {{ "%02d:%02d:00" | format(hour, minute) }}
Persistent=true

[Install]
WantedBy=timers.target
```

### 模板 `systemd-digest.service.j2`

类似 decay，ExecStart 改 `digest --notify`。

### 模板 `systemd-digest.timer.j2`

```ini
[Unit]
Description=memoryd weekly digest timer

[Timer]
OnCalendar=Mon *-*-* {{ "%02d:%02d:00" | format(hour, minute) }}
Persistent=true

[Install]
WantedBy=timers.target
```

### 模板 `windows-decay.xml.j2`

```xml
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>memoryd daily decay sweep</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>2026-05-15T{{ "%02d:%02d:00" | format(hour, minute) }}</StartBoundary>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
      <Enabled>true</Enabled>
    </CalendarTrigger>
  </Triggers>
  <Actions Context="Author">
    <Exec>
      <Command>{{ memoryd_bin }}</Command>
      <Arguments>decay-sweep</Arguments>
    </Exec>
  </Actions>
  <Settings>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
  </Settings>
</Task>
```

### 模板 `windows-digest.xml.j2`

CalendarTrigger 改 `<ScheduleByWeek><WeeksInterval>1</WeeksInterval><DaysOfWeek><Monday/></DaysOfWeek></ScheduleByWeek>`；Arguments 改 `digest --notify`。

### `platforms/macos.py`

```python
"""macOS launchd helpers for cron-style jobs."""
from __future__ import annotations

import subprocess
from pathlib import Path

from ..templates import render


def launch_agents_dir() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def install_plist(template: str, label: str, *, ctx: dict) -> Path:
    text = render(template, label=label, **ctx)
    out = launch_agents_dir() / f"{label}.plist"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return out


def bootstrap(label: str) -> None:
    """Best-effort launchctl bootstrap."""
    plist = launch_agents_dir() / f"{label}.plist"
    uid = subprocess.check_output(["id", "-u"]).decode().strip()
    subprocess.run(["launchctl", "bootout", f"gui/{uid}/{label}"],
                   capture_output=True, check=False)
    subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(plist)],
                   check=True)


def uninstall(label: str) -> None:
    plist = launch_agents_dir() / f"{label}.plist"
    uid = subprocess.check_output(["id", "-u"]).decode().strip()
    subprocess.run(["launchctl", "bootout", f"gui/{uid}/{label}"],
                   capture_output=True, check=False)
    if plist.exists():
        plist.unlink()
```

### `platforms/linux.py`

```python
"""Linux systemd user unit helpers."""
from __future__ import annotations

import subprocess
from pathlib import Path

from ..templates import render


def units_dir() -> Path:
    return Path.home() / ".config" / "systemd" / "user"


def install_units(service_template: str, timer_template: str, label: str,
                  *, ctx: dict) -> tuple[Path, Path]:
    units_dir().mkdir(parents=True, exist_ok=True)
    svc = units_dir() / f"{label}.service"
    tmr = units_dir() / f"{label}.timer"
    svc.write_text(render(service_template, label=label, **ctx), encoding="utf-8")
    tmr.write_text(render(timer_template, label=label, **ctx), encoding="utf-8")
    return svc, tmr


def enable_timer(label: str) -> None:
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", f"{label}.timer"],
                   check=True)


def uninstall(label: str) -> None:
    subprocess.run(["systemctl", "--user", "disable", "--now", f"{label}.timer"],
                   capture_output=True, check=False)
    for suffix in (".timer", ".service"):
        f = units_dir() / f"{label}{suffix}"
        if f.exists():
            f.unlink()
    subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True, check=False)
```

### `platforms/windows.py`

```python
"""Windows Task Scheduler helpers."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from ..templates import render


def task_xml_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "memoryd"


def install_task(template: str, label: str, *, ctx: dict) -> Path:
    task_xml_dir().mkdir(parents=True, exist_ok=True)
    xml = render(template, label=label, **ctx)
    out = task_xml_dir() / f"{label}.xml"
    # Task Scheduler requires UTF-16 LE BOM
    out.write_bytes(b"\xff\xfe" + xml.encode("utf-16-le"))
    return out


def register_task(label: str) -> None:
    xml = task_xml_dir() / f"{label}.xml"
    subprocess.run(
        ["schtasks", "/Create", "/TN", label, "/XML", str(xml), "/F"],
        check=True,
    )


def uninstall(label: str) -> None:
    subprocess.run(["schtasks", "/Delete", "/TN", label, "/F"],
                   capture_output=True, check=False)
    xml = task_xml_dir() / f"{label}.xml"
    if xml.exists():
        xml.unlink()
```

### `setup_cron.py`

```python
"""Cross-platform cron-style job install / uninstall.

Two job kinds:
- decay-sweep: daily at 03:00
- weekly-digest: Monday 09:00 (with --notify)
"""
from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from . import platforms


@dataclass
class CronSchedule:
    hour: int
    minute: int
    weekday: int | None = None  # 0=Sun … 6=Sat (launchd numbering); None for daily

    def to_systemd_oncalendar(self) -> str:
        if self.weekday is None:
            return f"*-*-* {self.hour:02d}:{self.minute:02d}:00"
        names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        return f"{names[self.weekday]} *-*-* {self.hour:02d}:{self.minute:02d}:00"


_JOBS = {
    "decay": {
        "label": "com.memoryd.decay-sweep",
        "schedule": CronSchedule(hour=3, minute=0),
        "macos_template": "launchd-decay.plist.j2",
        "linux_service": "systemd-decay.service.j2",
        "linux_timer": "systemd-decay.timer.j2",
        "windows_template": "windows-decay.xml.j2",
    },
    "digest": {
        "label": "com.memoryd.weekly-digest",
        "schedule": CronSchedule(hour=9, minute=0, weekday=1),  # Mon
        "macos_template": "launchd-digest.plist.j2",
        "linux_service": "systemd-digest.service.j2",
        "linux_timer": "systemd-digest.timer.j2",
        "windows_template": "windows-digest.xml.j2",
    },
}


def _ctx(job_key: str) -> dict:
    spec = _JOBS[job_key]
    sch = spec["schedule"]
    bin_path = shutil.which("memoryd") or sys.executable
    data_root = os.environ.get(
        "MEMORYD_DATA_ROOT", str(Path.home() / ".local" / "share" / "memoryd")
    )
    log_dir = str(Path(data_root) / "logs")
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    ctx = dict(
        memoryd_bin=bin_path,
        data_root=data_root,
        log_dir=log_dir,
        hour=sch.hour,
        minute=sch.minute,
    )
    if sch.weekday is not None:
        ctx["weekday"] = sch.weekday
    return ctx


def install(job_key: str, *, register: bool = True) -> Path | tuple[Path, Path]:
    if job_key not in _JOBS:
        raise ValueError(f"unknown job: {job_key}")
    spec = _JOBS[job_key]
    label = spec["label"]
    ctx = _ctx(job_key)
    plat = platforms.detect()
    if plat == "darwin":
        from .platforms import macos
        path = macos.install_plist(spec["macos_template"], label, ctx=ctx)
        if register:
            macos.bootstrap(label)
        return path
    if plat == "linux":
        from .platforms import linux
        svc, tmr = linux.install_units(
            spec["linux_service"], spec["linux_timer"], label, ctx=ctx
        )
        if register:
            linux.enable_timer(label)
        return svc, tmr
    if plat == "windows":
        from .platforms import windows
        xml = windows.install_task(spec["windows_template"], label, ctx=ctx)
        if register:
            windows.register_task(label)
        return xml


def uninstall(job_key: str) -> None:
    spec = _JOBS[job_key]
    label = spec["label"]
    plat = platforms.detect()
    if plat == "darwin":
        from .platforms import macos
        macos.uninstall(label)
    elif plat == "linux":
        from .platforms import linux
        linux.uninstall(label)
    elif plat == "windows":
        from .platforms import windows
        windows.uninstall(label)
```

### Tests `test_setup_cron.py`

```python
from unittest.mock import MagicMock, patch

import pytest

from memoryd.setup_cron import CronSchedule, _JOBS, _ctx, install, uninstall
from memoryd.templates import render


def test_cron_schedule_systemd_daily():
    assert CronSchedule(3, 0).to_systemd_oncalendar() == "*-*-* 03:00:00"


def test_cron_schedule_systemd_weekly_monday():
    assert CronSchedule(9, 0, weekday=1).to_systemd_oncalendar() == "Mon *-*-* 09:00:00"


def test_render_launchd_decay_contains_hour():
    out = render(
        "launchd-decay.plist.j2",
        label="com.memoryd.decay-sweep",
        memoryd_bin="/usr/bin/memoryd",
        data_root="/tmp/d",
        log_dir="/tmp/d/logs",
        hour=3,
        minute=0,
    )
    assert "<integer>3</integer>" in out
    assert "decay-sweep" in out
    assert "com.memoryd.decay-sweep" in out


def test_render_launchd_digest_contains_weekday():
    out = render(
        "launchd-digest.plist.j2",
        label="com.memoryd.weekly-digest",
        memoryd_bin="/usr/bin/memoryd",
        data_root="/tmp/d",
        log_dir="/tmp/d/logs",
        hour=9,
        minute=0,
        weekday=1,
    )
    assert "<integer>1</integer>" in out
    assert "digest" in out
    assert "--notify" in out


def test_render_systemd_timer_daily_oncalendar():
    out = render(
        "systemd-decay.timer.j2",
        label="com.memoryd.decay-sweep",
        hour=3, minute=0,
    )
    assert "OnCalendar=*-*-* 03:00:00" in out


def test_render_systemd_digest_timer_monday():
    out = render(
        "systemd-digest.timer.j2",
        label="com.memoryd.weekly-digest",
        hour=9, minute=0,
    )
    assert "OnCalendar=Mon *-*-* 09:00:00" in out


def test_render_windows_decay_daily():
    out = render(
        "windows-decay.xml.j2",
        label="com.memoryd.decay-sweep",
        memoryd_bin="C:\\memoryd\\memoryd.exe",
        data_root="C:\\m",
        log_dir="C:\\m\\logs",
        hour=3, minute=0,
    )
    assert "ScheduleByDay" in out
    assert "T03:00:00" in out


def test_render_windows_digest_weekly_monday():
    out = render(
        "windows-digest.xml.j2",
        label="com.memoryd.weekly-digest",
        memoryd_bin="C:\\memoryd\\memoryd.exe",
        data_root="C:\\m",
        log_dir="C:\\m\\logs",
        hour=9, minute=0,
        weekday=1,
    )
    assert "ScheduleByWeek" in out
    assert "Monday" in out
    assert "--notify" in out


def test_install_macos_writes_plist_and_bootstraps(monkeypatch, tmp_path):
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    fake_run = MagicMock(return_value=MagicMock(returncode=0, stdout=b"500"))
    fake_co = MagicMock(return_value=b"500\n")
    monkeypatch.setattr("subprocess.check_output", fake_co)
    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr("shutil.which", lambda _: "/usr/local/bin/memoryd")
    out = install("decay")
    assert out.exists()
    assert "com.memoryd.decay-sweep.plist" in str(out)
    # bootstrap called
    assert any("bootstrap" in (" ".join(c.args[0]) if isinstance(c.args[0], list) else "")
               for c in fake_run.call_args_list)


def test_install_linux_writes_units_and_enables(monkeypatch, tmp_path):
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    fake_run = MagicMock(return_value=MagicMock(returncode=0))
    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/memoryd")
    out = install("digest")
    svc, tmr = out
    assert svc.exists() and tmr.exists()
    assert "weekly-digest.service" in svc.name
    assert "weekly-digest.timer" in tmr.name


def test_install_windows_writes_xml_utf16(monkeypatch, tmp_path):
    monkeypatch.setattr("platform.system", lambda: "Windows")
    monkeypatch.setattr("os.environ", {**dict(__import__("os").environ), "APPDATA": str(tmp_path)})
    fake_run = MagicMock(return_value=MagicMock(returncode=0))
    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr("shutil.which", lambda _: "C:\\memoryd.exe")
    out = install("decay")
    assert out.exists()
    head = out.read_bytes()[:2]
    assert head == b"\xff\xfe"  # UTF-16 LE BOM
```

### Steps

- [ ] **Step 1: Add jinja2 to pyproject.toml + reinstall**

```bash
cd memoryd && uv pip install -e ".[dev]"
```

- [ ] **Step 2: Create 8 .j2 templates + templates/__init__.py**

- [ ] **Step 3: Create platforms/{macos,linux,windows}.py**

- [ ] **Step 4: Create setup_cron.py**

- [ ] **Step 5: Write test_setup_cron.py and run**

```bash
cd memoryd && uv run pytest tests/test_setup_cron.py -v
```
Expected: 11 passed.

- [ ] **Step 6: Run full suite**

```bash
cd memoryd && uv run pytest -v 2>&1 | tail -10
```
Expected: prev + 11 ≈ 188 passed.

- [ ] **Step 7: macOS real-machine smoke test**

```bash
cd memoryd && uv run python -c "from memoryd.setup_cron import install; print(install('decay', register=False))"
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.memoryd.decay-sweep.plist
launchctl print gui/$(id -u)/com.memoryd.decay-sweep | head
launchctl bootout gui/$(id -u)/com.memoryd.decay-sweep
rm ~/Library/LaunchAgents/com.memoryd.decay-sweep.plist
```

- [ ] **Step 8: Commit**

```bash
git add memoryd/pyproject.toml memoryd/src/memoryd/templates/ memoryd/src/memoryd/platforms/ memoryd/src/memoryd/setup_cron.py memoryd/tests/test_setup_cron.py
git commit -m "$(cat <<'EOF'
plan5/task3: cron templates + platform dispatch + setup_cron

- jinja2 templates: launchd plist / systemd service+timer / Win Task XML
- platforms/{macos,linux,windows}.py：install + register/uninstall
- setup_cron.install(job_key) 三平台分发
- CronSchedule dataclass 抽 systemd OnCalendar 表达
- 11 new tests
EOF
)"
```

---

## Task 4：CLI 子命令 + cc-session-end-hook 跨平台 + digest --notify

**Files:**
- Modify: `memoryd/src/memoryd/setup.py`
- Modify: `memoryd/src/memoryd/cli.py`
- Modify: `memoryd/src/memoryd/governance/digest.py`
- Create: `scripts/cc-session-end-hook.py`
- Create: `scripts/cc-session-end-hook.ps1`
- Create: `memoryd/tests/test_setup_cross_platform.py`

### `setup.py` 新函数

加 5 个：

```python
def install_cron(job_key: str) -> Path | tuple[Path, Path]:
    from .setup_cron import install
    return install(job_key)


def uninstall_cron(job_key: str) -> None:
    from .setup_cron import uninstall
    return uninstall(job_key)


def install_cc_hook(target_settings: Path | None = None) -> Path:
    """Wire scripts/cc-session-end-hook.py into ~/.claude/settings.json hooks.SessionEnd."""
    import json
    from .platforms import detect
    settings = target_settings or (Path.home() / ".claude" / "settings.json")
    backup_file(settings)
    repo_root = Path(__file__).resolve().parents[3]
    plat = detect()
    if plat == "windows":
        hook_path = repo_root / "scripts" / "cc-session-end-hook.ps1"
        cmd = f"powershell -NoProfile -ExecutionPolicy Bypass -File \"{hook_path}\""
    else:
        hook_path = repo_root / "scripts" / "cc-session-end-hook.py"
        cmd = f"python3 \"{hook_path}\""
    data = json.loads(settings.read_text("utf-8")) if settings.exists() else {}
    hooks = data.setdefault("hooks", {})
    session_end = hooks.setdefault("SessionEnd", [])
    # remove any prior matcher==* entry that points to our hook
    session_end[:] = [
        m for m in session_end
        if not (m.get("matcher") == "*"
                and any("cc-session-end-hook" in (h.get("command") or "")
                        for h in m.get("hooks", [])))
    ]
    session_end.append({
        "matcher": "*",
        "hooks": [{"type": "command", "command": cmd}],
    })
    settings.write_text(json.dumps(data, indent=2, ensure_ascii=False), "utf-8")
    return settings


def auto_install() -> dict:
    """Detect platform, install daemon + cron + cc-hook; return per-step results."""
    from .platforms import detect
    plat = detect()
    results = {"platform": plat}
    try:
        results["decay_cron"] = str(install_cron("decay"))
    except Exception as e:
        results["decay_cron_error"] = str(e)
    try:
        results["digest_cron"] = str(install_cron("digest"))
    except Exception as e:
        results["digest_cron_error"] = str(e)
    try:
        results["cc_hook"] = str(install_cc_hook())
    except Exception as e:
        results["cc_hook_error"] = str(e)
    return results
```

### `cli.py` 子命令 wire-up

加 argparse 入口：

```python
# setup install-cron
sp_install_cron = sp_setup.add_parser("install-cron")
sp_install_cron.add_argument("--decay", action="store_true")
sp_install_cron.add_argument("--digest", action="store_true")
sp_install_cron.add_argument("--all", action="store_true")

# setup uninstall-cron --decay/--digest/--all
sp_un_cron = sp_setup.add_parser("uninstall-cron")
sp_un_cron.add_argument("--decay", action="store_true")
sp_un_cron.add_argument("--digest", action="store_true")
sp_un_cron.add_argument("--all", action="store_true")

# setup install-cc-hook
sp_setup.add_parser("install-cc-hook")

# setup auto-install
sp_setup.add_parser("auto-install")
```

dispatch:

```python
elif args.setup_cmd == "install-cron":
    keys = []
    if args.all or args.decay: keys.append("decay")
    if args.all or args.digest: keys.append("digest")
    for k in keys:
        out = install_cron(k)
        print(f"installed {k}: {out}")
elif args.setup_cmd == "uninstall-cron":
    keys = []
    if args.all or args.decay: keys.append("decay")
    if args.all or args.digest: keys.append("digest")
    for k in keys:
        uninstall_cron(k)
        print(f"uninstalled {k}")
elif args.setup_cmd == "install-cc-hook":
    out = install_cc_hook()
    print(f"wired CC SessionEnd hook in {out}")
elif args.setup_cmd == "auto-install":
    import json
    print(json.dumps(auto_install(), indent=2))
```

### `governance/digest.py` --notify flag

读现有 `digest` CLI entry：现状大概是 `def cmd_digest(args)`。加：

```python
def cmd_digest(args):
    ...生成 digest 内容（已有）...
    if getattr(args, "notify", False):
        from ..notify import notify
        from ..config import load_config
        cfg = load_config()
        body = _render_digest_summary(...)  # 用已有函数
        notify("memoryd weekly digest ready", body, cfg.notify.smtp)
```

### `scripts/cc-session-end-hook.py`

```python
#!/usr/bin/env python3
"""Cross-platform Claude Code SessionEnd hook for memoryd.

Reads CLAUDE_CODE_TRANSCRIPT_PATH (or first argv) and invokes
`memoryd capture --client claude-code --transcript <path>`.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys


def main() -> int:
    path = os.environ.get("CLAUDE_CODE_TRANSCRIPT_PATH") or (
        sys.argv[1] if len(sys.argv) > 1 else ""
    )
    if not path:
        return 0  # nothing to capture
    memoryd_bin = shutil.which("memoryd") or "memoryd"
    cmd = [memoryd_bin, "capture", "--client", "claude-code",
           "--transcript", path]
    try:
        subprocess.run(cmd, check=False, timeout=30)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

### `scripts/cc-session-end-hook.ps1`

```powershell
# Claude Code SessionEnd hook (Windows PowerShell)
$transcript = $env:CLAUDE_CODE_TRANSCRIPT_PATH
if (-not $transcript -and $args.Count -gt 0) { $transcript = $args[0] }
if (-not $transcript) { exit 0 }

$memoryd = (Get-Command memoryd -ErrorAction SilentlyContinue).Source
if (-not $memoryd) { $memoryd = "memoryd" }

try {
    & $memoryd capture --client claude-code --transcript $transcript 2>&1 | Out-Null
} catch {
    # best-effort; never block CC
}
exit 0
```

### Tests `test_setup_cross_platform.py`

```python
import json
from unittest.mock import MagicMock, patch

import pytest

from memoryd.setup import (
    auto_install,
    install_cc_hook,
    install_cron,
    uninstall_cron,
)


def test_install_cron_macos_invokes_setup_cron(monkeypatch, tmp_path):
    fake = MagicMock(return_value=tmp_path / "plist")
    monkeypatch.setattr("memoryd.setup_cron.install", fake)
    out = install_cron("decay")
    fake.assert_called_once_with("decay")
    assert out == tmp_path / "plist"


def test_uninstall_cron_delegates(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr("memoryd.setup_cron.uninstall", fake)
    uninstall_cron("digest")
    fake.assert_called_once_with("digest")


def test_install_cc_hook_writes_settings_macos(monkeypatch, tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"hooks": {}}))
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    install_cc_hook(target_settings=settings)
    data = json.loads(settings.read_text())
    se = data["hooks"]["SessionEnd"]
    assert len(se) == 1
    assert "cc-session-end-hook.py" in se[0]["hooks"][0]["command"]


def test_install_cc_hook_uses_ps1_on_windows(monkeypatch, tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text("{}")
    monkeypatch.setattr("platform.system", lambda: "Windows")
    install_cc_hook(target_settings=settings)
    data = json.loads(settings.read_text())
    cmd = data["hooks"]["SessionEnd"][0]["hooks"][0]["command"]
    assert "cc-session-end-hook.ps1" in cmd
    assert "powershell" in cmd


def test_install_cc_hook_replaces_prior_entry(monkeypatch, tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({
        "hooks": {
            "SessionEnd": [{
                "matcher": "*",
                "hooks": [{"type": "command",
                           "command": "/old/cc-session-end-hook.sh"}],
            }]
        }
    }))
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    install_cc_hook(target_settings=settings)
    data = json.loads(settings.read_text())
    # only one entry now, pointing at our wrapper
    assert len(data["hooks"]["SessionEnd"]) == 1


def test_auto_install_returns_results(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    monkeypatch.setattr("memoryd.setup.install_cron",
                        MagicMock(return_value="/tmp/x.plist"))
    monkeypatch.setattr("memoryd.setup.install_cc_hook",
                        MagicMock(return_value="/tmp/settings.json"))
    out = auto_install()
    assert out["platform"] == "darwin"
    assert "decay_cron" in out
    assert "digest_cron" in out
    assert "cc_hook" in out


def test_auto_install_records_errors(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Linux")
    def boom(*_): raise RuntimeError("no systemd")
    monkeypatch.setattr("memoryd.setup.install_cron", boom)
    monkeypatch.setattr("memoryd.setup.install_cc_hook",
                        MagicMock(return_value="/tmp/s.json"))
    out = auto_install()
    assert "decay_cron_error" in out
    assert "no systemd" in out["decay_cron_error"]
```

### Steps

- [ ] **Step 1: Implement setup.py new functions**

- [ ] **Step 2: Wire cli.py subcommands**

- [ ] **Step 3: Add --notify flag to digest CLI + digest.py callsite**

- [ ] **Step 4: Create scripts/cc-session-end-hook.py + .ps1**

```bash
chmod +x scripts/cc-session-end-hook.py
```

- [ ] **Step 5: Write test_setup_cross_platform.py and run**

```bash
cd memoryd && uv run pytest tests/test_setup_cross_platform.py -v
```
Expected: 7 passed.

- [ ] **Step 6: Full suite**

```bash
cd memoryd && uv run pytest -v 2>&1 | tail -10
```
Expected: prev + 7 ≈ 195 passed.

- [ ] **Step 7: macOS real-machine cc-hook swap test**

```bash
# 1. backup 当前 settings
cp ~/.claude/settings.json ~/.claude/settings.json.bak-plan5
# 2. install
cd memoryd && uv run memoryd setup install-cc-hook
# 3. 比对 .sh → .py
diff <(jq '.hooks.SessionEnd' ~/.claude/settings.json) <(jq '.hooks.SessionEnd' ~/.claude/settings.json.bak-plan5)
# 4. restore（暂时）
cp ~/.claude/settings.json.bak-plan5 ~/.claude/settings.json
```

(Phase 1 用户手册里会让用户实际切到 .py 再实跑一轮 CC SessionEnd。)

- [ ] **Step 8: Commit**

```bash
git add memoryd/src/memoryd/setup.py memoryd/src/memoryd/cli.py memoryd/src/memoryd/governance/digest.py scripts/cc-session-end-hook.py scripts/cc-session-end-hook.ps1 memoryd/tests/test_setup_cross_platform.py
git commit -m "$(cat <<'EOF'
plan5/task4: CLI subcommands + cross-platform CC hook + digest --notify

- memoryd setup install-cron --decay/--digest/--all
- memoryd setup install-cc-hook (auto Python on mac/linux, PowerShell on Win)
- memoryd setup auto-install (one-shot platform-aware)
- digest --notify → notify.notify() with native GUI + optional SMTP
- scripts/cc-session-end-hook.py (cross-platform) + .ps1 (Win fallback)
- 7 new tests
EOF
)"
```

---

## Task 5：README + execution log + 完成判据校验

**Files:**
- Modify: `memoryd/README.md`
- Create: `docs/superpowers/plans/2026-05-15-plan5-cross-platform.execution-log.txt`

### README 加章节

在现有 Plan 4 之后插：

```markdown
## Cross-platform install (Plan 5)

memoryd v0.5.0 起 macOS / Linux / Windows 三平台都可用。
- 加密：keyring 自动选 backend（Keychain / Credential Manager / Secret Service）
- Daemon 自启：launchd / systemd user / Task Scheduler
- Digest 通知：原生 GUI + 可选 SMTP

### One-shot install

```bash
memoryd setup auto-install
```

会按平台依次：
- 装 cron（decay 03:00 daily + weekly digest Mon 09:00）
- 写 CC SessionEnd hook（Python wrapper）

### Granular control

```bash
memoryd setup install-cron --decay
memoryd setup install-cron --digest
memoryd setup install-cron --all
memoryd setup install-cc-hook
```

### 反操作

```bash
memoryd setup uninstall-cron --all
```

### SMTP digest（可选）

`~/.config/memoryd/config.toml`：

```toml
[notify.smtp]
enabled = true
host = "smtp.gmail.com"
port = 587
use_tls = true
from = "you@gmail.com"
to = "you@gmail.com"
username = "you@gmail.com"
password_env = "MEMORYD_SMTP_PW"
```

`export MEMORYD_SMTP_PW=<app-password>` 后 digest --notify 同时发邮件。

### Limitations

- Linux：需 secret-service daemon（gnome-keyring / KeePassXC）
- Windows：BurntToast 未装时降级 msg.exe
- 老 Linux systemd：可能需 `loginctl enable-linger <user>` 让 user timer 在登录前跑
```

### Execution log

```
# Plan 5 Phase 1 用户手册（cross-platform install + cc-hook swap）

## 1. install-cron --all（macOS 实测）

memoryd setup install-cron --all
ls -la ~/Library/LaunchAgents/com.memoryd.*.plist
launchctl print gui/$(id -u)/com.memoryd.decay-sweep | head
launchctl print gui/$(id -u)/com.memoryd.weekly-digest | head

## 2. cc-session-end-hook 切到 .py

cp ~/.claude/settings.json ~/.claude/settings.json.before-plan5
memoryd setup install-cc-hook
diff <(jq '.hooks.SessionEnd' ~/.claude/settings.json) <(jq '.hooks.SessionEnd' ~/.claude/settings.json.before-plan5)
# 跑一次 CC turn，确认 source=claude-code 的 .md 仍正常生成
find ~/.local/share/memoryd/scopes -newer /tmp -name "*.md" -ls

## 3. digest --notify 实测（macOS）

memoryd digest --notify
# 屏幕右上角应出现 osascript 通知

## 4. SMTP 可选实测

# 用户配 [notify.smtp] 后再跑 digest --notify，查收件箱
```

### Steps

- [ ] **Step 1: README 加 Cross-platform 章节**

- [ ] **Step 2: 写 execution-log.txt（Phase 1 用户手册）**

- [ ] **Step 3: Full suite 最终校验**

```bash
cd memoryd && uv run pytest -v 2>&1 | tail -15
```
Expected: ≥ 186 passed.

- [ ] **Step 4: OpenClaw plugin 测试无回归**

```bash
cd scripts/openclaw-memoryd-plugin && npm test 2>&1 | tail -5
```
Expected: 12 passed.

- [ ] **Step 5: 最终 commit**

```bash
git add memoryd/README.md docs/superpowers/plans/2026-05-15-plan5-cross-platform.execution-log.txt
git commit -m "$(cat <<'EOF'
plan5/task5: README + execution log + Phase 1 用户手册

- README 加 Cross-platform install 章节
- execution-log.txt 记录 install-cron / cc-hook swap / digest --notify 真机步骤
EOF
)"
```

- [ ] **Step 6: finishing-a-development-branch**

调用 `superpowers:finishing-a-development-branch` skill，开 PR 回 main，auto-merge。

---

## 完成判据

1. ✅ pytest 全绿（≥ 186 passed）
2. ✅ npm test 全绿（12 passed，OpenClaw plugin 无回归）
3. ✅ Plan 1-4 测试集合无 fail（在前一项之内自然成立）
4. ✅ macOS 真机：install-cron --all → launchctl print 看到 decay-sweep + weekly-digest，bootstrap 成功
5. ✅ macOS 真机：digest --notify → 出 osascript 通知
6. ✅ macOS 真机：install-cc-hook → ~/.claude/settings.json hooks.SessionEnd 切到 .py wrapper
7. ✅ Win / Linux 模板渲染走 fixture 字节级比对（unit test 等价 of real machine 验证）
8. ✅ MCP 工具数仍 8 / 12（未增）
9. ✅ jinja2 是新依赖；现 pip install -e .[dev] 一次后能用
10. ✅ README + execution-log 写完
