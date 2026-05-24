"""Regression guard for the cross-scope sentinel `scope="global"`.

Three independent surfaces (CLI, Web routes, MCP tools) historically each
re-implemented the "global" check; new code reliably forgot. These tests
lock in the behaviour: every public surface that accepts a scope must
return data from ALL scopes when given the sentinel.

Failure mode being prevented: silent empty result. The bug looked OK to
callers (no exception, `ok=True`) but returned 0 hits because SQL filtered
on `scope_hash = 'global'` which never matches.
"""
from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest


@pytest.fixture
def populated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Two memories in two distinct scopes — proves cross-scope queries work."""
    data_root = tmp_path / "data"
    data_root.mkdir()
    (data_root / "scopes" / "scope_a" / "decisions").mkdir(parents=True)
    (data_root / "scopes" / "scope_b" / "facts").mkdir(parents=True)

    # Two markdown files so ripgrep can find them
    (data_root / "scopes" / "scope_a" / "decisions" / "alpha.md").write_text(
        "---\nslug: alpha\ntype: decision\n---\nthe target keyword zebra\n",
        encoding="utf-8",
    )
    (data_root / "scopes" / "scope_b" / "facts" / "beta.md").write_text(
        "---\nslug: beta\ntype: fact\n---\nanother zebra mention here\n",
        encoding="utf-8",
    )

    # Initialize index from these files
    monkeypatch.setenv("MEMORYD_DATA_ROOT", str(data_root))
    from memoryd.index import open_index
    idx = open_index(data_root / "index.db")
    now = datetime.now(timezone.utc).isoformat()
    idx.conn.execute(
        "INSERT INTO memories (slug, type, scope_hash, title, source, created_at, "
        "fingerprint, body_path) VALUES (?,?,?,?,?,?,?,?)",
        ("alpha", "decision", "scope_a", "Alpha decision: zebra", "manual", now,
         "fp_a", "scopes/scope_a/decisions/alpha.md"),
    )
    idx.conn.execute(
        "INSERT INTO memories (slug, type, scope_hash, title, source, created_at, "
        "fingerprint, body_path) VALUES (?,?,?,?,?,?,?,?)",
        ("beta", "fact", "scope_b", "Beta fact about zebras", "manual", now,
         "fp_b", "scopes/scope_b/facts/beta.md"),
    )
    idx.conn.commit()
    idx.close()
    return data_root


def test_is_global_scope_helper_recognizes_all_aliases() -> None:
    from memoryd.mcp_tools.util import is_global_scope
    assert is_global_scope("global") is True
    assert is_global_scope("_global") is True
    assert is_global_scope("") is True  # internal alias used by some sites
    assert is_global_scope("scope_a") is False
    assert is_global_scope("auto") is False
    assert is_global_scope(None) is False


def test_mem_timeline_global_returns_cross_scope_entries(populated_db: Path) -> None:
    """The regression that prompted this test file: scope='global' returned []."""
    from memoryd.mcp_tools.memory import timeline
    result = asyncio.run(
        timeline(scope="global", since="2020-01-01T00:00:00Z", limit=20)
    )
    assert result["ok"] is True
    slugs = {e["slug"] for e in result["entries"]}
    assert "alpha" in slugs, "scope_a memory missing from global timeline"
    assert "beta" in slugs, "scope_b memory missing from global timeline"


def test_hybrid_search_global_walks_all_scope_dirs(populated_db: Path) -> None:
    """`scope='global'` in hybrid_search must glob scopes/ not scopes/global/."""
    from memoryd.search.hybrid import hybrid_search
    results = hybrid_search(
        query="zebra",
        scope_hash="global",
        top_k=5,
        data_root=populated_db,
    )
    slugs = {r.memory_id for r in results}
    # Both files contain "zebra" — ripgrep should pick up both across scopes
    assert "alpha" in slugs or "beta" in slugs, (
        f"global ripgrep found nothing from 2 scopes; got {slugs}"
    )


def test_search_sessions_now_matches_title(tmp_path: Path) -> None:
    """The other recent regression: title-only matches were dropped.

    Memory whose title contains the query but body doesn't repeat the term
    used to return 0 hits. After fix, title matches surface.
    """
    data_root = tmp_path / "data"
    scope_dir = data_root / "scopes" / "scope_x" / "decisions"
    scope_dir.mkdir(parents=True)
    md = scope_dir / "title-only.md"
    md.write_text(
        "---\nslug: title-only\ntype: decision\ntitle: working-hours-system 上线前 P0 清单\n---\n"
        "body has no mention of the keyword at all\n",
        encoding="utf-8",
    )
    # Register in index
    from memoryd.index import open_index
    idx = open_index(data_root / "index.db")
    idx.conn.execute(
        "INSERT INTO memories (slug, type, scope_hash, title, source, created_at, "
        "fingerprint, body_path) VALUES (?,?,?,?,?,?,?,?)",
        ("title-only", "decision", "scope_x",
         "working-hours-system 上线前 P0 清单", "manual",
         datetime.now(timezone.utc).isoformat(),
         "fp_x", "scopes/scope_x/decisions/title-only.md"),
    )
    idx.conn.commit()
    idx.close()
    from memoryd.search.sessions import search_sessions
    hits = search_sessions(data_root, "scope_x", "working-hours", limit=5)
    assert len(hits) == 1, f"title-only match dropped; got {hits}"
    assert hits[0].slug == "title-only"
