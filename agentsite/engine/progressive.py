"""Progressive page generation pipeline (mockup mode only).

Instead of building a page in one shot, this pipeline runs in three stages:

1. **Skeleton** — after the usual PM (SitePlan) and Designer (StyleSpec)
   phases, a ``layout`` agent produces the complete HTML document shell with
   one ``<!-- @section:{key} -->`` marker per planned section, plus the
   complete ``styles.css``. The shell is written to disk and pushed to the
   preview immediately.
2. **Sections** — each section is generated independently (in parallel,
   bounded by a semaphore) by a ``section:{key}`` agent that only sees the
   stylesheet + style spec + its own section brief. As each fragment lands
   it is spliced into the document in place of its marker, the file is
   rewritten, and a fresh ``preview_update`` is emitted — so the preview
   fills in progressively.
3. **Repair** — weak/invalid fragments are retried individually with a
   repair prompt; sections that still fail get a graceful fallback fragment
   and the build continues. One bad section never fails the page.

Every ``preview_update`` carries the COMPLETE assembled document plus a
fresh ``content_hash``, so the frontend streams it with zero changes.
"""

from __future__ import annotations

import asyncio
import hashlib
import html as _html
import json
import logging
import re
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from prompture import AsyncSequentialGroup, ErrorPolicy, GroupResult

from ..agents.component_tools import component_catalog_lines, component_library_tools
from ..agents.orchestrator import _agent_model, _apply_agent_overrides
from ..agents.personas import LAYOUT_PERSONA, SECTION_PERSONA
from ..config import settings
from ..models import AgentConfig, AgentRun, DiscoveryBrief, Project, SitePlan, StyleSpec, WSEvent
from .pipeline import GenerationPipeline, _attach_streaming_callbacks, _build_budget_kwargs
from .project_manager import ProjectManager

logger = logging.getLogger("agentsite.progressive")

# Leading stopwords stripped from section descriptions when deriving keys.
_KEY_STOPWORDS = {"a", "an", "the", "with", "and", "for", "of", "to", "section", "main", "page"}


# ------------------------------------------------------------------
# Pure helpers (unit-testable, no LLM)
# ------------------------------------------------------------------


def derive_section_keys(sections: list[str]) -> list[str]:
    """Derive slugified unique keys from ordered section descriptions.

    Takes the first meaningful word of each description (e.g. "hero",
    "features"), dedupes with ``-2``/``-3`` suffixes, and falls back to
    ``section-{i+1}`` when a description yields nothing usable.
    """
    keys: list[str] = []
    used: set[str] = set()
    for i, desc in enumerate(sections):
        words = [w for w in re.findall(r"[a-z0-9]+", (desc or "").lower()) if w not in _KEY_STOPWORDS]
        key = (words[0] if words else "") or f"section-{i + 1}"
        base, n = key, 2
        while key in used:
            key = f"{base}-{n}"
            n += 1
        used.add(key)
        keys.append(key)
    return keys


def marker_for(key: str) -> str:
    """Return the HTML comment marker for a section key."""
    return f"<!-- @section:{key} -->"


def splice_section(document: str, key: str, fragment: str) -> str:
    """Splice a section fragment into the document.

    Replaces the section's marker if present; otherwise inserts before
    ``</body>`` (case-insensitive); otherwise appends to the document.
    """
    marker = marker_for(key)
    if marker in document:
        return document.replace(marker, fragment, 1)
    m = re.search(r"</body\s*>", document, re.IGNORECASE)
    if m:
        return document[: m.start()] + fragment + "\n" + document[m.start():]
    return document + "\n" + fragment


def clean_fragment(text: str) -> str:
    """Reduce raw model output to just the section markup.

    Strips reasoning preambles, markdown fences, and full-document wrappers
    (<!DOCTYPE>, <html>, <head>, <body>) so only the fragment remains.
    """
    if not text:
        return ""
    stripped = GenerationPipeline._strip_reasoning_preamble(text)

    # Prefer the first html (or untagged) fenced block if fences are present.
    fences = re.findall(r"```([a-zA-Z]*)\s*\n(.*?)```", stripped, re.DOTALL)
    if fences:
        html_blocks = [content for lang, content in fences if lang.lower() in ("html", "")]
        if html_blocks:
            stripped = html_blocks[0]

    frag = stripped.strip()
    frag = re.sub(r"<!DOCTYPE[^>]*>", "", frag, flags=re.IGNORECASE)
    frag = re.sub(r"</?html[^>]*>", "", frag, flags=re.IGNORECASE)
    frag = re.sub(r"<head\b[^>]*>.*?</head>", "", frag, flags=re.IGNORECASE | re.DOTALL)
    frag = re.sub(r"</?body[^>]*>", "", frag, flags=re.IGNORECASE)
    return frag.strip()


def validate_fragment(html: str) -> list[str]:
    """Return a list of problems with a section fragment (empty = valid)."""
    if not html or not html.strip():
        return ["fragment is empty"]
    problems: list[str] = []
    if "@section:" in html or "{{" in html:
        problems.append("fragment contains an unresolved marker or template placeholder")
    if not re.search(r"<[a-zA-Z][a-zA-Z0-9-]*(\s[^>]*)?>", html):
        problems.append("fragment contains no HTML tag")
    text_only = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()
    if len(text_only) < 40:
        problems.append("fragment has suspiciously little text (<40 chars)")
    return problems


def build_skeleton_prompt(
    *,
    page_prompt: str,
    site_plan_text: str,
    sections: list[tuple[str, str]],
    style_spec_text: str,
    shared_components: list[str] | None = None,
) -> str:
    """Build the user prompt for the layout (skeleton) agent."""
    lines = [
        "Build the structural skeleton for this page.\n",
        "## Page brief",
        page_prompt,
        "\n## Site plan (JSON)",
        site_plan_text or "{}",
    ]
    if shared_components:
        lines.append("\n## Shared components (may appear as chrome around the sections)")
        lines.extend(f"- {c}" for c in shared_components)
    lines.append("\n## Sections (in order)")
    lines.append(
        "Emit each marker VERBATIM, exactly once, in this order, where the "
        "section belongs in <body>:"
    )
    for i, (key, desc) in enumerate(sections, start=1):
        lines.append(f"{i}. `{key}` — {desc}\n   marker: {marker_for(key)}")
    lines.append("\n## Style spec (implement fully in the css block)")
    lines.append(style_spec_text or "{}")
    return "\n".join(lines)


def build_section_prompt(
    *,
    page_prompt: str,
    key: str,
    description: str,
    index: int,
    total: int,
    style_spec_text: str,
    css: str,
    shared_components: list[str] | None = None,
    available_components: list[str] | None = None,
) -> str:
    """Build the user prompt for one section agent."""
    lines = [
        f"Build section {index} of {total} (`{key}`) for this page.\n",
        "## Page brief",
        page_prompt,
        "\n## Your section",
        description,
        "\n## Style spec",
        style_spec_text or "{}",
    ]
    if shared_components:
        lines.append("\n## Shared components (for context only — do NOT rebuild them)")
        lines.extend(f"- {c}" for c in shared_components)
    if available_components:
        lines.append(
            "\n## Reusable components (call render_block(slug, config) to use one — "
            "PREFER this over hand-writing markup when your section matches)"
        )
        lines.extend(f"- {c}" for c in available_components)
    lines.append("\n## styles.css (use ONLY these classes/tokens)")
    lines.append(css or "/* none provided */")
    lines.append(
        "\nRespond with ONLY the <section>…</section> fragment for your section — "
        "no fences, no document wrappers, no explanation."
    )
    return "\n".join(lines)


def build_repair_prompt(*, original_prompt: str, problems: list[str], fragment: str) -> str:
    """Build a repair prompt asking for a corrected fragment only."""
    issues = "\n".join(f"- {p}" for p in problems)
    return (
        f"{original_prompt}\n\n"
        "## Your previous attempt had problems\n"
        f"{issues}\n\n"
        "## Previous attempt\n"
        f"{fragment[:4000]}\n\n"
        "Return ONLY the corrected <section>…</section> fragment — no fences, "
        "no document wrappers, no explanation."
    )


# ------------------------------------------------------------------
# Pipeline
# ------------------------------------------------------------------


class ProgressivePipeline:
    """Progressive (skeleton → parallel sections) generation pipeline.

    Exposes the same contract as :class:`GenerationPipeline` — same
    ``generate(**)`` kwargs, ``style_spec_text``, and ``agent_runs`` — so
    ``generation_runner`` can drive it interchangeably.
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
        max_parallel_sections: int = 3,
        max_section_attempts: int = 2,
    ) -> None:
        self._pm = project_manager
        self._on_event = on_event
        self._agent_configs = agent_configs
        self._cachibot_api_key = cachibot_api_key
        self._provider_keys = provider_keys
        self._project_component_repo = project_component_repo
        self._max_parallel_sections = max(1, max_parallel_sections)
        self._max_section_attempts = max(1, max_section_attempts)
        self.agent_runs: list[AgentRun] = []
        self._active_runs: dict[str, AgentRun] = {}
        self._run_start_times: dict[str, float] = {}
        self._agent_models: dict[str, str] = {}
        self._pending_usage: dict[str, dict] = {}
        self._combined_usage: dict[str, Any] = {}
        self._group_budget_kwargs: dict[str, Any] = {}
        self.site_plan_text: str = ""
        self.style_spec_text: str = ""

    # -- infrastructure (mirrors GenerationPipeline) --

    def _inject_driver(self, agent: Any, model_str: str) -> None:
        """Inject a per-project driver into an agent if provider_keys are set."""
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

    # -- agent run tracking (lightweight mirror of pipeline.py) --

    async def _agent_started(self, agent_key: str, project: Project, slug: str, version_number: int, model: str) -> None:
        started_at = datetime.now(timezone.utc).isoformat()
        await self._emit("agent_start", agent=agent_key, data={
            "started_at": started_at,
            "model": model,
            "strategy": "",
        })
        run = AgentRun(
            project_id=project.id,
            page_slug=slug,
            version=version_number,
            agent_name=agent_key,
            status="running",
            model=model,
        )
        self._active_runs[agent_key] = run
        self._run_start_times[agent_key] = time.monotonic()
        self.agent_runs.append(run)

    async def _agent_finished(self, agent_key: str, output_text: str = "", error: Exception | None = None) -> None:
        run = self._active_runs.pop(agent_key, None)
        start_time = self._run_start_times.pop(agent_key, None)
        duration_s = round(time.monotonic() - start_time, 1) if start_time else None
        usage = self._pending_usage.pop(agent_key, {}) or {}
        input_tokens = int(usage.get("input_tokens", 0) or usage.get("prompt_tokens", 0) or 0)
        output_tokens = int(usage.get("output_tokens", 0) or usage.get("completion_tokens", 0) or 0)
        cost = float(usage.get("cost", 0.0) or usage.get("total_cost", 0.0) or 0.0)

        if run is not None:
            run.completed_at = datetime.now(timezone.utc).isoformat()
            run.input_tokens = input_tokens
            run.output_tokens = output_tokens
            run.cost = cost
            if error is not None:
                run.status = "failed"
                run.output_summary = {"error": str(error)}
            else:
                run.status = "completed"

        if error is not None:
            # Non-fatal (matches pipeline.py): the stage decides whether to retry/fallback.
            await self._emit("agent_error", agent=agent_key, data={"message": str(error)})
        else:
            await self._emit("agent_complete", agent=agent_key, data={
                "output_preview": output_text[:2000],
                "full_output": output_text,
                "duration_s": duration_s,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost": cost,
                "tool_calls_count": 0,
                "model": self._agent_models.get(agent_key, ""),
                "reasoning": "",
            })

    async def _tracked_run(
        self,
        agent_key: str,
        system_prompt: Any,
        user_prompt: str,
        model: str,
        deps: dict | None,
        *,
        project: Project,
        slug: str,
        version_number: int,
    ) -> str:
        """Run one agent with lifecycle events + run tracking around it."""
        await self._agent_started(agent_key, project, slug, version_number, model)
        try:
            text = await self._run_agent(agent_key, system_prompt, user_prompt, model, deps)
        except Exception as exc:
            await self._agent_finished(agent_key, error=exc)
            raise
        await self._agent_finished(agent_key, output_text=text)
        return text

    async def _run_agent(
        self,
        agent_key: str,
        system_prompt: Any,
        user_prompt: str,
        model: str,
        deps: dict | None = None,
        tools: Any | None = None,
    ) -> str:
        """Build and run a single-agent group; return its output text.

        This is the single choke point for all LLM calls in the pipeline —
        PM and Designer reuse the real auto factories; every other agent is a
        plain agent built from the given system prompt.
        """
        from prompture import AsyncAgent

        output_key: str | None = None
        if agent_key == "pm":
            from ..agents.pm import create_pm_agent_auto

            agent = create_pm_agent_auto(model)
            output_key = "site_plan"
            override_key = "pm"
        elif agent_key == "designer":
            from ..agents.designer import create_designer_agent_auto

            agent = create_designer_agent_auto(model)
            output_key = "style_spec"
            override_key = "designer"
        else:
            agent = AsyncAgent(
                model,
                system_prompt=system_prompt,
                name=agent_key,
                description=f"Progressive build step: {agent_key}",
                options={"max_tokens": 8192},
                tools=tools,
            )
            override_key = "developer"

        _apply_agent_overrides(agent, override_key, self._agent_configs)
        self._inject_driver(agent, model)

        group = AsyncSequentialGroup(
            [(agent, "{prompt}")],
            state={"prompt": user_prompt},
            error_policy=ErrorPolicy.raise_on_error,
            deps=deps,
            **self._group_budget_kwargs,
        )
        _attach_streaming_callbacks(group, self._emit)
        result = await group.run(user_prompt)

        usage = getattr(result, "aggregate_usage", None)
        if isinstance(usage, dict):
            self._pending_usage[agent_key] = usage
            for k, v in usage.items():
                if isinstance(v, (int, float)):
                    self._combined_usage[k] = self._combined_usage.get(k, 0) + v

        state = getattr(result, "shared_state", None) or {}
        if output_key and state.get(output_key):
            out = state[output_key]
            if isinstance(out, str):
                return out
            if hasattr(out, "model_dump_json"):
                return out.model_dump_json()
            return json.dumps(out)

        for agent_result in reversed(getattr(result, "agent_results", []) or []):
            text = getattr(agent_result, "output_text", "") or ""
            if text:
                return text
        return getattr(result, "output_text", "") or ""

    # -- main entry point --

    async def generate(
        self,
        project: Project,
        *,
        slug: str,
        version_number: int,
        page_prompt: str,
        max_cost: float | None = None,
        budget_policy: str | None = None,
        discovery_brief: DiscoveryBrief | None = None,
        **kwargs: Any,
    ) -> GroupResult:
        """Run the progressive pipeline for a single page version.

        Extra kwargs are accepted (and ignored) for forward compatibility
        with :meth:`GenerationPipeline.generate`.
        """
        model = project.model or settings.default_model
        version_dir = self._pm.ensure_version_dir(project.id, slug, version_number)

        self._group_budget_kwargs = {
            k: v
            for k, v in _build_budget_kwargs(max_cost, budget_policy, None, None, None).items()
            if k == "max_total_cost"
        }

        deps = {
            "project_dir": self._pm.project_dir(project.id),
            "version_dir": version_dir,
            "assets_dir": self._pm.assets_dir(project.id),
            "project_id": project.id,
            "project_component_repo": self._project_component_repo,
        }

        async def _push_preview(path: str, html: str) -> None:
            content_hash = hashlib.sha1(html.encode("utf-8")).hexdigest()[:12]
            await self._emit("preview_update", data={
                "page_slug": slug,
                "path": path,
                "html": html,
                "content_hash": content_hash,
                "bytes": len(html),
            })

        async def _write_file(path: str, content: str) -> None:
            self._pm.write_version_file(project.id, slug, version_number, path, content)
            await self._emit("file_written", data={"path": path})

        # Inject per-user CachiBot API key into env for this generation
        import os as _os

        _prev_cachibot_key = _os.environ.get("CACHIBOT_API_KEY")
        if self._cachibot_api_key:
            _os.environ["CACHIBOT_API_KEY"] = self._cachibot_api_key

        try:
            for agent_key in ("pm", "designer", "developer"):
                self._agent_models[agent_key] = _agent_model(agent_key, model, self._agent_configs)

            await self._emit("phase_start", data={"phase": "planning", "slug": slug, "version": version_number})

            # --- Stage A: PM → SitePlan (same pattern as pipeline.py) ---
            pm_prompt = page_prompt
            if discovery_brief is not None:
                from ..agents.discovery import render_brief

                pm_prompt = f"{render_brief(discovery_brief)}\n\n---\n\nUser brief:\n{page_prompt}"

            site_plan_text = await self._tracked_run(
                "pm", None, pm_prompt, self._agent_models["pm"], deps,
                project=project, slug=slug, version_number=version_number,
            )
            self.site_plan_text = site_plan_text
            if site_plan_text:
                try:
                    self._pm.write_guide(project.id, "site-plan.json", site_plan_text)
                except Exception:
                    logger.warning("Failed to write site-plan.json guide", exc_info=True)

            site_plan: SitePlan | None = None
            if site_plan_text and site_plan_text.strip():
                try:
                    from prompture import clean_json_text

                    site_plan = SitePlan.model_validate(json.loads(clean_json_text(site_plan_text)))
                except Exception:
                    logger.debug("JSON parse of PM output failed, trying extract_structured fallback")
                    from .extract import extract_structured

                    site_plan = await extract_structured(
                        SitePlan,
                        site_plan_text,
                        self._agent_models.get("pm", model),
                        instruction="Extract the site plan from this output:",
                    )

            if site_plan is not None:
                await self._emit("site_plan_ready", data={
                    "site_plan": site_plan.model_dump(),
                    "required_agents": site_plan.required_agents,
                    "tech_stack": site_plan.tech_stack.model_dump(),
                })

            page_plan = None
            if site_plan is not None:
                page_plan = next(
                    (p for p in site_plan.pages if p.slug == slug),
                    site_plan.pages[0] if site_plan.pages else None,
                )
            sections = list(page_plan.sections) if page_plan and page_plan.sections else []
            if not sections:
                logger.info("No planned sections for page '%s' — synthesizing a default outline", slug)
                sections = [
                    f"Hero section introducing: {page_prompt[:80]}",
                    "Key features or highlights",
                    "Call to action",
                    "Footer with contact and links",
                ]
            keys = derive_section_keys(sections)
            shared_components = list(site_plan.shared_components) if site_plan is not None else []
            available_components = await component_catalog_lines(project.id, self._project_component_repo)

            # --- Stage B: Designer → StyleSpec (same pattern as pipeline.py) ---
            required_agents = list(site_plan.required_agents) if site_plan is not None else ["designer"]
            style_spec_text = ""
            if "designer" in required_agents:
                designer_prompt = (
                    "Design a visual style for this website:\n\n"
                    f"Site Plan: {site_plan_text}\n\n"
                    f"Logo URL: {project.logo_url or ''}\n"
                    f"Icon URL: {project.icon_url or ''}\n\n"
                    "Create a cohesive color scheme, typography, and spacing system."
                )
                style_spec_text = await self._tracked_run(
                    "designer", None, designer_prompt, self._agent_models["designer"], deps,
                    project=project, slug=slug, version_number=version_number,
                )
                self.style_spec_text = style_spec_text
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
            else:
                style_spec_text = (
                    project.style_spec.model_dump_json() if project.style_spec else StyleSpec().model_dump_json()
                )

            # --- Stage C1: Layout skeleton → immediate first preview ---
            await self._emit("phase_start", data={"phase": "layout", "slug": slug, "version": version_number})
            dev_model = self._agent_models["developer"]
            skeleton_prompt = build_skeleton_prompt(
                page_prompt=page_prompt,
                site_plan_text=site_plan_text,
                sections=list(zip(keys, sections, strict=True)),
                style_spec_text=style_spec_text,
                shared_components=shared_components,
            )
            layout_text = await self._tracked_run(
                "layout", LAYOUT_PERSONA, skeleton_prompt, dev_model, deps,
                project=project, slug=slug, version_number=version_number,
            )

            doc, css_text = self._parse_skeleton(layout_text)

            # Deterministic fix: append any missing markers before </body>.
            for key in keys:
                if marker_for(key) not in doc:
                    logger.warning("Layout skeleton missing marker for '%s' — appending it", key)
                    doc = splice_section(doc, key, marker_for(key))

            await _write_file("index.html", doc)
            await _write_file("styles.css", css_text or "/* styles generated per-section */\n")
            await _push_preview("index.html", doc)

            # --- Stage C2: sections in parallel, spliced as they land ---
            await self._emit("phase_start", data={
                "phase": "sections", "slug": slug, "version": version_number, "count": len(keys),
            })
            semaphore = asyncio.Semaphore(self._max_parallel_sections)
            doc_lock = asyncio.Lock()
            state = {"doc": doc}

            async def _build_section(i: int, key: str, description: str) -> None:
                async with semaphore:
                    agent_key = f"section:{key}"
                    prompt = build_section_prompt(
                        page_prompt=page_prompt,
                        key=key,
                        description=description,
                        index=i,
                        total=len(keys),
                        style_spec_text=style_spec_text,
                        css=css_text,
                        shared_components=shared_components,
                        available_components=available_components,
                    )
                    attempts = 0
                    fallback = False
                    fragment = ""
                    problems: list[str] = []
                    await self._agent_started(agent_key, project, slug, version_number, dev_model)
                    try:
                        while attempts < self._max_section_attempts:
                            attempts += 1
                            attempt_prompt = (
                                prompt
                                if attempts == 1
                                else build_repair_prompt(original_prompt=prompt, problems=problems, fragment=fragment)
                            )
                            raw = await self._run_agent(
                                agent_key, SECTION_PERSONA, attempt_prompt, dev_model, deps,
                                tools=component_library_tools,
                            )
                            fragment = clean_fragment(raw)
                            problems = validate_fragment(fragment)
                            if not problems:
                                break
                            logger.info(
                                "Section '%s' attempt %d/%d invalid: %s",
                                key, attempts, self._max_section_attempts, problems,
                            )
                    except Exception as exc:
                        logger.warning("Section '%s' agent failed — using fallback fragment", key, exc_info=True)
                        problems = problems or [str(exc)]
                    if problems:
                        fallback = True
                        fragment = self._fallback_fragment(key, description)
                    await self._agent_finished(agent_key, output_text=fragment)

                    async with doc_lock:
                        state["doc"] = splice_section(state["doc"], key, fragment)
                        self._pm.write_version_file(project.id, slug, version_number, "index.html", state["doc"])
                    await self._emit("file_written", data={"path": "index.html"})
                    await _push_preview("index.html", state["doc"])
                    await self._emit("section_complete", agent=agent_key, data={
                        "key": key,
                        "attempts": attempts,
                        "fallback": fallback,
                    })

            await asyncio.gather(*(_build_section(i, k, d) for i, (k, d) in enumerate(zip(keys, sections, strict=True), start=1)))

            # --- Stage C3: finalize ---
            final_doc = state["doc"]
            await _push_preview("index.html", final_doc)

            final_files = self._pm.list_version_files(project.id, slug, version_number)
            files_content: dict[str, str] = {}
            for fpath in final_files:
                content = self._pm.read_version_file(project.id, slug, version_number, fpath)
                if content is not None:
                    files_content[fpath] = content

            await self._emit("generation_complete", data={
                "success": True,
                "slug": slug,
                "version": version_number,
                "files": final_files,
                "files_content": files_content,
                "usage": self._combined_usage,
            })

            return GroupResult(
                agent_results=[],
                aggregate_usage=self._combined_usage,
                shared_state={},
                elapsed_ms=0,
                timeline=[],
                errors=[],
                success=True,
            )

        except Exception as exc:
            import traceback

            logger.exception("Progressive generation failed for project %s page %s v%d", project.id, slug, version_number)
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

    # -- skeleton parsing + fallback fragment --

    @staticmethod
    def _parse_skeleton(layout_text: str) -> tuple[str, str]:
        """Extract (index.html, styles.css) from the layout agent's output."""
        from prompture import extract_fenced_blocks

        cleaned = GenerationPipeline._strip_reasoning_preamble(layout_text or "")
        blocks = extract_fenced_blocks(cleaned, languages=["html", "css"])
        doc = next((b.content for b in blocks if b.language == "html"), "")
        css_text = next((b.content for b in blocks if b.language == "css"), "")
        if not doc:
            from prompture import extract_html_document

            raw = extract_html_document(cleaned)
            if raw.found:
                doc = raw.html
        if not doc:
            raise RuntimeError("Layout agent produced no HTML skeleton")
        return doc, css_text

    @staticmethod
    def _fallback_fragment(key: str, description: str) -> str:
        """Minimal graceful fallback for a section that never validated."""
        title = (description or "").strip().rstrip(".")[:80] or key.replace("-", " ").title()
        return (
            f'<section class="section section-{_html.escape(key)}">\n'
            f"  <h2>{_html.escape(title)}</h2>\n"
            f"</section>"
        )
