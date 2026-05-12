"""Schema roundtrip tests."""
from datetime import datetime

import pytest
import yaml

from memoryd.schema import SessionMemory, Frontmatter


def test_frontmatter_required_fields():
    fm = Frontmatter(
        title="周一项目讨论",
        slug="2026-05-09-monday-discussion",
        type="session",
        scope_hash="abc123",
        triggers=["项目", "logo"],
        source="claude-code",
        created_at=datetime(2026, 5, 9, 9, 30),
    )
    assert fm.title == "周一项目讨论"
    assert fm.type == "session"
    assert "项目" in fm.triggers


def test_session_to_markdown_roundtrip():
    """Write a session to markdown text and parse it back."""
    session = SessionMemory(
        frontmatter=Frontmatter(
            title="测试会话",
            slug="2026-05-09-test",
            type="session",
            scope_hash="abc123",
            triggers=["test"],
            source="claude-code",
            created_at=datetime(2026, 5, 9, 12, 0),
        ),
        body="## 摘要\n用户问 X，回答 Y。\n",
    )
    md_text = session.to_markdown()
    parsed = SessionMemory.from_markdown(md_text)
    assert parsed.frontmatter.title == "测试会话"
    assert parsed.frontmatter.triggers == ["test"]
    assert "用户问 X" in parsed.body


def test_from_markdown_rejects_missing_frontmatter():
    """Markdown without frontmatter should raise ValueError."""
    with pytest.raises(ValueError, match="frontmatter"):
        SessionMemory.from_markdown("## just a body\n\nno fm here.\n")
