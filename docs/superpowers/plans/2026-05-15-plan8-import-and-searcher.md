# 旧记忆导入 + memory-searcher（Plan 8）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** spec §4.7 #28 + §4.2 #5 落地——4 个单向 import 子命令（claude-md / auto-memory / agents-md / mcp-memory-service）+ memory-searcher sub-agent 模板 + install 子命令。

**Architecture:** `importers/` 包按 kind 分文件；共享 `common.py` 处理 frontmatter wrap + storage.save_memory；heuristic section split（无 LLM 依赖）。memory-searcher 是纯模板文件 + cp 命令。

**Tech Stack:** Python 3.11+；无新依赖。spec: `docs/superpowers/specs/2026-05-15-plan8-import-and-searcher-design.md`。

**Decomposition Note:** 8 plan 中的最后一个。上游 Plan 1-7 全 merged（3aeef52）。

---

## 文件结构

| 路径 | 责任 | 操作 |
|---|---|---|
| `memoryd/src/memoryd/importers/__init__.py` | package init + types | Create |
| `memoryd/src/memoryd/importers/common.py` | slug/frontmatter helpers + save_memory wrapper | Create |
| `memoryd/src/memoryd/importers/claude_md.py` | parse_sections + infer_type + run | Create |
| `memoryd/src/memoryd/importers/auto_memory.py` | scan dir + map auto-memory type | Create |
| `memoryd/src/memoryd/importers/agents_md.py` | reuse claude_md parse | Create |
| `memoryd/src/memoryd/importers/mcp_mem.py` | memories.json parse | Create |
| `memoryd/src/memoryd/templates/memory-searcher.md` | sub-agent .md 模板 | Create |
| `memoryd/src/memoryd/setup.py` | install_memory_searcher 函数 | Modify |
| `memoryd/src/memoryd/cli.py` | `import <kind>` + `setup install-memory-searcher` 子命令 | Modify |
| `memoryd/tests/test_importers_claude_md.py` | section split + type 推断 | Create |
| `memoryd/tests/test_importers_auto_memory.py` | scan + skip MEMORY.md + type map | Create |
| `memoryd/tests/test_importers_agents_md.py` | 通过 claude_md 路径复用 | Create |
| `memoryd/tests/test_importers_mcp_mem.py` | json load + skip invalid | Create |
| `memoryd/tests/test_setup_memory_searcher.py` | install + --force + --target | Create |
| `memoryd/README.md` | 加 Plan 8 章节 | Modify |
| `docs/superpowers/plans/2026-05-15-plan8-import-and-searcher.execution-log.txt` | Phase 1 用户手册 | Create |

---

## 风险与不确定性

1. **frontmatter wrap 需用 Plan 7 schema**：Plan 7 加了 tags / category / observations；importers 写入时不强制设这些。
2. **`save_memory` 已存在**：Plan 3 加入。importers 调用既有 API；不重新发明落盘逻辑。
3. **重复 slug**：默认 skip + log；--force 覆盖。`save_memory` 当前行为需先验证；测试覆盖。
4. **sensitive scope**：用 `--scope=<sensitive_hash>` import 时，`save_memory` 应自动走加密（Plan 4 既有）。不需 importers 特殊处理。
5. **memory-searcher 模板部署**：用户可能没装 CC（仅有 Codex / OpenClaw），install 应允许 --target 路径覆盖（不强制 ~/.claude/agents/）。

---

## Task 1：importers 框架 + claude-md

**Files:**
- Create: `memoryd/src/memoryd/importers/__init__.py`
- Create: `memoryd/src/memoryd/importers/common.py`
- Create: `memoryd/src/memoryd/importers/claude_md.py`
- Create: `memoryd/tests/test_importers_claude_md.py`

### `importers/__init__.py`

```python
"""One-shot importers for migrating older personal-memory layouts into memoryd."""
```

### `importers/common.py`

```python
"""Shared helpers for importers."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


_SLUG_BAD = re.compile(r"[^a-z0-9-]")


def kebab(text: str, max_len: int = 60) -> str:
    s = text.lower()
    s = re.sub(r"\s+", "-", s)
    s = _SLUG_BAD.sub("", s)
    return s[:max_len].strip("-") or "untitled"


def short_hash(text: str, n: int = 8) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:n]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ImportEntry:
    slug: str
    type: str
    title: str
    body: str
    triggers: list[str]
    source: str
    created_at: str


@dataclass
class ImportReport:
    parsed: int = 0
    written: int = 0
    skipped: int = 0
    by_type: dict | None = None
    dry_run: bool = False

    def __post_init__(self):
        if self.by_type is None:
            self.by_type = {}


def write_entry(
    data_root: Path,
    scope_hash: str,
    entry: ImportEntry,
    *,
    dry_run: bool = False,
    force: bool = False,
) -> bool:
    """Write to memoryd via storage.save_memory. Return True if written."""
    if dry_run:
        return True
    from ..schema import Frontmatter
    from ..storage import save_memory  # Plan 3 既有
    fm = Frontmatter(
        title=entry.title,
        slug=entry.slug,
        scope_hash=scope_hash,
        type=entry.type,
        triggers=entry.triggers,
        source=entry.source,
        created_at=entry.created_at,
    )
    # 检查存在
    target = data_root / "scopes" / scope_hash / _type_dir(entry.type) / f"{entry.slug}.md"
    if target.exists() and not force:
        return False
    save_memory(data_root, fm, entry.body)
    return True


def _type_dir(t: str) -> str:
    return {
        "session": "sessions",
        "decision": "decisions",
        "preference": "preferences",
        "fact": "facts",
        "playbook": "playbooks",
        "warning": "warnings",
    }.get(t, "facts")
```

注：调 `save_memory` 前要确认 Plan 3 该函数签名（`save_memory(data_root, frontmatter, body)` 或 `save_memory(data_root, MemoryEntry)`）。**先 grep 现状**调整。

### `importers/claude_md.py`

```python
"""Import CLAUDE.md by heuristic section split."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .common import (
    ImportEntry,
    ImportReport,
    kebab,
    now_iso,
    short_hash,
    write_entry,
)


_HEADING_PATTERN = re.compile(r"^(#{2,3})\s+(.+?)\s*$", re.MULTILINE)
_TYPE_HINTS = [
    (re.compile(r"warning|踩坑|不要|避免|caution", re.IGNORECASE), "warning"),
    (re.compile(r"playbook|流程|操作|how[- ]?to|steps?\b", re.IGNORECASE), "playbook"),
    (re.compile(r"decision|决策|选[择型方]?|chose|chosen", re.IGNORECASE), "decision"),
    (re.compile(r"preference|偏好|习惯|prefer|like to", re.IGNORECASE), "preference"),
]


@dataclass
class Section:
    level: int
    heading: str
    body: str


def parse_sections(text: str) -> list[Section]:
    matches = list(_HEADING_PATTERN.finditer(text))
    sections = []
    for i, m in enumerate(matches):
        level = len(m.group(1))
        heading = m.group(2)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if body:
            sections.append(Section(level=level, heading=heading, body=body))
    return sections


def infer_type(heading: str) -> str:
    for pattern, type_ in _TYPE_HINTS:
        if pattern.search(heading):
            return type_
    return "fact"


def derive_triggers(heading: str) -> list[str]:
    words = re.findall(r"[A-Za-z一-鿿][A-Za-z0-9一-鿿_-]+", heading)
    triggers = [w for w in words if len(w) >= 3][:5]
    if len(triggers) < 2:
        triggers = ["imported", kebab(heading)] + triggers
    return triggers[:5]


def to_entries(
    text: str,
    *,
    kind: str = "claude-md",
    source_tag: str | None = None,
) -> list[ImportEntry]:
    src = source_tag or f"imported-{kind}"
    out = []
    seen_slugs: dict[str, int] = {}
    for sec in parse_sections(text):
        type_ = infer_type(sec.heading)
        base_slug = f"imported-{kind}-{kebab(sec.heading)}"
        n = seen_slugs.get(base_slug, 0)
        slug = base_slug if n == 0 else f"{base_slug}-{n}"
        seen_slugs[base_slug] = n + 1
        body = sec.body if len(sec.body) <= 8000 else sec.body[:8000] + "..."
        out.append(ImportEntry(
            slug=slug,
            type=type_,
            title=sec.heading,
            body=body,
            triggers=derive_triggers(sec.heading),
            source=src,
            created_at=now_iso(),
        ))
    return out


def run(
    md_path: Path,
    data_root: Path,
    scope_hash: str,
    *,
    dry_run: bool = False,
    force: bool = False,
    source_tag: str | None = None,
) -> ImportReport:
    text = Path(md_path).read_text(encoding="utf-8")
    entries = to_entries(text, kind="claude-md", source_tag=source_tag)
    report = ImportReport(parsed=len(entries), dry_run=dry_run)
    for e in entries:
        written = write_entry(data_root, scope_hash, e, dry_run=dry_run, force=force)
        if written:
            report.written += 1
            report.by_type[e.type] = report.by_type.get(e.type, 0) + 1
        else:
            report.skipped += 1
    return report
```

### test_importers_claude_md.py

```python
import pytest

from memoryd.importers.claude_md import (
    derive_triggers,
    infer_type,
    parse_sections,
    to_entries,
    run,
)


SAMPLE = """\
# Project Notes

Some intro.

## Database decisions

We use postgres 15. Reason: jsonb support.

## How to deploy

1. Push to main
2. CI runs
3. Tag v0.x.y

## Warning: do not push --force

It triggers double deploys.

### prefer merge over squash

For PRs touching docs.
"""


def test_parse_sections_split_by_h2_and_h3():
    secs = parse_sections(SAMPLE)
    assert len(secs) == 4
    assert secs[0].heading == "Database decisions"
    assert secs[2].heading.startswith("Warning")
    assert secs[3].level == 3


def test_infer_type_keywords():
    assert infer_type("Database decisions") == "decision"
    assert infer_type("How to deploy") == "playbook"
    assert infer_type("Warning: do not push --force") == "warning"
    assert infer_type("prefer merge over squash") == "preference"
    assert infer_type("Random fact about life") == "fact"


def test_derive_triggers_at_least_two():
    assert len(derive_triggers("Database decisions")) >= 2
    assert len(derive_triggers("X")) >= 2  # fallback to ["imported", "x"]


def test_to_entries_round_trip():
    entries = to_entries(SAMPLE)
    assert len(entries) == 4
    types = sorted(e.type for e in entries)
    assert types == ["decision", "playbook", "preference", "warning"]
    assert all(e.source == "imported-claude-md" for e in entries)
    assert all(len(e.triggers) >= 2 for e in entries)


def test_to_entries_unique_slugs_for_duplicate_headings():
    text = "## Foo\nbody 1\n## Foo\nbody 2\n"
    entries = to_entries(text)
    slugs = [e.slug for e in entries]
    assert len(set(slugs)) == 2


def test_run_writes_to_data_root(tmp_path):
    md = tmp_path / "CLAUDE.md"
    md.write_text(SAMPLE)
    data_root = tmp_path / "data"
    report = run(md, data_root, scope_hash="h1")
    assert report.parsed == 4
    assert report.written == 4
    assert report.skipped == 0
    # files in correct dirs
    assert (data_root / "scopes" / "h1" / "decisions").exists()
    assert (data_root / "scopes" / "h1" / "warnings").exists()


def test_run_dry_run_writes_nothing(tmp_path):
    md = tmp_path / "CLAUDE.md"
    md.write_text(SAMPLE)
    data_root = tmp_path / "data"
    report = run(md, data_root, scope_hash="h1", dry_run=True)
    assert report.dry_run is True
    assert report.parsed == 4
    assert not (data_root / "scopes" / "h1").exists()


def test_run_skips_duplicate_without_force(tmp_path):
    md = tmp_path / "CLAUDE.md"
    md.write_text(SAMPLE)
    data_root = tmp_path / "data"
    run(md, data_root, scope_hash="h1")
    report = run(md, data_root, scope_hash="h1")
    assert report.written == 0
    assert report.skipped == 4
```

### Steps

- [ ] Step 1: 先 grep Plan 3 `save_memory` 签名（`memoryd/src/memoryd/storage.py`）
- [ ] Step 2: 写 importers/__init__.py + common.py + claude_md.py（按现 save_memory 签名调整）
- [ ] Step 3: 写 8 个测试
- [ ] Step 4: 跑：`cd memoryd && uv run pytest tests/test_importers_claude_md.py -v`
- [ ] Step 5: 全套 ~294 passed
- [ ] Step 6: commit `plan8/task1: importers framework + claude-md heuristic section split`

---

## Task 2：auto-memory + agents-md importers

**Files:**
- Create: `memoryd/src/memoryd/importers/auto_memory.py`
- Create: `memoryd/src/memoryd/importers/agents_md.py`
- Create: `memoryd/tests/test_importers_auto_memory.py`
- Create: `memoryd/tests/test_importers_agents_md.py`

### `importers/auto_memory.py`

```python
"""Import ~/.claude/projects/<proj>/memory/ auto-memory files."""
from __future__ import annotations

from pathlib import Path

from .common import (
    ImportEntry,
    ImportReport,
    kebab,
    now_iso,
    short_hash,
    write_entry,
)
from .claude_md import derive_triggers


_TYPE_MAP = {
    "user": "fact",
    "feedback": "preference",
    "project": "fact",
    "reference": "fact",
}


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Naive YAML frontmatter parser (handles only the small subset auto-memory writes)."""
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, text
    fm_text = text[4:end]
    body = text[end + 5 :]
    out: dict = {}
    cur_list_key: str | None = None
    for line in fm_text.splitlines():
        if line.startswith("  - "):
            if cur_list_key:
                out.setdefault(cur_list_key, []).append(line[4:].strip())
            continue
        if ": " in line:
            k, v = line.split(": ", 1)
            k = k.strip(); v = v.strip()
            if v.startswith("[") and v.endswith("]"):
                out[k] = [x.strip().strip('"') for x in v[1:-1].split(",") if x.strip()]
            elif v:
                out[k] = v
            else:
                cur_list_key = k
                out[k] = []
            continue
        if line.strip().startswith("type:") and "metadata" in out:
            # metadata: { type: foo } 内嵌 nested 简化版略
            pass
    return out, body


def run(
    memory_dir: Path,
    data_root: Path,
    scope_hash: str,
    *,
    dry_run: bool = False,
    force: bool = False,
    source_tag: str | None = None,
) -> ImportReport:
    src = source_tag or "imported-auto-memory"
    memory_dir = Path(memory_dir)
    report = ImportReport(dry_run=dry_run)
    if not memory_dir.exists():
        return report
    for md in memory_dir.glob("*.md"):
        if md.name == "MEMORY.md":
            continue
        text = md.read_text(encoding="utf-8")
        fm, body = _parse_frontmatter(text)
        auto_type = (fm.get("metadata.type")
                    or fm.get("type")
                    or "user")
        memoryd_type = _TYPE_MAP.get(auto_type, "fact")
        title = fm.get("name") or md.stem
        slug = f"imported-auto-memory-{kebab(title)}-{short_hash(text)}"
        body = body.strip() or text.strip()
        if len(body) > 8000:
            body = body[:8000] + "..."
        entry = ImportEntry(
            slug=slug,
            type=memoryd_type,
            title=title,
            body=body,
            triggers=derive_triggers(title),
            source=src,
            created_at=now_iso(),
        )
        report.parsed += 1
        if write_entry(data_root, scope_hash, entry,
                       dry_run=dry_run, force=force):
            report.written += 1
            report.by_type[memoryd_type] = report.by_type.get(memoryd_type, 0) + 1
        else:
            report.skipped += 1
    return report
```

### `importers/agents_md.py`

```python
"""Import Codex AGENTS.md by reusing claude_md heuristic split."""
from __future__ import annotations

from pathlib import Path

from .claude_md import run as _claude_run


def run(md_path: Path, data_root: Path, scope_hash: str, **kw) -> "ImportReport":
    """AGENTS.md ≈ CLAUDE.md structure；复用 claude-md kinds 即可，覆盖 source."""
    if kw.get("source_tag") is None:
        kw["source_tag"] = "imported-agents-md"
    return _claude_run(md_path, data_root, scope_hash, **kw)
```

### test_importers_auto_memory.py

```python
import pytest

from memoryd.importers.auto_memory import run, _parse_frontmatter, _TYPE_MAP


SAMPLE_FACT = """---
name: db-version
description: postgres version note
metadata:
  type: user
---

We use postgres 15 for jsonb support.
"""

SAMPLE_FEEDBACK = """---
name: pr-merge-pref
metadata:
  type: feedback
---

Prefer merge commits over squash for PRs touching docs.
"""


def test_run_skips_memory_md(tmp_path):
    mem_dir = tmp_path / "memory"
    mem_dir.mkdir()
    (mem_dir / "MEMORY.md").write_text("# index\nlinks")
    (mem_dir / "real.md").write_text(SAMPLE_FACT)
    data_root = tmp_path / "data"
    report = run(mem_dir, data_root, scope_hash="h1")
    assert report.parsed == 1
    assert (data_root / "scopes" / "h1" / "facts").exists()


def test_type_map_feedback_to_preference(tmp_path):
    mem_dir = tmp_path / "memory"
    mem_dir.mkdir()
    (mem_dir / "pref.md").write_text(SAMPLE_FEEDBACK)
    data_root = tmp_path / "data"
    report = run(mem_dir, data_root, scope_hash="h1")
    assert "preference" in report.by_type
    assert (data_root / "scopes" / "h1" / "preferences").exists()


def test_missing_dir_returns_empty(tmp_path):
    report = run(tmp_path / "nope", tmp_path / "data", "h1")
    assert report.parsed == 0
    assert report.written == 0


def test_dry_run_no_write(tmp_path):
    mem_dir = tmp_path / "memory"
    mem_dir.mkdir()
    (mem_dir / "x.md").write_text(SAMPLE_FACT)
    data_root = tmp_path / "data"
    report = run(mem_dir, data_root, scope_hash="h1", dry_run=True)
    assert report.parsed == 1
    assert report.written == 1  # dry_run still counts as "would write"
    assert not (data_root / "scopes" / "h1").exists()
```

### test_importers_agents_md.py

```python
from memoryd.importers.agents_md import run as agents_run


def test_run_sets_imported_agents_md_source(tmp_path):
    md = tmp_path / "AGENTS.md"
    md.write_text("## How to deploy\nstep 1 step 2\n## Warning: be careful\nthings\n")
    data_root = tmp_path / "data"
    report = agents_run(md, data_root, scope_hash="h1")
    assert report.written == 2
    # one of the .md should have source=imported-agents-md
    found = False
    for md_out in (data_root / "scopes" / "h1").rglob("*.md"):
        if "imported-agents-md" in md_out.read_text():
            found = True
            break
    assert found
```

### Steps

- [ ] 实现 auto_memory.py + agents_md.py
- [ ] 4 + 1 测试
- [ ] 全套 ~299 passed
- [ ] commit `plan8/task2: auto-memory + agents-md importers`

---

## Task 3：mcp-memory-service importer

**Files:**
- Create: `memoryd/src/memoryd/importers/mcp_mem.py`
- Create: `memoryd/tests/test_importers_mcp_mem.py`

### `importers/mcp_mem.py`

```python
"""Import mcp-memory-service memories.json."""
from __future__ import annotations

import json
from pathlib import Path

from .common import (
    ImportEntry,
    ImportReport,
    kebab,
    now_iso,
    short_hash,
    write_entry,
)
from .claude_md import derive_triggers


def _map_type(meta_type: str | None) -> str:
    if not meta_type:
        return "fact"
    s = meta_type.lower()
    if "decision" in s:
        return "decision"
    if "preference" in s or "pref" in s:
        return "preference"
    if "warning" in s or "warn" in s:
        return "warning"
    if "playbook" in s or "process" in s:
        return "playbook"
    return "fact"


def run(
    json_path: Path,
    data_root: Path,
    scope_hash: str,
    *,
    dry_run: bool = False,
    force: bool = False,
    source_tag: str | None = None,
) -> ImportReport:
    src = source_tag or "imported-mcp-memory-service"
    report = ImportReport(dry_run=dry_run)
    text = Path(json_path).read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return report
    if isinstance(data, dict) and "memories" in data:
        data = data["memories"]
    if not isinstance(data, list):
        return report
    for item in data:
        if not isinstance(item, dict):
            continue
        content = item.get("content") or item.get("text") or ""
        if not content:
            continue
        meta = item.get("metadata") or {}
        tags = meta.get("tags") or []
        if not isinstance(tags, list):
            tags = []
        item_id = item.get("id") or short_hash(content)
        meta_type = meta.get("type")
        memoryd_type = _map_type(meta_type)
        title = (content[:60] + "…") if len(content) > 60 else content
        slug = f"imported-mcpmem-{kebab(str(item_id))[:30]}-{short_hash(content)}"
        triggers = (tags or derive_triggers(title))[:5]
        body = content if len(content) <= 8000 else content[:8000] + "..."
        entry = ImportEntry(
            slug=slug,
            type=memoryd_type,
            title=title.strip(),
            body=body,
            triggers=triggers,
            source=src,
            created_at=meta.get("created_at") or now_iso(),
        )
        report.parsed += 1
        if write_entry(data_root, scope_hash, entry,
                       dry_run=dry_run, force=force):
            report.written += 1
            report.by_type[memoryd_type] = report.by_type.get(memoryd_type, 0) + 1
        else:
            report.skipped += 1
    return report
```

### test_importers_mcp_mem.py

```python
import json

import pytest

from memoryd.importers.mcp_mem import run, _map_type


SAMPLE = [
    {"id": "1", "content": "DB is postgres 15",
     "metadata": {"tags": ["db", "infra"], "type": "fact",
                  "created_at": "2026-01-01T00:00:00+00:00"}},
    {"id": "2", "content": "Logo: deep blue + silver",
     "metadata": {"tags": ["logo"], "type": "decision",
                  "created_at": "2026-02-01T00:00:00+00:00"}},
    {"id": "3", "content": "Don't push --force to main",
     "metadata": {"tags": ["ci"], "type": "warning"}},
]


def test_map_type_keywords():
    assert _map_type("decision") == "decision"
    assert _map_type("user.preference") == "preference"
    assert _map_type("warning") == "warning"
    assert _map_type(None) == "fact"


def test_run_writes_each_memory(tmp_path):
    p = tmp_path / "memories.json"
    p.write_text(json.dumps(SAMPLE))
    data_root = tmp_path / "data"
    report = run(p, data_root, scope_hash="h1")
    assert report.parsed == 3
    assert report.written == 3
    assert report.by_type == {"fact": 1, "decision": 1, "warning": 1}


def test_run_handles_wrapped_dict(tmp_path):
    """Some mcp-memory-service exports use {"memories": [...]}."""
    p = tmp_path / "memories.json"
    p.write_text(json.dumps({"memories": SAMPLE}))
    data_root = tmp_path / "data"
    report = run(p, data_root, scope_hash="h1")
    assert report.parsed == 3


def test_run_skips_invalid_entries(tmp_path):
    p = tmp_path / "memories.json"
    p.write_text(json.dumps([
        {"id": "ok", "content": "good"},
        {"no_content": True},  # bad
        "string-not-dict",       # bad
    ]))
    data_root = tmp_path / "data"
    report = run(p, data_root, scope_hash="h1")
    assert report.parsed == 1
    assert report.written == 1


def test_run_invalid_json_returns_empty(tmp_path):
    p = tmp_path / "memories.json"
    p.write_text("{not json")
    data_root = tmp_path / "data"
    report = run(p, data_root, scope_hash="h1")
    assert report.parsed == 0
```

### Steps

- [ ] 实现 mcp_mem.py
- [ ] 5 测试
- [ ] 全套 ~304 passed
- [ ] commit `plan8/task3: mcp-memory-service importer`

---

## Task 4：CLI `import` 子命令

**Files:**
- Modify: `memoryd/src/memoryd/cli.py`
- Create: `memoryd/tests/test_cli_import.py`（轻量 CLI 集成）

### cli.py 加：

```python
# import <kind> <path>
p_import = subparsers.add_parser("import",
    help="one-shot import from older memory layouts (single direction)")
import_subs = p_import.add_subparsers(dest="import_kind", required=True)

for _kind in ("claude-md", "auto-memory", "agents-md", "mcp-memory-service"):
    pp = import_subs.add_parser(_kind)
    pp.add_argument("path", type=Path)
    pp.add_argument("--scope", default=None,
                   help="explicit scope_hash; default = cwd-derived")
    pp.add_argument("--dry-run", action="store_true")
    pp.add_argument("--force", action="store_true",
                   help="overwrite existing slugs")
    pp.add_argument("--source-tag", default=None)
    pp.set_defaults(func=_cmd_import)


def _cmd_import(args):
    from .scope import resolve_scope_root, scope_hash as _scope_hash
    scope = args.scope or _scope_hash(resolve_scope_root(Path.cwd()))
    kind = args.import_kind
    if kind == "claude-md":
        from .importers import claude_md as mod
    elif kind == "auto-memory":
        from .importers import auto_memory as mod
    elif kind == "agents-md":
        from .importers import agents_md as mod
    elif kind == "mcp-memory-service":
        from .importers import mcp_mem as mod
    else:
        print(f"unknown import kind: {kind}", file=sys.stderr)
        return 2
    report = mod.run(
        args.path, _data_root(), scope,
        dry_run=args.dry_run, force=args.force,
        source_tag=args.source_tag,
    )
    import json as _json
    print(_json.dumps({
        "kind": kind,
        "path": str(args.path),
        "scope_hash": scope,
        "parsed": report.parsed,
        "written": report.written,
        "skipped": report.skipped,
        "by_type": report.by_type,
        "dry_run": report.dry_run,
    }, indent=2, ensure_ascii=False))
    return 0
```

### test_cli_import.py

```python
import json
from pathlib import Path

import pytest

from memoryd import cli


def test_cli_import_claude_md_dry_run(tmp_path, monkeypatch, capsys):
    md = tmp_path / "CLAUDE.md"
    md.write_text("## Foo\nbody one\n## Bar\nbody two\n")
    monkeypatch.setattr("memoryd.cli._data_root", lambda: tmp_path / "data")
    args = type("A", (), {
        "import_kind": "claude-md",
        "path": md,
        "scope": "h1",
        "dry_run": True,
        "force": False,
        "source_tag": None,
    })()
    rc = cli._cmd_import(args)
    assert rc == 0
    captured = capsys.readouterr().out
    parsed = json.loads(captured)
    assert parsed["parsed"] == 2
    assert parsed["dry_run"] is True


def test_cli_import_unknown_kind(monkeypatch, capsys):
    monkeypatch.setattr("memoryd.cli._data_root", lambda: Path("/tmp"))
    args = type("A", (), {
        "import_kind": "weird-kind",
        "path": Path("/x"),
        "scope": "h1",
        "dry_run": False, "force": False, "source_tag": None,
    })()
    rc = cli._cmd_import(args)
    assert rc == 2
```

### Steps

- [ ] cli.py 加 import 子命令树
- [ ] 2 CLI 集成测试
- [ ] CLI smoke：
  ```
  cd memoryd && uv run memoryd import claude-md --help
  uv run memoryd import auto-memory --help
  uv run memoryd import agents-md --help
  uv run memoryd import mcp-memory-service --help
  ```
- [ ] 全套 ~306 passed
- [ ] commit `plan8/task4: memoryd import CLI 子命令树`

---

## Task 5：memory-searcher sub-agent 模板 + install

**Files:**
- Create: `memoryd/src/memoryd/templates/memory-searcher.md`
- Modify: `memoryd/src/memoryd/setup.py`（加 install_memory_searcher）
- Modify: `memoryd/src/memoryd/cli.py`（加 setup install-memory-searcher 子命令）
- Create: `memoryd/tests/test_setup_memory_searcher.py`

### templates/memory-searcher.md

```markdown
---
name: memory-searcher
description: Fast read-only memory lookup. Use when the user asks about prior conversations, decisions, or context that may be stored in memoryd. Returns ≤ 500 token JSON.
model: claude-haiku-4-5-20251001
tools: Read, Grep
---

You are memoryd's lookup specialist. Your sole job: find relevant memories quickly and return a compact JSON response. Never invent content. Never write or modify files.

# How to find memories

1. The user's working directory determines scope. Memoryd stores data at `~/.local/share/memoryd/scopes/<scope_hash>/`.
2. Use Grep to search `.md` files for the user's query terms.
3. Read at most 5 matching .md files; pull frontmatter (title, type, triggers, created_at) and first ~200 chars of body.

# Sensitive scopes

Never read `.md.enc` files. If you find a `.memoryd-sensitive` marker in the path, report `{"sensitive": true}` for that scope and skip its content.

# Output format

Return a single JSON object, no prose, no markdown fences:

{
  "hits": [
    {
      "slug": "<slug>",
      "type": "session|decision|preference|fact|playbook|warning",
      "title": "<title from frontmatter>",
      "scope_hash": "<12-char hash>",
      "created_at": "<ISO>",
      "excerpt": "<= 150 chars from body>"
    }
  ],
  "total": <int>,
  "scope_used": "<the scope you searched>",
  "sensitive_skipped": ["<scope_hash>", ...]
}

Total response must be ≤ 500 tokens. If more than 5 hits, return top-5 by created_at descending + truncate excerpts.
```

### setup.py 加：

```python
def install_memory_searcher(
    target_dir: Path | None = None,
    *,
    force: bool = False,
) -> Path:
    """Copy memory-searcher.md template to ~/.claude/agents/ (or --target)."""
    src = Path(__file__).parent / "templates" / "memory-searcher.md"
    if not src.exists():
        raise FileNotFoundError(f"template missing: {src}")
    if target_dir is None:
        target_dir = Path.home() / ".claude" / "agents"
    target_dir.mkdir(parents=True, exist_ok=True)
    dst = target_dir / "memory-searcher.md"
    if dst.exists() and not force:
        raise FileExistsError(f"{dst} exists; use --force to overwrite")
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return dst
```

### cli.py 加子命令

```python
p_ims = setup_subs.add_parser("install-memory-searcher",
    help="copy memory-searcher.md template to ~/.claude/agents/")
p_ims.add_argument("--target", type=Path, default=None,
                   help="target directory; default ~/.claude/agents/")
p_ims.add_argument("--force", action="store_true")
p_ims.set_defaults(func=_cmd_install_memory_searcher)


def _cmd_install_memory_searcher(args):
    try:
        out = setup_mod.install_memory_searcher(
            target_dir=args.target, force=args.force
        )
    except FileExistsError as e:
        print(str(e), file=sys.stderr)
        return 1
    print(f"installed memory-searcher: {out}", file=sys.stderr)
    return 0
```

### test_setup_memory_searcher.py

```python
import pytest

from memoryd.setup import install_memory_searcher


def test_install_creates_file_in_target(tmp_path):
    target = tmp_path / ".claude" / "agents"
    out = install_memory_searcher(target_dir=target)
    assert out.exists()
    assert out.name == "memory-searcher.md"
    text = out.read_text()
    assert "memory-searcher" in text
    assert "claude-haiku" in text


def test_install_default_target_under_home(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    out = install_memory_searcher()
    assert out == tmp_path / ".claude" / "agents" / "memory-searcher.md"


def test_install_refuses_overwrite_without_force(tmp_path):
    target = tmp_path / "a"
    install_memory_searcher(target_dir=target)
    with pytest.raises(FileExistsError):
        install_memory_searcher(target_dir=target)


def test_install_overwrites_with_force(tmp_path):
    target = tmp_path / "a"
    out = install_memory_searcher(target_dir=target)
    out.write_text("# corrupted")
    out2 = install_memory_searcher(target_dir=target, force=True)
    assert "memory-searcher" in out2.read_text()
```

### Steps

- [ ] 写 memory-searcher.md 模板
- [ ] 改 setup.py
- [ ] 改 cli.py
- [ ] 4 测试
- [ ] CLI smoke：
  ```
  cd memoryd && uv run memoryd setup install-memory-searcher --target=/tmp/test-ms-install
  ls /tmp/test-ms-install/
  rm -rf /tmp/test-ms-install
  ```
- [ ] 全套 ~310 passed
- [ ] commit `plan8/task5: memory-searcher sub-agent 模板 + install-memory-searcher CLI`

---

## Task 6：README + execution-log + 收尾

**Files:**
- Modify: `memoryd/README.md`
- Create: `docs/superpowers/plans/2026-05-15-plan8-import-and-searcher.execution-log.txt`

README 加 "## Import + memory-searcher (Plan 8)" 章节：
- 4 个 import 子命令例子
- memory-searcher install + 怎么用
- Status 升 v0.8.0 — Import + memory-searcher (plan 8 of 8) **complete v1**

execution-log Phase 1：
- 真机 sample CLAUDE.md → import dry-run → import 实跑 → 看 .md 出现
- memory-searcher install + CC 重启 + 用户 prompt "找一下上次关于 X 的" 触发流程

完成判据：
- pytest ≥ 310 passed
- node test 12 passed
- CLI smoke 全部不报错
- macOS 真机 import sample 文件成功

commit + finishing-a-development-branch → PR → auto-merge → 整个 v1 完成
