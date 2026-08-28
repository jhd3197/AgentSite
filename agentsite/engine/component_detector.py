"""Auto-detect reusable sections in a generated page and save them as
project components.

After a successful generation, this walks the page's final HTML looking
for top-level sections worth reusing (hero, CTA, features, pricing, …),
turns each into a BlockDefinition draft via ``component_extractor``,
and persists the best few to the project's component library.

Pure heuristics — deterministic, no LLM call. Nav/header/footer are
EXCLUDED: they are shared layout chrome handled by scaffolds /
shared-components, not library components.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from bs4 import BeautifulSoup, Tag

from ..models import BlockFieldModel, ProjectComponent
from .component_extractor import extract

logger = logging.getLogger("agentsite.component_detector")

# --- thresholds -------------------------------------------------------------
MIN_MARKUP_CHARS = 200  # skip sections with less markup than this
MAX_AUTO_SAVE = 5  # cap on components auto-saved per generation

# Auto-saved components are marked distinctly via these existing fields.
AUTO_CATEGORY = "auto"
AUTO_THUMBNAIL = "🤖"

# --- exclusion rules (shared layout chrome, never library components) -------
_EXCLUDED_TAGS = {"nav", "header", "footer"}
_EXCLUDED_ROLES = {"navigation", "banner", "contentinfo"}
_EXCLUDED_RE = re.compile(r"\b(nav|navbar|header|footer|menu|breadcrumb)\b", re.IGNORECASE)

# --- classification keywords (first match wins) -----------------------------
_CATEGORY_KEYWORDS = (
    "hero", "cta", "feature", "pricing", "testimonial", "faq", "gallery",
    "stats", "team", "contact", "about", "newsletter", "subscribe", "logo",
    "partner", "portfolio", "showcase", "benefit", "service", "process",
    "steps", "blog", "quote",
)
_CATEGORY_RES = {kw: re.compile(rf"\b{re.escape(kw)}", re.IGNORECASE) for kw in _CATEGORY_KEYWORDS}

_HEADING_TAGS = ["h1", "h2", "h3", "h4"]


@dataclass
class DetectedSection:
    """One candidate reusable section found in a page."""

    category: str  # classification keyword ("hero", "cta", …) or "section"
    html: str  # the section's outer HTML
    heading: str  # first heading text ("" if none)
    size: int  # markup length — used to rank candidates


def detect_sections(html: str) -> list[DetectedSection]:
    """Find candidate reusable sections in a page's final HTML.

    Walks top-level ``<section>`` / ``<div role=...>`` elements (descending
    through plain wrapper divs / <main>), excluding nav/header/footer and
    anything containing the site's main ``<nav>``. Tiny sections and
    sections without a heading are skipped.

    Returns candidates ranked best-first (largest markup first).
    """
    soup = BeautifulSoup(html or "", "html.parser")
    root = soup.find("body") or soup

    candidates: list[DetectedSection] = []

    def _walk(parent: Any) -> None:
        for child in parent.children:
            if not isinstance(child, Tag):
                continue
            tag = child.name.lower()
            if _is_excluded(child, tag):
                continue
            if tag == "section" or (tag == "div" and child.get("role")):
                candidate = _evaluate(child)
                if candidate is not None:
                    candidates.append(candidate)
                continue  # don't descend into a candidate
            # Plain wrapper (div/main/etc.) — descend to find sections.
            _walk(child)

    _walk(root)
    candidates.sort(key=lambda c: c.size, reverse=True)
    return candidates


async def save_detected_components(
    *,
    project_id: str,
    page_slug: str,
    version: int,
    html: str,
    repo: Any,
    max_save: int = MAX_AUTO_SAVE,
) -> list[dict[str, str]]:
    """Detect reusable sections in `html` and persist new ones to `repo`.

    Dedupes against the existing library: a candidate is skipped when its
    ``auto-{category}`` slug already exists, or when its extracted template
    is identical (whitespace-normalized) to an existing component's.

    Returns a list of ``{"slug", "name"}`` for the components saved.
    """
    if repo is None or not html:
        return []
    candidates = detect_sections(html)
    if not candidates:
        return []

    existing = await repo.list_by_project(project_id)
    existing_slugs = {c.slug for c in existing}
    known_templates = {_normalize_template(c.template) for c in existing}
    run_slugs: set[str] = set()

    saved: list[dict[str, str]] = []
    for cand in candidates:
        if len(saved) >= max_save:
            break
        base_slug = f"auto-{cand.category}"
        if base_slug in existing_slugs:
            continue  # library already has this kind of auto component
        slug = base_slug
        n = 2
        while slug in run_slugs:
            slug = f"{base_slug}-{n}"
            n += 1

        name = cand.heading or f"{cand.category.title()} section"
        draft = extract(cand.html, default_name=name, default_slug=slug)
        normalized = _normalize_template(draft["template"])
        if normalized in known_templates:
            continue  # near-identical template already in the library

        component = ProjectComponent(
            project_id=project_id,
            slug=slug,
            name=name,
            category=AUTO_CATEGORY,
            description=(
                f"Auto-detected {cand.category} section from page "
                f"'{page_slug}' (v{version})."
            ),
            thumbnail=AUTO_THUMBNAIL,
            template=draft["template"],
            fields=[BlockFieldModel(**f) for f in draft["fields"]],
            source_page_slug=page_slug,
            source_version=version,
        )
        await repo.create(component)
        run_slugs.add(slug)
        known_templates.add(normalized)
        saved.append({"slug": slug, "name": name})

    if saved:
        logger.info(
            "Auto-saved %d component(s) for project %s from page '%s' v%d: %s",
            len(saved), project_id, page_slug, version,
            [s["slug"] for s in saved],
        )
    return saved


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_excluded(el: Tag, tag: str) -> bool:
    """True for nav/header/footer chrome or anything containing a <nav>."""
    if tag in _EXCLUDED_TAGS:
        return True
    role = (el.get("role") or "").strip().lower()
    if role in _EXCLUDED_ROLES:
        return True
    classes = " ".join(el.get("class") or [])
    ident = el.get("id") or ""
    if _EXCLUDED_RE.search(f"{classes} {ident}"):
        return True
    return el.find("nav") is not None


def _classify(el: Tag, tag: str) -> str:
    """Classify a section by tag/class/id keywords; default 'section'."""
    classes = " ".join(el.get("class") or [])
    haystack = f"{tag} {classes} {el.get('id') or ''} {el.get('role') or ''}"
    for kw in _CATEGORY_KEYWORDS:
        if _CATEGORY_RES[kw].search(haystack):
            return kw
    return "section"


def _evaluate(el: Tag) -> DetectedSection | None:
    """Apply size/heading thresholds and build a candidate, or None."""
    markup = str(el)
    if len(markup) < MIN_MARKUP_CHARS:
        return None
    heading_el = el.find(_HEADING_TAGS)
    if heading_el is None:
        return None
    heading = heading_el.get_text(strip=True)[:60]
    return DetectedSection(
        category=_classify(el, el.name.lower()),
        html=markup,
        heading=heading,
        size=len(markup),
    )


def _normalize_template(template: str) -> str:
    """Whitespace-normalized lowercase template for equality dedupe."""
    return re.sub(r"\s+", " ", (template or "").strip().lower())
