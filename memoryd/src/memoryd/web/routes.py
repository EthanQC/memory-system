"""Browse-only routes for the memoryd web dashboard."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    templates = request.app.state.templates
    data_root = request.app.state.data_root
    recent = _recent(data_root, limit=20)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "recent": recent,
            "token": request.app.state.token,
        },
    )


@router.get("/memories", response_class=HTMLResponse)
async def list_memories(
    request: Request,
    type: str | None = None,
    scope: str | None = None,
    page: int = 1,
):
    data_root = request.app.state.data_root
    items = _list_memories(data_root, type=type, scope=scope, page=page)
    return request.app.state.templates.TemplateResponse(
        request,
        "list.html",
        {
            "items": items,
            "type": type,
            "scope": scope,
            "page": page,
            "token": request.app.state.token,
        },
    )


@router.get("/memories/{slug}", response_class=HTMLResponse)
async def detail(request: Request, slug: str):
    data_root = request.app.state.data_root
    info = _resolve_memory(data_root, slug)
    if info is None:
        raise HTTPException(404, detail="not found")
    if info["sensitive"]:
        raise HTTPException(403, detail="sensitive scope; use CLI")
    return request.app.state.templates.TemplateResponse(
        request,
        "detail.html",
        {
            "memory": info,
            "token": request.app.state.token,
        },
    )


# --- helpers ---

def _recent(data_root: Path, limit: int):
    """List recent memories across all scopes (raw .md only)."""
    from memoryd.scope_meta import is_path_sensitive
    items: list[dict] = []
    scopes = data_root / "scopes"
    if not scopes.exists():
        return items
    for md in scopes.rglob("*.md"):
        if md.name.startswith("."):
            continue
        # ignore _conflicts/ entries (Plan 6)
        parts = md.relative_to(scopes).parts
        if not parts or parts[0].startswith("_"):
            continue
        scope_hash = parts[0]
        # type inferred from parent dir: scopes/<hash>/<type>/<slug>.md
        # for free-form files directly under <hash>, type = "memory"
        type_ = parts[1] if len(parts) >= 3 else "memory"
        slug = md.stem
        sensitive = is_path_sensitive(md.parent)
        items.append({
            "slug": slug,
            "type": type_,
            "scope_hash": scope_hash,
            "title": slug,
            "sensitive": sensitive,
            "path": str(md),
        })
    items.sort(key=lambda x: x["slug"], reverse=True)
    return items[:limit]


def _list_memories(data_root: Path, *, type=None, scope=None,
                   page=1, per_page=50):
    all_ = _recent(data_root, limit=10_000)
    if type:
        all_ = [x for x in all_ if x["type"] == type]
    if scope:
        all_ = [x for x in all_ if x["scope_hash"] == scope]
    start = (page - 1) * per_page
    return all_[start : start + per_page]


def _resolve_memory(data_root: Path, slug: str) -> dict | None:
    """Find a .md by slug across all scopes/types."""
    from memoryd.scope_meta import is_path_sensitive
    scopes = data_root / "scopes"
    if not scopes.exists():
        return None
    for md in scopes.rglob(f"{slug}.md"):
        parts = md.relative_to(scopes).parts
        if not parts or parts[0].startswith("_"):
            continue
        sensitive = is_path_sensitive(md.parent)
        if sensitive:
            return {"slug": slug, "sensitive": True, "path": str(md)}
        text = md.read_text(encoding="utf-8")
        return {"slug": slug, "sensitive": False, "path": str(md), "body": text}
    return None
