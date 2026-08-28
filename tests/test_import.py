"""Tests for the HTML page importer (engine normalization + API endpoints)."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from agentsite.api import deps
from agentsite.api.app import create_app
from agentsite.engine.importer import absolutize_urls, normalize_html
from agentsite.engine.project_manager import ProjectManager
from agentsite.storage.database import Database
from agentsite.storage.repository import (
    AgentConfigRepository,
    AgentRunRepository,
    PageRepository,
    ProjectRepository,
    VersionRepository,
)


@pytest.fixture
async def client(tmp_path):
    """Create an async test client with initialized deps."""
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


SAMPLE_HTML = """<html>
<head><title>Imported</title>
<style>
body { color: red; }
</style>
</head>
<body>
<h1>Hello</h1>
<style>.box { margin: 0; }</style>
</body>
</html>"""


class TestNormalizeHtml:
    def test_extracts_style_blocks(self):
        files = normalize_html(SAMPLE_HTML)
        assert set(files) == {"index.html", "styles.css"}
        assert "color: red" in files["styles.css"]
        assert ".box" in files["styles.css"]
        assert "<style" not in files["index.html"]
        assert '<link rel="stylesheet" href="styles.css">' in files["index.html"]

    def test_no_styles_no_css_file(self):
        files = normalize_html("<html><head></head><body><p>Hi</p></body></html>")
        assert set(files) == {"index.html"}

    def test_extract_css_disabled(self):
        files = normalize_html(SAMPLE_HTML, extract_css=False)
        assert set(files) == {"index.html"}
        assert "<style" in files["index.html"]

    def test_adds_doctype_and_charset(self):
        files = normalize_html(SAMPLE_HTML)
        html = files["index.html"]
        assert html.startswith("<!DOCTYPE html>")
        assert '<meta charset="utf-8">' in html

    def test_keeps_existing_doctype_and_charset(self):
        files = normalize_html(
            '<!DOCTYPE html><html><head><meta charset="utf-8"></head><body></body></html>'
        )
        html = files["index.html"]
        assert html.count("<!DOCTYPE html>") == 1
        assert html.lower().count("charset") == 1

    def test_wraps_bare_fragment(self):
        files = normalize_html("<h1>Fragment</h1>")
        html = files["index.html"]
        assert html.startswith("<!DOCTYPE html>")
        assert "<html>" in html
        assert '<meta charset="utf-8">' in html
        assert "<body>" in html
        assert "<h1>Fragment</h1>" in html

    def test_fragment_with_styles(self):
        files = normalize_html("<style>p { color: blue; }</style><p>Text</p>")
        assert set(files) == {"index.html", "styles.css"}
        assert "color: blue" in files["styles.css"]
        assert '<link rel="stylesheet" href="styles.css">' in files["index.html"]


class TestAbsolutizeUrls:
    def test_rewrites_relative_urls(self):
        html = '<img src="img/logo.png"><link href="/css/main.css">'
        out = absolutize_urls(html, "https://example.com/pages/about/")
        assert 'src="https://example.com/pages/about/img/logo.png"' in out
        assert 'href="https://example.com/css/main.css"' in out

    def test_leaves_absolute_and_special_urls(self):
        html = (
            '<a href="https://other.com/x">x</a>'
            '<img src="data:image/png;base64,abc">'
            '<a href="#section">s</a>'
            '<a href="mailto:a@b.c">m</a>'
            '<a href="tel:+123">t</a>'
            '<a href="javascript:void(0)">j</a>'
        )
        out = absolutize_urls(html, "https://example.com/")
        assert out == html


class TestImportEndpoints:
    async def _create_project(self, client, mode="mockup") -> str:
        resp = await client.post("/api/projects", json={"name": "Import Test", "mode": mode})
        assert resp.status_code == 200
        return resp.json()["id"]

    @pytest.mark.asyncio
    async def test_import_html_creates_page_and_version(self, client, tmp_path):
        project_id = await self._create_project(client)

        resp = await client.post(
            f"/api/projects/{project_id}/import",
            json={"slug": "landing", "title": "Landing", "html": SAMPLE_HTML},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["page"]["slug"] == "landing"
        assert data["page"]["title"] == "Landing"
        assert data["files"] == ["index.html", "styles.css"]
        assert data["version"]["version_number"] == 1
        assert data["version"]["status"] == "completed"
        assert data["version"]["completed_at"] is not None
        assert data["version"]["files"]["styles.css"]

        # Files on disk
        vdir = tmp_path / "projects" / project_id / "pages" / "landing" / "v1"
        assert (vdir / "index.html").is_file()
        assert (vdir / "styles.css").is_file()
        assert "color: red" in (vdir / "styles.css").read_text(encoding="utf-8")

        # Page visible via API
        page_resp = await client.get(f"/api/projects/{project_id}/pages/landing")
        assert page_resp.status_code == 200

    @pytest.mark.asyncio
    async def test_import_same_slug_creates_new_version(self, client, tmp_path):
        project_id = await self._create_project(client)
        await client.post(
            f"/api/projects/{project_id}/import",
            json={"slug": "landing", "html": SAMPLE_HTML},
        )
        resp = await client.post(
            f"/api/projects/{project_id}/import",
            json={"slug": "landing", "html": "<p>v2</p>"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["version"]["version_number"] == 2
        assert (tmp_path / "projects" / project_id / "pages" / "landing" / "v2" / "index.html").is_file()

    @pytest.mark.asyncio
    async def test_import_invalid_slug(self, client):
        project_id = await self._create_project(client)
        for slug in ("", "Bad Slug", "-leading", "UPPER", "under_score"):
            resp = await client.post(
                f"/api/projects/{project_id}/import",
                json={"slug": slug, "html": "<p>x</p>"},
            )
            assert resp.status_code == 400, slug

    @pytest.mark.asyncio
    async def test_import_empty_html(self, client):
        project_id = await self._create_project(client)
        resp = await client.post(
            f"/api/projects/{project_id}/import",
            json={"slug": "landing", "html": "   "},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_import_nonexistent_project(self, client):
        resp = await client.post(
            "/api/projects/nonexistent123/import",
            json={"slug": "landing", "html": "<p>x</p>"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_import_project_mode_rejected(self, client):
        resp = await client.post(
            "/api/projects", json={"name": "WS", "mode": "project"}
        )
        # Scaffold may fail without template assets; only proceed if created
        if resp.status_code != 200:
            pytest.skip("project-mode creation unavailable in test env")
        project_id = resp.json()["id"]
        resp = await client.post(
            f"/api/projects/{project_id}/import",
            json={"slug": "landing", "html": "<p>x</p>"},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_import_from_url(self, client, monkeypatch):
        project_id = await self._create_project(client)

        async def fake_fetch(url, **kwargs):
            return '<html><head></head><body><img src="img/a.png"></body></html>'

        monkeypatch.setattr("agentsite.api.routes.importer.fetch_page", fake_fetch)

        resp = await client.post(
            f"/api/projects/{project_id}/import/url",
            json={"slug": "from-url", "url": "https://example.com/page"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["page"]["prompt"] == "Imported from https://example.com/page"
        assert data["version"]["files"]["index.html"].startswith("<!DOCTYPE html>")

    @pytest.mark.asyncio
    async def test_import_from_url_fetch_error(self, client, monkeypatch):
        project_id = await self._create_project(client)

        async def fake_fetch(url, **kwargs):
            raise ValueError("Fetch failed with status 404")

        monkeypatch.setattr("agentsite.api.routes.importer.fetch_page", fake_fetch)

        resp = await client.post(
            f"/api/projects/{project_id}/import/url",
            json={"slug": "from-url", "url": "https://example.com/missing"},
        )
        assert resp.status_code == 400
        assert "404" in resp.json()["detail"]
