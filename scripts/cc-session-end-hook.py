#!/usr/bin/env python3
"""Cross-platform Claude Code SessionEnd hook for memoryd.

Reads CLAUDE_CODE_TRANSCRIPT_PATH (or first argv) and invokes
`memoryd capture --client claude-code --transcript <path>`.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys


def main() -> int:
    path = os.environ.get("CLAUDE_CODE_TRANSCRIPT_PATH") or (
        sys.argv[1] if len(sys.argv) > 1 else ""
    )
    if not path:
        return 0  # nothing to capture
    memoryd_bin = shutil.which("memoryd") or "memoryd"
    cmd = [
        memoryd_bin,
        "capture",
        "--client",
        "claude-code",
        "--transcript",
        path,
    ]
    try:
        subprocess.run(cmd, check=False, timeout=30)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
