"""Run package-manager commands (install/build) inside a project workspace.

Async subprocess wrappers so long npm installs never block the event loop.
Build errors are returned as data — the project pipeline feeds them back to
the dev agent as self-healing input.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from ..config import settings
from ..templates import TemplateInfo

logger = logging.getLogger("agentsite.workspace_runner")

# Keep the tail — compiler errors come last
_MAX_OUTPUT_CHARS = 8000


@dataclass
class CommandResult:
    ok: bool
    returncode: int
    output: str
    duration_s: float
    command: str

    @property
    def tail(self) -> str:
        return self.output[-_MAX_OUTPUT_CHARS:]


def _which_executable(name: str) -> str | None:
    """Resolve a tool to something CreateProcess can actually run.

    On Windows, node installs ship BOTH an extension-less `npm` (a POSIX
    sh script for Git Bash) and `npm.cmd`. ``shutil.which("npm")`` can
    return the sh script, which fails with WinError 193 ("%1 is not a
    valid Win32 application") — prefer the .cmd/.exe shims explicitly.
    """
    if os.name == "nt":
        for candidate in (f"{name}.cmd", f"{name}.exe", f"{name}.bat"):
            path = shutil.which(candidate)
            if path:
                return path
    return shutil.which(name)


def resolve_package_manager() -> str | None:
    """Full path to the package manager binary (pnpm preferred), or None."""
    pref = settings.package_manager
    if pref and pref != "auto":
        return _which_executable(pref)
    return _which_executable("pnpm") or _which_executable("npm")


def _translate(cmd: list[str], pm_path: str) -> list[str]:
    """Swap a manifest command's leading 'npm'/'pnpm' for the resolved binary."""
    if cmd and cmd[0] in ("npm", "pnpm"):
        return [pm_path, *cmd[1:]]
    return list(cmd)


def _finalize_argv(argv: list[str]) -> list[str]:
    """Batch shims (.cmd/.bat) need an explicit cmd.exe host on Windows."""
    if os.name == "nt" and argv and argv[0].lower().endswith((".cmd", ".bat")):
        return ["cmd.exe", "/c", *argv]
    return argv


async def run_workspace_command(
    workspace_dir: Path, argv: list[str], timeout_s: int
) -> CommandResult:
    """Run a command in the workspace, capturing merged stdout/stderr."""
    argv = _finalize_argv(argv)
    cmd_str = " ".join(argv)
    start = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(workspace_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except OSError as exc:
        return CommandResult(False, -1, f"Failed to start: {exc}", 0.0, cmd_str)

    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        duration = time.monotonic() - start
        return CommandResult(
            False, -1, f"Timed out after {timeout_s}s", round(duration, 1), cmd_str
        )

    duration = time.monotonic() - start
    output = (stdout or b"").decode("utf-8", errors="replace")
    # Strip ANSI color codes (vite et al.) — noise for agents and the UI
    output = re.sub(r"\x1b\[[0-9;]*m", "", output)
    if len(output) > _MAX_OUTPUT_CHARS:
        output = "...(truncated)...\n" + output[-_MAX_OUTPUT_CHARS:]
    result = CommandResult(proc.returncode == 0, proc.returncode or 0, output, round(duration, 1), cmd_str)
    logger.info("workspace cmd %r -> rc=%d in %.1fs", cmd_str, result.returncode, duration)
    return result


async def ensure_install(
    workspace_dir: Path, template: TemplateInfo, *, force: bool = False
) -> CommandResult | None:
    """Install dependencies if needed. None when the template has no install step."""
    if not template.install_cmd:
        return None
    if not force and (workspace_dir / "node_modules").exists():
        return CommandResult(True, 0, "node_modules present — install skipped", 0.0, "install (cached)")
    pm_path = resolve_package_manager()
    if pm_path is None:
        return CommandResult(
            False, -1,
            "No package manager found. Install Node.js (npm) or pnpm and restart AgentSite.",
            0.0, " ".join(template.install_cmd),
        )
    return await run_workspace_command(
        workspace_dir, _translate(template.install_cmd, pm_path), settings.install_timeout_s
    )


async def build_workspace(workspace_dir: Path, template: TemplateInfo) -> CommandResult | None:
    """Run the template's build command. None when there is no build step."""
    if not template.build_cmd:
        return None
    pm_path = resolve_package_manager()
    if pm_path is None:
        return CommandResult(
            False, -1,
            "No package manager found. Install Node.js (npm) or pnpm and restart AgentSite.",
            0.0, " ".join(template.build_cmd),
        )
    install = await ensure_install(workspace_dir, template)
    if install is not None and not install.ok:
        return install
    return await run_workspace_command(
        workspace_dir, _translate(template.build_cmd, pm_path), settings.build_timeout_s
    )
