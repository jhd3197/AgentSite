"""Phase E — triage routing for project-mode follow-up generations.

Direction A from ``.planning/agent-pipeline-redesign.md``: a cheap
classification step before the pipeline so "make the hero bigger" doesn't
re-run PM + Designer. First generations are always ``full`` (no LLM call);
classification failures fall back to ``full`` (the safe default).
"""

from __future__ import annotations

import logging

from ..models import TriageDecision
from .extract import extract_structured

logger = logging.getLogger("agentsite.triage")

_VALID_BUCKETS = {"tweak", "partial", "full"}

_TRIAGE_INSTRUCTION = (
    "You are routing a change request for an EXISTING website project. "
    "Classify the request into exactly one bucket:\n\n"
    "- 'tweak': a small scoped change to existing pages — copy edits, color/size "
    "adjustments, swapping an image, minor layout fixes. No new pages, no "
    "structural change, no rebrand. (needs_pm=false, needs_designer=false)\n"
    "- 'partial': adds or substantially reworks pages/sections within the "
    "existing brand — e.g. 'add a pricing page', 'rework the about section "
    "into a team grid'. The site plan must be updated. "
    "(needs_pm=true, needs_designer=false)\n"
    "- 'full': a new site, full redesign, or rebrand — e.g. 'redesign the whole "
    "thing', 'change the brand to dark neon'. (needs_pm=true, needs_designer=true)\n\n"
    "When in doubt between two buckets, pick the LARGER one. "
    "Classify this request:"
)


def _render_context(prompt: str, site_plan_text: str, file_tree: str) -> str:
    parts = [f"## Change request\n{prompt}"]
    if site_plan_text:
        parts.append(f"## Current site plan\n{site_plan_text[:4000]}")
    if file_tree:
        parts.append(f"## Current project files\n{file_tree[:3000]}")
    return "\n\n".join(parts)


def _normalize(decision: TriageDecision | None) -> TriageDecision:
    """Clamp a model decision to safe invariants (or fall back to full)."""
    if decision is None or decision.bucket not in _VALID_BUCKETS:
        return TriageDecision(bucket="full", needs_pm=True, needs_designer=True,
                              reason="triage unavailable — defaulting to full build")
    if decision.bucket == "full":
        decision.needs_pm = True
        decision.needs_designer = True
    elif decision.bucket == "partial":
        decision.needs_pm = True
        decision.needs_designer = False
    else:  # tweak
        decision.needs_pm = False
        decision.needs_designer = False
    return decision


async def triage_request(
    prompt: str,
    *,
    model: str,
    site_plan_text: str = "",
    file_tree: str = "",
    version_number: int = 1,
) -> TriageDecision:
    """Classify a generation request. Never raises."""
    if version_number <= 1 or not site_plan_text:
        return TriageDecision(
            bucket="full", needs_pm=True, needs_designer=True,
            reason="first build" if version_number <= 1 else "no existing site plan",
        )

    try:
        decision = await extract_structured(
            TriageDecision,
            _render_context(prompt, site_plan_text, file_tree),
            model,
            instruction=_TRIAGE_INSTRUCTION,
        )
    except Exception:
        logger.warning("Triage classification failed — defaulting to full", exc_info=True)
        decision = None

    decision = _normalize(decision)
    logger.info("Triage: %s (%s)", decision.bucket, decision.reason)
    return decision
