"""Project CRUD and page management endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ...agents.registry import AgentRegistry
from ...models import ChatMessage, Page, Project, StyleSpec
from ..deps import get_message_repo, get_page_repo, get_pm, get_repo, get_version_repo

router = APIRouter(prefix="/api/projects", tags=["projects"])


# -- Request models --

class CreateProjectRequest(BaseModel):
    name: str = "Untitled Project"
    description: str = ""
    model: str = ""
    mode: str = "mockup"  # "mockup" | "project"
    template_id: str | None = None  # workspace template when mode == "project"


class UpdateProjectRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    model: str | None = None
    logo_url: str | None = None
    icon_url: str | None = None
    style_spec: dict | None = None
    agent_overrides: dict | None = None


class CreatePageRequest(BaseModel):
    slug: str
    title: str = ""
    prompt: str = ""


class UpdatePageRequest(BaseModel):
    title: str | None = None
    prompt: str | None = None
    layout_overrides: dict | None = None  # partial StyleSpec dict; null/{} clears
    canvas_x: float | None = None  # whiteboard position; null clears
    canvas_y: float | None = None


# -- Project CRUD --

@router.get("/{project_id}/quality")
async def get_quality(project_id: str, repo=Depends(get_repo)):
    """Phase 4 — return the per-project quality ratchet (floors + history)."""
    project = await repo.get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    from ...engine.ratchet import load_ratchet
    ratchet = load_ratchet(project_id)
    return ratchet.model_dump()


@router.post("", response_model=Project)
async def create_project(req: CreateProjectRequest, repo=Depends(get_repo), pm=Depends(get_pm)):
    if req.mode not in ("mockup", "project"):
        raise HTTPException(status_code=400, detail="mode must be 'mockup' or 'project'")

    template = None
    if req.mode == "project":
        from ...config import settings
        from ...templates import find_template

        template = find_template(req.template_id or settings.default_template)
        if template is None:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown template '{req.template_id}'. See GET /api/templates.",
            )

    project = Project(
        name=req.name,
        description=req.description,
        model=req.model,
        style_spec=StyleSpec(),
        mode=req.mode,
        template_id=template.id if template else None,
    )
    pm.create(project)
    await repo.create(project)

    # Scaffold the workspace immediately so uploads land in it and the
    # file tree exists before the first generation.
    if template is not None:
        from ...engine.workspace import WorkspaceManager

        try:
            WorkspaceManager(pm.project_dir(project.id)).scaffold(template)
        except Exception as exc:
            pm.delete(project.id)
            await repo.delete(project.id)
            raise HTTPException(status_code=500, detail=f"Workspace scaffold failed: {exc}")

    return project


@router.get("", response_model=list[Project])
async def list_projects(repo=Depends(get_repo)):
    return await repo.list_all()


@router.get("/{project_id}", response_model=Project)
async def get_project(project_id: str, repo=Depends(get_repo)):
    project = await repo.get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.put("/{project_id}", response_model=Project)
async def update_project(project_id: str, req: UpdateProjectRequest, repo=Depends(get_repo)):
    project = await repo.get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if req.name is not None:
        project.name = req.name
    if req.description is not None:
        project.description = req.description
    if req.model is not None:
        project.model = req.model
    if req.logo_url is not None:
        project.logo_url = req.logo_url
    if req.icon_url is not None:
        project.icon_url = req.icon_url
    if req.style_spec is not None:
        project.style_spec = StyleSpec.model_validate(req.style_spec)
    if req.agent_overrides is not None:
        # Validate: only registered agent keys, only known fields per agent
        valid_agents = {d.key for d in AgentRegistry.list_all()}
        valid_fields = {"model", "temperature", "system_prompt_override"}
        cleaned = {}
        for agent_key, overrides in req.agent_overrides.items():
            if agent_key not in valid_agents or not isinstance(overrides, dict):
                continue
            agent_clean = {k: v for k, v in overrides.items() if k in valid_fields}
            if agent_clean:
                cleaned[agent_key] = agent_clean
        project.agent_overrides = cleaned or None
    await repo.update(project)
    return project


@router.delete("/{project_id}")
async def delete_project(project_id: str, repo=Depends(get_repo), pm=Depends(get_pm)):
    project = await repo.get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    # Delete disk files FIRST to avoid orphaned files
    pm.delete(project_id)
    await repo.delete(project_id)
    return {"deleted": project_id}


@router.get("/{project_id}/export")
async def export_zip(project_id: str, pm=Depends(get_pm), repo=Depends(get_repo)):
    from fastapi.responses import Response

    project = await repo.get(project_id)
    try:
        if project is not None and project.mode == "project":
            from ...engine.workspace import WorkspaceManager

            data = WorkspaceManager(pm.project_dir(project_id)).export_zip()
        else:
            data = pm.export_zip(project_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Project not found or empty")

    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={project_id}.zip"},
    )


# -- Guides (project knowledge base) --

@router.get("/{project_id}/guides")
async def list_guides(project_id: str, repo=Depends(get_repo), pm=Depends(get_pm)):
    project = await repo.get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    guide_files = pm.list_guides(project_id)
    guides: dict[str, str] = {}
    for filename in guide_files:
        content = pm.read_guide(project_id, filename)
        if content is not None:
            guides[filename] = content
    return guides


# -- Page CRUD --

@router.post("/{project_id}/pages", response_model=Page)
async def create_page(
    project_id: str,
    req: CreatePageRequest,
    repo=Depends(get_repo),
    page_repo=Depends(get_page_repo),
    pm=Depends(get_pm),
):
    project = await repo.get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    # Check for duplicate slug
    existing = await page_repo.get_by_slug(project_id, req.slug)
    if existing:
        raise HTTPException(status_code=409, detail=f"Page with slug '{req.slug}' already exists")

    page = Page(
        project_id=project_id,
        slug=req.slug,
        title=req.title or req.slug.replace("-", " ").title(),
        prompt=req.prompt,
    )
    await page_repo.create(page)
    return page


@router.get("/{project_id}/pages", response_model=list[Page])
async def list_pages(project_id: str, page_repo=Depends(get_page_repo)):
    return await page_repo.list_by_project(project_id)


@router.get("/{project_id}/pages/{slug}", response_model=Page)
async def get_page(project_id: str, slug: str, page_repo=Depends(get_page_repo)):
    page = await page_repo.get_by_slug(project_id, slug)
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found")
    return page


@router.patch("/{project_id}/pages/{slug}", response_model=Page)
async def update_page(
    project_id: str,
    slug: str,
    req: UpdatePageRequest,
    repo=Depends(get_repo),
    page_repo=Depends(get_page_repo),
):
    page = await page_repo.get_by_slug(project_id, slug)
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found")
    if req.title is not None:
        page.title = req.title
    if req.prompt is not None:
        page.prompt = req.prompt
    if "canvas_x" in req.model_fields_set:
        page.canvas_x = req.canvas_x
    if "canvas_y" in req.model_fields_set:
        page.canvas_y = req.canvas_y
    if "layout_overrides" in req.model_fields_set:
        if not req.layout_overrides:
            page.layout_overrides = None  # null or {} clears overrides
        else:
            unknown = sorted(set(req.layout_overrides) - set(StyleSpec.model_fields))
            if unknown:
                raise HTTPException(
                    status_code=422,
                    detail=f"Unknown StyleSpec field(s): {', '.join(unknown)}",
                )
            # Validate values by merging over the project's current spec
            project = await repo.get(project_id)
            from ...models import effective_style_spec

            try:
                effective_style_spec(
                    (project.style_spec if project else None) or StyleSpec(),
                    req.layout_overrides,
                )
            except Exception as exc:
                raise HTTPException(
                    status_code=422, detail=f"Invalid layout_overrides: {exc}"
                ) from exc
            page.layout_overrides = req.layout_overrides
    await page_repo.update(page)
    return page


@router.delete("/{project_id}/pages/{slug}")
async def delete_page(
    project_id: str,
    slug: str,
    page_repo=Depends(get_page_repo),
    pm=Depends(get_pm),
):
    page = await page_repo.get_by_slug(project_id, slug)
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found")
    # Delete disk files FIRST to avoid orphaned files if DB delete succeeds
    # but disk delete fails
    pm.delete_page(project_id, slug)
    await page_repo.delete(page.id)
    return {"deleted": slug}


# -- Version listing --

@router.get("/{project_id}/pages/{slug}/versions")
async def list_versions(
    project_id: str,
    slug: str,
    page_repo=Depends(get_page_repo),
    version_repo=Depends(get_version_repo),
):
    page = await page_repo.get_by_slug(project_id, slug)
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found")
    versions = await version_repo.list_by_page(page.id)
    return [v.model_dump() for v in versions]


@router.get("/{project_id}/pages/{slug}/versions/{version_number:int}/files")
async def list_version_files(
    project_id: str,
    slug: str,
    version_number: int,
    pm=Depends(get_pm),
):
    files = pm.list_version_files(project_id, slug, version_number)
    return {"files": files}


# -- Chat messages --

class CreateMessageRequest(BaseModel):
    role: str = "user"
    content: str = ""
    image: str | None = None
    meta: dict = {}


@router.get("/{project_id}/pages/{slug}/messages")
async def list_messages(
    project_id: str,
    slug: str,
    page_repo=Depends(get_page_repo),
    message_repo=Depends(get_message_repo),
):
    page = await page_repo.get_by_slug(project_id, slug)
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found")
    messages = await message_repo.list_by_page(page.id)
    return [m.model_dump() for m in messages]


@router.post("/{project_id}/pages/{slug}/messages")
async def create_message(
    project_id: str,
    slug: str,
    req: CreateMessageRequest,
    page_repo=Depends(get_page_repo),
    message_repo=Depends(get_message_repo),
):
    page = await page_repo.get_by_slug(project_id, slug)
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found")
    msg = ChatMessage(
        page_id=page.id,
        role=req.role,
        content=req.content,
        image=req.image,
        meta=req.meta,
    )
    await message_repo.create(msg)
    return msg.model_dump()
