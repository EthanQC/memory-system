"""Tests for codex_agents auto-injection.

Covers the 3 behaviours that must hold:
1. Fresh install creates AGENTS.md with BEGIN/END markers + identity body
2. Repeat install replaces the block in-place (idempotent, no duplication)
3. Uninstall strips only the marked block, leaving surrounding text intact
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from memoryd.codex_agents import (
    install_codex_agents_include,
    render_codex_block,
    uninstall_codex_agents_include,
    _BEGIN,
    _END,
)


@pytest.fixture
def codex_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated ~/.codex/ + memoryd data root for each test."""
    cdx = tmp_path / "codex"
    cdx.mkdir()
    data = tmp_path / "memoryd-data"
    data.mkdir()
    monkeypatch.setenv("MEMORYD_DATA_ROOT", str(data))
    return cdx


def test_render_block_contains_markers(codex_dir: Path) -> None:
    block = render_codex_block(data_root=Path(os.environ["MEMORYD_DATA_ROOT"]))
    assert block.startswith(_BEGIN)
    assert block.rstrip().endswith(_END)
    # Always carries a timestamp hint so users can see when it last refreshed
    assert "memoryd refreshes" in block


def test_install_creates_new_agents_md(codex_dir: Path) -> None:
    target = install_codex_agents_include(codex_dir=codex_dir)
    assert target == codex_dir / "AGENTS.md"
    text = target.read_text(encoding="utf-8")
    assert _BEGIN in text
    assert _END in text
    # New file gets the project header so users know what owns this file
    assert "memoryd 自动维护" in text


def test_install_preserves_user_content_around_block(codex_dir: Path) -> None:
    target = codex_dir / "AGENTS.md"
    target.write_text(
        "# My AGENTS\n\nMy own rules here.\n\n## Section B\n\nMore content.\n",
        encoding="utf-8",
    )
    install_codex_agents_include(codex_dir=codex_dir)
    text = target.read_text(encoding="utf-8")
    # User's original content survives unchanged
    assert "# My AGENTS" in text
    assert "My own rules here." in text
    assert "## Section B" in text
    assert "More content." in text
    # And the memoryd block is appended
    assert _BEGIN in text
    assert _END in text


def test_install_is_idempotent(codex_dir: Path) -> None:
    """Running install twice must NOT duplicate the block."""
    target = install_codex_agents_include(codex_dir=codex_dir)
    text1 = target.read_text(encoding="utf-8")
    install_codex_agents_include(codex_dir=codex_dir)
    text2 = target.read_text(encoding="utf-8")
    # Both runs land the same single block (timestamps may differ)
    assert text2.count(_BEGIN) == 1
    assert text2.count(_END) == 1
    # And the surrounding scaffolding stays semantically identical
    # (whitespace may collapse / expand but the user-facing text is unchanged)
    pre1 = text1.split(_BEGIN)[0].strip()
    pre2 = text2.split(_BEGIN)[0].strip()
    assert pre1 == pre2


def test_uninstall_strips_block_only(codex_dir: Path) -> None:
    target = codex_dir / "AGENTS.md"
    target.write_text(
        "# Keep me\n\nUser content.\n",
        encoding="utf-8",
    )
    install_codex_agents_include(codex_dir=codex_dir)
    assert _BEGIN in target.read_text(encoding="utf-8")

    removed = uninstall_codex_agents_include(codex_dir=codex_dir)
    assert removed is True
    text = target.read_text(encoding="utf-8")
    # User content stays
    assert "# Keep me" in text
    assert "User content." in text
    # memoryd block gone
    assert _BEGIN not in text
    assert _END not in text


def test_uninstall_when_no_block_returns_false(codex_dir: Path) -> None:
    target = codex_dir / "AGENTS.md"
    target.write_text("# No memoryd here\n", encoding="utf-8")
    removed = uninstall_codex_agents_include(codex_dir=codex_dir)
    assert removed is False
    # File untouched
    assert target.read_text(encoding="utf-8") == "# No memoryd here\n"


def test_uninstall_when_file_missing_returns_false(codex_dir: Path) -> None:
    """No ~/.codex/AGENTS.md at all → silent no-op, not error."""
    removed = uninstall_codex_agents_include(codex_dir=codex_dir)
    assert removed is False


def test_install_creates_codex_dir_if_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Even if user hasn't bootstrapped Codex yet, install must succeed."""
    fresh_codex = tmp_path / "never-existed"
    monkeypatch.setenv("MEMORYD_DATA_ROOT", str(tmp_path / "data"))
    (tmp_path / "data").mkdir()
    target = install_codex_agents_include(codex_dir=fresh_codex)
    assert target.exists()
    assert target.parent == fresh_codex
