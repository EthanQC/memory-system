# Plan 9: CLI search/list/show/delete/promote 子命令补缺

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** spec §4.3 #9 硬要求的 6 个 CLI 子命令里现只交付了 `merge`，补齐剩余 5 个：`search` / `list` / `show` / `delete` / `promote`。

**Architecture:** 5 个 CLI 子命令都直接复用既有 modules：
- `search` → `memoryd.search.search_sessions` + 优化输出
- `list` → 扫 SQLite memories 表（Plan 3）+ filter type/scope/limit
- `show` → `storage.load_session` + frontmatter 渲染；sensitive 走 grant check
- `delete` → 删 `.md` / `.md.enc` + SQLite DELETE + 同时 unindex；sensitive 走 grant check
- `promote` → 调 governance.analyze.approve_promotion + 真写 long-term .md（之前 Plan 7 Task 4 只 flip status，未真写文件）

**Tech Stack:** Python 3.11+；无新依赖。补 spec: `docs/superpowers/specs/2026-05-09-personal-usage-and-boundary-spec.md` §4.3 #9。

**Decomposition Note:** Plan 9 = v1 收尾补缺。上游 Plan 1-8 全 merged（8f3d081）。

---

## 文件结构

| 路径 | 责任 | 操作 |
|---|---|---|
| `memoryd/src/memoryd/cli.py` | 5 个 `cmd_*` + subparser wire | Modify |
| `memoryd/src/memoryd/governance/analyze.py` | `approve_promotion` 加真写 .md（不只 flip status） | Modify |
| `memoryd/tests/test_cli_query.py` | search / list / show 测试 | Create |
| `memoryd/tests/test_cli_mutate.py` | delete / promote 测试 | Create |
| `memoryd/README.md` | "## Manual control CLI (Plan 9)" 章节 | Modify |
| `docs/superpowers/plans/2026-05-16-plan9-cli-readwrite-commands.execution-log.txt` | Phase 1 真机手册 | Create |

---

## 风险与不确定性

1. **`delete` + sensitive**：删 sensitive scope 文件要走 grant check（Plan 4 既有 gate.check_or_raise）。CLI 走 `MEMORYD_AUTH_INTERACTIVE=1` 直接 prompt 用户；不交互模式 raise AuthorizationRequired。
2. **`promote` 真写 .md**：Plan 7 Task 4 `approve_promotion` 只 flip SQLite status；Plan 9 改成 flip status **+** 调 `record_long_term` 等价逻辑真写文件到 decisions/preferences/facts/playbooks/warnings 目录。需 promotions 表里有 `proposed_body` / `proposed_triggers` / `proposed_type` 字段；先 grep 确认 schema。
3. **`search` 输出**：CLI 上既能 human-readable table 也能 `--json`。默认 table。
4. **`list` 排序**：按 `created_at` desc；`--limit=N` 默认 50。
5. **`delete` confirmation**：默认 prompt y/N；`--force` 跳过。CI / 测试用 `--force`。
6. **slug ambiguity**：search/show/delete 用 slug 直接匹配；多 scope 同 slug 时按 scope_hash 优先 cwd-derived；不命中再 cross-scope。

---

## Task 1：CLI search + list + show（读类）

**Files:**
- Modify: `memoryd/src/memoryd/cli.py`
- Create: `memoryd/tests/test_cli_query.py`

### cli.py 增量

```python
# search
p_search = subparsers.add_parser("search",
    help="full-text search across memories (matches search_memory MCP tool)")
p_search.add_argument("query")
p_search.add_argument("--scope", default=None)
p_search.add_argument("--type", default=None,
                     dest="type_", help="filter by memoryd type")
p_search.add_argument("--limit", type=int, default=20)
p_search.add_argument("--json", action="store_true", dest="as_json")
p_search.set_defaults(func=cmd_search)


def cmd_search(args):
    from .search import search_sessions
    data_root = _data_root()
    hits = search_sessions(data_root, args.query, limit=args.limit)
    # 二次过滤（search_sessions 当前没 type 参数；CLI 层 filter）
    if args.scope:
        hits = [h for h in hits if h.get("scope_hash") == args.scope]
    if args.type_:
        hits = [h for h in hits if h.get("type") == args.type_]
    if args.as_json:
        import json
        print(json.dumps(hits, indent=2, ensure_ascii=False, default=str))
    else:
        if not hits:
            print("no hits", file=sys.stderr)
            return 0
        for h in hits[: args.limit]:
            print(f"{h.get('slug','?'):40} [{h.get('type','?'):10}] "
                  f"{h.get('scope_hash','?'):14} {h.get('excerpt','')[:80]}")
    return 0


# list
p_list = subparsers.add_parser("list",
    help="list memories filtered by type / scope")
p_list.add_argument("--type", default=None, dest="type_")
p_list.add_argument("--scope", default=None)
p_list.add_argument("--limit", type=int, default=50)
p_list.add_argument("--json", action="store_true", dest="as_json")
p_list.set_defaults(func=cmd_list)


def cmd_list(args):
    data_root = _data_root()
    rows = _list_memories(data_root, type_=args.type_,
                         scope_hash=args.scope, limit=args.limit)
    if args.as_json:
        import json
        print(json.dumps(rows, indent=2, ensure_ascii=False, default=str))
    else:
        if not rows:
            print("no memories", file=sys.stderr)
            return 0
        for r in rows:
            print(f"{r['slug']:40} [{r['type']:10}] {r['scope_hash']:14} "
                  f"{r.get('created_at','')}")
    return 0


def _list_memories(data_root, *, type_=None, scope_hash=None, limit=50):
    """Query SQLite memories table; fallback to filesystem scan if table missing."""
    import sqlite3
    db = data_root / "index.db"
    if not db.exists():
        return _scan_filesystem_memories(data_root, type_, scope_hash, limit)
    try:
        conn = sqlite3.connect(str(db))
        q = ("SELECT slug, type, scope_hash, ttl_days, last_recalled_at, "
             "recall_count, body_path FROM memories WHERE 1=1")
        params: list = []
        if type_:
            q += " AND type = ?"; params.append(type_)
        if scope_hash:
            q += " AND scope_hash = ?"; params.append(scope_hash)
        q += " ORDER BY slug DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(q, params).fetchall()
    finally:
        conn.close()
    cols = ["slug", "type", "scope_hash", "ttl_days", "last_recalled_at",
            "recall_count", "body_path"]
    return [dict(zip(cols, r)) for r in rows]


def _scan_filesystem_memories(data_root, type_, scope_hash, limit):
    """Fallback: walk scopes/ for .md when SQLite missing."""
    from .scope_meta import is_path_sensitive
    out = []
    scopes = data_root / "scopes"
    if not scopes.exists():
        return out
    for md in scopes.rglob("*.md"):
        if md.name.startswith(".") or md.parent.name.startswith("_"):
            continue
        parts = md.relative_to(scopes).parts
        if parts[0].startswith("_"):
            continue
        sh = parts[0]
        t_dir = parts[1] if len(parts) >= 3 else "memory"
        t = {"sessions": "session", "decisions": "decision",
             "preferences": "preference", "facts": "fact",
             "playbooks": "playbook", "warnings": "warning"}.get(t_dir, t_dir)
        if type_ and t != type_:
            continue
        if scope_hash and sh != scope_hash:
            continue
        out.append({"slug": md.stem, "type": t, "scope_hash": sh,
                   "body_path": str(md)})
    out.sort(key=lambda r: r["slug"], reverse=True)
    return out[:limit]


# show
p_show = subparsers.add_parser("show",
    help="display a single memory (frontmatter + body)")
p_show.add_argument("slug")
p_show.add_argument("--scope", default=None)
p_show.set_defaults(func=cmd_show)


def cmd_show(args):
    data_root = _data_root()
    path = _resolve_slug(data_root, args.slug, scope_hash=args.scope)
    if path is None:
        print(f"slug not found: {args.slug}", file=sys.stderr)
        return 1
    from .scope_meta import is_path_sensitive
    if is_path_sensitive(path.parent):
        # gate check
        from .governance import gate
        try:
            sh = path.relative_to(data_root / "scopes").parts[0]
            gate.check_or_raise(sh, "memoryd show")
        except gate.AuthorizationRequired as e:
            print(f"AUTHORIZATION_REQUIRED: {e}", file=sys.stderr)
            print("Run `memoryd grant <scope_path> --duration session` first.",
                  file=sys.stderr)
            return 1
    # plain text path
    if path.name.endswith(".md.enc"):
        from . import enc
        sh = path.relative_to(data_root / "scopes").parts[0]
        text = enc.decrypt_bytes(sh, path.read_bytes()).decode("utf-8")
    else:
        text = path.read_text(encoding="utf-8")
    print(text)
    return 0


def _resolve_slug(data_root, slug, *, scope_hash=None):
    """Find the .md / .md.enc path for slug; prefer scope_hash, fallback rglob."""
    scopes = data_root / "scopes"
    if not scopes.exists():
        return None
    candidates = []
    if scope_hash:
        roots = [scopes / scope_hash]
    else:
        roots = [d for d in scopes.iterdir() if d.is_dir()
                and not d.name.startswith("_")]
    for root in roots:
        if not root.exists():
            continue
        for ext in (".md", ".md.enc"):
            for p in root.rglob(f"{slug}{ext}"):
                candidates.append(p)
    if not candidates:
        return None
    # prefer non-sensitive plain .md
    for c in candidates:
        if c.suffix == ".md":
            return c
    return candidates[0]
```

### test_cli_query.py

```python
import json
from pathlib import Path

import pytest

from memoryd import cli


def _write_md(root, scope, type_dir, slug, body="x"):
    p = root / "scopes" / scope / type_dir / f"{slug}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\nslug: {slug}\nscope_hash: {scope}\n---\n{body}",
                encoding="utf-8")
    return p


def test_cli_search_finds_match(tmp_path, monkeypatch, capsys):
    _write_md(tmp_path, "h1", "sessions", "a",
             body="logo direction blue silver")
    monkeypatch.setattr("memoryd.cli._data_root", lambda: tmp_path)
    args = type("A", (), {"query": "logo", "scope": None, "type_": None,
                          "limit": 20, "as_json": False})()
    rc = cli.cmd_search(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert "a" in out


def test_cli_search_json_output(tmp_path, monkeypatch, capsys):
    _write_md(tmp_path, "h1", "sessions", "abc", body="hello world")
    monkeypatch.setattr("memoryd.cli._data_root", lambda: tmp_path)
    args = type("A", (), {"query": "hello", "scope": None, "type_": None,
                          "limit": 20, "as_json": True})()
    cli.cmd_search(args)
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert isinstance(parsed, list)


def test_cli_search_returns_0_on_no_hits(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("memoryd.cli._data_root", lambda: tmp_path)
    args = type("A", (), {"query": "missing", "scope": None, "type_": None,
                          "limit": 20, "as_json": False})()
    rc = cli.cmd_search(args)
    assert rc == 0


def test_cli_list_shows_memories(tmp_path, monkeypatch, capsys):
    _write_md(tmp_path, "h1", "sessions", "alpha")
    _write_md(tmp_path, "h1", "decisions", "beta")
    monkeypatch.setattr("memoryd.cli._data_root", lambda: tmp_path)
    args = type("A", (), {"type_": None, "scope": None, "limit": 50,
                          "as_json": False})()
    cli.cmd_list(args)
    out = capsys.readouterr().out
    assert "alpha" in out
    assert "beta" in out


def test_cli_list_filters_by_type(tmp_path, monkeypatch, capsys):
    _write_md(tmp_path, "h1", "sessions", "s1")
    _write_md(tmp_path, "h1", "decisions", "d1")
    monkeypatch.setattr("memoryd.cli._data_root", lambda: tmp_path)
    args = type("A", (), {"type_": "decision", "scope": None, "limit": 50,
                          "as_json": False})()
    cli.cmd_list(args)
    out = capsys.readouterr().out
    assert "d1" in out
    assert "s1" not in out


def test_cli_list_filters_by_scope(tmp_path, monkeypatch, capsys):
    _write_md(tmp_path, "h1", "sessions", "x1")
    _write_md(tmp_path, "h2", "sessions", "x2")
    monkeypatch.setattr("memoryd.cli._data_root", lambda: tmp_path)
    args = type("A", (), {"type_": None, "scope": "h2", "limit": 50,
                          "as_json": False})()
    cli.cmd_list(args)
    out = capsys.readouterr().out
    assert "x2" in out
    assert "x1" not in out


def test_cli_show_returns_body(tmp_path, monkeypatch, capsys):
    _write_md(tmp_path, "h1", "sessions", "viewme",
             body="this is the body content")
    monkeypatch.setattr("memoryd.cli._data_root", lambda: tmp_path)
    args = type("A", (), {"slug": "viewme", "scope": None})()
    rc = cli.cmd_show(args)
    assert rc == 0
    out = capsys.readouterr().out
    assert "this is the body content" in out


def test_cli_show_returns_1_for_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("memoryd.cli._data_root", lambda: tmp_path)
    args = type("A", (), {"slug": "missing", "scope": None})()
    rc = cli.cmd_show(args)
    assert rc == 1
```

### Steps

- [ ] cli.py 加 3 个 cmd_ + 2 个 helper（_list_memories / _scan_filesystem_memories / _resolve_slug）
- [ ] 写 test_cli_query.py 8 测试
- [ ] 跑 + 全套（320 + 8 ≈ 328）
- [ ] commit `plan9/task1: CLI search + list + show 子命令`

---

## Task 2：CLI delete + promote（写类）

**Files:**
- Modify: `memoryd/src/memoryd/cli.py`
- Modify: `memoryd/src/memoryd/governance/analyze.py`（approve_promotion 加真写 .md）
- Create: `memoryd/tests/test_cli_mutate.py`

### analyze.py approve_promotion 增强

读现状的 approve_promotion（Plan 7 Task 4 加的），改成：

```python
def approve_promotion(data_root: Path, promotion_id: int) -> Path | None:
    """Approve a promotion: mark status=approved AND write the .md file.

    Returns the path of the written .md, or None if nothing to write.
    """
    import sqlite3
    db = data_root / "index.db"
    if not db.exists():
        raise FileNotFoundError(f"no index.db at {db}")
    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute(
            "SELECT source_session_slug, proposed_type, proposed_title, "
            "       proposed_body, proposed_triggers, scope_hash "
            "FROM promotions WHERE id = ?", (promotion_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"no promotion #{promotion_id}")
        source_slug, type_, title, body, triggers, scope_hash = row
        cur = conn.execute(
            "UPDATE promotions SET status='approved' WHERE id = ?",
            (promotion_id,),
        )
        conn.commit()
    finally:
        conn.close()
    if not (type_ and title and body):
        return None  # partial promotion; status flipped but no file
    # write to <type>s/ directory
    from ..schema import Frontmatter, SessionMemory
    from ..storage import save_memory
    from ..scope import scope_hash as _scope_hash, resolve_scope_root
    sh = scope_hash or _scope_hash(resolve_scope_root(Path.cwd()))
    # parse triggers (stored as JSON list or comma-separated string)
    import json
    parsed_triggers: list[str] = []
    if triggers:
        try:
            parsed_triggers = json.loads(triggers)
            if not isinstance(parsed_triggers, list):
                parsed_triggers = []
        except Exception:
            parsed_triggers = [t.strip() for t in triggers.split(",") if t.strip()]
    if not parsed_triggers:
        parsed_triggers = ["promoted", source_slug or "imported"]
    from datetime import datetime, timezone
    fm = Frontmatter(
        title=title,
        slug=f"promoted-{promotion_id}-{(_safe_kebab(title))[:40]}",
        scope_hash=sh,
        type=type_,
        triggers=parsed_triggers,
        source=f"promoted-from-{source_slug}" if source_slug else "promoted",
        created_at=datetime.now(timezone.utc).isoformat(),
        promoted_from=source_slug,
    )
    return save_memory(data_root, SessionMemory(frontmatter=fm, body=body))


def _safe_kebab(s: str) -> str:
    import re
    return re.sub(r"[^a-z0-9-]", "", re.sub(r"\s+", "-", s.lower())).strip("-")
```

注意：Frontmatter `promoted_from` 字段是 Plan 3 加的（"长期记忆引用其源 session slug"），应该已存在。如不存在 raise；如存在则 OK。先 grep 确认。

### cli.py delete + promote

```python
# delete
p_delete = subparsers.add_parser("delete",
    help="delete a memory permanently (irreversible)")
p_delete.add_argument("slug")
p_delete.add_argument("--scope", default=None)
p_delete.add_argument("--force", action="store_true",
                    help="skip y/N confirmation")
p_delete.set_defaults(func=cmd_delete)


def cmd_delete(args):
    data_root = _data_root()
    path = _resolve_slug(data_root, args.slug, scope_hash=args.scope)
    if path is None:
        print(f"slug not found: {args.slug}", file=sys.stderr)
        return 1
    from .scope_meta import is_path_sensitive
    if is_path_sensitive(path.parent):
        from .governance import gate
        try:
            sh = path.relative_to(data_root / "scopes").parts[0]
            gate.check_or_raise(sh, "memoryd delete")
        except gate.AuthorizationRequired as e:
            print(f"AUTHORIZATION_REQUIRED: {e}", file=sys.stderr)
            return 1
    if not args.force:
        ans = input(f"delete {path}? [y/N] ")
        if ans.lower() != "y":
            print("aborted", file=sys.stderr)
            return 1
    # delete .md file + SQLite row
    path.unlink()
    import sqlite3
    db = data_root / "index.db"
    if db.exists():
        conn = sqlite3.connect(str(db))
        try:
            conn.execute("DELETE FROM memories WHERE slug = ?", (args.slug,))
            conn.execute("DELETE FROM triggers WHERE slug = ?", (args.slug,))
            conn.commit()
        finally:
            conn.close()
    print(f"deleted: {path}", file=sys.stderr)
    return 0


# promote
p_promote = subparsers.add_parser("promote",
    help="approve a pending promotion (writes the long-term memory .md)")
p_promote.add_argument("promotion_id", type=int,
                      help="id from `memoryd digest --json` or web /digest")
p_promote.set_defaults(func=cmd_promote)


def cmd_promote(args):
    from .governance.analyze import approve_promotion
    data_root = _data_root()
    try:
        out = approve_promotion(data_root, args.promotion_id)
    except FileNotFoundError as e:
        print(f"no SQLite db: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"{e}", file=sys.stderr)
        return 1
    if out is None:
        print(f"promotion #{args.promotion_id} approved (status only; "
              "no body to write)", file=sys.stderr)
    else:
        print(f"promoted: {out}", file=sys.stderr)
    return 0
```

### test_cli_mutate.py

```python
import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from memoryd import cli


def _write_md(root, scope, type_dir, slug, body="x"):
    p = root / "scopes" / scope / type_dir / f"{slug}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\nslug: {slug}\n---\n{body}", encoding="utf-8")
    return p


def _init_db_with_promotions(data_root):
    db = data_root / "index.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS memories ("
        "slug TEXT PRIMARY KEY, type TEXT, scope_hash TEXT, "
        "ttl_days INTEGER, last_recalled_at TEXT, "
        "recall_count INTEGER, body_path TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS triggers (slug TEXT, trigger TEXT, "
        "PRIMARY KEY (slug, trigger))"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS promotions ("
        "id INTEGER PRIMARY KEY, source_session_slug TEXT, "
        "proposed_type TEXT, proposed_title TEXT, "
        "proposed_body TEXT, proposed_triggers TEXT, "
        "scope_hash TEXT, reasoning TEXT, status TEXT)"
    )
    conn.commit()
    conn.close()


def test_cli_delete_removes_file_with_force(tmp_path, monkeypatch, capsys):
    p = _write_md(tmp_path, "h1", "sessions", "bye")
    monkeypatch.setattr("memoryd.cli._data_root", lambda: tmp_path)
    args = type("A", (), {"slug": "bye", "scope": None, "force": True})()
    rc = cli.cmd_delete(args)
    assert rc == 0
    assert not p.exists()


def test_cli_delete_returns_1_for_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("memoryd.cli._data_root", lambda: tmp_path)
    args = type("A", (), {"slug": "missing", "scope": None, "force": True})()
    rc = cli.cmd_delete(args)
    assert rc == 1


def test_cli_delete_prompts_without_force(tmp_path, monkeypatch, capsys):
    _write_md(tmp_path, "h1", "sessions", "ask")
    monkeypatch.setattr("memoryd.cli._data_root", lambda: tmp_path)
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")
    args = type("A", (), {"slug": "ask", "scope": None, "force": False})()
    rc = cli.cmd_delete(args)
    assert rc == 1
    # 文件还在
    assert (tmp_path / "scopes" / "h1" / "sessions" / "ask.md").exists()


def test_cli_delete_unindexes_sqlite(tmp_path, monkeypatch):
    p = _write_md(tmp_path, "h1", "sessions", "byedb")
    _init_db_with_promotions(tmp_path)
    db = tmp_path / "index.db"
    conn = sqlite3.connect(str(db))
    conn.execute("INSERT INTO memories (slug, type, scope_hash) "
                "VALUES ('byedb', 'session', 'h1')")
    conn.execute("INSERT INTO triggers (slug, trigger) "
                "VALUES ('byedb', 'foo')")
    conn.commit()
    conn.close()
    monkeypatch.setattr("memoryd.cli._data_root", lambda: tmp_path)
    args = type("A", (), {"slug": "byedb", "scope": None, "force": True})()
    cli.cmd_delete(args)
    conn = sqlite3.connect(str(db))
    rows = conn.execute("SELECT * FROM memories WHERE slug='byedb'").fetchall()
    conn.close()
    assert rows == []


def test_cli_promote_writes_md(tmp_path, monkeypatch, capsys):
    _init_db_with_promotions(tmp_path)
    db = tmp_path / "index.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO promotions (source_session_slug, proposed_type, "
        "proposed_title, proposed_body, proposed_triggers, scope_hash, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("sess-1", "decision", "logo blue", "decision body here",
         '["logo", "blue"]', "h1", "pending"),
    )
    conn.commit()
    pid = conn.execute(
        "SELECT id FROM promotions WHERE proposed_title='logo blue'"
    ).fetchone()[0]
    conn.close()
    monkeypatch.setattr("memoryd.cli._data_root", lambda: tmp_path)
    args = type("A", (), {"promotion_id": pid})()
    rc = cli.cmd_promote(args)
    assert rc == 0
    # SQLite status changed
    conn = sqlite3.connect(str(db))
    st = conn.execute("SELECT status FROM promotions WHERE id = ?",
                     (pid,)).fetchone()[0]
    conn.close()
    assert st == "approved"
    # .md file exists in decisions/
    md_files = list((tmp_path / "scopes" / "h1" / "decisions").glob("*.md"))
    assert len(md_files) == 1
    text = md_files[0].read_text()
    assert "decision body here" in text


def test_cli_promote_unknown_id(tmp_path, monkeypatch, capsys):
    _init_db_with_promotions(tmp_path)
    monkeypatch.setattr("memoryd.cli._data_root", lambda: tmp_path)
    args = type("A", (), {"promotion_id": 999})()
    rc = cli.cmd_promote(args)
    assert rc == 1
```

### Steps

- [ ] grep Plan 3 Frontmatter 是否有 `promoted_from` 字段；Plan 3 spec §3 说有
- [ ] 改 governance/analyze.py approve_promotion 加真写
- [ ] cli.py 加 cmd_delete + cmd_promote
- [ ] 写 test_cli_mutate.py 6 测试
- [ ] 全套 ~334 passed（328 + 6）
- [ ] commit `plan9/task2: CLI delete + promote 子命令；approve_promotion 真写 .md`

---

## Task 3：README + execution-log + 收尾

**Files:**
- Modify: `memoryd/README.md`
- Create: `docs/superpowers/plans/2026-05-16-plan9-cli-readwrite-commands.execution-log.txt`

### README 加 "## Manual control CLI (Plan 9)" 章节

在现有 Plan 8 章节之后插入：

```markdown
## Manual control CLI (Plan 9)

spec §4.3 #9 hard requirement：补 5 个 CLI 子命令让用户脱离 CC 也能查询/控制记忆库。

\`\`\`bash
# 搜索
memoryd search "logo blue"
memoryd search "x" --type=decision --scope=d8e86b48589e --limit=10 --json

# 列表
memoryd list                            # 默认全部，按 slug desc，limit 50
memoryd list --type=decision
memoryd list --scope=d8e86b48589e --limit=100

# 详情
memoryd show <slug>                     # 输出 frontmatter + body 原文
memoryd show <slug> --scope=<hash>      # 显式 scope

# 删除
memoryd delete <slug>                   # prompt y/N
memoryd delete <slug> --force           # 跳过确认

# 提升 pending promotion 为正式长期记忆
memoryd promote <promotion_id>          # 用 memoryd digest --json 拿 id
\`\`\`

### Sensitive scope

`show` / `delete` 在 sensitive scope 上前自动 gate.check_or_raise；没 grant 抛 `AUTHORIZATION_REQUIRED`。先：

\`\`\`bash
memoryd grant ~/scopes/finance --duration session
memoryd show <slug>
\`\`\`

### promote 真写文件

`memoryd promote` 不只是 SQLite status=approved，还真把 promotion 的 proposed_body / proposed_type / proposed_triggers 写到 `scopes/<hash>/<type>s/promoted-<id>-<slug>.md`，含 promoted_from 字段标 source session。
```

### execution-log

```
# Plan 9 Phase 1 用户手册（CLI 主动控制 5 子命令）

## 1. search smoke

cd /Users/abble/project-management-personal/memoryd
uv run memoryd search "logo"
uv run memoryd search "decision" --type=decision --limit=5
uv run memoryd search "x" --json | jq

## 2. list smoke

uv run memoryd list
uv run memoryd list --type=decision
uv run memoryd list --scope=<hash>

## 3. show

uv run memoryd list --limit=1 --json | jq -r '.[0].slug'
SLUG=$(uv run memoryd list --limit=1 --json | jq -r '.[0].slug')
uv run memoryd show "$SLUG"

## 4. delete（sandbox 安全测）

# 先 import 一条 sandbox 数据，再删
mkdir -p /tmp/memoryd-delete-test/scopes/h_test/sessions
cat > /tmp/memoryd-delete-test/scopes/h_test/sessions/test-delete.md <<EOF
---
slug: test-delete
scope_hash: h_test
type: session
---
soon to be deleted
EOF
MEMORYD_DATA_ROOT=/tmp/memoryd-delete-test uv run memoryd delete test-delete --force
test ! -f /tmp/memoryd-delete-test/scopes/h_test/sessions/test-delete.md && echo "OK"
rm -rf /tmp/memoryd-delete-test

## 5. promote（需先有 pending promotion；配 ANTHROPIC_API_KEY 后跑过 analyze-session 才生成）

uv run memoryd digest --json | jq '.promotions[] | select(.status=="pending")'
# 拿 id，然后：
# uv run memoryd promote <id>
```

### Steps

- [ ] README 加 Manual control CLI 章节 + Status 升 v0.9.0
- [ ] 写 execution-log
- [ ] 跑全套 (>= 334 passed) + npm test (12)
- [ ] commit `plan9/task3: README + execution-log + Status 升 v0.9.0`
- [ ] finishing-a-development-branch → PR → auto-merge

---

## 完成判据

1. ✅ pytest ≥ 334 passed
2. ✅ npm test 12 passed
3. ✅ 5 个 CLI 子命令 --help 不报错
4. ✅ Plan 1-8 测试无回归
5. ✅ MCP 工具数仍 8/12（未加新工具）
6. ✅ approve_promotion 真写 .md 文件而不只 flip status
7. ✅ sensitive scope show/delete 走 gate
