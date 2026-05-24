"""Tests for memoryd.handoff.reader."""
from __future__ import annotations

from pathlib import Path

from memoryd.handoff.reader import (
    find_handoff_path,
    list_dated_handoffs,
    read_local_handoff,
)


def test_find_handoff_returns_none_when_absent(tmp_path: Path):
    assert find_handoff_path(tmp_path) is None


def test_find_handoff_returns_path_when_present(tmp_path: Path):
    p = tmp_path / "HANDOFF.md"
    p.write_text("# h", encoding="utf-8")
    found = find_handoff_path(tmp_path)
    assert found == p


def test_read_local_handoff_returns_content(tmp_path: Path):
    (tmp_path / "HANDOFF.md").write_text("# header\nbody\n", encoding="utf-8")
    text = read_local_handoff(tmp_path)
    assert text == "# header\nbody\n"


def test_read_local_handoff_returns_none_when_absent(tmp_path: Path):
    assert read_local_handoff(tmp_path) is None


def test_read_local_handoff_clips_to_max_chars(tmp_path: Path):
    big = "x" * 5000
    (tmp_path / "HANDOFF.md").write_text(big, encoding="utf-8")
    text = read_local_handoff(tmp_path, max_chars=100)
    assert text is not None
    # Clipped + truncation marker
    assert len(text) < 200
    assert "truncated" in text


def test_list_dated_handoffs_sorts_newest_first(tmp_path: Path):
    (tmp_path / "HANDOFF-2026-05-20.md").write_text("a", encoding="utf-8")
    (tmp_path / "HANDOFF-2026-05-22.md").write_text("b", encoding="utf-8")
    (tmp_path / "HANDOFF-2026-05-19.md").write_text("c", encoding="utf-8")
    # Non-matching files should be ignored
    (tmp_path / "HANDOFF.md").write_text("canonical", encoding="utf-8")
    (tmp_path / "NOTES.md").write_text("misc", encoding="utf-8")
    (tmp_path / "HANDOFF-bad.md").write_text("x", encoding="utf-8")

    listing = list_dated_handoffs(tmp_path)
    assert [r["date"] for r in listing] == ["2026-05-22", "2026-05-20", "2026-05-19"]


def test_list_dated_handoffs_empty_dir_returns_empty(tmp_path: Path):
    assert list_dated_handoffs(tmp_path) == []
