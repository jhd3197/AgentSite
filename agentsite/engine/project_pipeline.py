"""Project-mode generation pipeline — resident dev agent in a real workspace.

Differences from the mockup pipeline (``pipeline.py``):

- The unit of work is the project **workspace** (scaffolded from a template),
  not a page-version directory of three static files.
- The developer is ONE persistent agent session across all review cycles —
  feedback and build errors go back into the same conversation as targeted
  edits, not whole-file regeneration.
- The filesystem is the shared state. There are no JSON-blob handoffs, no
  nested-group state merging, and no salvage chains: project mode requires a
  tool-capable model up front.
- Node templates are actually built (`npm install` + `npm run build`); build
  errors feed back to the dev session as self-healing input.
- Versioning is git checkpoints inside the workspace.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from prompture import AgentCallbacks, AsyncAgent, GroupResult, clean_json_text

from ..agents.orchestrator import _agent_model, _apply_agent_overrides
from ..agents.personas import PROJECT_DEVELOPER_PERSONA, PROJECT_REVIEWER_PERSONA
from ..agents.workspace_tools import dev_workspace_tools, reviewer_workspace_tools
from ..config import settings
from ..models import (
    AgentConfig,
    AgentRun,
    DiscoveryBrief,
    Project,
    ReviewFeedback,
    SitePlan,
    StyleSpec,
    TriageDecision,
    WSEvent,
)
from ..templates import find_template, read_template_doc
from . import triage as triage_mod
from . import verifier
from .project_manager import ProjectManager
from .tokens import render_tokens_css
from .workspace import WorkspaceManager
from .workspace_runner import build_workspace

logger = logging.getLogger("agentsite.project_pipeline")

_DEV_OPTIONS = {"max_tokens": 65536, "timeout": 900}
_REVIEWER_OPTIONS = {"max_tokens": 8192, "timeout": 600}


class ProjectGenerationPipeline:
    """Orchestrates a project-mode build inside the workspace.

    Exposes the same surface as ``GenerationPipeline`` so the generation
    runner can swap between them by ``project.mode``.
    """

    def __init__(
        self,
        project_manager: ProjectManager,
        *,
        on_event: Any | None = None,
        agent_configs: dict[str, AgentConfig] | None = None,
        cachibot_api_key: str | None = None,
        provider_keys: dict[str, str] | None = None,
    ) -> None:
        self._pm = project_manager
        self._on_event = on_event
        self._agent_configs = agent_configs
        self._cachibot_api_key = cachibot_api_key
        self._provider_keys = provider_keys
        self.agent_runs: list[AgentRun] = []
        self._agent_models: dict[str, str] = {}
        self._usage: dict[str, Any] = {}
        self.site_plan_text: str = ""
        self.style_spec_text: str = ""

    # -- infrastructure -------------------------------------------------

    async def _emit(self, event_type: str, agent: str = "", data: dict[str, Any] | None = None) -> None:
        if self._on_event:
            result = self._on_event(WSEvent(type=event_type, agent=agent, data=data or {}))
            if asyncio.iscoroutine(result):
                await result

    def _inject_driver(self, agent: Any, model_str: str) -> None:
        if not self._provider_keys:
            return
        from .driver_factory import resolve_driver_for_model

        driver = resolve_driver_for_model(model_str, self._provider_keys)
        if driver is not None:
            agent.driver = driver

    def _attach_streaming(self, agent: Any, agent_key: str) -> None:
        async def _on_tool_start(name: str, args: Any, *, _key: str = agent_key) -> None:
            await self._emit("tool_start", agent=_key, data={"name": name, "args": args})

        async def _on_tool_end(name: str, result: Any, *, _key: str = agent_key) -> None:
            await self._emit("tool_end", agent=_key, data={"name": name, "result": str(result)[:500]})

        async def _on_thinking(text: str, *, _key: str = agent_key) -> None:
            await self._emit("agent_thinking", agent=_key, data={"text": text[:2000]})

        async def _on_step(step: Any, *, _key: str = agent_key) -> None:
            await self._emit("agent_step", agent=_key, data={
                "step_type": step.step_type.value if hasattr(step.step_type, "value") else str(step.step_type),
                "content": (step.content or "")[:500],
                "tool_name": getattr(step, "tool_name", None),
            })

        async def _on_iteration(idx: int, *, _key: str = agent_key) -> None:
            await self._emit("agent_iteration", agent=_key, data={"iteration": idx})

        async def _on_message(text: str, *, _key: str = agent_key) -> None:
            if text:
                await self._emit("text_delta", agent=_key, data={"text": text[:4000]})

        async def _on_output(result: Any, *, _key: str = agent_key) -> None:
            output_text = getattr(result, "output_text", "") or ""
            if output_text:
                await self._emit("agent_output", agent=_key, data={"text": output_text[:2000]})

        agent.callbacks = AgentCallbacks(
            on_tool_start=_on_tool_start,
            on_tool_end=_on_tool_end,
            on_thinking=_on_thinking,
            on_step=_on_step,
            on_iteration=_on_iteration,
            on_message=_on_message,
            on_output=_on_output,
        )

    @staticmethod
    def _extract_usage(result: Any) -> tuple[int, int, float]:
        usage = getattr(result, "usage", None) or getattr(result, "run_usage", None) or {}
        if not isinstance(usage, dict):
            return 0, 0, 0.0
        input_tokens = int(
            usage.get("input_tokens", 0)
            or usage.get("prompt_tokens", 0)
            or usage.get("promptTokenCount", 0)
        )
        output_tokens = int(
            usage.get("output_tokens", 0)
            or usage.get("completion_tokens", 0)
            or usage.get("candidatesTokenCount", 0)
        )
        cost = float(usage.get("cost", 0.0) or usage.get("total_cost", 0.0) or 0.0)
        return input_tokens, output_tokens, cost

    def _add_usage(self, input_tokens: int, output_tokens: int, cost: float) -> None:
        self._usage["input_tokens"] = self._usage.get("input_tokens", 0) + input_tokens
        self._usage["output_tokens"] = self._usage.get("output_tokens", 0) + output_tokens
        self._usage["total_tokens"] = self._usage.get("total_tokens", 0) + input_tokens + output_tokens
        self._usage["cost"] = round(self._usage.get("cost", 0.0) + cost, 6)

    async def _run_agent(
        self,
        agent_key: str,
        agent: Any,
        prompt: str,
        deps: dict[str, Any],
        *,
        project_id: str,
        slug: str,
        version: int,
        session_id: str,
        images: list[str] | None = None,
    ) -> Any:
        """Run one agent with full WS event + AgentRun bookkeeping."""
        agent_model = self._agent_models.get(agent_key, "")
        strategy = settings.agent_routing.get(agent_key, "")
        if "/" in strategy:
            strategy = "explicit"

        self._attach_streaming(agent, agent_key)
        await self._emit("agent_start", agent=agent_key, data={
            "started_at": datetime.now(timezone.utc).isoformat(),
            "model": agent_model,
            "strategy": strategy,
        })
        run = AgentRun(
            project_id=project_id,
            page_slug=slug,
            version=version,
            agent_name=agent_key,
            status="running",
            session_id=session_id,
            strategy=strategy,
            model=agent_model,
        )
        self.agent_runs.append(run)
        start = time.monotonic()

        try:
            result = await agent.run(prompt, deps=deps, images=images)
        except Exception as exc:
            run.status = "failed"
            run.completed_at = datetime.now(timezone.utc).isoformat()
            run.output_summary = {"error": str(exc)}
            await self._emit("agent_error", agent=agent_key, data={"message": str(exc)})
            raise

        duration_s = round(time.monotonic() - start, 1)
        input_tokens, output_tokens, cost = self._extract_usage(result)
        run.status = "completed"
        run.completed_at = datetime.now(timezone.utc).isoformat()
        run.input_tokens = input_tokens
        run.output_tokens = output_tokens
        run.cost = cost
        self._add_usage(input_tokens, output_tokens, cost)

        output_text = getattr(result, "output_text", "") or ""
        tool_calls = getattr(result, "all_tool_calls", []) or []
        # Prompture >= 1.9.1 attaches reasoning_content to assistant messages
        # on every path, so project mode can surface thinking like mockup mode.
        reasoning_text = ""
        for msg in getattr(result, "messages", []) or []:
            if isinstance(msg, dict) and msg.get("role") == "assistant" and msg.get("reasoning_content"):
                reasoning_text = msg["reasoning_content"]
        await self._emit("agent_complete", agent=agent_key, data={
            "output_preview": output_text[:2000],
            "full_output": output_text,
            "duration_s": duration_s,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost": cost,
            "tool_calls_count": len(tool_calls),
            "model": agent_model,
            "reasoning": reasoning_text,
        })
        return result

    # -- main entry ------------------------------------------------------

    async def generate(
        self,
        project: Project,
        *,
        slug: str,
        version_number: int,
        page_prompt: str,
        max_cost: float | None = None,
        budget_policy: str | None = None,
        max_review_iterations: int | None = None,
        review_threshold: int | None = None,
        cancel_event: asyncio.Event | None = None,
        conversation_context: str = "",
        discovery_brief: DiscoveryBrief | None = None,
    ) -> GroupResult:
        t0 = time.monotonic()
        model = project.model or settings.default_model
        session_id = f"gen-{project.id}-{slug}-v{version_number}"
        ws = WorkspaceManager(self._pm.project_dir(project.id))

        # -- workspace + event plumbing --------------------------------
        written_files: list[str] = []
        _background_tasks: list[asyncio.Task] = []

        def _fire(event_type: str, data: dict[str, Any]) -> None:
            try:
                loop = asyncio.get_running_loop()
                task = loop.create_task(self._emit(event_type, data=data))
                _background_tasks.append(task)
                task.add_done_callback(_background_tasks.remove)
            except RuntimeError:
                pass

        def _on_file_written(path: str) -> None:
            if path not in written_files:
                written_files.append(path)
            _fire("file_written", {"path": path})

        def _on_preview_update(path: str, html: str) -> None:
            import hashlib

            _fire("preview_update", {
                "page_slug": slug,
                "path": path,
                "html": html,
                "content_hash": hashlib.sha1(html.encode("utf-8")).hexdigest()[:12],
                "bytes": len(html),
            })

        async def _emit_data(event_type: str, data: dict[str, Any]) -> None:
            await self._emit(event_type, data=data)

        def _checkpoint(message: str) -> None:
            ref = ws.checkpoint(message)
            if ref:
                _fire("checkpoint_created", {"message": message, "ref": ref})

        import os as _os

        _prev_cachibot_key = _os.environ.get("CACHIBOT_API_KEY")
        if self._cachibot_api_key:
            _os.environ["CACHIBOT_API_KEY"] = self._cachibot_api_key

        try:
            await self._emit("phase_start", data={
                "phase": "planning", "slug": slug, "version": version_number,
            })

            template = (
                ws.template()
                or find_template(project.template_id)
                or find_template(settings.default_template)
            )
            if template is None:
                raise ValueError(
                    "No workspace template available. Check agentsite/templates/ is intact."
                )

            for agent_key in ("pm", "designer", "developer", "reviewer"):
                self._agent_models[agent_key] = _agent_model(agent_key, model, self._agent_configs)

            dev_model = self._agent_models["developer"]
            from .capabilities import supports_tools, supports_vision

            if not supports_tools(dev_model):
                raise ValueError(
                    f"Project mode requires a tool-capable model; '{dev_model}' does not "
                    "support tool calling. Pick a different developer model or use a "
                    "mockup-mode project."
                )

            if not ws.exists():
                files = ws.scaffold(template)
                await self._emit("workspace_scaffolded", data={
                    "template_id": template.id,
                    "files": files,
                })

            has_direction = (
                discovery_brief is not None
                and discovery_brief.brand_mode == "pick_direction"
                and bool(discovery_brief.direction_id)
            )

            # -- Phase E: triage follow-up requests ----------------------
            existing_plan_text = (
                ws.read_file(".agentsite/site-plan.json")
                or self._pm.read_guide(project.id, "site-plan.json")
                or ""
            )
            decision = TriageDecision(
                bucket="full",
                needs_pm=True,
                needs_designer=(version_number == 1),
                reason="first build" if version_number == 1 else "triage disabled",
            )
            if settings.triage_enabled and version_number > 1 and existing_plan_text:
                triage_model = _agent_model("triage", model, self._agent_configs)
                decision = await triage_mod.triage_request(
                    page_prompt,
                    model=triage_model,
                    site_plan_text=existing_plan_text,
                    file_tree=ws.file_tree(),
                    version_number=version_number,
                )
                await self._emit("triage_decision", data=decision.model_dump())

            run_pm = decision.needs_pm or not existing_plan_text
            run_designer = (version_number == 1 or decision.needs_designer) and not has_direction
            skip_review = decision.bucket == "tweak"

            # -- pipeline plan for the frontend -------------------------
            planned_agents = (
                (["pm"] if run_pm else [])
                + (["designer"] if run_designer else [])
                + ["developer"]
                + ([] if skip_review else ["reviewer"])
            )
            try:
                from ..agents.registry import AgentRegistry

                agent_meta = {}
                for key in planned_agents:
                    desc = AgentRegistry.get(key)
                    if desc:
                        agent_meta[key] = {
                            "name": desc.name,
                            "icon": desc.icon,
                            "icon_color": desc.icon_color,
                            "category": desc.category.value,
                        }
            except Exception:
                agent_meta = {}
            await self._emit("pipeline_plan", data={
                "required_agents": planned_agents,
                "agent_meta": agent_meta,
                "parallel_groups": [],
                "tech_stack": {"framework": template.id, "markup": "html", "styling": "css"},
                "bucket": decision.bucket,
            })

            # -- discovery / memory prelude ------------------------------
            discovery_brief_text = ""
            if discovery_brief is not None:
                from ..agents.discovery import render_brief

                discovery_brief_text = render_brief(discovery_brief)
                await self._emit("discovery_brief_submitted", data={
                    "brief": discovery_brief.model_dump(),
                    "rendered": discovery_brief_text,
                })

            memory_block = ""
            try:
                from ..api import deps as _api_deps
                from .memory import render_for_context as _render_mem

                if getattr(_api_deps, "memory_repo", None) is not None:
                    _facts = await _api_deps.memory_repo.list_by_project(project.id, limit=15)
                    memory_block = _render_mem(_facts)
            except Exception:
                logger.debug("Memory load skipped", exc_info=True)

            try:
                from .interrupt import mailbox as _steer_mailbox

                _steer_mailbox.clear(project.id)
            except Exception:
                pass

            uploads_listing = ""
            uploads = [
                f.name for f in ws.uploads_dir(template).iterdir()
                if f.is_file() and f.name != ".gitkeep"
            ]
            if uploads:
                uploads_listing = "## User uploads available\n" + "\n".join(
                    f"- uploads/{name}" for name in uploads
                )

            # -- Phase A: PM (skipped for tweaks — existing plan reused) --
            site_plan: SitePlan | None = None
            if run_pm:
                from ..agents.pm import create_pm_agent_auto

                pm_model = self._agent_models["pm"]
                pm_agent = create_pm_agent_auto(pm_model)
                _apply_agent_overrides(pm_agent, "pm", self._agent_configs)
                self._inject_driver(pm_agent, pm_model)

                template_note = (
                    f"## Workspace template (fixed)\nThis project uses the '{template.name}' "
                    f"template ({template.kind}). The tech stack is already decided — do NOT "
                    "choose tech_stack or required_agents. Plan only: pages, sections, and titles."
                )
                plan_update_note = ""
                if existing_plan_text and version_number > 1:
                    plan_update_note = (
                        "## Existing site plan — UPDATE it\nThe site already exists. "
                        "Produce the updated FULL site plan incorporating the request: "
                        "keep existing pages unless the request says otherwise.\n\n"
                        + existing_plan_text[:6000]
                    )
                prelude = [p for p in (
                    memory_block, discovery_brief_text, uploads_listing,
                    template_note, plan_update_note,
                ) if p]
                pm_prompt = "\n\n---\n\n".join(prelude) + f"\n\n---\n\nUser brief:\n{page_prompt}"

                pm_deps = {"project_dir": self._pm.project_dir(project.id)}
                pm_result = await self._run_agent(
                    "pm", pm_agent, pm_prompt, pm_deps,
                    project_id=project.id, slug=slug, version=version_number, session_id=session_id,
                )
                self.site_plan_text = getattr(pm_result, "output_text", "") or ""

                try:
                    site_plan = SitePlan.model_validate(json.loads(clean_json_text(self.site_plan_text)))
                except Exception:
                    from .extract import extract_structured

                    site_plan = await extract_structured(
                        SitePlan, self.site_plan_text, pm_model,
                        instruction="Extract the site plan from this output:",
                    )
                if site_plan is not None:
                    self.site_plan_text = site_plan.model_dump_json(indent=2)
                    try:
                        self._pm.write_guide(project.id, "site-plan.json", self.site_plan_text)
                        ws.write_file(".agentsite/site-plan.json", self.site_plan_text)
                    except Exception:
                        logger.debug("site-plan persistence skipped", exc_info=True)
                    await self._emit("site_plan_ready", data={
                        "site_plan": site_plan.model_dump(),
                        "required_agents": planned_agents,
                        "tech_stack": {"framework": template.id},
                    })
            else:
                # Tweak path: the existing plan is the contract
                self.site_plan_text = existing_plan_text
                try:
                    site_plan = SitePlan.model_validate(json.loads(clean_json_text(existing_plan_text)))
                except Exception:
                    site_plan = None
                await self._emit("site_plan_ready", data={
                    "site_plan": site_plan.model_dump() if site_plan else {},
                    "required_agents": planned_agents,
                    "tech_stack": {"framework": template.id},
                    "source": "existing",
                })

            if cancel_event and cancel_event.is_set():
                return self._cancelled_result(slug, version_number)

            # -- Phase B: design tokens ----------------------------------
            spec: StyleSpec | None = None
            if has_direction:
                from ..agents.directions import find_direction, synthesize_style_spec

                _direction = find_direction(discovery_brief.direction_id)
                if _direction is not None:
                    spec = synthesize_style_spec(_direction)
                    self.style_spec_text = spec.model_dump_json()
                    await self._emit("style_spec_ready", data={
                        "style_spec": self.style_spec_text,
                        "parsed": True,
                        "source": "direction",
                        "direction_id": _direction.id,
                    })

            if spec is None and run_designer:
                from ..agents.designer import create_designer_agent_auto

                designer_model = self._agent_models["designer"]
                designer_agent = create_designer_agent_auto(designer_model)
                _apply_agent_overrides(designer_agent, "designer", self._agent_configs)
                self._inject_driver(designer_agent, designer_model)

                designer_prompt = (
                    "Design a visual style for this website:\n\n"
                    + (f"{discovery_brief_text}\n\n" if discovery_brief_text else "")
                    + f"Site Plan: {self.site_plan_text}\n\n"
                    "Create a cohesive color scheme, typography, and spacing system."
                )
                designer_result = await self._run_agent(
                    "designer", designer_agent, designer_prompt,
                    {"project_dir": self._pm.project_dir(project.id)},
                    project_id=project.id, slug=slug, version=version_number, session_id=session_id,
                )
                designer_text = getattr(designer_result, "output_text", "") or ""
                try:
                    spec = StyleSpec.model_validate(json.loads(clean_json_text(designer_text)))
                except Exception:
                    from .extract import extract_structured

                    spec = await extract_structured(
                        StyleSpec, designer_text, designer_model,
                        instruction="Extract the design style specification from this output:",
                    )
                if spec is not None:
                    self.style_spec_text = spec.model_dump_json()
                    await self._emit("style_spec_ready", data={
                        "style_spec": self.style_spec_text, "parsed": True,
                    })

            fresh_spec = spec is not None  # direction-synthesized or designer-produced
            if spec is None:
                spec = project.style_spec or StyleSpec()
                if not self.style_spec_text:
                    self.style_spec_text = spec.model_dump_json()

            # Rewrite the tokens file only when the design actually changed
            # (or on first build) — scoped follow-ups must not clobber it.
            if fresh_spec or version_number == 1:
                tokens_css = render_tokens_css(spec, template.tokens_format)
                ws.write_file(template.tokens_path, tokens_css)
                _on_file_written(template.tokens_path)
                _checkpoint(f"v{version_number}: design tokens")

            if cancel_event and cancel_event.is_set():
                return self._cancelled_result(slug, version_number)

            # -- Phase C: resident dev session + review cycles -----------
            await self._emit("phase_start", data={
                "phase": "build", "slug": slug, "version": version_number,
            })

            dev_kwargs: dict[str, Any] = {}
            if max_cost:
                dev_kwargs["max_cost"] = max_cost
            dev_agent = AsyncAgent(
                model=dev_model,
                tools=dev_workspace_tools,
                system_prompt=PROJECT_DEVELOPER_PERSONA,
                max_iterations=settings.project_dev_max_iterations,
                options=dict(_DEV_OPTIONS),
                persistent_conversation=True,
                name="agentsite_developer",
                **dev_kwargs,
            )
            _apply_agent_overrides(dev_agent, "developer", self._agent_configs)
            self._inject_driver(dev_agent, dev_model)

            dev_deps: dict[str, Any] = {
                "workspace_dir": ws.workspace_dir,
                "template": template,
                "project_id": project.id,
                "project_dir": self._pm.project_dir(project.id),
                "written_files": written_files,
                "on_file_written": _on_file_written,
                "on_preview_update": _on_preview_update,
                "emit_event": _emit_data,
                "assets_dir": ws.uploads_dir(template),
                "asset_rel_prefix": "uploads/",
                "build_dirty": True,
                "last_build_ok": False,
                # Phase E — specialist delegation
                "specialist_models": {
                    k: _agent_model(k, model, self._agent_configs)
                    for k in ("copywriter", "seo", "accessibility", "animation")
                },
                "subagent_runs": [],
                "_delegations_left": settings.specialist_max_delegations,
                "provider_keys": self._provider_keys,
            }

            template_doc = read_template_doc(template.id)
            build_note = (
                "When you finish your changes, run_command('build') and fix any "
                "errors until it passes."
                if template.kind == "node"
                else "This template has no build step — files are served directly."
            )
            if decision.bucket == "tweak":
                task_text = (
                    f"## Task — small scoped change\n{page_prompt}\n\n"
                    "The site already exists and works. Make ONLY the edits this "
                    "request needs (prefer edit_file); change nothing else. "
                    f"{build_note}"
                )
            elif decision.bucket == "partial":
                task_text = (
                    f"## Task — incremental update\n{page_prompt}\n\n"
                    "The site already exists. Implement this update against the "
                    "current workspace: add or modify only what the request and the "
                    "updated site plan require, keep everything else intact, and "
                    f"keep navigation consistent across all pages. {build_note}"
                )
            else:
                task_text = (
                    f"## Task\n{page_prompt}\n\nBuild the COMPLETE site now: every page in "
                    f"the site plan, with working navigation between them. {build_note}"
                )

            initial_parts = [p for p in (
                discovery_brief_text,
                memory_block,
                f"## Site plan\n{self.site_plan_text}",
                f"## Template contract — follow this exactly\n{template_doc}" if template_doc else "",
                (
                    f"## Design tokens\nAlready written to `{template.tokens_path}` by the "
                    "Designer. Consume these variables everywhere; never hardcode colors/fonts."
                ),
                uploads_listing,
                (f"## Conversation context\n{conversation_context}" if conversation_context else ""),
                task_text,
            ) if p]
            dev_prompt = "\n\n".join(initial_parts)

            max_cycles = max_review_iterations or settings.project_max_cycles
            threshold = review_threshold or settings.review_approval_threshold
            approved = False
            success = True
            verify_ok: bool | None = None
            last_verify_report: verifier.VerifyReport | None = None

            for cycle in range(1, max_cycles + 1):
                try:
                    from .interrupt import mailbox as _sm

                    drained = _sm.drain(project.id)
                    if drained:
                        steer = "\n".join(f"- {s}" for s in drained)
                        dev_prompt += f"\n\n## User steering (apply this)\n{steer}"
                        await self._emit("steer_applied", data={"text": steer, "count": len(drained)})
                except Exception:
                    pass

                await self._run_agent(
                    "developer", dev_agent, dev_prompt, dev_deps,
                    project_id=project.id, slug=slug, version=version_number, session_id=session_id,
                )
                self._drain_subagent_runs(
                    dev_deps, project_id=project.id, slug=slug,
                    version=version_number, session_id=session_id,
                )

                if cancel_event and cancel_event.is_set():
                    return self._cancelled_result(slug, version_number)

                # Safety-net build: the dev agent is told to build, but never
                # trust "it should be fine" — verify before preview/review.
                if template.kind == "node" and (
                    dev_deps.get("build_dirty", True) or not dev_deps.get("last_build_ok")
                ):
                    await self._emit("build_started", data={
                        "command": " ".join(template.build_cmd or ["npm", "run", "build"]),
                    })
                    build_res = await build_workspace(ws.workspace_dir, template)
                    build_ok = build_res.ok if build_res is not None else True
                    await self._emit("build_finished", data={
                        "ok": build_ok,
                        "duration_s": getattr(build_res, "duration_s", 0.0),
                        "output_tail": getattr(build_res, "tail", "")[-1500:],
                    })
                    dev_deps["last_build_ok"] = build_ok
                    if build_ok:
                        dev_deps["build_dirty"] = False
                    else:
                        _checkpoint(f"v{version_number} cycle {cycle}: build failed")
                        if cycle == max_cycles:
                            success = False
                            break
                        dev_prompt = (
                            "The production build FAILED. Output:\n\n"
                            f"{build_res.tail if build_res else ''}\n\n"
                            "Fix the errors with targeted edits (edit_file), then "
                            "run_command('build') until it passes."
                        )
                        continue

                await self._emit("preview_ready", data={
                    "url": f"/preview/{project.id}/app/",
                    "build_hash": uuid.uuid4().hex[:8],
                })
                _checkpoint(f"v{version_number} cycle {cycle}")

                # -- verify (hard gate the reviewer cannot override) --
                last_verify_report = None
                if settings.verify_enabled:
                    serve_root = (
                        ws.workspace_dir / (template.output_dir or "dist")
                        if template.kind == "node"
                        else ws.workspace_dir
                    )
                    planned, _ = verifier.plan_routes(template, site_plan, serve_root)
                    await self._emit("verify_started", data={
                        "routes": [label for label, _ in planned],
                    })
                    report = await verifier.run_verification(
                        ws.workspace_dir, template, site_plan, version_number,
                    )
                    last_verify_report = report
                    if not report.skipped:
                        verify_ok = report.ok
                    await self._emit("verify_report", data={
                        "ok": report.ok,
                        "skipped": report.skipped,
                        "skip_reason": report.skip_reason,
                        "summary": report.render_summary(),
                        "duration_s": report.duration_s,
                        "missing_pages": report.missing_pages,
                        "routes": [r.model_dump() for r in report.routes],
                        "screenshot_urls": [
                            f"/preview/{project.id}/verify/{rel}"
                            for rel in report.screenshot_rel_paths
                        ],
                    })
                    if not verifier.evaluate_gate(report):
                        if cycle == max_cycles:
                            approved = False
                            break
                        dev_prompt = report.render_feedback() + (
                            "\n\nThen run_command('build') and make sure it passes."
                            if template.kind == "node" else ""
                        )
                        continue

                # Tweaks skip the LLM review — verification already gated the
                # result, and a scoped edit doesn't justify a full QA pass.
                if skip_review:
                    approved = True
                    break

                # -- review --
                reviewer_model = self._agent_models["reviewer"]
                reviewer_agent = AsyncAgent(
                    model=reviewer_model,
                    tools=reviewer_workspace_tools,
                    system_prompt=PROJECT_REVIEWER_PERSONA,
                    max_iterations=15,
                    options=dict(_REVIEWER_OPTIONS),
                    name="agentsite_reviewer",
                )
                _apply_agent_overrides(reviewer_agent, "reviewer", self._agent_configs)
                self._inject_driver(reviewer_agent, reviewer_model)

                # Vision review: attach verification screenshots (desktop first)
                # when the reviewer model supports images — judge what the
                # user actually sees, not just the markup.
                review_images: list[str] | None = None
                verify_note = ""
                if last_verify_report is not None and not last_verify_report.skipped:
                    verify_note = f"\nAutomated verification: {last_verify_report.render_summary()}\n"
                    shots = [
                        str(ws.workspace_dir / ".agentsite" / "verify" / rel)
                        for rel in last_verify_report.screenshot_rel_paths
                    ]
                    shots.sort(key=lambda s: 0 if "desktop" in s else 1)
                    if shots and supports_vision(reviewer_model):
                        review_images = shots[:6]

                review_prompt = (
                    "Review the project workspace against this site plan:\n\n"
                    f"{self.site_plan_text}\n\n"
                    f"Original user brief:\n{page_prompt}\n"
                    + verify_note
                    + (
                        "\nScreenshots of the RENDERED site (desktop first, then mobile) "
                        "are attached — judge the visual result from them: layout, "
                        "hierarchy, spacing, responsiveness, polish. Use your file tools "
                        "only to cross-check causes of visual problems.\n"
                        if review_images
                        else ""
                    )
                    + "\nInspect with your tools, then respond ONLY with the "
                    "ReviewFeedback JSON object."
                )
                review_deps = {"workspace_dir": ws.workspace_dir, "template": template}
                review_result = await self._run_agent(
                    "reviewer", reviewer_agent, review_prompt, review_deps,
                    project_id=project.id, slug=slug, version=version_number, session_id=session_id,
                    images=review_images,
                )
                review_text = getattr(review_result, "output_text", "") or ""

                feedback: ReviewFeedback | None = None
                try:
                    feedback = ReviewFeedback.model_validate(json.loads(clean_json_text(review_text)))
                except Exception:
                    logger.warning("Reviewer output unparseable — accepting build as-is")

                if feedback is None:
                    approved = True
                    break

                await self._emit("review_feedback", data={
                    "score": feedback.score,
                    "approved": feedback.approved,
                    "issues": feedback.issues,
                    "suggestions": feedback.suggestions,
                })

                if feedback.approved or feedback.score >= threshold:
                    approved = True
                    break
                if cycle == max_cycles:
                    break

                issues = "\n".join(f"- {i}" for i in feedback.issues) or "- (none listed)"
                suggestions = "\n".join(f"- {s}" for s in feedback.suggestions)
                dev_prompt = (
                    f"The reviewer scored the site {feedback.score}/10. Fix these issues "
                    "with TARGETED edits (edit_file) — do not rewrite files wholesale:\n\n"
                    f"## Issues\n{issues}\n"
                    + (f"\n## Suggestions\n{suggestions}\n" if suggestions else "")
                    + ("\nThen run_command('build') and make sure it passes." if template.kind == "node" else "")
                )

            # -- finalize -------------------------------------------------
            final_files = ws.list_files()
            files_content = ws.collect_files_content()
            if not final_files:
                raise RuntimeError(
                    "Project generation finished but the workspace is empty — "
                    "the developer agent produced no files."
                )

            # Phase E — flagged multi-dimension critique panel + ratchet,
            # reading the workspace (and the verify summary) instead of a
            # mockup page dir. Off by default (settings.use_critique_panel).
            if settings.use_critique_panel and approved and final_files:
                try:
                    from ..agents.critique import run_critique_panel
                    from .ratchet import update_ratchet

                    judge_model = self._agent_models.get("reviewer") or model
                    panel_deps = {
                        "version_dir": ws.workspace_dir,
                        "project_dir": self._pm.project_dir(project.id),
                    }
                    context_note = (
                        last_verify_report.render_summary()
                        if last_verify_report is not None else ""
                    )
                    verdict, _debate = await run_critique_panel(
                        judge_model, page_slug=slug, deps=panel_deps,
                        context_note=context_note,
                    )
                    if verdict is not None:
                        ratchet, accepted, regressed = update_ratchet(
                            project.id, verdict, slug=slug, version=version_number,
                        )
                        await self._emit("critique_verdict", data={
                            "verdict": verdict.model_dump(),
                            "accepted": accepted,
                            "regressed": regressed,
                            "floors": ratchet.floors,
                        })
                except Exception:
                    logger.warning("Critique panel failed (non-fatal)", exc_info=True)

            await self._emit("generation_complete", data={
                "success": success,
                "slug": slug,
                "version": version_number,
                "files": final_files,
                "files_content": files_content,
                "usage": self._usage,
                "approved": approved,
                "verify_ok": verify_ok,
                "bucket": decision.bucket,
            })

            return GroupResult(
                agent_results=[],
                aggregate_usage=dict(self._usage),
                shared_state={},
                elapsed_ms=int((time.monotonic() - t0) * 1000),
                timeline=[],
                errors=[],
                success=success,
            )

        except Exception as exc:
            import traceback

            logger.exception(
                "Project generation failed for project %s v%d", project.id, version_number
            )
            await self._emit("error", data={"message": str(exc), "traceback": traceback.format_exc()})
            await self._emit("generation_complete", data={
                "success": False,
                "slug": slug,
                "version": version_number,
                "files": [],
                "error": str(exc),
            })
            raise

        finally:
            if self._cachibot_api_key:
                if _prev_cachibot_key is not None:
                    _os.environ["CACHIBOT_API_KEY"] = _prev_cachibot_key
                else:
                    _os.environ.pop("CACHIBOT_API_KEY", None)

    def _drain_subagent_runs(
        self,
        deps: dict[str, Any],
        *,
        project_id: str,
        slug: str,
        version: int,
        session_id: str,
    ) -> None:
        """Fold specialist sub-agent runs (recorded by delegate_to_specialist)
        into the pipeline's AgentRun records and usage totals."""
        entries = deps.get("subagent_runs") or []
        deps["subagent_runs"] = []
        for entry in entries:
            input_tokens = int(entry.get("input_tokens", 0) or 0)
            output_tokens = int(entry.get("output_tokens", 0) or 0)
            cost = float(entry.get("cost", 0.0) or 0.0)
            self.agent_runs.append(AgentRun(
                project_id=project_id,
                page_slug=slug,
                version=version,
                agent_name=str(entry.get("agent", "specialist")),
                status="completed",
                session_id=session_id,
                model=str(entry.get("model", "")),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost=cost,
                completed_at=datetime.now(timezone.utc).isoformat(),
            ))
            self._add_usage(input_tokens, output_tokens, cost)

    def _cancelled_result(self, slug: str, version_number: int) -> GroupResult:
        return GroupResult(
            agent_results=[], aggregate_usage=dict(self._usage),
            shared_state={}, elapsed_ms=0, timeline=[], errors=[],
            success=False,
        )
