"""Image/asset upload endpoints."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile

from ..deps import get_assets, get_pm, get_repo

logger = logging.getLogger("agentsite.api.assets")

router = APIRouter(tags=["assets"])


@router.post("/api/projects/{project_id}/assets")
async def upload_asset(
    project_id: str,
    file: UploadFile,
    assets=Depends(get_assets),
    repo=Depends(get_repo),
    pm=Depends(get_pm),
):
    """Upload an image or asset file to a project.

    Project-mode uploads also land directly in the workspace uploads
    directory so the dev agent (and the built site) can reference them.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    data = await file.read()
    if len(data) > 10 * 1024 * 1024:  # 10 MB limit
        raise HTTPException(status_code=413, detail="File too large (max 10 MB)")

    try:
        rel_path = assets.save_upload(project_id, file.filename, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    workspace_path = None
    try:
        project = await repo.get(project_id)
        if project is not None and project.mode == "project":
            from ...engine.workspace import WorkspaceManager

            ws = WorkspaceManager(pm.project_dir(project_id))
            if ws.exists():
                safe_name = Path(rel_path).name
                target = ws.uploads_dir() / safe_name
                target.write_bytes(data)
                workspace_path = f"uploads/{safe_name}"
    except Exception:
        logger.warning("Workspace upload copy failed for %s", project_id, exc_info=True)

    return {
        "path": rel_path,
        "filename": file.filename,
        "size": len(data),
        "workspace_path": workspace_path,
    }


@router.get("/api/projects/{project_id}/assets")
async def list_assets(project_id: str, assets=Depends(get_assets)):
    """List all uploaded assets for a project with metadata."""
    return {"assets": assets.list_assets_detailed(project_id)}


@router.delete("/api/projects/{project_id}/assets/{filename}")
async def delete_asset(project_id: str, filename: str, assets=Depends(get_assets)):
    """Delete an asset file from a project."""
    deleted = assets.delete_asset(project_id, filename)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Asset not found: {filename}")
    return {"deleted": True, "filename": filename}
