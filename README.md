# AgentSite

[![PyPI version](https://badge.fury.io/py/agentsite.svg)](https://badge.fury.io/py/agentsite)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker&logoColor=white)](https://github.com/jhd3197/AgentSite/blob/main/Dockerfile)
[![Built with Prompture](https://img.shields.io/badge/built%20with-Prompture-blueviolet)](https://pypi.org/project/prompture/)

[<img src="https://serverkit.ai/badge/install.png" alt="Install in ServerKit" width="240">](https://serverkit.ai/i/template/agentsite)

[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/new/template?template=https://github.com/jhd3197/AgentSite)
[![Deploy to Heroku](https://www.herokucdn.com/deploy/button.svg)](https://heroku.com/deploy?template=https://github.com/jhd3197/AgentSite)
[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/jhd3197/AgentSite)

An AI-powered website builder that uses multi-agent orchestration to generate complete, production-ready websites from a single text prompt. Nine specialized agents — four core and five specialists — collaborate to plan, design, build, and review your site.

**PyPI Package:** [pypi.org/project/agentsite](https://pypi.org/project/agentsite/)

---

## Why This Tool?

Most AI website builders give you a single LLM call that dumps out a generic template. The result is usually a wall of code with no real structure, inconsistent styling, and no quality checks. You end up spending more time fixing the output than you saved by generating it.

AgentSite takes a different approach: **nine specialized AI agents collaborate in a pipeline**, each handling what they're best at. A PM agent plans the site structure and selects the build strategy. A Designer agent defines the visual system. In monolithic mode, a single Developer agent writes all the code; in specialist mode, dedicated Markup, Style, Script, and Image agents work in parallel for faster builds. A Reviewer agent evaluates quality and can send work back for revision — just like a real team would.

The entire pipeline is **model-agnostic**. You can use OpenAI, Claude, Google, Groq, Ollama, LM Studio, or any provider supported by [Prompture](https://pypi.org/project/prompture/). Swap models without changing anything else.

You get **two ways to work**: a full Web UI with live preview, chat input, and real-time progress tracking — or a CLI for generating sites directly from the terminal. Both produce the same output: clean, semantic HTML with proper accessibility baked in.

Under the hood, the pipeline enforces **quality gates**. The Reviewer agent scores every page against criteria like accessibility, semantic markup, and visual consistency. If the score is too low, the Developer gets feedback and iterates — up to two revision loops — before the site is finalized.

---

## Table of Contents

- [Quick Start](#quick-start)
- [How It Works](#how-it-works)
- [Features](#features)
- [CLI Reference](#cli-reference)
- [Web UI](#web-ui)
- [Embeddable Component](#embeddable-component)
- [Configuration](#configuration)
- [Project Structure](#project-structure)
- [Tech Stack](#tech-stack)
- [Development](#development)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)

---

## Quick Start

```bash
# 1. Install from PyPI
pip install agentsite

# 2. Set up your API keys
cp .env.copy .env
# Edit .env with your provider keys (OPENAI_API_KEY, CLAUDE_API_KEY, etc.)

# 3. Generate a website
agentsite generate "A portfolio website for a photographer"
```

**That's it!** A complete multi-page website will be generated in your output directory.

**Prefer a UI?** Launch the web interface instead:

```bash
agentsite serve
# Open http://127.0.0.1:6391
```

---

## How It Works

AgentSite supports two build modes, chosen automatically by the PM agent based on site complexity:

**Monolithic mode** — a single Developer agent handles all code:

```
Prompt --> PM --> Designer --> Developer <--> Reviewer --> Website
```

**Specialist mode** — dedicated agents work in parallel for faster builds:

```
Prompt --> PM --> Designer --> Image -----> Reviewer --> Website
                              Markup --/
                              Style --/
                              Script -/
```

### Core Agents

| Agent | Role | Output |
| --- | --- | --- |
| **PM** | Analyzes the prompt, plans site structure, selects build strategy and agents | `SitePlan` |
| **Designer** | Defines colors, typography, spacing, and the visual system | `StyleSpec` |
| **Developer** | Writes semantic HTML, CSS, and vanilla JS for each page (monolithic mode) | `PageOutput` |
| **Reviewer** | Evaluates quality, accessibility, and correctness (score >= 7 = approved) | `ReviewFeedback` |

### Specialist Agents

| Agent | Role | Output |
| --- | --- | --- |
| **Markup** | Writes HTML/JSX markup with semantic structure and ARIA labels | `MarkupOutput` |
| **Style** | Writes CSS or SCSS stylesheets with custom properties and responsive design | `StyleOutput` |
| **Script** | Writes vanilla JavaScript for interactivity and animations | `ScriptOutput` |
| **Image** | Generates images and manages the asset library | `ImageOutput` |

The Reviewer can trigger revision loops, sending feedback back to the Developer or specialists until quality meets the approval threshold. This runs up to two iterations per page.

---

## Features

### Multi-Agent Pipeline

Nine agents with distinct personas coordinate through [Prompture](https://pypi.org/project/prompture/) groups. Four core agents handle planning, design, development, and QA. Five specialist agents (Markup, Style, SCSS, Script, Image) can run in parallel for faster builds. Each agent has a focused role and structured output — no single monolithic prompt trying to do everything.

### Real-Time Progress

WebSocket-based live updates during generation. Watch each agent work in real time through the Web UI with per-agent status, token usage, and timing.

### Multi-Provider LLM Support

Use any model from any provider: OpenAI, Claude, Google, Groq, Grok, Ollama, LM Studio, OpenRouter, and more. Switch models per-generation without changing configuration.

### Accessible Output

Agents enforce WCAG AA contrast, semantic HTML, ARIA labels, and keyboard navigation. Accessibility is built into the generation pipeline, not bolted on after.

### Export

Download generated sites as ZIP archives or browse them directly through the built-in preview server.

### Discovery brief & direction picker

Before the PM agent runs, the frontend shows a 30-second discovery form (ported from open-design) — what surface, who it's for, brand context, tone, scale, constraints. If the user picks "Pick a direction for me", a follow-up direction picker shows 5 OKLch palettes (editorial-monocle, modern-minimal, human-approachable, tech-utility, brutalist-experimental). Choosing a direction skips the Designer agent entirely and synthesizes the StyleSpec deterministically from the chosen palette.

### Skill catalog + RAG-style retrieval

Eight bundled skills (`saas-landing`, `pricing-page`, `dashboard`, `docs-page`, `blog-post`, `portfolio`, `mobile-app`, `coming-soon`) live under `agentsite/skills/<id>/SKILL.md`. The PM agent receives a ranked top-5 list per brief (via lightweight token-overlap retrieval over the catalog) instead of a hardcoded full inventory; it picks `skill_id` per page and the Developer's prompt inherits that skill's instructions.

### Design system inheritance

Four bundled design systems (`linear`, `vercel`, `stripe`, `notion`) under `agentsite/design_systems/<id>/{DESIGN.md, tokens.css}`. Setting `style_spec.inherits_from = "linear"` makes the Designer agent extend those tokens instead of inventing new ones. Users can save their own systems via the API; they persist in SQLite alongside the bundled ones.

### Multi-dimensional critique + per-project quality ratchet

Behind `AGENTSITE_USE_CRITIQUE_PANEL=1`: a panel of four single-dimension reviewers (visual_fidelity, accessibility, content_quality, code_health) scores each generation; a judge agent aggregates into a `ReviewVerdict`. An only-up `quality_ratchet.json` per project enforces "every dimension must equal or exceed its current floor" — regressions are rejected, accepted runs raise the floor. Surfaced in the Analytics dashboard.

### Pre-flight enforcement

The Developer must call `read_guide('design-system.md')` and `read_guide('architecture.md')` before its first `write_file`. Returns an actionable error otherwise; self-disarms after the first satisfied write so subsequent writes are unblocked.

### Steer mailbox (in-flight steering)

While generation is running, the chat input flips to "Steer" mode. Steer messages flow through the WebSocket into a per-project mailbox; the pipeline drains the mailbox just before the build phase and injects accumulated tweaks into the developer prompt via `{user_steer}`.

### Live srcdoc preview

`write_file` of any `*.html` publishes a `preview_update` WS event with the rendered HTML and a content hash. The preview iframe switches to `srcDoc` mode and remounts on every hash change so you see the page evolve as the agent writes it — no server round trip.

### Brand extraction (URL / screenshot / PDF)

Three-tab uploader on the project Brand page. URL extraction fetches HTML + linked CSS over an SSRF-guarded `httpx` client and derives a populated `StyleSpec` (hex palette classified by luminance + chroma into bg / surface / fg / accent slots; font sniff from a curated family list). Image extraction uses Pillow quantization; PDF extraction prefers Prompture's ingestion pipeline with a raw-bytes fallback.

### Per-project memory

Heuristic extraction after every successful generation captures durable facts from the discovery brief, in-flight steer messages, and the critique verdict ("you prefer serif headers", "no emoji in body copy", "weakest dimension last run: accessibility"). Saved to `project_memories`, deduplicated, and prepended to the PM prompt on the next run.

### Smart per-agent routing

`settings.agent_routing` maps each agent key to a strategy hint (`fast`, `cost_optimized`, `balanced`, `quality_first`) or an explicit model id; `routing_model_pools` holds the candidate pool per strategy. Critique-panel reviewers default to cheap models and the judge to quality-first so enabling the panel doesn't balloon the per-run cost.

### Refusal detection & analytics

Every agent's text output is run through `RefusalDetector` (prefers Prompture's when installed, regex fallback otherwise). Refusals are stamped onto the AgentRun record and surfaced live via the `refusal_detected` WS event. The Analytics dashboard shows refusal rate by agent alongside cost-by-routing and per-project quality ratchet trends.

### Device frames

Pixel-accurate SVG chrome (iPhone 15 Pro, Pixel, iPad Pro, MacBook) under `frontend/public/frames/`. The DeviceSwitcher in the page builder swaps the synthetic browser chrome for real device chrome around the preview iframe.

### Prompt template gallery

Six starter templates on the dashboard (`saas-landing-b2b`, `portfolio-designer`, `docs-quickstart`, `dashboard-ops`, `pricing-saas`, `coming-soon`) each link a `skill_id` + `direction_id` + concrete prompt; clicking prefills the create-project modal.

---

## Phase 1–12 Feature Flags

All non-default capabilities live behind a setting in `agentsite/config.py` (prefix env vars with `AGENTSITE_`):

| Flag | Default | Effect |
|---|---|---|
| `preflight_enabled` | `True` | Developer must call `read_guide()` for required guides before any `write_file`. |
| `preflight_required_guides` | `["design-system.md", "architecture.md"]` | Which guides satisfy the pre-flight gate. |
| `use_critique_panel` | `False` | Run the 4-dim critique panel + judge + ratchet after every successful generation. Pair with `agent_routing` to keep cost flat. |
| `use_deep_agent_developer` | `False` | Wrap the Developer in `AsyncDeepAgent` with planning on, enabling the TodoStream UI. Falls back to the tool-calling Developer when the installed Prompture predates `AsyncDeepAgent`. |
| `agent_routing` | `{accessibility: cost_optimized, …}` | Per-agent routing strategy or explicit model id. |
| `routing_model_pools` | `{fast: [], cost_optimized: [], …}` | Strategy → candidate model id pool (first wins). |

Per-project knobs live on the `Project.style_spec`:

- `style_spec.inherits_from` — id of a bundled or user-saved design system. The Designer extends those tokens instead of inventing.
- `style_spec.direction_id` — bound to the chosen `DesignDirection` from the picker; deterministically synthesized.

Per-generation overrides live on the `POST /api/projects/{id}/pages/{slug}/generate` request body:

- `discovery_brief` — answers from `GET /api/discovery/form`.
- `direction_id` — short-circuits the Designer.
- `inherits_from` — sets the design system for this run.
- `agent_models`, `provider_keys`, `max_cost`, `budget_policy` — fine-grain budget + model overrides per agent.

---

## CLI Reference

```bash
agentsite generate <prompt>       # Generate a website from a text prompt
  -m, --model <provider/model>    # LLM model to use (default: openai/gpt-4o)
  -o, --output <dir>              # Output directory
  -n, --name <name>               # Project name

agentsite serve                   # Start the web UI server
  --host <host>                   # Server host (default: 127.0.0.1)
  --port <port>                   # Server port (default: 6391)
  --reload                        # Enable auto-reload for development

agentsite models                  # List available LLM models
```

---

## Web UI

Launch the browser-based interface for a full visual experience:

```bash
agentsite serve
```

The Web UI includes:

- **Dashboard** — manage projects, create new sites
- **Page Builder** — chat-based generation with live preview
- **Agent Monitoring** — see each agent's status, metrics, and activity
- **Analytics** — token usage, cost breakdown, and generation history

For development, run the backend and frontend separately with hot-reload:

```bash
# Terminal 1: Backend
agentsite serve --reload

# Terminal 2: Frontend (Vite dev server)
cd frontend && npm run dev
```

---

## Embeddable Component

Use AgentSite as a library inside any Python application — no server, database, or frontend required. Two async functions expose the full pipeline:

```python
import asyncio
import os
from pathlib import Path

from agentsite import generate_website, regenerate_page, GenerationConfig

async def main():
    # Generate a site from a prompt
    result = await generate_website(
        "A dark portfolio site with projects and contact page",
        output_dir=Path("./websites"),
        config=GenerationConfig(
            model="openai/gpt-4o",
            provider_keys={"openai": os.environ["OPENAI_API_KEY"]},
            max_cost=0.50,
        ),
        on_event=lambda e: print(f"{e.agent}: {e.type}"),
    )

    for path, html in result.files_content.items():
        print(f"{path}: {len(html)} bytes")

    # Iterate on the same project with new feedback
    v2 = await regenerate_page(
        "Make the hero section taller and add a testimonials page",
        output_dir=Path("./websites"),
        project_id=result.project_id,
        config=GenerationConfig(model="openai/gpt-4o"),
    )

if __name__ == "__main__":
    asyncio.run(main())
```

### API

| Function | Description |
| --- | --- |
| `generate_website(prompt, *, output_dir, config, on_event, project_name, slug)` | One-shot generation. Creates a project, runs the full pipeline, writes files to `output_dir`. |
| `regenerate_page(prompt, *, output_dir, project_id, slug, version, config, on_event)` | Iterate on an existing project. Auto-detects next version number and preserves the StyleSpec from prior runs. |
| `load_project(output_dir, project_id)` | Restore a project's full state from disk — metadata, conversation history, site plan, and latest page files. Returns `None` if not found. |

### GenerationConfig

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `model` | `str` | `"openai/gpt-4o"` | LLM model to use |
| `max_cost` | `float \| None` | `None` | Budget cap in USD |
| `budget_policy` | `str \| None` | `None` | Budget enforcement policy |
| `provider_keys` | `dict[str, str] \| None` | `None` | API keys per provider |
| `agent_configs` | `dict[str, AgentConfig] \| None` | `None` | Per-agent overrides |
| `style_spec` | `StyleSpec \| None` | `None` | Pre-defined design tokens |
| `logo_url` | `str` | `""` | Logo URL for the site |
| `icon_url` | `str` | `""` | Favicon URL |
| `max_review_iterations` | `int \| None` | `None` | Maximum review/fix cycles per page. `None` uses the pipeline default. |
| `review_threshold` | `int \| None` | `None` | Minimum review score to accept a page. `None` uses the pipeline default. |
| `cancel_event` | `asyncio.Event \| None` | `None` | Cooperative cancellation flag. Set the event to abort generation between phases. |
| `conversation_context` | `str` | `""` | Extra context prepended to the prompt (e.g., prior conversation history). |

### GenerationResult

| Field | Type | Description |
| --- | --- | --- |
| `project_id` | `str` | Unique project identifier |
| `files` | `list[str]` | List of generated file paths |
| `files_content` | `dict[str, str]` | File path → content mapping |
| `output_dir` | `Path` | Directory where files were written |
| `usage` | `dict` | Aggregate token/cost usage |
| `agent_runs` | `list[dict]` | Per-agent run data |
| `style_spec` | `StyleSpec \| None` | Parsed design spec (auto-saved for reuse) |
| `success` | `bool` | Whether generation completed |
| `error` | `str \| None` | Error message if failed |

### ProjectState

| Field | Type | Description |
| --- | --- | --- |
| `project_id` | `str` | Unique project identifier |
| `name` | `str` | Project name |
| `model` | `str` | LLM model used |
| `style_spec` | `StyleSpec \| None` | Design tokens from the Designer agent |
| `site_plan_raw` | `str` | Raw site plan JSON |
| `pages` | `list[PageState]` | Latest version of each page with files |
| `messages` | `list[ConversationMessage]` | Full conversation history |

### ConversationMessage

| Field | Type | Description |
| --- | --- | --- |
| `role` | `str` | `"user"` or `"assistant"` |
| `content` | `str` | Human-readable message text |
| `timestamp` | `str` | ISO 8601 UTC timestamp |
| `meta` | `dict` | Structured data (slug, version, files, action, etc.) |

### Conversation Persistence

Prompts and agent responses are auto-persisted to `messages.json` on disk. Use `load_project` to restore the full conversation thread days later:

```python
from pathlib import Path
from agentsite import generate_website, load_project, GenerationConfig

# Day 1: generate a site
result = await generate_website(
    "A dark portfolio site",
    output_dir=Path("./websites"),
    config=GenerationConfig(model="openai/gpt-4o"),
)
project_id = result.project_id  # save this

# Day 4: restore everything and continue
state = load_project(Path("./websites"), project_id)
print(state.messages)    # full conversation history
print(state.pages)       # latest files per page
print(state.style_spec)  # design tokens ready to reuse
```

### Design Notes

- **No database** — files and metadata live on disk via `ProjectManager`
- **No server** — direct async function calls, runs in-process
- **StyleSpec auto-persisted** — after generation, the designer's output is saved to `project.json` so `regenerate_page` picks up the brand
- **Error recovery** — budget exceeded and pipeline failures still return partial files if any were written
- **Conversation auto-persisted** — user prompts and agent responses are saved to `messages.json` for session restoration via `load_project`
- **Sync/async callbacks** — `on_event` accepts either sync or async functions

---

## Configuration

| Variable | Description | Default |
| --- | --- | --- |
| `AGENTSITE_DEFAULT_MODEL` | LLM model for all agents | `openai/gpt-4o` |
| `AGENTSITE_DATA_DIR` | Project storage directory | `~/.agentsite` |
| `AGENTSITE_HOST` | Server bind address | `127.0.0.1` |
| `AGENTSITE_PORT` | Server port | `6391` |

Provider API keys (`OPENAI_API_KEY`, `CLAUDE_API_KEY`, `GOOGLE_API_KEY`, etc.) are inherited from [Prompture's configuration](https://pypi.org/project/prompture/).

---

## Project Structure

```
agentsite/
  agents/            # Agent factories, Prompture personas, orchestration
    personas.py      # All agent persona definitions (core + specialists)
    orchestrator.py  # Pipeline wiring, dynamic mode selection, parallel groups
    registry.py      # Centralized agent registry with auto-discovery
    specialists/     # Specialist agents (markup, style, script, image)
  api/               # FastAPI application
    routes/          # REST endpoints (projects, generate, models, assets, preview)
    websocket.py     # WebSocket manager for real-time progress
  engine/            # Core generation logic
    pipeline.py      # Orchestrates agents, handles file output and events
    component.py     # Embeddable API (generate_website, regenerate_page)
  storage/           # Persistence layer
    database.py      # Async SQLite via aiosqlite
    repository.py    # CRUD operations for projects and generations
  cli.py             # Click CLI entry point
  config.py          # Pydantic-settings (env vars, defaults)
  models.py          # Domain models (SitePlan, StyleSpec, PageOutput, etc.)
frontend/            # React 19 + Vite 6 + Tailwind CSS 4 SPA
tests/               # pytest test suite
```

---

## Tech Stack

| Layer | Technology |
| --- | --- |
| Agent orchestration | [Prompture](https://pypi.org/project/prompture/) |
| API server | [FastAPI](https://fastapi.tiangolo.com) + [Uvicorn](https://www.uvicorn.org) |
| Database | SQLite via [aiosqlite](https://github.com/omnilib/aiosqlite) |
| CLI | [Click](https://click.palletsprojects.com) |
| Config | [Pydantic Settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) |
| Frontend | React 19 + Vite 6 + Tailwind CSS 4 |
| Linting | [Ruff](https://github.com/astral-sh/ruff) |

---

## Development

```bash
# Install with dev + test extras
pip install -e ".[dev]"

# Run tests
pytest

# Lint
ruff check .

# Format
ruff format .

# Build frontend
cd frontend && npm install && npm run build
```

---

## Troubleshooting

### Common Issues

**Generation fails immediately?**

- Check that your `.env` has valid API keys for the provider you're using
- Run `agentsite models` to verify your provider is reachable

**Empty or broken output?**

- Try a different model — some smaller models struggle with structured output
- Check the Reviewer feedback in the Web UI for specific issues

**Frontend not loading?**

- Make sure you've built the frontend: `cd frontend && npm run build`
- For development, run `npm run dev` separately on port 5173

**WebSocket disconnects?**

- The generation is still running server-side — refresh the page to reconnect
- Check the terminal output for any backend errors

---

## Contributing

Contributions welcome! Here's how:

1. **Report bugs** — [GitHub Issues](https://github.com/jhd3197/AgentSite/issues)
2. **Improve docs** — PRs for documentation improvements
3. **Submit PRs** — Bug fixes and features
4. **Add providers** — Extend LLM provider support via Prompture

---

## License

This project is licensed under the **MIT License**.
See the [LICENSE](LICENSE) file for full details.

---

## Get Help

- **PyPI Package** — [pypi.org/project/agentsite](https://pypi.org/project/agentsite/)
- **Issues** — [GitHub Issues](https://github.com/jhd3197/AgentSite/issues)
- **Prompture** — [pypi.org/project/prompture](https://pypi.org/project/prompture/)

---

**Built by [Juan Denis](mailto:juan@vene.co)**
