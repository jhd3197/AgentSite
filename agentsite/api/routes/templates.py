"""Workspace template listing endpoints (project mode)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ...templates import find_template, list_templates, read_starter_prompts

router = APIRouter(prefix="/api/templates", tags=["templates"])


@router.get("")
async def get_templates():
    """List available workspace templates."""
    return [
        {
            "id": t.id,
            "name": t.name,
            "description": t.description,
            "kind": t.kind,
        }
        for t in list_templates()
    ]


@router.get("/{template_id}/prompts")
async def get_template_prompts(template_id: str):
    """Starter prompts for a template."""
    if find_template(template_id) is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return {"prompts": read_starter_prompts(template_id)}
