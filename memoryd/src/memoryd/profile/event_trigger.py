"""Event-triggered profile rewrite.

The weekly cron (Sun 02:00) is the primary mechanism for keeping
``identity.md`` fresh. But power users can accumulate dozens of new
long-term memories within hours, leaving identity.md stale until the
next Sunday. This module adds an event-driven complement:

    auto-promote / manual-promote N times since last rewrite
        ⇒ fork-and-forget ``memoryd profile rewrite --on-event``

The N threshold is read from env ``MEMORYD_PROFILE_REWRITE_THRESHOLD``
(default 10). Set to ``0`` (or any non-positive number) to disable —
weekly cron remains the only trigger.

State persists in ``<memory_root>/.profile_rewrite_pending`` as a plain
integer string. The counter resets to 0 when we fork a rewrite. Failures
to read/write the marker degrade gracefully (counter is best-effort).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

_MARKER_NAME = ".profile_rewrite_pending"
_DEFAULT_THRESHOLD = 10


def _read_threshold() -> int:
    raw = os.environ.get("MEMORYD_PROFILE_REWRITE_THRESHOLD")
    if raw is None or raw == "":
        return _DEFAULT_THRESHOLD
    try:
        return int(raw)
    except ValueError:
        return _DEFAULT_THRESHOLD


def _marker_path(memory_root: Path) -> Path:
    return memory_root / _MARKER_NAME


def _read_counter(marker: Path) -> int:
    try:
        text = marker.read_text(encoding="utf-8").strip()
        return int(text) if text else 0
    except (OSError, ValueError):
        return 0


def _write_counter(marker: Path, value: int) -> None:
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(str(value), encoding="utf-8")
    except OSError:
        # Counter is best-effort. If we cannot persist, the next call
        # restarts from 0 — at worst the trigger fires later than ideal.
        pass


def record_and_check(memory_root: Path, increment: int) -> int | None:
    """Add ``increment`` to the pending-rewrite counter. Return the
    counter value when the threshold is met (and reset to 0), else None.

    Returns None when:
      - threshold is disabled (``<= 0``)
      - increment is non-positive
      - counter has not yet reached threshold

    The single source of truth is the marker file under ``memory_root``,
    so concurrent writers race but never corrupt data — worst case is a
    duplicate trigger or a delayed one, both of which are harmless.
    """
    if increment <= 0:
        return None
    threshold = _read_threshold()
    if threshold <= 0:
        return None
    marker = _marker_path(memory_root)
    new_value = _read_counter(marker) + increment
    if new_value >= threshold:
        _write_counter(marker, 0)
        return new_value
    _write_counter(marker, new_value)
    return None


def spawn_rewrite_if_due(memory_root: Path, increment: int) -> bool:
    """Call ``record_and_check`` and, if threshold met, fork
    ``memoryd profile rewrite --on-event`` in the background.

    Fire-and-forget: never blocks, never raises. Returns True iff the
    subprocess was actually spawned.
    """
    triggered = record_and_check(memory_root, increment)
    if triggered is None:
        return False
    memoryd_bin = shutil.which("memoryd") or sys.executable
    try:
        subprocess.Popen(
            [memoryd_bin, "profile", "rewrite", "--on-event"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return True
    except OSError:
        # Fork failure (PATH / fd / etc) — counter already reset, next
        # cycle will retry naturally.
        return False
