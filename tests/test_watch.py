"""Tests for live-preview watching: script injection + feedback rendering."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from agentsite.api import deps
from agentsite.config import settings
from agentsite.engine.watch import (
    _MARKER,
    append_watch_feedback,
    inject_watch_script,
    render_watch_feedback,
)
from agentsite.models import Page
from agentsite.storage.repository import (
    PageRepository,
    ProjectRepository,
    VersionRepository,
)


class TestInjectWatchScript:
    def test_injects_before_head_close(self):
        html = "<html><head><title>t</title></head><body>hi</body></html>"
        out = inject_watch_script(html)
        assert _MARKER in out
        assert out.index("data-agentsite-watch") < out.index("</head>")
        assert out.endswith("</head><body>hi</body></html>")

    def test_idempotent(self):
        html = "<html><head></head><body></body></html>"
        once = inject_watch_script(html)
        assert inject_watch_script(once) == once

    def test_no_head_falls_back_to_prepend(self):
        html = "<div>fragment</div>"
        out = inject_watch_script(html)
        assert out.startswith("<script")
        assert out.rstrip().endswith("<div>fragment</div>")

    def test_disabled_leaves_html_untouched(self, monkeypatch):
        monkeypatch.setattr(settings, "watch_enabled", False)
        html = "<html><head></head><body></body></html>"
        assert inject_watch_script(html) == html


class TestRenderWatchFeedback:
    def test_empty_events_render_nothing(self):
        assert render_watch_feedback([]) == ""
        assert render_watch_feedback([None, "junk", {"type": "nope"}]) == ""

    def test_groups_duplicates_with_counts(self):
        events = [
            {"type": "dead_click", "selector": "button.cta", "message": "Clicked CTA"},
            {"type": "dead_click", "selector": "button.cta", "message": "Clicked CTA"},
            {"type": "js_error", "message": "boom"},
        ]
        out = render_watch_feedback(events)
        assert "Dead click" in out
        assert "`button.cta`" in out
        assert "x2" in out
        assert "Uncaught JS error" in out
        # grouped: dead_click appears once
        assert out.count("**Dead click") == 1

    def test_line_cap(self):
        events = [
            {"type": "js_error", "message": f"err {i}", "selector": f"#e{i}"}
            for i in range(60)
        ]
        out = render_watch_feedback(events)
        assert "more observations" in out


class TestAppendWatchFeedback:
    def test_appends_section(self):
        prompt = append_watch_feedback("Make it blue", [
            {"type": "dead_click", "selector": "a.missing", "message": "Clicked nav link"},
        ])
        assert prompt.startswith("Make it blue")
        assert "## Issues observed while a human used the live preview" in prompt
        assert "Dead click" in prompt

    def test_noop_on_invalid(self):
        assert append_watch_feedback("prompt", [{"type": "bogus"}]) == "prompt"
        assert append_watch_feedback("prompt", []) == "prompt"


@pytest.fixture
async def api_client(tmp_path):
    deps.db = deps.Database(db_path=tmp_path / "test.db")
    deps.project_manager = deps.ProjectManager(base_dir=tmp_path / "projects")
    deps.asset_handler = deps.AssetHandler(deps.project_manager)

    await deps.db.connect()
    deps.project_repo = ProjectRepository(deps.db)
    deps.page_repo = PageRepository(deps.db)
    deps.version_repo = VersionRepository(deps.db)

    from agentsite.api.app import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    await deps.db.close()


class TestPreviewInjection:
    @pytest.mark.asyncio
    async def test_preview_page_serves_watcher(self, api_client, tmp_path):
        client = api_client
        proj = (await client.post("/api/projects", json={"name": "Watch"})).json()
        pid = proj["id"]
        page = Page(project_id=pid, slug="home", title="Home", prompt="p")
        await deps.page_repo.create(page)

        pm = deps.project_manager
        pm.write_version_file(pid, "home", 1, "index.html", "<html><head></head><body>ok</body></html>")

        resp = await client.get(f"/preview/{pid}/home")
        assert resp.status_code == 200
        assert _MARKER in resp.text

    @pytest.mark.asyncio
    async def test_preview_non_html_not_touched(self, api_client, tmp_path):
        client = api_client
        proj = (await client.post("/api/projects", json={"name": "Watch2"})).json()
        pid = proj["id"]
        page = Page(project_id=pid, slug="home", title="Home", prompt="p")
        await deps.page_repo.create(page)

        pm = deps.project_manager
        pm.write_version_file(pid, "home", 1, "index.html", "<html><head></head><body>ok</body></html>")
        pm.write_version_file(pid, "home", 1, "style.css", "body{}")

        resp = await client.get(f"/preview/{pid}/home/v/1/style.css")
        assert resp.status_code == 200
        assert _MARKER not in resp.text
