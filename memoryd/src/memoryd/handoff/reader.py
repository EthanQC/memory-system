"""Read HANDOFF files from a project directory.

HANDOFF.md lives in the **project root** (cwd of the AI session),
unlike memoryd's user-level memories under ``~/.local/share/memoryd``.
This module knows where to look and supports dated snapshot variants
(``HANDOFF-2026-05-20.md``).

Used by:
- ``memoryd handoff read`` CLI
- ``memoryd handoff list`` CLI
- ``inject.py`` to surface the local HANDOFF to SessionStart hooks
"""
from __future__ import annotations

import re
from pathlib import Path


_DATED_HANDOFF_RE = re.compile(r"^HANDOFF-(\d{4}-\d{2}-\d{2})\.md$")


def find_handoff_path(cwd: Path) -> Path | None:
    """Return the canonical HANDOFF.md path if it exists, else None.

    Only considers ``cwd/HANDOFF.md`` — does **not** walk up the tree.
    The convention is per-project, and walking would surface a parent's
    HANDOFF in unrelated sub-projects.
    """
    candidate = cwd / "HANDOFF.md"
    return candidate if candidate.exists() else None


def read_local_handoff(cwd: Path, max_chars: int | None = None) -> str | None:
    """Return the content of ``cwd/HANDOFF.md``, or None if absent.

    Optionally clip to ``max_chars`` (useful for inject contexts that
    have to fit alongside the rest of the prompt budget).
    """
    p = find_handoff_path(cwd)
    if p is None:
        return None
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return None
    if max_chars is not None and len(text) > max_chars:
        return text[:max_chars].rstrip() + "\n\n_(truncated, see HANDOFF.md)_"
    return text


def list_dated_handoffs(cwd: Path) -> list[dict[str, str]]:
    """Return dated snapshot files in cwd (HANDOFF-YYYY-MM-DD.md), newest first.

    Returns ``[{"date": "2026-05-20", "path": "/.../HANDOFF-2026-05-20.md"}, ...]``.
    """
    out: list[dict[str, str]] = []
    try:
        entries = list(cwd.iterdir())
    except OSError:
        return out
    for p in entries:
        if not p.is_file():
            continue
        m = _DATED_HANDOFF_RE.match(p.name)
        if not m:
            continue
        out.append({"date": m.group(1), "path": str(p.resolve())})
    out.sort(key=lambda r: r["date"], reverse=True)
    return out
