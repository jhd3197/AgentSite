"""Phase 5: per-page layout overrides.

Covers the ``effective_style_spec`` merge helper, the ``layout_overrides``
DB column migration + repository round-trip, the PATCH page endpoint, and
effective-spec delivery in all three pipelines (mockup / progressive /
project) with faked agents — no LLM calls.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import ClassVar

import aiosqlite
import pytest
from httpx import ASGITransport, AsyncClient
from prompture import GroupResult

from agentsite.api import deps
from agentsite.api.app import create_app
from agentsite.engine.project_manager import ProjectManager
from agentsite.models import Page, Project, StyleSpec, _deep_merge, effective_style_spec
from agentsite.storage.database import Database
from agentsite.storage.repository import (
    AgentConfigRepository,
    AgentRunRepository,
    PageRepository,
    ProjectComponentRepository,
    ProjectRepository,
    VersionRepository,
)

# ------------------------------------------------------------------
# Merge helper
# ------------------------------------------------------------------


class TestDeepMerge:
    def test_scalar_replace(self):
        assert _deep_merge({"a": 1, "b": 2}, {"b": 3}) == {"a": 1, "b": 3}

    def test_nested_dict_merge(self):
        base = {"layout": {"nav": "top", "width": "1200px"}, "color": "red"}
        out = _deep_merge(base, {"layout": {"width": "800px"}})
        assert out == {"layout": {"nav": "top", "width": "800px"}, "color": "red"}

    def test_dict_replaced_by_scalar(self):
        assert _deep_merge({"a": {"x": 1}}, {"a": "flat"}) == {"a": "flat"}

    def test_base_not_mutated(self):
        base = {"a": {"x": 1}}
        _deep_merge(base, {"a": {"y": 2}})
        assert base == {"a": {"x": 1}}


class TestEffectiveStyleSpec:
    def test_no_overrides_returns_project_spec(self):
        spec = StyleSpec(layout_style="sidebar", max_width="900px")
        assert effective_style_spec(spec, None) is spec
        assert effective_style_spec(spec, {}) is spec

    def test_unset_fields_inherit(self):
        spec = StyleSpec(layout_style="top-nav", max_width="1200px")
        merged = effective_style_spec(spec, {"layout_style": "centered"})
        assert merged.layout_style == "centered"
        assert merged.max_width == "1200px"  # inherited
        assert merged.primary_color == spec.primary_color  # inherited

    def test_none_values_inherit(self):
        spec = StyleSpec(nav_position="fixed")
        merged = effective_style_spec(spec, {"nav_position": None, "footer_style": "none"})
        assert merged.nav_position == "fixed"
        assert merged.footer_style == "none"

    def test_unknown_keys_ignored(self):
        spec = StyleSpec()
        merged = effective_style_spec(spec, {"not_a_field": "x", "layout_style": "minimal"})
        assert merged.layout_style == "minimal"
        assert not hasattr(merged, "not_a_field")

    def test_project_spec_not_mutated(self):
        spec = StyleSpec(layout_style="top-nav")
        effective_style_spec(spec, {"layout_style": "sidebar"})
        assert spec.layout_style == "top-nav"

    def test_invalid_value_rejected(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            effective_style_spec(StyleSpec(), {"max_width": 123})


# ------------------------------------------------------------------
# Migration + repository
# ------------------------------------------------------------------


class TestMigration:
    @pytest.mark.asyncio
    async def test_fresh_db_has_column(self, tmp_path):
        db = Database(db_path=tmp_path / "fresh.db")
        await db.connect()
        cursor = await db.conn.execute("PRAGMA table_info(pages)")
        cols = {row[1] for row in await cursor.fetchall()}
        assert "layout_overrides" in cols
        await db.close()

    @pytest.mark.asyncio
    async def test_migration_adds_column_to_old_db(self, tmp_path):
        """A pre-Phase-5 pages table gains the column without losing data."""
        db_path = tmp_path / "old.db"
        conn = await aiosqlite.connect(str(db_path))
        await conn.execute(
            """CREATE TABLE projects (
                id TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '', model TEXT NOT NULL DEFAULT '',
                style_spec TEXT, agent_overrides TEXT, user_id TEXT,
                mode TEXT NOT NULL DEFAULT 'mockup', template_id TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"""
        )
        await conn.execute(
            """CREATE TABLE pages (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL, slug TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '', prompt TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"""
        )
        await conn.execute(
            "INSERT INTO pages VALUES ('p1', 'proj1', 'home', 'Home', '', '2024', '2024')"
        )
        await conn.commit()
        await conn.close()

        db = Database(db_path=db_path)
        await db.connect()
        cursor = await db.conn.execute("PRAGMA table_info(pages)")
        cols = {row[1] for row in await cursor.fetchall()}
        assert "layout_overrides" in cols

        page = await PageRepository(db).get("p1")
        assert page is not None
        assert page.slug == "home"
        assert page.layout_overrides is None
        await db.close()


class TestPageRepositoryOverrides:
    @pytest.fixture
    async def repos(self, tmp_path):
        db = Database(db_path=tmp_path / "test.db")
        await db.connect()
        yield ProjectRepository(db), PageRepository(db)
        await db.close()

    @pytest.mark.asyncio
    async def test_round_trip(self, repos):
        project_repo, page_repo = repos
        project = Project(name="T")
        await project_repo.create(project)

        page = Page(
            project_id=project.id, slug="home",
            layout_overrides={"layout_style": "centered", "max_width": "720px"},
        )
        await page_repo.create(page)

        loaded = await page_repo.get_by_slug(project.id, "home")
        assert loaded.layout_overrides == {"layout_style": "centered", "max_width": "720px"}

    @pytest.mark.asyncio
    async def test_update_and_clear(self, repos):
        project_repo, page_repo = repos
        project = Project(name="T")
        await project_repo.create(project)
        page = Page(project_id=project.id, slug="home")
        await page_repo.create(page)

        page.layout_overrides = {"section_gap": "8rem"}
        await page_repo.update(page)
        assert (await page_repo.get(page.id)).layout_overrides == {"section_gap": "8rem"}

        page.layout_overrides = None
        await page_repo.update(page)
        assert (await page_repo.get(page.id)).layout_overrides is None


# ------------------------------------------------------------------
# PATCH endpoint
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
    deps.project_component_repo = ProjectComponentRepository(deps.db)

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    await deps.db.close()


async def _project_with_page(client, slug="home"):
    resp = await client.post("/api/projects", json={"name": "LO Test"})
    project_id = resp.json()["id"]
    await client.post(f"/api/projects/{project_id}/pages", json={"slug": slug})
    return project_id


class TestPatchPage:
    @pytest.mark.asyncio
    async def test_set_overrides(self, client):
        project_id = await _project_with_page(client)
        resp = await client.patch(
            f"/api/projects/{project_id}/pages/home",
            json={"layout_overrides": {"layout_style": "sidebar", "section_gap": "6rem"}},
        )
        assert resp.status_code == 200
        assert resp.json()["layout_overrides"] == {
            "layout_style": "sidebar",
            "section_gap": "6rem",
        }

        # Persisted — included in page responses
        resp = await client.get(f"/api/projects/{project_id}/pages/home")
        assert resp.json()["layout_overrides"]["layout_style"] == "sidebar"

    @pytest.mark.asyncio
    async def test_title_prompt_update_preserves_overrides(self, client):
        project_id = await _project_with_page(client)
        await client.patch(
            f"/api/projects/{project_id}/pages/home",
            json={"layout_overrides": {"layout_style": "minimal"}},
        )
        resp = await client.patch(
            f"/api/projects/{project_id}/pages/home",
            json={"title": "Landing", "prompt": "build it"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Landing"
        assert data["prompt"] == "build it"
        assert data["layout_overrides"] == {"layout_style": "minimal"}

    @pytest.mark.asyncio
    async def test_clear_with_null_and_empty_dict(self, client):
        project_id = await _project_with_page(client)
        await client.patch(
            f"/api/projects/{project_id}/pages/home",
            json={"layout_overrides": {"layout_style": "minimal"}},
        )
        resp = await client.patch(
            f"/api/projects/{project_id}/pages/home", json={"layout_overrides": None}
        )
        assert resp.json()["layout_overrides"] is None

        await client.patch(
            f"/api/projects/{project_id}/pages/home",
            json={"layout_overrides": {"max_width": "640px"}},
        )
        resp = await client.patch(
            f"/api/projects/{project_id}/pages/home", json={"layout_overrides": {}}
        )
        assert resp.json()["layout_overrides"] is None

    @pytest.mark.asyncio
    async def test_unknown_key_rejected_422(self, client):
        project_id = await _project_with_page(client)
        resp = await client.patch(
            f"/api/projects/{project_id}/pages/home",
            json={"layout_overrides": {"banana": "yellow"}},
        )
        assert resp.status_code == 422
        assert "banana" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_invalid_value_rejected_422(self, client):
        project_id = await _project_with_page(client)
        resp = await client.patch(
            f"/api/projects/{project_id}/pages/home",
            json={"layout_overrides": {"max_width": 123}},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_patch_missing_page_404(self, client):
        project_id = await _project_with_page(client)
        resp = await client.patch(
            f"/api/projects/{project_id}/pages/nope", json={"title": "x"}
        )
        assert resp.status_code == 404


# ------------------------------------------------------------------
# generation_runner hands the page's overrides to the pipeline
# ------------------------------------------------------------------


class TestGenerationRunnerDispatch:
    @pytest.mark.asyncio
    async def test_overrides_reach_pipeline_generate(self, client, monkeypatch):
        import agentsite.engine.generation_runner as runner

        class FakePipeline:
            instances: ClassVar[list] = []

            def __init__(self, *args, **kwargs):
                type(self).instances.append(self)
                self.style_spec_text = ""
                self.agent_runs = []
                self.generate_kwargs = None

            async def generate(self, *args, **kwargs):
                self.generate_kwargs = kwargs
                return SimpleNamespace(aggregate_usage={}, success=True)

        monkeypatch.setattr(runner, "GenerationPipeline", FakePipeline)

        project_id = await _project_with_page(client)
        await client.patch(
            f"/api/projects/{project_id}/pages/home",
            json={"layout_overrides": {"layout_style": "centered"}},
        )
        resp = await client.post(
            f"/api/projects/{project_id}/pages/home/generate",
            json={"prompt": "build it"},
        )
        assert resp.status_code == 200
        await asyncio.sleep(0.05)  # let the background _run() task settle

        assert len(FakePipeline.instances) == 1
        assert FakePipeline.instances[0].generate_kwargs["layout_overrides"] == {
            "layout_style": "centered"
        }

    @pytest.mark.asyncio
    async def test_no_overrides_passes_none(self, client, monkeypatch):
        import agentsite.engine.generation_runner as runner

        class FakePipeline:
            instances: ClassVar[list] = []

            def __init__(self, *args, **kwargs):
                type(self).instances.append(self)
                self.style_spec_text = ""
                self.agent_runs = []
                self.generate_kwargs = None

            async def generate(self, *args, **kwargs):
                self.generate_kwargs = kwargs
                return SimpleNamespace(aggregate_usage={}, success=True)

        monkeypatch.setattr(runner, "GenerationPipeline", FakePipeline)

        project_id = await _project_with_page(client)
        resp = await client.post(
            f"/api/projects/{project_id}/pages/home/generate",
            json={"prompt": "build it"},
        )
        assert resp.status_code == 200
        await asyncio.sleep(0.05)
        assert FakePipeline.instances[0].generate_kwargs["layout_overrides"] is None


# ------------------------------------------------------------------
# Mockup pipeline — effective spec lands in the build agents' state
# ------------------------------------------------------------------

SITE_PLAN_JSON = json.dumps({
    "project_name": "Mock",
    "tagline": "t",
    "pages": [{"slug": "home", "title": "Home", "sections": ["hero"]}],
    "required_agents": ["developer", "reviewer"],  # no designer → fallback spec path
})


class _FakePlanner:
    """Stands in for PM/Designer/plain-Developer factory agents."""

    def __init__(self, name: str, output: str, output_key: str | None = None):
        self.name = name
        self.output_key = output_key
        self._output = output
        self.callbacks = None
        self.options: dict = {}

    async def run(self, prompt, deps=None, **kwargs):
        return SimpleNamespace(
            output_text=self._output, run_usage={}, all_tool_calls=[], messages=[]
        )


class _StateCapturingGroup:
    """Captures the state injected into the build pipeline."""

    instances: ClassVar[list] = []

    def __init__(self):
        self._state: dict = {}
        type(self).instances.append(self)

    def inject_state(self, state, recursive: bool = False):
        self._state.update(state)

    @property
    def shared_state(self):
        return dict(self._state)

    async def run(self, prompt=""):
        return GroupResult(
            agent_results=[], aggregate_usage={}, shared_state=dict(self._state),
            elapsed_ms=0, timeline=[], errors=[], success=True,
        )


class TestMockupPipelineOverrides:
    @pytest.mark.asyncio
    async def test_effective_spec_in_build_state(self, tmp_path, monkeypatch):
        import agentsite.agents.designer as designer_mod
        import agentsite.agents.developer as developer_mod
        import agentsite.agents.pm as pm_mod
        import agentsite.engine.pipeline as pipeline_mod
        from agentsite.config import settings
        from agentsite.engine.pipeline import GenerationPipeline

        _StateCapturingGroup.instances = []
        pm_mgr = ProjectManager(base_dir=tmp_path / "projects")
        project = Project(name="Mockup", style_spec=StyleSpec(layout_style="top-nav"))
        pm_mgr.create(project)

        monkeypatch.setattr(settings, "verify_enabled", False)
        monkeypatch.setattr(
            pm_mod, "create_pm_agent_auto",
            lambda m: _FakePlanner("agentsite_pm", SITE_PLAN_JSON, "site_plan"),
        )
        monkeypatch.setattr(
            designer_mod, "create_designer_agent_auto",
            lambda m: _FakePlanner(
                "agentsite_designer",
                StyleSpec(layout_style="top-nav", max_width="1200px").model_dump_json(),
                "style_spec",
            ),
        )
        monkeypatch.setattr(
            developer_mod, "create_developer_agent_plain",
            lambda m: _FakePlanner(
                "agentsite_developer",
                "```html\n<!DOCTYPE html><html><body>layout override test page with "
                "enough text to look real</body></html>\n```",
            ),
        )
        monkeypatch.setattr(
            pipeline_mod, "create_dynamic_pipeline", lambda *a, **k: _StateCapturingGroup()
        )

        pipeline = GenerationPipeline(pm_mgr)
        result = await pipeline.generate(
            project,
            slug="home",
            version_number=1,
            page_prompt="build a landing page",
            layout_overrides={"layout_style": "centered"},
        )

        assert result.success
        state = _StateCapturingGroup.instances[0]._state
        spec = json.loads(state["style_spec"])
        assert spec["layout_style"] == "centered"  # override applied
        assert spec["max_width"] == "1200px"  # inherited
        # The project spec itself is untouched
        assert project.style_spec.layout_style == "top-nav"

    @pytest.mark.asyncio
    async def test_no_overrides_keeps_project_spec(self, tmp_path, monkeypatch):
        import agentsite.agents.designer as designer_mod
        import agentsite.agents.developer as developer_mod
        import agentsite.agents.pm as pm_mod
        import agentsite.engine.pipeline as pipeline_mod
        from agentsite.config import settings
        from agentsite.engine.pipeline import GenerationPipeline

        _StateCapturingGroup.instances = []
        pm_mgr = ProjectManager(base_dir=tmp_path / "projects")
        project = Project(name="Mockup", style_spec=StyleSpec(layout_style="top-nav"))
        pm_mgr.create(project)

        monkeypatch.setattr(settings, "verify_enabled", False)
        monkeypatch.setattr(
            pm_mod, "create_pm_agent_auto",
            lambda m: _FakePlanner("agentsite_pm", SITE_PLAN_JSON, "site_plan"),
        )
        monkeypatch.setattr(
            designer_mod, "create_designer_agent_auto",
            lambda m: _FakePlanner(
                "agentsite_designer", StyleSpec(layout_style="top-nav").model_dump_json(),
                "style_spec",
            ),
        )
        monkeypatch.setattr(
            developer_mod, "create_developer_agent_plain",
            lambda m: _FakePlanner(
                "agentsite_developer",
                "```html\n<!DOCTYPE html><html><body>plain page with enough text "
                "to be considered real content</body></html>\n```",
            ),
        )
        monkeypatch.setattr(
            pipeline_mod, "create_dynamic_pipeline", lambda *a, **k: _StateCapturingGroup()
        )

        pipeline = GenerationPipeline(pm_mgr)
        result = await pipeline.generate(
            project, slug="home", version_number=1, page_prompt="build",
        )

        assert result.success
        state = _StateCapturingGroup.instances[0]._state
        assert json.loads(state["style_spec"])["layout_style"] == "top-nav"


# ------------------------------------------------------------------
# Progressive pipeline — effective spec lands in layout/section briefs
# ------------------------------------------------------------------

PROG_SITE_PLAN = {
    "project_name": "Test Site",
    "tagline": "A test site",
    "pages": [
        {"slug": "home", "title": "Home", "sections": ["Hero with headline"]}
    ],
    "shared_components": [],
    "required_agents": ["designer", "developer"],
}

PROG_STYLE_SPEC = {"primary_color": "#ff0000", "layout_style": "top-nav"}

PROG_LAYOUT_OUTPUT = """```html
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Home</title><link rel="stylesheet" href="styles.css"></head>
<body>
<!-- @section:hero -->
</body>
</html>
```
```css
:root { --primary: #ff0000; }
```"""

PROG_FRAGMENT = (
    '<section class="hero"><h1>Welcome</h1>'
    "<p>Real hero copy here, long enough to validate cleanly.</p></section>"
)


class TestProgressivePipelineOverrides:
    @pytest.mark.asyncio
    async def test_layout_brief_uses_effective_spec(
        self, project_manager, sample_project, monkeypatch
    ):
        from agentsite.engine.progressive import ProgressivePipeline

        prompts: dict[str, str] = {}

        async def fake_run_agent(self, agent_key, system_prompt, user_prompt, model, deps=None, tools=None):
            prompts[agent_key] = user_prompt
            if agent_key == "pm":
                return json.dumps(PROG_SITE_PLAN)
            if agent_key == "designer":
                return json.dumps(PROG_STYLE_SPEC)
            if agent_key == "layout":
                return PROG_LAYOUT_OUTPUT
            if agent_key.startswith("section:"):
                return PROG_FRAGMENT
            raise AssertionError(f"unexpected agent_key: {agent_key}")

        monkeypatch.setattr(ProgressivePipeline, "_run_agent", fake_run_agent)

        sample_project.style_spec = StyleSpec(layout_style="top-nav")
        pipeline = ProgressivePipeline(project_manager)
        await pipeline.generate(
            sample_project,
            slug="home",
            version_number=1,
            page_prompt="A test site",
            layout_overrides={"layout_style": "sidebar", "section_gap": "8rem"},
        )

        # Layout + section briefs carry the effective spec
        decoder = json.JSONDecoder()
        layout_spec, _ = decoder.raw_decode(
            prompts["layout"].split("## Style spec (implement fully in the css block)")[1].strip()
        )
        assert layout_spec["layout_style"] == "sidebar"
        assert layout_spec["section_gap"] == "8rem"
        assert layout_spec["primary_color"] == "#ff0000"  # inherited from designer output
        section_spec, _ = decoder.raw_decode(
            prompts["section:hero"].split("## Style spec")[1].strip()
        )
        assert section_spec["layout_style"] == "sidebar"

        # The raw designer output (persisted project-wide) stays untouched
        assert json.loads(pipeline.style_spec_text) == PROG_STYLE_SPEC


# ------------------------------------------------------------------
# Project pipeline — effective spec in tokens file + dev brief
# ------------------------------------------------------------------


class _FakeDevOrReviewer:
    instances: ClassVar[list] = []

    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs
        self.name = kwargs.get("name", "")
        self.callbacks = None
        self.options = kwargs.get("options", {})
        type(self).instances.append(self)

    async def run(self, prompt: str, deps=None, **kwargs):
        if "developer" in self.name:
            self.last_prompt = prompt
            from agentsite.agents.workspace_tools import write_file

            ctx = SimpleNamespace(deps=deps)
            write_file(ctx, "about.html", "<!DOCTYPE html><html><body>About</body></html>")
            return SimpleNamespace(
                output_text="Built.", usage={"input_tokens": 1, "output_tokens": 1, "cost": 0.0},
                all_tool_calls=[], messages=[],
            )
        from agentsite.models import ReviewFeedback

        return SimpleNamespace(
            output_text=ReviewFeedback(issues=[], suggestions=[], score=9, approved=True).model_dump_json(),
            usage={"input_tokens": 1, "output_tokens": 1, "cost": 0.0},
            all_tool_calls=[], messages=[],
        )


class TestProjectPipelineOverrides:
    @pytest.mark.asyncio
    async def test_tokens_and_brief_use_effective_spec(self, tmp_path, monkeypatch):
        import agentsite.agents.designer as designer_mod
        import agentsite.agents.pm as pm_mod
        import agentsite.engine.capabilities as caps_mod
        import agentsite.engine.project_pipeline as pp_mod
        from agentsite.engine.project_pipeline import ProjectGenerationPipeline
        from agentsite.engine.verifier import RouteCheck, VerifyReport
        from agentsite.engine.workspace import WorkspaceManager
        from agentsite.models import SitePlan
        from agentsite.templates import find_template

        _FakeDevOrReviewer.instances = []
        pm_mgr = ProjectManager(base_dir=tmp_path / "projects")
        project = Project(name="E2E", mode="project", template_id="static-multipage")
        pm_mgr.create(project)
        WorkspaceManager(pm_mgr.project_dir(project.id)).scaffold(find_template("static-multipage"))

        site_plan = SitePlan(
            project_name="Test Site", tagline="Testing",
            pages=[{"slug": "index", "title": "Home", "sections": ["hero"]}],
        )
        monkeypatch.setattr(
            pm_mod, "create_pm_agent_auto",
            lambda model: _FakePlanner("agentsite_pm", site_plan.model_dump_json()),
        )
        monkeypatch.setattr(
            designer_mod, "create_designer_agent_auto",
            lambda model: _FakePlanner(
                "agentsite_designer", StyleSpec(primary_color="#123456").model_dump_json()
            ),
        )
        monkeypatch.setattr(caps_mod, "supports_tools", lambda model: True)
        monkeypatch.setattr(caps_mod, "supports_vision", lambda model: False)
        monkeypatch.setattr(pp_mod, "AsyncAgent", _FakeDevOrReviewer)

        async def _fake_verify(*args, **kwargs):
            return VerifyReport(
                ok=True,
                routes=[RouteCheck(route="index.html", ok=True, content_chars=500, console_errors=[])],
                summary="stubbed",
            )

        monkeypatch.setattr(pp_mod.verifier, "run_verification", _fake_verify)

        pipeline = ProjectGenerationPipeline(pm_mgr)
        result = await pipeline.generate(
            project,
            slug="home",
            version_number=1,
            page_prompt="Build a test site",
            layout_overrides={"max_width": "800px", "layout_style": "centered"},
        )
        await asyncio.sleep(0.05)

        assert result.success is True

        # Tokens file rendered from the effective spec
        ws = WorkspaceManager(pm_mgr.project_dir(project.id))
        tokens = ws.read_file("styles/tokens.css")
        assert "--max-width: 800px;" in tokens
        assert "--color-primary: #123456;" in tokens  # designer values intact

        # Dev brief mentions the overrides
        dev = next(a for a in _FakeDevOrReviewer.instances if "developer" in a.name)
        assert "Page layout overrides" in dev.last_prompt
        assert "max_width: 800px" in dev.last_prompt

        # Raw designer output (persisted project-wide) has no override leakage
        assert "800px" not in pipeline.style_spec_text
        assert json.loads(pipeline.style_spec_text)["max_width"] == "1200px"
