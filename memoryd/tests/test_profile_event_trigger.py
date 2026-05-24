"""Tests for memoryd.profile.event_trigger.

Covers:
- counter accumulation across multiple record_and_check calls
- threshold trip resets counter to 0 and returns the trip value
- env override of the threshold (set high, set low, disable with 0)
- non-positive increment is a no-op
- spawn_rewrite_if_due actually forks `memoryd profile rewrite --on-event`
- subprocess failure does not raise (graceful)
"""
from __future__ import annotations

from pathlib import Path

import pytest

from memoryd.profile import event_trigger


@pytest.fixture
def memory_root(tmp_path: Path) -> Path:
    return tmp_path / "data"


def test_below_threshold_returns_none(memory_root, monkeypatch):
    monkeypatch.setenv("MEMORYD_PROFILE_REWRITE_THRESHOLD", "10")
    assert event_trigger.record_and_check(memory_root, 3) is None
    assert event_trigger.record_and_check(memory_root, 5) is None
    # Counter persisted across calls
    assert (memory_root / ".profile_rewrite_pending").read_text() == "8"


def test_threshold_trip_returns_count_and_resets(memory_root, monkeypatch):
    monkeypatch.setenv("MEMORYD_PROFILE_REWRITE_THRESHOLD", "10")
    event_trigger.record_and_check(memory_root, 7)
    tripped = event_trigger.record_and_check(memory_root, 4)
    assert tripped == 11           # ≥ threshold returns actual counter
    # Marker reset to 0 after trip
    assert (memory_root / ".profile_rewrite_pending").read_text() == "0"
    # Next small increment again below threshold
    assert event_trigger.record_and_check(memory_root, 1) is None


def test_threshold_zero_disables(memory_root, monkeypatch):
    monkeypatch.setenv("MEMORYD_PROFILE_REWRITE_THRESHOLD", "0")
    assert event_trigger.record_and_check(memory_root, 9999) is None
    # Marker not even created when feature disabled
    assert not (memory_root / ".profile_rewrite_pending").exists()


def test_negative_threshold_disables(memory_root, monkeypatch):
    monkeypatch.setenv("MEMORYD_PROFILE_REWRITE_THRESHOLD", "-5")
    assert event_trigger.record_and_check(memory_root, 9999) is None


def test_nonpositive_increment_noop(memory_root, monkeypatch):
    monkeypatch.setenv("MEMORYD_PROFILE_REWRITE_THRESHOLD", "10")
    assert event_trigger.record_and_check(memory_root, 0) is None
    assert event_trigger.record_and_check(memory_root, -3) is None
    # No marker written
    assert not (memory_root / ".profile_rewrite_pending").exists()


def test_invalid_env_falls_back_to_default(memory_root, monkeypatch):
    monkeypatch.setenv("MEMORYD_PROFILE_REWRITE_THRESHOLD", "not-a-number")
    # Default 10
    assert event_trigger.record_and_check(memory_root, 9) is None
    assert event_trigger.record_and_check(memory_root, 2) == 11


def test_threshold_env_unset_uses_default(memory_root, monkeypatch):
    monkeypatch.delenv("MEMORYD_PROFILE_REWRITE_THRESHOLD", raising=False)
    assert event_trigger.record_and_check(memory_root, 9) is None
    assert event_trigger.record_and_check(memory_root, 1) == 10


def test_spawn_rewrite_if_due_below_threshold_no_fork(memory_root, monkeypatch):
    monkeypatch.setenv("MEMORYD_PROFILE_REWRITE_THRESHOLD", "10")
    calls = []
    monkeypatch.setattr(
        event_trigger.subprocess,
        "Popen",
        lambda *a, **kw: calls.append((a, kw)) or object(),
    )
    assert event_trigger.spawn_rewrite_if_due(memory_root, 5) is False
    assert calls == []


def test_spawn_rewrite_if_due_at_threshold_forks(memory_root, monkeypatch):
    monkeypatch.setenv("MEMORYD_PROFILE_REWRITE_THRESHOLD", "5")
    calls = []
    monkeypatch.setattr(
        event_trigger.subprocess,
        "Popen",
        lambda *a, **kw: calls.append((a, kw)) or object(),
    )
    assert event_trigger.spawn_rewrite_if_due(memory_root, 5) is True
    assert len(calls) == 1
    cmd = calls[0][0][0]
    # Trailing args must include the on-event sub-command flag
    assert cmd[-3:] == ["profile", "rewrite", "--on-event"]
    # Counter reset
    assert (memory_root / ".profile_rewrite_pending").read_text() == "0"


def test_spawn_rewrite_if_due_oserror_returns_false(memory_root, monkeypatch):
    monkeypatch.setenv("MEMORYD_PROFILE_REWRITE_THRESHOLD", "5")

    def boom(*a, **kw):
        raise OSError("fork limit")

    monkeypatch.setattr(event_trigger.subprocess, "Popen", boom)
    # Should not raise
    assert event_trigger.spawn_rewrite_if_due(memory_root, 10) is False


def test_marker_unreadable_starts_from_zero(memory_root, monkeypatch):
    """If the marker file exists but contains garbage, treat as 0."""
    monkeypatch.setenv("MEMORYD_PROFILE_REWRITE_THRESHOLD", "10")
    memory_root.mkdir(parents=True)
    (memory_root / ".profile_rewrite_pending").write_text("garbage\n")
    # Should not raise; treats garbage as 0 and accumulates
    assert event_trigger.record_and_check(memory_root, 4) is None
    assert (memory_root / ".profile_rewrite_pending").read_text() == "4"
