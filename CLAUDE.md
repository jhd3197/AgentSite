# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AgentSite is an AI-powered website builder using multi-agent orchestration. Four specialized AI agents (PM, Designer, Developer, Reviewer) collaborate in a pipeline to generate production-ready websites from text prompts.

## Commands

```bash
# Install (with dev/test extras)
pip install -e ".[dev]"

# Run web UI server (http://127.0.0.1:6391)
agentsite serve
agentsite serve --reload  # with hot-reload

# Generate via CLI
agentsite generate "A portfolio site" -m openai/gpt-4o -o ./output

# List available LLM models
agentsite models

# Frontend development
cd frontend && npm install    # install deps
cd frontend && npm run dev    # dev server on port 5173 (proxies to backend)
cd frontend && npm run build  # production build to frontend/dist/

# Tests
pytest              # all tests
pytest tests/test_api.py  # single test file
pytest -k "test_name"     # single test by name

# Lint and format
ruff check .
ruff format .
```

## Architecture

**Backend** (`agentsite/`): Python 3.10+, FastAPI, Uvicorn, SQLite via aiosqlite. CLI via Click.

**Frontend** (`frontend/`): React 19 + Vite 6 + Tailwind CSS 4 SPA. Built to `frontend/dist/` and served by FastAPI with SPA catch-all fallback.

- **Routing**: React Router 7 with 5 routes: `/` (Dashboard), `/project/:id` (Project), `/project/:id/page/:slug` (Page Builder), `/agents`, `/analytics`
- **State**: React Context (`AppContext`) for global state (models, providers, settings). Custom hooks (`useProjects`, `useProject`, `useVersions`, `useGeneration`, `useWebSocket`) for data fetching.
- **API layer**: Modular fetch wrappers in `frontend/src/api/` (client.js, projects.js, providers.js, models.js, generate.js, assets.js)
- **Icons**: `@phosphor-icons/react` — use `weight="fill"` prop for filled variants
- **Fonts**: Inter (body), JetBrains Mono (code), Space Grotesk (display) via Google Fonts CDN

**Dev workflow**: Run backend (`agentsite serve --reload` on port 6391) and frontend (`npm run dev` on port 5173) simultaneously. Vite proxies `/api/*`, `/ws/*`, `/preview/*` to the backend.

**Production**: `npm run build` in `frontend/`, then `agentsite serve` serves everything from `frontend/dist/`.

**Agent orchestration** uses the **Prompture** library (`prompture>=0.0.40`). The pipeline is defined in `agentsite/engine/pipeline.py`:

```
Sequential:
  1. PM Agent → SitePlan (structure, pages, sections)
  2. Designer Agent → StyleSpec (colors, typography, spacing)
  3. Loop (max 2 iterations):
     a. Developer Agent → PageOutput (HTML/CSS/JS files)
     b. Reviewer Agent → ReviewFeedback (score ≥ 7 = approved)
```

Agent personas/system prompts live in `agentsite/agents/personas.py`. Each agent has a factory module (`pm.py`, `designer.py`, `developer.py`, `reviewer.py`). The orchestrator wires them together in `agentsite/agents/orchestrator.py`.

**Project mode** (`project.mode == "project"`): instead of page-version one-pagers, the project gets a real workspace at `~/.agentsite/projects/{id}/workspace/` scaffolded from a template in `agentsite/templates/` (`static-multipage`, `vite-react-tailwind`). `agentsite/engine/project_pipeline.py` runs PM → Designer (tokens rendered to a real file via `engine/tokens.py`) → ONE persistent developer session (`agents/workspace_tools.py`: read/write/edit_file/search/run_command) → Playwright verification → Reviewer, with review feedback, build errors, and verification failures fed back into the same session as targeted edits. Versioning = git checkpoints (`engine/workspace.py`); preview = `/preview/{id}/app/` (serves `dist/` for node templates after `engine/workspace_runner.py` builds); export zips the workspace. Mockup mode (the original `pipeline.py` flow) remains the default and the fallback for non-tool-capable models.

**Verification** (`engine/verifier.py`, optional: `pip install agentsite[verify]` + `playwright install chromium`, auto-skips when missing): after each successful build the site is served on an ephemeral port and walked with Playwright. Uncaught JS errors, failed same-origin requests, blank pages, and missing planned pages are HARD gates the LLM reviewer cannot override — failures go back to the dev session as feedback. Desktop+mobile screenshots land in `workspace/.agentsite/verify/v{n}/`, are served at `/preview/{id}/verify/{path}`, shown in the chat timeline, and attached to the Reviewer when its model supports vision. Roadmap: `.planning/project-workspace-roadmap.md` (phase E pending: triage routing + specialist consolidation).

**Real-time updates**: Generation progress flows via WebSocket from `agentsite/api/websocket.py` to `useWebSocket` / `useGeneration` hooks. The Page Builder updates ChatSidebar, PreviewFrame, and ProgressPipeline components in response.

**Storage**: SQLite database (projects + generations tables) managed in `agentsite/storage/`. Generated site files are written to `~/.agentsite/projects/{id}/site/` via agent tools defined in `agentsite/agents/tools.py`.

**API routes** are in `agentsite/api/routes/` — generation, projects CRUD, model listing, file/asset management, preview, and provider configuration.

## Frontend File Structure

```
frontend/
  src/
    main.jsx                  # Router setup
    App.jsx                   # Layout shell (sidebar + outlet)
    index.css                 # Tailwind directives + custom utilities
    api/                      # Fetch wrappers per resource
    hooks/                    # React hooks for data + WebSocket
    context/AppContext.jsx    # Global state provider
    pages/                    # Route-level page components
    components/
      layout/                 # AppSidebar, ProjectSidebar, TopHeader, PageBuilderHeader
      dashboard/              # ProjectCard, CreateProjectCard, ProjectFilterBar
      project/                # PageCard, CreatePageCard, BrandIdentityPanel
      builder/                # ChatSidebar, ChatMessage, ChatInput, PreviewFrame, DeviceSwitcher, VersionSelector, ZoomControls, ProgressPipeline
      agents/                 # AgentCard, AgentMetricsBar, AgentActivityPanel
      analytics/              # MetricCard, TokenChart, CostByAgentChart, ActivityTable
      shared/                 # Badge, Button, Modal, Spinner, SettingsModal
```

## Configuration

Copy `.env.copy` to `.env` and set provider API keys (`OPENAI_API_KEY`, `CLAUDE_API_KEY`, `GOOGLE_API_KEY`, etc.). Key settings prefixed with `AGENTSITE_` are defined in `agentsite/config.py` using Pydantic Settings.

Default model: `openai/gpt-4o`. Default port: `6391`. Data directory: `~/.agentsite`.

## Domain Models

Core data models in `agentsite/models.py`: `SitePlan`, `StyleSpec`, `PageOutput`, `ReviewFeedback`, `Project`, `WSEvent`. These are the structured outputs passed between agents and stored in the database.
