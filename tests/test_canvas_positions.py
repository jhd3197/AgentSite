"""Phase 6: whiteboard canvas positions (canvas_x / canvas_y) on pages.

Covers the DB migration, repository round-trip, and PATCH endpoint
semantics (absent = no change, null clears) — no LLM calls.
"""

from __future__ import annotations

import aiosqlite
import pytest
from httpx import ASGITransport, AsyncClient

from agentsite.api import deps
from agentsite.api.app import create_app
from agentsite.engine.project_manager import ProjectManager
from agentsite.models import Page, Project
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
# Migration + repository
# ------------------------------------------------------------------


class TestCanvasMigration:
    @pytest.mark.asyncio
    async def test_fresh_db_has_columns(self, tmp_path):
        db = Database(db_path=tmp_path / "fresh.db")
        await db.connect()
        cursor = await db.conn.execute("PRAGMA table_info(pages)")
        cols = {row[1] for row in await cursor.fetchall()}
        assert "canvas_x" in cols
        assert "canvas_y" in cols
        await db.close()

    @pytest.mark.asyncio
    async def test_migration_adds_columns_to_old_db(self, tmp_path):
        """A pre-Phase-6 pages table gains the columns without losing data."""
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
                layout_overrides TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"""
        )
        await conn.execute(
            "INSERT INTO pages VALUES ('p1', 'proj1', 'home', 'Home', '', NULL, '2024', '2024')"
        )
        await conn.commit()
        await conn.close()

        db = Database(db_path=db_path)
        await db.connect()
        cursor = await db.conn.execute("PRAGMA table_info(pages)")
        cols = {row[1] for row in await cursor.fetchall()}
        assert "canvas_x" in cols
        assert "canvas_y" in cols

        page = await PageRepository(db).get("p1")
        assert page is not None
        assert page.slug == "home"
        assert page.canvas_x is None
        assert page.canvas_y is None
        await db.close()


class TestPageRepositoryCanvas:
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

        page = Page(project_id=project.id, slug="home", canvas_x=120.5, canvas_y=-40.0)
        await page_repo.create(page)

        loaded = await page_repo.get_by_slug(project.id, "home")
        assert loaded.canvas_x == 120.5
        assert loaded.canvas_y == -40.0

    @pytest.mark.asyncio
    async def test_default_is_none(self, repos):
        project_repo, page_repo = repos
        project = Project(name="T")
        await project_repo.create(project)
        page = Page(project_id=project.id, slug="home")
        await page_repo.create(page)

        loaded = await page_repo.get(page.id)
        assert loaded.canvas_x is None
        assert loaded.canvas_y is None

    @pytest.mark.asyncio
    async def test_update_and_clear(self, repos):
        project_repo, page_repo = repos
        project = Project(name="T")
        await project_repo.create(project)
        page = Page(project_id=project.id, slug="home")
        await page_repo.create(page)

        page.canvas_x = 320.0
        page.canvas_y = 640.0
        await page_repo.update(page)
        loaded = await page_repo.get(page.id)
        assert loaded.canvas_x == 320.0
        assert loaded.canvas_y == 640.0

        page.canvas_x = None
        page.canvas_y = None
        await page_repo.update(page)
        loaded = await page_repo.get(page.id)
        assert loaded.canvas_x is None
        assert loaded.canvas_y is None


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
    resp = await client.post("/api/projects", json={"name": "Canvas Test"})
    project_id = resp.json()["id"]
    await client.post(f"/api/projects/{project_id}/pages", json={"slug": slug})
    return project_id


class TestPatchCanvasPosition:
    @pytest.mark.asyncio
    async def test_responses_include_canvas_fields(self, client):
        project_id = await _project_with_page(client)
        resp = await client.get(f"/api/projects/{project_id}/pages")
        page = resp.json()[0]
        assert page["canvas_x"] is None
        assert page["canvas_y"] is None

    @pytest.mark.asyncio
    async def test_patch_sets_position(self, client):
        project_id = await _project_with_page(client)
        resp = await client.patch(
            f"/api/projects/{project_id}/pages/home",
            json={"canvas_x": 512.5, "canvas_y": 128.0},
        )
        assert resp.status_code == 200
        assert resp.json()["canvas_x"] == 512.5
        assert resp.json()["canvas_y"] == 128.0

        # Persisted — included in subsequent page responses
        resp = await client.get(f"/api/projects/{project_id}/pages/home")
        assert resp.json()["canvas_x"] == 512.5
        assert resp.json()["canvas_y"] == 128.0

    @pytest.mark.asyncio
    async def test_absent_fields_do_not_change_position(self, client):
        project_id = await _project_with_page(client)
        await client.patch(
            f"/api/projects/{project_id}/pages/home",
            json={"canvas_x": 100.0, "canvas_y": 200.0},
        )
        resp = await client.patch(
            f"/api/projects/{project_id}/pages/home", json={"title": "Landing"}
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "Landing"
        assert resp.json()["canvas_x"] == 100.0
        assert resp.json()["canvas_y"] == 200.0

    @pytest.mark.asyncio
    async def test_null_clears_position(self, client):
        project_id = await _project_with_page(client)
        await client.patch(
            f"/api/projects/{project_id}/pages/home",
            json={"canvas_x": 100.0, "canvas_y": 200.0},
        )
        resp = await client.patch(
            f"/api/projects/{project_id}/pages/home",
            json={"canvas_x": None, "canvas_y": None},
        )
        assert resp.json()["canvas_x"] is None
        assert resp.json()["canvas_y"] is None

    @pytest.mark.asyncio
    async def test_partial_update_single_axis(self, client):
        project_id = await _project_with_page(client)
        resp = await client.patch(
            f"/api/projects/{project_id}/pages/home", json={"canvas_x": 42.0}
        )
        assert resp.status_code == 200
        assert resp.json()["canvas_x"] == 42.0
        assert resp.json()["canvas_y"] is None
