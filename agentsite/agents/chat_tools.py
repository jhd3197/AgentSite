"""Tools the chat agent uses to drive the build pipeline.

The chat agent (prompture.AsyncAgent) gets this registry. Tools read
their dependencies from ``ctx.deps``, which the chat endpoint populates
with project repos, the project manager, and the current project_id.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from prompture import RunContext, ToolRegistry

from ..engine.component_extractor import extract as _extract_component
from ..engine.generation_runner import start_generation_task
from ..engine.html_query import (
    find_all as _html_find_all,
    find_by_id as _html_find_by_id,
    find_closest as _html_find_closest,
    get_children as _html_get_children,
    get_parent as _html_get_parent,
    get_tree as _html_get_tree,
    load_current_source as _html_load_source,
)
from ..engine.interrupt import mailbox
from ..models import BlockFieldModel, ProjectComponent
from .component_tools import list_blocks, list_project_components, render_block

logger = logging.getLogger("agentsite.chat_tools")


async def start_build(
    ctx: RunContext,
    prompt: str,
    page_slug: str = "home",
    audience: str = "",
    visual_tone: list[str] | None = None,
    direction_id: str | None = None,
    constraints: str = "",
) -> str:
    """Kick off generation of a page from a prompt.

    Use this when the user asks to build, create, or generate a new
    page or site. Returns the version number once the background task
    is scheduled — progress streams over the project's WebSocket.

    ALWAYS populate ``audience`` and ``visual_tone`` from the user's
    request when you can (e.g. a luxury booking landing page →
    audience="premium-charter customers",
    visual_tone=["luxury", "modern_minimal"]).  Empty values force the
    pipeline to guess and often produce off-brand output.

    Args:
        prompt: What the user wants built.
        page_slug: Page identifier (default ``"home"``).
        audience: Who the site is for, in plain language (e.g.
            "premium-charter customers"). Empty when the
            user hasn't said.
        visual_tone: Tone keywords from this fixed set:
            ``"editorial"``, ``"modern_minimal"``, ``"playful"``,
            ``"tech_utility"``, ``"luxury"``, ``"brutalist"``,
            ``"human"``. Pick 1-2.
        direction_id: When the user explicitly named a design direction
            (or the chat surfaced one), the id (e.g.
            ``"modern-minimal"``, ``"luxury-refined"``). When set,
            Prompture synthesises StyleSpec from the direction and
            skips the Designer agent — only use it when the user
            picked a direction.
        constraints: Free-text constraints (deadlines, must-use fonts,
            things to avoid). Empty when none.
    """
    deps: dict[str, Any] = ctx.deps
    project_id = deps.get("project_id")
    if not project_id:
        return "Error: no project_id in context"

    discovery_brief: dict[str, Any] | None = None
    if audience or visual_tone or constraints:
        discovery_brief = {
            "audience": audience,
            "tone": list(visual_tone or []),
            "constraints": constraints,
            "brand_mode": "pick_direction",
        }

    try:
        result = await start_generation_task(
            project_id,
            page_slug,
            prompt,
            project_repo=deps["project_repo"],
            page_repo=deps["page_repo"],
            version_repo=deps["version_repo"],
            agent_config_repo=deps["agent_config_repo"],
            agent_run_repo=deps["agent_run_repo"],
            pm=deps["pm"],
            model=deps.get("model", ""),
            provider_keys=deps.get("provider_keys"),
            project_component_repo=deps.get("project_component_repo"),
            discovery_brief=discovery_brief,
            direction_id=direction_id,
        )
    except ValueError as exc:
        return f"Error: {exc}"
    except Exception as exc:
        logger.exception("start_build failed")
        return f"Error starting build: {exc}"

    return json.dumps({
        "status": "started",
        "page_slug": page_slug,
        "version_number": result["version_number"],
        "audience": audience,
        "visual_tone": list(visual_tone or []),
        "direction_id": direction_id,
        "note": "Pipeline running. Progress is broadcast over the WebSocket.",
    })


def steer_build(ctx: RunContext, instruction: str) -> str:
    """Steer the currently-running generation with a tweak.

    Deposits the instruction into the in-memory mailbox the pipeline
    drains between phases. Use this when a build is already running
    and the user wants to refine it (e.g. "make the headline punchier").

    Args:
        instruction: Refinement text to inject into the pipeline.
    """
    project_id = ctx.deps.get("project_id")
    if not project_id:
        return "Error: no project_id in context"
    text = (instruction or "").strip()
    if not text:
        return "Error: instruction is empty"
    mailbox.deposit(project_id, text)
    return f"Steer deposited ({len(text)} chars). Pipeline will pick it up between phases."


async def list_pages(ctx: RunContext) -> str:
    """List all pages in the current project with their slugs and titles."""
    project_id = ctx.deps.get("project_id")
    page_repo = ctx.deps.get("page_repo")
    if not project_id or page_repo is None:
        return "Error: no project context"
    pages = await page_repo.list_by_project(project_id)
    return json.dumps(
        [{"slug": p.slug, "title": p.title, "prompt": p.prompt} for p in pages],
        indent=2,
    )


async def list_versions(ctx: RunContext, page_slug: str = "home") -> str:
    """List all versions of a page with their status and timestamps."""
    project_id = ctx.deps.get("project_id")
    page_repo = ctx.deps.get("page_repo")
    version_repo = ctx.deps.get("version_repo")
    if not project_id or page_repo is None or version_repo is None:
        return "Error: no project context"
    page = await page_repo.get_by_slug(project_id, page_slug)
    if page is None:
        return f"Error: page '{page_slug}' not found"
    versions = await version_repo.list_by_page(page.id)
    return json.dumps(
        [
            {
                "version": v.version_number,
                "status": v.status,
                "completed_at": v.completed_at,
                "files": list((v.files or {}).keys()),
            }
            for v in versions
        ],
        indent=2,
    )


async def read_page_file(
    ctx: RunContext,
    page_slug: str,
    path: str,
    version_number: int = 0,
) -> str:
    """Read a generated file from a page version.

    Args:
        page_slug: Page identifier (e.g. ``"home"``).
        path: File path within the version (e.g. ``"index.html"``).
        version_number: Version to read, or ``0`` for the latest.
    """
    project_id = ctx.deps.get("project_id")
    pm = ctx.deps.get("pm")
    page_repo = ctx.deps.get("page_repo")
    version_repo = ctx.deps.get("version_repo")
    if not project_id or pm is None or page_repo is None or version_repo is None:
        return "Error: no project context"

    page = await page_repo.get_by_slug(project_id, page_slug)
    if page is None:
        return f"Error: page '{page_slug}' not found"

    if version_number == 0:
        latest = await version_repo.get_latest(page.id)
        if latest is None:
            return f"Error: no versions yet for page '{page_slug}'"
        version_number = latest.version_number

    content = pm.read_version_file(project_id, page_slug, version_number, path)
    if content is None:
        return f"Error: file '{path}' not found in {page_slug} v{version_number}"
    return content


async def get_build_status(ctx: RunContext, page_slug: str = "home") -> str:
    """Check whether a build is currently running for a page."""
    project_id = ctx.deps.get("project_id")
    page_repo = ctx.deps.get("page_repo")
    version_repo = ctx.deps.get("version_repo")
    if not project_id or page_repo is None or version_repo is None:
        return "Error: no project context"
    page = await page_repo.get_by_slug(project_id, page_slug)
    if page is None:
        return json.dumps({"page_slug": page_slug, "exists": False})
    latest = await version_repo.get_latest(page.id)
    if latest is None:
        return json.dumps({"page_slug": page_slug, "exists": True, "has_versions": False})
    return json.dumps({
        "page_slug": page_slug,
        "version": latest.version_number,
        "status": latest.status,
        "error": latest.error,
        "completed_at": latest.completed_at,
    })


# ---------------------------------------------------------------------------
# Edit-mode tools — used when the user has the visual editor open with an
# element selected. The agent's only job here is to emit Patch tool-calls;
# the frontend intercepts `tool_use_stop` events and applies them via
# htmlstudio's `applyPatch`. Persistence to disk happens through the same
# `useVisualEdit` round-trip the inspector uses, so agent edits and human
# edits share one rail.
# ---------------------------------------------------------------------------


async def patch(
    ctx: RunContext,
    kind: Literal[
        "set-text", "set-link", "set-image", "set-style", "set-attributes", "set-outer-html"
    ],
    id: str,
    value: str | None = None,
    href: str | None = None,
    text: str | None = None,
    src: str | None = None,
    alt: str | None = None,
    styles: dict[str, str] | None = None,
    attributes: dict[str, str | None] | None = None,
    html: str | None = None,
) -> str:
    """Apply a visual edit to an element in the current page.

    Use this in edit mode to tweak what the user has selected. One call
    per logical change. The frontend applies the patch through htmlstudio
    and persists it — you do NOT need to call any other tool.

    Args:
        kind: Which kind of edit. Pick exactly one:
            - ``"set-text"`` — replace the text of a leaf element. Use ``value``.
            - ``"set-link"`` — update an ``<a>``'s href and label. Use ``href`` + ``text``.
            - ``"set-image"`` — update an ``<img>``'s src and alt. Use ``src`` + ``alt``.
            - ``"set-style"`` — merge inline styles. Use ``styles`` (e.g.
              ``{"color": "#2563eb", "font-size": "20px"}``). Empty string
              value removes a property.
            - ``"set-attributes"`` — set or remove HTML attributes. Use
              ``attributes`` (e.g. ``{"target": "_blank", "class": null}``;
              null removes).
            - ``"set-outer-html"`` — replace the element's entire markup.
              Use ``html``. The selected id is preserved on the replacement.
        id: The ``data-ve-id`` of the target element. ALWAYS use the
            ``id`` field from the [Edit mode — selected: ...] header in
            the user's message. Never invent ids.
        value: Plain text for ``set-text``. HTML-escaped automatically.
        href: New URL for ``set-link``.
        text: New label text for ``set-link``.
        src: New image URL for ``set-image``.
        alt: New alt text for ``set-image``.
        styles: CSS property→value map for ``set-style``. Use kebab-case
            (``"font-size"`` not ``fontSize``). Set a value to ``""`` to
            remove that property.
        attributes: HTML attribute map for ``set-attributes``. ``null``
            removes the attribute.
        html: Full replacement markup for ``set-outer-html``.

    Returns:
        A JSON blob with the patch payload. The frontend applies it
        immediately and persists to disk; the user sees the change without
        any further action from you.
    """
    payload: dict[str, Any] = {"kind": kind, "id": id}
    for k, v in (
        ("value", value),
        ("href", href),
        ("text", text),
        ("src", src),
        ("alt", alt),
        ("styles", styles),
        ("attributes", attributes),
        ("html", html),
    ):
        if v is not None:
            payload[k] = v
    return json.dumps({"queued": True, "patch": payload})


# ---------------------------------------------------------------------------
# Registries — used by the chat endpoint
# ---------------------------------------------------------------------------

chat_registry = ToolRegistry()
chat_registry.register(start_build)
chat_registry.register(steer_build)
chat_registry.register(list_pages)
chat_registry.register(list_versions)
chat_registry.register(read_page_file)
chat_registry.register(get_build_status)

# ---------------------------------------------------------------------------
# Edit-mode discovery tools — let the agent reason about element relationships
# before patching. All read-only. They run BeautifulSoup against the current
# on-disk source so the agent can do things like "find every button in the
# hero section" without round-tripping a query through the iframe bridge.
# ---------------------------------------------------------------------------


def _edit_source(ctx: RunContext) -> str | None:
    """Load the HTML of the version the user is currently editing.

    Looks at ``ctx.deps['edit_context']`` (populated by chat.py when the
    user is in edit mode) for the slug + version, then reads via the
    PageManager.
    """
    edit_ctx = ctx.deps.get("edit_context") or {}
    if not edit_ctx.get("mode"):
        return None
    project_id = ctx.deps.get("project_id")
    slug = ctx.deps.get("current_page_slug")
    version = edit_ctx.get("version")
    pm = ctx.deps.get("pm")
    if not (project_id and slug and version and pm):
        return None
    try:
        return _html_load_source(pm, project_id, slug, int(version))
    except FileNotFoundError:
        return None


async def find(ctx: RunContext, selector: str, limit: int = 20) -> str:
    """Find elements in the current page matching a CSS selector.

    Use this BEFORE patching when the user says "all of the buttons" or
    "every card in the pricing section" — you need the list of ids to
    issue patches against. Only elements that already carry a
    ``data-ve-id`` are returned.

    Args:
        selector: Any CSS selector, e.g. ``"button"``, ``"section h2"``,
            ``"[data-ve-block=hero] a"``, ``".cta"``.
        limit: Max results (default 20). Keep the agent from drowning
            the context with hundreds of matches.

    Returns:
        JSON list of ``{id, tag, kind, attributes, text?, block?}``.
        Empty list when nothing matches or no edit context.
    """
    source = _edit_source(ctx)
    if source is None:
        return json.dumps({"error": "Not in edit mode — no source to query"})
    matches = _html_find_all(source, selector, limit=int(limit))
    return json.dumps(matches)


async def get_tree(ctx: RunContext, id: str, depth: int = 2) -> str:
    """Get a structural tree of an element and its descendants.

    Use this to understand the layout before bulk edits — e.g. before
    "make all the section headings the same color" you'd call
    ``get_tree('p-0', depth=3)`` to see what's inside.

    Args:
        id: ``data-ve-id`` of the root element for the tree.
        depth: How many levels deep to traverse (default 2, max 5).
    """
    source = _edit_source(ctx)
    if source is None:
        return json.dumps({"error": "Not in edit mode — no source to query"})
    tree = _html_get_tree(source, id, max_depth=min(int(depth), 5))
    if tree is None:
        return json.dumps({"error": f"Element not found: {id}"})
    return json.dumps(tree)


async def find_closest(ctx: RunContext, from_id: str, selector: str) -> str:
    """Walk up from ``from_id`` to the nearest ancestor matching ``selector``.

    Example: ``find_closest('p-0-1-2-3', '[data-ve-block]')`` returns
    the block container that owns the selected element.
    """
    source = _edit_source(ctx)
    if source is None:
        return json.dumps({"error": "Not in edit mode — no source to query"})
    found = _html_find_closest(source, from_id, selector)
    return json.dumps(found) if found else json.dumps({"error": "No matching ancestor"})


async def get_parent(ctx: RunContext, id: str) -> str:
    """Immediate parent element of ``id``."""
    source = _edit_source(ctx)
    if source is None:
        return json.dumps({"error": "Not in edit mode — no source to query"})
    p = _html_get_parent(source, id)
    return json.dumps(p) if p else json.dumps({"error": "No parent (root)"})


async def get_children(ctx: RunContext, id: str) -> str:
    """Direct element children of ``id``."""
    source = _edit_source(ctx)
    if source is None:
        return json.dumps({"error": "Not in edit mode — no source to query"})
    return json.dumps(_html_get_children(source, id))


# ---------------------------------------------------------------------------
# Component-library tools (list_blocks / render_block /
# list_project_components) live in agents/component_tools.py — shared with
# the generation-time developer agent and progressive section agents — and
# are imported above + registered on edit_registry below.
# ---------------------------------------------------------------------------


async def extract_component(
    ctx: RunContext,
    target_id: str,
    name: str,
    slug: str,
) -> str:
    """Save the selected element as a reusable project component.

    Use this when:
      - the user says 'save this as a component' / 'make this reusable'
      - you spot 3+ near-identical sections in `get_tree` output and
        want to propose extraction so the user can edit one definition
        and have all instances follow

    Args:
        target_id: `data-ve-id` of the element to extract.
        name: Human-readable display name (e.g. 'Pricing Card').
        slug: kebab-case identifier (e.g. 'pricing-card'). Must be
            unique within the project.

    Returns:
        JSON with the saved component's id + extracted field count.
        After this fires, the new component shows up in the user's
        block palette and is insertable everywhere.
    """
    project_id = ctx.deps.get("project_id")
    slug_repo = ctx.deps.get("project_component_repo")
    page_slug = ctx.deps.get("current_page_slug")
    edit_ctx = ctx.deps.get("edit_context") or {}
    if not (project_id and slug_repo and page_slug):
        return json.dumps({"error": "No project context"})

    source = _edit_source(ctx)
    if source is None:
        return json.dumps({"error": "Not in edit mode — no source to extract from"})

    # Pull the target's outer HTML directly from the on-disk source.
    info = _html_find_by_id(source, target_id)
    if info is None:
        return json.dumps({"error": f"target_id not found in current source: {target_id}"})

    # Re-walk source to grab the *raw* outer HTML — html_query doesn't
    # surface that today, so we slice it ourselves via BeautifulSoup.
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(source, "html.parser")
    target = soup.find(attrs={"data-ve-id": target_id})
    if target is None:
        return json.dumps({"error": "Element lookup mismatch"})
    source_html = str(target)

    # Check slug collision before doing the work.
    existing = await slug_repo.get_by_slug(project_id, slug)
    if existing is not None:
        return json.dumps({"error": f"slug '{slug}' already exists in this project"})

    draft = _extract_component(source_html, default_name=name, default_slug=slug)
    version = edit_ctx.get("version")

    component = ProjectComponent(
        project_id=project_id,
        slug=slug,
        name=name,
        category="custom",
        description="",
        thumbnail="🧱",
        template=draft["template"],
        fields=[BlockFieldModel(**f) for f in draft["fields"]],
        source_instance_id=target_id,
        source_page_slug=page_slug,
        source_version=int(version) if version else None,
    )
    saved = await slug_repo.create(component)
    logger.info(
        "Agent extracted component: project=%s slug=%s from=%s fields=%d",
        project_id, slug, target_id, len(saved.fields),
    )
    return json.dumps({
        "ok": True,
        "component_id": saved.id,
        "slug": saved.slug,
        "name": saved.name,
        "fields_count": len(saved.fields),
        "note": "Component saved to project library. Insert via render_block(slug, config) → patch(set-outer-html).",
    })


# Edit mode: agent can patch the selected element, query structure,
# insert pre-built blocks, AND save / use project components.
# start_build / steer_build deliberately excluded — rebuilding the page
# is the opposite of what an edit-mode user wants.
edit_registry = ToolRegistry()
edit_registry.register(patch)
edit_registry.register(read_page_file)
edit_registry.register(find)
edit_registry.register(get_tree)
edit_registry.register(find_closest)
edit_registry.register(get_parent)
edit_registry.register(get_children)
edit_registry.register(list_blocks)
edit_registry.register(render_block)
edit_registry.register(list_project_components)
edit_registry.register(extract_component)
