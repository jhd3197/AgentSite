"""Tests for the Playwright verifier: route planning, gates, real browser runs."""

from __future__ import annotations

import urllib.request

import pytest

from agentsite.engine import verifier
from agentsite.engine.verifier import (
    RouteCheck,
    VerifyReport,
    evaluate_gate,
    plan_routes,
    run_verification,
    serve_directory,
)
from agentsite.engine.workspace import WorkspaceManager
from agentsite.models import PagePlan, SitePlan
from agentsite.templates import find_template

SITE_PLAN = SitePlan(
    project_name="x", tagline="y",
    pages=[
        PagePlan(slug="index", title="Home", sections=["hero"]),
        PagePlan(slug="about", title="About", sections=["bio"]),
    ],
)


# ---------------------------------------------------------------------------
# Route planning
# ---------------------------------------------------------------------------


class TestPlanRoutes:
    def test_static_detects_missing_pages(self, tmp_path):
        (tmp_path / "index.html").write_text("<html></html>")
        routes, missing = plan_routes(find_template("static-multipage"), SITE_PLAN, tmp_path)
        assert ("index.html", "/index.html") in routes
        assert missing == ["about"]

    def test_static_includes_existing_pages(self, tmp_path):
        (tmp_path / "index.html").write_text("x")
        (tmp_path / "about.html").write_text("x")
        routes, missing = plan_routes(find_template("static-multipage"), SITE_PLAN, tmp_path)
        assert ("about.html", "/about.html") in routes
        assert missing == []

    def test_node_uses_hash_routes(self, tmp_path):
        routes, missing = plan_routes(find_template("vite-react-tailwind"), SITE_PLAN, tmp_path)
        assert ("#/", "/#/") in routes
        assert ("#/about", "/#/about") in routes
        assert missing == []

    def test_entry_always_checked_even_if_plan_omits_it(self, tmp_path):
        (tmp_path / "index.html").write_text("x")
        plan = SitePlan(project_name="x", tagline="y",
                        pages=[PagePlan(slug="about", title="A", sections=[])])
        (tmp_path / "about.html").write_text("x")
        routes, _ = plan_routes(find_template("static-multipage"), plan, tmp_path)
        assert routes[0] == ("index.html", "/index.html")

    def test_route_cap(self, tmp_path, monkeypatch):
        from agentsite.config import settings

        monkeypatch.setattr(settings, "verify_max_routes", 2)
        pages = [PagePlan(slug=f"p{i}", title=str(i), sections=[]) for i in range(6)]
        plan = SitePlan(project_name="x", tagline="y", pages=pages)
        routes, _ = plan_routes(find_template("vite-react-tailwind"), plan, tmp_path)
        assert len(routes) == 2


# ---------------------------------------------------------------------------
# Gate semantics + feedback rendering
# ---------------------------------------------------------------------------


class TestGate:
    def test_skipped_passes_gate(self):
        assert evaluate_gate(VerifyReport(ok=False, skipped=True, skip_reason="no playwright"))

    def test_ok_passes_failed_fails(self):
        assert evaluate_gate(VerifyReport(ok=True))
        assert not evaluate_gate(VerifyReport(ok=False))

    def test_feedback_lists_concrete_problems(self):
        report = VerifyReport(
            ok=False,
            missing_pages=["pricing"],
            routes=[RouteCheck(
                route="index.html", ok=False,
                console_errors=["ReferenceError: foo is not defined"],
                failed_requests=["GET http://x/styles/nope.css -> 404"],
                content_chars=10,
            )],
        )
        text = report.render_feedback()
        assert "pricing" in text
        assert "ReferenceError" in text
        assert "nope.css" in text
        assert "almost no content" in text


# ---------------------------------------------------------------------------
# Ephemeral server
# ---------------------------------------------------------------------------


def test_serve_directory_roundtrip(tmp_path):
    (tmp_path / "index.html").write_text("<html><body>hello-serve</body></html>")
    with serve_directory(tmp_path) as base_url:
        body = urllib.request.urlopen(f"{base_url}/index.html", timeout=5).read().decode()
        assert "hello-serve" in body
        # directory request serves index.html
        body2 = urllib.request.urlopen(f"{base_url}/", timeout=5).read().decode()
        assert "hello-serve" in body2


# ---------------------------------------------------------------------------
# run_verification skip paths (no browser needed)
# ---------------------------------------------------------------------------


class TestSkipPaths:
    @pytest.mark.asyncio
    async def test_disabled(self, tmp_path):
        report = await run_verification(
            tmp_path, find_template("static-multipage"), SITE_PLAN, 1, enabled=False,
        )
        assert report.skipped and "disabled" in report.skip_reason

    @pytest.mark.asyncio
    async def test_playwright_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(verifier, "playwright_available", lambda: False)
        report = await run_verification(
            tmp_path, find_template("static-multipage"), SITE_PLAN, 1,
        )
        assert report.skipped and "playwright not installed" in report.skip_reason
        assert evaluate_gate(report)

    @pytest.mark.asyncio
    async def test_node_without_build_output(self, tmp_path):
        report = await run_verification(
            tmp_path, find_template("vite-react-tailwind"), SITE_PLAN, 1,
        )
        assert report.skipped and "no build output" in report.skip_reason


# ---------------------------------------------------------------------------
# Real browser integration (skips cleanly where chromium isn't installed)
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


class TestRealBrowser:
    @pytest.mark.asyncio
    async def test_clean_scaffold_passes(self, tmp_path, chromium_available):
        ws = WorkspaceManager(tmp_path / "proj")
        tpl = find_template("static-multipage")
        ws.scaffold(tpl)
        plan = SitePlan(project_name="x", tagline="y",
                        pages=[PagePlan(slug="index", title="Home", sections=["hero"])])

        report = await run_verification(ws.workspace_dir, tpl, plan, 1)

        assert not report.skipped
        assert report.ok, report.render_feedback()
        assert report.routes and report.routes[0].content_chars > 40
        shots = report.screenshot_rel_paths
        assert len(shots) == 2  # desktop + mobile
        for rel in shots:
            f = ws.workspace_dir / ".agentsite" / "verify" / rel
            assert f.exists() and f.stat().st_size > 1000

    @pytest.mark.asyncio
    async def test_broken_page_fails_gate(self, tmp_path, chromium_available):
        ws = WorkspaceManager(tmp_path / "proj")
        tpl = find_template("static-multipage")
        ws.scaffold(tpl)
        ws.write_file("index.html", (
            "<!DOCTYPE html><html><head><title>broken</title>"
            '<link rel="stylesheet" href="styles/does-not-exist.css">'
            "</head><body><h1>Broken page with enough body text to not be blank, "
            "padding padding padding</h1>"
            "<script>throw new Error('boom-from-test');</script>"
            "</body></html>"
        ))
        plan = SitePlan(project_name="x", tagline="y",
                        pages=[PagePlan(slug="index", title="Home", sections=[])])

        report = await run_verification(ws.workspace_dir, tpl, plan, 2)

        assert not report.skipped
        assert not report.ok
        assert not evaluate_gate(report)
        route = report.routes[0]
        assert any("boom-from-test" in e for e in route.console_errors)
        assert any("does-not-exist.css" in f for f in route.failed_requests)
        feedback = report.render_feedback()
        assert "boom-from-test" in feedback and "does-not-exist.css" in feedback

    @pytest.mark.asyncio
    async def test_blank_page_fails_gate(self, tmp_path, chromium_available):
        ws = WorkspaceManager(tmp_path / "proj")
        tpl = find_template("static-multipage")
        ws.scaffold(tpl)
        ws.write_file("index.html", "<!DOCTYPE html><html><head><title>b</title></head><body></body></html>")
        plan = SitePlan(project_name="x", tagline="y",
                        pages=[PagePlan(slug="index", title="Home", sections=[])])

        report = await run_verification(ws.workspace_dir, tpl, plan, 3)
        assert not report.ok
        assert report.routes[0].content_chars < 40
