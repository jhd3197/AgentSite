"""Multi-dimensional critique panel.

Four single-dimension reviewer agents + a judge that aggregates their scores
into a `ReviewVerdict`. Each reviewer scores 1-10 on its dimension; the judge
takes the minimum (or its own override) as the overall score and decides
approval against `settings.review_approval_threshold`.

The panel is invoked by `run_critique_panel()` which fans out reviewers via
`AsyncDebateGroup(rounds=1)` — using a debate group of 1 round with distinct
positions gives us OD-style "5-dim radar" semantics on top of Prompture's
group primitive. The judge is the DebateGroup's `judge` slot.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from prompture import AsyncAgent as Agent
from prompture import Persona as _Persona
from prompture import clean_json_text
from prompture.groups.debate import AsyncDebateGroup, DebateConfig, DebateResult

from ..engine.capabilities import supports_structured_output
from ..models import CRITIQUE_DIMENSIONS, DimensionScore, ReviewVerdict
from .tools import reviewer_tools

# Acknowledge symbol used in docstrings / typing (no functional use)
_ = CRITIQUE_DIMENSIONS

logger = logging.getLogger("agentsite.critique")


def _dim_persona(dimension: str, focus: str, checklist: list[str]) -> _Persona:
    return _Persona(
        name=f"agentsite_critique_{dimension}",
        system_prompt=(
            "You are a single-dimension QA reviewer. Your dimension is "
            f"**{dimension}** — score the generated page on this dimension ONLY. "
            "Ignore other dimensions (other reviewers cover those).\n\n"
            f"## Focus\n{focus}\n\n"
            "## Checklist\n"
            + "\n".join(f"- {item}" for item in checklist)
            + "\n\n"
            "Workflow:\n"
            "1. Call list_files() then read_file() on the generated HTML/CSS/JS.\n"
            "2. Read any relevant guides via read_guide() (design-system.md, etc).\n"
            "3. Respond with a JSON object: "
            '{"dimension": "' + dimension + '", "score": 1-10, '
            '"issues": ["..."], "suggestions": ["..."]}\n\n'
            "Score honestly. 10 = best-in-class on this dimension. 5 = average. "
            "1 = broken. Be specific about issues (file names, line ranges, "
            "selector names). One JSON object only. No prose."
        ),
        description=f"Single-dimension critic for {dimension}",
        settings={"temperature": 0.2},
    )


DIM_VISUAL = _dim_persona(
    "visual_fidelity",
    "How closely the rendered page follows the StyleSpec / direction tokens.",
    [
        "Are the StyleSpec color tokens used (no rogue hex / oklch values)?",
        "Typography rhythm: heading scale, line-height, letter-spacing match spec",
        "Spacing system (4/8px scale) respected — no random padding values",
        "Borders, radii, shadows match the design system tokens",
        "One accent color used at most twice per screen",
    ],
)

DIM_A11Y = _dim_persona(
    "accessibility",
    "WCAG 2.1 AA conformance for the rendered page.",
    [
        "Color contrast >= 4.5:1 for body text, 3:1 for large text",
        "Focus order matches reading order; visible :focus-visible styles",
        "All images have meaningful alt text; decorative images alt=''",
        "Form inputs have associated <label> or aria-label",
        "Headings form a valid h1-h6 hierarchy (single h1 per page)",
        "Interactive elements have role / aria-* where needed",
    ],
)

DIM_CONTENT = _dim_persona(
    "content_quality",
    "Copy quality: no Lorem ipsum, no 'Feature One', specific to the brief.",
    [
        "No placeholder text ('Lorem ipsum', 'Your Title Here', 'Feature One')",
        "Headlines are specific, not generic ('AI for sales teams' > 'Welcome')",
        "CTAs are action-oriented ('Start free trial' > 'Click here')",
        "Microcopy and labels match brand voice in copy-guide.md (if present)",
        "No invented metrics ('99.9% uptime') without a source",
    ],
)

DIM_CODE = _dim_persona(
    "code_health",
    "Semantic HTML, structural correctness, perf hygiene.",
    [
        "Semantic HTML5 (<main>, <nav>, <section>, <article>, <footer>)",
        "No console errors (check JS for obvious bugs / undefined refs)",
        "No huge inline styles / scripts — CSS in styles.css, JS in script.js",
        "Images sized (width/height attrs) to avoid CLS",
        "No deprecated tags / attributes; valid HTML5",
        "Mobile-first responsive — works at 360px without overflow",
    ],
)


JUDGE_PERSONA = _Persona(
    name="agentsite_critique_judge",
    system_prompt=(
        "You are the head reviewer aggregating per-dimension verdicts from a "
        "panel of single-dimension critics.\n\n"
        "INPUT: a transcript with one JSON verdict per dimension (visual_fidelity, "
        "accessibility, content_quality, code_health).\n\n"
        "OUTPUT: a single JSON object matching this schema EXACTLY:\n"
        '{\n'
        '  "scores": [\n'
        '    {"dimension": "visual_fidelity", "score": 1-10, "issues": [...], "suggestions": [...]},\n'
        '    {"dimension": "accessibility", "score": 1-10, "issues": [...], "suggestions": [...]},\n'
        '    {"dimension": "content_quality", "score": 1-10, "issues": [...], "suggestions": [...]},\n'
        '    {"dimension": "code_health", "score": 1-10, "issues": [...], "suggestions": [...]}\n'
        '  ],\n'
        '  "overall_score": 1-10,\n'
        '  "approved": true|false,\n'
        '  "summary": "one paragraph explaining the verdict"\n'
        '}\n\n'
        "RULES:\n"
        "- overall_score = min(dimension scores). A single failing dimension drags it down.\n"
        "- approved = true iff overall_score >= 7 AND no dimension is < 7.\n"
        "- Preserve every dimension entry from the panel transcript; do not drop any.\n"
        "- Respond with the JSON object ONLY — no markdown fence, no prose."
    ),
    description="Aggregates panel reviewer scores into a single ReviewVerdict.",
    settings={"temperature": 0.0},
)


def _make_reviewer(model: str, persona: _Persona, output_key: str) -> Agent:
    return Agent(
        model,
        system_prompt=persona,
        tools=reviewer_tools,
        name=persona.name,
        description=persona.description,
        output_key=output_key,
        options={"max_tokens": 1500, "temperature": 0.2},
    )


def _make_judge(model: str) -> Agent:
    if supports_structured_output(model):
        return Agent(
            model,
            system_prompt=JUDGE_PERSONA,
            output_type=ReviewVerdict,
            name=JUDGE_PERSONA.name,
            description=JUDGE_PERSONA.description,
            output_key="review_feedback",
            options={"max_tokens": 2000, "temperature": 0.0},
        )
    return Agent(
        model,
        system_prompt=JUDGE_PERSONA,
        name=JUDGE_PERSONA.name,
        description=JUDGE_PERSONA.description,
        output_key="review_feedback",
        options={"max_tokens": 2000, "temperature": 0.0},
    )


def parse_verdict(text: str) -> ReviewVerdict | None:
    """Parse a judge's JSON output into a `ReviewVerdict`, tolerant of fences."""
    if not text:
        return None
    try:
        cleaned = clean_json_text(text)
        data = json.loads(cleaned)
        return ReviewVerdict.model_validate(data)
    except Exception:
        logger.debug("Failed to parse judge verdict from text: %s", text[:200])
        return None


def synthesize_verdict_from_dim_outputs(dim_outputs: list[str]) -> ReviewVerdict:
    """Fallback aggregator when no judge is available — local min-rule synthesis.

    Each ``dim_outputs`` entry is the raw JSON text from one dimension reviewer.
    Missing or unparseable entries get a neutral score of 5.
    """
    scores: list[DimensionScore] = []
    for txt in dim_outputs:
        try:
            data = json.loads(clean_json_text(txt))
            scores.append(DimensionScore.model_validate(data))
        except Exception:
            scores.append(DimensionScore(dimension="unknown", score=5))
    overall = min((s.score for s in scores), default=5)
    return ReviewVerdict(
        scores=scores,
        overall_score=overall,
        approved=overall >= 7,
        summary="Synthesized locally (no judge agent).",
    )


async def run_critique_panel(
    model: str,
    *,
    page_slug: str,
    deps: dict[str, Any],
    callbacks: Any | None = None,
    context_note: str = "",
) -> tuple[ReviewVerdict | None, DebateResult]:
    """Run the 4-dimension critique panel + judge, return parsed verdict."""
    reviewers = [
        _make_reviewer(model, DIM_VISUAL, "critique_visual"),
        _make_reviewer(model, DIM_A11Y, "critique_a11y"),
        _make_reviewer(model, DIM_CONTENT, "critique_content"),
        _make_reviewer(model, DIM_CODE, "critique_code"),
    ]
    judge = _make_judge(model)

    # Inject deps so reviewer agents can call list_files/read_file/read_guide.
    for ag in reviewers + [judge]:
        try:
            ag.deps = deps  # type: ignore[attr-defined]
        except Exception:
            pass

    config = DebateConfig(
        rounds=1,
        positions={persona.name: persona.name.split("_")[-1] for persona in
                   (DIM_VISUAL, DIM_A11Y, DIM_CONTENT, DIM_CODE)},
        judge=judge,
        judge_prompt_template=(
            "Topic: aggregate panel verdicts for the '" + page_slug + "' page.\n\n"
            "{transcript}\n\n"
            "Produce the final ReviewVerdict JSON now."
        ),
        show_position_in_prompt=False,
    )

    group = AsyncDebateGroup(reviewers, config=config, callbacks=callbacks)
    topic = (
        f"Review the generated '{page_slug}' page on your dimension. "
        "Use list_files + read_file to inspect the actual generated code first."
    )
    if context_note:
        topic += f"\n\nContext from automated checks:\n{context_note}"
    result = await group.run(topic)

    verdict = parse_verdict(result.judge_verdict or "")
    if verdict is None and result.transcript:
        verdict = synthesize_verdict_from_dim_outputs(
            [e.content for e in result.transcript]
        )
    return verdict, result
