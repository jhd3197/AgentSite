"""Built-in design direction library.

Ported verbatim from `open-design/apps/daemon/src/prompts/directions.ts` —
palette OKLch values, font stacks, and posture cues all copied as-is. When the
user picks `brand_mode == "pick_direction"` and a `direction_id`, the Designer
agent is skipped and `StyleSpec` is synthesized from the chosen direction.

Adding a direction: append to `DESIGN_DIRECTIONS`. Keep entries visually
distinct — two near-identical directions defeat the purpose.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DesignDirection:
    """One direction spec: palette, fonts, posture."""

    id: str
    label: str
    mood: str
    references: list[str]
    display_font: str
    body_font: str
    palette: dict[str, str]  # bg, surface, fg, muted, border, accent — OKLch strings
    posture: list[str]
    mono_font: str | None = None


DESIGN_DIRECTIONS: list[DesignDirection] = [
    DesignDirection(
        id="editorial-monocle",
        label="Editorial — Monocle / FT magazine",
        mood=(
            "Print-magazine feel for explicitly editorial or publishing briefs. Generous "
            "whitespace, large serif headlines, restrained palette of neutral paper + ink "
            "+ a single brand-justified accent."
        ),
        references=["Monocle", "The Financial Times Weekend", "NYT Magazine", "It's Nice That"],
        display_font="'Iowan Old Style', 'Charter', Georgia, serif",
        body_font="-apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif",
        palette={
            "bg":      "oklch(98% 0.004 95)",
            "surface": "oklch(100% 0.002 95)",
            "fg":      "oklch(20% 0.018 70)",
            "muted":   "oklch(48% 0.012 70)",
            "border":  "oklch(90% 0.006 95)",
            "accent":  "oklch(52% 0.10 28)",
        },
        posture=[
            "serif display, sans body, mono for metadata only",
            "no shadows, no rounded cards — borders + whitespace do the work",
            "one decisive image, cropped only at the bottom",
            "kicker / eyebrow in mono uppercase, one accent color used at most twice",
        ],
    ),
    DesignDirection(
        id="modern-minimal",
        label="Modern minimal — Linear / Vercel",
        mood=(
            "Quiet, precise, software-native. System fonts, crisp neutral foundations, and "
            "a small but visible product palette so the interface feels shipped rather than "
            "greyscale."
        ),
        references=["Linear", "Vercel", "Notion 2024", "Stripe docs"],
        display_font="-apple-system, BlinkMacSystemFont, 'SF Pro Display', system-ui, sans-serif",
        body_font="-apple-system, BlinkMacSystemFont, 'SF Pro Text', system-ui, sans-serif",
        palette={
            "bg":      "oklch(99% 0.002 240)",
            "surface": "oklch(100% 0 0)",
            "fg":      "oklch(18% 0.012 250)",
            "muted":   "oklch(54% 0.012 250)",
            "border":  "oklch(92% 0.005 250)",
            "accent":  "oklch(58% 0.18 255)",
        },
        posture=[
            "tight letter-spacing on display sizes (-0.02em)",
            "hairline borders only, no shadows except dropdowns/modals",
            "mono numerics with `font-variant-numeric: tabular-nums`",
            "sticky frosted nav, content-led layouts",
            "primary action color + one secondary signal + status colors",
        ],
    ),
    DesignDirection(
        id="human-approachable",
        label="Human / approachable — Airbnb / Duolingo systems",
        mood=(
            "Friendly and tactile without the generic cozy canvas. Clean neutral background, "
            "product-led color system, generous radii, clear hierarchy. Good for consumer "
            "tools, marketplaces, wellness, education, AI assistants."
        ),
        references=["Airbnb", "Duolingo product surfaces", "Miro", "Mercury"],
        display_font="'Sohne', 'Avenir Next', -apple-system, BlinkMacSystemFont, system-ui, sans-serif",
        body_font="-apple-system, BlinkMacSystemFont, 'SF Pro Text', system-ui, sans-serif",
        palette={
            "bg":      "oklch(98% 0.004 240)",
            "surface": "oklch(100% 0 0)",
            "fg":      "oklch(20% 0.02 240)",
            "muted":   "oklch(50% 0.018 240)",
            "border":  "oklch(90% 0.006 240)",
            "accent":  "oklch(56% 0.12 170)",
        },
        posture=[
            "sans display with strong weight contrast, system body for readability",
            "comfortable radii (12-18px) paired with crisp grid alignment",
            "primary + secondary/domain accent + clear status colors",
            "subtle elevation only on interactive cards",
            "avoid generic pastel/beige gradients",
        ],
    ),
    DesignDirection(
        id="tech-utility",
        label="Tech / utility — Datadog / GitHub",
        mood=(
            "Data-dense, monospace-friendly, dark or light + grid. Made for engineers and "
            "operators who want information per square inch, not vibes."
        ),
        references=["Datadog", "GitHub", "Cloudflare dashboard", "Sentry"],
        display_font="-apple-system, BlinkMacSystemFont, 'Inter', 'Segoe UI', system-ui, sans-serif",
        body_font="-apple-system, BlinkMacSystemFont, 'Inter', 'Segoe UI', system-ui, sans-serif",
        mono_font="'JetBrains Mono', 'IBM Plex Mono', ui-monospace, Menlo, monospace",
        palette={
            "bg":      "oklch(98% 0.005 250)",
            "surface": "oklch(100% 0 0)",
            "fg":      "oklch(22% 0.02 240)",
            "muted":   "oklch(50% 0.018 240)",
            "border":  "oklch(90% 0.008 240)",
            "accent":  "oklch(58% 0.16 145)",
        },
        posture=[
            "sans display + sans body (one family) is OK here",
            "tabular numerics everywhere, mono for code / IDs / hashes",
            "dense tables with hairline borders, no row striping",
            "inline status pills with restrained tinted backgrounds",
            "avoid hero images, oversized headlines, marketing copy",
        ],
    ),
    DesignDirection(
        id="brutalist-experimental",
        label="Brutalist / experimental — Are.na / Yale",
        mood=(
            "Loud type. Visible grid. System sans + a single oversized serif. Deliberate "
            "ugliness as confidence. Great for art, indie, agency, manifesto pages."
        ),
        references=["Are.na", "Yale Center for British Art", "mschf", "Read.cv"],
        display_font="'Times New Roman', 'Iowan Old Style', Georgia, serif",
        body_font="ui-monospace, 'IBM Plex Mono', 'JetBrains Mono', Menlo, monospace",
        palette={
            "bg":      "oklch(98% 0.004 240)",
            "surface": "oklch(100% 0 0)",
            "fg":      "oklch(15% 0.02 100)",
            "muted":   "oklch(40% 0.02 100)",
            "border":  "oklch(15% 0.02 100)",
            "accent":  "oklch(60% 0.22 25)",
        },
        posture=[
            "display = serif at extreme sizes (clamp(80px, 12vw, 200px))",
            "body = monospace — yes, monospace as body, deliberately",
            "borders are full-strength fg (1.5-2px), not muted greys",
            "asymmetric layouts: one column 70%, the other 30%",
            "almost no border-radius (0-2px); no shadows, no gradients",
            "underline links, no hover decoration",
        ],
    ),
]


_BY_ID = {d.id: d for d in DESIGN_DIRECTIONS}


def find_direction(direction_id: str | None) -> DesignDirection | None:
    """Return the direction with this id, or None if unknown."""
    if not direction_id:
        return None
    return _BY_ID.get(direction_id)


def synthesize_style_spec(direction: DesignDirection):
    """Build a `StyleSpec` from a direction's tokens — no LLM call.

    Maps the 6-color OKLch palette into the StyleSpec's color slots, the
    display/body/mono fonts into the typography slots, and stores both the
    `direction_id` and parallel OKLch fields so downstream consumers can pick
    whichever form fits.
    """
    from ..models import StyleSpec

    p = direction.palette
    return StyleSpec(
        # Map OKLch values directly into the color fields (CSS accepts oklch())
        primary_color=p["accent"],
        secondary_color=p["fg"],
        accent_color=p["accent"],
        background_color=p["bg"],
        surface_color=p["surface"],
        text_color=p["fg"],
        text_secondary_color=p["muted"],
        border_color=p["border"],
        font_heading=direction.display_font,
        font_body=direction.body_font,
        font_mono=direction.mono_font or "JetBrains Mono",
        direction_id=direction.id,
        # Personality fields — a picked direction IS an aesthetic decision;
        # carry it through so conventions.css and the dev personas see it.
        aesthetic_direction=f"{direction.label} — {direction.mood}",
        signature_element=direction.posture[0] if direction.posture else "",
        motion_language="one orchestrated page-load — staggered fade-up reveals via conventions.css [data-reveal-group]",
        bg_oklch=p["bg"],
        surface_oklch=p["surface"],
        fg_oklch=p["fg"],
        muted_oklch=p["muted"],
        border_oklch=p["border"],
        accent_oklch=p["accent"],
    )


def direction_summary(direction: DesignDirection) -> dict:
    """Compact dict for API / picker UI."""
    return {
        "id": direction.id,
        "label": direction.label,
        "mood": direction.mood,
        "references": list(direction.references),
        "display_font": direction.display_font,
        "body_font": direction.body_font,
        "mono_font": direction.mono_font,
        "palette": dict(direction.palette),
        "posture": list(direction.posture),
    }


def list_direction_summaries() -> list[dict]:
    return [direction_summary(d) for d in DESIGN_DIRECTIONS]
