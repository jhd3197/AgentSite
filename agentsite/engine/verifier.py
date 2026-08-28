"""Post-build verification: serve the workspace and walk it with Playwright.

The verifier is the hard quality gate the LLM reviewer cannot override:
uncaught JS errors, failed same-origin requests, blank pages, and missing
planned pages all fail the gate, and the failure report goes back to the
resident dev session as actionable feedback. Screenshots land in
``workspace/.agentsite/verify/v{n}/`` for the vision reviewer and the chat
timeline.

Playwright is an optional dependency: install with
``pip install agentsite[verify]`` then ``playwright install chromium``.
When unavailable, verification is skipped (reported, never fatal).
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import re
import shutil
import threading
import time
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from pydantic import BaseModel, Field

from ..config import settings
from ..models import SitePlan
from ..templates import TemplateInfo

logger = logging.getLogger("agentsite.verifier")

_DESKTOP = {"width": 1280, "height": 800}
_MOBILE = {"width": 390, "height": 844}
_MIN_CONTENT_CHARS = 40  # below this, a page is considered blank
_SETTLE_MS = 600  # post-load delay so SPAs finish mounting


class RouteCheck(BaseModel):
    """Verification result for a single route."""

    route: str
    url: str = ""
    ok: bool = True
    console_errors: list[str] = Field(default_factory=list)
    failed_requests: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    screenshots: list[str] = Field(default_factory=list)  # rel to .agentsite/verify/
    content_chars: int = 0


class VerifyReport(BaseModel):
    """Aggregate verification verdict — ``ok`` is the hard gate."""

    ok: bool = True
    skipped: bool = False
    skip_reason: str = ""
    routes: list[RouteCheck] = Field(default_factory=list)
    missing_pages: list[str] = Field(default_factory=list)
    summary: str = ""
    duration_s: float = 0.0

    @property
    def screenshot_rel_paths(self) -> list[str]:
        return [s for r in self.routes for s in r.screenshots]

    def render_feedback(self) -> str:
        """Actionable failure report for the dev session."""
        lines = ["Automated verification FAILED. The rendered site has real problems:"]
        if self.missing_pages:
            lines.append(
                "\n## Planned pages missing\n"
                + "\n".join(f"- '{p}' is in the site plan but has no page file" for p in self.missing_pages)
            )
        for r in self.routes:
            if r.ok:
                continue
            lines.append(f"\n## Route {r.route}")
            for e in r.console_errors:
                lines.append(f"- Uncaught JS error: {e}")
            for f in r.failed_requests:
                lines.append(f"- Broken reference (request failed): {f}")
            if r.content_chars < _MIN_CONTENT_CHARS:
                lines.append(
                    f"- Page renders almost no content ({r.content_chars} chars of text). "
                    "It is blank or failed to mount."
                )
        lines.append(
            "\nFix these with targeted edits, rebuild if needed — the issues above "
            "are from actually loading the site in a browser, not from reading code."
        )
        return "\n".join(lines)

    def render_summary(self) -> str:
        if self.skipped:
            return f"Verification skipped: {self.skip_reason}"
        shots = len(self.screenshot_rel_paths)
        errors = sum(len(r.console_errors) for r in self.routes)
        failed = sum(len(r.failed_requests) for r in self.routes)
        status = "passed" if self.ok else "FAILED"
        return (
            f"Verification {status}: {len(self.routes)} routes checked, "
            f"{shots} screenshots, {errors} console errors, {failed} failed requests"
            + (f", {len(self.missing_pages)} planned pages missing" if self.missing_pages else "")
        )


def playwright_available() -> bool:
    return importlib.util.find_spec("playwright") is not None


def _safe_label(route: str) -> str:
    label = route.replace("#/", "").replace("/", "-").strip("-")
    label = re.sub(r"[^\w-]+", "", label)
    return label or "index"


def plan_routes(
    template: TemplateInfo,
    site_plan: SitePlan | None,
    serve_root: Path,
) -> tuple[list[tuple[str, str]], list[str]]:
    """Map the site plan onto navigable routes.

    Returns ([(label, url_path)], missing_pages). Static templates route to
    real ``*.html`` files (missing file => missing page); HashRouter
    templates route to ``/#/{slug}``.
    """
    slugs: list[str] = []
    if site_plan is not None:
        slugs = [p.slug for p in site_plan.pages]
    if not slugs:
        slugs = ["index"]

    routes: list[tuple[str, str]] = []
    missing: list[str] = []
    seen: set[str] = set()

    for slug in slugs:
        is_index = slug in ("index", "home", "")
        if template.kind == "node":
            label = "#/" if is_index else f"#/{slug}"
            path = "/#/" if is_index else f"/#/{slug}"
        else:
            filename = "index.html" if is_index else f"{slug}.html"
            if not (serve_root / filename).exists():
                missing.append(slug)
                continue
            label = filename
            path = f"/{filename}"
        if label not in seen:
            seen.add(label)
            routes.append((label, path))

    # Always check the entry page even if the plan omitted it
    entry_label = "#/" if template.kind == "node" else "index.html"
    if entry_label not in seen and (template.kind == "node" or (serve_root / "index.html").exists()):
        routes.insert(0, (entry_label, "/#/" if template.kind == "node" else "/index.html"))

    return routes[: settings.verify_max_routes], missing


def page_routes(page_dir: Path) -> list[tuple[str, str]]:
    """Routes for a single page-version directory (mockup mode).

    Every top-level ``*.html`` file is a route; ``index.html`` first.
    """
    files = sorted(page_dir.glob("*.html"), key=lambda f: (f.name != "index.html", f.name))
    routes = [(f.name, f"/{f.name}") for f in files]
    return routes[: settings.verify_max_routes]


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # matches base signature
        pass


@contextmanager
def serve_directory(root: Path):
    """Serve ``root`` on an ephemeral localhost port (background thread)."""
    handler = partial(_QuietHandler, directory=str(root))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


async def run_verification(
    workspace_dir: Path,
    template: TemplateInfo,
    site_plan: SitePlan | None,
    version: int,
    *,
    enabled: bool | None = None,
) -> VerifyReport:
    """Verify the built site. Never raises — failures land in the report."""
    if enabled is None:
        enabled = settings.verify_enabled
    if not enabled:
        return VerifyReport(skipped=True, skip_reason="verification disabled in settings")
    if not playwright_available():
        return VerifyReport(
            skipped=True,
            skip_reason=(
                "playwright not installed — pip install agentsite[verify] "
                "&& playwright install chromium"
            ),
        )

    if template.kind == "node":
        serve_root = workspace_dir / (template.output_dir or "dist")
        if not serve_root.exists():
            return VerifyReport(skipped=True, skip_reason="no build output to verify")
    else:
        serve_root = workspace_dir

    verify_dir = workspace_dir / ".agentsite" / "verify" / f"v{version}"
    routes, missing = plan_routes(template, site_plan, serve_root)
    return await _verify_routes(serve_root, routes, missing, verify_dir, version)


async def run_page_verification(
    page_dir: Path,
    version: int,
    *,
    enabled: bool | None = None,
) -> VerifyReport:
    """Verify a single rendered page-version directory (mockup mode).

    Serves ``page_dir`` directly (index.html + styles.css + script.js +
    assets) and walks every top-level HTML page. Screenshots land in
    ``page_dir/.verify/v{n}/``. Never raises — failures land in the report.
    """
    if enabled is None:
        enabled = settings.verify_enabled
    if not enabled:
        return VerifyReport(skipped=True, skip_reason="verification disabled in settings")
    if not playwright_available():
        return VerifyReport(
            skipped=True,
            skip_reason=(
                "playwright not installed — pip install agentsite[verify] "
                "&& playwright install chromium"
            ),
        )
    if not (page_dir / "index.html").exists():
        return VerifyReport(skipped=True, skip_reason="no index.html to verify")

    verify_dir = page_dir / ".verify" / f"v{version}"
    routes = page_routes(page_dir)
    return await _verify_routes(page_dir, routes, [], verify_dir, version)


async def _verify_routes(
    serve_root: Path,
    routes: list[tuple[str, str]],
    missing: list[str],
    verify_dir: Path,
    version: int,
) -> VerifyReport:
    """Serve ``serve_root`` and walk ``routes`` in headless Chromium."""
    if verify_dir.exists():
        shutil.rmtree(verify_dir, ignore_errors=True)
    verify_dir.mkdir(parents=True, exist_ok=True)

    report = VerifyReport(missing_pages=missing)
    start = time.monotonic()

    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            try:
                browser = await p.chromium.launch(headless=True)
            except Exception as exc:
                return VerifyReport(
                    skipped=True,
                    skip_reason=f"chromium unavailable ({exc}) — run: playwright install chromium",
                )
            try:
                loop = asyncio.get_running_loop()
                base_url = None

                def _serve():
                    return serve_directory(serve_root)

                # The std-lib server runs in its own thread; enter the context
                # manager off-loop to avoid blocking startup edge cases.
                cm = _serve()
                base_url = await loop.run_in_executor(None, cm.__enter__)
                try:
                    for label, path in routes:
                        report.routes.append(
                            await _check_route(browser, base_url, label, path, verify_dir, version)
                        )
                finally:
                    await loop.run_in_executor(None, lambda: cm.__exit__(None, None, None))
            finally:
                await browser.close()
    except Exception as exc:
        logger.warning("Verification crashed (non-fatal)", exc_info=True)
        return VerifyReport(skipped=True, skip_reason=f"verifier error: {exc}")

    report.duration_s = round(time.monotonic() - start, 1)
    report.ok = not report.missing_pages and all(r.ok for r in report.routes)
    report.summary = report.render_summary()
    logger.info("%s (%.1fs)", report.summary, report.duration_s)
    return report


async def _check_route(
    browser, base_url: str, label: str, path: str, verify_dir: Path, version: int
) -> RouteCheck:
    check = RouteCheck(route=label, url=path)
    context = await browser.new_context(viewport=dict(_DESKTOP))
    page = await context.new_page()

    def _is_internal(url: str) -> bool:
        return url.startswith(base_url)

    def _is_noise(url: str) -> bool:
        return url.endswith("/favicon.ico")

    def on_pageerror(err) -> None:
        check.console_errors.append(str(err)[:300])

    def on_console(msg) -> None:
        if msg.type == "error":
            check.warnings.append(f"console.error: {str(msg.text)[:200]}")

    def on_requestfailed(request) -> None:
        if _is_noise(request.url):
            return
        entry = f"{request.method} {request.url} -> {request.failure or 'failed'}"
        if _is_internal(request.url):
            check.failed_requests.append(entry[:300])
        else:
            check.warnings.append(f"external: {entry[:200]}")

    def on_response(response) -> None:
        if response.status < 400 or _is_noise(response.url):
            return
        entry = f"GET {response.url} -> {response.status}"
        if _is_internal(response.url):
            check.failed_requests.append(entry[:300])
        else:
            check.warnings.append(f"external: {entry[:200]}")

    page.on("pageerror", on_pageerror)
    page.on("console", on_console)
    page.on("requestfailed", on_requestfailed)
    page.on("response", on_response)

    try:
        await page.goto(base_url + path, wait_until="load", timeout=settings.verify_timeout_s * 1000)
        await page.wait_for_timeout(_SETTLE_MS)
        try:
            check.content_chars = len((await page.inner_text("body")).strip())
        except Exception:
            check.content_chars = 0

        safe = _safe_label(label)
        desktop_rel = f"v{version}/{safe}-desktop.jpg"
        await page.screenshot(
            path=str(verify_dir / f"{safe}-desktop.jpg"),
            full_page=True, type="jpeg", quality=70,
        )
        check.screenshots.append(desktop_rel)

        await page.set_viewport_size(_MOBILE)
        await page.wait_for_timeout(250)
        mobile_rel = f"v{version}/{safe}-mobile.jpg"
        await page.screenshot(
            path=str(verify_dir / f"{safe}-mobile.jpg"),
            full_page=True, type="jpeg", quality=70,
        )
        check.screenshots.append(mobile_rel)
    except Exception as exc:
        check.console_errors.append(f"navigation failed: {str(exc)[:200]}")
    finally:
        await context.close()

    check.ok = (
        not check.console_errors
        and not check.failed_requests
        and check.content_chars >= _MIN_CONTENT_CHARS
    )
    return check


def evaluate_gate(report: VerifyReport) -> bool:
    """The hard gate: skipped reports pass, failed reports cannot be overridden."""
    return report.skipped or report.ok


# ---------------------------------------------------------------------------
# Mockup-pipeline glue: verify step + vision reviewer proxy for LoopGroups
# ---------------------------------------------------------------------------


class RenderVerifyStep:
    """LoopGroup step that verifies the rendered page between dev and review.

    Quacks like a prompture agent (``name`` / ``output_key`` / ``run``) so it
    can sit inside an ``AsyncLoopGroup`` between the developer and reviewer.
    Writes ``verify_feedback`` into shared state: empty when the page passes
    (or verification is unavailable), the actionable ``render_feedback()``
    text when it fails — the loop's exit condition treats a non-empty value
    like a reviewer rejection. Absolute screenshot paths are stashed in
    ``deps['verify_screenshots']`` for a vision-capable reviewer.
    """

    name = "agentsite_render_verify"
    output_key = "verify_feedback"

    async def run(self, prompt: str = "", deps: dict | None = None):
        from types import SimpleNamespace

        deps = deps if isinstance(deps, dict) else {}
        version_dir = Path(deps.get("version_dir") or ".")
        m = re.search(r"v(\d+)$", version_dir.name)
        version = int(m.group(1)) if m else 1

        report = await run_page_verification(version_dir, version)

        shots: list[str] = []
        if not report.skipped:
            shots = [str(version_dir / ".verify" / rel) for rel in report.screenshot_rel_paths]
            shots.sort(key=lambda s: 0 if "desktop" in s else 1)
        deps["verify_screenshots"] = shots

        text = "" if (report.skipped or report.ok) else report.render_feedback()
        return SimpleNamespace(output_text=text, run_usage={})


class VisionReviewerProxy:
    """Wrap the reviewer agent to attach verify screenshots for vision models.

    Mirrors project mode: screenshots (desktop first, max 6) are only passed
    when the reviewer model ``supports_vision()``; otherwise the reviewer is
    called exactly as before.
    """

    def __init__(self, agent, model: str) -> None:
        self._agent = agent
        self._model = model
        self.name = getattr(agent, "name", "")
        self.output_key = getattr(agent, "output_key", None)

    @property
    def callbacks(self):
        return getattr(self._agent, "callbacks", None)

    @callbacks.setter
    def callbacks(self, value) -> None:
        self._agent.callbacks = value

    async def run(self, prompt: str, deps: dict | None = None):
        from .capabilities import supports_vision

        shots = (deps or {}).get("verify_screenshots") or []
        images = shots[:6] if shots and supports_vision(self._model) else None
        return await self._agent.run(prompt, deps=deps, images=images)
