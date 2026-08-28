"""Reusable generation-launching helper.

Extracts the pipeline setup + background task wiring out of the
``/api/projects/{id}/pages/{slug}/generate`` route handler so the chat
agent (or any other caller) can kick off a build using the same code path.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from ..api.websocket import ws_manager
from ..engine.pipeline import GenerationPipeline
from ..engine.progressive import ProgressivePipeline
from ..engine.project_manager import ProjectManager
from ..models import AgentConfig, Page, PageVersion, WSEvent
from ..storage.repository import (
    AgentConfigRepository,
    AgentRunRepository,
    PageRepository,
    ProjectRepository,
    VersionRepository,
)

logger = logging.getLogger("agentsite.generation_runner")


async def start_generation_task(
    project_id: str,
    slug: str,
    prompt: str,
    *,
    project_repo: ProjectRepository,
    page_repo: PageRepository,
    version_repo: VersionRepository,
    agent_config_repo: AgentConfigRepository,
    agent_run_repo: AgentRunRepository,
    pm: ProjectManager,
    model: str = "",
    agent_models: dict[str, str] | None = None,
    max_cost: float | None = None,
    budget_policy: str | None = None,
    provider_keys: dict[str, str] | None = None,
    discovery_brief: dict | None = None,
    strategy: str | None = None,
    direction_id: str | None = None,
    inherits_from: str | None = None,
    watch_feedback: list[dict] | None = None,
) -> dict[str, Any]:
    """Kick off page generation as a background task.

    Returns immediately with version info. Pipeline progress is broadcast
    over the project's WebSocket channel.

    Raises:
        ValueError: project not found, page state invalid, or prompt missing.
    """
    project = await project_repo.get(project_id)
    if project is None:
        raise ValueError(f"Project '{project_id}' not found")

    if model:
        project.model = model
        await project_repo.update(project)

    page = await page_repo.get_by_slug(project_id, slug)
    if page is None:
        page = Page(
            project_id=project_id,
            slug=slug,
            title=slug.replace("-", " ").title(),
            prompt=prompt,
        )
        await page_repo.create(page)
    elif prompt:
        page.prompt = prompt
        await page_repo.update(page)

    effective_prompt = prompt or page.prompt
    if not effective_prompt:
        raise ValueError("Prompt is required")

    if watch_feedback:
        from .watch import append_watch_feedback

        effective_prompt = append_watch_feedback(effective_prompt, watch_feedback)

    latest = await version_repo.get_latest(page.id)
    if latest and latest.status == "generating":
        raise ValueError("Generation already in progress for this page")

    version_number = await version_repo.next_version_number(page.id)
    version = PageVersion(
        page_id=page.id,
        version_number=version_number,
        status="generating",
        prompt=effective_prompt,
    )
    await version_repo.create(version)

    on_event = ws_manager.make_callback(project_id)

    configs_list = await agent_config_repo.list_all()
    agent_configs = {c.agent_name: c for c in configs_list}

    if project.agent_overrides:
        for agent_key, overrides in project.agent_overrides.items():
            if not isinstance(overrides, dict):
                continue
            if agent_key not in agent_configs:
                agent_configs[agent_key] = AgentConfig(agent_name=agent_key)
            cfg = agent_configs[agent_key]
            if "enabled" in overrides:
                cfg.enabled = bool(overrides["enabled"])
            if overrides.get("model") and "/" in overrides["model"]:
                cfg.model = overrides["model"]
            if "temperature" in overrides:
                cfg.temperature = float(overrides["temperature"])
            if overrides.get("system_prompt_override"):
                cfg.system_prompt_override = overrides["system_prompt_override"]

    if agent_models:
        for agent_key, model_str in agent_models.items():
            if model_str and "/" in model_str:
                if agent_key in agent_configs:
                    agent_configs[agent_key].model = model_str
                else:
                    agent_configs[agent_key] = AgentConfig(agent_name=agent_key, model=model_str)

    merged_provider_keys = dict(project.provider_keys or {})
    if provider_keys:
        merged_provider_keys.update(provider_keys)

    project_mode = (getattr(project, "mode", "mockup") or "mockup") == "project"
    if project_mode:
        from ..engine.project_pipeline import ProjectGenerationPipeline

        pipeline = ProjectGenerationPipeline(
            pm,
            on_event=on_event,
            agent_configs=agent_configs,
            provider_keys=merged_provider_keys or None,
        )
    elif strategy == "progressive":
        pipeline = ProgressivePipeline(
            pm,
            on_event=on_event,
            agent_configs=agent_configs,
            provider_keys=merged_provider_keys or None,
        )
    else:
        pipeline = GenerationPipeline(
            pm,
            on_event=on_event,
            agent_configs=agent_configs,
            provider_keys=merged_provider_keys or None,
        )

    def _collect_files() -> tuple[list[str], dict[str, str]]:
        """Snapshot generated files for DB capture (mode-aware)."""
        if project_mode:
            from ..engine.workspace import WorkspaceManager

            ws = WorkspaceManager(pm.project_dir(project_id))
            content = ws.collect_files_content()
            return ws.list_files(), content
        file_list = pm.list_version_files(project_id, slug, version_number)
        content = {}
        for fpath in file_list:
            c = pm.read_version_file(project_id, slug, version_number, fpath)
            if c is not None:
                content[fpath] = c
        return file_list, content

    try:
        from prompture.exceptions import BudgetExceededError as _BudgetExceededError
    except ImportError:
        class _BudgetExceededError(Exception):
            pass

    brief = None
    if discovery_brief:
        from ..agents.discovery import brief_from_form
        brief = brief_from_form(discovery_brief)

    if inherits_from:
        if project.style_spec is None:
            from ..models import StyleSpec as _SS
            project.style_spec = _SS()
        project.style_spec.inherits_from = inherits_from
        await project_repo.update(project)

    if direction_id:
        if brief is None:
            from ..models import DiscoveryBrief
            brief = DiscoveryBrief(brand_mode="pick_direction", direction_id=direction_id)
        else:
            brief.direction_id = direction_id
            if not brief.brand_mode:
                brief.brand_mode = "pick_direction"

    async def _run():
        try:
            result = await pipeline.generate(
                project,
                slug=slug,
                version_number=version_number,
                page_prompt=effective_prompt,
                max_cost=max_cost,
                budget_policy=budget_policy,
                discovery_brief=brief,
            )
            if pipeline.style_spec_text:
                try:
                    import json as _json

                    from prompture import clean_json_text

                    from ..models import StyleSpec
                    cleaned_ss = clean_json_text(pipeline.style_spec_text)
                    ss_data = _json.loads(cleaned_ss)
                    project.style_spec = StyleSpec.model_validate(ss_data)
                    await project_repo.update(project)
                except Exception:
                    from ..engine.extract import extract_structured
                    from ..models import StyleSpec

                    extracted = await extract_structured(
                        StyleSpec,
                        pipeline.style_spec_text,
                        project.model or "openai/gpt-4o",
                        instruction="Extract the design style specification from this output:",
                    )
                    if extracted:
                        project.style_spec = extracted
                        await project_repo.update(project)
                    else:
                        logger.warning("Failed to auto-save StyleSpec to project", exc_info=True)

            file_list, files_content = _collect_files()

            version.status = "completed"
            version.usage = result.aggregate_usage
            version.files = files_content
            version.completed_at = datetime.now(timezone.utc).isoformat()
            await version_repo.update(version)
        except _BudgetExceededError as budget_exc:
            logger.warning(
                "Budget exceeded for project %s page %s: %s",
                project_id, slug, budget_exc,
            )
            file_list, files_content = _collect_files()

            version.status = "budget_exceeded"
            version.error = str(budget_exc)
            version.files = files_content or None
            version.completed_at = datetime.now(timezone.utc).isoformat()
            await version_repo.update(version)

            try:
                await ws_manager.broadcast(
                    project_id,
                    WSEvent(
                        type="budget_exceeded",
                        data={
                            "message": str(budget_exc),
                            "slug": slug,
                            "version": version_number,
                            "files_recovered": len(files_content),
                        },
                    ),
                )
                await ws_manager.broadcast(
                    project_id,
                    WSEvent(
                        type="generation_complete",
                        data={
                            "success": False,
                            "slug": slug,
                            "version": version_number,
                            "files": file_list,
                            "error": str(budget_exc),
                            "budget_exceeded": True,
                        },
                    ),
                )
            except Exception:
                logger.warning("Failed to broadcast budget_exceeded via WebSocket")
        except Exception as exc:
            import traceback as tb_mod
            error_detail = str(exc)
            tb = tb_mod.format_exc()
            logger.exception("Generation failed for project %s page %s", project_id, slug)

            file_list, files_content = _collect_files()
            # Mockup-only recovery: files on disk mean the build salvaged.
            # In project mode the workspace always has scaffold files, so
            # their presence proves nothing — keep the failure status.
            if file_list and not project_mode:
                logger.info(
                    "Pipeline failed but %d files exist on disk for project %s page %s v%d — marking completed",
                    len(file_list), project_id, slug, version_number,
                )
                version.status = "completed"
                version.files = files_content
                version.completed_at = datetime.now(timezone.utc).isoformat()
                await version_repo.update(version)
            else:
                version.status = "failed"
                version.error = error_detail
                version.completed_at = datetime.now(timezone.utc).isoformat()
                await version_repo.update(version)
            recovered = version.status == "completed"
            try:
                if not recovered:
                    await ws_manager.broadcast(
                        project_id,
                        WSEvent(type="error", data={"message": error_detail, "traceback": tb}),
                    )
                await ws_manager.broadcast(
                    project_id,
                    WSEvent(
                        type="generation_complete",
                        data={
                            "success": recovered,
                            "slug": slug,
                            "version": version_number,
                            "files": file_list if recovered else [],
                            "error": error_detail if not recovered else None,
                        },
                    ),
                )
            except Exception:
                logger.warning("Failed to broadcast via WebSocket")
        finally:
            for run in pipeline.agent_runs:
                try:
                    await agent_run_repo.create(run)
                except Exception:
                    logger.warning("Failed to persist agent run: %s", run.id)

    asyncio.create_task(_run())

    return {
        "project_id": project_id,
        "slug": slug,
        "version_number": version_number,
        "version_id": version.id,
        "status": "started",
    }
