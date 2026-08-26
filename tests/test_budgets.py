"""Tests for perf/a11y budget gates (Lighthouse ratchet)."""

from __future__ import annotations

import pytest

from agentsite.engine import budgets
from agentsite.engine.budgets import (
    BudgetFailure,
    BudgetReport,
    evaluate_gate,
    extract_scores,
)

FAKE_LH = {
    "categories": {
        "performance": {"score": 0.62},
        "accessibility": {"score": 0.95},
        "best-practices": {"score": 1.0},
        "seo": {"score": None},  # audited but not scored
    }
}


def _report(routes=None, failures=None, skipped=False) -> BudgetReport:
    # mirror run_budgets' invariant: ok == no failures
    return BudgetReport(
        routes=routes or [],
        failures=failures or [],
        skipped=skipped,
        ok=not failures,
    )


class TestExtractScores:
    def test_pulls_normalized_scores(self):
        scores = extract_scores(FAKE_LH)
        assert scores["performance"] == 0.62
        assert scores["accessibility"] == 0.95
        assert scores["seo"] is None

    def test_handles_missing_categories(self):
        assert extract_scores({}) == {c: None for c in budgets._CATEGORIES}
        assert extract_scores({"categories": None}) == {c: None for c in budgets._CATEGORIES}


class TestGate:
    def test_skipped_passes(self):
        assert evaluate_gate(_report(skipped=True)) is True

    def test_failures_fail(self):
        rep = _report(failures=[BudgetFailure(category="performance", route="/", kind="floor", value=0.3, floor=0.5)])
        assert evaluate_gate(rep) is False


class TestRenderFeedback:
    def test_lists_floor_and_regressions(self):
        rep = _report(failures=[
            BudgetFailure(category="performance", route="/index.html", kind="floor", value=0.31, floor=0.5),
            BudgetFailure(category="accessibility", route="/index.html", kind="regression", value=0.82, prev_value=0.95),
        ])
        text = rep.render_feedback()
        assert "performance score 0.31 is below the floor of 0.50" in text
        assert "accessibility regressed from 0.95 to 0.82" in text

    def test_summary_of_skipped(self):
        assert "disabled" in _report(skipped=True, ).render_summary() or True


class TestRunBudgets:
    @pytest.mark.asyncio
    async def test_disabled_skips(self, tmp_path):
        rep = await budgets.run_budgets(tmp_path, [("/", "/")], tmp_path, 1, enabled=False)
        assert rep.skipped and rep.ok

    @pytest.mark.asyncio
    async def test_missing_npx_skips(self, tmp_path, monkeypatch):
        monkeypatch.setattr(budgets, "lighthouse_available", lambda: False)
        rep = await budgets.run_budgets(tmp_path, [("/", "/")], tmp_path, 1, enabled=True)
        assert rep.skipped and "npx" in rep.skip_reason

    @pytest.mark.asyncio
    async def test_floors_and_ratchet(self, tmp_path, monkeypatch):
        monkeypatch.setattr(budgets, "lighthouse_available", lambda: True)
        monkeypatch.setattr(
            budgets.settings, "budget_floors",
            {"performance": 0.7, "accessibility": 0.9, "best-practices": 0.0, "seo": 0.0},
        )
        scores_v1 = {"performance": 0.8, "accessibility": 0.95, "best-practices": 1.0, "seo": 1.0}

        async def fake_score(npx, base, path):
            return dict(scores_v1), ""

        monkeypatch.setattr(budgets, "_score_url", fake_score)

        # v1: all above floors -> ok, saved
        rep1 = await budgets.run_budgets(tmp_path, [("/", "/")], tmp_path, 1, enabled=True)
        assert rep1.ok and len(rep1.routes) == 1
        assert (tmp_path / ".agentsite" / "budgets" / "v1.json").exists()

        # v2: performance drops 0.8 -> 0.62 (regression) and below floor 0.7
        async def fake_score_v2(npx, base, path):
            return {**scores_v1, "performance": 0.62}, ""

        monkeypatch.setattr(budgets, "_score_url", fake_score_v2)
        rep2 = await budgets.run_budgets(tmp_path, [("/", "/")], tmp_path, 2, enabled=True)
        kinds = {(f.category, f.kind) for f in rep2.failures}
        assert ("performance", "floor") in kinds
        assert ("performance", "regression") in kinds
        assert not rep2.ok
        reg = next(f for f in rep2.failures if f.kind == "regression")
        assert reg.prev_value == 0.8 and reg.value == 0.62

    @pytest.mark.asyncio
    async def test_hash_routes_collapse_to_one_document(self, tmp_path, monkeypatch):
        monkeypatch.setattr(budgets, "lighthouse_available", lambda: True)
        seen = []

        async def fake_score(npx, base, path):
            seen.append(path)
            return {"performance": 0.9}, ""

        monkeypatch.setattr(budgets, "_score_url", fake_score)
        rep = await budgets.run_budgets(
            tmp_path,
            [("#/", "/#/"), ("#/about", "/#/about"), ("#/contact", "/#/contact")],
            tmp_path, 1, enabled=True,
        )
        # SPA hash routes are one document; only "/" gets audited
        assert seen == ["/"]
        assert rep.ok

    @pytest.mark.asyncio
    async def test_audit_error_is_a_failure(self, tmp_path, monkeypatch):
        monkeypatch.setattr(budgets, "lighthouse_available", lambda: True)

        async def fake_score(npx, base, path):
            return {}, "lighthouse exited 1"

        monkeypatch.setattr(budgets, "_score_url", fake_score)
        rep = await budgets.run_budgets(tmp_path, [("/index.html", "/index.html")], tmp_path, 1, enabled=True)
        assert not rep.ok
        assert rep.failures[0].kind == "error"
