# 浏览界面（Plan 7）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** spec §4.3 #11 + §4.8 #30-32 落地——轻量本地 FastAPI Web Dashboard（127.0.0.1:<random> + token URL via stderr）+ textual digest TUI + Basic Memory schema 对齐。Web 仅浏览，TUI 接 digest approve/reject 主交互。

**Architecture:** `memoryd/src/memoryd/web/` 包 FastAPI app + Jinja2 templates + 内置 HTMX；`tui/digest.py` textual App；`schema.py` 加 4 个向后兼容字段。Sensitive scope 在 Web 一律 list 显 🔒、detail 403。

**Tech Stack:** Python 3.11+；新增依赖 `fastapi`, `uvicorn`, `textual`（合计 ~3MB 增量）。spec: `docs/superpowers/specs/2026-05-15-plan7-web-dashboard-design.md`。

**Decomposition Note:** 8 plan 中的第 7 个。上游 Plan 1-6 全 merged（de97325）。下游 Plan 8 旧记忆导入 + memory-searcher sub-agent。

---

## 文件结构

| 路径 | 责任 | 操作 |
|---|---|---|
| `memoryd/pyproject.toml` | 加 fastapi / uvicorn / textual | Modify |
| `memoryd/src/memoryd/web/__init__.py` | FastAPI app factory + token auth | Create |
| `memoryd/src/memoryd/web/routes.py` | 路由 handler | Create |
| `memoryd/src/memoryd/web/server.py` | uvicorn 启动 + port/token bootstrap | Create |
| `memoryd/src/memoryd/web/templates/*.html` | Jinja2 模板（7 个）| Create |
| `memoryd/src/memoryd/web/static/base.css` | 简洁灰阶样式 | Create |
| `memoryd/src/memoryd/web/static/htmx.min.js` | HTMX 1.9（内置） | Create |
| `memoryd/src/memoryd/tui/__init__.py` | textual app 入口 | Create |
| `memoryd/src/memoryd/tui/digest.py` | digest TUI App | Create |
| `memoryd/src/memoryd/schema.py` | 加 tags / category / observations 字段 | Modify |
| `memoryd/src/memoryd/cli.py` | 加 `web` 子命令 + `digest --tui` flag | Modify |
| `memoryd/tests/test_web_auth.py` | token middleware 测试 | Create |
| `memoryd/tests/test_web_routes.py` | 路由响应（200/401/403） | Create |
| `memoryd/tests/test_web_sensitive.py` | sensitive scope guard | Create |
| `memoryd/tests/test_tui_digest.py` | textual.testing 异步测试 | Create |
| `memoryd/tests/test_schema_basic_memory.py` | 新字段兼容 + 旧 .md load | Create |
| `memoryd/README.md` | 加 Web + TUI 章节 | Modify |
| `docs/superpowers/plans/2026-05-15-plan7-web-dashboard.execution-log.txt` | Phase 1 真机手册 | Create |

---

## 风险与不确定性

1. **fastapi + uvicorn 总大小**：fastapi 0.110 + uvicorn 0.27 + starlette ~3MB；对 v1 是可接受的（同 jinja2 / textual 都属现代标准）。pyproject 加进 `[project] dependencies`，本地 `uv pip install -e ".[dev]"` 自动拉。
2. **textual 终端兼容**：macOS Terminal / iTerm / Win Terminal 都支持；老 Win Console / Linux fb console 不行。文档建议 Windows Terminal。
3. **port=0 取派发**：`socket.socket().bind(("127.0.0.1", 0))` 后 `getsockname()[1]` 拿 OS 派发的 port。注意 socket 要在 uvicorn.run 之前 close（uvicorn 自己 bind）。
4. **Jinja2 autoescape**：默认 enable（avoid XSS in body that contains markdown）。
5. **sensitive scope 探测**：Web 加载 .md 前调 `scope_meta.is_path_sensitive(<file_path>)`，是则不读 body（仅显 placeholder）。
6. **新 schema fields 与 Plan 3 Frontmatter 已有 fields 冲突**：Plan 3 已有 `relations: list[str]`。Plan 7 不重复；只加新的 `tags / category / observations`。tests 必须 cover 旧 .md（无新字段）load 成功。
7. **textual.testing**：用 `pilot` 异步驱动；需 `pytest-asyncio`。或者拆分 logic 到不依赖 textual 的 reducer 单测，textual app 仅做 thin wrapper（推荐）。

---

## Task 1：Web server skeleton + token auth + /healthz

**Files:**
- Modify: `memoryd/pyproject.toml`（加 fastapi, uvicorn[standard]）
- Create: `memoryd/src/memoryd/web/__init__.py`
- Create: `memoryd/src/memoryd/web/server.py`
- Create: `memoryd/tests/test_web_auth.py`

### pyproject 依赖增量

```toml
dependencies = [
    # 既有...
    "fastapi>=0.110",
    "uvicorn[standard]>=0.27",
]
```

跑 `uv pip install -e ".[dev]"` 重装。

### `web/__init__.py`

```python
"""FastAPI app factory for memoryd browse-only dashboard."""
from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates


def _module_dir() -> Path:
    return Path(__file__).parent


def create_app(token: str, data_root: Path) -> FastAPI:
    """Create FastAPI app bound to the given token + data root."""
    app = FastAPI(title="memoryd web", docs_url=None, redoc_url=None)
    app.state.token = token
    app.state.data_root = data_root
    templates = Jinja2Templates(directory=str(_module_dir() / "templates"))
    app.state.templates = templates
    app.mount("/static", StaticFiles(directory=str(_module_dir() / "static")),
              name="static")

    @app.middleware("http")
    async def _check_token(request: Request, call_next):
        path = request.url.path
        if path == "/healthz" or path.startswith("/static"):
            return await call_next(request)
        supplied = (
            request.query_params.get("token")
            or request.cookies.get("memoryd_token")
            or (request.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
        )
        if not supplied or not secrets.compare_digest(supplied, app.state.token):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    return app
```

### `web/server.py`

```python
"""memoryd web CLI entry."""
from __future__ import annotations

import os
import secrets
import socket
import sys
import webbrowser
from pathlib import Path


def pick_free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def gen_token() -> str:
    return secrets.token_urlsafe(32)


def run(port: int | None = None, open_browser: bool = True) -> int:
    """Start uvicorn with random port + token; never returns until Ctrl+C."""
    import uvicorn
    from . import create_app
    p = port or pick_free_port()
    token = gen_token()
    data_root = Path(
        os.environ.get("MEMORYD_DATA_ROOT",
                       str(Path.home() / ".local" / "share" / "memoryd"))
    )
    app = create_app(token=token, data_root=data_root)
    url = f"http://127.0.0.1:{p}/?token={token}"
    print(f"memoryd web on {url}", file=sys.stderr, flush=True)
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    uvicorn.run(app, host="127.0.0.1", port=p, log_level="warning")
    return 0
```

### test_web_auth.py

```python
import secrets

import pytest
from fastapi.testclient import TestClient

from memoryd.web import create_app


@pytest.fixture
def app(tmp_path):
    return create_app(token="test-token-1234", data_root=tmp_path)


@pytest.fixture
def client(app):
    return TestClient(app)


def test_healthz_no_auth_required(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_root_requires_token(client):
    r = client.get("/")
    # 401 from middleware before any route would 404
    assert r.status_code == 401
    assert r.json() == {"error": "unauthorized"}


def test_root_accepts_token_query(client, app):
    # We haven't built / route yet (Task 2) → middleware should pass, route
    # itself may 404. The point is middleware returns past 401.
    r = client.get(f"/?token={app.state.token}")
    assert r.status_code != 401


def test_root_accepts_token_cookie(client, app):
    r = client.get("/", cookies={"memoryd_token": app.state.token})
    assert r.status_code != 401


def test_root_accepts_bearer_header(client, app):
    r = client.get(
        "/", headers={"Authorization": f"Bearer {app.state.token}"}
    )
    assert r.status_code != 401


def test_constant_time_compare(client, app):
    # Just verify wrong-length token still 401
    r = client.get("/?token=wrong")
    assert r.status_code == 401
```

### CLI wire-up（cli.py）

```python
p_web = subparsers.add_parser("web", help="launch local browse dashboard (FastAPI 127.0.0.1)")
p_web.add_argument("--port", type=int, default=None)
p_web.add_argument("--no-browser", action="store_true")
p_web.set_defaults(func=_cmd_web)


def _cmd_web(args):
    from .web.server import run
    return run(port=args.port, open_browser=not args.no_browser)
```

### Steps

- [ ] Step 1: 加 fastapi / uvicorn 到 pyproject + `uv pip install -e ".[dev]"`
- [ ] Step 2: 创建 `memoryd/src/memoryd/web/{__init__,server}.py`
- [ ] Step 3: 创建 `memoryd/src/memoryd/web/templates/` 和 `static/` 空目录（StaticFiles mount 需要存在）
- [ ] Step 4: 写 test_web_auth.py（6 测试）
- [ ] Step 5: cli.py 加 `web` 子命令
- [ ] Step 6: `cd memoryd && uv run pytest tests/test_web_auth.py -v`
- [ ] Step 7: 全套 ~256 passed
- [ ] Step 8: smoke：`cd memoryd && uv run memoryd web --no-browser &`, `curl http://127.0.0.1:<port>/healthz`, then kill
- [ ] Step 9: commit `plan7/task1: FastAPI web skeleton + token auth + healthz`

---

## Task 2：Web /memories list + detail + sensitive guard

**Files:**
- Create: `memoryd/src/memoryd/web/routes.py`
- Create: `memoryd/src/memoryd/web/templates/{base.html,index.html,list.html,detail.html}`
- Create: `memoryd/src/memoryd/web/static/base.css`
- Modify: `memoryd/src/memoryd/web/__init__.py` 接 routes
- Create: `memoryd/tests/test_web_routes.py`
- Create: `memoryd/tests/test_web_sensitive.py`

### `web/routes.py`

```python
"""Browse-only routes."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    templates = request.app.state.templates
    data_root = request.app.state.data_root
    recent = _recent(data_root, limit=20)
    return templates.TemplateResponse("index.html", {
        "request": request, "recent": recent, "token": request.app.state.token,
    })


@router.get("/memories", response_class=HTMLResponse)
async def list_memories(
    request: Request,
    type: str | None = None,
    scope: str | None = None,
    page: int = 1,
):
    data_root = request.app.state.data_root
    items = _list_memories(data_root, type=type, scope=scope, page=page)
    return request.app.state.templates.TemplateResponse(
        "list.html",
        {"request": request, "items": items, "type": type, "scope": scope,
         "page": page, "token": request.app.state.token},
    )


@router.get("/memories/{slug}", response_class=HTMLResponse)
async def detail(request: Request, slug: str):
    data_root = request.app.state.data_root
    info = _resolve_memory(data_root, slug)
    if info is None:
        raise HTTPException(404, detail="not found")
    if info["sensitive"]:
        raise HTTPException(403, detail="sensitive scope; use CLI")
    return request.app.state.templates.TemplateResponse(
        "detail.html",
        {"request": request, "memory": info, "token": request.app.state.token},
    )


# --- helpers ---

def _recent(data_root: Path, limit: int):
    """Return [{slug,type,scope_hash,title,sensitive}] sorted by created_at desc."""
    # 复用 Plan 1 storage.list_sessions + Plan 3 list_by_type 已有逻辑；
    # 简化版：扫 scopes/*/sessions+decisions+...的 .md（注意忽略 .md.enc 内容；只看 frontmatter 元数据
    # 但 frontmatter 是加密的——sensitive 用 scope_meta.is_path_sensitive 判断，不读 body）
    from memoryd.scope_meta import is_path_sensitive
    items = []
    scopes = data_root / "scopes"
    if not scopes.exists():
        return items
    for md in scopes.rglob("*.md"):
        parts = md.relative_to(scopes).parts
        if not parts or parts[-1].startswith("."):
            continue
        scope_hash = parts[0]
        type_ = parts[1] if len(parts) > 2 else "session"
        slug = md.stem
        sensitive = is_path_sensitive(md.parent)
        items.append({"slug": slug, "type": type_, "scope_hash": scope_hash,
                      "title": slug, "sensitive": sensitive,
                      "path": str(md)})
    items.sort(key=lambda x: x["slug"], reverse=True)
    return items[:limit]


def _list_memories(data_root: Path, *, type=None, scope=None, page=1, per_page=50):
    all_ = _recent(data_root, limit=10_000)
    if type:
        all_ = [x for x in all_ if x["type"] == type]
    if scope:
        all_ = [x for x in all_ if x["scope_hash"] == scope]
    start = (page - 1) * per_page
    return all_[start : start + per_page]


def _resolve_memory(data_root: Path, slug: str) -> dict | None:
    """Find a .md by slug across all scopes/types."""
    from memoryd.scope_meta import is_path_sensitive
    scopes = data_root / "scopes"
    if not scopes.exists():
        return None
    for md in scopes.rglob(f"{slug}.md"):
        sensitive = is_path_sensitive(md.parent)
        if sensitive:
            return {"slug": slug, "sensitive": True, "path": str(md)}
        text = md.read_text(encoding="utf-8")
        return {"slug": slug, "sensitive": False, "path": str(md),
                "body": text}
    return None
```

### `web/__init__.py` 末尾加：

```python
    from .routes import router
    app.include_router(router)
    return app
```

### templates/base.html

```html
<!doctype html>
<html><head>
<meta charset="utf-8">
<title>memoryd</title>
<link rel="stylesheet" href="/static/base.css">
<script src="/static/htmx.min.js"></script>
</head><body>
<header><a href="/?token={{ token }}">memoryd</a> ·
<a href="/memories?token={{ token }}">list</a> ·
<a href="/audit?token={{ token }}">audit</a> ·
<a href="/digest?token={{ token }}">digest</a></header>
<main>{% block content %}{% endblock %}</main>
</body></html>
```

### templates/index.html

```html
{% extends "base.html" %}
{% block content %}
<form hx-get="/search" hx-target="#results">
  <input name="q" placeholder="search…" hx-trigger="keyup changed delay:300ms">
  <input type="hidden" name="token" value="{{ token }}">
</form>
<div id="results"></div>
<h2>recent</h2>
<ul>
{% for item in recent %}
<li>{% if item.sensitive %}🔒{% else %}<a href="/memories/{{ item.slug }}?token={{ token }}">{% endif %}
[{{ item.type }}] {{ item.title }} <small>{{ item.scope_hash }}</small>
{% if not item.sensitive %}</a>{% endif %}
</li>
{% endfor %}
</ul>
{% endblock %}
```

### templates/list.html / detail.html / search_fragment.html

类似简洁结构。detail.html 若 `memory.sensitive` 显占位；否则 `<pre>{{ memory.body }}</pre>`。

### static/base.css

```css
body { font-family: -apple-system, monospace, monospace; background: #fafafa; color: #222; max-width: 900px; margin: 2em auto; padding: 0 1em; line-height: 1.4; }
header a { margin-right: 1em; color: #06f; text-decoration: none; }
ul { list-style: none; padding-left: 0; }
li { padding: 0.3em 0; border-bottom: 1px solid #eee; }
small { color: #888; }
pre { background: #fff; padding: 1em; border: 1px solid #ddd; white-space: pre-wrap; }
input[name="q"] { width: 100%; padding: 0.5em; font-size: 1em; }
```

### static/htmx.min.js

从 https://unpkg.com/htmx.org@1.9 拿 minified 文件（~14KB）。本地存。

### 测试：test_web_routes.py

```python
import pytest
from fastapi.testclient import TestClient

from memoryd.web import create_app


@pytest.fixture
def make_app(tmp_path):
    def _factory(*, data=None):
        return create_app(token="t", data_root=tmp_path), tmp_path
    return _factory


def _write_md(root, scope, type_, slug, body="x"):
    p = root / "scopes" / scope / type_ / f"{slug}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


def test_index_renders_with_token(make_app):
    app, root = make_app()
    _write_md(root, "h1", "sessions", "2026-05-15-hello")
    client = TestClient(app)
    r = client.get("/?token=t")
    assert r.status_code == 200
    assert "2026-05-15-hello" in r.text


def test_list_filters_by_type(make_app):
    app, root = make_app()
    _write_md(root, "h1", "sessions", "a")
    _write_md(root, "h1", "decisions", "b")
    client = TestClient(app)
    r = client.get("/memories?type=sessions&token=t")
    assert "a" in r.text
    assert "b" not in r.text


def test_detail_returns_body(make_app):
    app, root = make_app()
    _write_md(root, "h1", "sessions", "z", body="my body")
    client = TestClient(app)
    r = client.get("/memories/z?token=t")
    assert r.status_code == 200
    assert "my body" in r.text


def test_detail_404_unknown_slug(make_app):
    app, root = make_app()
    client = TestClient(app)
    r = client.get("/memories/missing?token=t")
    assert r.status_code == 404
```

### test_web_sensitive.py

```python
import pytest
from fastapi.testclient import TestClient

from memoryd.web import create_app


def _write_md(root, scope, type_, slug, body="x", sensitive=False):
    p = root / "scopes" / scope / type_ / f"{slug}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    if sensitive:
        (root / "scopes" / scope / ".memoryd-sensitive").write_text("scope_root: /x")
    return p


def test_list_shows_lock_for_sensitive(tmp_path):
    _write_md(tmp_path, "h1", "sessions", "a")
    _write_md(tmp_path, "h2", "sessions", "b", sensitive=True)
    client = TestClient(create_app(token="t", data_root=tmp_path))
    r = client.get("/?token=t")
    assert "🔒" in r.text


def test_detail_403_for_sensitive(tmp_path):
    _write_md(tmp_path, "h2", "sessions", "secret", body="secret data", sensitive=True)
    client = TestClient(create_app(token="t", data_root=tmp_path))
    r = client.get("/memories/secret?token=t")
    assert r.status_code == 403
    assert "secret data" not in r.text
```

### Steps

- [ ] Step 1-3: 写 routes.py + templates + static
- [ ] Step 4: 改 __init__.py 接 router
- [ ] Step 5: 4 routes test + 2 sensitive test
- [ ] Step 6: 全套 ~262 passed
- [ ] Step 7: commit `plan7/task2: web list + detail + sensitive guard + base templates`

---

## Task 3：Web /search + /audit + /digest

**Files:**
- Modify: `memoryd/src/memoryd/web/routes.py`
- Create: `memoryd/src/memoryd/web/templates/{search_fragment,audit,digest}.html`
- Modify: `memoryd/tests/test_web_routes.py` 增量

### routes.py 加：

```python
@router.get("/search", response_class=HTMLResponse)
async def search(request: Request, q: str = "", type: str | None = None):
    data_root = request.app.state.data_root
    if not q.strip():
        return HTMLResponse("<ul></ul>")
    from memoryd.search import search_sessions
    hits = search_sessions(data_root, q, limit=50)
    return request.app.state.templates.TemplateResponse(
        "search_fragment.html",
        {"request": request, "hits": hits, "token": request.app.state.token},
    )


@router.get("/audit", response_class=HTMLResponse)
async def audit(request: Request, scope: str | None = None,
                since: str | None = None, event_type: str | None = None):
    data_root = request.app.state.data_root
    entries = _read_audit(data_root, scope=scope, since=since,
                          event_type=event_type, limit=200)
    return request.app.state.templates.TemplateResponse(
        "audit.html",
        {"request": request, "entries": entries, "scope": scope, "since": since,
         "event_type": event_type, "token": request.app.state.token},
    )


@router.get("/digest", response_class=HTMLResponse)
async def digest(request: Request):
    data_root = request.app.state.data_root
    items = _list_pending_promotions(data_root)
    return request.app.state.templates.TemplateResponse(
        "digest.html",
        {"request": request, "items": items, "token": request.app.state.token},
    )


def _read_audit(data_root: Path, *, scope=None, since=None, event_type=None,
                limit=200):
    import json
    f = data_root / "audit" / "audit.jsonl"
    if not f.exists():
        return []
    entries = []
    for line in reversed(f.read_text("utf-8").splitlines()):
        if not line.strip(): continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        if scope and d.get("scope_hash") != scope: continue
        if since and d.get("ts", "") < since: continue
        if event_type and d.get("event_type") != event_type: continue
        entries.append(d)
        if len(entries) >= limit:
            break
    return entries


def _list_pending_promotions(data_root: Path):
    from memoryd.index import open_connection  # 现有 helper
    try:
        conn = open_connection(data_root)
    except Exception:
        return []
    try:
        rows = conn.execute(
            "SELECT id, source_session_slug, proposed_type, proposed_title, "
            "       reasoning, status FROM promotions WHERE status = 'pending' "
            "ORDER BY id DESC LIMIT 200"
        ).fetchall()
    except Exception:
        return []
    finally:
        conn.close()
    return [dict(zip(["id", "source_session_slug", "proposed_type",
                      "proposed_title", "reasoning", "status"], r))
            for r in rows]
```

### search_fragment.html

```html
<ul>
{% for hit in hits %}
<li><a href="/memories/{{ hit.slug }}?token={{ token }}">{{ hit.slug }}</a>
<small>{{ hit.excerpt }}</small></li>
{% endfor %}
</ul>
```

### audit.html / digest.html

简洁表格 / 列表。模板自由发挥但需含必要字段。

### 测试增量（test_web_routes.py）

```python
def test_search_returns_fragment(tmp_path):
    p = _write_md(tmp_path, "h1", "sessions", "abc",
                  body="---\nslug: abc\ntriggers: [foo]\n---\nbody mentions foo")
    client = TestClient(create_app(token="t", data_root=tmp_path))
    r = client.get("/search?q=foo&token=t")
    assert r.status_code == 200
    assert "abc" in r.text


def test_audit_empty(tmp_path):
    client = TestClient(create_app(token="t", data_root=tmp_path))
    r = client.get("/audit?token=t")
    assert r.status_code == 200


def test_audit_filters_scope(tmp_path):
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    (audit_dir / "audit.jsonl").write_text(
        '{"ts":"2026-05-01T00:00:00+00:00","scope_hash":"a","event_type":"access_granted"}\n'
        '{"ts":"2026-05-02T00:00:00+00:00","scope_hash":"b","event_type":"access_granted"}\n'
    )
    client = TestClient(create_app(token="t", data_root=tmp_path))
    r = client.get("/audit?scope=a&token=t")
    assert "a" in r.text


def test_digest_empty_no_db(tmp_path):
    client = TestClient(create_app(token="t", data_root=tmp_path))
    r = client.get("/digest?token=t")
    assert r.status_code == 200
```

### Steps

- [ ] 增量 routes.py + 3 templates
- [ ] 4 测试增量
- [ ] 全套 ~266 passed
- [ ] commit `plan7/task3: web search / audit / digest read-only`

---

## Task 4：textual TUI for digest（approve/reject/merge）

**Files:**
- Create: `memoryd/src/memoryd/tui/__init__.py`
- Create: `memoryd/src/memoryd/tui/digest.py`
- Modify: `memoryd/src/memoryd/cli.py` 加 `digest --tui` flag
- Create: `memoryd/tests/test_tui_digest.py`
- Modify: `memoryd/pyproject.toml` 加 textual + pytest-asyncio

### pyproject 增量

```toml
dependencies = [
    # ...
    "textual>=0.40",
]
[project.optional-dependencies]
dev = [
    # ...
    "pytest-asyncio>=0.23",
]
```

### `tui/digest.py`

```python
"""textual app for memoryd digest interactive审批."""
from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, ListView, ListItem, Label


class DigestApp(App):
    BINDINGS = [
        Binding("a", "approve_all", "Approve all"),
        Binding("r", "reject", "Reject"),
        Binding("m", "merge", "Merge"),
        Binding("s", "skip", "Skip"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, data_root, **kw):
        super().__init__(**kw)
        self.data_root = data_root

    def compose(self) -> ComposeResult:
        yield Header()
        yield ListView(id="promotions")
        yield Footer()

    def on_mount(self):
        self._load_pending()

    def _load_pending(self):
        # 调既有 list_promotions 拿 pending；填进 ListView
        from memoryd.governance.analyze import list_promotions  # 实际路径可能略异
        try:
            items = list_promotions(self.data_root, status="pending")
        except Exception:
            items = []
        lv = self.query_one("#promotions", ListView)
        lv.clear()
        for it in items:
            lv.append(ListItem(Label(f"[{it.get('proposed_type','?')}] "
                                     f"{it.get('proposed_title','')}")))

    def action_approve_all(self):
        from memoryd.governance.analyze import approve_promotion
        from memoryd.governance.analyze import list_promotions
        try:
            for it in list_promotions(self.data_root, status="pending"):
                approve_promotion(self.data_root, it["id"])
        except Exception as e:
            self.bell()
        self._load_pending()

    def action_reject(self):
        ...

    def action_merge(self):
        ...

    def action_skip(self):
        ...


def run_tui(data_root):
    DigestApp(data_root=data_root).run()
```

注意：`approve_promotion` / `list_promotions` 这些名字若 Plan 3 实际实现不同需对齐。先 grep Plan 3 现状（governance/analyze.py 或 governance/digest.py）。如果不存在，先在 plan 里补一个轻量 reducer 函数（不引入 textual 依赖），让 TUI 调它。

### cli.py 加 --tui flag

读现有 cmd_digest，加：

```python
p_digest.add_argument("--tui", action="store_true",
                     help="interactive textual TUI for approve/reject/merge")
```

cmd_digest 开头：

```python
def cmd_digest(args):
    if args.tui:
        from .tui.digest import run_tui
        from pathlib import Path
        run_tui(_data_root())
        return 0
    # ...既有 text/json 输出...
```

### test_tui_digest.py

textual.testing 模式比较复杂；可改用"reducer logic 单测"策略：把 approve/reject/merge 抽到 `tui/digest.py` 的非 textual 函数（`approve_all_pending(data_root)`），TUI 只 thin wrapper。然后单测 reducer：

```python
import pytest
from memoryd.tui.digest import approve_all_pending


@pytest.fixture
def stubbed_promotions(monkeypatch):
    calls = []
    def fake_list(*, status):
        return [{"id": 1, "proposed_type": "decision"},
                {"id": 2, "proposed_type": "fact"}]
    def fake_approve(_root, pid):
        calls.append(pid)
    monkeypatch.setattr("memoryd.tui.digest.list_promotions", fake_list)
    monkeypatch.setattr("memoryd.tui.digest.approve_promotion", fake_approve)
    return calls


def test_approve_all_pending_calls_each(tmp_path, stubbed_promotions):
    approve_all_pending(tmp_path)
    assert stubbed_promotions == [1, 2]
```

实施 implementer 需要先确认 Plan 3 既有 list_promotions / approve_promotion 函数；若没有 approve_promotion，可在 Plan 3 governance/analyze.py 顺手抽一个出来（按 spec 行为）。

### Steps

- [ ] Step 1: 加 textual + pytest-asyncio 到 pyproject
- [ ] Step 2: 先 grep Plan 3 既有 list_promotions / approve_promotion 行为；缺则补
- [ ] Step 3: 写 tui/digest.py（reducer + textual App）
- [ ] Step 4: cli.py 加 --tui
- [ ] Step 5: 写 test_tui_digest.py（≥ 2 个 reducer 测试 + smoke approve action）
- [ ] Step 6: 全套 ~270 passed
- [ ] Step 7: macOS smoke：`memoryd digest --tui` 启动 textual；按 q 退出（建议 implementer 用 echo "q" | timeout 5 ...）
- [ ] Step 8: commit `plan7/task4: textual digest TUI + approve_all_pending reducer`

---

## Task 5：Basic Memory schema 对齐

**Files:**
- Modify: `memoryd/src/memoryd/schema.py`
- Create: `memoryd/tests/test_schema_basic_memory.py`

读现有 `memoryd/src/memoryd/schema.py`，在 `Frontmatter` 类加：

```python
class Frontmatter(BaseModel):
    # ...既有字段...
    tags: list[str] = Field(default_factory=list)
    category: str | None = None
    observations: list[str] = Field(default_factory=list)
    # relations: list[str] 已存（Plan 3）；不重复
```

### test_schema_basic_memory.py

```python
from memoryd.schema import Frontmatter, SessionMemory


def test_frontmatter_accepts_new_fields():
    fm = Frontmatter(
        title="t", slug="s", scope_hash="h", triggers=["x"],
        source="claude-code", created_at="2026-05-15T00:00:00+00:00",
        tags=["important"],
        category="decisions/architecture",
        observations=["obs-1", "obs-2"],
    )
    assert fm.tags == ["important"]
    assert fm.category == "decisions/architecture"
    assert fm.observations == ["obs-1", "obs-2"]


def test_frontmatter_old_md_loads_without_new_fields():
    """Backward compat: Plan 1-6 已存 .md 没新字段，应仍能 parse."""
    fm = Frontmatter(
        title="t", slug="s", scope_hash="h", triggers=["x"],
        source="claude-code", created_at="2026-05-15T00:00:00+00:00",
    )
    assert fm.tags == []
    assert fm.category is None
    assert fm.observations == []


def test_session_memory_roundtrip_with_new_fields(tmp_path):
    """Save + load roundtrip should preserve new fields."""
    from memoryd.storage import save_session, load_session
    from memoryd.schema import SessionMemory
    s = SessionMemory(
        frontmatter=Frontmatter(
            title="t", slug="2026-05-15-test", scope_hash="abc",
            triggers=["x"], source="claude-code",
            created_at="2026-05-15T00:00:00+00:00",
            tags=["a"], category="cat", observations=["o1"],
        ),
        body="body",
    )
    path = save_session(tmp_path, s)
    loaded = load_session(path)
    assert loaded.frontmatter.tags == ["a"]
    assert loaded.frontmatter.category == "cat"
    assert loaded.frontmatter.observations == ["o1"]
```

### Steps

- [ ] 改 schema.py
- [ ] 3 测试
- [ ] 全套 ~273 passed
- [ ] commit `plan7/task5: Frontmatter 加 tags/category/observations（Basic Memory 对齐）`

---

## Task 6：README + execution-log + 收尾

**Files:**
- Modify: `memoryd/README.md`
- Create: `docs/superpowers/plans/2026-05-15-plan7-web-dashboard.execution-log.txt`

### README 加 "## Web dashboard + TUI (Plan 7)" 章节（在 Plan 6 之后）

包含：
- `memoryd web` 启动 + 复制 stderr URL 流程
- `memoryd digest --tui` 入口
- 安全模型：token 不持久化；重启换 token
- Sensitive scope 在 Web 看不到（用 CLI grant + show）
- Schema 加了 tags / category / observations（Basic Memory 对齐；纯 optional 加 field）
- Limitations：v1 仅浏览不可编辑 / 不支持 HTTPS / 不支持多用户

Status 升 v0.7.0。

### execution-log

Phase 1 用户手册：
- `memoryd web` 启动 → stderr URL → 浏览器粘贴 → 看 list / search / audit / digest
- `memoryd web --port=8088` 显式端口
- `memoryd digest --tui` 启动 textual UI → 体验 a/r/m/s/q
- 写一条带 `tags: [test]` 的 .md，验证 Web list 显示 + frontmatter 正确

### 完成判据校验

```
cd memoryd && uv run pytest 2>&1 | tail -10        # ≥ 273 passed
cd scripts/openclaw-memoryd-plugin && npm test     # 12 passed
cd memoryd && uv run memoryd web --no-browser &    # 真机启动
curl -s http://127.0.0.1:<port>/healthz             # {"status":"ok"}
kill %1
```

### commit + finishing-a-development-branch

```
git add memoryd/README.md docs/superpowers/plans/2026-05-15-plan7-web-dashboard.execution-log.txt
git commit -m "plan7/task6: README + execution log + Phase 1 用户手册

- README 加 Web dashboard + TUI 章节 + Status 升 v0.7.0
- execution-log Phase 1：memoryd web 启动 / digest --tui / Basic Memory schema

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

然后 finishing-a-development-branch → PR → auto-merge。
