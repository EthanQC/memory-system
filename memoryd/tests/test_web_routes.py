import pytest
from fastapi.testclient import TestClient

from memoryd.web import create_app


def _write_md(root, scope, type_, slug, body="x"):
    p = root / "scopes" / scope / type_ / f"{slug}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


def test_index_renders_with_token(tmp_path):
    _write_md(tmp_path, "h1", "sessions", "2026-05-15-hello")
    client = TestClient(create_app(token="t", data_root=tmp_path))
    r = client.get("/?token=t")
    assert r.status_code == 200
    assert "2026-05-15-hello" in r.text


def test_list_filters_by_type(tmp_path):
    _write_md(tmp_path, "h1", "sessions", "session-a")
    _write_md(tmp_path, "h1", "decisions", "decision-b")
    client = TestClient(create_app(token="t", data_root=tmp_path))
    r = client.get("/memories?type=sessions&token=t")
    assert r.status_code == 200
    assert "session-a" in r.text
    assert "decision-b" not in r.text


def test_list_filters_by_scope(tmp_path):
    _write_md(tmp_path, "h1", "sessions", "a-h1")
    _write_md(tmp_path, "h2", "sessions", "b-h2")
    client = TestClient(create_app(token="t", data_root=tmp_path))
    r = client.get("/memories?scope=h2&token=t")
    assert "a-h1" not in r.text
    assert "b-h2" in r.text


def test_detail_returns_body(tmp_path):
    _write_md(tmp_path, "h1", "sessions", "detail-z", body="my body content here")
    client = TestClient(create_app(token="t", data_root=tmp_path))
    r = client.get("/memories/detail-z?token=t")
    assert r.status_code == 200
    assert "my body content here" in r.text


def test_detail_404_unknown_slug(tmp_path):
    client = TestClient(create_app(token="t", data_root=tmp_path))
    r = client.get("/memories/missing?token=t")
    assert r.status_code == 404


def test_index_empty_when_no_scopes(tmp_path):
    client = TestClient(create_app(token="t", data_root=tmp_path))
    r = client.get("/?token=t")
    assert r.status_code == 200


def test_list_ignores_conflicts_dir(tmp_path):
    """_conflicts/ is Plan 6 backup; should not appear in web list."""
    _write_md(tmp_path, "h1", "sessions", "good")
    conf = tmp_path / "scopes" / "_conflicts"
    conf.mkdir(parents=True)
    (conf / "leaked.md").write_text("should not be visible")
    client = TestClient(create_app(token="t", data_root=tmp_path))
    r = client.get("/memories?token=t")
    assert "good" in r.text
    assert "leaked" not in r.text
