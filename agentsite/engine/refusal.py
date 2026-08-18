"""Phase 12 — refusal detection + retry wrapper.

When a model emits a soft refusal ("I cannot help with that...") instead of
useful output, the pipeline currently records the run as completed with empty
content. This module detects that pattern and exposes a retry helper that the
orchestrator can wrap around an agent call.

Backends, in order:
1. Prompture's `RefusalDetector` when available (richer signals)
2. Local heuristic over a known refusal-phrase set
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger("agentsite.refusal")

_LOCAL_REFUSAL_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bi (?:can(?:not|'?t)|am (?:not (?:able|allowed)|unable)) (?:to )?(?:help|assist|comply|provide)",
        r"\bi (?:must|have to) decline\b",
        r"\b(?:sorry|apologies)[,.] (?:but )?i (?:can(?:not|'?t)|am unable)",
        r"\bagainst (?:my|the) (?:guidelines|policy|policies)\b",
        r"\bi (?:do not|don'?t) (?:feel comfortable|think (?:it'?s|i can))\b",
        r"\bas an? (?:ai|language model)[\w\s,.]{0,60}?\bi (?:can(?:not|'?t)|am unable)",
    )
]


@dataclass(frozen=True)
class RefusalSignal:
    is_refusal: bool
    reason: str = ""
    matched: str = ""


def detect_refusal(text: str) -> RefusalSignal:
    """Return a RefusalSignal describing whether ``text`` looks like a refusal.

    Empty text is NOT treated as a refusal — that's covered by the existing
    no-files-written fallback chain in the pipeline.
    """
    if not text or len(text.strip()) < 20:
        return RefusalSignal(is_refusal=False)

    # Prefer Prompture's detector when present (richer signal)
    try:
        from prompture.refusal import RefusalDetector  # type: ignore
        verdict = RefusalDetector().detect(text)
        if verdict.is_refusal:
            category = getattr(verdict.category, "value", verdict.category)
            return RefusalSignal(
                is_refusal=True,
                reason=f"prompture:{category} ({verdict.confidence:.2f})",
                matched="; ".join(verdict.matched_markers)[:200],
            )
        return RefusalSignal(is_refusal=False, reason="prompture-clean")
    except Exception:
        pass

    # Local fallback: regex over known phrases
    head = text[:1500]
    for pat in _LOCAL_REFUSAL_PATTERNS:
        m = pat.search(head)
        if m:
            return RefusalSignal(
                is_refusal=True,
                reason="local-heuristic",
                matched=m.group(0)[:200],
            )
    return RefusalSignal(is_refusal=False)


def pick_fallback_model(current: str, fallbacks: list[str]) -> str | None:
    """Return the first fallback model that isn't ``current``."""
    for m in fallbacks or []:
        if m and m != current:
            return m
    return None
