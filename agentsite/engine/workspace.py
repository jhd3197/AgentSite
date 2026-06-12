"""Project-mode workspace management: scaffolding, files, git checkpoints, export.

A workspace is a real project root at ``{project_dir}/workspace/`` created
from a template scaffold. The filesystem is the shared state between agents;
versioning happens via git commits (checkpoints) instead of v1/v2 dir copies.
"""

from __future__ import annotations

import io
import json
import logging
import shutil
import subprocess
import zipfile
from pathlib import Path

from ..config import settings
from ..templates import TemplateInfo, find_template, scaffold_workspace

logger = logging.getLogger("agentsite.workspace")

# Directories never exposed to agents, never zipped, never captured to DB
EXCLUDED_DIRS = {"node_modules", ".git", "dist", ".agentsite", "__pycache__"}

_TEXT_EXTENSIONS = {
    ".html", ".htm", ".css", ".scss", ".js", ".jsx", ".ts", ".tsx", ".json",
    ".md", ".txt", ".svg", ".xml", ".yml", ".yaml", ".env", ".gitignore",
    ".cjs", ".mjs", ".toml", ".webmanifest",
}

_GIT_IDENTITY = ["-c", "user.name=AgentSite", "-c", "user.email=agent@agentsite.local"]


def _is_text_file(path: Path) -> bool:
    return path.suffix.lower() in _TEXT_EXTENSIONS or path.name in (".gitignore", ".gitkeep")


class WorkspaceManager:
    """Manages a single project's workspace directory."""

    def __init__(self, project_dir: Path) -> None:
        self._project_dir = project_dir
        self.workspace_dir = project_dir / "workspace"
        self._meta_dir = self.workspace_dir / ".agentsite"

    # -- lifecycle -----------------------------------------------------

    def exists(self) -> bool:
        return (self._meta_dir / "template.json").exists()

    @property
    def template_id(self) -> str | None:
        marker = self._meta_dir / "template.json"
        if not marker.exists():
            return None
        try:
            return json.loads(marker.read_text(encoding="utf-8")).get("template_id")
        except Exception:
            return None

    def template(self) -> TemplateInfo | None:
        return find_template(self.template_id)

    def scaffold(self, template: TemplateInfo) -> list[str]:
        """Create the workspace from a template scaffold and git-init it."""
        files = scaffold_workspace(template.id, self.workspace_dir)
        self._meta_dir.mkdir(parents=True, exist_ok=True)
        (self._meta_dir / "template.json").write_text(
            json.dumps({"template_id": template.id}), encoding="utf-8"
        )
        self._git_init()
        self.checkpoint(f"scaffold: {template.id}")
        logger.info(
            "Scaffolded workspace from '%s' (%d files) at %s",
            template.id, len(files), self.workspace_dir,
        )
        return files

    # -- file operations -----------------------------------------------

    def safe_path(self, rel_path: str) -> Path:
        """Resolve a relative path inside the workspace; raises on traversal."""
        target = self.workspace_dir / rel_path
        target.resolve().relative_to(self.workspace_dir.resolve())
        return target

    def read_file(self, rel_path: str) -> str | None:
        try:
            target = self.safe_path(rel_path)
        except ValueError:
            return None
        if not target.exists() or not target.is_file():
            return None
        return target.read_text(encoding="utf-8", errors="replace")

    def write_file(self, rel_path: str, content: str) -> None:
        target = self.safe_path(rel_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def write_bytes(self, rel_path: str, data: bytes) -> None:
        target = self.safe_path(rel_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def list_files(self) -> list[str]:
        """All workspace files, excluding node_modules/.git/dist/.agentsite."""
        if not self.workspace_dir.exists():
            return []
        out: list[str] = []
        for f in self.workspace_dir.rglob("*"):
            if not f.is_file():
                continue
            rel = f.relative_to(self.workspace_dir)
            if any(part in EXCLUDED_DIRS for part in rel.parts):
                continue
            out.append(str(rel).replace("\\", "/"))
        return sorted(out)

    def file_tree(self) -> str:
        """Pretty file listing with sizes, for agent context."""
        lines: list[str] = []
        for rel in self.list_files():
            size = (self.workspace_dir / rel).stat().st_size
            lines.append(f"{rel} ({size:,} bytes)")
        return "\n".join(lines) if lines else "(workspace is empty)"

    def collect_files_content(self, max_kb: int | None = None) -> dict[str, str]:
        """Text file contents for DB capture / the frontend code view.

        Skips binaries and files larger than ``max_kb`` (defaults to
        ``settings.workspace_max_file_kb``).
        """
        cap = (max_kb or settings.workspace_max_file_kb) * 1024
        out: dict[str, str] = {}
        for rel in self.list_files():
            path = self.workspace_dir / rel
            if not _is_text_file(path):
                continue
            try:
                if path.stat().st_size > cap:
                    continue
                out[rel] = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
        return out

    def uploads_dir(self, template: TemplateInfo | None = None) -> Path:
        """Where user uploads land ('uploads/' static, 'public/uploads/' node)."""
        tpl = template or self.template()
        rel = "public/uploads" if (tpl and tpl.kind == "node") else "uploads"
        d = self.workspace_dir / rel
        d.mkdir(parents=True, exist_ok=True)
        return d

    # -- git checkpoints -------------------------------------------------

    @property
    def git_available(self) -> bool:
        return shutil.which("git") is not None

    def _git(self, *args: str, check: bool = False) -> tuple[bool, str]:
        if not self.git_available:
            return False, "git not available"
        try:
            proc = subprocess.run(
                ["git", *_GIT_IDENTITY, *args],
                cwd=str(self.workspace_dir),
                capture_output=True,
                timeout=60,
            )
            output = (proc.stdout + proc.stderr).decode("utf-8", errors="replace").strip()
            ok = proc.returncode == 0
            if not ok and check:
                logger.warning("git %s failed: %s", " ".join(args), output[:500])
            return ok, output
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.warning("git %s failed: %s", " ".join(args), exc)
            return False, str(exc)

    def _git_init(self) -> None:
        if (self.workspace_dir / ".git").exists():
            return
        ok, _ = self._git("init", "-q", check=True)
        if ok:
            self._git("config", "core.autocrlf", "false")

    def checkpoint(self, message: str) -> str | None:
        """Commit the current workspace state. Returns short sha or None.

        Skips silently when git is unavailable or nothing changed.
        """
        if not self.git_available or not (self.workspace_dir / ".git").exists():
            return None
        ok, status = self._git("status", "--porcelain")
        if not ok or not status.strip():
            return None
        self._git("add", "-A")
        ok, _ = self._git("commit", "-q", "-m", message, check=True)
        if not ok:
            return None
        _, sha = self._git("rev-parse", "--short", "HEAD")
        return sha.strip() or None

    def list_checkpoints(self, limit: int = 50) -> list[dict[str, str]]:
        ok, out = self._git("log", f"-{limit}", "--pretty=format:%h%x09%cI%x09%s")
        if not ok or not out.strip():
            return []
        checkpoints = []
        for line in out.splitlines():
            parts = line.split("\t", 2)
            if len(parts) == 3:
                checkpoints.append({"ref": parts[0], "timestamp": parts[1], "message": parts[2]})
        return checkpoints

    # -- export ----------------------------------------------------------

    def export_zip(self) -> bytes:
        """Zip the workspace (minus node_modules/.git/dist), adding a README
        with run instructions when the template defines build commands."""
        buf = io.BytesIO()
        template = self.template()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for rel in self.list_files():
                zf.write(self.workspace_dir / rel, rel)
            if "README.md" not in {Path(r).name for r in self.list_files() if "/" not in r}:
                zf.writestr("README.md", self._render_readme(template))
        return buf.getvalue()

    @staticmethod
    def _render_readme(template: TemplateInfo | None) -> str:
        if template is None or template.kind != "node":
            return (
                "# AgentSite Export\n\n"
                "Static site — open `index.html` in a browser, or serve the "
                "folder with any static file server.\n"
            )
        install = " ".join(template.install_cmd or ["npm", "install"])
        build = " ".join(template.build_cmd or ["npm", "run", "build"])
        dev = " ".join(template.dev_cmd or ["npm", "run", "dev"])
        return (
            f"# AgentSite Export — {template.name}\n\n"
            "```bash\n"
            f"{install}\n"
            f"{dev}      # local dev server\n"
            f"{build}    # production build -> {template.output_dir or 'dist'}/\n"
            "```\n"
        )
