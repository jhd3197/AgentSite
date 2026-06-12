"""Project workspace templates — registry, manifests, and scaffolding.

A template is a directory under ``agentsite/templates/<id>/`` containing::

    manifest.json   machine-readable build/preview contract
    TEMPLATE.md     structure conventions the dev agent reads first
    prompts.json    starter prompts for the dashboard gallery
    scaffold/       real files copied verbatim into a new workspace

Scaffolds are copied deterministically — no LLM tokens are spent on
boilerplate like package.json or vite.config.js.
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from pydantic import BaseModel, Field

logger = logging.getLogger("agentsite.templates")


class TemplateInfo(BaseModel):
    """Parsed manifest.json for a workspace template."""

    id: str
    name: str
    description: str = ""
    kind: str = "static"  # "static" (no build) | "node" (npm install + build)
    install_cmd: list[str] | None = None
    build_cmd: list[str] | None = None
    dev_cmd: list[str] | None = None
    output_dir: str | None = None  # build output dir to serve (None = workspace root)
    entry: str = "index.html"
    tokens_path: str = "styles/tokens.css"  # where Designer tokens get written
    tokens_format: str = "css-vars"  # "css-vars" | "tailwind4"
    protected_paths: list[str] = Field(default_factory=list)
    requires_tools: bool = True


def _root() -> Path:
    return Path(__file__).parent


def template_dir(template_id: str) -> Path:
    return _root() / template_id


def list_templates() -> list[TemplateInfo]:
    """Return all valid templates bundled with AgentSite."""
    templates: list[TemplateInfo] = []
    if not _root().exists():
        return templates
    for d in sorted(_root().iterdir()):
        manifest = d / "manifest.json"
        if not (d.is_dir() and manifest.exists()):
            continue
        try:
            templates.append(TemplateInfo.model_validate_json(manifest.read_text(encoding="utf-8")))
        except Exception:
            logger.warning("Invalid template manifest: %s", manifest, exc_info=True)
    return templates


def find_template(template_id: str | None) -> TemplateInfo | None:
    """Find a template by id, or None."""
    if not template_id:
        return None
    manifest = template_dir(template_id) / "manifest.json"
    if not manifest.exists():
        return None
    try:
        return TemplateInfo.model_validate_json(manifest.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Invalid template manifest: %s", manifest, exc_info=True)
        return None


def read_template_doc(template_id: str) -> str:
    """Return TEMPLATE.md content (the structure contract), or empty string."""
    doc = template_dir(template_id) / "TEMPLATE.md"
    if not doc.exists():
        return ""
    return doc.read_text(encoding="utf-8")


def read_starter_prompts(template_id: str) -> list[dict]:
    """Return the template's starter prompts ([{id, title, prompt}])."""
    path = template_dir(template_id) / "prompts.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def scaffold_workspace(template_id: str, dest: Path) -> list[str]:
    """Copy a template's scaffold into ``dest``. Returns relative file paths.

    Raises ValueError when the template or its scaffold directory is missing.
    """
    src = template_dir(template_id) / "scaffold"
    if not src.exists():
        raise ValueError(f"Template '{template_id}' has no scaffold directory")

    dest.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest, dirs_exist_ok=True)

    return sorted(
        str(f.relative_to(dest)).replace("\\", "/") for f in dest.rglob("*") if f.is_file()
    )
