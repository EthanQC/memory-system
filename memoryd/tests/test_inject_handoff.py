"""Tests for inject.render_session_context HANDOFF integration.

Goal: when the caller's cwd contains a HANDOFF.md, SessionStart inject
surfaces it as a quoted block at the top of the context. When absent,
inject behaves identically to before.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from memoryd.index import open_index
from memoryd.inject import render_session_context, _EMPTY_FALLBACK


@pytest.fixture
def empty_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("MEMORYD_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("MEMORYD_PROFILE_DIR", str(tmp_path / "data" / "profile"))
    open_index(tmp_path / "data" / "index.db").close()
    return tmp_path


def test_inject_surfaces_local_handoff(empty_root: Path):
    project = empty_root / "myrepo"
    project.mkdir()
    (project / "HANDOFF.md").write_text(
        "# HANDOFF — myrepo (2026-05-24)\n## TL;DR\nA project.\n",
        encoding="utf-8",
    )
    text = render_session_context(cwd=project)
    assert "本项目 HANDOFF.md" in text
    assert "myrepo" in text
    assert "A project." in text


def test_inject_without_handoff_falls_back_when_db_empty(empty_root: Path):
    """No HANDOFF + empty memory data → empty fallback."""
    project = empty_root / "noh"
    project.mkdir()
    text = render_session_context(cwd=project)
    assert text == _EMPTY_FALLBACK


def test_inject_handoff_clipped_when_oversized(empty_root: Path):
    project = empty_root / "big"
    project.mkdir()
    (project / "HANDOFF.md").write_text("# huge\n" + "x" * 10000, encoding="utf-8")
    text = render_session_context(cwd=project, handoff_max_chars=200)
    # Truncation marker from reader.py
    assert "truncated" in text


def test_inject_handoff_block_comes_before_identity(empty_root: Path):
    """HANDOFF should appear above identity (project state > long-term profile)."""
    profile = empty_root / "data" / "profile"
    profile.mkdir(parents=True, exist_ok=True)
    (profile / "identity.md").write_text("# 画像\nabble 是个开发者", encoding="utf-8")

    project = empty_root / "p"
    project.mkdir()
    (project / "HANDOFF.md").write_text("# HANDOFF\n## TL;DR\nfoo", encoding="utf-8")

    text = render_session_context(cwd=project)
    pos_handoff = text.find("本项目 HANDOFF.md")
    pos_identity = text.find("画像摘要")
    assert pos_handoff >= 0
    assert pos_identity >= 0
    assert pos_handoff < pos_identity


def test_inject_never_raises_on_unreadable_handoff(empty_root: Path, monkeypatch):
    """Hook contract: inject must NEVER raise even if HANDOFF.md exists but errors."""
    project = empty_root / "p"
    project.mkdir()
    (project / "HANDOFF.md").write_text("ok", encoding="utf-8")

    # Force the reader to blow up
    import memoryd.handoff as hpkg
    def boom(*a, **kw):
        raise RuntimeError("disk on fire")
    monkeypatch.setattr(hpkg, "read_local_handoff", boom)

    text = render_session_context(cwd=project)
    # Must not raise; output is either fallback or normal content sans HANDOFF
    assert isinstance(text, str)
