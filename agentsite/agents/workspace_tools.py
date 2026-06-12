"""Workspace-scoped tools for project-mode agents (resident developer/reviewer).

Unlike the mockup-mode tools (which target a page-version directory), these
operate on the project workspace — a real scaffolded codebase. The registry
adds targeted editing (edit_file), search, and a sandboxed build runner so
review iterations are cheap diffs instead of whole-file regeneration.

Expected ctx.deps keys:
    workspace_dir     Path — workspace root (all paths scoped here)
    template          TemplateInfo — manifest of the active template
    written_files     list[str] — mutated in place as files change
    on_file_written   callable(rel_path) | None
    on_preview_update callable(rel_path, html) | None — static templates only
    emit_event        async callable(type, data) | None — WS bridge for builds
    assets_dir        Path — uploads dir (generate_image target)
    asset_rel_prefix  str — rel prefix for generated image src paths
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from prompture import RunContext, ToolRegistry

from .tools import generate_image

logger = logging.getLogger("agentsite.workspace_tools")

_EXCLUDED_DIRS = {"node_modules", ".git", "dist", ".agentsite", "__pycache__"}
_MAX_READ_CHARS = 64_000
_MAX_SEARCH_RESULTS = 100
_SEARCHABLE_EXTENSIONS = {
    ".html", ".htm", ".css", ".scss", ".js", ".jsx", ".ts", ".tsx", ".json",
    ".md", ".txt", ".svg", ".xml", ".yml", ".yaml", ".cjs", ".mjs",
}


def _workspace(ctx: RunContext) -> Path:
    return ctx.deps["workspace_dir"]


def _resolve(ctx: RunContext, path: str) -> Path | None:
    """Resolve a relative path inside the workspace, or None on traversal."""
    target = _workspace(ctx) / path
    try:
        target.resolve().relative_to(_workspace(ctx).resolve())
    except ValueError:
        return None
    return target


def _is_excluded(rel: Path) -> bool:
    return any(part in _EXCLUDED_DIRS for part in rel.parts)


def _notify_write(ctx: RunContext, rel_path: str, content: str) -> None:
    written: list[str] = ctx.deps.setdefault("written_files", [])
    if rel_path not in written:
        written.append(rel_path)
    ctx.deps["build_dirty"] = True

    on_file_written = ctx.deps.get("on_file_written")
    if on_file_written:
        on_file_written(rel_path)

    template = ctx.deps.get("template")
    if (
        rel_path.endswith(".html")
        and template is not None
        and getattr(template, "kind", "static") == "static"
    ):
        on_preview = ctx.deps.get("on_preview_update")
        if on_preview:
            on_preview(rel_path, content)


def list_files(ctx: RunContext) -> str:
    """List all files in the project workspace with sizes."""
    ws = _workspace(ctx)
    if not ws.exists():
        return "Workspace is empty."
    lines: list[str] = []
    for f in sorted(ws.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(ws)
        if _is_excluded(rel):
            continue
        lines.append(f"{str(rel).replace(chr(92), '/')} ({f.stat().st_size:,} bytes)")
    return "\n".join(lines) if lines else "Workspace is empty."


def read_file(ctx: RunContext, path: str) -> str:
    """Read a file from the workspace.

    Args:
        path: Relative file path within the workspace.
    """
    target = _resolve(ctx, path)
    if target is None:
        return f"Error: path '{path}' escapes the workspace"
    if not target.exists() or not target.is_file():
        return f"Error: file '{path}' not found. Call list_files to see what exists."
    content = target.read_text(encoding="utf-8", errors="replace")
    if len(content) > _MAX_READ_CHARS:
        return (
            content[:_MAX_READ_CHARS]
            + f"\n\n...(truncated — file is {len(content):,} chars; "
            "use search_files to locate specific sections)"
        )
    return content


def write_file(ctx: RunContext, path: str, content: str) -> str:
    """Create or fully overwrite a file in the workspace.

    Prefer edit_file for changes to existing files. Use write_file for new
    files or full rewrites.

    Args:
        path: Relative file path within the workspace.
        content: Complete file content.
    """
    target = _resolve(ctx, path)
    if target is None:
        return f"Error: path '{path}' escapes the workspace"

    rel = str(Path(path)).replace("\\", "/")
    if _is_excluded(Path(rel)):
        return f"Error: '{path}' is inside a managed directory (node_modules/dist/.git) — not writable"

    template = ctx.deps.get("template")
    warning = ""
    if template is not None and rel in getattr(template, "protected_paths", []):
        warning = (
            f" WARNING: '{rel}' is a protected scaffold file — only change it "
            "when strictly necessary, and keep edits minimal."
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    _notify_write(ctx, rel, content)
    return f"Written: {rel} ({len(content)} bytes).{warning}"


def edit_file(
    ctx: RunContext, path: str, old_string: str, new_string: str, replace_all: bool = False
) -> str:
    """Replace an exact string in an existing file (targeted edit).

    old_string must match the file content exactly (including whitespace)
    and must be unique unless replace_all is true. Include enough
    surrounding lines to make the match unique.

    Args:
        path: Relative file path within the workspace.
        old_string: Exact text to find.
        new_string: Replacement text.
        replace_all: Replace every occurrence instead of requiring uniqueness.
    """
    target = _resolve(ctx, path)
    if target is None:
        return f"Error: path '{path}' escapes the workspace"
    if not target.exists() or not target.is_file():
        return f"Error: file '{path}' not found. Call list_files to see what exists."

    content = target.read_text(encoding="utf-8", errors="replace")
    count = content.count(old_string)
    if count == 0:
        return (
            f"Error: old_string not found in '{path}'. Read the file again — "
            "the content may differ from what you expect (check whitespace)."
        )
    if count > 1 and not replace_all:
        return (
            f"Error: old_string appears {count} times in '{path}'. Add more "
            "surrounding context to make it unique, or set replace_all=true."
        )

    new_content = content.replace(old_string, new_string)
    target.write_text(new_content, encoding="utf-8")
    rel = str(Path(path)).replace("\\", "/")
    _notify_write(ctx, rel, new_content)
    replaced = count if replace_all else 1
    return f"Edited {rel}: {replaced} replacement(s) made."


def search_files(ctx: RunContext, pattern: str, file_glob: str = "**/*") -> str:
    """Search workspace files with a regex, returning 'path:line: text' matches.

    Args:
        pattern: Regular expression to search for.
        file_glob: Glob to limit the search (e.g. 'src/**/*.jsx').
    """
    try:
        rx = re.compile(pattern)
    except re.error as exc:
        return f"Error: invalid regex: {exc}"

    ws = _workspace(ctx)
    results: list[str] = []
    for f in sorted(ws.glob(file_glob)):
        if not f.is_file() or f.suffix.lower() not in _SEARCHABLE_EXTENSIONS:
            continue
        rel = f.relative_to(ws)
        if _is_excluded(rel):
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if rx.search(line):
                results.append(f"{str(rel).replace(chr(92), '/')}:{lineno}: {line.strip()[:200]}")
                if len(results) >= _MAX_SEARCH_RESULTS:
                    return "\n".join(results) + f"\n...(capped at {_MAX_SEARCH_RESULTS} matches)"
    return "\n".join(results) if results else "No matches."


async def run_command(ctx: RunContext, command: str) -> str:
    """Run a project command: 'install' (dependencies) or 'build' (production build).

    Build output (including compile errors) is returned — read it and fix
    any errors with targeted edits, then build again.

    Args:
        command: One of 'install', 'build'.
    """
    from ..engine import workspace_runner as runner

    template = ctx.deps.get("template")
    if command not in ("install", "build"):
        return "Error: command must be 'install' or 'build'."
    if template is None or template.kind != "node":
        return "This template has no build step — files are served as-is. Nothing to do."

    ws = _workspace(ctx)
    emit = ctx.deps.get("emit_event")
    if emit:
        await emit("build_started", {"command": command})

    if command == "install":
        result = await runner.ensure_install(ws, template, force=True)
    else:
        result = await runner.build_workspace(ws, template)

    if result is None:
        return "Nothing to run for this template."

    ctx.deps["last_build_ok"] = result.ok
    if result.ok and command == "build":
        ctx.deps["build_dirty"] = False

    if emit:
        await emit("build_finished", {
            "ok": result.ok,
            "duration_s": result.duration_s,
            "output_tail": result.tail[-1500:],
        })

    status = "OK" if result.ok else "FAILED"
    return f"{command} {status} (rc={result.returncode}, {result.duration_s}s)\n\n{result.tail}"


def list_uploads(ctx: RunContext) -> str:
    """List user-uploaded files available in the workspace uploads directory."""
    template = ctx.deps.get("template")
    ws = _workspace(ctx)
    rel_dir = "public/uploads" if (template is not None and template.kind == "node") else "uploads"
    uploads = ws / rel_dir
    if not uploads.exists():
        return "No uploads."
    files = [f for f in sorted(uploads.iterdir()) if f.is_file() and f.name != ".gitkeep"]
    if not files:
        return "No uploads."
    lines = [
        f"{rel_dir}/{f.name} ({f.stat().st_size:,} bytes) — reference as 'uploads/{f.name}'"
        for f in files
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Registries
# ---------------------------------------------------------------------------

dev_workspace_tools = ToolRegistry()
dev_workspace_tools.register(list_files)
dev_workspace_tools.register(read_file)
dev_workspace_tools.register(write_file)
dev_workspace_tools.register(edit_file)
dev_workspace_tools.register(search_files)
dev_workspace_tools.register(run_command)
dev_workspace_tools.register(list_uploads)
dev_workspace_tools.register(generate_image)

reviewer_workspace_tools = ToolRegistry()
reviewer_workspace_tools.register(list_files)
reviewer_workspace_tools.register(read_file)
reviewer_workspace_tools.register(search_files)
reviewer_workspace_tools.register(list_uploads)
