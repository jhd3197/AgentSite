"""Agent tools for filesystem operations, image generation, and asset management."""

from __future__ import annotations

import base64
import json
import logging
import os
import uuid
from pathlib import Path

from prompture import RunContext, ToolRegistry
from prompture.drivers.img_gen_registry import get_img_gen_driver_for_model

logger = logging.getLogger("agentsite.tools")


def write_file(ctx: RunContext, path: str, content: str) -> str:
    """Write content to a file within the project version directory.

    Args:
        path: Relative file path within the version directory.
        content: Full file content to write.
    """
    # Phase 3 — pre-flight gate. If `_preflight_required` is set in deps,
    # block the write until every required guide has been read (or attempted).
    # Returns an actionable error string so the model can recover by reading
    # the missing guides and retrying. Once satisfied, the gate self-disarms.
    required = ctx.deps.get("_preflight_required")
    if required:
        attempted = ctx.deps.setdefault("_preflight_read", set())
        missing = [g for g in required if g not in attempted]
        if missing:
            return (
                "PRE-FLIGHT REQUIRED — before calling write_file you must call "
                f"read_guide() for each of: {missing}. "
                "(These guides anchor cross-page consistency. Calling read_guide "
                "satisfies the gate even if the guide does not exist yet — the "
                "tool simply returns 'not found' and the gate clears.) "
                "Retry your write_file after reading them."
            )
        # Gate satisfied — disarm so we only check once per run.
        ctx.deps.pop("_preflight_required", None)

    version_dir: Path = ctx.deps["version_dir"]
    target = version_dir / path

    # Prevent path traversal
    try:
        target.resolve().relative_to(version_dir.resolve())
    except ValueError:
        return f"Error: path '{path}' escapes project directory"

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")

    # Track written files
    written: list[str] = ctx.deps.setdefault("written_files", [])
    if path not in written:
        written.append(path)

    # Fire callback if available
    on_file_written = ctx.deps.get("on_file_written")
    if on_file_written:
        on_file_written(path)

    # Phase 6 — srcdoc live preview. For canonical HTML pages, hand the
    # rendered body to the preview callback so the iframe can swap to
    # srcdoc mode without waiting for a server round-trip.
    if path.endswith(".html"):
        on_preview = ctx.deps.get("on_preview_update")
        if on_preview:
            on_preview(path, content)

    return f"Written: {path} ({len(content)} bytes)"


def read_file(ctx: RunContext, path: str) -> str:
    """Read a file from the project version directory.

    Args:
        path: Relative file path within the version directory.
    """
    version_dir: Path = ctx.deps["version_dir"]
    target = version_dir / path

    try:
        target.resolve().relative_to(version_dir.resolve())
    except ValueError:
        return f"Error: path '{path}' escapes project directory"

    if not target.exists():
        return f"Error: file '{path}' not found"

    return target.read_text(encoding="utf-8")


def list_files(ctx: RunContext) -> str:
    """List all files in the project version directory."""
    version_dir: Path = ctx.deps["version_dir"]

    if not version_dir.exists():
        return "No files generated yet."

    files = sorted(str(f.relative_to(version_dir)) for f in version_dir.rglob("*") if f.is_file())
    if not files:
        return "No files generated yet."

    return json.dumps(files, indent=2)


# ---------------------------------------------------------------------------
# Guide tools (project knowledge base)
# ---------------------------------------------------------------------------

_ALLOWED_GUIDE_FILENAMES = {
    "design-system.md",
    "style.json",
    "architecture.md",
    "component-guide.md",
    "site-plan.json",
    "asset-manifest.md",
    "copy-guide.md",
    "seo-config.md",
    "accessibility-report.md",
    "animation-guide.md",
}


def write_guide(ctx: RunContext, filename: str, content: str) -> str:
    """Write a guide file to the project knowledge base.

    Guides persist across generations so agents can build on prior knowledge.

    Args:
        filename: One of: design-system.md, style.json, architecture.md, component-guide.md
        content: Guide content to write.
    """
    if filename not in _ALLOWED_GUIDE_FILENAMES:
        return f"Error: filename must be one of {sorted(_ALLOWED_GUIDE_FILENAMES)}"

    project_dir: Path = ctx.deps["project_dir"]
    guides_dir = project_dir / "guides"
    guides_dir.mkdir(parents=True, exist_ok=True)
    target = guides_dir / filename

    # Prevent path traversal
    try:
        target.resolve().relative_to(guides_dir.resolve())
    except ValueError:
        return f"Error: path '{filename}' escapes guides directory"

    target.write_text(content, encoding="utf-8")
    return f"Guide written: {filename} ({len(content)} bytes)"


def read_guide(ctx: RunContext, filename: str) -> str:
    """Read a guide file from the project knowledge base.

    Args:
        filename: Guide filename to read.
    """
    # Phase 3 — pre-flight: record the attempt regardless of whether the guide
    # exists. The act of asking for it is what satisfies the gate.
    attempted = ctx.deps.setdefault("_preflight_read", set())
    attempted.add(filename)

    project_dir: Path = ctx.deps["project_dir"]
    guides_dir = project_dir / "guides"
    target = guides_dir / filename

    try:
        target.resolve().relative_to(guides_dir.resolve())
    except ValueError:
        return f"Error: path '{filename}' escapes guides directory"

    if not target.exists():
        return f"Guide '{filename}' not found. Available guides: {list_guides(ctx)}"

    return target.read_text(encoding="utf-8")


def list_guides(ctx: RunContext) -> str:
    """List all guide files in the project knowledge base."""
    project_dir: Path = ctx.deps["project_dir"]
    guides_dir = project_dir / "guides"

    if not guides_dir.exists():
        return "No guides yet."

    files = sorted(f.name for f in guides_dir.iterdir() if f.is_file())
    if not files:
        return "No guides yet."

    return json.dumps(files, indent=2)


# ---------------------------------------------------------------------------
# Image generation and library tools
# ---------------------------------------------------------------------------

_ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def generate_image(ctx: RunContext, prompt: str, filename: str) -> str:
    """Generate an image using AI and save it to the project library.

    Args:
        prompt: Description of the image to generate.
        filename: Filename for the image (e.g. hero-bg.png, team-photo.jpg).
    """
    assets_dir: Path | None = ctx.deps.get("assets_dir")
    project_id: str | None = ctx.deps.get("project_id")

    if not assets_dir or not project_id:
        return "Error: assets_dir or project_id not available in context"

    ext = Path(filename).suffix.lower()
    if ext not in _ALLOWED_IMAGE_EXTENSIONS:
        return f"Error: extension '{ext}' not allowed. Use one of: {sorted(_ALLOWED_IMAGE_EXTENSIONS)}"

    if not os.environ.get("OPENAI_API_KEY"):
        return "Error: OPENAI_API_KEY not set — cannot generate images"

    try:
        driver = get_img_gen_driver_for_model("openai/dall-e-3")
        resp = driver.generate_image(prompt, {"size": "1024x1024", "n": 1})
        images = resp.get("images") or []
        if not images:
            return "Error: image generation returned no images"
        img_data = base64.b64decode(images[0].data)
    except Exception as exc:
        logger.warning("Image generation failed: %s", exc)
        return f"Error generating image: {exc}"

    # Save with UUID prefix for uniqueness
    asset_id = uuid.uuid4().hex[:8]
    stem = Path(filename).stem
    safe_name = f"{asset_id}-{stem}{ext}"

    assets_dir.mkdir(parents=True, exist_ok=True)
    target = assets_dir / safe_name
    target.write_bytes(img_data)

    logger.info("Generated image saved: %s (%d bytes)", safe_name, len(img_data))

    # Fire callback for WebSocket event
    on_asset_created = ctx.deps.get("on_asset_created")
    if on_asset_created:
        on_asset_created(safe_name)

    # Workspace tools override the reference prefix (e.g. "uploads/")
    prefix = ctx.deps.get("asset_rel_prefix", "assets/")
    return f"{prefix}{safe_name}"


def list_library(ctx: RunContext) -> str:
    """List all images and assets available in the project library."""
    assets_dir: Path | None = ctx.deps.get("assets_dir")
    project_id: str | None = ctx.deps.get("project_id")

    if not assets_dir or not project_id:
        return "Error: assets_dir or project_id not available in context"

    if not assets_dir.exists():
        return json.dumps({"assets": [], "message": "Library is empty"})

    assets = []
    for f in sorted(assets_dir.iterdir()):
        if f.is_file():
            assets.append({
                "filename": f.name,
                "path": f"assets/{f.name}",
                "size": f.stat().st_size,
            })

    return json.dumps({"assets": assets, "count": len(assets)})


# ---------------------------------------------------------------------------
# Shared tool registries
# ---------------------------------------------------------------------------

registry = ToolRegistry()
registry.register(write_file)
registry.register(read_file)
registry.register(list_files)

# Designer: guide tools only (no file write/read for site files)
designer_tools = ToolRegistry()
designer_tools.register(write_guide)
designer_tools.register(read_guide)
designer_tools.register(list_guides)

# Developer: all file tools + guide tools + image generation
dev_tools = ToolRegistry()
dev_tools.register(write_file)
dev_tools.register(read_file)
dev_tools.register(list_files)
dev_tools.register(read_guide)
dev_tools.register(write_guide)
dev_tools.register(list_guides)
dev_tools.register(generate_image)
dev_tools.register(list_library)

# Reviewer: read-only file tools + read-only guide tools
reviewer_tools = ToolRegistry()
reviewer_tools.register(read_file)
reviewer_tools.register(list_files)
reviewer_tools.register(read_guide)
reviewer_tools.register(list_guides)

# ---------------------------------------------------------------------------
# Specialist agent tool registries
# ---------------------------------------------------------------------------

# Markup: write/read files + guides + library (for image paths)
markup_tools = ToolRegistry()
markup_tools.register(write_file)
markup_tools.register(read_file)
markup_tools.register(list_files)
markup_tools.register(read_guide)
markup_tools.register(list_guides)
markup_tools.register(list_library)

# Style: write/read files + guides (reads design tokens)
style_tools = ToolRegistry()
style_tools.register(write_file)
style_tools.register(read_file)
style_tools.register(read_guide)
style_tools.register(list_guides)

# Script: write/read files + guides (reads architecture for DOM structure)
script_tools = ToolRegistry()
script_tools.register(write_file)
script_tools.register(read_file)
script_tools.register(list_files)
script_tools.register(read_guide)
script_tools.register(list_guides)

# Image: generate images + library management + guides
image_tools = ToolRegistry()
image_tools.register(generate_image)
image_tools.register(list_library)
image_tools.register(write_guide)
image_tools.register(read_guide)
image_tools.register(list_guides)

# ---------------------------------------------------------------------------
# Post-processing agent tool registries
# ---------------------------------------------------------------------------

# Copywriter: read/write files + guides
copywriter_tools = ToolRegistry()
copywriter_tools.register(write_file)
copywriter_tools.register(read_file)
copywriter_tools.register(list_files)
copywriter_tools.register(read_guide)
copywriter_tools.register(write_guide)
copywriter_tools.register(list_guides)

# SEO: read/write files + guides
seo_tools = ToolRegistry()
seo_tools.register(write_file)
seo_tools.register(read_file)
seo_tools.register(list_files)
seo_tools.register(read_guide)
seo_tools.register(write_guide)
seo_tools.register(list_guides)

# Accessibility: read/write files + guides
accessibility_tools = ToolRegistry()
accessibility_tools.register(write_file)
accessibility_tools.register(read_file)
accessibility_tools.register(list_files)
accessibility_tools.register(read_guide)
accessibility_tools.register(write_guide)
accessibility_tools.register(list_guides)

# Animation: read/write files + guides
animation_tools = ToolRegistry()
animation_tools.register(write_file)
animation_tools.register(read_file)
animation_tools.register(list_files)
animation_tools.register(read_guide)
animation_tools.register(write_guide)
animation_tools.register(list_guides)
