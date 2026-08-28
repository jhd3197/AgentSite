"""Phase 3: rendered-output verification + vision review for mockup mode.

Covers the single-page verifier (``run_page_verification``), the LoopGroup
glue (``RenderVerifyStep`` / ``VisionReviewerProxy``), the review-loop wiring
in the orchestrator, and the ``GenerationPipeline`` flag threading. No LLM
calls: agent factories and the browser layer are monkeypatched.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from prompture import GroupResult

import agentsite.agents.orchestrator as orch_mod
import agentsite.engine.capabilities as caps_mod
import agentsite.engine.pipeline as pipeline_mod
from agentsite.config import settings
from agentsite.engine import verifier
from agentsite.engine.pipeline import GenerationPipeline
from agentsite.engine.project_manager import ProjectManager
from agentsite.engine.verifier import (
    RenderVerifyStep,
    RouteCheck,
    VerifyReport,
    VisionReviewerProxy,
    page_routes,
    run_page_verification,
)
from agentsite.models import PagePlan, Project, SitePlan, StyleSpec

SITE_PLAN = SitePlan(
    project_name="Mock",
    tagline="t",
    pages=[PagePlan(slug="home", title="Home", sections=["hero"])],
    required_agents=["developer", "reviewer"],
)


def _report(ok: bool, *, skipped: bool = False, with_shots: bool = False) -> VerifyReport:
    return VerifyReport(
        ok=ok,
        skipped=skipped,
        skip_reason="no playwright" if skipped else "",
        routes=[RouteCheck(
            route="index.html",
            ok=ok,
            content_chars=500 if ok else 5,
            console_errors=[] if ok else ["ReferenceError: boom is not defined"],
            screenshots=["v1/index-desktop.jpg", "v1/index-mobile.jpg"] if with_shots else [],
        )],
    )


# ---------------------------------------------------------------------------
# page_routes / run_page_verification
# ---------------------------------------------------------------------------


class TestPageRoutes:
    def test_index_first_then_other_html(self, tmp_path):
        (tmp_path / "about.html").write_text("x")
        (tmp_path / "index.html").write_text("x")
        routes = page_routes(tmp_path)
        assert routes[0] == ("index.html", "/index.html")
        assert ("about.html", "/about.html") in routes

    def test_route_cap(self, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "verify_max_routes", 2)
        for i in range(5):
            (tmp_path / f"p{i}.html").write_text("x")
        assert len(page_routes(tmp_path)) == 2


class TestPageVerificationSkips:
    @pytest.mark.asyncio
    async def test_disabled(self, tmp_path):
        (tmp_path / "index.html").write_text("<html></html>")
        report = await run_page_verification(tmp_path, 1, enabled=False)
        assert report.skipped and "disabled" in report.skip_reason

    @pytest.mark.asyncio
    async def test_playwright_missing(self, tmp_path, monkeypatch):
        (tmp_path / "index.html").write_text("<html></html>")
        monkeypatch.setattr(verifier, "playwright_available", lambda: False)
        report = await run_page_verification(tmp_path, 1)
        assert report.skipped and "playwright not installed" in report.skip_reason

    @pytest.mark.asyncio
    async def test_no_index_html(self, tmp_path):
        report = await run_page_verification(tmp_path, 1)
        assert report.skipped and "no index.html" in report.skip_reason


# ---------------------------------------------------------------------------
# RenderVerifyStep / VisionReviewerProxy
# ---------------------------------------------------------------------------


class TestRenderVerifyStep:
    @pytest.mark.asyncio
    async def test_failure_text_and_screenshots_land_in_deps(self, tmp_path, monkeypatch):
        seen = {}

        async def _fake(page_dir, version, **kwargs):
            seen["page_dir"] = page_dir
            seen["version"] = version
            return _report(ok=False, with_shots=True)

        monkeypatch.setattr(verifier, "run_page_verification", _fake)
        vdir = tmp_path / "pages" / "home" / "v2"
        vdir.mkdir(parents=True)
        deps = {"version_dir": str(vdir)}

        result = await RenderVerifyStep().run(deps=deps)

        assert seen["version"] == 2  # parsed from the v{n} dir name
        assert "boom is not defined" in result.output_text
        shots = deps["verify_screenshots"]
        assert len(shots) == 2
        assert shots[0].endswith("index-desktop.jpg")  # desktop first
        assert "index-mobile.jpg" in shots[1]

    @pytest.mark.asyncio
    async def test_pass_and_skip_are_silent(self, tmp_path, monkeypatch):
        async def _passing(*a, **k):
            return _report(ok=True)

        monkeypatch.setattr(verifier, "run_page_verification", _passing)
        deps = {"version_dir": str(tmp_path / "v1")}
        result = await RenderVerifyStep().run(deps=deps)
        assert result.output_text == ""
        assert deps["verify_screenshots"] == []

        async def _skipped(*a, **k):
            return _report(ok=False, skipped=True)

        monkeypatch.setattr(verifier, "run_page_verification", _skipped)
        deps = {"version_dir": str(tmp_path / "v1")}
        result = await RenderVerifyStep().run(deps=deps)
        assert result.output_text == ""
        assert deps["verify_screenshots"] == []


class _RecordingAgent:
    def __init__(self):
        self.name = "agentsite_reviewer"
        self.output_key = "review_feedback"
        self.calls: list[dict] = []

    async def run(self, prompt, deps=None, images=None):
        self.calls.append({"prompt": prompt, "images": images})
        return SimpleNamespace(output_text='{"approved": true}', run_usage={})


class TestVisionReviewerProxy:
    @pytest.mark.asyncio
    async def test_shots_attached_only_for_vision_models(self, monkeypatch):
        inner = _RecordingAgent()
        proxy = VisionReviewerProxy(inner, "openai/x")
        deps = {"verify_screenshots": [f"/shots/s{i}.jpg" for i in range(8)]}

        monkeypatch.setattr(caps_mod, "supports_vision", lambda model: True)
        await proxy.run("review", deps=deps)
        assert inner.calls[-1]["images"] == [f"/shots/s{i}.jpg" for i in range(6)]

        monkeypatch.setattr(caps_mod, "supports_vision", lambda model: False)
        await proxy.run("review", deps=deps)
        assert inner.calls[-1]["images"] is None

    @pytest.mark.asyncio
    async def test_no_shots_means_no_images(self, monkeypatch):
        inner = _RecordingAgent()
        proxy = VisionReviewerProxy(inner, "openai/x")
        monkeypatch.setattr(caps_mod, "supports_vision", lambda model: True)
        await proxy.run("review", deps={})
        assert inner.calls[-1]["images"] is None


# ---------------------------------------------------------------------------
# Review-loop wiring in the orchestrator (dynamic mockup pipeline)
# ---------------------------------------------------------------------------


class _FakeDev:
    def __init__(self, model):
        self.name = "agentsite_developer"
        self.output_key = "page_output"
        self.prompts: list[str] = []

    async def run(self, prompt, deps=None, **kwargs):
        self.prompts.append(prompt)
        return SimpleNamespace(output_text="built", run_usage={})


class _FakeReviewer:
    def __init__(self, model):
        self.name = "agentsite_reviewer"
        self.output_key = "review_feedback"
        self.images_seen: list[list[str] | None] = []

    async def run(self, prompt, deps=None, images=None):
        self.images_seen.append(images)
        return SimpleNamespace(
            output_text='{"approved": true, "score": 9, "issues": [], "suggestions": []}',
            run_usage={},
        )


def _loop_of(pipeline):
    return pipeline._agents[0][0]


async def _run_loop(pipeline, deps):
    pipeline.inject_state({
        "page_slug": "home",
        "site_plan": "",
        "style_spec": "",
        "design_system_guide": "",
        "architecture_guide": "",
        "logo_url": "",
        "icon_url": "",
        "review_feedback": "",
        "verify_feedback": "",
    }, recursive=True)
    return await pipeline.run("")


class TestDynamicLoopWiring:
    @pytest.mark.asyncio
    async def test_verify_failure_blocks_exit_and_feeds_fix_loop(self, tmp_path, monkeypatch):
        dev = _FakeDev("m")
        reviewer = _FakeReviewer("m")
        monkeypatch.setattr(orch_mod, "create_developer_agent_auto", lambda m: dev)
        monkeypatch.setattr(orch_mod, "create_reviewer_agent_auto", lambda m: reviewer)
        monkeypatch.setattr(verifier, "playwright_available", lambda: True)
        monkeypatch.setattr(caps_mod, "supports_vision", lambda model: True)

        reports = [_report(ok=False, with_shots=True), _report(ok=True, with_shots=True)]
        calls = []

        async def _fake_verify(page_dir, version, **kwargs):
            calls.append(page_dir)
            return reports.pop(0)

        monkeypatch.setattr(verifier, "run_page_verification", _fake_verify)

        vdir = tmp_path / "pages" / "home" / "v1"
        vdir.mkdir(parents=True)
        deps = {"version_dir": str(vdir)}
        pipeline = orch_mod.create_dynamic_pipeline(
            ["developer", "reviewer"], "openai/x", render_verify=True, deps=deps,
        )

        # Structure: verify step sits between developer and (proxied) reviewer
        steps = _loop_of(pipeline)._agents
        assert isinstance(steps[1][0], RenderVerifyStep)
        assert isinstance(steps[2][0], VisionReviewerProxy)

        result = await _run_loop(pipeline, deps)

        assert result.success
        # Verifier ran on the version dir, once per iteration
        assert len(calls) == 2 and calls[0] == vdir
        # Reviewer approved on iteration 1, but verify failure forced a 2nd pass
        assert len(dev.prompts) == 2
        assert "boom is not defined" in dev.prompts[1]
        # Screenshots reached the vision reviewer on both iterations
        assert len(reviewer.images_seen) == 2
        assert all(imgs and any("desktop" in s for s in imgs) for imgs in reviewer.images_seen)

    @pytest.mark.asyncio
    async def test_non_vision_reviewer_gets_no_images(self, tmp_path, monkeypatch):
        reviewer = _FakeReviewer("m")
        monkeypatch.setattr(orch_mod, "create_developer_agent_auto", _FakeDev)
        monkeypatch.setattr(orch_mod, "create_reviewer_agent_auto", lambda m: reviewer)
        monkeypatch.setattr(verifier, "playwright_available", lambda: True)
        monkeypatch.setattr(caps_mod, "supports_vision", lambda model: False)

        async def _fake_verify(*a, **k):
            return _report(ok=True, with_shots=True)

        monkeypatch.setattr(verifier, "run_page_verification", _fake_verify)

        deps = {"version_dir": str(tmp_path / "v1")}
        pipeline = orch_mod.create_dynamic_pipeline(
            ["developer", "reviewer"], "openai/x", render_verify=True, deps=deps,
        )
        await _run_loop(pipeline, deps)
        assert reviewer.images_seen == [None]

    @pytest.mark.asyncio
    async def test_skip_path_behaves_as_today(self, tmp_path, monkeypatch):
        """Without Playwright the loop is exactly the old dev+reviewer loop."""
        dev = _FakeDev("m")
        reviewer = _FakeReviewer("m")
        monkeypatch.setattr(orch_mod, "create_developer_agent_auto", lambda m: dev)
        monkeypatch.setattr(orch_mod, "create_reviewer_agent_auto", lambda m: reviewer)
        monkeypatch.setattr(verifier, "playwright_available", lambda: False)

        async def _boom(*a, **k):
            raise AssertionError("verifier must not run without playwright")

        monkeypatch.setattr(verifier, "run_page_verification", _boom)

        deps = {"version_dir": str(tmp_path / "v1")}
        pipeline = orch_mod.create_dynamic_pipeline(
            ["developer", "reviewer"], "openai/x", render_verify=True, deps=deps,
        )
        steps = _loop_of(pipeline)._agents
        assert [a.name for a, _ in steps] == ["agentsite_developer", "agentsite_reviewer"]

        result = await _run_loop(pipeline, deps)
        assert result.success
        assert len(dev.prompts) == 1  # approved on first pass, single iteration
        assert reviewer.images_seen == [None]

    @pytest.mark.asyncio
    async def test_render_verify_disabled_flag(self, tmp_path, monkeypatch):
        monkeypatch.setattr(verifier, "playwright_available", lambda: True)
        pipeline = orch_mod.create_dynamic_pipeline(
            ["developer", "reviewer"], "openai/x", render_verify=False,
        )
        steps = _loop_of(pipeline)._agents
        assert not any(isinstance(a, RenderVerifyStep) for a, _ in steps)


class TestSpecialistLoopWiring:
    def test_verify_step_and_proxy_present(self, monkeypatch):
        monkeypatch.setattr(verifier, "playwright_available", lambda: True)
        pipeline = orch_mod.create_specialist_pipeline(
            ["markup", "style", "script", "reviewer"], "openai/x", render_verify=True,
        )
        steps = _loop_of(pipeline)._agents
        assert any(isinstance(a, RenderVerifyStep) for a, _ in steps)
        assert any(isinstance(a, VisionReviewerProxy) for a, _ in steps)
        # Specialists see the verify feedback placeholder on fix iterations
        parallel = steps[0][0]
        markup_prompt = next(p for a, p in parallel._agents if getattr(a, "name", "") == "markup")
        assert "{verify_feedback}" in markup_prompt

    def test_absent_without_playwright(self, monkeypatch):
        monkeypatch.setattr(verifier, "playwright_available", lambda: False)
        pipeline = orch_mod.create_specialist_pipeline(
            ["markup", "style", "reviewer"], "openai/x", render_verify=True,
        )
        steps = _loop_of(pipeline)._agents
        assert not any(isinstance(a, RenderVerifyStep) for a, _ in steps)
        assert not any(isinstance(a, VisionReviewerProxy) for a, _ in steps)


# ---------------------------------------------------------------------------
# GenerationPipeline threads the flag from settings
# ---------------------------------------------------------------------------


class _FakePlanner:
    """Stands in for PM/Designer/plain-Developer factory agents."""

    def __init__(self, name: str, output: str, output_key: str | None = None):
        self.name = name
        self.output_key = output_key
        self._output = output
        self.callbacks = None
        self.options: dict = {}

    async def run(self, prompt, deps=None, **kwargs):
        return SimpleNamespace(output_text=self._output, run_usage={}, all_tool_calls=[], messages=[])


class _StubBuildGroup:
    """Captures the dynamic-pipeline call without running any agents."""

    def __init__(self):
        self._agents: list = []
        self._state: dict = {}

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


@pytest.mark.asyncio
@pytest.mark.parametrize("flag", [True, False])
async def test_generate_threads_render_verify_flag(tmp_path, monkeypatch, flag):
    import agentsite.agents.designer as designer_mod
    import agentsite.agents.developer as developer_mod
    import agentsite.agents.pm as pm_mod

    pm_mgr = ProjectManager(base_dir=tmp_path / "projects")
    project = Project(name="Mockup")
    pm_mgr.create(project)

    monkeypatch.setattr(settings, "verify_enabled", flag)
    monkeypatch.setattr(
        pm_mod, "create_pm_agent_auto",
        lambda m: _FakePlanner("agentsite_pm", SITE_PLAN.model_dump_json(), "site_plan"),
    )
    monkeypatch.setattr(
        designer_mod, "create_designer_agent_auto",
        lambda m: _FakePlanner("agentsite_designer", StyleSpec().model_dump_json()),
    )
    monkeypatch.setattr(
        developer_mod, "create_developer_agent_plain",
        lambda m: _FakePlanner(
            "agentsite_developer",
            "```html\n<!DOCTYPE html><html><body>mockup flag threading test page "
            "with enough text</body></html>\n```",
        ),
    )

    captured: list[dict] = []

    def _stub_dynamic(*args, **kwargs):
        captured.append(kwargs)
        return _StubBuildGroup()

    monkeypatch.setattr(pipeline_mod, "create_dynamic_pipeline", _stub_dynamic)

    pipeline = GenerationPipeline(pm_mgr)
    result = await pipeline.generate(
        project, slug="home", version_number=1, page_prompt="build a landing page",
    )

    assert result.success
    assert captured and captured[0]["render_verify"] is flag
    # The developer fallback wrote a real page to the version dir
    files = pm_mgr.list_version_files(project.id, "home", 1)
    assert "index.html" in files


# ---------------------------------------------------------------------------
# Real browser: single static page-version directory
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def chromium_available():
    if not verifier.playwright_available():
        pytest.skip("playwright not installed")
    import asyncio

    async def probe() -> bool:
        from playwright.async_api import async_playwright

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                await browser.close()
            return True
        except Exception:
            return False

    if not asyncio.run(probe()):
        pytest.skip("chromium not installed (playwright install chromium)")
    return True


class TestRealBrowserPage:
    @pytest.mark.asyncio
    async def test_clean_page_passes_with_screenshots(self, tmp_path, chromium_available):
        (tmp_path / "index.html").write_text(
            "<!DOCTYPE html><html><head><title>ok</title>"
            '<link rel="stylesheet" href="styles.css"></head>'
            "<body><h1>A perfectly fine mockup page with plenty of visible text</h1>"
            "</body></html>"
        )
        (tmp_path / "styles.css").write_text("body { margin: 0; }")

        report = await run_page_verification(tmp_path, 1)

        assert not report.skipped
        assert report.ok, report.render_feedback()
        shots = report.screenshot_rel_paths
        assert len(shots) == 2  # desktop + mobile
        for rel in shots:
            f = tmp_path / ".verify" / rel
            assert f.exists() and f.stat().st_size > 1000

    @pytest.mark.asyncio
    async def test_broken_page_fails(self, tmp_path, chromium_available):
        (tmp_path / "index.html").write_text(
            "<!DOCTYPE html><html><head><title>broken</title>"
            '<link rel="stylesheet" href="nope.css"></head>'
            "<body><h1>Broken mockup page with enough body text to not be blank, "
            "padding padding padding</h1>"
            "<script>throw new Error('boom-mockup');</script>"
            "</body></html>"
        )

        report = await run_page_verification(tmp_path, 2)

        assert not report.skipped
        assert not report.ok
        feedback = report.render_feedback()
        assert "boom-mockup" in feedback and "nope.css" in feedback
