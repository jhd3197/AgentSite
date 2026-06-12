"""SQLite database management via aiosqlite."""

from __future__ import annotations

import logging
from pathlib import Path

import aiosqlite

from ..config import settings

logger = logging.getLogger("agentsite.database")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT 'Untitled Project',
    description TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    style_spec TEXT,
    agent_overrides TEXT,
    user_id TEXT,
    mode TEXT NOT NULL DEFAULT 'mockup',
    template_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pages (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    slug TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    prompt TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, slug)
);

CREATE TABLE IF NOT EXISTS versions (
    id TEXT PRIMARY KEY,
    page_id TEXT NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'generating',
    prompt TEXT NOT NULL DEFAULT '',
    usage TEXT DEFAULT '{}',
    files TEXT DEFAULT '{}',
    error TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    UNIQUE(page_id, version_number)
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    page_id TEXT NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'user',
    content TEXT NOT NULL DEFAULT '',
    image TEXT,
    meta TEXT DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_configs (
    agent_name TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 1,
    model TEXT NOT NULL DEFAULT '',
    temperature REAL NOT NULL DEFAULT 0.5,
    system_prompt_override TEXT,
    category TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS design_systems (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    tokens_css TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'user',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS project_memories (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 0.5,
    source_run_id TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_runs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    page_slug TEXT NOT NULL DEFAULT '',
    version INTEGER NOT NULL DEFAULT 1,
    agent_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    started_at TEXT NOT NULL,
    completed_at TEXT,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cost REAL NOT NULL DEFAULT 0.0,
    session_id TEXT DEFAULT '',
    output_summary TEXT DEFAULT '{}',
    user_id TEXT,
    strategy TEXT DEFAULT '',
    model TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS project_components (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    slug TEXT NOT NULL,
    name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'custom',
    description TEXT NOT NULL DEFAULT '',
    thumbnail TEXT NOT NULL DEFAULT '🧱',
    template TEXT NOT NULL,
    fields_json TEXT NOT NULL DEFAULT '[]',
    source_instance_id TEXT,
    source_page_slug TEXT,
    source_version INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (project_id, slug)
);
CREATE INDEX IF NOT EXISTS idx_project_components_project ON project_components(project_id);
"""

# Migration: drop old tables if they exist with old schema
MIGRATION_SQL = """
-- Drop legacy tables that no longer match the schema
DROP TABLE IF EXISTS generations;
"""


class Database:
    """Async SQLite database wrapper."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._path = db_path or settings.db_path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        """Open the database connection and create tables."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(str(self._path))
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA foreign_keys = ON")
        await self._migrate()
        await self._conn.executescript(SCHEMA_SQL)
        await self._conn.commit()
        await self._seed_agent_configs()
        logger.info("Database connected: %s", self._path)

    async def _migrate(self) -> None:
        """Handle migrations from old schema."""
        # Check if old projects table has columns we need to drop
        cursor = await self._conn.execute("PRAGMA table_info(projects)")
        columns = {row[1] for row in await cursor.fetchall()}

        if "prompt" in columns or "status" in columns or "site_plan" in columns:
            # Old schema detected — rename and recreate
            logger.info("Migrating database from old schema...")
            await self._conn.executescript("""
                DROP TABLE IF EXISTS generations;
                ALTER TABLE projects RENAME TO _old_projects;
            """)
            await self._conn.executescript(SCHEMA_SQL)
            # Migrate old project data
            try:
                old_cursor = await self._conn.execute("SELECT * FROM _old_projects")
                old_rows = await old_cursor.fetchall()
                for row in old_rows:
                    await self._conn.execute(
                        """INSERT OR IGNORE INTO projects (id, name, description, model, style_spec, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (
                            row["id"],
                            row["name"],
                            row["prompt"] if "prompt" in columns else "",
                            row["model"],
                            row["style_spec"] if "style_spec" in columns else None,
                            row["created_at"],
                            row["updated_at"],
                        ),
                    )
                await self._conn.execute("DROP TABLE _old_projects")
                await self._conn.commit()
                logger.info("Migration complete — %d projects migrated", len(old_rows))
            except Exception:
                logger.warning("Migration of old data failed, starting fresh")
                await self._conn.execute("DROP TABLE IF EXISTS _old_projects")
                await self._conn.commit()
        else:
            # No old schema or already migrated — just clean up legacy tables
            await self._conn.executescript(MIGRATION_SQL)
            await self._conn.commit()

        # Add session_id column to agent_runs table if missing
        cursor = await self._conn.execute("PRAGMA table_info(agent_runs)")
        ar_columns = {row[1] for row in await cursor.fetchall()}
        if ar_columns and "session_id" not in ar_columns:
            logger.info("Adding 'session_id' column to agent_runs table...")
            await self._conn.execute(
                "ALTER TABLE agent_runs ADD COLUMN session_id TEXT DEFAULT ''"
            )
            await self._conn.commit()

        # Add files column to versions table if missing (incremental migration)
        cursor = await self._conn.execute("PRAGMA table_info(versions)")
        version_columns = {row[1] for row in await cursor.fetchall()}
        if version_columns and "files" not in version_columns:
            logger.info("Adding 'files' column to versions table...")
            await self._conn.execute("ALTER TABLE versions ADD COLUMN files TEXT DEFAULT '{}'")
            await self._conn.commit()

        # Add agent_overrides column to projects table if missing
        if columns and "agent_overrides" not in columns:
            logger.info("Adding 'agent_overrides' column to projects table...")
            await self._conn.execute("ALTER TABLE projects ADD COLUMN agent_overrides TEXT")
            await self._conn.commit()

        # Add user_id column to projects table if missing
        if columns and "user_id" not in columns:
            logger.info("Adding 'user_id' column to projects table...")
            await self._conn.execute("ALTER TABLE projects ADD COLUMN user_id TEXT")
            await self._conn.commit()

        # Project-mode workspaces — add mode + template_id to projects
        if columns and "mode" not in columns:
            logger.info("Adding 'mode' column to projects table...")
            await self._conn.execute(
                "ALTER TABLE projects ADD COLUMN mode TEXT NOT NULL DEFAULT 'mockup'"
            )
            await self._conn.commit()
        if columns and "template_id" not in columns:
            logger.info("Adding 'template_id' column to projects table...")
            await self._conn.execute("ALTER TABLE projects ADD COLUMN template_id TEXT")
            await self._conn.commit()

        # Phase 13 — add strategy + model columns to agent_runs if missing
        if ar_columns and "strategy" not in ar_columns:
            logger.info("Adding 'strategy' column to agent_runs table...")
            await self._conn.execute("ALTER TABLE agent_runs ADD COLUMN strategy TEXT DEFAULT ''")
            await self._conn.commit()
        if ar_columns and "model" not in ar_columns:
            logger.info("Adding 'model' column to agent_runs table...")
            await self._conn.execute("ALTER TABLE agent_runs ADD COLUMN model TEXT DEFAULT ''")
            await self._conn.commit()

        # Add user_id column to agent_runs table if missing
        if ar_columns and "user_id" not in ar_columns:
            logger.info("Adding 'user_id' column to agent_runs table...")
            await self._conn.execute("ALTER TABLE agent_runs ADD COLUMN user_id TEXT")
            await self._conn.commit()

        # Add category column to agent_configs table if missing
        cursor = await self._conn.execute("PRAGMA table_info(agent_configs)")
        ac_columns = {row[1] for row in await cursor.fetchall()}
        if ac_columns and "category" not in ac_columns:
            logger.info("Adding 'category' column to agent_configs table...")
            await self._conn.execute(
                "ALTER TABLE agent_configs ADD COLUMN category TEXT NOT NULL DEFAULT ''"
            )
            await self._conn.commit()
            # Backfill categories from registry
            try:
                from agentsite.agents.registry import AgentRegistry

                for desc in AgentRegistry.list_all():
                    await self._conn.execute(
                        "UPDATE agent_configs SET category = ? WHERE agent_name = ?",
                        (desc.category.value, desc.key),
                    )
                await self._conn.commit()
            except ImportError:
                logger.debug("Could not import AgentRegistry for category backfill")

    async def _seed_agent_configs(self) -> None:
        """Insert default agent configs if they don't exist.

        Seeds both the core 4 agents and the specialist agents.
        Specialist agents are disabled by default for backward compatibility.
        """
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()

        # Try to seed from registry (has all agents including specialists)
        try:
            from agentsite.agents.registry import AgentRegistry

            core_keys = {"pm", "designer", "developer", "reviewer"}
            for desc in AgentRegistry.list_all():
                enabled = 1 if desc.key in core_keys else 0
                await self._conn.execute(
                    """INSERT OR IGNORE INTO agent_configs
                       (agent_name, enabled, model, temperature, system_prompt_override, category, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (desc.key, enabled, "", desc.default_temperature, None, desc.category.value, now),
                )
        except ImportError:
            # Fallback: seed core agents only if registry can't be imported
            defaults = [
                ("pm", 1, "", 0.3, None, "planning", now),
                ("designer", 1, "", 0.5, None, "design", now),
                ("developer", 1, "", 0.2, None, "development", now),
                ("reviewer", 1, "", 0.1, None, "qa", now),
            ]
            for row in defaults:
                await self._conn.execute(
                    """INSERT OR IGNORE INTO agent_configs
                       (agent_name, enabled, model, temperature, system_prompt_override, category, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    row,
                )
        await self._conn.commit()

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._conn
