"""Tests for project-mode workspaces: templates, WorkspaceManager, tools, API."""

from __future__ import annotations

import io
import re
import zipfile

import pytest
from httpx import ASGITransport, AsyncClient

from agentsite.api import deps
from agentsite.api.app import create_app
from agentsite.engine.project_manager import ProjectManager
from agentsite.engine.tokens import render_conventions_css, render_tokens_css
from agentsite.engine.workspace import WorkspaceManager
from agentsite.models import StyleSpec
from agentsite.storage.database import Database
from agentsite.storage.repository import (
    AgentConfigRepository,
    AgentRunRepository,
    PageRepository,
    ProjectRepository,
    VersionRepository,
)
from agentsite.templates import (
    find_template,
    list_templates,
    read_template_doc,
    scaffold_workspace,
)


@pytest.fixture
async def client(tmp_path):
    """Async test client with initialized deps (mirrors test_api.py)."""
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


# ---------------------------------------------------------------------------
# Template registry
# ---------------------------------------------------------------------------


class TestTemplateRegistry:
    def test_bundled_templates_present(self):
        ids = {t.id for t in list_templates()}
        assert "static-multipage" in ids
        assert "vite-react-tailwind" in ids

    def test_find_template(self):
        t = find_template("vite-react-tailwind")
        assert t is not None
        assert t.kind == "node"
        assert t.build_cmd == ["npm", "run", "build"]
        assert t.output_dir == "dist"
        assert find_template("nope") is None
        assert find_template(None) is None

    def test_template_docs_exist(self):
        assert len(read_template_doc("static-multipage")) > 500
        assert len(read_template_doc("vite-react-tailwind")) > 500

    def test_scaffold_copies_files(self, tmp_path):
        files = scaffold_workspace("static-multipage", tmp_path / "ws")
        assert "index.html" in files
        assert "styles/tokens.css" in files
        assert "styles/main.css" in files
        assert "scripts/main.js" in files

    def test_conventions_wired_into_both_templates(self):
        """Every template declares a conventions path, scaffolds the stub,
        and its styles entry loads it."""
        import pathlib

        root = pathlib.Path(__file__).parents[1] / "agentsite" / "templates"
        checks = {
            "static-multipage": ("scaffold/index.html",),
            "vite-react-tailwind": ("scaffold/src/index.css",),
        }
        for tid, (ref_file,) in checks.items():
            t = find_template(tid)
            assert t is not None and t.conventions_path, tid
            assert (root / tid / "scaffold" / t.conventions_path).exists(), (
                f"{tid}: missing scaffold stub {t.conventions_path}"
            )
            assert "conventions.css" in (root / tid / ref_file).read_text(
                encoding="utf-8"
            ), f"{tid}: {ref_file} does not load conventions.css"


# ---------------------------------------------------------------------------
# Tokens renderer <-> scaffold consistency
# ---------------------------------------------------------------------------


def _declared_vars(css: str) -> set[str]:
    return set(re.findall(r"(--[\w-]+)\s*:", css))


class TestTokensRenderer:
    def test_css_vars_cover_static_scaffold(self):
        """Every variable the static scaffold declares must be re-declared
        when the Designer regenerates tokens — otherwise main.css breaks."""
        scaffold_css = (
            find_template("static-multipage") and
            (  # read the scaffold's tokens file
                __import__("pathlib").Path(__file__).parents[1]
                / "agentsite" / "templates" / "static-multipage"
                / "scaffold" / "styles" / "tokens.css"
            ).read_text(encoding="utf-8")
        )
        rendered = render_tokens_css(StyleSpec(), "css-vars")
        missing = _declared_vars(scaffold_css) - _declared_vars(rendered)
        assert not missing, f"Renderer drops scaffold tokens: {missing}"

    def test_tailwind4_cover_vite_scaffold(self):
        scaffold_css = (
            __import__("pathlib").Path(__file__).parents[1]
            / "agentsite" / "templates" / "vite-react-tailwind"
            / "scaffold" / "src" / "styles" / "tokens.css"
        ).read_text(encoding="utf-8")
        rendered = render_tokens_css(StyleSpec(), "tailwind4")
        assert rendered.lstrip("/* \n").startswith("Design tokens") or "@theme" in rendered
        missing = _declared_vars(scaffold_css) - _declared_vars(rendered)
        assert not missing, f"Renderer drops scaffold tokens: {missing}"

    def test_custom_spec_values_flow_through(self):
        spec = StyleSpec(primary_color="#ff0000", font_heading="Space Grotesk")
        out = render_tokens_css(spec, "css-vars")
        assert "--color-primary: #ff0000;" in out
        assert "Space Grotesk" in out


class TestConventionsCSS:
    def test_house_basics_present(self):
        out = render_conventions_css(StyleSpec())
        assert ".ph {" in out
        assert "@keyframes as-rise" in out
        assert "[data-reveal-group]" in out
        assert ":focus-visible" in out
        assert "::selection" in out
        assert "prefers-reduced-motion" in out

    def test_default_placeholder_is_stripes(self):
        out = render_conventions_css(StyleSpec())
        assert "--stripes" in out
        # The chosen pattern is the bare .ph default background.
        stripe_block = out.split(".ph {", 1)[1].split("}", 1)[0]
        assert "repeating-linear-gradient(-45deg" in stripe_block

    def test_placeholder_style_switches_pattern(self):
        dots = render_conventions_css(StyleSpec(placeholder_style="dots"))
        dots_block = dots.split(".ph {", 1)[1].split("}", 1)[0]
        assert "radial-gradient(var(--as-ph-ink)" in dots_block
        blueprint = render_conventions_css(StyleSpec(placeholder_style="blueprint"))
        blueprint_block = blueprint.split(".ph {", 1)[1].split("}", 1)[0]
        assert "linear-gradient(var(--as-ph-line)" in blueprint_block

    def test_unknown_placeholder_falls_back_to_stripes(self):
        out = render_conventions_css(StyleSpec(placeholder_style="hologram"))
        assert "repeating-linear-gradient(-45deg" in out

    def test_personality_notes_rendered_as_comments(self):
        spec = StyleSpec(
            aesthetic_direction="editorial ink — broadsheet grid",
            signature_element="oversized numbered section markers",
        )
        out = render_conventions_css(spec)
        assert "Direction: editorial ink — broadsheet grid" in out
        assert "Signature element: oversized numbered section markers" in out
        # Empty fields are omitted, not emitted blank.
        assert "Motion:" not in out
        assert "Backgrounds:" not in out

    def test_consumes_tokens_only(self):
        """The conventions sheet must reference tokens via var(), not hex codes."""
        spec = StyleSpec(primary_color="#123456")
        out = render_conventions_css(spec)
        assert "#123456" not in out
        assert "var(--color-primary)" in out


# ---------------------------------------------------------------------------
# WorkspaceManager
# ---------------------------------------------------------------------------


class TestWorkspaceManager:
    @pytest.fixture
    def ws(self, tmp_path):
        ws = WorkspaceManager(tmp_path / "proj")
        ws.scaffold(find_template("static-multipage"))
        return ws

    def test_scaffold_sets_marker(self, ws):
        assert ws.exists()
        assert ws.template_id == "static-multipage"
        assert ws.template().kind == "static"

    def test_write_read_roundtrip(self, ws):
        ws.write_file("about.html", "<html>about</html>")
        assert ws.read_file("about.html") == "<html>about</html>"

    def test_traversal_blocked(self, ws):
        with pytest.raises(ValueError):
            ws.safe_path("../outside.txt")
        assert ws.read_file("../outside.txt") is None

    def test_list_files_excludes_internals(self, ws):
        (ws.workspace_dir / "node_modules" / "pkg").mkdir(parents=True)
        (ws.workspace_dir / "node_modules" / "pkg" / "x.js").write_text("x")
        files = ws.list_files()
        assert "index.html" in files
        assert not any(f.startswith("node_modules") for f in files)
        assert not any(f.startswith(".agentsite") for f in files)
        assert not any(f.startswith(".git/") for f in files)

    def test_collect_files_content_caps_and_skips_binary(self, ws):
        ws.write_bytes("assets/logo.png", b"\x89PNG\r\n")
        content = ws.collect_files_content(max_kb=1)
        assert "assets/logo.png" not in content
        assert "index.html" not in content or len(content.get("index.html", "")) <= 1024
        small = ws.collect_files_content()
        assert "index.html" in small

    def test_checkpoints(self, ws):
        if not ws.git_available:
            pytest.skip("git not installed")
        # scaffold() already made the initial checkpoint
        assert ws.checkpoint("no changes") is None  # nothing dirty
        ws.write_file("new.html", "<html></html>")
        ref = ws.checkpoint("add new page")
        assert ref
        log = ws.list_checkpoints()
        assert any("add new page" in c["message"] for c in log)

    def test_export_zip_contains_readme_and_excludes(self, ws):
        (ws.workspace_dir / "node_modules").mkdir(exist_ok=True)
        (ws.workspace_dir / "node_modules" / "y.js").write_text("y")
        data = ws.export_zip()
        zf = zipfile.ZipFile(io.BytesIO(data))
        names = zf.namelist()
        assert "index.html" in names
        assert "README.md" in names
        assert not any(n.startswith("node_modules") for n in names)
        assert not any(n.startswith(".git/") for n in names)  # .gitignore itself is fine

    def test_uploads_dir_static_vs_node(self, tmp_path):
        ws_static = WorkspaceManager(tmp_path / "a")
        ws_static.scaffold(find_template("static-multipage"))
        assert ws_static.uploads_dir().name == "uploads"
        assert ws_static.uploads_dir().parent == ws_static.workspace_dir

        ws_node = WorkspaceManager(tmp_path / "b")
        ws_node.scaffold(find_template("vite-react-tailwind"))
        rel = ws_node.uploads_dir().relative_to(ws_node.workspace_dir)
        assert str(rel).replace("\\", "/") == "public/uploads"


# ---------------------------------------------------------------------------
# Workspace tools (edit_file semantics, run_command gating)
# ---------------------------------------------------------------------------


class _Ctx:
    """Duck-typed RunContext — the tools only touch ctx.deps."""

    def __init__(self, deps):
        self.deps = deps


class TestWorkspaceTools:
    @pytest.fixture
    def ctx(self, tmp_path):
        ws = WorkspaceManager(tmp_path / "proj")
        template = find_template("static-multipage")
        ws.scaffold(template)
        return _Ctx({
            "workspace_dir": ws.workspace_dir,
            "template": template,
            "written_files": [],
        })

    def test_edit_file_unique_replacement(self, ctx):
        from agentsite.agents.workspace_tools import edit_file, write_file

        write_file(ctx, "page.html", "<h1>Old Title</h1>\n<p>body</p>")
        out = edit_file(ctx, "page.html", "Old Title", "New Title")
        assert "1 replacement" in out
        assert "New Title" in (ctx.deps["workspace_dir"] / "page.html").read_text()

    def test_edit_file_rejects_ambiguous_and_missing(self, ctx):
        from agentsite.agents.workspace_tools import edit_file, write_file

        write_file(ctx, "p.html", "<p>x</p><p>x</p>")
        assert "appears 2 times" in edit_file(ctx, "p.html", "<p>x</p>", "<p>y</p>")
        assert "not found" in edit_file(ctx, "p.html", "zzz", "y")
        ok = edit_file(ctx, "p.html", "<p>x</p>", "<p>y</p>", replace_all=True)
        assert "2 replacement" in ok

    def test_write_file_traversal_and_excluded(self, ctx):
        from agentsite.agents.workspace_tools import write_file

        assert "escapes" in write_file(ctx, "../evil.txt", "x")
        assert "managed directory" in write_file(ctx, "node_modules/x.js", "x")

    def test_write_file_tracks_and_warns_protected(self, tmp_path):
        from agentsite.agents.workspace_tools import write_file

        ws = WorkspaceManager(tmp_path / "p2")
        template = find_template("vite-react-tailwind")
        ws.scaffold(template)
        ctx = _Ctx({
            "workspace_dir": ws.workspace_dir,
            "template": template,
            "written_files": [],
        })
        out = write_file(ctx, "package.json", "{}")
        assert "WARNING" in out
        assert "package.json" in ctx.deps["written_files"]

    @pytest.mark.asyncio
    async def test_run_command_gating(self, ctx):
        from agentsite.agents.workspace_tools import run_command

        assert "must be" in await run_command(ctx, "rm -rf /")
        assert "no build step" in await run_command(ctx, "build")

    def test_search_files(self, ctx):
        from agentsite.agents.workspace_tools import search_files

        out = search_files(ctx, r"<title>")
        assert "index.html" in out


# ---------------------------------------------------------------------------
# API integration
# ---------------------------------------------------------------------------


class TestProjectModeAPI:
    @pytest.mark.asyncio
    async def test_list_templates_endpoint(self, client):
        resp = await client.get("/api/templates")
        assert resp.status_code == 200
        ids = {t["id"] for t in resp.json()}
        assert {"static-multipage", "vite-react-tailwind"} <= ids

    @pytest.mark.asyncio
    async def test_create_project_mode_scaffolds_workspace(self, client):
        resp = await client.post("/api/projects", json={
            "name": "WS Test",
            "mode": "project",
            "template_id": "static-multipage",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["mode"] == "project"
        assert body["template_id"] == "static-multipage"

        ws = WorkspaceManager(deps.project_manager.project_dir(body["id"]))
        assert ws.exists()
        assert "index.html" in ws.list_files()

        # round-trips through the DB
        got = await client.get(f"/api/projects/{body['id']}")
        assert got.json()["mode"] == "project"

    @pytest.mark.asyncio
    async def test_create_project_rejects_bad_template(self, client):
        resp = await client.post("/api/projects", json={
            "name": "Bad", "mode": "project", "template_id": "no-such",
        })
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_mockup_default_unchanged(self, client):
        resp = await client.post("/api/projects", json={"name": "Plain"})
        assert resp.status_code == 200
        assert resp.json()["mode"] == "mockup"

    @pytest.mark.asyncio
    async def test_export_zips_workspace(self, client):
        created = (await client.post("/api/projects", json={
            "name": "Exp", "mode": "project", "template_id": "static-multipage",
        })).json()
        resp = await client.get(f"/api/projects/{created['id']}/export")
        assert resp.status_code == 200
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        assert "index.html" in zf.namelist()

    @pytest.mark.asyncio
    async def test_app_preview_serves_static_workspace(self, client):
        created = (await client.post("/api/projects", json={
            "name": "Prev", "mode": "project", "template_id": "static-multipage",
        })).json()
        resp = await client.get(f"/preview/{created['id']}/app/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        css = await client.get(f"/preview/{created['id']}/app/styles/tokens.css")
        assert css.status_code == 200
        assert "--color-primary" in css.text

    @pytest.mark.asyncio
    async def test_app_preview_placeholder_for_unbuilt_node(self, client):
        created = (await client.post("/api/projects", json={
            "name": "Node", "mode": "project", "template_id": "vite-react-tailwind",
        })).json()
        resp = await client.get(f"/preview/{created['id']}/app/")
        assert resp.status_code == 200
        assert "not built yet" in resp.text.lower()

    @pytest.mark.asyncio
    async def test_upload_lands_in_workspace(self, client):
        created = (await client.post("/api/projects", json={
            "name": "Up", "mode": "project", "template_id": "static-multipage",
        })).json()
        resp = await client.post(
            f"/api/projects/{created['id']}/assets",
            files={"file": ("photo.png", b"\x89PNG\r\n\x1a\n123", "image/png")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["workspace_path"] and body["workspace_path"].startswith("uploads/")
        ws = WorkspaceManager(deps.project_manager.project_dir(created["id"]))
        uploaded = [f for f in ws.list_files() if f.startswith("uploads/") and f != "uploads/.gitkeep"]
        assert uploaded, "upload should appear in workspace uploads/"


class TestRunnerWindowsResolution:
    def test_finalize_argv_wraps_batch_shims(self):
        import os

        from agentsite.engine.workspace_runner import _finalize_argv

        if os.name == "nt":
            assert _finalize_argv([r"C:\x\npm.cmd", "install"]) == [
                "cmd.exe", "/c", r"C:\x\npm.cmd", "install",
            ]
            assert _finalize_argv([r"C:\x\node.exe", "-v"]) == [r"C:\x\node.exe", "-v"]
        else:
            assert _finalize_argv(["/usr/bin/npm", "install"]) == ["/usr/bin/npm", "install"]

    def test_resolve_package_manager_returns_runnable(self):
        import os

        from agentsite.engine.workspace_runner import resolve_package_manager

        pm = resolve_package_manager()
        if pm is None:
            import pytest

            pytest.skip("no node toolchain installed")
        # The WinError 193 regression: never the extension-less sh shim
        if os.name == "nt":
            assert pm.lower().endswith((".cmd", ".exe", ".bat")), pm
