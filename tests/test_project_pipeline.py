"""Orchestration test for ProjectGenerationPipeline with faked agents.

No LLM calls: the PM/Designer factories and AsyncAgent are monkeypatched so
the test exercises the real flow — scaffold reuse, token rendering, the dev
session writing through workspace tools, the review gate, WS event sequence,
checkpoints, and final capture.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agentsite.engine.project_manager import ProjectManager
from agentsite.engine.project_pipeline import ProjectGenerationPipeline
from agentsite.engine.workspace import WorkspaceManager
from agentsite.models import Project, ReviewFeedback, SitePlan, StyleSpec
from agentsite.templates import find_template

SITE_PLAN = SitePlan(
    project_name="Test Site",
    tagline="Testing",
    pages=[{"slug": "index", "title": "Home", "sections": ["hero"]}],
)


def _result(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        output_text=text,
        usage={"input_tokens": 10, "output_tokens": 20, "cost": 0.001},
        all_tool_calls=[],
        messages=[],
    )


class FakePlannerAgent:
    """Stands in for the PM/Designer factory agents."""

    def __init__(self, name: str, output: str):
        self.name = name
        self._output = output
        self.callbacks = None
        self.options: dict = {}

    async def run(self, prompt: str, deps=None, **kwargs):
        return _result(self._output)


class FakeDevOrReviewer:
    """Stands in for AsyncAgent — behavior keyed off the `name` kwarg."""

    instances = []  # noqa: RUF012 — reset per test; subclass-aware via type(self)

    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs
        self.name = kwargs.get("name", "")
        self.callbacks = None
        self.options = kwargs.get("options", {})
        self.run_count = 0
        type(self).instances.append(self)  # subclass-aware

    async def run(self, prompt: str, deps=None, **kwargs):
        self.run_count += 1
        if "developer" in self.name:
            # Write a real file through the real workspace tool
            from agentsite.agents.workspace_tools import write_file

            ctx = SimpleNamespace(deps=deps)
            write_file(ctx, "about.html", "<!DOCTYPE html><html><body>About</body></html>")
            return _result("Built the site.")
        # Reviewer: approve
        feedback = ReviewFeedback(issues=[], suggestions=[], score=9, approved=True)
        return _result(feedback.model_dump_json())


@pytest.mark.asyncio
async def test_project_pipeline_end_to_end(tmp_path, monkeypatch):
    FakeDevOrReviewer.instances = []

    pm_mgr = ProjectManager(base_dir=tmp_path / "projects")
    project = Project(name="E2E", mode="project", template_id="static-multipage")
    pm_mgr.create(project)
    WorkspaceManager(pm_mgr.project_dir(project.id)).scaffold(find_template("static-multipage"))

    # -- fakes ----------------------------------------------------------
    import agentsite.agents.designer as designer_mod
    import agentsite.agents.pm as pm_mod
    import agentsite.engine.capabilities as caps_mod
    import agentsite.engine.project_pipeline as pp_mod

    monkeypatch.setattr(
        pm_mod, "create_pm_agent_auto",
        lambda model: FakePlannerAgent("agentsite_pm", SITE_PLAN.model_dump_json()),
    )
    monkeypatch.setattr(
        designer_mod, "create_designer_agent_auto",
        lambda model: FakePlannerAgent("agentsite_designer", StyleSpec(primary_color="#123456").model_dump_json()),
    )
    monkeypatch.setattr(caps_mod, "supports_tools", lambda model: True)
    monkeypatch.setattr(pp_mod, "AsyncAgent", FakeDevOrReviewer)

    events = []

    def on_event(evt):
        events.append(evt)

    pipeline = ProjectGenerationPipeline(pm_mgr, on_event=on_event)
    result = await pipeline.generate(
        project,
        slug="home",
        version_number=1,
        page_prompt="Build a test site",
    )
    # Flush fire-and-forget event tasks (file_written, checkpoint_created)
    import asyncio

    await asyncio.sleep(0.05)

    # -- pipeline result --------------------------------------------------
    assert result.success is True
    assert result.aggregate_usage["input_tokens"] > 0
    assert result.aggregate_usage["cost"] > 0

    # -- the dev session wrote into the workspace -------------------------
    ws = WorkspaceManager(pm_mgr.project_dir(project.id))
    assert "about.html" in ws.list_files()

    # -- designer tokens were rendered into the template's tokens file ----
    tokens = ws.read_file("styles/tokens.css")
    assert "--color-primary: #123456;" in tokens

    # -- event sequence ----------------------------------------------------
    types = [e.type for e in events]
    for expected in (
        "phase_start", "pipeline_plan", "agent_start", "agent_complete",
        "site_plan_ready", "style_spec_ready", "file_written",
        "preview_ready", "review_feedback", "generation_complete",
    ):
        assert expected in types, f"missing WS event: {expected}"

    completes = [e for e in events if e.type == "generation_complete"]
    assert completes[-1].data["success"] is True
    assert "about.html" in completes[-1].data["files"]
    assert completes[-1].data["approved"] is True

    # -- one persistent dev session, one reviewer; approved on cycle 1 ----
    dev_agents = [a for a in FakeDevOrReviewer.instances if "developer" in a.name]
    reviewer_agents = [a for a in FakeDevOrReviewer.instances if "reviewer" in a.name]
    assert len(dev_agents) == 1, "developer must be ONE persistent session"
    assert dev_agents[0].run_count == 1
    assert dev_agents[0].kwargs.get("persistent_conversation") is True
    assert len(reviewer_agents) == 1

    # -- agent runs recorded for analytics --------------------------------
    run_names = [r.agent_name for r in pipeline.agent_runs]
    assert run_names == ["pm", "designer", "developer", "reviewer"]
    assert all(r.status == "completed" for r in pipeline.agent_runs)

    # -- git checkpoints (when git is available) ---------------------------
    if ws.git_available:
        messages = " | ".join(c["message"] for c in ws.list_checkpoints())
        assert "design tokens" in messages
        assert "cycle 1" in messages


@pytest.mark.asyncio
async def test_project_pipeline_rejects_non_tool_model(tmp_path, monkeypatch):
    import agentsite.engine.capabilities as caps_mod

    pm_mgr = ProjectManager(base_dir=tmp_path / "projects")
    project = Project(name="NoTools", mode="project", template_id="static-multipage")
    pm_mgr.create(project)
    WorkspaceManager(pm_mgr.project_dir(project.id)).scaffold(find_template("static-multipage"))

    monkeypatch.setattr(caps_mod, "supports_tools", lambda model: False)

    events = []
    pipeline = ProjectGenerationPipeline(pm_mgr, on_event=events.append)
    with pytest.raises(ValueError, match="tool-capable"):
        await pipeline.generate(
            project, slug="home", version_number=1, page_prompt="x",
        )
    # failure surfaced over WS too
    assert any(e.type == "error" for e in events)
    completes = [e for e in events if e.type == "generation_complete"]
    assert completes and completes[-1].data["success"] is False


@pytest.mark.asyncio
async def test_review_loop_feeds_back_into_same_session(tmp_path, monkeypatch):
    """Reviewer rejects once -> the SAME dev session runs again with feedback."""
    FakeDevOrReviewer.instances = []

    pm_mgr = ProjectManager(base_dir=tmp_path / "projects")
    project = Project(name="Loop", mode="project", template_id="static-multipage")
    pm_mgr.create(project)
    WorkspaceManager(pm_mgr.project_dir(project.id)).scaffold(find_template("static-multipage"))

    import agentsite.agents.designer as designer_mod
    import agentsite.agents.pm as pm_mod
    import agentsite.engine.capabilities as caps_mod
    import agentsite.engine.project_pipeline as pp_mod

    monkeypatch.setattr(
        pm_mod, "create_pm_agent_auto",
        lambda model: FakePlannerAgent("agentsite_pm", SITE_PLAN.model_dump_json()),
    )
    monkeypatch.setattr(
        designer_mod, "create_designer_agent_auto",
        lambda model: FakePlannerAgent("agentsite_designer", StyleSpec().model_dump_json()),
    )
    monkeypatch.setattr(caps_mod, "supports_tools", lambda model: True)

    review_scores = iter([4, 9])  # reject, then approve

    class LoopFake(FakeDevOrReviewer):
        async def run(self, prompt: str, deps=None, **kwargs):
            self.run_count += 1
            if "developer" in self.name:
                self.last_prompt = prompt
                return _result("done")
            score = next(review_scores)
            fb = ReviewFeedback(
                issues=["Hero section missing"] if score < 7 else [],
                score=score,
                approved=score >= 7,
            )
            return _result(fb.model_dump_json())

    LoopFake.instances = []
    monkeypatch.setattr(pp_mod, "AsyncAgent", LoopFake)

    pipeline = ProjectGenerationPipeline(pm_mgr, on_event=lambda e: None)
    result = await pipeline.generate(
        project, slug="home", version_number=1, page_prompt="x",
    )

    assert result.success is True
    dev_agents = [a for a in LoopFake.instances if "developer" in a.name]
    assert len(dev_agents) == 1, "feedback must go to the same persistent session"
    assert dev_agents[0].run_count == 2
    assert "Hero section missing" in dev_agents[0].last_prompt
    reviewer_agents = [a for a in LoopFake.instances if "reviewer" in a.name]
    assert sum(a.run_count for a in reviewer_agents) == 2
