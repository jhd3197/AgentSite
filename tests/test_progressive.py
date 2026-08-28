"""Tests for the progressive (skeleton → parallel sections) generation pipeline."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import ClassVar

import pytest
from httpx import ASGITransport, AsyncClient

from agentsite.api import deps
from agentsite.api.app import create_app
from agentsite.engine.progressive import (
    ProgressivePipeline,
    build_repair_prompt,
    build_section_prompt,
    build_skeleton_prompt,
    clean_fragment,
    derive_section_keys,
    marker_for,
    splice_section,
    validate_fragment,
)
from agentsite.engine.project_manager import ProjectManager
from agentsite.storage.database import Database
from agentsite.storage.repository import (
    AgentConfigRepository,
    AgentRunRepository,
    PageRepository,
    ProjectRepository,
    VersionRepository,
)

# ------------------------------------------------------------------
# Pure helpers
# ------------------------------------------------------------------


class TestDeriveSectionKeys:
    def test_slugifies_first_words(self):
        keys = derive_section_keys(["Hero with headline", "Features grid", "Pricing table"])
        assert keys == ["hero", "features", "pricing"]

    def test_strips_leading_stopwords(self):
        keys = derive_section_keys(["The hero banner", "A features list"])
        assert keys == ["hero", "features"]

    def test_dedupes_with_suffix(self):
        keys = derive_section_keys(["Hero", "Hero banner", "Hero again"])
        assert keys == ["hero", "hero-2", "hero-3"]

    def test_fallback_for_empty_description(self):
        keys = derive_section_keys(["", "!!!", "Contact"])
        assert keys == ["section-1", "section-2", "contact"]


class TestMarkerAndSplice:
    def test_marker_for(self):
        assert marker_for("hero") == "<!-- @section:hero -->"

    def test_replaces_marker(self):
        doc = "<html><body><!-- @section:hero --></body></html>"
        out = splice_section(doc, "hero", "<section>HI</section>")
        assert out == "<html><body><section>HI</section></body></html>"

    def test_missing_marker_inserts_before_body_end(self):
        doc = "<html><body><p>x</p></BODY></html>"
        out = splice_section(doc, "hero", "<section>HI</section>")
        assert "<p>x</p><section>HI</section>\n</BODY>" in out

    def test_no_body_appends(self):
        doc = "<p>fragment only</p>"
        out = splice_section(doc, "hero", "<section>HI</section>")
        assert out.endswith("<section>HI</section>")
        assert "<p>fragment only</p>" in out


class TestCleanFragment:
    def test_strips_fences(self):
        raw = "```html\n<section><h1>Hi</h1></section>\n```"
        assert clean_fragment(raw) == "<section><h1>Hi</h1></section>"

    def test_strips_reasoning_preamble(self):
        raw = "Let me think about this section...\n```html\n<section>S</section>\n```"
        assert clean_fragment(raw) == "<section>S</section>"

    def test_unwraps_full_document(self):
        raw = (
            "<!DOCTYPE html><html><head><title>T</title><style>.x{}</style></head>"
            "<body><section>Body content</section></body></html>"
        )
        out = clean_fragment(raw)
        assert out == "<section>Body content</section>"

    def test_empty_input(self):
        assert clean_fragment("") == ""


class TestValidateFragment:
    def test_valid_fragment(self):
        html = "<section><h2>Welcome</h2><p>This is a proper section with real copy.</p></section>"
        assert validate_fragment(html) == []

    def test_empty(self):
        assert validate_fragment("") == ["fragment is empty"]
        assert validate_fragment("   \n ") == ["fragment is empty"]

    def test_unresolved_marker_or_placeholder(self):
        problems = validate_fragment("<!-- @section:hero --><p>some real copy here to pass length</p>")
        assert any("marker" in p for p in problems)
        problems = validate_fragment("<p>{{heading}} is a template placeholder that is long enough</p>")
        assert any("marker" in p for p in problems)

    def test_no_html_tag(self):
        problems = validate_fragment("just some plain text without any markup at all here")
        assert any("no HTML tag" in p for p in problems)

    def test_suspiciously_short(self):
        problems = validate_fragment("<section><h2>Hi</h2></section>")
        assert any("<40 chars" in p for p in problems)


class TestPromptBuilders:
    def test_skeleton_prompt_contains_markers_verbatim(self):
        prompt = build_skeleton_prompt(
            page_prompt="A bakery site",
            site_plan_text="{}",
            sections=[("hero", "Hero section"), ("menu", "Menu grid")],
            style_spec_text='{"primary_color": "#fff"}',
            shared_components=["navbar"],
        )
        assert "<!-- @section:hero -->" in prompt
        assert "<!-- @section:menu -->" in prompt
        assert "A bakery site" in prompt
        assert "navbar" in prompt

    def test_section_prompt_contains_css_and_position(self):
        prompt = build_section_prompt(
            page_prompt="A bakery site",
            key="menu",
            description="Menu grid",
            index=2,
            total=3,
            style_spec_text="{}",
            css=":root{--p:red}",
            shared_components=["footer"],
        )
        assert "section 2 of 3" in prompt
        assert ":root{--p:red}" in prompt
        assert "Menu grid" in prompt

    def test_repair_prompt_lists_problems(self):
        prompt = build_repair_prompt(
            original_prompt="ORIGINAL", problems=["fragment is empty"], fragment="<bad>"
        )
        assert "ORIGINAL" in prompt
        assert "fragment is empty" in prompt
        assert "<bad>" in prompt


# ------------------------------------------------------------------
# Orchestration with fakes
# ------------------------------------------------------------------

SITE_PLAN = {
    "project_name": "Test Site",
    "tagline": "A test site",
    "pages": [
        {
            "slug": "home",
            "title": "Home",
            "sections": ["Hero with headline", "Features grid", "Contact call to action"],
        }
    ],
    "shared_components": ["navbar", "footer"],
    "required_agents": ["designer", "developer"],
}

STYLE_SPEC = {"primary_color": "#ff0000", "background_color": "#ffffff"}

LAYOUT_OUTPUT = """```html
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Home</title><link rel="stylesheet" href="styles.css"></head>
<body>
<!-- @section:hero -->
<!-- @section:features -->
<!-- @section:contact -->
</body>
</html>
```
```css
:root { --primary: #ff0000; }
section { padding: 2rem; }
```"""

VALID_FRAGMENTS = {
    "hero": "<section class=\"hero\"><h1>Welcome to the test site</h1><p>Real hero copy here.</p></section>",
    "features": "<section class=\"features\"><h2>Features</h2><p>Real feature copy here, long enough to validate.</p></section>",
    "contact": "<section class=\"contact\"><h2>Contact us</h2><p>Real contact copy here, long enough to validate.</p></section>",
}


def make_fake_run_agent(overrides: dict[str, list[str]] | None = None):
    """Build a fake _run_agent. ``overrides`` maps agent_key -> queued responses
    (each call pops the next response; the last one repeats)."""
    overrides = overrides or {}
    calls: dict[str, int] = {}

    async def fake(self, agent_key, system_prompt, user_prompt, model, deps=None):
        calls[agent_key] = calls.get(agent_key, 0) + 1
        if agent_key in overrides:
            queue = overrides[agent_key]
            return queue[min(calls[agent_key] - 1, len(queue) - 1)]
        if agent_key == "pm":
            return json.dumps(SITE_PLAN)
        if agent_key == "designer":
            return json.dumps(STYLE_SPEC)
        if agent_key == "layout":
            return LAYOUT_OUTPUT
        if agent_key.startswith("section:"):
            key = agent_key.split(":", 1)[1]
            return VALID_FRAGMENTS.get(key, f"<section><p>{key} content that is long enough.</p></section>")
        raise AssertionError(f"unexpected agent_key: {agent_key}")

    return fake, calls


def make_pipeline(project_manager, monkeypatch, overrides=None):
    events = []
    pipeline = ProgressivePipeline(project_manager, on_event=lambda e: events.append(e))
    fake, calls = make_fake_run_agent(overrides)
    monkeypatch.setattr(ProgressivePipeline, "_run_agent", fake)
    return pipeline, events, calls


class TestProgressiveOrchestration:
    @pytest.mark.asyncio
    async def test_full_build(self, project_manager, sample_project, monkeypatch):
        pipeline, events, _ = make_pipeline(project_manager, monkeypatch)
        await pipeline.generate(
            sample_project, slug="home", version_number=1, page_prompt="A test site"
        )

        # Files written to disk: all fragments spliced, markers gone.
        doc = project_manager.read_version_file(sample_project.id, "home", 1, "index.html")
        assert doc is not None
        for frag in VALID_FRAGMENTS.values():
            assert frag in doc
        assert "@section:" not in doc
        css = project_manager.read_version_file(sample_project.id, "home", 1, "styles.css")
        assert css is not None and "--primary" in css

        # Preview stream: skeleton + one update per section (+ final), each a
        # full document with a content hash.
        previews = [e for e in events if e.type == "preview_update"]
        assert len(previews) >= len(VALID_FRAGMENTS) + 1
        for e in previews:
            assert "<!DOCTYPE html>" in e.data["html"]
            assert e.data["content_hash"]
            assert e.data["page_slug"] == "home"
        hashes = {e.data["content_hash"] for e in previews}
        assert len(hashes) >= len(VALID_FRAGMENTS)  # each splice changes the doc

        # Lifecycle + completion events.
        complete = [e for e in events if e.type == "generation_complete"]
        assert len(complete) == 1
        assert complete[0].data["success"] is True
        assert "index.html" in complete[0].data["files"]
        assert "index.html" in complete[0].data["files_content"]

        section_events = [e for e in events if e.type == "section_complete"]
        assert {e.data["key"] for e in section_events} == set(VALID_FRAGMENTS)
        for e in section_events:
            assert e.data["attempts"] == 1
            assert e.data["fallback"] is False

        agent_starts = [e.agent for e in events if e.type == "agent_start"]
        assert "layout" in agent_starts
        assert "section:hero" in agent_starts

        # Contract surface for generation_runner.
        assert pipeline.style_spec_text
        assert json.loads(pipeline.style_spec_text) == STYLE_SPEC
        assert pipeline.agent_runs
        names = {r.agent_name for r in pipeline.agent_runs}
        assert {"pm", "designer", "layout", "section:hero"} <= names
        assert all(r.status == "completed" for r in pipeline.agent_runs)

    @pytest.mark.asyncio
    async def test_layout_missing_marker_is_repaired(self, project_manager, sample_project, monkeypatch):
        layout_without_contact = LAYOUT_OUTPUT.replace("<!-- @section:contact -->\n", "")
        pipeline, _, _ = make_pipeline(
            project_manager, monkeypatch, overrides={"layout": [layout_without_contact]}
        )
        await pipeline.generate(
            sample_project, slug="home", version_number=1, page_prompt="A test site"
        )
        doc = project_manager.read_version_file(sample_project.id, "home", 1, "index.html")
        assert VALID_FRAGMENTS["contact"] in doc
        assert "@section:" not in doc

    @pytest.mark.asyncio
    async def test_repair_path_retries_weak_section(self, project_manager, sample_project, monkeypatch):
        garbage = "I cannot produce this section right now, sorry."
        pipeline, events, calls = make_pipeline(
            project_manager, monkeypatch,
            overrides={"section:hero": [garbage, VALID_FRAGMENTS["hero"]]},
        )
        await pipeline.generate(
            sample_project, slug="home", version_number=1, page_prompt="A test site"
        )
        assert calls["section:hero"] == 2
        hero_events = [e for e in events if e.type == "section_complete" and e.data["key"] == "hero"]
        assert hero_events[0].data["attempts"] == 2
        assert hero_events[0].data["fallback"] is False
        doc = project_manager.read_version_file(sample_project.id, "home", 1, "index.html")
        assert VALID_FRAGMENTS["hero"] in doc

    @pytest.mark.asyncio
    async def test_permanently_failing_section_uses_fallback(self, project_manager, sample_project, monkeypatch):
        pipeline, events, _ = make_pipeline(
            project_manager, monkeypatch,
            overrides={"section:features": ["garbage with no markup", "still no markup here"]},
        )
        await pipeline.generate(
            sample_project, slug="home", version_number=1, page_prompt="A test site"
        )
        feat_events = [e for e in events if e.type == "section_complete" and e.data["key"] == "features"]
        assert feat_events[0].data["fallback"] is True
        assert feat_events[0].data["attempts"] == 2

        doc = project_manager.read_version_file(sample_project.id, "home", 1, "index.html")
        assert "<h2>Features grid</h2>" in doc  # fallback fragment spliced
        assert "@section:" not in doc

        # Build still succeeds.
        complete = [e for e in events if e.type == "generation_complete"]
        assert complete[0].data["success"] is True

    @pytest.mark.asyncio
    async def test_unparseable_pm_output_falls_back_to_default_sections(
        self, project_manager, sample_project, monkeypatch
    ):
        # PM returns junk and structured extraction finds nothing → the pipeline
        # must synthesize a default outline instead of failing the run.
        default_layout = """```html
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Home</title><link rel="stylesheet" href="styles.css"></head>
<body>
<!-- @section:hero -->
<!-- @section:key -->
<!-- @section:call -->
<!-- @section:footer -->
</body>
</html>
```
```css
:root { --primary: #ff0000; }
```"""
        pipeline, events, _ = make_pipeline(
            project_manager, monkeypatch,
            overrides={"pm": ["not json at all"], "layout": [default_layout]},
        )

        async def no_extract(*args, **kwargs):
            return None

        monkeypatch.setattr("agentsite.engine.extract.extract_structured", no_extract)
        await pipeline.generate(
            sample_project, slug="home", version_number=1, page_prompt="A test site"
        )
        complete = [e for e in events if e.type == "generation_complete"]
        assert complete[0].data["success"] is True
        doc = project_manager.read_version_file(sample_project.id, "home", 1, "index.html")
        assert doc is not None
        assert "@section:" not in doc


# ------------------------------------------------------------------
# Dispatch (API → generation_runner picks the right pipeline)
# ------------------------------------------------------------------


@pytest.fixture
async def client(tmp_path):
    deps.db = Database(db_path=tmp_path / "test.db")
    deps.project_manager = ProjectManager(base_dir=tmp_path / "projects")
    deps.asset_handler = deps.AssetHandler(deps.project_manager)

    await deps.db.connect()
    deps.project_repo = ProjectRepository(deps.db)
    deps.page_repo = PageRepository(deps.db)
    deps.version_repo = VersionRepository(deps.db)
    deps.agent_config_repo = AgentConfigRepository(deps.db)
    deps.agent_run_repo = AgentRunRepository(deps.db)

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    await deps.db.close()


class FakePipelineBase:
    instances: ClassVar[list] = []

    def __init__(self, *args, **kwargs):
        type(self).instances.append(self)
        self.style_spec_text = ""
        self.agent_runs = []

    async def generate(self, *args, **kwargs):
        return SimpleNamespace(aggregate_usage={}, success=True)


class TestDispatch:
    @pytest.mark.asyncio
    async def test_progressive_strategy_selects_progressive_pipeline(self, client, monkeypatch):
        import agentsite.engine.generation_runner as runner

        class FakeProgressive(FakePipelineBase):
            instances: ClassVar[list] = []

        class FakeStandard(FakePipelineBase):
            instances: ClassVar[list] = []

        monkeypatch.setattr(runner, "ProgressivePipeline", FakeProgressive)
        monkeypatch.setattr(runner, "GenerationPipeline", FakeStandard)

        resp = await client.post("/api/projects", json={"name": "T", "description": "d"})
        project_id = resp.json()["id"]

        resp = await client.post(
            f"/api/projects/{project_id}/pages/home/generate",
            json={"prompt": "build it", "strategy": "progressive"},
        )
        assert resp.status_code == 200
        assert len(FakeProgressive.instances) == 1
        assert len(FakeStandard.instances) == 0
        await asyncio.sleep(0.05)  # let the background _run() task settle

    @pytest.mark.asyncio
    async def test_default_strategy_selects_generation_pipeline(self, client, monkeypatch):
        import agentsite.engine.generation_runner as runner

        class FakeProgressive(FakePipelineBase):
            instances: ClassVar[list] = []

        class FakeStandard(FakePipelineBase):
            instances: ClassVar[list] = []

        monkeypatch.setattr(runner, "ProgressivePipeline", FakeProgressive)
        monkeypatch.setattr(runner, "GenerationPipeline", FakeStandard)

        resp = await client.post("/api/projects", json={"name": "T", "description": "d"})
        project_id = resp.json()["id"]

        resp = await client.post(
            f"/api/projects/{project_id}/pages/home/generate",
            json={"prompt": "build it"},
        )
        assert resp.status_code == 200
        assert len(FakeStandard.instances) == 1
        assert len(FakeProgressive.instances) == 0
        await asyncio.sleep(0.05)  # let the background _run() task settle
