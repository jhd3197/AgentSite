"""Data access layer for AgentSite projects, pages, and versions."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from ..models import AgentConfig, AgentRun, BlockFieldModel, ChatMessage, MemoryFact, Page, PageVersion, Project, ProjectComponent, StyleSpec
from .database import Database


class ProjectRepository:
    """CRUD operations for projects stored in SQLite."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(self, project: Project) -> Project:
        """Insert a new project."""
        await self._db.conn.execute(
            """INSERT INTO projects (id, name, description, model, style_spec, agent_overrides, user_id, mode, template_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                project.id,
                project.name,
                project.description,
                project.model,
                project.style_spec.model_dump_json() if project.style_spec else None,
                json.dumps(project.agent_overrides) if project.agent_overrides else None,
                project.user_id,
                project.mode,
                project.template_id,
                project.created_at,
                project.updated_at,
            ),
        )
        await self._db.conn.commit()
        return project

    async def get(self, project_id: str, *, user_id: str | None = None) -> Project | None:
        """Fetch a project by ID, optionally scoped to a user."""
        if user_id is not None:
            cursor = await self._db.conn.execute(
                "SELECT * FROM projects WHERE id = ? AND user_id = ?", (project_id, user_id)
            )
        else:
            cursor = await self._db.conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_project(row)

    async def list_all(self, *, user_id: str | None = None) -> list[Project]:
        """Fetch all projects ordered by creation date, optionally scoped to a user."""
        if user_id is not None:
            cursor = await self._db.conn.execute(
                "SELECT * FROM projects WHERE user_id = ? ORDER BY created_at DESC", (user_id,)
            )
        else:
            cursor = await self._db.conn.execute("SELECT * FROM projects ORDER BY created_at DESC")
        rows = await cursor.fetchall()
        return [self._row_to_project(row) for row in rows]

    async def update(self, project: Project, *, user_id: str | None = None) -> None:
        """Update an existing project, optionally scoped to a user."""
        project.updated_at = datetime.now(timezone.utc).isoformat()
        if user_id is not None:
            await self._db.conn.execute(
                """UPDATE projects SET name=?, description=?, model=?, style_spec=?,
                   agent_overrides=?, mode=?, template_id=?, updated_at=? WHERE id=? AND user_id=?""",
                (
                    project.name,
                    project.description,
                    project.model,
                    project.style_spec.model_dump_json() if project.style_spec else None,
                    json.dumps(project.agent_overrides) if project.agent_overrides else None,
                    project.mode,
                    project.template_id,
                    project.updated_at,
                    project.id,
                    user_id,
                ),
            )
        else:
            await self._db.conn.execute(
                """UPDATE projects SET name=?, description=?, model=?, style_spec=?,
                   agent_overrides=?, mode=?, template_id=?, updated_at=? WHERE id=?""",
                (
                    project.name,
                    project.description,
                    project.model,
                    project.style_spec.model_dump_json() if project.style_spec else None,
                    json.dumps(project.agent_overrides) if project.agent_overrides else None,
                    project.mode,
                    project.template_id,
                    project.updated_at,
                    project.id,
                ),
            )
        await self._db.conn.commit()

    async def delete(self, project_id: str, *, user_id: str | None = None) -> None:
        """Delete a project and all its pages/versions (via CASCADE), optionally scoped to a user."""
        if user_id is not None:
            await self._db.conn.execute(
                "DELETE FROM projects WHERE id = ? AND user_id = ?", (project_id, user_id)
            )
        else:
            await self._db.conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        await self._db.conn.commit()

    @staticmethod
    def _row_to_project(row: Any) -> Project:
        """Convert a database row to a Project model."""
        style_spec = None
        if row["style_spec"]:
            style_spec = StyleSpec.model_validate_json(row["style_spec"])

        agent_overrides = None
        try:
            raw = row["agent_overrides"]
            if raw:
                agent_overrides = json.loads(raw)
        except (KeyError, IndexError):
            pass  # column may not exist in old DBs before migration runs

        user_id = None
        try:
            user_id = row["user_id"]
        except (KeyError, IndexError):
            pass  # column may not exist in old DBs before migration runs

        mode = "mockup"
        template_id = None
        try:
            mode = row["mode"] or "mockup"
            template_id = row["template_id"]
        except (KeyError, IndexError):
            pass  # columns may not exist in old DBs before migration runs

        return Project(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            model=row["model"],
            style_spec=style_spec,
            agent_overrides=agent_overrides,
            user_id=user_id,
            mode=mode,
            template_id=template_id,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


class PageRepository:
    """CRUD operations for pages within projects."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(self, page: Page) -> Page:
        """Insert a new page."""
        await self._db.conn.execute(
            """INSERT INTO pages (id, project_id, slug, title, prompt, layout_overrides, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                page.id,
                page.project_id,
                page.slug,
                page.title,
                page.prompt,
                json.dumps(page.layout_overrides) if page.layout_overrides else None,
                page.created_at,
                page.updated_at,
            ),
        )
        await self._db.conn.commit()
        return page

    async def get(self, page_id: str) -> Page | None:
        """Fetch a page by ID."""
        cursor = await self._db.conn.execute("SELECT * FROM pages WHERE id = ?", (page_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_page(row)

    async def get_by_slug(self, project_id: str, slug: str) -> Page | None:
        """Fetch a page by project ID and slug."""
        cursor = await self._db.conn.execute(
            "SELECT * FROM pages WHERE project_id = ? AND slug = ?", (project_id, slug)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_page(row)

    async def list_by_project(self, project_id: str) -> list[Page]:
        """List all pages for a project."""
        cursor = await self._db.conn.execute(
            "SELECT * FROM pages WHERE project_id = ? ORDER BY created_at ASC", (project_id,)
        )
        rows = await cursor.fetchall()
        return [self._row_to_page(row) for row in rows]

    async def update(self, page: Page) -> None:
        """Update a page."""
        page.updated_at = datetime.now(timezone.utc).isoformat()
        await self._db.conn.execute(
            """UPDATE pages SET slug=?, title=?, prompt=?, layout_overrides=?, updated_at=? WHERE id=?""",
            (
                page.slug,
                page.title,
                page.prompt,
                json.dumps(page.layout_overrides) if page.layout_overrides else None,
                page.updated_at,
                page.id,
            ),
        )
        await self._db.conn.commit()

    async def delete(self, page_id: str) -> None:
        """Delete a page and all its versions (via CASCADE)."""
        await self._db.conn.execute("DELETE FROM pages WHERE id = ?", (page_id,))
        await self._db.conn.commit()

    async def delete_by_slug(self, project_id: str, slug: str) -> None:
        """Delete a page by project ID and slug."""
        await self._db.conn.execute(
            "DELETE FROM pages WHERE project_id = ? AND slug = ?", (project_id, slug)
        )
        await self._db.conn.commit()

    @staticmethod
    def _row_to_page(row: Any) -> Page:
        layout_overrides = None
        try:
            raw = row["layout_overrides"]
            if raw:
                layout_overrides = json.loads(raw)
        except (KeyError, IndexError):
            pass  # column may not exist in old DBs before migration runs

        return Page(
            id=row["id"],
            project_id=row["project_id"],
            slug=row["slug"],
            title=row["title"],
            prompt=row["prompt"],
            layout_overrides=layout_overrides,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


class VersionRepository:
    """CRUD operations for page versions."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(self, version: PageVersion) -> PageVersion:
        """Insert a new version."""
        await self._db.conn.execute(
            """INSERT INTO versions (id, page_id, version_number, status, prompt, usage, files, error, created_at, completed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                version.id,
                version.page_id,
                version.version_number,
                version.status,
                version.prompt,
                json.dumps(version.usage),
                json.dumps(version.files),
                version.error,
                version.created_at,
                version.completed_at,
            ),
        )
        await self._db.conn.commit()
        return version

    async def get(self, version_id: str) -> PageVersion | None:
        """Fetch a version by ID."""
        cursor = await self._db.conn.execute("SELECT * FROM versions WHERE id = ?", (version_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_version(row)

    async def get_by_number(self, page_id: str, version_number: int) -> PageVersion | None:
        """Fetch a specific version by page ID and version number."""
        cursor = await self._db.conn.execute(
            "SELECT * FROM versions WHERE page_id = ? AND version_number = ?",
            (page_id, version_number),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_version(row)

    async def list_by_page(self, page_id: str) -> list[PageVersion]:
        """List all versions for a page, ordered by version number."""
        cursor = await self._db.conn.execute(
            "SELECT * FROM versions WHERE page_id = ? ORDER BY version_number ASC", (page_id,)
        )
        rows = await cursor.fetchall()
        return [self._row_to_version(row) for row in rows]

    async def get_latest(self, page_id: str) -> PageVersion | None:
        """Get the latest version for a page."""
        cursor = await self._db.conn.execute(
            "SELECT * FROM versions WHERE page_id = ? ORDER BY version_number DESC LIMIT 1",
            (page_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_version(row)

    async def next_version_number(self, page_id: str) -> int:
        """Get the next version number for a page."""
        cursor = await self._db.conn.execute(
            "SELECT MAX(version_number) FROM versions WHERE page_id = ?", (page_id,)
        )
        row = await cursor.fetchone()
        current_max = row[0] if row[0] is not None else 0
        return current_max + 1

    async def update(self, version: PageVersion) -> None:
        """Update a version record."""
        await self._db.conn.execute(
            """UPDATE versions SET status=?, usage=?, files=?, error=?, completed_at=? WHERE id=?""",
            (
                version.status,
                json.dumps(version.usage),
                json.dumps(version.files),
                version.error,
                version.completed_at,
                version.id,
            ),
        )
        await self._db.conn.commit()

    @staticmethod
    def _row_to_version(row: Any) -> PageVersion:
        return PageVersion(
            id=row["id"],
            page_id=row["page_id"],
            version_number=row["version_number"],
            status=row["status"],
            prompt=row["prompt"],
            usage=json.loads(row["usage"]) if row["usage"] else {},
            files=json.loads(row["files"]) if row["files"] else {},
            error=row["error"],
            created_at=row["created_at"],
            completed_at=row["completed_at"],
        )


class MessageRepository:
    """CRUD operations for chat messages within page builder sessions."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(self, msg: ChatMessage) -> ChatMessage:
        """Insert a new message."""
        await self._db.conn.execute(
            """INSERT INTO messages (id, page_id, role, content, image, meta, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                msg.id,
                msg.page_id,
                msg.role,
                msg.content,
                msg.image,
                json.dumps(msg.meta),
                msg.created_at,
            ),
        )
        await self._db.conn.commit()
        return msg

    async def list_by_page(self, page_id: str) -> list[ChatMessage]:
        """List all messages for a page, ordered chronologically."""
        cursor = await self._db.conn.execute(
            "SELECT * FROM messages WHERE page_id = ? ORDER BY created_at ASC",
            (page_id,),
        )
        rows = await cursor.fetchall()
        return [self._row_to_message(row) for row in rows]

    async def delete_by_page(self, page_id: str) -> None:
        """Delete all messages for a page."""
        await self._db.conn.execute(
            "DELETE FROM messages WHERE page_id = ?", (page_id,)
        )
        await self._db.conn.commit()

    @staticmethod
    def _row_to_message(row) -> ChatMessage:
        return ChatMessage(
            id=row["id"],
            page_id=row["page_id"],
            role=row["role"],
            content=row["content"],
            image=row["image"],
            meta=json.loads(row["meta"]) if row["meta"] else {},
            created_at=row["created_at"],
        )


class AgentConfigRepository:
    """CRUD operations for agent configurations."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def list_all(self) -> list[AgentConfig]:
        """Fetch all agent configs."""
        cursor = await self._db.conn.execute(
            "SELECT * FROM agent_configs ORDER BY agent_name"
        )
        rows = await cursor.fetchall()
        return [self._row_to_config(row) for row in rows]

    async def get(self, agent_name: str) -> AgentConfig | None:
        """Fetch a single agent config by name."""
        cursor = await self._db.conn.execute(
            "SELECT * FROM agent_configs WHERE agent_name = ?", (agent_name,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_config(row)

    async def update(self, config: AgentConfig) -> None:
        """Update an agent config."""
        config.updated_at = datetime.now(timezone.utc).isoformat()
        await self._db.conn.execute(
            """UPDATE agent_configs SET enabled=?, model=?, temperature=?,
               system_prompt_override=?, updated_at=? WHERE agent_name=?""",
            (
                1 if config.enabled else 0,
                config.model,
                config.temperature,
                config.system_prompt_override,
                config.updated_at,
                config.agent_name,
            ),
        )
        await self._db.conn.commit()

    @staticmethod
    def _row_to_config(row: Any) -> AgentConfig:
        # category column may not exist in older DBs before migration runs
        row_keys = row.keys() if hasattr(row, "keys") else []
        return AgentConfig(
            agent_name=row["agent_name"],
            enabled=bool(row["enabled"]),
            model=row["model"],
            temperature=row["temperature"],
            system_prompt_override=row["system_prompt_override"],
            category=row["category"] if "category" in row_keys else "",
            updated_at=row["updated_at"],
        )


class AgentRunRepository:
    """CRUD operations for agent run records."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(self, run: AgentRun, *, user_id: str | None = None) -> AgentRun:
        """Insert a new agent run, optionally tagged with a user_id."""
        await self._db.conn.execute(
            """INSERT INTO agent_runs
               (id, project_id, page_slug, version, agent_name, status,
                started_at, completed_at, input_tokens, output_tokens, cost,
                session_id, output_summary, user_id, strategy, model)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run.id,
                run.project_id,
                run.page_slug,
                run.version,
                run.agent_name,
                run.status,
                run.started_at,
                run.completed_at,
                run.input_tokens,
                run.output_tokens,
                run.cost,
                run.session_id,
                json.dumps(run.output_summary),
                user_id,
                run.strategy,
                run.model,
            ),
        )
        await self._db.conn.commit()
        return run

    async def update(self, run: AgentRun) -> None:
        """Update an agent run record."""
        await self._db.conn.execute(
            """UPDATE agent_runs SET status=?, completed_at=?,
               input_tokens=?, output_tokens=?, cost=?, output_summary=?,
               strategy=?, model=?
               WHERE id=?""",
            (
                run.status,
                run.completed_at,
                run.input_tokens,
                run.output_tokens,
                run.cost,
                json.dumps(run.output_summary),
                run.strategy,
                run.model,
                run.id,
            ),
        )
        await self._db.conn.commit()

    async def list_recent(
        self, limit: int = 50, since: str | None = None, *, user_id: str | None = None
    ) -> list[AgentRun]:
        """List recent agent runs ordered by start time, optionally scoped to a user."""
        clauses = []
        params: list = []
        if since:
            clauses.append("started_at >= ?")
            params.append(since)
        if user_id is not None:
            clauses.append("user_id = ?")
            params.append(user_id)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        cursor = await self._db.conn.execute(
            f"SELECT * FROM agent_runs {where} ORDER BY started_at DESC LIMIT ?",
            (*params, limit),
        )
        rows = await cursor.fetchall()
        return [self._row_to_run(row) for row in rows]

    async def get_stats(self, since: str | None = None, *, user_id: str | None = None) -> dict:
        """Get aggregated agent stats, optionally filtered by start date and user."""
        where = "WHERE status = 'completed'"
        params: list = []
        if since:
            where += " AND started_at >= ?"
            params.append(since)
        if user_id is not None:
            where += " AND user_id = ?"
            params.append(user_id)

        cursor = await self._db.conn.execute(
            f"""
            SELECT
                agent_name,
                COUNT(*) as total_runs,
                SUM(input_tokens) as total_input_tokens,
                SUM(output_tokens) as total_output_tokens,
                SUM(cost) as total_cost,
                AVG(
                    CASE WHEN completed_at IS NOT NULL AND started_at IS NOT NULL
                    THEN (julianday(completed_at) - julianday(started_at)) * 86400
                    ELSE NULL END
                ) as avg_duration_seconds
            FROM agent_runs
            {where}
            GROUP BY agent_name
        """,
            params,
        )
        rows = await cursor.fetchall()
        per_agent = {}
        total_runs = 0
        total_cost = 0.0
        total_duration = 0.0
        duration_count = 0
        for row in rows:
            name = row["agent_name"]
            runs = row["total_runs"]
            cost = row["total_cost"] or 0.0
            avg_dur = row["avg_duration_seconds"]
            per_agent[name] = {
                "total_runs": runs,
                "total_input_tokens": row["total_input_tokens"] or 0,
                "total_output_tokens": row["total_output_tokens"] or 0,
                "total_cost": round(cost, 4),
                "avg_duration_seconds": round(avg_dur, 1) if avg_dur else None,
            }
            total_runs += runs
            total_cost += cost
            if avg_dur is not None:
                total_duration += avg_dur * runs
                duration_count += runs

        return {
            "total_runs": total_runs,
            "total_cost": round(total_cost, 4),
            "avg_duration_seconds": round(total_duration / duration_count, 1) if duration_count else None,
            "per_agent": per_agent,
        }

    async def get_daily_stats(self, days: int = 30, *, user_id: str | None = None) -> list[dict]:
        """Get daily token and cost aggregates for the last N days, optionally scoped to a user."""
        where = "WHERE started_at >= DATE('now', ?)"
        params: list = [f"-{days} days"]
        if user_id is not None:
            where += " AND user_id = ?"
            params.append(user_id)
        cursor = await self._db.conn.execute(
            f"""
            SELECT
                DATE(started_at) as date,
                SUM(input_tokens) as input_tokens,
                SUM(output_tokens) as output_tokens,
                SUM(cost) as cost
            FROM agent_runs
            {where}
            GROUP BY DATE(started_at)
            ORDER BY date ASC
        """,
            params,
        )
        rows = await cursor.fetchall()
        return [
            {
                "date": row["date"],
                "input_tokens": row["input_tokens"] or 0,
                "output_tokens": row["output_tokens"] or 0,
                "cost": round(row["cost"] or 0.0, 4),
            }
            for row in rows
        ]

    async def backfill_costs(self) -> int:
        """Recalculate costs for runs with tokens but zero cost."""
        cursor = await self._db.conn.execute(
            """SELECT ar.id, ar.input_tokens, ar.output_tokens, p.model
               FROM agent_runs ar
               JOIN projects p ON ar.project_id = p.id
               WHERE ar.cost = 0.0 AND (ar.input_tokens > 0 OR ar.output_tokens > 0)"""
        )
        rows = await cursor.fetchall()
        if not rows:
            return 0

        try:
            from prompture.infra import get_model_rates

            updated = 0
            for row in rows:
                model_str = row["model"] or ""
                try:
                    provider = model_str.split("/")[0] if "/" in model_str else ""
                    model_id = model_str.split("/", 1)[1] if "/" in model_str else model_str
                    rates = get_model_rates(provider, model_id)
                    if rates and "input" in rates and "output" in rates:
                        cost = (
                            (row["input_tokens"] / 1_000_000) * rates["input"]
                            + (row["output_tokens"] / 1_000_000) * rates["output"]
                        )
                    else:
                        cost = 0.0
                except Exception:
                    cost = 0.0
                if cost > 0:
                    await self._db.conn.execute(
                        "UPDATE agent_runs SET cost = ? WHERE id = ?",
                        (round(cost, 6), row["id"]),
                    )
                    updated += 1
            await self._db.conn.commit()
            return updated
        except ImportError:
            return 0

    @staticmethod
    def _row_to_run(row: Any) -> AgentRun:
        return AgentRun(
            id=row["id"],
            project_id=row["project_id"],
            page_slug=row["page_slug"],
            version=row["version"],
            agent_name=row["agent_name"],
            status=row["status"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            input_tokens=row["input_tokens"],
            output_tokens=row["output_tokens"],
            cost=row["cost"],
            session_id=row["session_id"] if "session_id" in row else "",
            output_summary=json.loads(row["output_summary"]) if row["output_summary"] else {},
            strategy=(row["strategy"] if "strategy" in row.keys() else "") or "",
            model=(row["model"] if "model" in row.keys() else "") or "",
        )


class MemoryRepository:
    """Phase 10 — CRUD for per-project memory facts."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(self, fact: MemoryFact) -> MemoryFact:
        await self._db.conn.execute(
            """INSERT INTO project_memories
               (id, project_id, kind, body, confidence, source_run_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (fact.id, fact.project_id, fact.kind, fact.body, fact.confidence,
             fact.source_run_id, fact.created_at),
        )
        await self._db.conn.commit()
        return fact

    async def list_by_project(self, project_id: str, *, limit: int = 20) -> list[MemoryFact]:
        cursor = await self._db.conn.execute(
            "SELECT * FROM project_memories WHERE project_id=? "
            "ORDER BY confidence DESC, created_at DESC LIMIT ?",
            (project_id, limit),
        )
        rows = await cursor.fetchall()
        return [self._row_to_fact(r) for r in rows]

    async def delete(self, fact_id: str) -> bool:
        cursor = await self._db.conn.execute(
            "DELETE FROM project_memories WHERE id=?", (fact_id,)
        )
        await self._db.conn.commit()
        return cursor.rowcount > 0

    async def delete_by_project(self, project_id: str) -> int:
        cursor = await self._db.conn.execute(
            "DELETE FROM project_memories WHERE project_id=?", (project_id,)
        )
        await self._db.conn.commit()
        return cursor.rowcount

    @staticmethod
    def _row_to_fact(row) -> MemoryFact:
        return MemoryFact(
            id=row["id"],
            project_id=row["project_id"],
            kind=row["kind"],
            body=row["body"],
            confidence=row["confidence"],
            source_run_id=row["source_run_id"] or "",
            created_at=row["created_at"],
        )


class DesignSystemRepository:
    """Phase 13 — persistent storage for user-saved design systems."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(self, *, id: str, name: str, description: str, tokens_css: str,
                     source: str = "user") -> dict:
        now = datetime.now(timezone.utc).isoformat()
        await self._db.conn.execute(
            """INSERT OR REPLACE INTO design_systems
               (id, name, description, tokens_css, source, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (id, name, description, tokens_css, source, now),
        )
        await self._db.conn.commit()
        return {"id": id, "name": name, "description": description,
                "tokens_css": tokens_css, "source": source, "created_at": now}

    async def get(self, id: str) -> dict | None:
        cursor = await self._db.conn.execute(
            "SELECT * FROM design_systems WHERE id=?", (id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return self._row(row)

    async def list_all(self) -> list[dict]:
        cursor = await self._db.conn.execute(
            "SELECT * FROM design_systems ORDER BY created_at DESC"
        )
        rows = await cursor.fetchall()
        return [self._row(r) for r in rows]

    async def delete(self, id: str) -> bool:
        cursor = await self._db.conn.execute(
            "DELETE FROM design_systems WHERE id=?", (id,)
        )
        await self._db.conn.commit()
        return cursor.rowcount > 0

    @staticmethod
    def _row(row) -> dict:
        return {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"],
            "tokens_css": row["tokens_css"],
            "source": row["source"],
            "created_at": row["created_at"],
        }


class ProjectComponentRepository:
    """Phase 4 — project-scoped reusable block definitions.

    A ProjectComponent is shape-compatible with htmlstudio's
    BlockDefinition (same fields), so the same palette / config form /
    render pipeline works for builtins and project components alike.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(self, component: ProjectComponent) -> ProjectComponent:
        await self._db.conn.execute(
            """INSERT INTO project_components
               (id, project_id, slug, name, category, description, thumbnail,
                template, fields_json,
                source_instance_id, source_page_slug, source_version,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                component.id,
                component.project_id,
                component.slug,
                component.name,
                component.category,
                component.description,
                component.thumbnail,
                component.template,
                json.dumps([f.model_dump() for f in component.fields]),
                component.source_instance_id,
                component.source_page_slug,
                component.source_version,
                component.created_at,
                component.updated_at,
            ),
        )
        await self._db.conn.commit()
        return component

    async def list_by_project(self, project_id: str) -> list[ProjectComponent]:
        cursor = await self._db.conn.execute(
            "SELECT * FROM project_components WHERE project_id=? ORDER BY created_at DESC",
            (project_id,),
        )
        rows = await cursor.fetchall()
        return [self._row_to_component(r) for r in rows]

    async def get(self, component_id: str) -> ProjectComponent | None:
        cursor = await self._db.conn.execute(
            "SELECT * FROM project_components WHERE id=?", (component_id,)
        )
        row = await cursor.fetchone()
        return self._row_to_component(row) if row else None

    async def get_by_slug(self, project_id: str, slug: str) -> ProjectComponent | None:
        cursor = await self._db.conn.execute(
            "SELECT * FROM project_components WHERE project_id=? AND slug=?",
            (project_id, slug),
        )
        row = await cursor.fetchone()
        return self._row_to_component(row) if row else None

    async def update(self, component: ProjectComponent) -> None:
        component.updated_at = datetime.now(timezone.utc).isoformat()
        await self._db.conn.execute(
            """UPDATE project_components
               SET slug=?, name=?, category=?, description=?, thumbnail=?,
                   template=?, fields_json=?, updated_at=?
               WHERE id=?""",
            (
                component.slug,
                component.name,
                component.category,
                component.description,
                component.thumbnail,
                component.template,
                json.dumps([f.model_dump() for f in component.fields]),
                component.updated_at,
                component.id,
            ),
        )
        await self._db.conn.commit()

    async def delete(self, component_id: str) -> bool:
        cursor = await self._db.conn.execute(
            "DELETE FROM project_components WHERE id=?", (component_id,)
        )
        await self._db.conn.commit()
        return cursor.rowcount > 0

    @staticmethod
    def _row_to_component(row: Any) -> ProjectComponent:
        fields_data = json.loads(row["fields_json"] or "[]")
        return ProjectComponent(
            id=row["id"],
            project_id=row["project_id"],
            slug=row["slug"],
            name=row["name"],
            category=row["category"],
            description=row["description"],
            thumbnail=row["thumbnail"],
            template=row["template"],
            fields=[BlockFieldModel(**f) for f in fields_data],
            source_instance_id=row["source_instance_id"],
            source_page_slug=row["source_page_slug"],
            source_version=row["source_version"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
