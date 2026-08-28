"""High-level generation pipeline wiring agents, callbacks, and storage."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from prompture import AsyncSequentialGroup, ErrorPolicy, GroupCallbacks, GroupResult

from ..agents.orchestrator import (
    _agent_model,
    _apply_agent_overrides,
    create_dynamic_pipeline,
    create_specialist_pipeline,
)
from ..config import settings
from ..models import (
    AgentConfig,
    AgentRun,
    DiscoveryBrief,
    PageOutput,
    Project,
    ReviewFeedback,
    SitePlan,
    StyleSpec,
    TechStack,
    WSEvent,
)
from .project_manager import ProjectManager

logger = logging.getLogger("agentsite.pipeline")


def _agent_name_to_key(name: str) -> str:
    """Normalize agent name to short key (handles both persona and agent names)."""
    _NAME_MAP = {
        "agentsite_pm": "pm",
        "agentsite_designer": "designer",
        "agentsite_developer": "developer",
        "agentsite_reviewer": "reviewer",
        "agentsite_markup": "markup",
        "agentsite_style": "style",
        "agentsite_style_scss": "style_scss",
        "agentsite_script": "script",
        "agentsite_image": "image",
        "agentsite_copywriter": "copywriter",
        "agentsite_seo": "seo",
        "agentsite_accessibility": "accessibility",
        "agentsite_animation": "animation",
        "agentsite_render_verify": "render_verify",
    }
    return _NAME_MAP.get(name, name)


def _attach_streaming_callbacks(group: Any, emit_fn: Any) -> None:
    """Attach AgentCallbacks for real-time streaming events to all agents in a group.

    Wires up tool start/end, thinking, step, iteration, and text output
    callbacks so the frontend receives granular progress via WebSocket.
    """
    try:
        from prompture import AgentCallbacks
    except ImportError:
        return  # AgentCallbacks not available in this version

    agents = getattr(group, "_agents", [])
    for item in agents:
        agent = item[0] if isinstance(item, tuple) else item
        if hasattr(agent, "_agents"):
            _attach_streaming_callbacks(agent, emit_fn)
        else:
            agent_key = _agent_name_to_key(agent.name)

            async def _on_tool_start(name: str, args: Any, *, _key: str = agent_key) -> None:
                await emit_fn("tool_start", agent=_key, data={"name": name, "args": args})

            async def _on_tool_end(name: str, result: Any, *, _key: str = agent_key) -> None:
                await emit_fn("tool_end", agent=_key, data={"name": name, "result": str(result)[:500]})

            async def _on_thinking(text: str, *, _key: str = agent_key) -> None:
                await emit_fn("agent_thinking", agent=_key, data={"text": text[:2000]})

            async def _on_step(step: Any, *, _key: str = agent_key) -> None:
                await emit_fn("agent_step", agent=_key, data={
                    "step_type": step.step_type.value if hasattr(step.step_type, "value") else str(step.step_type),
                    "content": (step.content or "")[:500],
                    "tool_name": getattr(step, "tool_name", None),
                })

            async def _on_iteration(idx: int, *, _key: str = agent_key) -> None:
                await emit_fn("agent_iteration", agent=_key, data={"iteration": idx})

            async def _on_message(text: str, *, _key: str = agent_key) -> None:
                """Emit agent text output as a text_delta event for real-time display."""
                if text:
                    await emit_fn("text_delta", agent=_key, data={"text": text[:4000]})

            async def _on_output(result: Any, *, _key: str = agent_key) -> None:
                """Emit structured output preview when agent produces final result."""
                output_text = getattr(result, "output_text", "") or ""
                if output_text:
                    await emit_fn("agent_output", agent=_key, data={
                        "text": output_text[:2000],
                    })

            agent.callbacks = AgentCallbacks(
                on_tool_start=_on_tool_start,
                on_tool_end=_on_tool_end,
                on_thinking=_on_thinking,
                on_step=_on_step,
                on_iteration=_on_iteration,
                on_message=_on_message,
                on_output=_on_output,
            )


def _merge_nested_group_state(group: Any) -> None:
    """After a pipeline runs, merge nested group state back to the parent.

    The developer's ``page_output`` is stored in the LoopGroup's state
    but never propagated to the parent SequentialGroup.  This helper
    copies nested state back up so the pipeline can access it.

    Child state *always* overwrites parent state — the child ran later
    and holds the most up-to-date values for keys like ``page_output``
    and ``review_feedback``.
    """
    agents = getattr(group, "_agents", [])
    for item in agents:
        agent = item[0] if isinstance(item, tuple) else item
        if hasattr(agent, "shared_state") and hasattr(agent, "_agents"):
            # Recurse first
            _merge_nested_group_state(agent)
            # Merge child state into parent (child always wins)
            for k, v in agent.shared_state.items():
                group._state[k] = v


def _build_budget_kwargs(
    max_cost: float | None,
    policy: str | None,
    max_tokens: int | None,
    fallback_models: list[str] | None,
    on_fallback: Any | None,
) -> dict[str, Any]:
    """Build kwargs dict for budget enforcement on pipeline groups and agents.

    Returns a dict with ``max_total_cost`` (for groups) and
    ``budget_policy``, ``fallback_models``, ``budget_max_tokens``,
    ``on_model_fallback`` (for agents via orchestrator).
    """
    kwargs: dict[str, Any] = {}
    if max_cost:
        kwargs["max_total_cost"] = max_cost
    if policy:
        try:
            from prompture.infra import BudgetPolicy

            kwargs["budget_policy"] = BudgetPolicy(policy)
        except (ValueError, ImportError):
            pass
        else:
            if max_tokens:
                kwargs["budget_max_tokens"] = max_tokens
            if fallback_models:
                kwargs["fallback_models"] = fallback_models
            if on_fallback:
                kwargs["on_model_fallback"] = on_fallback
    return kwargs


class GenerationPipeline:
    """Orchestrates the generation process for a single page version.

    Bridges the Prompture agent pipeline with the project filesystem
    and optional WebSocket event callbacks.
    """

    def __init__(
        self,
        project_manager: ProjectManager,
        *,
        on_event: Callable[[WSEvent], None] | None = None,
        agent_configs: dict[str, AgentConfig] | None = None,
        cachibot_api_key: str | None = None,
        provider_keys: dict[str, str] | None = None,
        project_component_repo: Any | None = None,
    ) -> None:
        self._pm = project_manager
        self._on_event = on_event
        self._agent_configs = agent_configs
        self._cachibot_api_key = cachibot_api_key
        self._provider_keys = provider_keys
        self._project_component_repo = project_component_repo
        self.agent_runs: list[AgentRun] = []
        self._active_runs: dict[str, AgentRun] = {}
        self._run_start_times: dict[str, float] = {}
        self._developer_output_text: str = ""  # direct capture from callback
        self._developer_tool_calls: list[dict] = []  # tool calls from developer agent
        self._agent_models: dict[str, str] = {}  # agent_key -> resolved model name
        self.site_plan_text: str = ""  # raw PM output for guide persistence
        self.style_spec_text: str = ""  # raw Designer output for project persistence

    def _inject_driver(self, agent: Any, model_str: str) -> None:
        """Inject a per-project driver into an agent if provider_keys are set.

        Uses the driver factory to build a custom driver with per-project
        API keys, so this project's generation uses its own credentials.
        """
        if not self._provider_keys:
            return

        from .driver_factory import resolve_driver_for_model

        driver = resolve_driver_for_model(model_str, self._provider_keys)
        if driver is not None:
            agent.driver = driver
            logger.debug("Injected per-project driver for %s (model=%s)", agent.name, model_str)

    async def _emit(self, event_type: str, agent: str = "", data: dict[str, Any] | None = None) -> None:
        """Fire a WebSocket event if a callback is registered."""
        if self._on_event:
            result = self._on_event(WSEvent(type=event_type, agent=agent, data=data or {}))
            if asyncio.iscoroutine(result):
                await result

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
        """Run the generation pipeline for a single page version.

        Args:
            project: The parent project.
            slug: Page slug (e.g. "home", "about").
            version_number: Version number to write to.
            page_prompt: The prompt describing what to build for this page.

        Returns:
            GroupResult from the Prompture pipeline.
        """
        model = project.model or settings.default_model

        # Ensure the version directory exists
        version_dir = self._pm.ensure_version_dir(project.id, slug, version_number)

        # Track written files for WS events
        written_files: list[str] = []

        _background_tasks: list[asyncio.Task] = []  # prevent GC of fire-and-forget tasks

        def _on_file_written(path: str) -> None:
            written_files.append(path)
            try:
                loop = asyncio.get_running_loop()
                task = loop.create_task(self._emit("file_written", data={"path": path}))
                _background_tasks.append(task)
                task.add_done_callback(_background_tasks.remove)
            except RuntimeError:
                pass  # No event loop in thread context — file_written events are nice-to-have

        def _on_preview_update(path: str, html: str) -> None:
            # Phase 6 — emit a `preview_update` WS event with the rendered
            # HTML so the frontend can swap the iframe to srcdoc mode.
            try:
                loop = asyncio.get_running_loop()
                # Stable content hash for iframe key=hash remount semantics
                import hashlib as _hashlib
                content_hash = _hashlib.sha1(html.encode("utf-8")).hexdigest()[:12]
                task = loop.create_task(self._emit("preview_update", data={
                    "page_slug": slug,
                    "path": path,
                    "html": html,
                    "content_hash": content_hash,
                    "bytes": len(html),
                }))
                _background_tasks.append(task)
                task.add_done_callback(_background_tasks.remove)
            except RuntimeError:
                pass

        def _on_asset_created(filename: str) -> None:
            try:
                loop = asyncio.get_running_loop()
                task = loop.create_task(
                    self._emit("asset_created", data={"filename": filename})
                )
                _background_tasks.append(task)
                task.add_done_callback(_background_tasks.remove)
            except RuntimeError:
                pass

        async def _on_agent_start(name: str, prompt: str) -> None:
            agent_key = _agent_name_to_key(name)
            started_at = datetime.now(timezone.utc).isoformat()
            agent_model = self._agent_models.get(agent_key, "")
            # Phase 13 — record the routing strategy that picked this model
            strategy = settings.agent_routing.get(agent_key, "")
            if "/" in strategy:  # explicit model override — not a strategy
                strategy = "explicit"
            await self._emit("agent_start", agent=agent_key, data={
                "started_at": started_at,
                "model": agent_model,
                "strategy": strategy,
            })
            run = AgentRun(
                project_id=project.id,
                page_slug=slug,
                version=version_number,
                agent_name=agent_key,
                status="running",
                session_id=session_id,
                strategy=strategy,
                model=agent_model,
            )
            self._active_runs[name] = run
            self._run_start_times[name] = time.monotonic()
            self.agent_runs.append(run)

        async def _on_agent_complete(name: str, result: Any) -> None:
            agent_key = _agent_name_to_key(name)
            run = self._active_runs.pop(name, None)
            start_time = self._run_start_times.pop(name, None)
            duration_s = round(time.monotonic() - start_time, 1) if start_time else None

            output_text = getattr(result, "output_text", "") or ""
            tool_calls = getattr(result, "all_tool_calls", []) or []

            input_tokens = 0
            output_tokens = 0
            if run:
                run.status = "completed"
                run.completed_at = datetime.now(timezone.utc).isoformat()
                # Try multiple usage key formats (OpenAI vs Gemini vs Anthropic)
                usage = getattr(result, "usage", None) or getattr(result, "run_usage", None) or {}
                if isinstance(usage, dict):
                    input_tokens = (
                        usage.get("input_tokens", 0)
                        or usage.get("prompt_tokens", 0)
                        or usage.get("promptTokenCount", 0)
                    )
                    output_tokens = (
                        usage.get("output_tokens", 0)
                        or usage.get("completion_tokens", 0)
                        or usage.get("candidatesTokenCount", 0)
                    )
                    run.input_tokens = input_tokens
                    run.output_tokens = output_tokens
                    run.cost = float(
                        usage.get("cost", 0.0)
                        or usage.get("total_cost", 0.0)  # backwards compat
                        or 0.0
                    )

            # Emit review_feedback when reviewer completes
            if agent_key == "reviewer" and output_text:
                try:
                    from prompture import clean_json_text as _cjt2
                    _rfb_data = json.loads(_cjt2(output_text))
                    _rfb = ReviewFeedback.model_validate(_rfb_data) if isinstance(_rfb_data, dict) else None
                except Exception:
                    _rfb = None
                if _rfb is not None:
                    await self._emit("review_feedback", data={
                        "score": _rfb.score,
                        "approved": _rfb.approved,
                        "issues": _rfb.issues,
                        "suggestions": _rfb.suggestions,
                    })

            # Phase 12 — surface refusal-like outputs as a WS warning so the
            # frontend can show a "try a different model" hint. Non-fatal —
            # the existing fallback chain handles empty output too. Also
            # stamp the active AgentRun so it shows up in analytics later.
            if output_text:
                try:
                    from .refusal import detect_refusal
                    sig = detect_refusal(output_text)
                    if sig.is_refusal:
                        if run is not None:
                            if not isinstance(run.output_summary, dict):
                                run.output_summary = {}
                            run.output_summary["refusal"] = {
                                "reason": sig.reason,
                                "matched": sig.matched[:200],
                            }
                        await self._emit("refusal_detected", agent=agent_key, data={
                            "reason": sig.reason,
                            "matched": sig.matched,
                            "model": self._agent_models.get(agent_key, ""),
                        })
                except Exception:
                    pass

            # Phase 7 — when the developer was a DeepAgent, snapshot its
            # todo list and emit it for the live TodoStream UI.
            if agent_key == "developer":
                try:
                    deep_state = getattr(result, "deep_state", None) or getattr(
                        getattr(result, "agent", None), "deep_state", None
                    )
                    if deep_state is not None and getattr(deep_state, "todos", None):
                        todos_payload = [
                            t.to_dict() if hasattr(t, "to_dict") else dict(t)
                            for t in deep_state.todos
                        ]
                        if todos_payload:
                            await self._emit("todo_update", agent="developer", data={
                                "todos": todos_payload,
                            })
                except Exception:
                    pass

            # Capture developer/specialist output for fallback extraction
            _build_agents = {"developer", "markup", "style", "style_scss", "script"}
            if agent_key in _build_agents:
                if agent_key == "developer":
                    self._developer_output_text = output_text
                    self._developer_tool_calls = tool_calls
                logger.info(
                    "%s agent completed: output_text length=%d, tool_calls=%d, output_text[:200]=%s",
                    agent_key,
                    len(output_text),
                    len(tool_calls),
                    repr(output_text[:200]),
                )
                if tool_calls:
                    for tc in tool_calls:
                        logger.info(
                            "  tool_call: %s(%s)",
                            tc.get("name", "?"),
                            ", ".join(f"{k}=...({len(str(v))})" for k, v in (tc.get("arguments") or {}).items()),
                        )

            # Extract reasoning/thinking from assistant messages.
            # Prompture >= 1.9.1 attaches reasoning_content to assistant
            # messages on all code paths (not just native tool use).
            reasoning_text = ""
            result_messages = getattr(result, "messages", []) or []
            for msg in result_messages:
                if isinstance(msg, dict) and msg.get("role") == "assistant" and msg.get("reasoning_content"):
                    reasoning_text = msg["reasoning_content"]

            # When a reasoning model returns empty content (e.g. Kimi K2.5),
            # the driver uses reasoning_content as the text response.  Detect
            # this so we don't show reasoning twice (once as output, once as
            # thinking) and so the pipeline knows the real output was empty.
            if reasoning_text and output_text and output_text.strip() == reasoning_text.strip():
                logger.info(
                    "Agent %s output equals reasoning (%d chars) — actual content was empty",
                    agent_key,
                    len(reasoning_text),
                )
                output_text = ""

            if agent_key == "developer" and reasoning_text:
                self._developer_reasoning = reasoning_text

            agent_model = self._agent_models.get(agent_key, "")
            agent_cost = run.cost if run else 0.0
            await self._emit(
                "agent_complete",
                agent=agent_key,
                data={
                    "output_preview": output_text[:2000],
                    "full_output": output_text,
                    "duration_s": duration_s,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cost": agent_cost,
                    "tool_calls_count": len(tool_calls),
                    "model": agent_model,
                    "reasoning": reasoning_text,
                },
            )

        async def _on_agent_error(name: str, exc: Exception) -> None:
            agent_key = _agent_name_to_key(name)
            # Emit as "agent_error" (non-fatal) rather than "error" (fatal).
            # The pipeline may retry this agent with a fallback, so we don't
            # want the frontend to disconnect the WebSocket prematurely.
            await self._emit("agent_error", agent=agent_key, data={"message": str(exc)})
            run = self._active_runs.pop(name, None)
            if run:
                run.status = "failed"
                run.completed_at = datetime.now(timezone.utc).isoformat()
                run.output_summary = {"error": str(exc)}

        async def _on_state_update(key: str, value: Any) -> None:
            await self._emit("state_update", data={"key": key, "value_preview": str(value)[:200]})

        async def _on_round_start(round_number: int) -> None:
            await self._emit("round_start", data={"round": round_number})

        async def _on_round_complete(round_number: int) -> None:
            await self._emit("round_complete", data={"round": round_number})

        # Build group callbacks that bridge to WS events
        group_callbacks = GroupCallbacks(
            on_agent_start=_on_agent_start,
            on_agent_complete=_on_agent_complete,
            on_agent_error=_on_agent_error,
            on_state_update=_on_state_update,
            on_round_start=_on_round_start,
            on_round_complete=_on_round_complete,
        )

        # Inject deps for tools (they read from RunContext.deps)
        deps = {
            "project_dir": self._pm.project_dir(project.id),
            "version_dir": version_dir,
            "assets_dir": self._pm.assets_dir(project.id),
            "project_id": project.id,
            "on_file_written": _on_file_written,
            "on_asset_created": _on_asset_created,
            "on_preview_update": _on_preview_update,
            "written_files": written_files,
        }
        # Phase 3 — pre-flight gate state. write_file checks
        # `_preflight_required`; read_guide records into `_preflight_read`.
        if settings.preflight_enabled and settings.preflight_required_guides:
            deps["_preflight_required"] = set(settings.preflight_required_guides)
            deps["_preflight_read"] = set()

        # Phase 10 — load top memories for this project so the PM has context.
        memory_block = ""
        try:
            from ..api import deps as _api_deps
            from .memory import render_for_context as _render_mem

            if getattr(_api_deps, "memory_repo", None) is not None:
                _facts = await _api_deps.memory_repo.list_by_project(project.id, limit=15)
                memory_block = _render_mem(_facts)
        except Exception:
            logger.debug("Memory load skipped", exc_info=True)

        # Phase 7 — drain any pending steer messages so the run starts clean
        try:
            from .interrupt import mailbox as _steer_mailbox
            _steer_mailbox.clear(project.id)
        except Exception:
            pass

        # Phase 1 — surface the discovery brief (if any) before planning starts
        discovery_brief_text = ""
        if discovery_brief is not None:
            from ..agents.discovery import render_brief

            discovery_brief_text = render_brief(discovery_brief)
            await self._emit(
                "discovery_brief_submitted",
                data={"brief": discovery_brief.model_dump(), "rendered": discovery_brief_text},
            )

        await self._emit("phase_start", data={"phase": "planning", "slug": slug, "version": version_number})

        session_id = f"gen-{project.id}-{slug}-v{version_number}"

        # Inject per-user CachiBot API key into env for this generation
        import os as _os

        _prev_cachibot_key = _os.environ.get("CACHIBOT_API_KEY")
        if self._cachibot_api_key:
            _os.environ["CACHIBOT_API_KEY"] = self._cachibot_api_key

        try:
            # --- Resolve model for each agent and store for WS events ---
            from ..agents.pm import create_pm_agent_auto

            for agent_key in ("pm", "designer", "developer", "reviewer"):
                self._agent_models[agent_key] = _agent_model(agent_key, model, self._agent_configs)

            # --- Phase A: Run PM agent standalone to get SitePlan ---
            pm_model = self._agent_models["pm"]
            # Use auto factory to select structured/plain mode based on capabilities
            pm_agent = create_pm_agent_auto(pm_model)
            _apply_agent_overrides(pm_agent, "pm", self._agent_configs)
            self._inject_driver(pm_agent, pm_model)

            pm_callbacks = GroupCallbacks(
                on_agent_start=_on_agent_start,
                on_agent_complete=_on_agent_complete,
                on_agent_error=_on_agent_error,
            )
            # Phase 11 wiring — retrieve the top relevant skills + design
            # systems for this brief and inline them, so the PM can pick from
            # a short ranked list instead of from a hardcoded full catalog.
            skill_block = ""
            design_system_block = ""
            try:
                from .rag_index import retrieve as _rag_retrieve

                _skill_hits = _rag_retrieve(page_prompt, k=5, kinds=["skill"])
                if _skill_hits:
                    skill_lines = ["## Available skills (sorted by relevance to your brief)"]
                    for h in _skill_hits:
                        skill_lines.append(
                            f"- `{h.entry.id}` (match {h.score:.0%}) — {h.entry.body[:140]}"
                        )
                    skill_block = "\n".join(skill_lines)

                _ds_hits = _rag_retrieve(page_prompt, k=3, kinds=["design_system"])
                if _ds_hits:
                    ds_lines = ["## Candidate design systems (most relevant first)"]
                    for h in _ds_hits:
                        ds_lines.append(f"- `{h.entry.id}` ({h.entry.title}) — match {h.score:.0%}")
                    design_system_block = "\n".join(ds_lines)
            except Exception:
                logger.debug("RAG retrieve skipped", exc_info=True)

            pm_prompt = page_prompt
            prelude_parts = []
            if memory_block:
                prelude_parts.append(memory_block)
            if discovery_brief_text:
                prelude_parts.append(discovery_brief_text)
            if skill_block:
                prelude_parts.append(skill_block)
            if design_system_block:
                prelude_parts.append(design_system_block)
            if prelude_parts:
                pm_prompt = "\n\n---\n\n".join(prelude_parts) + f"\n\n---\n\nUser brief:\n{page_prompt}"

            pm_pipeline = AsyncSequentialGroup(
                [(pm_agent, "{prompt}")],
                callbacks=pm_callbacks,
                state={"prompt": pm_prompt},
                error_policy=ErrorPolicy.raise_on_error,
                deps=deps,
            )
            _attach_streaming_callbacks(pm_pipeline, self._emit)

            pm_result = await pm_pipeline.run(pm_prompt)
            site_plan_text = pm_result.shared_state.get("site_plan", "")
            self.site_plan_text = site_plan_text

            # Persist site plan as a guide file for the Navigation page
            if site_plan_text:
                try:
                    self._pm.write_guide(project.id, "site-plan.json", site_plan_text)
                except Exception:
                    logger.warning("Failed to write site-plan.json guide", exc_info=True)

            # Parse required_agents and tech_stack from the PM output
            required_agents = ["designer", "developer", "reviewer"]  # default
            tech_stack = TechStack()
            site_plan: SitePlan | None = None
            try:
                from prompture import clean_json_text

                cleaned = clean_json_text(site_plan_text)
                plan_data = json.loads(cleaned)
                site_plan = SitePlan.model_validate(plan_data)
            except Exception:
                logger.debug("JSON parse of PM output failed, trying extract_with_model fallback")
                from .extract import extract_structured

                pm_model = self._agent_models.get("pm", model)
                site_plan = await extract_structured(
                    SitePlan,
                    site_plan_text,
                    pm_model,
                    instruction="Extract the site plan from this output:",
                )

            if site_plan is not None:
                required_agents = site_plan.required_agents
                tech_stack = site_plan.tech_stack

                # Phase 5 — find the page's skill (if PM picked one) and surface
                # its instructions to the build pipeline via shared state.
                self._skill_instructions = ""
                self._skill_id = None
                try:
                    page_plan = next(
                        (p for p in site_plan.pages if p.slug == slug),
                        site_plan.pages[0] if site_plan.pages else None,
                    )
                    if page_plan and page_plan.skill_id:
                        from ..skills import find_skill
                        _sk = find_skill(page_plan.skill_id)
                        if _sk is not None:
                            self._skill_id = _sk.name
                            self._skill_instructions = _sk.instructions
                            logger.info("Phase 5: bound skill '%s' for page '%s'", _sk.name, slug)
                            await self._emit("skill_bound", data={
                                "skill": _sk.name,
                                "description": _sk.description,
                                "slug": slug,
                            })
                except Exception:
                    logger.debug("Skill resolution skipped", exc_info=True)

                # Emit site_plan_ready so hosts can inspect structure before design/dev
                await self._emit("site_plan_ready", data={
                    "site_plan": site_plan.model_dump(),
                    "required_agents": required_agents,
                    "tech_stack": tech_stack.model_dump(),
                })

                # Ensure at least one build agent is present
                has_specialists = any(k in required_agents for k in ("markup", "style", "style_scss", "script"))
                if not has_specialists and "developer" not in required_agents:
                    required_agents.append("developer")

                # Defensive guard: some PM models (notably weaker ones)
                # omit 'designer' from required_agents even on fresh builds.
                # For any new build where the user hasn't picked a direction
                # AND the project has no inherited style, the Designer must
                # run — otherwise the developer invents brand identity from
                # scratch and the output is rarely on-brand.
                _has_direction = (
                    discovery_brief is not None
                    and discovery_brief.brand_mode == "pick_direction"
                    and bool(discovery_brief.direction_id)
                )
                _has_inherited = bool(
                    project.style_spec is not None
                    and getattr(project.style_spec, "inherits_from", None)
                )
                if (
                    "designer" not in required_agents
                    and not _has_direction
                    and not _has_inherited
                ):
                    required_agents.insert(0, "designer")
                    logger.info(
                        "Pipeline guard: PM omitted 'designer'; reinstating it "
                        "for fresh build (no direction, no inherited style)."
                    )
            else:
                logger.debug("Could not parse required_agents from PM output, using defaults")

            # Filter out agents that are disabled in agent configs (global or project-level)
            if self._agent_configs:
                disabled_agents = {
                    key for key, cfg in self._agent_configs.items()
                    if not cfg.enabled
                }
                if disabled_agents:
                    before = list(required_agents)
                    required_agents = [a for a in required_agents if a not in disabled_agents]
                    removed = set(before) - set(required_agents)
                    if removed:
                        logger.info("Filtered out disabled agents: %s", removed)
                    # Re-check: if specialist agents were disabled, fall back to developer (if enabled)
                    has_specialists = any(k in required_agents for k in ("markup", "style", "style_scss", "script"))
                    has_developer = "developer" in required_agents
                    if not has_specialists and not has_developer:
                        # All build agents disabled — add developer as fallback unless also disabled
                        if "developer" not in disabled_agents:
                            required_agents.append("developer")
                            logger.info("Added developer agent as fallback (all specialists disabled)")
                        else:
                            logger.warning("All build agents are disabled — generation may fail")

            # Emit pipeline_plan event so frontend knows which agents will run
            all_agents = ["pm"] + [a for a in required_agents]

            # Detect parallel groups for frontend visualization
            specialist_keys = {"markup", "style", "style_scss", "script"}
            parallel_agents = [k for k in required_agents if k in specialist_keys]
            parallel_groups = [parallel_agents] if len(parallel_agents) > 1 else []

            # Post-processing parallel group (seo, accessibility, animation)
            post_process_parallel_keys = {"seo", "accessibility", "animation"}
            post_parallel = [k for k in required_agents if k in post_process_parallel_keys]
            if len(post_parallel) > 1:
                parallel_groups.append(post_parallel)

            # Build agent metadata from registry
            from agentsite.agents.registry import AgentRegistry

            agent_meta = {}
            for key in all_agents:
                desc = AgentRegistry.get(key)
                if desc:
                    agent_meta[key] = {
                        "name": desc.name,
                        "icon": desc.icon,
                        "icon_color": desc.icon_color,
                        "category": desc.category.value,
                    }

            await self._emit("pipeline_plan", data={
                "required_agents": all_agents,
                "agent_meta": agent_meta,
                "parallel_groups": parallel_groups,
                "tech_stack": tech_stack.model_dump(),
            })

            # --- Cancellation check after PM ---
            if cancel_event and cancel_event.is_set():
                await self._emit("generation_complete", data={
                    "success": False, "slug": slug, "version": version_number,
                    "files": [], "error": "Cancelled by host",
                })
                return GroupResult(
                    agent_results=[], aggregate_usage={},
                    shared_state={}, elapsed_ms=0, timeline=[], errors=[],
                    success=False,
                )

            # --- Load existing guides for template injection ---
            design_system_guide = self._pm.read_guide(project.id, "design-system.md") or ""
            architecture_guide = self._pm.read_guide(project.id, "architecture.md") or ""

            # --- Phase B: Run Designer standalone (with fallback) if needed ---
            # Phase 7 — drain any steer the user sent while PM was running
            user_steer = ""
            try:
                from .interrupt import mailbox as _sm
                drained = _sm.drain(project.id)
                if drained:
                    user_steer = "\n".join(f"- {s}" for s in drained)
                    await self._emit("steer_applied", data={"text": user_steer, "count": len(drained)})
            except Exception:
                logger.debug("steer drain skipped", exc_info=True)

            initial_state = {
                "prompt": page_prompt,
                "discovery_brief": discovery_brief_text,
                "user_steer": user_steer,
                "skill_instructions": getattr(self, "_skill_instructions", "") or "",
                "skill_id": getattr(self, "_skill_id", "") or "",
                "site_plan": site_plan_text,
                "project_dir": self._pm.project_dir(project.id),
                "review_feedback": "",
                "verify_feedback": "",
                "logo_url": project.logo_url or "",
                "icon_url": project.icon_url or "",
                "page_slug": slug,
                "page_title": slug.replace("-", " ").title(),
                "design_system_guide": design_system_guide,
                "architecture_guide": architecture_guide,
                "tech_stack": tech_stack.model_dump_json(),
                "conversation_context": conversation_context,
            }

            # Phase 2 — if the user picked a deterministic direction, synthesize
            # StyleSpec from it and skip the Designer agent entirely.
            direction_synthesized = False
            if (
                discovery_brief is not None
                and discovery_brief.brand_mode == "pick_direction"
                and discovery_brief.direction_id
            ):
                from ..agents.directions import find_direction, synthesize_style_spec

                _direction = find_direction(discovery_brief.direction_id)
                if _direction is not None:
                    _spec = synthesize_style_spec(_direction)
                    self.style_spec_text = _spec.model_dump_json()
                    initial_state["style_spec"] = self.style_spec_text
                    await self._emit("style_spec_ready", data={
                        "style_spec": self.style_spec_text,
                        "parsed": True,
                        "source": "direction",
                        "direction_id": _direction.id,
                    })
                    direction_synthesized = True
                    if "designer" in required_agents:
                        required_agents = [a for a in required_agents if a != "designer"]
                    logger.info("Phase 2: synthesized StyleSpec from direction '%s'", _direction.id)

            if not direction_synthesized and "designer" in required_agents:
                from ..agents.designer import create_designer_agent_auto

                designer_model = self._agent_models["designer"]
                # Use auto factory to select structured/plain mode based on capabilities
                designer_agent = create_designer_agent_auto(designer_model)
                _apply_agent_overrides(designer_agent, "designer", self._agent_configs)
                self._inject_driver(designer_agent, designer_model)
                # Phase 9 — if project.style_spec.inherits_from is set, load
                # the bundled/user system and instruct the Designer to extend
                # rather than invent.
                inherits_block = ""
                if project.style_spec and getattr(project.style_spec, "inherits_from", None):
                    try:
                        from ..design_systems import find_design_system as _find_ds
                        _ds = _find_ds(project.style_spec.inherits_from)
                        if _ds is not None:
                            inherits_block = (
                                "Inherit from this existing design system "
                                f"(`{_ds['id']}`) — extend it, don't replace it. "
                                "Match its palette, typography, and posture exactly; "
                                "only add tokens the system doesn't already define.\n\n"
                                f"## {_ds['name']}\n\n{_ds['description']}\n\n"
                                "```css\n" + _ds["raw_css"] + "\n```\n\n"
                            )
                    except Exception:
                        logger.debug("Design system inheritance lookup failed", exc_info=True)

                designer_prompt = (
                    "Design a visual style for this website:\n\n"
                    + (f"{discovery_brief_text}\n\n" if discovery_brief_text else "")
                    + inherits_block
                    + f"Site Plan: {site_plan_text}\n\n"
                    f"Logo URL: {project.logo_url or ''}\n"
                    f"Icon URL: {project.icon_url or ''}\n\n"
                    "Create a cohesive color scheme, typography, and spacing system."
                )

                designer_callbacks = GroupCallbacks(
                    on_agent_start=_on_agent_start,
                    on_agent_complete=_on_agent_complete,
                    on_agent_error=_on_agent_error,
                )

                designer_pipeline = AsyncSequentialGroup(
                    [(designer_agent, "{designer_prompt}")],
                    callbacks=designer_callbacks,
                    state={"designer_prompt": designer_prompt},
                    error_policy=ErrorPolicy.raise_on_error,
                    deps=deps,
                )
                _attach_streaming_callbacks(designer_pipeline, self._emit)

                designer_result = await designer_pipeline.run(designer_prompt)
                style_spec_text = designer_result.shared_state.get("style_spec", "")
                self.style_spec_text = style_spec_text

                # Emit style_spec_ready so hosts can preview design before dev starts
                _style_parsed = False
                if style_spec_text:
                    try:
                        from prompture import clean_json_text as _cjt
                        json.loads(_cjt(style_spec_text))
                        _style_parsed = True
                    except Exception:
                        pass
                await self._emit("style_spec_ready", data={
                    "style_spec": style_spec_text,
                    "parsed": _style_parsed,
                })

                initial_state["style_spec"] = style_spec_text

                # Merge designer usage into pm_result for later aggregation
                if hasattr(designer_result, "aggregate_usage"):
                    if not hasattr(pm_result, "aggregate_usage"):
                        pm_result.aggregate_usage = {}
                    for k, v in designer_result.aggregate_usage.items():
                        if isinstance(v, (int, float)):
                            pm_result.aggregate_usage[k] = pm_result.aggregate_usage.get(k, 0) + v

                # Remove designer from remaining pipeline since we ran it here
                remaining_agents = [a for a in required_agents if a != "designer"]
            else:
                remaining_agents = list(required_agents)
                # If the direction synthesizer already set a style_spec, keep it.
                # Otherwise fall back to project default or empty.
                if "style_spec" not in initial_state:
                    if project.style_spec:
                        initial_state["style_spec"] = project.style_spec.model_dump_json()
                    else:
                        initial_state["style_spec"] = StyleSpec().model_dump_json()

            # --- Cancellation check after Designer ---
            if cancel_event and cancel_event.is_set():
                await self._emit("generation_complete", data={
                    "success": False, "slug": slug, "version": version_number,
                    "files": [], "error": "Cancelled by host",
                })
                return GroupResult(
                    agent_results=[], aggregate_usage={},
                    shared_state={}, elapsed_ms=0, timeline=[], errors=[],
                    success=False,
                )

            # --- Phase C: Build pipeline — specialist (parallel) or legacy (monolithic) ---
            # Build budget kwargs from per-request overrides or global settings
            effective_max_cost = max_cost if max_cost is not None else (settings.max_generation_cost or None)
            effective_policy = budget_policy or settings.budget_policy or None

            async def _on_model_fallback(old_model: str, new_model: str, state: Any) -> None:
                logger.info("Budget policy triggered model fallback: %s -> %s", old_model, new_model)
                await self._emit(
                    "model_fallback",
                    data={"old_model": old_model, "new_model": new_model},
                )

            budget_kwargs = _build_budget_kwargs(
                max_cost=effective_max_cost,
                policy=effective_policy,
                max_tokens=settings.budget_max_tokens or None,
                fallback_models=settings.budget_fallback_models or None,
                on_fallback=_on_model_fallback,
            )

            specialist_keys = {"markup", "style", "style_scss", "script", "image"}
            has_specialists = any(k in remaining_agents for k in specialist_keys)

            # Resolve models for specialist and post-processing agents
            all_specialist_keys = specialist_keys | {"copywriter", "seo", "accessibility", "animation"}
            for agent_key in all_specialist_keys:
                if agent_key in remaining_agents:
                    self._agent_models[agent_key] = _agent_model(agent_key, model, self._agent_configs)

            if has_specialists:
                remaining_pipeline = create_specialist_pipeline(
                    remaining_agents,
                    model,
                    callbacks=group_callbacks,
                    agent_configs=self._agent_configs,
                    error_policy=ErrorPolicy.raise_on_error,
                    deps=deps,
                    provider_keys=self._provider_keys,
                    max_review_iterations=max_review_iterations,
                    review_threshold=review_threshold,
                    render_verify=settings.verify_enabled,
                    **budget_kwargs,
                )
            else:
                remaining_pipeline = create_dynamic_pipeline(
                    remaining_agents,
                    model,
                    callbacks=group_callbacks,
                    agent_configs=self._agent_configs,
                    error_policy=ErrorPolicy.raise_on_error,
                    deps=deps,
                    provider_keys=self._provider_keys,
                    max_review_iterations=max_review_iterations,
                    review_threshold=review_threshold,
                    render_verify=settings.verify_enabled,
                    **budget_kwargs,
                )

            # Transfer state from PM phase and propagate to nested groups
            # (LoopGroup) so prompt templates like {site_plan} resolve.
            remaining_pipeline.inject_state(initial_state, recursive=True)

            _attach_streaming_callbacks(remaining_pipeline, self._emit)

            _need_dev_fallback = False
            try:
                result = await remaining_pipeline.run("")
            except Exception as dev_exc:
                logger.warning(
                    "Developer pipeline failed (tools may be unsupported), will retry with plain text developer: %s",
                    dev_exc,
                )
                _need_dev_fallback = True
                # Create a minimal result to carry forward
                result = GroupResult(
                    agent_results=[],
                    aggregate_usage={},
                    shared_state=dict(initial_state),
                    elapsed_ms=0,
                    timeline=[],
                    errors=[],
                    success=False,
                )

            # --- Cancellation check after build/review pipeline ---
            if cancel_event and cancel_event.is_set():
                await self._emit("generation_complete", data={
                    "success": False, "slug": slug, "version": version_number,
                    "files": [], "error": "Cancelled by host",
                })
                return GroupResult(
                    agent_results=[], aggregate_usage={},
                    shared_state={}, elapsed_ms=0, timeline=[], errors=[],
                    success=False,
                )

            # Merge nested group state back so we can access page_output
            _merge_nested_group_state(remaining_pipeline)

            # Also fall back if the pipeline "succeeded" but developer
            # produced no usable output — either no tool calls and no files,
            # or the output text has no actual HTML code (just analysis/planning).
            if not _need_dev_fallback and not written_files and not self._developer_tool_calls:
                dev_text = self._developer_output_text or ""
                has_html = "<!DOCTYPE" in dev_text.upper() or "<html" in dev_text.lower()
                has_fenced = "```html" in dev_text or "```css" in dev_text
                if not has_html and not has_fenced:
                    logger.warning(
                        "Developer pipeline produced no usable code (success=%s, "
                        "written_files=%d, tool_calls=%d, has_html=%s, output_len=%d). "
                        "Retrying with plain text developer.",
                        result.success,
                        len(written_files),
                        len(self._developer_tool_calls),
                        has_html,
                        len(dev_text),
                    )
                    _need_dev_fallback = True

            if _need_dev_fallback:
                from ..agents.developer import create_developer_agent_plain

                dev_model = self._agent_models["developer"]
                dev_agent_plain = create_developer_agent_plain(dev_model)

                dev_prompt = (
                    f"Build the '{slug}' page ONLY. No other pages.\n\n"
                    f"Site Plan: {initial_state['site_plan']}\n\n"
                    f"Style Spec: {initial_state.get('style_spec', '')}\n\n"
                    f"Logo URL: {initial_state.get('logo_url', '')}\n"
                    f"Icon URL: {initial_state.get('icon_url', '')}\n\n"
                    "RESPOND WITH ONLY A ```html CODE BLOCK. "
                    "No planning, no analysis, no explanation. "
                    "Single self-contained HTML file with <style> and <script> inline. "
                    "Start your response with ```html immediately."
                )

                dev_callbacks = GroupCallbacks(
                    on_agent_start=_on_agent_start,
                    on_agent_complete=_on_agent_complete,
                    on_agent_error=_on_agent_error,
                )
                dev_pipeline_plain = AsyncSequentialGroup(
                    [(dev_agent_plain, "{dev_prompt}")],
                    callbacks=dev_callbacks,
                    state={"dev_prompt": dev_prompt},
                    error_policy=ErrorPolicy.raise_on_error,
                    deps=deps,
                )
                _attach_streaming_callbacks(dev_pipeline_plain, self._emit)
                plain_result = await dev_pipeline_plain.run(dev_prompt)

                # Use the plain result's usage and state
                if hasattr(plain_result, "aggregate_usage"):
                    if not hasattr(result, "aggregate_usage"):
                        result.aggregate_usage = {}
                    for k, v in plain_result.aggregate_usage.items():
                        if isinstance(v, (int, float)):
                            result.aggregate_usage[k] = result.aggregate_usage.get(k, 0) + v
                result = plain_result

            # Build combined_usage by merging both pipeline phases.
            # The global tracker (configure_tracker) captures usage
            # automatically for analytics; here we aggregate per-generation.
            combined_usage: dict[str, Any] = (
                pm_result.aggregate_usage.copy() if hasattr(pm_result, "aggregate_usage") else {}
            )
            if hasattr(result, "aggregate_usage"):
                for k, v in result.aggregate_usage.items():
                    if isinstance(v, (int, float)):
                        combined_usage[k] = combined_usage.get(k, 0) + v

            # Extract structured outputs from shared state —
            # check both the result's shared_state and the pipeline's
            # own state (which now includes merged nested group state).
            state = result.shared_state
            page_output_text = (
                state.get("page_output", "")
                or remaining_pipeline.shared_state.get("page_output", "")
                or self._developer_output_text  # direct capture from callback
            )

            logger.info(
                "Post-pipeline state keys: result=%s, pipeline=%s, "
                "page_output_text length=%d, developer_output_text length=%d, "
                "written_files=%s",
                list(state.keys()),
                list(remaining_pipeline.shared_state.keys()),
                len(page_output_text or ""),
                len(self._developer_output_text),
                written_files,
            )

            # If the developer agent didn't write files via tools, try to
            # extract content from its raw output text as a fallback.
            if not written_files:
                logger.warning(
                    "No files written via tools for project %s page %s v%d. page_output_text[:500]: %s",
                    project.id,
                    slug,
                    version_number,
                    (page_output_text or "")[:500],
                )
                if page_output_text:
                    self._write_files_from_output(project.id, slug, version_number, page_output_text)

            # Post-generation: compile SCSS files if present
            try:
                from .scss_compiler import compile_directory

                scss_count = compile_directory(version_dir)
                if scss_count:
                    logger.info("Compiled %d SCSS files to CSS", scss_count)
            except ImportError:
                pass  # libsass not installed — no SCSS compilation

            # Verify files actually exist on disk
            final_files = self._pm.list_version_files(project.id, slug, version_number)

            # Fallback chain: try multiple strategies to get files on disk
            if not final_files and self._developer_tool_calls:
                logger.warning(
                    "No files on disk — trying extraction from %d tool_calls",
                    len(self._developer_tool_calls),
                )
                self._write_files_from_tool_calls(project.id, slug, version_number, self._developer_tool_calls)
                final_files = self._pm.list_version_files(project.id, slug, version_number)

            if not final_files:
                # Strategy 2: Extract from text output sources
                for source_name, source_text in [
                    ("page_output_text", page_output_text),
                    ("developer_output_text", self._developer_output_text),
                ]:
                    if source_text:
                        logger.warning(
                            "No files on disk — trying text fallback from %s (length=%d)",
                            source_name,
                            len(source_text),
                        )
                        self._write_files_from_output(project.id, slug, version_number, source_text)
                        final_files = self._pm.list_version_files(project.id, slug, version_number)
                        if final_files:
                            break

            if not final_files:
                logger.error(
                    "Generation produced no files for project %s page %s v%d. "
                    "tool_calls=%d, developer_output_text[:500]=%s",
                    project.id,
                    slug,
                    version_number,
                    len(self._developer_tool_calls),
                    self._developer_output_text[:500],
                )
                raise RuntimeError(
                    "Generation completed but no files were written to disk. "
                    "The developer agent may have returned output in an unexpected format.\n\n"
                    f"Developer output preview:\n{self._developer_output_text[:1000]}"
                )

            # Read files from disk into a dict for DB storage
            files_content: dict[str, str] = {}
            for fpath in final_files:
                content = self._pm.read_version_file(project.id, slug, version_number, fpath)
                if content is not None:
                    files_content[fpath] = content

            # Phase 10 — heuristic memory extraction from the inputs of this run.
            try:
                from ..api import deps as _api_deps
                from .memory import extract_memories as _extract_mem

                if getattr(_api_deps, "memory_repo", None) is not None and final_files:
                    _steer_lines = user_steer.split("\n") if user_steer else []
                    facts = _extract_mem(
                        project_id=project.id,
                        brief=discovery_brief,
                        steer_lines=[s.lstrip("- ").strip() for s in _steer_lines if s.strip()],
                        source_run_id=session_id,
                    )
                    # Save only facts that aren't trivially duplicate of existing rows
                    if facts:
                        existing = await _api_deps.memory_repo.list_by_project(project.id, limit=50)
                        existing_keys = {(f.kind, f.body) for f in existing}
                        new_facts = [f for f in facts if (f.kind, f.body) not in existing_keys]
                        for f in new_facts:
                            try:
                                await _api_deps.memory_repo.create(f)
                            except Exception:
                                logger.debug("Memory create skipped", exc_info=True)
                        if new_facts:
                            await self._emit("memory_extracted", data={
                                "count": len(new_facts),
                                "facts": [f.model_dump() for f in new_facts],
                            })
            except Exception:
                logger.debug("Memory extraction skipped", exc_info=True)

            # Phase 4 — run the multi-dim critique panel + update ratchet.
            # Feature-flagged: off by default; surfaces a `critique_verdict`
            # WS event and writes <project>/quality_ratchet.json when on.
            if settings.use_critique_panel and final_files:
                try:
                    from ..agents.critique import run_critique_panel
                    from .ratchet import update_ratchet

                    judge_model = self._agent_models.get("reviewer") or model
                    verdict, _debate_result = await run_critique_panel(
                        judge_model,
                        page_slug=slug,
                        deps=deps,
                    )
                    if verdict is not None:
                        ratchet, accepted, regressed = update_ratchet(
                            project.id,
                            verdict,
                            slug=slug,
                            version=version_number,
                        )
                        await self._emit(
                            "critique_verdict",
                            data={
                                "verdict": verdict.model_dump(),
                                "accepted": accepted,
                                "regressed": regressed,
                                "floors": ratchet.floors,
                            },
                        )
                except Exception:
                    logger.warning("Critique panel failed (non-fatal)", exc_info=True)

            # Phase 2 (components) — auto-detect reusable sections in the
            # final page HTML and save the best few to the project library.
            components_detected: list[dict] = []
            if result.success and self._project_component_repo is not None:
                try:
                    from .component_detector import save_detected_components

                    index_html = files_content.get("index.html", "")
                    if index_html:
                        components_detected = await save_detected_components(
                            project_id=project.id,
                            page_slug=slug,
                            version=version_number,
                            html=index_html,
                            repo=self._project_component_repo,
                        )
                except Exception:
                    logger.warning("Component auto-detection failed (non-fatal)", exc_info=True)

            await self._emit(
                "generation_complete",
                data={
                    "success": result.success,
                    "slug": slug,
                    "version": version_number,
                    "files": final_files,
                    "files_content": files_content,
                    "usage": combined_usage,
                    "components_detected": components_detected,
                },
            )

            # Return a result-like object with combined usage
            result.aggregate_usage = combined_usage
            return result

        except Exception as exc:
            import traceback

            logger.exception("Generation failed for project %s page %s v%d", project.id, slug, version_number)
            await self._emit("error", data={"message": str(exc), "traceback": traceback.format_exc()})
            await self._emit(
                "generation_complete",
                data={
                    "success": False,
                    "slug": slug,
                    "version": version_number,
                    "files": [],
                    "error": str(exc),
                },
            )
            raise

        finally:
            # Restore previous CACHIBOT_API_KEY env var
            if self._cachibot_api_key:
                if _prev_cachibot_key is not None:
                    _os.environ["CACHIBOT_API_KEY"] = _prev_cachibot_key
                else:
                    _os.environ.pop("CACHIBOT_API_KEY", None)

    def _write_files_from_tool_calls(self, project_id: str, slug: str, version: int, tool_calls: list[dict]) -> None:
        """Extract files from write_file tool call arguments and write them to disk."""
        for tc in tool_calls:
            name = tc.get("name", "")
            args = tc.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except (json.JSONDecodeError, TypeError):
                    continue
            if name == "write_file" and "path" in args and "content" in args:
                path = args["path"]
                content = args["content"]
                try:
                    self._pm.write_version_file(project_id, slug, version, path, content)
                    logger.info("Wrote file from tool_call args: %s (%d bytes)", path, len(content))
                except Exception:
                    logger.warning("Failed to write file from tool_call: %s", path, exc_info=True)

    @staticmethod
    def _strip_reasoning_preamble(text: str) -> str:
        """Strip reasoning/thinking preamble from model output.

        Some models (e.g. Kimi K2.5) emit chain-of-thought reasoning before
        the actual code.  This helper removes everything before the first
        code fence or HTML tag so extraction can find the real content.
        """
        import re

        # If the text starts with a code fence, nothing to strip
        if text.lstrip().startswith("```"):
            return text

        # Try to find the first ```html or ```css or ```js fence
        fence_match = re.search(r"```(?:html|css|javascript|js)\b", text, re.IGNORECASE)
        if fence_match:
            stripped = text[fence_match.start() :]
            logger.info(
                "Stripped %d chars of reasoning preamble before code fence",
                fence_match.start(),
            )
            return stripped

        # Try to find raw HTML (<!DOCTYPE or <html)
        html_match = re.search(r"<!DOCTYPE\s+html|<html[\s>]", text, re.IGNORECASE)
        if html_match:
            stripped = text[html_match.start() :]
            logger.info(
                "Stripped %d chars of reasoning preamble before HTML",
                html_match.start(),
            )
            return stripped

        return text

    def _write_files_from_output(self, project_id: str, slug: str, version: int, output_text: str) -> None:
        """Parse PageOutput JSON from output text and write files."""
        try:
            from prompture import clean_json_text

            cleaned = clean_json_text(output_text)
            data = json.loads(cleaned)
            page_output = PageOutput.model_validate(data)
            for f in page_output.files:
                self._pm.write_version_file(project_id, slug, version, f.path, f.content)
                logger.info("Wrote file from output: %s", f.path)
        except Exception:
            logger.warning(
                "Could not parse PageOutput JSON, attempting fenced/raw extraction (length=%d)",
                len(output_text),
                exc_info=True,
            )
            # Strip reasoning/thinking preamble that some models emit
            cleaned_text = self._strip_reasoning_preamble(output_text)

            # Try extracting markdown-fenced code blocks first
            wrote_fenced = self._extract_fenced_blocks(project_id, slug, version, cleaned_text)
            if not wrote_fenced:
                # Last resort: if the output contains raw HTML, save it as index.html
                self._try_extract_raw_html(project_id, slug, version, cleaned_text)

    def _extract_fenced_blocks(self, project_id: str, slug: str, version: int, text: str) -> bool:
        """Salvage ```html/css/js fenced blocks via prompture and write them.

        Returns True if at least one file was written.
        """
        from prompture import extract_fenced_blocks

        blocks = extract_fenced_blocks(text, languages=["html", "css", "js", "javascript"])
        if not blocks:
            return False

        lang_to_file = {
            "html": "index.html",
            "css": "styles.css",
            "js": "script.js",
            "javascript": "script.js",
        }
        used_names: set[str] = set()
        wrote_any = False
        for block in blocks:
            filename = lang_to_file.get(block.language)
            if not filename:
                continue
            if filename in used_names:
                base, ext = filename.rsplit(".", 1)
                counter = 2
                while f"{base}_{counter}.{ext}" in used_names:
                    counter += 1
                filename = f"{base}_{counter}.{ext}"
            used_names.add(filename)
            self._pm.write_version_file(project_id, slug, version, filename, block.content)
            logger.info(
                "Extracted fenced %s block as %s (%d bytes)",
                block.language,
                filename,
                len(block.content),
            )
            wrote_any = True
        return wrote_any

    def _try_extract_raw_html(self, project_id: str, slug: str, version: int, text: str) -> None:
        """Salvage a raw HTML document via prompture as a last resort."""
        from prompture import extract_html_document

        doc = extract_html_document(text)
        if not doc.found:
            logger.error("No HTML content found in developer output (length=%d)", len(text))
            return

        self._pm.write_version_file(project_id, slug, version, "index.html", doc.html)
        logger.info("Extracted raw HTML fallback as index.html (%d bytes)", len(doc.html))

        if doc.styles:
            css_content = "\n\n".join(doc.styles)
            self._pm.write_version_file(project_id, slug, version, "styles.css", css_content)
            logger.info("Extracted CSS fallback as styles.css (%d bytes)", len(css_content))

        if doc.scripts:
            js_content = "\n\n".join(doc.scripts)
            self._pm.write_version_file(project_id, slug, version, "script.js", js_content)
            logger.info("Extracted JS fallback as script.js (%d bytes)", len(js_content))
