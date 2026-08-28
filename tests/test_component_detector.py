"""Auto-detection of reusable sections after generation.

Covers: section detection/classification in sample page HTML, exclusion of
nav/header/footer chrome, tiny-section thresholds, dedupe against the
existing project library, the per-generation cap, and the end-to-end path
where detected sections land in ``project_component_repo``.
"""

from __future__ import annotations

import pytest

from agentsite.engine.component_detector import (
    MAX_AUTO_SAVE,
    detect_sections,
    save_detected_components,
)
from agentsite.models import Project, ProjectComponent
from agentsite.storage.database import Database
from agentsite.storage.repository import ProjectComponentRepository, ProjectRepository


@pytest.fixture
async def component_repo(tmp_path):
    db = Database(db_path=tmp_path / "test.db")
    await db.connect()
    project_repo = ProjectRepository(db)
    await project_repo.create(Project(id="p1", name="p1", model="openai/gpt-4o"))
    repo = ProjectComponentRepository(db)
    yield repo
    await db.close()


def _section(cls: str, heading: str, *, tag: str = "h2", extra: str = "") -> str:
    """A section comfortably above the 200-char markup threshold."""
    body = "Some descriptive paragraph text for this section. " * 3
    return (
        f'<section class="{cls}">'
        f"<{tag}>{heading}</{tag}>"
        f"<p>{body}</p>"
        f"{extra}"
        f"</section>"
    )


SAMPLE_PAGE = f"""<!DOCTYPE html>
<html>
<head><title>Sample</title></head>
<body>
  <header class="site-header">
    <nav class="main-nav"><a href="/">Home</a><a href="/about">About</a></nav>
  </header>
  {_section("hero", "Build faster with AgentSite", tag="h1", extra='<a href="#start">Get started</a>')}
  <div class="page-wrapper">
    {_section("features-grid", "Everything you need", extra='<div class="card"><h3>Fast</h3><p>Quick builds for every page on your site.</p></div>')}
  </div>
  {_section("cta-banner", "Ready to launch?", extra='<a href="/contact">Contact us</a>')}
  <section class="tiny"><h2>Hi</h2></section>
  <section class="headingless"><p>No heading here, just a long run of plain text that goes on and on and on and on and on and on and on and on and on and on and on and on.</p></section>
  {_section("hero-with-nav", "Hero hosting the nav", tag="h1", extra='<nav><a href="/">Home</a></nav>')}
  <footer class="site-footer">
    <p>© 2026 Example Corp. All rights reserved. Footer content that is long enough to pass the size threshold anyway and then some more text.</p>
  </footer>
</body>
</html>
"""


# ------------------------------------------------------------------
# Detection heuristics
# ------------------------------------------------------------------


class TestDetectSections:
    def test_finds_classified_sections(self):
        categories = {c.category for c in detect_sections(SAMPLE_PAGE)}
        assert {"hero", "feature", "cta"} <= categories

    def test_candidates_carry_heading_and_markup(self):
        by_cat = {c.category: c for c in detect_sections(SAMPLE_PAGE)}
        assert by_cat["cta"].heading == "Ready to launch?"
        assert "cta-banner" in by_cat["cta"].html

    def test_descends_through_plain_wrappers(self):
        # The features section lives inside a plain <div class="page-wrapper">.
        assert any(c.category == "feature" for c in detect_sections(SAMPLE_PAGE))

    def test_excludes_nav_header_footer(self):
        htmls = [c.html for c in detect_sections(SAMPLE_PAGE)]
        assert not any('class="site-header"' in h for h in htmls)
        assert not any('class="site-footer"' in h for h in htmls)
        assert not any("main-nav" in h for h in htmls)

    def test_excludes_section_containing_main_nav(self):
        assert not any(c.heading == "Hero hosting the nav" for c in detect_sections(SAMPLE_PAGE))

    def test_skips_tiny_and_headingless_sections(self):
        headings = {c.heading for c in detect_sections(SAMPLE_PAGE)}
        assert "Hi" not in headings  # below the markup threshold
        assert not any('class="headingless"' in c.html for c in detect_sections(SAMPLE_PAGE))

    def test_largest_candidates_first(self):
        sizes = [c.size for c in detect_sections(SAMPLE_PAGE)]
        assert sizes == sorted(sizes, reverse=True)

    def test_empty_or_trivial_html(self):
        assert detect_sections("") == []
        assert detect_sections("<p>hello</p>") == []


# ------------------------------------------------------------------
# Persistence — dedupe, cap, end-to-end
# ------------------------------------------------------------------


class TestSaveDetectedComponents:
    async def test_end_to_end_components_land_in_repo(self, component_repo):
        saved = await save_detected_components(
            project_id="p1", page_slug="home", version=1,
            html=SAMPLE_PAGE, repo=component_repo,
        )
        slugs = {s["slug"] for s in saved}
        assert {"auto-hero", "auto-feature", "auto-cta"} <= slugs

        items = await component_repo.list_by_project("p1")
        assert len(items) == len(saved)
        for comp in items:
            # Auto-saved components are marked distinctly.
            assert comp.category == "auto"
            assert comp.source_page_slug == "home"
            assert comp.source_version == 1
            assert "Auto-detected" in comp.description
            # Draft carries editable fields + placeholders.
            assert comp.fields, comp.slug
            assert "{{" in comp.template

    async def test_rerun_on_same_page_saves_nothing(self, component_repo):
        kwargs = dict(project_id="p1", page_slug="home", version=1, html=SAMPLE_PAGE, repo=component_repo)
        first = await save_detected_components(**kwargs)
        assert first
        second = await save_detected_components(**kwargs)
        assert second == []
        assert len(await component_repo.list_by_project("p1")) == len(first)

    async def test_skips_slug_already_in_library(self, component_repo):
        existing = await save_detected_components(
            project_id="p1", page_slug="home", version=1,
            html=SAMPLE_PAGE, repo=component_repo,
        )
        assert any(s["slug"] == "auto-cta" for s in existing)
        # New page with only a CTA → its auto-cta slug already exists.
        other_page = (
            "<html><body>"
            + _section("cta", "A different CTA heading entirely", extra='<a href="/x">Go</a>')
            + "</body></html>"
        )
        saved = await save_detected_components(
            project_id="p1", page_slug="about", version=1,
            html=other_page, repo=component_repo,
        )
        assert saved == []

    async def test_skips_near_identical_template(self, component_repo):
        # Seed the library with a component whose extracted template matches
        # what the detector will produce for this exact section markup.
        cta_html = _section("cta", "Ready to launch?", extra='<a href="/contact">Contact us</a>')
        seed = await save_detected_components(
            project_id="p1", page_slug="home", version=1,
            html=f"<html><body>{cta_html}</body></html>", repo=component_repo,
        )
        assert len(seed) == 1
        # Delete the row but keep its template under a different slug to
        # exercise the template-equality dedupe (not the slug dedupe).
        items = await component_repo.list_by_project("p1")
        template = items[0].template
        await component_repo.delete(items[0].id)
        await component_repo.create(ProjectComponent(
            project_id="p1", slug="user-cta", name="User CTA", template=template,
        ))
        saved = await save_detected_components(
            project_id="p1", page_slug="home", version=2,
            html=f"<html><body>{cta_html}</body></html>", repo=component_repo,
        )
        assert saved == []

    async def test_caps_at_max_auto_save(self, component_repo):
        kinds = ["hero", "cta", "features", "pricing", "faq", "team", "contact"]
        sections = "".join(_section(k, f"Heading {k}") for k in kinds)
        saved = await save_detected_components(
            project_id="p1", page_slug="home", version=1,
            html=f"<html><body>{sections}</body></html>", repo=component_repo,
        )
        assert len(saved) == MAX_AUTO_SAVE
        assert len(await component_repo.list_by_project("p1")) == MAX_AUTO_SAVE

    async def test_no_repo_or_no_html_is_noop(self, component_repo):
        assert await save_detected_components(
            project_id="p1", page_slug="home", version=1, html=SAMPLE_PAGE, repo=None,
        ) == []
        assert await save_detected_components(
            project_id="p1", page_slug="home", version=1, html="", repo=component_repo,
        ) == []


# ------------------------------------------------------------------
# Pipeline wiring
# ------------------------------------------------------------------


class TestPipelineWiring:
    def test_one_shot_pipeline_accepts_component_repo(self, project_manager):
        from agentsite.engine.pipeline import GenerationPipeline

        sentinel = object()
        pipeline = GenerationPipeline(project_manager, project_component_repo=sentinel)
        assert pipeline._project_component_repo is sentinel

    def test_progressive_pipeline_accepts_component_repo(self, project_manager):
        from agentsite.engine.progressive import ProgressivePipeline

        sentinel = object()
        pipeline = ProgressivePipeline(project_manager, project_component_repo=sentinel)
        assert pipeline._project_component_repo is sentinel
