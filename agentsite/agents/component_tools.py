"""Component-library tools shared by every agent surface.

The same three tools are registered on:
  - the edit-mode chat registry (``chat_tools.edit_registry``)
  - the generation-time developer registry
    (``workspace_tools.dev_workspace_tools``)
  - the progressive section agents (``engine/progressive.py``)

They resolve against BOTH the builtin block catalog (``engine/blocks.py``)
and the project's saved components, keyed by ``ctx.deps['project_id']`` +
``ctx.deps['project_component_repo']``. When the repo is absent from deps
(e.g. a caller that never wired it), builtin blocks keep working and the
project-component lookups degrade gracefully to empty.
"""

from __future__ import annotations

import json
from typing import Any

from prompture import RunContext, ToolRegistry

from ..engine.blocks import BUILTIN_BLOCKS as _BUILTIN_BLOCKS
from ..engine.blocks import get_block as _get_block
from ..engine.blocks import render_block as _render_block

# ---------------------------------------------------------------------------
# Block tools — let the agent insert pre-built sections (hero, CTA banner,
# feature grid, testimonial) or saved project components instead of writing
# every layout from scratch. The agent's flow:
#   1. list_blocks() / list_project_components() → see what's available
#   2. render_block(block_id, config) → get the HTML string
#   3. insert it (edit mode: patch set-outer-html; generation: into the file)
# ---------------------------------------------------------------------------


async def list_blocks(ctx: RunContext) -> str:
    """List every available reusable block (hero, CTA, feature grid, etc).

    Use this BEFORE `render_block` to discover block ids + their declared
    editable fields. Returns a compact JSON listing — just metadata, no
    templates.
    """
    out = [
        {
            "id": b["id"],
            "name": b["name"],
            "category": b["category"],
            "description": b["description"],
            "fields": [
                {"key": f["key"], "type": f["type"], "label": f.get("label", f["key"])}
                for f in b["fields"]
            ],
        }
        for b in _BUILTIN_BLOCKS
    ]
    return json.dumps(out)


async def render_block(
    ctx: RunContext,
    block_id: str,
    config: dict[str, Any] | None = None,
) -> str:
    """Render a block to insert-ready HTML with the given config.

    Resolves against BOTH the built-in catalog (`list_blocks`) AND the
    project's saved components (`list_project_components`). Use either
    a builtin id like ``'hero-split'`` or a project component slug like
    ``'pricing-card'``.

    Args:
        block_id: Builtin id OR project component slug.
        config: Field values overriding the block's declared defaults.
            Any field you leave out keeps its default. Example:
            ``{'heading': 'New product', 'accent': '#16a34a'}``.

    Returns:
        JSON ``{"html": "<section …>…</section>"}`` — insert this HTML into
        the page (edit mode: ``patch(kind='set-outer-html', html=...)``;
        generation: include it in the file you are writing).
    """
    definition = _get_block(block_id)
    if definition is None:
        # Fall back to project components — block_id may be a custom slug.
        project_id = ctx.deps.get("project_id")
        component_repo = ctx.deps.get("project_component_repo")
        if project_id and component_repo:
            pc = await component_repo.get_by_slug(project_id, block_id)
            if pc is not None:
                definition = {
                    "id": pc.slug,
                    "name": pc.name,
                    "category": pc.category,
                    "description": pc.description,
                    "thumbnail": pc.thumbnail,
                    "template": pc.template,
                    "fields": [f.model_dump() for f in pc.fields],
                }
    if definition is None:
        return json.dumps({"error": f"Unknown block_id (no builtin or project component): {block_id}"})
    try:
        html = _render_block(definition, config or {})
    except Exception as exc:
        return json.dumps({"error": f"render failed: {exc}"})
    return json.dumps({"html": html, "block_id": block_id})


async def list_project_components(ctx: RunContext) -> str:
    """List every reusable component saved in this project's library.

    Returns metadata (id, slug, name, category, description, fields) for
    each — call this BEFORE list_blocks if the user refers to something
    by a custom name like 'pricing card' that doesn't match a builtin.
    """
    project_id = ctx.deps.get("project_id")
    component_repo = ctx.deps.get("project_component_repo")
    if not project_id or component_repo is None:
        return json.dumps([])
    items = await component_repo.list_by_project(project_id)
    out = [
        {
            "id": c.id,
            "slug": c.slug,
            "name": c.name,
            "category": c.category,
            "description": c.description,
            "fields": [
                {"key": f.key, "type": f.type, "label": f.label}
                for f in c.fields
            ],
        }
        for c in items
    ]
    return json.dumps(out)


async def component_catalog_lines(
    project_id: str | None,
    component_repo: Any | None,
) -> list[str]:
    """One short ``id: description`` line per available component.

    Used to inject the library into generation prompts (project-mode dev
    brief, progressive section briefs) so the agent knows what it can
    render instead of hand-writing markup.
    """
    lines = [f"{b['id']} (builtin): {b['description']}" for b in _BUILTIN_BLOCKS]
    if project_id and component_repo is not None:
        items = await component_repo.list_by_project(project_id)
        lines.extend(
            f"{c.slug} (saved component): {c.description or c.name}" for c in items
        )
    return lines


# Standalone registry for agents that ONLY need the component library
# (e.g. progressive section agents). The chat and workspace registries
# register the same functions individually alongside their own tools.
component_library_tools = ToolRegistry()
component_library_tools.register(list_blocks)
component_library_tools.register(render_block)
component_library_tools.register(list_project_components)
