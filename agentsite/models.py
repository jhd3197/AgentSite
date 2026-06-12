"""Domain models for AgentSite.

All structured output types used by the agent pipeline, plus the
persistence models for Project, Page, and PageVersion.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field

# ------------------------------------------------------------------
# Pipeline output models (used as Agent output_type)
# ------------------------------------------------------------------


class DiscoveryBrief(BaseModel):
    """30-second discovery answers — ported from open-design discovery form.

    Captures what the user is building, who it's for, the brand context, and
    rough scope before the PM agent runs. Fields are intentionally permissive
    (defaults + lists) so partial answers still validate.
    """

    output: str = Field(
        default="",
        description=(
            "Surface type. One of: 'slide_deck', 'web_prototype', 'app_prototype', "
            "'dashboard', 'editorial', 'other'."
        ),
    )
    platform: list[str] = Field(
        default_factory=list,
        description="Target platforms: 'responsive_web', 'desktop_web', 'ios', 'android', 'tablet', 'desktop_app', 'fixed_canvas'.",
    )
    audience: str = Field(default="", description="Who this is for (free text).")
    tone: list[str] = Field(
        default_factory=list,
        description="Visual tone keywords (e.g. 'editorial', 'modern_minimal', 'playful', 'tech_utility', 'luxury', 'brutalist', 'human').",
    )
    brand_mode: str = Field(
        default="pick_direction",
        description="One of: 'pick_direction', 'brand_spec', 'reference_match'.",
    )
    scale: str = Field(default="", description="Rough scope (e.g. '1 landing + 3 sub-pages').")
    constraints: str = Field(default="", description="Anything else: deadlines, must-use fonts, things to avoid.")
    direction_id: str | None = Field(
        default=None,
        description="When brand_mode=='pick_direction' and the user has chosen one, the direction id (e.g. 'modern-minimal').",
    )


class TechStack(BaseModel):
    """Technology choices for a website build, decided by the PM agent."""

    markup: str = Field(default="html", description="Markup format: 'html' or 'jsx'")
    styling: str = Field(default="css", description="Styling format: 'css' or 'scss'")
    framework: str = Field(default="vanilla", description="Framework: 'vanilla' or 'react'")


class PagePlan(BaseModel):
    """Plan for a single page within a site."""

    slug: str = Field(description="URL slug, e.g. 'index', 'about', 'contact'")
    title: str = Field(description="Page title")
    sections: list[str] = Field(description="Ordered list of section descriptions")
    priority: int = Field(default=1, description="Build priority (1 = highest)")
    skill_id: str | None = Field(
        default=None,
        description=(
            "Phase 5 — id of the skill (from GET /api/skills) whose persona will guide "
            "the Developer for this page. None = use the default Developer persona."
        ),
    )


class SitePlan(BaseModel):
    """Output of the PM Agent — overall site structure."""

    project_name: str = Field(description="Name of the website project")
    tagline: str = Field(description="One-line description of the site")
    pages: list[PagePlan] = Field(description="Pages to generate, ordered by priority")
    shared_components: list[str] = Field(
        default_factory=lambda: ["navbar", "footer"],
        description="Shared UI components across pages",
    )
    tech_stack: TechStack = Field(
        default_factory=TechStack,
        description=(
            "Technology choices for the build. Use 'html'+'css'+'vanilla' for most sites. "
            "Use 'jsx'+'scss'+'react' for complex interactive apps."
        ),
    )
    required_agents: list[str] = Field(
        default_factory=lambda: ["designer", "developer", "reviewer"],
        description=(
            "Which agents are needed for this task. Options include:\n"
            "- 'designer': Design system (needed for new sites or brand changes)\n"
            "- 'developer': Monolithic developer (writes all HTML/CSS/JS)\n"
            "- 'markup': Specialist — writes HTML/JSX only\n"
            "- 'style': Specialist — writes CSS only\n"
            "- 'style_scss': Specialist — writes SCSS only\n"
            "- 'script': Specialist — writes JavaScript only\n"
            "- 'image': Specialist — generates images before other specialists\n"
            "- 'reviewer': QA review (needed for complex builds)\n"
            "Post-process agents (run after build, before reviewer):\n"
            "- 'copywriter': Rewrites placeholder text with on-brand copy\n"
            "- 'seo': Injects meta tags, sitemap.xml, robots.txt\n"
            "- 'accessibility': Adds ARIA labels, fixes contrast, WCAG AA\n"
            "- 'animation': Creates scroll-triggered animations and transitions\n"
            "Use EITHER 'developer' (monolithic) OR specialists ('markup'+'style'+'script'), not both."
        ),
    )


class StyleSpec(BaseModel):
    """Output of the Designer Agent — visual design specification.

    Also serves as the project's full brand / design-system token set.
    New tokens are optional with sensible defaults so existing data stays valid.
    """

    # Colors
    primary_color: str = Field(default="#2563eb", description="Primary brand color (hex)")
    secondary_color: str = Field(default="#1e40af", description="Secondary color (hex)")
    accent_color: str = Field(default="#f59e0b", description="Accent color (hex)")
    background_color: str = Field(default="#ffffff", description="Page background (hex)")
    surface_color: str = Field(default="#f8fafc", description="Surface / card background (hex)")
    text_color: str = Field(default="#1f2937", description="Body text color (hex)")
    text_secondary_color: str = Field(default="#6b7280", description="Secondary text color (hex)")
    border_color: str = Field(default="#e5e7eb", description="Default border color (hex)")

    # Typography — families
    font_heading: str = Field(default="Inter", description="Heading font family (Google Fonts)")
    font_body: str = Field(default="Inter", description="Body font family (Google Fonts)")
    font_mono: str = Field(default="JetBrains Mono", description="Monospace font family")

    # Typography — scale
    font_size_base: str = Field(default="16px", description="Base font size")
    font_size_sm: str = Field(default="14px", description="Small font size")
    font_size_lg: str = Field(default="18px", description="Large font size")
    font_size_xl: str = Field(default="20px", description="XL font size")
    font_size_2xl: str = Field(default="24px", description="2XL font size")
    font_size_3xl: str = Field(default="30px", description="3XL font size")
    font_size_4xl: str = Field(default="36px", description="4XL font size")

    # Typography — rhythm
    line_height: str = Field(default="1.6", description="Base line height")
    letter_spacing: str = Field(default="0", description="Base letter spacing")
    font_weight_normal: str = Field(default="400", description="Normal font weight")
    font_weight_medium: str = Field(default="500", description="Medium font weight")
    font_weight_bold: str = Field(default="700", description="Bold font weight")

    # Layout
    layout_style: str = Field(default="top-nav", description="Navigation layout: top-nav, sidebar, minimal, centered")
    nav_position: str = Field(default="sticky", description="Nav behavior: sticky, fixed, static")
    footer_style: str = Field(default="standard", description="Footer style: standard, minimal, none")
    max_width: str = Field(default="1200px", description="Container max width")
    container_padding: str = Field(default="1.5rem", description="Container horizontal padding")
    section_gap: str = Field(default="4rem", description="Vertical gap between page sections")

    # Spacing scale
    spacing_unit: str = Field(default="1rem", description="Base spacing unit")
    spacing_xs: str = Field(default="0.25rem", description="Extra-small spacing")
    spacing_sm: str = Field(default="0.5rem", description="Small spacing")
    spacing_md: str = Field(default="1rem", description="Medium spacing")
    spacing_lg: str = Field(default="1.5rem", description="Large spacing")
    spacing_xl: str = Field(default="2rem", description="Extra-large spacing")
    spacing_2xl: str = Field(default="3rem", description="2XL spacing")

    # Borders
    border_radius: str = Field(default="8px", description="Default border radius")
    border_radius_sm: str = Field(default="4px", description="Small border radius")
    border_radius_lg: str = Field(default="12px", description="Large border radius")
    border_radius_full: str = Field(default="9999px", description="Full / pill border radius")
    border_width: str = Field(default="1px", description="Default border width")

    # Shadows
    shadow_sm: str = Field(default="0 1px 2px rgba(0,0,0,0.05)", description="Small elevation shadow")
    shadow_md: str = Field(default="0 4px 6px rgba(0,0,0,0.07)", description="Medium elevation shadow")
    shadow_lg: str = Field(default="0 10px 15px rgba(0,0,0,0.1)", description="Large elevation shadow")

    # Effects
    transition_speed: str = Field(default="150ms", description="Default transition duration")
    backdrop_blur: str = Field(default="8px", description="Backdrop blur amount")

    # Phase 9 — design-system inheritance
    inherits_from: str | None = Field(
        default=None,
        description=(
            "ID of a bundled or user-saved design system. When set, the Designer "
            "extends those tokens instead of inventing fresh ones."
        ),
    )

    # Phase 2 — direction-library binding
    direction_id: str | None = Field(
        default=None,
        description="When the StyleSpec was synthesized from a `DesignDirection`, its id.",
    )
    bg_oklch: str | None = Field(default=None, description="Background in OKLch (parallel to background_color).")
    surface_oklch: str | None = Field(default=None, description="Surface in OKLch.")
    fg_oklch: str | None = Field(default=None, description="Foreground/text in OKLch.")
    muted_oklch: str | None = Field(default=None, description="Muted text/border in OKLch.")
    border_oklch: str | None = Field(default=None, description="Border in OKLch.")
    accent_oklch: str | None = Field(default=None, description="Accent in OKLch.")


class GeneratedFile(BaseModel):
    """A single file produced by the Developer Agent."""

    path: str = Field(description="Relative file path, e.g. 'index.html'")
    content: str = Field(description="Full file content")
    language: str = Field(default="html", description="File language: html, css, js")


class PageOutput(BaseModel):
    """Output of the Developer Agent — generated files for one page."""

    files: list[GeneratedFile] = Field(description="Generated files for this page")
    notes: str = Field(default="", description="Developer notes about the implementation")


class PageOutputSummary(BaseModel):
    """Lightweight summary returned by Developer Agent after writing files via tools.

    The actual file contents are written to disk using the write_file tool.
    This model only captures metadata so that JSON parsing stays reliable.
    """

    files_written: list[str] = Field(
        description="List of relative file paths that were written using the write_file tool, e.g. ['index.html', 'styles.css']"
    )
    notes: str = Field(default="", description="Brief developer notes about the implementation")


class TriageDecision(BaseModel):
    """Phase E — classification of a follow-up request (project mode).

    Decides which agents a generation actually needs instead of always
    running the full PM -> Designer -> Developer -> Reviewer line.
    """

    bucket: str = Field(
        default="full",
        description=(
            "'tweak' (small scoped change: copy/style/minor layout — developer only), "
            "'partial' (new pages or section rework within the existing brand — "
            "PM updates the plan, no designer), or "
            "'full' (new site / redesign / rebrand — everything runs)."
        ),
    )
    needs_pm: bool = Field(
        default=True,
        description="True when the site plan must be created or updated (structure changes).",
    )
    needs_designer: bool = Field(
        default=False,
        description="True only for visual rebrands — the design tokens get regenerated.",
    )
    reason: str = Field(default="", description="One short sentence explaining the choice.")


class ReviewFeedback(BaseModel):
    """Output of the Reviewer Agent — QA feedback."""

    issues: list[str] = Field(default_factory=list, description="Issues found in the code")
    suggestions: list[str] = Field(default_factory=list, description="Improvement suggestions")
    score: int = Field(default=5, description="Quality score from 1-10")
    approved: bool = Field(default=False, description="True if score >= 7 and no critical issues")


# ------------------------------------------------------------------
# Phase 4 — Multi-dimensional critique
# ------------------------------------------------------------------


CRITIQUE_DIMENSIONS = (
    "visual_fidelity",
    "accessibility",
    "content_quality",
    "code_health",
)


class DimensionScore(BaseModel):
    """One reviewer's verdict for a single dimension."""

    dimension: str = Field(description="One of CRITIQUE_DIMENSIONS")
    score: int = Field(default=5, description="1-10")
    issues: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class ReviewVerdict(BaseModel):
    """Aggregated judgment produced by the critique panel's judge."""

    scores: list[DimensionScore] = Field(default_factory=list)
    overall_score: int = Field(default=5, description="Min of dimension scores or judge override")
    approved: bool = Field(default=False)
    summary: str = Field(default="")

    def score_map(self) -> dict[str, int]:
        return {d.dimension: d.score for d in self.scores}


class MemoryFact(BaseModel):
    """Phase 10 — a durable per-project fact learned from prior runs."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    project_id: str = Field(default="")
    kind: str = Field(default="preference", description="preference | constraint | brand | other")
    body: str = Field(description="One-sentence fact in second person ('You prefer …').")
    confidence: float = Field(default=0.5, description="0-1")
    source_run_id: str = Field(default="")
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class QualityRatchet(BaseModel):
    """Per-project floor: future runs must equal or exceed every dimension."""

    project_id: str = Field(default="")
    floors: dict[str, int] = Field(
        default_factory=dict,
        description="Dimension -> minimum acceptable score (0 = no floor yet).",
    )
    last_verdict: ReviewVerdict | None = Field(default=None)
    history: list[dict] = Field(
        default_factory=list,
        description="Append-only log: {ts, slug, version, scores, accepted, raised}.",
    )


# ------------------------------------------------------------------
# Persistence models
# ------------------------------------------------------------------


class Project(BaseModel):
    """Persistent project record — top-level container with branding."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = Field(default="Untitled Project")
    description: str = Field(default="")
    model: str = Field(default="")
    logo_url: str = Field(default="")
    icon_url: str = Field(default="")
    style_spec: StyleSpec | None = Field(default=None)
    agent_overrides: dict | None = Field(
        default=None,
        description="Per-project agent overrides keyed by agent name (pm, designer, developer, reviewer). "
        "Each value is a dict with optional keys: model, temperature, system_prompt_override.",
    )
    provider_keys: dict[str, str] | None = Field(
        default=None,
        description="Per-project provider API keys keyed by provider name (openai, claude, google, etc.). "
        "When set, these override the global environment keys for this project only.",
    )
    mode: str = Field(
        default="mockup",
        description="'mockup' (page-version one-pagers) or 'project' (real template workspace).",
    )
    template_id: str | None = Field(
        default=None,
        description="Workspace template id (e.g. 'vite-react-tailwind') when mode=='project'.",
    )
    user_id: str | None = Field(default=None)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class Page(BaseModel):
    """A page within a project."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    project_id: str = Field(default="")
    slug: str = Field(default="home")
    title: str = Field(default="Home Page")
    prompt: str = Field(default="")
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class PageVersion(BaseModel):
    """A versioned output for a page."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    page_id: str = Field(default="")
    version_number: int = Field(default=1)
    status: str = Field(default="generating")  # generating, completed, failed
    prompt: str = Field(default="")
    usage: dict = Field(default_factory=dict)
    files: dict = Field(default_factory=dict)
    error: str | None = Field(default=None)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: str | None = Field(default=None)


# ------------------------------------------------------------------
# Agent configuration & run tracking
# ------------------------------------------------------------------


class AgentConfig(BaseModel):
    """Server-side configuration for a pipeline agent."""

    agent_name: str = Field(description="Agent key: pm, designer, developer, reviewer, markup, style, script, image")
    enabled: bool = Field(default=True, description="Whether this agent is active")
    model: str = Field(default="", description="Model override (empty = use project default)")
    temperature: float = Field(default=0.5, description="Sampling temperature 0-1")
    system_prompt_override: str | None = Field(
        default=None, description="Custom system prompt (None = use default persona)"
    )
    category: str = Field(default="", description="Agent category: planning, design, development, assets, qa")
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class AgentRun(BaseModel):
    """Record of a single agent execution during generation."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    project_id: str = Field(default="")
    page_slug: str = Field(default="")
    version: int = Field(default=1)
    agent_name: str = Field(default="")
    status: str = Field(default="running")  # running, completed, skipped, failed
    started_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: str | None = Field(default=None)
    input_tokens: int = Field(default=0)
    output_tokens: int = Field(default=0)
    cost: float = Field(default=0.0)
    reasoning: str = Field(default="")
    session_id: str = Field(default="")  # Prompture tracker session ID
    output_summary: dict = Field(default_factory=dict)
    strategy: str = Field(default="", description="Routing strategy that picked this run's model")
    model: str = Field(default="", description="Concrete model id used for this run")


# ------------------------------------------------------------------
# WebSocket event model
# ------------------------------------------------------------------


class ChatMessage(BaseModel):
    """A chat message within a page builder session."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    page_id: str = Field(default="")
    role: str = Field(default="user")  # user, agent, agent-progress
    content: str = Field(default="")
    image: str | None = Field(default=None)
    meta: dict = Field(default_factory=dict)  # agents list, done flag, etc.
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ------------------------------------------------------------------
# Project components (htmlstudio Phase 4 — user-saved reusable blocks)
# ------------------------------------------------------------------


class BlockFieldModel(BaseModel):
    """One editable surface on a BlockDefinition. Mirror of htmlstudio's BlockField."""

    key: str
    type: str = "text"  # text/textarea/url/image/color/select/number/boolean
    label: str = ""
    help: str = ""
    default: str | int | float | bool | None = None
    options: list[dict] = Field(default_factory=list)  # for type=select
    optional: bool = False


class ProjectComponent(BaseModel):
    """A reusable block definition saved to a specific project.

    Compatible shape with htmlstudio's `BlockDefinition` so the same
    palette / config form / render path works for builtins and project
    components alike.
    """

    id: str = Field(default_factory=lambda: "pc_" + uuid.uuid4().hex[:10])
    project_id: str
    slug: str
    name: str
    category: str = "custom"
    description: str = ""
    thumbnail: str = "🧱"
    template: str  # HTML with {{key}} placeholders
    fields: list[BlockFieldModel] = Field(default_factory=list)
    # Audit trail — where this component was extracted from
    source_instance_id: str | None = None
    source_page_slug: str | None = None
    source_version: int | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ------------------------------------------------------------------
# WebSocket event model
# ------------------------------------------------------------------


class WSEvent(BaseModel):
    """WebSocket event sent to the frontend."""

    type: str = Field(
        description=(
            "Event type: phase_start, phase_complete, agent_start, agent_complete, "
            "agent_thinking, agent_step, agent_iteration, agent_output, "
            "text_delta, tool_start, tool_end, "
            "error, file_written, generation_complete, "
            "pipeline_plan, model_fallback, budget_exceeded, "
            "discovery_form_requested, discovery_brief_submitted, "
            "critique_verdict, preview_update, skill_bound, "
            "todo_update, steer_received, steer_applied, "
            "memory_extracted, refusal_detected, "
            "workspace_scaffolded, preview_ready, build_started, "
            "build_finished, checkpoint_created, verify_started, verify_report, "
            "triage_decision, specialist_start, specialist_complete"
        )
    )
    agent: str = Field(default="", description="Agent name")
    data: dict = Field(default_factory=dict, description="Event payload")
