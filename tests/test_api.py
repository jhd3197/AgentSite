"""Tests for AgentSite FastAPI endpoints."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from agentsite.api import deps
from agentsite.api.app import create_app
from agentsite.engine.project_manager import ProjectManager
from agentsite.storage.database import Database
from agentsite.storage.repository import (
    AgentConfigRepository,
    AgentRunRepository,
    PageRepository,
    ProjectComponentRepository,
    ProjectRepository,
    VersionRepository,
)


@pytest.fixture
async def client(tmp_path):
    """Create an async test client with initialized deps."""
    # Override deps with temp paths
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


class TestModelsEndpoint:
    @pytest.mark.asyncio
    async def test_list_models(self, client):
        resp = await client.get("/api/models")
        assert resp.status_code == 200
        data = resp.json()
        assert "groups" in data
        assert isinstance(data["groups"], dict)


class TestProjectEndpoints:
    @pytest.mark.asyncio
    async def test_create_project(self, client):
        resp = await client.post(
            "/api/projects",
            json={"name": "Test", "description": "Build a portfolio"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Test"
        assert "id" in data

    @pytest.mark.asyncio
    async def test_list_projects(self, client):
        await client.post("/api/projects", json={"name": "List Test"})
        resp = await client.get("/api/projects")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    @pytest.mark.asyncio
    async def test_get_project(self, client):
        create_resp = await client.post("/api/projects", json={"name": "Get Test"})
        project_id = create_resp.json()["id"]

        resp = await client.get(f"/api/projects/{project_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == project_id

    @pytest.mark.asyncio
    async def test_get_nonexistent_project(self, client):
        resp = await client.get("/api/projects/nonexistent123")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_project(self, client):
        create_resp = await client.post("/api/projects", json={"name": "Delete Test"})
        project_id = create_resp.json()["id"]

        resp = await client.delete(f"/api/projects/{project_id}")
        assert resp.status_code == 200

        resp = await client.get(f"/api/projects/{project_id}")
        assert resp.status_code == 404


class TestPageEndpoints:
    @pytest.mark.asyncio
    async def test_create_page(self, client):
        create_resp = await client.post("/api/projects", json={"name": "Page Test"})
        project_id = create_resp.json()["id"]

        resp = await client.post(
            f"/api/projects/{project_id}/pages",
            json={"slug": "home", "title": "Home Page"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["slug"] == "home"
        assert data["title"] == "Home Page"

    @pytest.mark.asyncio
    async def test_list_pages(self, client):
        create_resp = await client.post("/api/projects", json={"name": "Page List"})
        project_id = create_resp.json()["id"]

        await client.post(f"/api/projects/{project_id}/pages", json={"slug": "home"})
        await client.post(f"/api/projects/{project_id}/pages", json={"slug": "about"})

        resp = await client.get(f"/api/projects/{project_id}/pages")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

    @pytest.mark.asyncio
    async def test_get_page(self, client):
        create_resp = await client.post("/api/projects", json={"name": "Page Get"})
        project_id = create_resp.json()["id"]

        await client.post(f"/api/projects/{project_id}/pages", json={"slug": "contact"})

        resp = await client.get(f"/api/projects/{project_id}/pages/contact")
        assert resp.status_code == 200
        assert resp.json()["slug"] == "contact"

    @pytest.mark.asyncio
    async def test_delete_page(self, client):
        create_resp = await client.post("/api/projects", json={"name": "Page Delete"})
        project_id = create_resp.json()["id"]

        await client.post(f"/api/projects/{project_id}/pages", json={"slug": "temp"})

        resp = await client.delete(f"/api/projects/{project_id}/pages/temp")
        assert resp.status_code == 200

        resp = await client.get(f"/api/projects/{project_id}/pages/temp")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_duplicate_slug_rejected(self, client):
        create_resp = await client.post("/api/projects", json={"name": "Dup Test"})
        project_id = create_resp.json()["id"]

        await client.post(f"/api/projects/{project_id}/pages", json={"slug": "home"})
        resp = await client.post(f"/api/projects/{project_id}/pages", json={"slug": "home"})
        assert resp.status_code == 409


class TestGenerationEndpoint:
    @pytest.mark.asyncio
    async def test_generate_requires_prompt(self, client):
        create_resp = await client.post("/api/projects", json={"name": "Gen Test"})
        project_id = create_resp.json()["id"]

        resp = await client.post(f"/api/projects/{project_id}/pages/home/generate", json={})
        assert resp.status_code == 400
