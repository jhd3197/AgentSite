"""Pipeline orchestration using Prompture groups."""

from __future__ import annotations

from typing import Any

from prompture import AsyncLoopGroup, AsyncSequentialGroup, GroupCallbacks
from prompture.groups import ParallelGroup

from ..config import settings
from ..engine.model_resolver import resolve_agent_model
from ..models import AgentConfig
from .designer import create_designer_agent_auto
from .developer import create_developer_agent_auto
from .pm import create_pm_agent_auto
from .reviewer import create_reviewer_agent_auto


def create_pipeline(
    model: str | None = None,
    *,
    callbacks: GroupCallbacks | None = None,
    max_review_iterations: int | None = None,
    review_threshold: int | None = None,
    agent_configs: dict[str, AgentConfig] | None = None,
    deps: Any = None,
) -> AsyncSequentialGroup:
    """Build the full generation pipeline (static — all 4 agents).

    Pipeline structure::

        SequentialGroup([
            PM Agent         -> site_plan
            Designer Agent   -> style_spec
            LoopGroup([      (per build+review cycle)
                Developer    -> page_output
                Reviewer     -> review_feedback
            ])
        ])

    Args:
        model: Model string (provider/model). Defaults to settings.
        callbacks: Group-level observability callbacks.
        max_review_iterations: Max dev+review cycles. Defaults to settings.
        review_threshold: Min review score to approve. Defaults to settings.
        agent_configs: Per-agent config overrides from DB.
    """
    effective_model = model or settings.default_model
    max_iters = max_review_iterations or settings.max_review_iterations
    threshold = review_threshold or settings.review_approval_threshold

    # Use auto factories to select the right agent variant based on model capabilities
    pm = create_pm_agent_auto(_agent_model("pm", effective_model, agent_configs))
    designer = create_designer_agent_auto(_agent_model("designer", effective_model, agent_configs))
    developer = create_developer_agent_auto(_agent_model("developer", effective_model, agent_configs))
    reviewer = create_reviewer_agent_auto(_agent_model("reviewer", effective_model, agent_configs))

    # Apply temperature and system prompt overrides from configs
    _apply_agent_overrides(pm, "pm", agent_configs)
    _apply_agent_overrides(designer, "designer", agent_configs)
    _apply_agent_overrides(developer, "developer", agent_configs)
    _apply_agent_overrides(reviewer, "reviewer", agent_configs)

    # Build+Review loop: exit when approved or max iterations reached
    def _exit_condition(state: dict[str, Any], iteration: int) -> bool:
        feedback_text = state.get("review_feedback", "")
        if not feedback_text:
            return False
        lower = feedback_text.lower()
        return '"approved": true' in lower or '"approved":true' in lower

    build_review_loop = AsyncLoopGroup(
        [
            (
                developer,
                "You are building the '{page_slug}' page ONLY. "
                "Ignore other pages in the site plan.\n\n"
                "Build the website page based on this plan:\n\n"
                "Site Plan: {site_plan}\n\n"
                "Style Spec: {style_spec}\n\n"
                "Project Design Guide: {design_system_guide}\n"
                "Architecture Guide: {architecture_guide}\n\n"
                "Logo URL: {logo_url}\n"
                "Icon URL: {icon_url}\n\n"
                "Previous review feedback (if any): {review_feedback}\n\n"
                "Skill guidance (when set, treat as authoritative for this page type):\n"
                "{skill_instructions}\n\n"
                "Live user steer (incorporate these tweaks if present):\n{user_steer}\n\n"
                "Use the write_file tool to save each file. Generate complete, "
                "self-contained HTML with inline or linked CSS/JS.",
            ),
            (
                reviewer,
                "Review the generated website code.\n\n"
                "Site Plan: {site_plan}\n"
                "Style Spec: {style_spec}\n"
                "Project Design Guide: {design_system_guide}\n"
                "Architecture Guide: {architecture_guide}\n"
                "Developer output: {page_output}\n\n"
                "IMPORTANT: First call the list_files tool to discover what files were generated, "
                "then use read_file to inspect each one. "
                f"Approve if quality score >= {threshold}.",
            ),
        ],
        exit_condition=_exit_condition,
        max_iterations=max_iters,
        callbacks=callbacks,
        deps=deps,
    )

    # Full pipeline
    pipeline = AsyncSequentialGroup(
        [
            (pm, "{prompt}"),
            (
                designer,
                "Design a visual style for this website:\n\n"
                "Site Plan: {site_plan}\n\n"
                "Logo URL: {logo_url}\n"
                "Icon URL: {icon_url}\n\n"
                "Create a cohesive color scheme, typography, and spacing system.",
            ),
            build_review_loop,
        ],
        callbacks=callbacks,
        deps=deps,
    )

    return pipeline


def _apply_budget_to_agent(
    agent: Any,
    budget_policy: Any | None = None,
    fallback_models: list[str] | None = None,
    max_tokens: int | None = None,
    on_model_fallback: Any | None = None,
) -> None:
    """Apply budget policy parameters to an agent instance."""
    if budget_policy is not None:
        agent._budget_policy = budget_policy
    if fallback_models:
        agent._fallback_models = fallback_models
    if max_tokens:
        agent._max_tokens = max_tokens
    if on_model_fallback is not None:
        agent._on_model_fallback = on_model_fallback


def _inject_driver_if_needed(agent: Any, model_str: str, provider_keys: dict[str, str] | None) -> None:
    """Inject a per-project driver into an agent if provider_keys are set."""
    if not provider_keys:
        return
    from ..engine.driver_factory import resolve_driver_for_model

    driver = resolve_driver_for_model(model_str, provider_keys)
    if driver is not None:
        agent.driver = driver


def _render_verify_step(enabled: bool):
    """Build the render-verify loop step, or None when it can't run.

    When verification is disabled or Playwright isn't installed the step is
    omitted entirely, so the review loop behaves exactly as before
    (code-reading review only).
    """
    if not enabled:
        return None
    from ..engine import verifier

    if not verifier.playwright_available():
        return None
    return verifier.RenderVerifyStep()


def create_dynamic_pipeline(
    required_agents: list[str],
    model: str | None = None,
    *,
    callbacks: GroupCallbacks | None = None,
    max_review_iterations: int | None = None,
    review_threshold: int | None = None,
    agent_configs: dict[str, AgentConfig] | None = None,
    error_policy: Any = None,
    deps: Any = None,
    max_total_cost: float | None = None,
    budget_policy: Any | None = None,
    fallback_models: list[str] | None = None,
    budget_max_tokens: int | None = None,
    on_model_fallback: Any | None = None,
    provider_keys: dict[str, str] | None = None,
    render_verify: bool = False,
) -> AsyncSequentialGroup:
    """Build a dynamic pipeline based on PM's required_agents output.

    PM always runs before this. This builds the remaining pipeline steps
    based on which agents the PM decided are needed.

    Args:
        required_agents: List of agent keys from SitePlan.required_agents.
        model: Default model string.
        callbacks: Group-level observability callbacks.
        max_review_iterations: Max dev+review cycles.
        review_threshold: Min review score.
        agent_configs: Per-agent config overrides from DB.
        provider_keys: Per-project provider API keys for driver injection.
    """
    effective_model = model or settings.default_model
    max_iters = max_review_iterations or settings.max_review_iterations
    threshold = review_threshold or settings.review_approval_threshold

    steps: list[Any] = []

    _budget_kw = dict(
        budget_policy=budget_policy,
        fallback_models=fallback_models,
        max_tokens=budget_max_tokens,
        on_model_fallback=on_model_fallback,
    )

    # Designer (optional) - use auto factory for capability detection
    if "designer" in required_agents:
        _dm = _agent_model("designer", effective_model, agent_configs)
        designer = create_designer_agent_auto(_dm)
        _apply_agent_overrides(designer, "designer", agent_configs)
        _apply_budget_to_agent(designer, **_budget_kw)
        _inject_driver_if_needed(designer, _dm, provider_keys)
        steps.append(
            (
                designer,
                "Design a visual style for this website:\n\n"
                "Site Plan: {site_plan}\n\n"
                "Logo URL: {logo_url}\n"
                "Icon URL: {icon_url}\n\n"
                "Create a cohesive color scheme, typography, and spacing system.",
            )
        )

    # Developer (always required) - use auto factory for capability detection
    _dev_m = _agent_model("developer", effective_model, agent_configs)
    developer = create_developer_agent_auto(_dev_m)
    _apply_agent_overrides(developer, "developer", agent_configs)
    _apply_budget_to_agent(developer, **_budget_kw)
    _inject_driver_if_needed(developer, _dev_m, provider_keys)

    if "reviewer" in required_agents:
        # Use auto factory for capability detection
        _rev_m = _agent_model("reviewer", effective_model, agent_configs)
        reviewer = create_reviewer_agent_auto(_rev_m)
        _apply_agent_overrides(reviewer, "reviewer", agent_configs)
        _apply_budget_to_agent(reviewer, **_budget_kw)
        _inject_driver_if_needed(reviewer, _rev_m, provider_keys)

        # Rendered-output verification: a loop step between developer and
        # reviewer verifies the actual page in a headless browser. Failures
        # block loop exit (like a reviewer rejection) and flow back to the
        # developer via {verify_feedback}; screenshots reach the reviewer
        # through the vision proxy when the model supports images.
        verify_step = _render_verify_step(render_verify)
        reviewer_step: Any = reviewer
        dev_verify_line = ""
        rev_verify_line = ""
        if verify_step is not None:
            from ..engine.verifier import VisionReviewerProxy

            reviewer_step = VisionReviewerProxy(reviewer, _rev_m)
            dev_verify_line = (
                "Automated render verification (from loading the page in a real "
                "browser; failures MUST be fixed, empty means it passed):\n"
                "{verify_feedback}\n\n"
            )
            rev_verify_line = (
                "Automated render verification failures (from a real browser; "
                "weigh these heavily in your score):\n{verify_feedback}\n\n"
                "If screenshots of the rendered page are attached, judge the "
                "visual result from them (layout, spacing, responsiveness).\n\n"
            )

        def _exit_condition(state: dict[str, Any], iteration: int) -> bool:
            if state.get("verify_feedback"):
                return False  # rendered page failed verification — keep fixing
            feedback_text = state.get("review_feedback", "")
            if not feedback_text:
                return False
            lower = feedback_text.lower()
            return '"approved": true' in lower or '"approved":true' in lower

        loop_steps: list[Any] = [
            (
                developer,
                "You are building the '{page_slug}' page ONLY. "
                "Ignore other pages in the site plan.\n\n"
                "Build the website page based on this plan:\n\n"
                "Site Plan: {site_plan}\n\n"
                "Style Spec: {style_spec}\n\n"
                "Project Design Guide: {design_system_guide}\n"
                "Architecture Guide: {architecture_guide}\n\n"
                "Logo URL: {logo_url}\n"
                "Icon URL: {icon_url}\n\n"
                "Previous review feedback (if any): {review_feedback}\n\n"
                + dev_verify_line
                + "Use the write_file tool to save each file. Generate complete, "
                "self-contained HTML with inline or linked CSS/JS.",
            ),
        ]
        if verify_step is not None:
            loop_steps.append(verify_step)
        loop_steps.append(
            (
                reviewer_step,
                "Review the generated website code.\n\n"
                "Site Plan: {site_plan}\n"
                "Style Spec: {style_spec}\n"
                "Project Design Guide: {design_system_guide}\n"
                "Architecture Guide: {architecture_guide}\n"
                "Developer output: {page_output}\n\n"
                + rev_verify_line
                + "IMPORTANT: First call the list_files tool to discover what files were generated, "
                "then use read_file to inspect each one. "
                f"Approve if quality score >= {threshold}.",
            ),
        )

        build_review_loop = AsyncLoopGroup(
            loop_steps,
            exit_condition=_exit_condition,
            max_iterations=max_iters,
            callbacks=callbacks,
            deps=deps,
            max_total_cost=max_total_cost,
        )
        steps.append(build_review_loop)
    else:
        # Developer only, no review loop
        steps.append(
            (
                developer,
                "You are building the '{page_slug}' page ONLY. "
                "Ignore other pages in the site plan.\n\n"
                "Build the website page based on this plan:\n\n"
                "Site Plan: {site_plan}\n\n"
                "Style Spec: {style_spec}\n\n"
                "Project Design Guide: {design_system_guide}\n"
                "Architecture Guide: {architecture_guide}\n\n"
                "Logo URL: {logo_url}\n"
                "Icon URL: {icon_url}\n\n"
                "Use the write_file tool to save each file. Generate complete, "
                "self-contained HTML with inline or linked CSS/JS.",
            )
        )

    kwargs: dict[str, Any] = {"callbacks": callbacks, "deps": deps}
    if error_policy is not None:
        kwargs["error_policy"] = error_policy
    if max_total_cost is not None:
        kwargs["max_total_cost"] = max_total_cost
    return AsyncSequentialGroup(steps, **kwargs)


def create_specialist_pipeline(
    required_agents: list[str],
    model: str | None = None,
    *,
    callbacks: GroupCallbacks | None = None,
    max_review_iterations: int | None = None,
    review_threshold: int | None = None,
    agent_configs: dict[str, AgentConfig] | None = None,
    error_policy: Any = None,
    deps: Any = None,
    max_total_cost: float | None = None,
    budget_policy: Any | None = None,
    fallback_models: list[str] | None = None,
    budget_max_tokens: int | None = None,
    on_model_fallback: Any | None = None,
    provider_keys: dict[str, str] | None = None,
    render_verify: bool = False,
) -> AsyncSequentialGroup:
    """Build a specialist pipeline with parallel execution.

    Pipeline structure::

        SequentialGroup([
            Image Agent (if "image" in required_agents)  → assets first
            ParallelGroup([                              → concurrent
                Markup Agent  → index.html / App.jsx
                Style Agent   → styles.css / styles.scss
                Script Agent  → script.js
            ])
            (optional) LoopGroup([                       → review cycle
                ParallelGroup([markup, style, script])
                Reviewer
            ])
        ])

    Specialists write to the same version_dir via ctx.deps (filesystem),
    not via state. Each writes different file types so there are no conflicts.
    """
    # Lazy imports to avoid circular import chain
    from .specialists.accessibility import create_accessibility_agent
    from .specialists.animation import create_animation_agent
    from .specialists.copywriter import create_copywriter_agent
    from .specialists.image import create_image_agent
    from .specialists.markup import create_markup_agent
    from .specialists.script import create_script_agent
    from .specialists.seo import create_seo_agent
    from .specialists.style import create_style_agent, create_style_scss_agent

    effective_model = model or settings.default_model
    max_iters = max_review_iterations or settings.max_review_iterations
    threshold = review_threshold or settings.review_approval_threshold

    # Rendered-output verification step (see create_dynamic_pipeline). Built
    # up front so specialist prompts can surface {verify_feedback} on retries.
    verify_step = _render_verify_step(render_verify)
    dev_verify_line = ""
    if verify_step is not None:
        dev_verify_line = (
            "Automated render verification (from loading the page in a real "
            "browser; failures MUST be fixed, empty means it passed):\n"
            "{verify_feedback}\n\n"
        )

    _budget_kw = dict(
        budget_policy=budget_policy,
        fallback_models=fallback_models,
        max_tokens=budget_max_tokens,
        on_model_fallback=on_model_fallback,
    )

    steps: list[Any] = []

    # --- Image agent runs FIRST (sequential) so asset-manifest.md exists ---
    if "image" in required_agents:
        _img_m = _agent_model("image", effective_model, agent_configs)
        img_agent = create_image_agent(_img_m)
        _apply_agent_overrides(img_agent, "image", agent_configs)
        _apply_budget_to_agent(img_agent, **_budget_kw)
        _inject_driver_if_needed(img_agent, _img_m, provider_keys)
        steps.append(
            (
                img_agent,
                "Generate images for this website page.\n\n"
                "Site Plan: {site_plan}\n"
                "Style Spec: {style_spec}\n"
                "Page: {page_slug}\n\n"
                "Check existing assets first, then generate what's missing.",
            )
        )

    # --- Build the parallel group of specialists ---
    parallel_agents: list[Any] = []

    if "markup" in required_agents:
        _mk_m = _agent_model("markup", effective_model, agent_configs)
        markup = create_markup_agent(_mk_m)
        _apply_agent_overrides(markup, "markup", agent_configs)
        _apply_budget_to_agent(markup, **_budget_kw)
        _inject_driver_if_needed(markup, _mk_m, provider_keys)
        parallel_agents.append(
            (
                markup,
                "You are building the '{page_slug}' page ONLY.\n\n"
                "Site Plan: {site_plan}\n"
                "Style Spec: {style_spec}\n"
                "Design Guide: {design_system_guide}\n"
                "Architecture Guide: {architecture_guide}\n"
                "Logo URL: {logo_url}\n"
                "Icon URL: {icon_url}\n"
                "Tech Stack: {tech_stack}\n\n"
                "Skill guidance (when set, treat as authoritative for this page type):\n"
                "{skill_instructions}\n\n"
                "Previous review feedback (if any): {review_feedback}\n\n"
                + dev_verify_line
                + "Write the HTML markup file. Reference styles.css and script.js via link/script tags.",
            )
        )

    # Style — pick CSS or SCSS variant
    if "style_scss" in required_agents:
        _ss_m = _agent_model("style_scss", effective_model, agent_configs)
        style = create_style_scss_agent(_ss_m)
        _apply_agent_overrides(style, "style_scss", agent_configs)
        _apply_budget_to_agent(style, **_budget_kw)
        _inject_driver_if_needed(style, _ss_m, provider_keys)
        parallel_agents.append(
            (
                style,
                "Write the SCSS stylesheet for the '{page_slug}' page.\n\n"
                "Style Spec: {style_spec}\n"
                "Design Guide: {design_system_guide}\n"
                "Tech Stack: {tech_stack}\n\n"
                "Previous review feedback (if any): {review_feedback}\n\n"
                + dev_verify_line
                + "Write styles.scss with all design tokens and responsive styles.",
            )
        )
    elif "style" in required_agents:
        _st_m = _agent_model("style", effective_model, agent_configs)
        style = create_style_agent(_st_m)
        _apply_agent_overrides(style, "style", agent_configs)
        _apply_budget_to_agent(style, **_budget_kw)
        _inject_driver_if_needed(style, _st_m, provider_keys)
        parallel_agents.append(
            (
                style,
                "Write the CSS stylesheet for the '{page_slug}' page.\n\n"
                "Style Spec: {style_spec}\n"
                "Design Guide: {design_system_guide}\n"
                "Tech Stack: {tech_stack}\n\n"
                "Previous review feedback (if any): {review_feedback}\n\n"
                + dev_verify_line
                + "Write styles.css with all design tokens and responsive styles.",
            )
        )

    if "script" in required_agents:
        _sc_m = _agent_model("script", effective_model, agent_configs)
        script = create_script_agent(_sc_m)
        _apply_agent_overrides(script, "script", agent_configs)
        _apply_budget_to_agent(script, **_budget_kw)
        _inject_driver_if_needed(script, _sc_m, provider_keys)
        parallel_agents.append(
            (
                script,
                "Write the JavaScript for the '{page_slug}' page.\n\n"
                "Site Plan: {site_plan}\n"
                "Architecture Guide: {architecture_guide}\n"
                "Tech Stack: {tech_stack}\n\n"
                "Previous review feedback (if any): {review_feedback}\n\n"
                + dev_verify_line
                + "Write script.js with mobile menu, smooth scroll, animations, form handling.",
            )
        )

    if not parallel_agents:
        raise ValueError("Specialist pipeline requires at least one of: markup, style, style_scss, script")

    from prompture import ErrorPolicy as EP

    eff_error_policy = error_policy if error_policy is not None else EP.raise_on_error

    parallel_group = ParallelGroup(
        parallel_agents,
        callbacks=callbacks,
        deps=deps,
        error_policy=eff_error_policy,
    )

    # --- Post-processing phase (after build, before review) ---
    post_process_steps: list[Any] = []
    _POST_PROCESS_KEYS = {"copywriter", "seo", "accessibility", "animation"}
    has_post_process = any(k in required_agents for k in _POST_PROCESS_KEYS)

    if has_post_process:
        # Copywriter runs first so SEO can read final copy for meta descriptions
        if "copywriter" in required_agents:
            _cw_m = _agent_model("copywriter", effective_model, agent_configs)
            cw = create_copywriter_agent(_cw_m)
            _apply_agent_overrides(cw, "copywriter", agent_configs)
            _apply_budget_to_agent(cw, **_budget_kw)
            _inject_driver_if_needed(cw, _cw_m, provider_keys)
            post_process_steps.append(
                (
                    cw,
                    "Rewrite all placeholder text in the '{page_slug}' page.\n\n"
                    "Site Plan: {site_plan}\n"
                    "Style Spec: {style_spec}\n"
                    "Design Guide: {design_system_guide}\n\n"
                    "Read existing HTML files, then rewrite all generic/placeholder copy "
                    "with compelling, on-brand text. Preserve HTML structure.",
                )
            )

        # SEO, Accessibility, Animation run in parallel (orthogonal modifications)
        post_parallel: list[Any] = []

        if "seo" in required_agents:
            _seo_m = _agent_model("seo", effective_model, agent_configs)
            seo = create_seo_agent(_seo_m)
            _apply_agent_overrides(seo, "seo", agent_configs)
            _apply_budget_to_agent(seo, **_budget_kw)
            _inject_driver_if_needed(seo, _seo_m, provider_keys)
            post_parallel.append(
                (
                    seo,
                    "Optimize the '{page_slug}' page for search engines.\n\n"
                    "Site Plan: {site_plan}\n"
                    "Style Spec: {style_spec}\n\n"
                    "Add meta tags, Open Graph, JSON-LD structured data, "
                    "fix heading hierarchy, create sitemap.xml and robots.txt.",
                )
            )

        if "accessibility" in required_agents:
            _a11y_m = _agent_model("accessibility", effective_model, agent_configs)
            a11y = create_accessibility_agent(_a11y_m)
            _apply_agent_overrides(a11y, "accessibility", agent_configs)
            _apply_budget_to_agent(a11y, **_budget_kw)
            _inject_driver_if_needed(a11y, _a11y_m, provider_keys)
            post_parallel.append(
                (
                    a11y,
                    "Fix accessibility issues in the '{page_slug}' page.\n\n"
                    "Style Spec: {style_spec}\n"
                    "Design Guide: {design_system_guide}\n\n"
                    "Add ARIA labels, fix tabindex/focus order, check color contrast, "
                    "add skip-nav links, ensure WCAG AA compliance.",
                )
            )

        if "animation" in required_agents:
            _anim_m = _agent_model("animation", effective_model, agent_configs)
            anim = create_animation_agent(_anim_m)
            _apply_agent_overrides(anim, "animation", agent_configs)
            _apply_budget_to_agent(anim, **_budget_kw)
            _inject_driver_if_needed(anim, _anim_m, provider_keys)
            post_parallel.append(
                (
                    anim,
                    "Add animations to the '{page_slug}' page.\n\n"
                    "Style Spec: {style_spec}\n"
                    "Design Guide: {design_system_guide}\n\n"
                    "Create animations.css and animations.js with scroll-triggered "
                    "animations. Modify HTML to add animation classes and link tags.",
                )
            )

        if len(post_parallel) > 1:
            post_process_steps.append(ParallelGroup(
                post_parallel,
                callbacks=callbacks,
                deps=deps,
                error_policy=eff_error_policy,
            ))
        elif post_parallel:
            post_process_steps.append(post_parallel[0])

    # --- Optionally wrap with reviewer loop ---
    if "reviewer" in required_agents:
        _rev_m = _agent_model("reviewer", effective_model, agent_configs)
        reviewer = create_reviewer_agent_auto(_rev_m)
        _apply_agent_overrides(reviewer, "reviewer", agent_configs)
        _apply_budget_to_agent(reviewer, **_budget_kw)
        _inject_driver_if_needed(reviewer, _rev_m, provider_keys)

        # Rendered-output verification step (built up front; see above).
        reviewer_step: Any = reviewer
        rev_verify_line = ""
        if verify_step is not None:
            from ..engine.verifier import VisionReviewerProxy

            reviewer_step = VisionReviewerProxy(reviewer, _rev_m)
            rev_verify_line = (
                "Automated render verification failures (from a real browser; "
                "weigh these heavily in your score):\n{verify_feedback}\n\n"
                "If screenshots of the rendered page are attached, judge the "
                "visual result from them (layout, spacing, responsiveness).\n\n"
            )

        def _exit_condition(state: dict[str, Any], iteration: int) -> bool:
            if state.get("verify_feedback"):
                return False  # rendered page failed verification — keep fixing
            feedback_text = state.get("review_feedback", "")
            if not feedback_text:
                return False
            lower = feedback_text.lower()
            return '"approved": true' in lower or '"approved":true' in lower

        # Build the inner steps: build parallel group + post-processing + reviewer
        loop_inner: list[Any] = [parallel_group]
        loop_inner.extend(post_process_steps)
        if verify_step is not None:
            loop_inner.append(verify_step)
        loop_inner.append(
            (
                reviewer_step,
                "Review the generated website code.\n\n"
                "Site Plan: {site_plan}\n"
                "Style Spec: {style_spec}\n"
                "Design Guide: {design_system_guide}\n"
                "Architecture Guide: {architecture_guide}\n\n"
                + rev_verify_line
                + "IMPORTANT: First call list_files to discover what files were generated, "
                "then use read_file to inspect each one. "
                f"Approve if quality score >= {threshold}.",
            ),
        )

        build_review_loop = AsyncLoopGroup(
            loop_inner,
            exit_condition=_exit_condition,
            max_iterations=max_iters,
            callbacks=callbacks,
            deps=deps,
            max_total_cost=max_total_cost,
        )
        steps.append(build_review_loop)
    else:
        steps.append(parallel_group)
        steps.extend(post_process_steps)

    kwargs: dict[str, Any] = {"callbacks": callbacks, "deps": deps}
    if error_policy is not None:
        kwargs["error_policy"] = error_policy
    if max_total_cost is not None:
        kwargs["max_total_cost"] = max_total_cost
    return AsyncSequentialGroup(steps, **kwargs)


def _apply_agent_overrides(
    agent: Any,
    agent_key: str,
    configs: dict[str, AgentConfig] | None,
) -> None:
    """Apply temperature and system_prompt_override from AgentConfig to a created agent.

    Model is already handled by ``_agent_model()`` at agent creation time.
    This function applies the remaining override fields (temperature and
    system_prompt_override) to the agent instance after it has been created.
    """
    if not configs or agent_key not in configs:
        return
    cfg = configs[agent_key]

    # Apply temperature via agent options
    if cfg.temperature is not None:
        if not hasattr(agent, "options") or agent.options is None:
            agent.options = {}
        agent.options["temperature"] = cfg.temperature

    # Apply system prompt override (replaces the default persona)
    if cfg.system_prompt_override:
        agent.system_prompt = cfg.system_prompt_override


def _agent_model(
    agent_key: str,
    default_model: str,
    configs: dict[str, AgentConfig] | None,
) -> str:
    """Resolve the model for an agent using multi-layer ModelResolver.

    Resolution order (via Prompture ModelResolver):
    1. Agent-specific override in ``configs`` (if valid provider/model format)
    2. ``default_model`` (project or request level)
    3. ``settings.default_model`` (global fallback)

    Falls back to manual resolution if ModelResolver is unavailable.
    """
    return resolve_agent_model(agent_key, default_model, configs)
