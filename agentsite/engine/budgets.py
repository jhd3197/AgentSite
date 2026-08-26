"""Perf/a11y budget gates — Lighthouse per route with a version ratchet.

After each build (project mode), selected entry routes are audited with
Lighthouse (invoked through ``npx``, so Node must be installed). Two gates:

- **floors** — absolute category minimums (e.g. accessibility >= 0.9).
  A floor of 0 disables that category's gate.
- **ratchet** — a category may not regress by more than
  ``budget_regression_threshold`` versus the previous version's stored
  report (``.agentsite/budgets/v{n-1}.json``).

Failures go back to the resident dev session like verifier feedback.
Everything is advisory unless ``budget_enabled`` is on; Lighthouse runs are
slow (~20s/route), so ``budget_max_routes`` caps how many pages get audited.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import time
from pathlib import Path

from pydantic import BaseModel, Field

from ..config import settings
from .verifier import serve_directory

logger = logging.getLogger("agentsite.budgets")

_CATEGORIES = ("performance", "accessibility", "best-practices", "seo")


class RouteScores(BaseModel):
    """Lighthouse category scores (0..1) for one audited route."""

    route: str
    url: str = ""
    scores: dict[str, float | None] = Field(default_factory=dict)
    error: str = ""
    duration_s: float = 0.0


class BudgetFailure(BaseModel):
    category: str
    route: str
    kind: str  # "floor" | "regression" | "error"
    value: float | None = None
    floor: float | None = None
    prev_value: float | None = None


class BudgetReport(BaseModel):
    """Aggregate budget verdict — ``ok`` is the gate when enabled."""

    ok: bool = True
    skipped: bool = False
    skip_reason: str = ""
    routes: list[RouteScores] = Field(default_factory=list)
    failures: list[BudgetFailure] = Field(default_factory=list)
    duration_s: float = 0.0

    def render_summary(self) -> str:
        if self.skipped:
            return f"Budgets skipped: {self.skip_reason}"
        parts = []
        for r in self.routes:
            scored = ", ".join(
                f"{cat} {_fmt_score(r.scores.get(cat))}" for cat in _CATEGORIES if cat in r.scores
            )
            parts.append(f"{r.route} ({scored})" if scored else f"{r.route} (no scores)")
        status = "FAILED" if not self.ok else "passed"
        return f"Budgets {status}: " + "; ".join(parts)

    def render_feedback(self) -> str:
        lines = [
            "Performance/accessibility budget check FAILED against the live "
            "site. Fix these with targeted edits:",
        ]
        for f in self.failures:
            if f.kind == "floor":
                lines.append(
                    f"- {f.route}: {f.category} score {_fmt_score(f.value)} is below the "
                    f"floor of {f.floor:.2f}"
                )
            elif f.kind == "regression":
                lines.append(
                    f"- {f.route}: {f.category} regressed from "
                    f"{_fmt_score(f.prev_value)} to {_fmt_score(f.value)}"
                )
            else:
                lines.append(f"- {f.route}: audit failed ({f.category})")
        lines.append(
            "Common wins: compress/resize images, lazy-load below-the-fold media, "
            "add width/height to media, reduce blocking scripts, ensure text has "
            "sufficient contrast and interactive elements are reachable."
        )
        return "\n".join(lines)


def _fmt_score(v: float | int | None) -> str:
    return "n/a" if v is None else str(round(float(v), 2))


def lighthouse_available() -> bool:
    return shutil.which("npx") is not None


def extract_scores(lh_json: dict) -> dict[str, float | None]:
    """Pull normalized category scores out of a Lighthouse JSON report."""
    categories = (lh_json or {}).get("categories") or {}
    scores: dict[str, float | None] = {}
    for cat in _CATEGORIES:
        entry = categories.get(cat)
        raw = entry.get("score") if isinstance(entry, dict) else None
        scores[cat] = float(raw) if isinstance(raw, (int, float)) else None
    return scores


def evaluate_gate(report: BudgetReport) -> bool:
    return report.skipped or report.ok


def _budgets_dir(workspace_dir: Path) -> Path:
    return workspace_dir / ".agentsite" / "budgets"


def _load_previous(workspace_dir: Path, version: int) -> dict[str, dict[str, float | None]]:
    """Category scores per route from version n-1, keyed by route label."""
    prev_path = _budgets_dir(workspace_dir) / f"v{version - 1}.json"
    if not prev_path.exists():
        return {}
    try:
        data = json.loads(prev_path.read_text(encoding="utf-8"))
        return {r["route"]: r.get("scores", {}) for r in data.get("routes", [])}
    except Exception:
        logger.debug("Could not load previous budget report", exc_info=True)
        return {}


def _save_report(workspace_dir: Path, version: int, report: BudgetReport) -> None:
    out = _budgets_dir(workspace_dir) / f"v{version}.json"
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    except Exception:
        logger.debug("Could not save budget report", exc_info=True)


def _safe_label(route: str) -> str:
    label = route.replace("#/", "").replace("/", "-").strip("-")
    return re.sub(r"[^\w-]+", "", label) or "index"


async def _score_url(npx: str, base_url: str, path: str) -> tuple[dict[str, float | None], str]:
    """Run Lighthouse against one URL. Returns (scores, error)."""
    cmd = [
        npx,
        "--yes",
        "--package=lighthouse@11",
        "lh",
        base_url + path,
        "--output=json",
        "--output-path=stdout",
        "--only-categories=" + ",".join(_CATEGORIES),
        "--chrome-flags=--headless=new --no-sandbox --disable-gpu",
        "--quiet",
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
    except OSError as exc:
        return {}, f"could not launch npx: {exc}"

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=settings.budget_timeout_s)
    except asyncio.TimeoutError:
        proc.kill()
        return {}, f"lighthouse timed out after {settings.budget_timeout_s}s"

    if proc.returncode != 0:
        tail = (stderr or b"").decode("utf-8", errors="replace")[-300:]
        return {}, f"lighthouse exited {proc.returncode}: {tail}"

    try:
        text = stdout.decode("utf-8", errors="replace")
        # Defensive: some npm versions print progress noise before the JSON.
        start = text.index("{")
        data = json.loads(text[start:])
        return extract_scores(data), ""
    except Exception as exc:
        return {}, f"unparseable lighthouse output: {exc}"


async def run_budgets(
    serve_root: Path,
    routes: list[tuple[str, str]],
    workspace_dir: Path,
    version: int,
    *,
    enabled: bool | None = None,
) -> BudgetReport:
    """Audit up to ``budget_max_routes`` routes and compare against floors +
    the previous version's report. Never raises."""
    if enabled is None:
        enabled = settings.budget_enabled
    if not enabled:
        return BudgetReport(skipped=True, skip_reason="budgets disabled in settings")
    if not lighthouse_available():
        return BudgetReport(
            skipped=True,
            skip_reason="npx/node not found — install Node.js to enable perf/a11y budgets",
        )
    # Lighthouse audits whole documents — collapse hash-route variants of a
    # SPA (#/, #/about) onto their single document so node templates still
    # get one meaningful audit instead of being skipped entirely.
    seen_docs: set[str] = set()
    usable: list[tuple[str, str]] = []
    for _label, path in routes:
        doc = path.split("#", 1)[0] or "/"
        if doc not in seen_docs:
            seen_docs.add(doc)
            usable.append((doc, doc))
    if not usable:
        return BudgetReport(skipped=True, skip_reason="no static routes to audit")

    npx = shutil.which("npx") or "npx"
    report = BudgetReport()
    start = time.monotonic()

    cm = serve_directory(serve_root)
    loop = asyncio.get_running_loop()
    base_url = await loop.run_in_executor(None, cm.__enter__)
    try:
        for label, path in usable[: settings.budget_max_routes]:
            t0 = time.monotonic()
            scores, error = await _score_url(npx, base_url, path)
            report.routes.append(
                RouteScores(
                    route=label,
                    url=path,
                    scores=scores,
                    error=error[:200],
                    duration_s=round(time.monotonic() - t0, 1),
                )
            )
    finally:
        await loop.run_in_executor(None, lambda: cm.__exit__(None, None, None))

    prev = _load_previous(workspace_dir, version)
    for r in report.routes:
        if r.error and not r.scores:
            report.failures.append(BudgetFailure(category="audit", route=r.route, kind="error"))
            continue
        before = prev.get(r.route, {})
        for cat, floor in settings.budget_floors.items():
            value = r.scores.get(cat)
            if floor > 0 and value is not None and value < floor:
                report.failures.append(
                    BudgetFailure(category=cat, route=r.route, kind="floor", value=value, floor=floor)
                )
            prev_val = before.get(cat)
            if (
                value is not None
                and isinstance(prev_val, (int, float))
                and (prev_val - value) > settings.budget_regression_threshold
            ):
                report.failures.append(
                    BudgetFailure(
                        category=cat,
                        route=r.route,
                        kind="regression",
                        value=value,
                        prev_value=float(prev_val),
                    )
                )

    report.duration_s = round(time.monotonic() - start, 1)
    report.ok = not report.failures
    _save_report(workspace_dir, version, report)
    logger.info("%s (%.1fs)", report.render_summary(), report.duration_s)
    return report
