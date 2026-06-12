"""Phase E tests: triage routing, specialist delegation, scoped pipeline flows."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import agentsite.engine.triage as triage_mod
from agentsite.engine.project_manager import ProjectManager
from agentsite.engine.project_pipeline import ProjectGenerationPipeline
from agentsite.engine.triage import triage_request
from agentsite.engine.workspace import WorkspaceManager
from agentsite.models import (
    PagePlan,
    Project,
    QualityRatchet,
    ReviewVerdict,
    SitePlan,
    StyleSpec,
    TriageDecision,
)
from agentsite.templates import find_template
from tests.test_project_pipeline import (
    FakeDevOrReviewer,
    FakePlannerAgent,
    _result,
    _stub_verifier,
    _verify_report,
)

SITE_PLAN = SitePlan(
    project_name="Site", tagline="t",
    pages=[PagePlan(slug="index", title="Home", sections=["hero"])],
)


# ---------------------------------------------------------------------------
# Triage unit tests
# ---------------------------------------------------------------------------


class TestTriage:
    @pytest.mark.asyncio
    async def test_first_build_short_circuits_without_llm(self, monkeypatch):
        async def _boom(*a, **k):
            raise AssertionError("LLM must not be called for v1")

        monkeypatch.setattr(triage_mod, "extract_structured", _boom)
        d = await triage_request("build me a site", model="m", version_number=1)
        assert d.bucket == "full" and d.needs_pm and d.needs_designer

    @pytest.mark.asyncio
    async def test_no_existing_plan_means_full(self, monkeypatch):
        async def _boom(*a, **k):
            raise AssertionError("LLM must not be called without a plan")

        monkeypatch.setattr(triage_mod, "extract_structured", _boom)
        d = await triage_request("x", model="m", site_plan_text="", version_number=3)
        assert d.bucket == "full"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bucket,needs_pm,needs_designer", [
        ("tweak", False, False),
        ("partial", True, False),
        ("full", True, True),
    ])
    async def test_buckets_are_normalized(self, monkeypatch, bucket, needs_pm, needs_designer):
        # The model may return inconsistent flags — normalization clamps them.
        async def _fake(model_cls, text, model, **kw):
            return TriageDecision(bucket=bucket, needs_pm=not needs_pm,
                                  needs_designer=not needs_designer, reason="r")

        monkeypatch.setattr(triage_mod, "extract_structured", _fake)
        d = await triage_request("x", model="m", site_plan_text="{}", version_number=2)
        assert d.bucket == bucket
        assert d.needs_pm is needs_pm
        assert d.needs_designer is needs_designer

    @pytest.mark.asyncio
    async def test_invalid_bucket_and_errors_fall_back_to_full(self, monkeypatch):
        async def _weird(*a, **k):
            return TriageDecision(bucket="banana")

        monkeypatch.setattr(triage_mod, "extract_structured", _weird)
        d = await triage_request("x", model="m", site_plan_text="{}", version_number=2)
        assert d.bucket == "full" and d.needs_pm and d.needs_designer

        async def _raise(*a, **k):
            raise RuntimeError("provider down")

        monkeypatch.setattr(triage_mod, "extract_structured", _raise)
        d2 = await triage_request("x", model="m", site_plan_text="{}", version_number=2)
        assert d2.bucket == "full"


# ---------------------------------------------------------------------------
# delegate_to_specialist tool
# ---------------------------------------------------------------------------


class FakeSpecialistAgent:
    created = []  # noqa: RUF012 — reset per test; subclass-aware via type(self)

    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs
        self.name = kwargs.get("name", "")
        type(self).created.append(self)

    async def run(self, prompt, deps=None, **kwargs):
        self.prompt = prompt
        return SimpleNamespace(
            output_text=f"Rewrote copy for {prompt[:20]}",
            usage={"input_tokens": 5, "output_tokens": 7, "cost": 0.002},
            all_tool_calls=[],
        )


class TestDelegateTool:
    @pytest.fixture
    def ctx(self, tmp_path):
        ws = WorkspaceManager(tmp_path / "p")
        template = find_template("static-multipage")
        ws.scaffold(template)
        events = []

        async def emit(event_type, data):
            events.append((event_type, data))

        deps = {
            "workspace_dir": ws.workspace_dir,
            "template": template,
            "specialist_models": {k: "openai/test-model" for k in
                                  ("copywriter", "seo", "accessibility", "animation")},
            "emit_event": emit,
            "subagent_runs": [],
            "_delegations_left": 2,
            "_events": events,
        }
        return SimpleNamespace(deps=deps)

    @pytest.mark.asyncio
    async def test_delegate_runs_specialist_and_records(self, ctx, monkeypatch):
        import agentsite.agents.workspace_tools as wt

        FakeSpecialistAgent.created = []
        monkeypatch.setattr(wt, "AsyncAgent", FakeSpecialistAgent)

        out = await wt.delegate_to_specialist(ctx, "copywriter", "Punch up the hero copy in index.html")
        assert "copywriter done" in out and "Rewrote copy" in out

        agent = FakeSpecialistAgent.created[0]
        assert agent.kwargs["name"] == "agentsite_copywriter"
        # Composed system prompt: base persona + workspace override
        assert "PROJECT WORKSPACE OVERRIDE" in agent.kwargs["system_prompt"]
        # Specialists must not get run_command or delegation (no recursion)
        assert agent.kwargs["tools"] is wt.specialist_workspace_tools

        runs = ctx.deps["subagent_runs"]
        assert len(runs) == 1 and runs[0]["agent"] == "copywriter"
        assert runs[0]["input_tokens"] == 5 and runs[0]["cost"] == 0.002
        assert ctx.deps["_delegations_left"] == 1

        kinds = [e[0] for e in ctx.deps["_events"]]
        assert kinds == ["specialist_start", "specialist_complete"]
        assert ctx.deps["_events"][1][1]["ok"] is True

    @pytest.mark.asyncio
    async def test_budget_and_validation(self, ctx, monkeypatch):
        import agentsite.agents.workspace_tools as wt

        FakeSpecialistAgent.created = []
        monkeypatch.setattr(wt, "AsyncAgent", FakeSpecialistAgent)

        assert "unknown specialist" in await wt.delegate_to_specialist(ctx, "astrologer", "t")
        await wt.delegate_to_specialist(ctx, "seo", "meta tags")
        await wt.delegate_to_specialist(ctx, "accessibility", "aria pass")
        out = await wt.delegate_to_specialist(ctx, "animation", "motion")
        assert "budget exhausted" in out
        assert len(FakeSpecialistAgent.created) == 2

    @pytest.mark.asyncio
    async def test_specialist_failure_is_contained(self, ctx, monkeypatch):
        import agentsite.agents.workspace_tools as wt

        class ExplodingAgent(FakeSpecialistAgent):
            async def run(self, prompt, deps=None, **kwargs):
                raise RuntimeError("model exploded")

        ExplodingAgent.created = []
        monkeypatch.setattr(wt, "AsyncAgent", ExplodingAgent)
        out = await wt.delegate_to_specialist(ctx, "seo", "meta")
        assert "failed" in out and "Handle the task yourself" in out
        assert ctx.deps["_events"][-1][1]["ok"] is False


# ---------------------------------------------------------------------------
# Scoped pipeline flows
# ---------------------------------------------------------------------------


def _setup_v2_project(tmp_path, tokens_sentinel="/* sentinel */"):
    pm_mgr = ProjectManager(base_dir=tmp_path / "projects")
    project = Project(name="V2", mode="project", template_id="static-multipage")
    pm_mgr.create(project)
    ws = WorkspaceManager(pm_mgr.project_dir(project.id))
    ws.scaffold(find_template("static-multipage"))
    ws.write_file(".agentsite/site-plan.json", SITE_PLAN.model_dump_json())
    ws.write_file("styles/tokens.css", tokens_sentinel)
    return pm_mgr, project, ws


def _patch_decision(monkeypatch, decision: TriageDecision):
    async def _fake(*a, **k):
        return decision

    monkeypatch.setattr(triage_mod, "triage_request", _fake)


def _forbid_factory(monkeypatch, module, attr, label):
    def _boom(model):
        raise AssertionError(f"{label} must not be constructed for this bucket")

    monkeypatch.setattr(module, attr, _boom)


@pytest.mark.asyncio
async def test_tweak_flow_runs_developer_only(tmp_path, monkeypatch):
    pm_mgr, project, ws = _setup_v2_project(tmp_path)

    import agentsite.agents.designer as designer_mod
    import agentsite.agents.pm as pm_mod
    import agentsite.engine.capabilities as caps_mod
    import agentsite.engine.project_pipeline as pp_mod

    _forbid_factory(monkeypatch, pm_mod, "create_pm_agent_auto", "PM")
    _forbid_factory(monkeypatch, designer_mod, "create_designer_agent_auto", "Designer")
    monkeypatch.setattr(caps_mod, "supports_tools", lambda model: True)
    monkeypatch.setattr(caps_mod, "supports_vision", lambda model: False)
    _patch_decision(monkeypatch, TriageDecision(
        bucket="tweak", needs_pm=False, needs_designer=False, reason="small change",
    ))
    _stub_verifier(monkeypatch, [_verify_report(ok=True)])

    captured = {}

    class TweakFake(FakeDevOrReviewer):
        async def run(self, prompt, deps=None, **kwargs):
            self.run_count += 1
            if "developer" in self.name:
                captured["dev_prompt"] = prompt
                return _result("tweaked")
            raise AssertionError("reviewer must not run for tweaks")

    TweakFake.instances = []
    monkeypatch.setattr(pp_mod, "AsyncAgent", TweakFake)

    events = []
    pipeline = ProjectGenerationPipeline(pm_mgr, on_event=events.append)
    result = await pipeline.generate(
        project, slug="home", version_number=2, page_prompt="make the hero button bigger",
    )

    assert result.success is True
    plans = [e for e in events if e.type == "pipeline_plan"]
    assert plans[0].data["required_agents"] == ["developer"]
    assert plans[0].data["bucket"] == "tweak"
    assert any(e.type == "triage_decision" and e.data["bucket"] == "tweak" for e in events)
    assert "small scoped change" in captured["dev_prompt"]
    # existing plan was reused as context
    assert "Site" in captured["dev_prompt"]
    # tokens file untouched (no designer ran)
    assert ws.read_file("styles/tokens.css") == "/* sentinel */"
    # reviewer never instantiated
    assert not [a for a in TweakFake.instances if "reviewer" in a.name]
    completes = [e for e in events if e.type == "generation_complete"]
    assert completes[-1].data["approved"] is True
    assert completes[-1].data["bucket"] == "tweak"
    assert [r.agent_name for r in pipeline.agent_runs] == ["developer"]


@pytest.mark.asyncio
async def test_partial_flow_updates_plan_but_skips_designer(tmp_path, monkeypatch):
    pm_mgr, project, ws = _setup_v2_project(tmp_path)

    import agentsite.agents.designer as designer_mod
    import agentsite.agents.pm as pm_mod
    import agentsite.engine.capabilities as caps_mod
    import agentsite.engine.project_pipeline as pp_mod

    pm_calls = {"count": 0}

    def _pm_factory(model):
        pm_calls["count"] += 1
        return FakePlannerAgent("agentsite_pm", SITE_PLAN.model_dump_json())

    monkeypatch.setattr(pm_mod, "create_pm_agent_auto", _pm_factory)
    _forbid_factory(monkeypatch, designer_mod, "create_designer_agent_auto", "Designer")
    monkeypatch.setattr(caps_mod, "supports_tools", lambda model: True)
    monkeypatch.setattr(caps_mod, "supports_vision", lambda model: False)
    _patch_decision(monkeypatch, TriageDecision(
        bucket="partial", needs_pm=True, needs_designer=False, reason="new page",
    ))
    _stub_verifier(monkeypatch, [_verify_report(ok=True)])

    FakeDevOrReviewer.instances = []
    monkeypatch.setattr(pp_mod, "AsyncAgent", FakeDevOrReviewer)

    events = []
    pipeline = ProjectGenerationPipeline(pm_mgr, on_event=events.append)
    result = await pipeline.generate(
        project, slug="home", version_number=2, page_prompt="add a pricing page",
    )

    assert result.success is True
    assert pm_calls["count"] == 1
    plans = [e for e in events if e.type == "pipeline_plan"]
    assert plans[0].data["required_agents"] == ["pm", "developer", "reviewer"]
    # tokens untouched, reviewer DID run
    assert ws.read_file("styles/tokens.css") == "/* sentinel */"
    assert [a for a in FakeDevOrReviewer.instances if "reviewer" in a.name]
    completes = [e for e in events if e.type == "generation_complete"]
    assert completes[-1].data["bucket"] == "partial"


@pytest.mark.asyncio
async def test_critique_panel_runs_on_workspace_when_flagged(tmp_path, monkeypatch):
    pm_mgr = ProjectManager(base_dir=tmp_path / "projects")
    project = Project(name="Crit", mode="project", template_id="static-multipage")
    pm_mgr.create(project)
    ws = WorkspaceManager(pm_mgr.project_dir(project.id))
    ws.scaffold(find_template("static-multipage"))

    import agentsite.agents.critique as critique_mod
    import agentsite.agents.designer as designer_mod
    import agentsite.agents.pm as pm_mod
    import agentsite.engine.capabilities as caps_mod
    import agentsite.engine.project_pipeline as pp_mod
    import agentsite.engine.ratchet as ratchet_mod
    from agentsite.config import settings

    monkeypatch.setattr(
        pm_mod, "create_pm_agent_auto",
        lambda model: FakePlannerAgent("agentsite_pm", SITE_PLAN.model_dump_json()),
    )
    monkeypatch.setattr(
        designer_mod, "create_designer_agent_auto",
        lambda model: FakePlannerAgent("agentsite_designer", StyleSpec().model_dump_json()),
    )
    monkeypatch.setattr(caps_mod, "supports_tools", lambda model: True)
    monkeypatch.setattr(caps_mod, "supports_vision", lambda model: False)
    monkeypatch.setattr(pp_mod, "AsyncAgent", FakeDevOrReviewer)
    FakeDevOrReviewer.instances = []
    _stub_verifier(monkeypatch, [_verify_report(ok=True)])
    monkeypatch.setattr(settings, "use_critique_panel", True)

    panel_calls = {}

    async def _fake_panel(model, *, page_slug, deps, callbacks=None, context_note=""):
        panel_calls["deps"] = deps
        panel_calls["context_note"] = context_note
        return ReviewVerdict(overall_score=8, approved=True, summary="solid"), None

    def _fake_ratchet(project_id, verdict, *, slug, version):
        return QualityRatchet(project_id=project_id, floors={"visual_fidelity": 8}), True, []

    monkeypatch.setattr(critique_mod, "run_critique_panel", _fake_panel)
    monkeypatch.setattr(ratchet_mod, "update_ratchet", _fake_ratchet)

    events = []
    pipeline = ProjectGenerationPipeline(pm_mgr, on_event=events.append)
    result = await pipeline.generate(
        project, slug="home", version_number=1, page_prompt="build it",
    )

    assert result.success is True
    # Panel read the WORKSPACE, with the verify summary as context
    assert panel_calls["deps"]["version_dir"] == ws.workspace_dir
    assert "Verification" in panel_calls["context_note"]
    verdicts = [e for e in events if e.type == "critique_verdict"]
    assert verdicts and verdicts[0].data["accepted"] is True
    assert verdicts[0].data["floors"] == {"visual_fidelity": 8}
