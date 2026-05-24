"""HANDOFF.md generation + reading.

Public surface:

- :func:`generate_handoff` — produce a 6-block HANDOFF markdown body
  from the user's recent memoryd signals (LLM-rewritten by default,
  with a deterministic fallback)
- :func:`read_local_handoff` — read ``cwd/HANDOFF.md`` for inject use
- :func:`find_handoff_path` — locate canonical HANDOFF in a cwd
- :func:`list_dated_handoffs` — enumerate dated snapshot files
- :func:`gather_signals` — raw signals only (no LLM), exposed for tests
  and debugging
"""
from .generator import gather_signals, generate_handoff
from .reader import find_handoff_path, list_dated_handoffs, read_local_handoff

__all__ = [
    "find_handoff_path",
    "gather_signals",
    "generate_handoff",
    "list_dated_handoffs",
    "read_local_handoff",
]
