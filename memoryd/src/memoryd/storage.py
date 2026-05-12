"""Markdown file storage for memory entries.

Layout:
    <root>/scopes/<scope_hash>/sessions/<slug>.md
"""
from __future__ import annotations

from pathlib import Path

from .schema import SessionMemory


def _scope_dir(root: Path, scope_hash: str) -> Path:
    return root / "scopes" / scope_hash / "sessions"


def save_session(root: Path, session: SessionMemory) -> Path:
    """Write a session to <root>/scopes/<hash>/sessions/<slug>.md.

    Returns the path written. Creates parent dirs as needed.
    """
    scope_dir = _scope_dir(root, session.frontmatter.scope_hash)
    scope_dir.mkdir(parents=True, exist_ok=True)
    path = scope_dir / f"{session.frontmatter.slug}.md"
    path.write_text(session.to_markdown(), encoding="utf-8")
    return path


def load_session(path: Path) -> SessionMemory:
    """Parse a markdown file at `path` back into a SessionMemory."""
    text = path.read_text(encoding="utf-8")
    return SessionMemory.from_markdown(text)


def list_sessions(root: Path, scope_hash: str) -> list[Path]:
    """List all session markdown files for a given scope."""
    scope_dir = _scope_dir(root, scope_hash)
    if not scope_dir.exists():
        return []
    return sorted(scope_dir.glob("*.md"))
