"""Component library wired into the generation pipeline.

Covers: generation-time tool registration (dev workspace registry), the
shared component tools resolving builtin blocks AND saved project
components by slug against the right project, and prompt injection of
the available-component catalog (progressive section briefs).
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agentsite.agents.chat_tools import edit_registry
from agentsite.agents.component_tools import (
    component_catalog_lines,
    component_library_tools,
    list_blocks,
    list_project_components,
    render_block,
)
from agentsite.agents.workspace_tools import dev_workspace_tools
from agentsite.engine.progressive import build_section_prompt
from agentsite.models import BlockFieldModel, Project, ProjectComponent
from agentsite.storage.database import Database
from agentsite.storage.repository import ProjectComponentRepository, ProjectRepository


def _ctx(deps: dict | None = None):
    return SimpleNamespace(deps=deps or {})


@pytest.fixture
async def component_repo(tmp_path):
    db = Database(db_path=tmp_path / "test.db")
    await db.connect()
    project_repo = ProjectRepository(db)
    for pid in ("p1", "p2"):
        await project_repo.create(Project(id=pid, name=pid, model="openai/gpt-4o"))
    repo = ProjectComponentRepository(db)
    yield repo
    await db.close()


def _cta_component(project_id: str) -> ProjectComponent:
    return ProjectComponent(
        project_id=project_id,
        slug="cta",
        name="Contact CTA",
        category="cta",
        description="Contact us call-to-action banner",
        template='<section class="cta"><h2>{{heading}}</h2><a href="{{cta_href}}">{{cta_text}}</a></section>',
        fields=[
            BlockFieldModel(key="heading", type="text", label="Heading", default="Talk to us"),
            BlockFieldModel(key="cta_text", type="text", label="CTA label", default="Contact us"),
            BlockFieldModel(key="cta_href", type="url", label="CTA link", default="#contact"),
        ],
    )


# ------------------------------------------------------------------
# Tool registration
# ------------------------------------------------------------------


class TestGenerationToolRegistration:
    def test_dev_workspace_tools_include_component_library(self):
        names = list(dev_workspace_tools.names)
        assert "list_blocks" in names
        assert "render_block" in names
        assert "list_project_components" in names

    def test_edit_registry_keeps_component_tools(self):
        names = list(edit_registry.names)
        assert "list_blocks" in names
        assert "render_block" in names
        assert "list_project_components" in names
        assert "extract_component" in names

    def test_component_library_registry_for_section_agents(self):
        names = list(component_library_tools.names)
        assert names == ["list_blocks", "render_block", "list_project_components"]


# ------------------------------------------------------------------
# Shared tools — listing + rendering
# ------------------------------------------------------------------


class TestListBlocks:
    async def test_lists_builtin_blocks(self):
        out = json.loads(await list_blocks(_ctx()))
        ids = {b["id"] for b in out}
        assert {"hero-split", "cta-banner", "feature-grid-3", "testimonial-quote"} <= ids

    async def test_lists_project_components_for_project(self, component_repo):
        await component_repo.create(_cta_component("p1"))
        ctx = _ctx({"project_id": "p1", "project_component_repo": component_repo})
        out = json.loads(await list_project_components(ctx))
        assert [c["slug"] for c in out] == ["cta"]
        assert out[0]["fields"][0]["key"] == "heading"

    async def test_lists_nothing_without_project_context(self):
        assert json.loads(await list_project_components(_ctx())) == []


class TestRenderBlock:
    async def test_renders_builtin_with_config(self):
        out = json.loads(await render_block(_ctx(), "cta-banner", {"heading": "Ship it"}))
        assert "Ship it" in out["html"]
        assert 'data-ve-block="cta-banner"' in out["html"]

    async def test_resolves_project_component_by_slug(self, component_repo):
        await component_repo.create(_cta_component("p1"))
        ctx = _ctx({"project_id": "p1", "project_component_repo": component_repo})
        out = json.loads(await render_block(ctx, "cta", {"heading": "Contact the team"}))
        assert out["block_id"] == "cta"
        assert "Contact the team" in out["html"]
        # Untouched fields keep their declared defaults.
        assert "Contact us" in out["html"]
        assert 'data-ve-block="cta"' in out["html"]

    async def test_project_components_are_project_scoped(self, component_repo):
        await component_repo.create(_cta_component("p1"))
        other = _ctx({"project_id": "p2", "project_component_repo": component_repo})
        out = json.loads(await render_block(other, "cta"))
        assert "error" in out

    async def test_unknown_block_id_errors(self):
        out = json.loads(await render_block(_ctx(), "no-such-block"))
        assert "error" in out


# ------------------------------------------------------------------
# Prompt injection
# ------------------------------------------------------------------


class TestComponentCatalogLines:
    async def test_includes_builtins_without_repo(self):
        lines = await component_catalog_lines("p1", None)
        assert any(line.startswith("hero-split (builtin):") for line in lines)

    async def test_includes_saved_components(self, component_repo):
        await component_repo.create(_cta_component("p1"))
        lines = await component_catalog_lines("p1", component_repo)
        assert any(line.startswith("cta (saved component):") for line in lines)


class TestSectionPromptInjection:
    def _prompt(self, **kwargs):
        return build_section_prompt(
            page_prompt="A landing page for a sauna studio",
            key="cta",
            description="Contact us CTA banner",
            index=3,
            total=4,
            style_spec_text="{}",
            css="/* css */",
            **kwargs,
        )

    def test_mentions_available_components(self):
        prompt = self._prompt(available_components=["cta (saved component): Contact us call-to-action banner"])
        assert "## Reusable components" in prompt
        assert "cta (saved component): Contact us call-to-action banner" in prompt
        assert "render_block" in prompt

    def test_omits_section_when_no_components(self):
        prompt = self._prompt()
        assert "## Reusable components" not in prompt
