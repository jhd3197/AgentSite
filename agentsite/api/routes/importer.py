"""HTML page import endpoints — bring external pages into AgentSite."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from ...engine.importer import fetch_page, normalize_html
from ...models import Page, PageVersion
from ..deps import get_page_repo, get_pm, get_repo, get_version_repo

router = APIRouter(prefix="/api/projects", tags=["import"])

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


# -- Request models --


class ImportHtmlRequest(BaseModel):
    slug: str
    title: str = ""
    html: str
    extract_css: bool = True


class ImportUrlRequest(BaseModel):
    slug: str
    title: str = ""
    url: str
    extract_css: bool = True


# -- Shared logic --


async def _import_files(
    project_id: str,
    slug: str,
    title: str,
    source: str,
    file_map: dict[str, str],
    repo,
    page_repo,
    version_repo,
    pm,
    response: Response,
):
    """Persist an imported file map as a page (or new version) and return the payload."""
    page = await page_repo.get_by_slug(project_id, slug)
    created = page is None
    if created:
        page = Page(
            project_id=project_id,
            slug=slug,
            title=title or slug.replace("-", " ").title(),
            prompt=f"Imported from {source}",
        )
        await page_repo.create(page)

    version_number = await version_repo.next_version_number(page.id)
    for rel_path, content in file_map.items():
        pm.write_version_file(project_id, slug, version_number, rel_path, content)

    version = PageVersion(
        page_id=page.id,
        version_number=version_number,
        status="completed",
        prompt=f"Imported from {source}",
        files=file_map,
        completed_at=datetime.now(timezone.utc).isoformat(),
    )
    await version_repo.create(version)

    response.status_code = 201 if created else 200
    return {
        "page": page.model_dump(),
        "version": version.model_dump(),
        "files": sorted(file_map.keys()),
    }


def _validate(project, slug: str):
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.mode != "mockup":
        raise HTTPException(status_code=400, detail="Import is only supported for mockup-mode projects")
    if not slug or not _SLUG_RE.match(slug):
        raise HTTPException(
            status_code=400,
            detail="Invalid slug — use lowercase letters, numbers, and hyphens (e.g. 'about-us')",
        )


# -- Endpoints --


@router.post("/{project_id}/import")
async def import_html(
    project_id: str,
    req: ImportHtmlRequest,
    response: Response,
    repo=Depends(get_repo),
    page_repo=Depends(get_page_repo),
    version_repo=Depends(get_version_repo),
    pm=Depends(get_pm),
):
    """Import pasted HTML as a page (or a new version of an existing page)."""
    project = await repo.get(project_id)
    _validate(project, req.slug)
    if not req.html.strip():
        raise HTTPException(status_code=400, detail="HTML content is required")

    file_map = normalize_html(req.html, extract_css=req.extract_css)
    return await _import_files(
        project_id, req.slug, req.title, "HTML paste", file_map,
        repo, page_repo, version_repo, pm, response,
    )


@router.post("/{project_id}/import/url")
async def import_url(
    project_id: str,
    req: ImportUrlRequest,
    response: Response,
    repo=Depends(get_repo),
    page_repo=Depends(get_page_repo),
    version_repo=Depends(get_version_repo),
    pm=Depends(get_pm),
):
    """Fetch a page from a URL and import it (or a new version of an existing page)."""
    project = await repo.get(project_id)
    _validate(project, req.slug)
    if not req.url.strip():
        raise HTTPException(status_code=400, detail="URL is required")

    try:
        html = await fetch_page(req.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    file_map = normalize_html(html, extract_css=req.extract_css)
    return await _import_files(
        project_id, req.slug, req.title, req.url, file_map,
        repo, page_repo, version_repo, pm, response,
    )
