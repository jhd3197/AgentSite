"""Configuration for AgentSite via Pydantic-settings."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """AgentSite application settings loaded from environment / .env."""

    model_config = {"env_prefix": "AGENTSITE_", "env_file": ".env", "extra": "ignore"}

    # Default LLM model for all agents
    default_model: str = "openai/gpt-4o"

    # Data directory for projects and database
    data_dir: Path = Path.home() / ".agentsite"

    # Server
    host: str = "127.0.0.1"
    port: int = 6391

    # Agent pipeline
    max_review_iterations: int = 2
    review_approval_threshold: int = 7

    # Budget enforcement (0 = no limit)
    max_generation_cost: float = 0.0
    budget_policy: str = ""  # "hard_stop", "warn_and_continue", "degrade" (empty = disabled)
    budget_max_tokens: int = 0  # 0 = no limit
    budget_fallback_models: list[str] = []  # e.g. ["openai/gpt-4o-mini"]

    # Response caching
    cache_enabled: bool = False

    # Project-mode workspaces (Phase A-C of project-workspace roadmap)
    default_template: str = "static-multipage"
    package_manager: str = "auto"  # "auto" (pnpm then npm) | "npm" | "pnpm"
    install_timeout_s: int = 600
    build_timeout_s: int = 300
    workspace_max_file_kb: int = 256  # per-file cap when capturing text to DB
    project_max_cycles: int = 3  # dev->build->review cycles per generation
    project_dev_max_iterations: int = 40  # tool-loop iterations per dev run

    # Phase D — Playwright verification (project mode). Auto-skips when
    # playwright isn't installed: pip install agentsite[verify] &&
    # playwright install chromium
    verify_enabled: bool = True
    verify_timeout_s: int = 30  # per-route navigation timeout
    verify_max_routes: int = 8

    # Phase E — triage routing + specialist delegation (project mode)
    triage_enabled: bool = True  # scope follow-up builds (tweak/partial/full)
    specialist_max_delegations: int = 4  # delegate_to_specialist calls per build
    specialist_max_iterations: int = 20  # tool-loop cap per specialist run

    # Phase 3 — pre-flight enforcement on write_file (Developer must read
    # design-system.md and architecture.md first). Default on.
    preflight_enabled: bool = True
    preflight_required_guides: list[str] = ["design-system.md", "architecture.md"]

    # Phase 4 — multi-dimensional critique panel + ratchet. Default OFF for
    # one release; flip on once Phase 11 (smart routing) lands so the panel's
    # extra reviewer cost is offset.
    use_critique_panel: bool = False

    # Phase 7 — wrap the Developer in AsyncDeepAgent with planning on so we
    # get streamed todos + in-flight steer support. Off by default until the
    # plain Agent path is fully decommissioned.
    use_deep_agent_developer: bool = False

    # Phase 11 — per-agent routing. Maps agent_key -> strategy hint or
    # explicit model id. Strategies: "fast" | "cost_optimized" | "balanced"
    # | "quality_first". When the value contains "/" it is treated as an
    # explicit model id and used verbatim.
    agent_routing: dict[str, str] = {
        # Reviewers can be cheap; judge wants quality
        "triage": "cost_optimized",
        "accessibility": "cost_optimized",
        "seo": "cost_optimized",
        "critique_visual_fidelity": "cost_optimized",
        "critique_accessibility": "cost_optimized",
        "critique_content_quality": "fast",
        "critique_code_health": "balanced",
        "critique_judge": "quality_first",
    }
    # Strategy -> model id pool (first wins, fall through to next). Empty
    # pools fall back to settings.default_model.
    routing_model_pools: dict[str, list[str]] = {
        "fast": [],
        "cost_optimized": [],
        "balanced": [],
        "quality_first": [],
    }

    @property
    def projects_dir(self) -> Path:
        return self.data_dir / "projects"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "agentsite.db"

    def ensure_dirs(self) -> None:
        """Create required directories if they don't exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.projects_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()


def init_prompture() -> None:
    """Initialize Prompture global configuration (tracker + cache).

    Called once at app startup (CLI or server).
    """
    from prompture import configure_tracker

    configure_tracker(enabled=True, db_path=str(settings.data_dir / "usage.db"))

    if settings.cache_enabled:
        from prompture import configure_cache

        configure_cache(backend="sqlite", ttl=3600, db_path=str(settings.data_dir / "cache.db"))
