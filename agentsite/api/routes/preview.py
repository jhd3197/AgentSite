"""Serve generated sites for live preview in iframe."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response

from ...engine.watch import inject_watch_script
from ..deps import get_page_repo, get_pm, get_version_repo

logger = logging.getLogger("agentsite.api.preview")

router = APIRouter(prefix="/preview", tags=["preview"])

# Root-level routes for watcher support assets. Registered separately because
# they must live OUTSIDE the /preview prefix — injected scripts resolve them
# from arbitrary depths like /preview/{id}/app/ or /preview/{id}/{slug}/v/1/.
root_router = APIRouter(tags=["preview"])

_AXE_PATH = Path(__file__).resolve().parent.parent.parent / "assets" / "vendor" / "axe.min.js"


@root_router.get("/_agentsite/axe.min.js")
async def serve_axe():
    """Serve the vendored axe-core used by the injected a11y scanner."""
    if not _AXE_PATH.exists():
        raise HTTPException(status_code=404, detail="axe-core not vendored")
    return FileResponse(_AXE_PATH, media_type="application/javascript")

# MIME type mapping
_MIME_TYPES = {
    ".html": "text/html",
    ".css": "text/css",
    ".scss": "text/x-scss",
    ".js": "application/javascript",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
}


def _find_latest_version(pm, project_id: str, slug: str) -> int | None:
    """Find the highest version number that has files on disk."""
    page_dir = pm.page_dir(project_id, slug)
    if not page_dir.exists():
        return None
    versions = []
    for d in page_dir.iterdir():
        if d.is_dir() and d.name.startswith("v"):
            try:
                versions.append(int(d.name[1:]))
            except ValueError:
                continue
    return max(versions) if versions else None


@router.get("/{project_id}/assets/{filename:path}")
async def preview_asset(project_id: str, filename: str, pm=Depends(get_pm)):
    """Serve an asset file from the project assets directory."""
    assets_dir = pm.assets_dir(project_id)
    target = assets_dir / filename

    # Prevent path traversal
    try:
        target.resolve().relative_to(assets_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied") from None

    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail=f"Asset not found: {filename}")

    suffix = target.suffix.lower()
    media_type = _MIME_TYPES.get(suffix, "application/octet-stream")
    return FileResponse(target, media_type=media_type)


# -- Project-mode workspace serving (must register before /{slug} routes) --

_WORKSPACE_HIDDEN = {".git", ".agentsite", "node_modules"}


def _workspace_serve_root(pm, project_id: str):
    """Resolve (serve_root, template, built) for a project workspace.

    Node templates serve the build output dir once it exists ("built");
    static templates serve the workspace root directly (always "built").
    """
    from ...engine.workspace import WorkspaceManager

    ws = WorkspaceManager(pm.project_dir(project_id))
    template = ws.template()
    if template is not None and template.kind == "node":
        out = ws.workspace_dir / (template.output_dir or "dist")
        if out.exists():
            return out, template, True
        return ws.workspace_dir, template, False
    return ws.workspace_dir, template, True


_NOT_BUILT_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Not built yet</title>
<style>body{font-family:system-ui;display:grid;place-items:center;height:100vh;margin:0;
background:#0b0d12;color:#9aa4b2}div{text-align:center}h1{font-size:18px;color:#e6e9ee}</style>
</head><body><div><h1>Project not built yet</h1>
<p>Run a generation — the preview appears after the first successful build.</p></div></body></html>"""


@router.get("/{project_id}/verify/{path:path}")
async def preview_verify_artifact(project_id: str, path: str, pm=Depends(get_pm)):
    """Serve verification artifacts (screenshots) from .agentsite/verify/."""
    from ...engine.workspace import WorkspaceManager

    verify_root = WorkspaceManager(pm.project_dir(project_id)).workspace_dir / ".agentsite" / "verify"
    target = verify_root / path
    try:
        target.resolve().relative_to(verify_root.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied") from None
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")
    media_type = _MIME_TYPES.get(target.suffix.lower(), "application/octet-stream")
    return FileResponse(target, media_type=media_type)


@router.get("/{project_id}/app")
async def preview_app_redirect(project_id: str):
    """Redirect to the trailing-slash form so relative asset paths resolve."""
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url=f"/preview/{project_id}/app/")


@router.get("/{project_id}/app/{path:path}")
async def preview_app_file(project_id: str, path: str, pm=Depends(get_pm)):
    """Serve a file from the project workspace (built output when present)."""
    root, template, built = _workspace_serve_root(pm, project_id)
    if not root.exists():
        raise HTTPException(status_code=404, detail="Workspace not found")

    rel = path or (template.entry if template else "index.html")
    if rel.endswith("/"):
        rel += "index.html"

    # Unbuilt node project: the source index.html references JSX modules
    # the browser can't run — show a placeholder until the first build.
    if not built:
        if not path or rel.endswith((".html", ".htm")):
            return Response(content=_NOT_BUILT_HTML, media_type="text/html")
        raise HTTPException(status_code=404, detail="Project not built yet")

    target = root / rel
    try:
        target.resolve().relative_to(root.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied") from None
    if any(part in _WORKSPACE_HIDDEN for part in Path(rel).parts):
        raise HTTPException(status_code=403, detail="Access denied")

    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {rel}")

    suffix = target.suffix.lower()
    media_type = _MIME_TYPES.get(suffix, "application/octet-stream")
    if suffix in (".html", ".htm"):
        # Inject the live-preview watcher so post-build browsing feeds the
        # friction report back to the agents.
        try:
            html = target.read_text(encoding="utf-8", errors="replace")
            return Response(
                content=inject_watch_script(html),
                media_type="text/html",
                headers={"Cache-Control": "no-store"},
            )
        except Exception:
            logger.warning("Watch injection failed for %s — serving raw", rel, exc_info=True)
    return FileResponse(target, media_type=media_type, headers=None)


@router.get("/{project_id}/{slug}")
async def preview_page_latest(
    project_id: str,
    slug: str,
    pm=Depends(get_pm),
    page_repo=Depends(get_page_repo),
    version_repo=Depends(get_version_repo),
):
    """Serve the index.html of the latest version of a page."""
    # Cross-check: page must exist in DB to prevent serving stale files
    page = await page_repo.get_by_slug(project_id, slug)
    if page is None:
        raise HTTPException(status_code=404, detail=f"Page '{slug}' not found")
    version = _find_latest_version(pm, project_id, slug)
    if version is None:
        # Try DB fallback: find latest version from DB
        latest_ver = await version_repo.get_latest(page.id)
        if latest_ver and latest_ver.files:
            version = latest_ver.version_number
        else:
            raise HTTPException(status_code=404, detail=f"No versions found for page '{slug}'")
    return await _serve_version_file(pm, project_id, slug, version, "index.html", page_repo, version_repo)


@router.get("/{project_id}/{slug}/v/{version:int}")
async def preview_page_version(
    project_id: str,
    slug: str,
    version: int,
    pm=Depends(get_pm),
    page_repo=Depends(get_page_repo),
    version_repo=Depends(get_version_repo),
):
    """Serve the index.html of a specific version."""
    return await _serve_version_file(pm, project_id, slug, version, "index.html", page_repo, version_repo)


@router.get("/{project_id}/{slug}/v/{version:int}/{path:path}")
async def preview_version_file(
    project_id: str,
    slug: str,
    version: int,
    path: str,
    pm=Depends(get_pm),
    page_repo=Depends(get_page_repo),
    version_repo=Depends(get_version_repo),
):
    """Serve any file from a specific page version."""
    return await _serve_version_file(pm, project_id, slug, version, path, page_repo, version_repo)


async def _serve_version_file(pm, project_id: str, slug: str, version: int, path: str, page_repo=None, version_repo=None):
    """Resolve and serve a file from a version directory, with DB fallback."""
    vdir = pm.version_dir(project_id, slug, version)
    target = vdir / path

    # Prevent path traversal
    try:
        target.resolve().relative_to(vdir.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")

    if target.exists() and target.is_file():
        suffix = target.suffix.lower()
        media_type = _MIME_TYPES.get(suffix, "application/octet-stream")
        if suffix in (".html", ".htm"):
            try:
                html = target.read_text(encoding="utf-8", errors="replace")
                return Response(
                    content=inject_watch_script(html),
                    media_type="text/html",
                    headers={"Cache-Control": "no-store"},
                )
            except Exception:
                logger.warning("Watch injection failed for %s — serving raw", path, exc_info=True)
        return FileResponse(target, media_type=media_type)

    # SCSS fallback: if requesting .css but only .scss exists, compile on-the-fly
    if target.suffix.lower() == ".css":
        scss_path = target.with_suffix(".scss")
        if scss_path.exists() and scss_path.is_file():
            try:
                from ...engine.scss_compiler import compile_scss

                scss_source = scss_path.read_text(encoding="utf-8")
                css_content = compile_scss(scss_source)
                # Cache the compiled CSS to disk for future requests
                target.write_text(css_content, encoding="utf-8")
                logger.info("Compiled SCSS on-the-fly: %s -> %s", scss_path.name, target.name)
                return Response(content=css_content, media_type="text/css")
            except ImportError:
                logger.warning("SCSS file found but libsass not installed: %s", scss_path)
            except Exception:
                logger.warning("Failed to compile SCSS on-the-fly: %s", scss_path, exc_info=True)

    # File not on disk — try DB fallback
    if version_repo and page_repo:
        page = await page_repo.get_by_slug(project_id, slug)
        if page:
            ver = await version_repo.get_by_number(page.id, version)
            if ver and ver.files:
                # Normalize path separators
                normalized_path = path.replace("\\", "/")
                content = ver.files.get(normalized_path)
                if content is not None:
                    logger.info("Serving %s from DB for project %s page %s v%d", path, project_id, slug, version)
                    # Lazy restore: write to disk for future requests
                    try:
                        pm.write_version_file(project_id, slug, version, normalized_path, content)
                    except Exception:
                        logger.warning("Failed to lazy-restore %s to disk", path)

                    suffix = Path(path).suffix.lower()
                    media_type = _MIME_TYPES.get(suffix, "application/octet-stream")
                    if suffix in (".html", ".htm"):
                        content = inject_watch_script(content)
                        media_type = "text/html"
                    return Response(content=content, media_type=media_type)

    raise HTTPException(status_code=404, detail=f"File not found: {path}")
