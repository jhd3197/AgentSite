"""Generation endpoints — POST trigger + WebSocket progress."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from ...engine.generation_runner import start_generation_task
from ..deps import (
    get_agent_config_repo,
    get_agent_run_repo,
    get_page_repo,
    get_pm,
    get_project_component_repo,
    get_repo,
    get_version_repo,
)
from ..websocket import ws_manager

logger = logging.getLogger("agentsite.api.generate")
router = APIRouter(tags=["generate"])

class GenerateRequest(BaseModel):
    prompt: str = ""
    model: str = ""
    agent_models: dict[str, str] | None = None
    max_cost: float | None = None  # per-request budget override
    budget_policy: str | None = None  # per-request policy override
    provider_keys: dict[str, str] | None = None  # per-request provider key overrides
    discovery_brief: dict | None = None  # Phase 1 — answers from the discovery form
    strategy: str | None = None  # "progressive" for staged layout→sections build
    direction_id: str | None = None  # Phase 2 — chosen design direction id
    inherits_from: str | None = None  # Phase 9 — design system id to extend
    watch_feedback: list[dict] | None = None  # live-preview friction observations


@router.post("/api/projects/{project_id}/pages/{slug}/generate")
async def start_generation(
    project_id: str,
    slug: str,
    req: GenerateRequest,
    repo=Depends(get_repo),
    page_repo=Depends(get_page_repo),
    version_repo=Depends(get_version_repo),
    pm=Depends(get_pm),
    agent_run_repo=Depends(get_agent_run_repo),
    agent_config_repo=Depends(get_agent_config_repo),
    project_component_repo=Depends(get_project_component_repo),
):
    """Start page generation — creates a new version and runs the pipeline."""
    try:
        result = await start_generation_task(
            project_id,
            slug,
            req.prompt,
            project_repo=repo,
            page_repo=page_repo,
            version_repo=version_repo,
            agent_config_repo=agent_config_repo,
            agent_run_repo=agent_run_repo,
            pm=pm,
            model=req.model,
            agent_models=req.agent_models,
            max_cost=req.max_cost,
            budget_policy=req.budget_policy,
            provider_keys=req.provider_keys,
            discovery_brief=req.discovery_brief,
            strategy=req.strategy,
            direction_id=req.direction_id,
            inherits_from=req.inherits_from,
            watch_feedback=req.watch_feedback,
            project_component_repo=project_component_repo,
        )
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg.lower():
            raise HTTPException(status_code=404, detail=msg) from exc
        if "already in progress" in msg.lower():
            raise HTTPException(status_code=409, detail=msg) from exc
        raise HTTPException(status_code=400, detail=msg) from exc

    return {**result, "message": "Generation started. Connect to WebSocket for progress."}


@router.websocket("/ws/generate/{project_id}")
async def generation_websocket(project_id: str, ws: WebSocket):
    """WebSocket endpoint for real-time generation progress."""
    await ws_manager.connect(project_id, ws)
    try:
        import json as _json

        from ...engine.interrupt import mailbox
        from ...models import WSEvent
        while True:
            data = await ws.receive_text()
            # Phase 7 — inbound steer: {"type": "steer", "text": "..."}.
            try:
                msg = _json.loads(data) if data else {}
            except Exception:
                msg = {}
            if isinstance(msg, dict) and msg.get("type") == "steer":
                text = str(msg.get("text", "")).strip()
                if text:
                    mailbox.deposit(project_id, text)
                    await ws_manager.broadcast(
                        project_id,
                        WSEvent(type="steer_received", data={"text": text, "bytes": len(text)}),
                    )
    except WebSocketDisconnect:
        ws_manager.disconnect(project_id, ws)
