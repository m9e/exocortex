"""CLI delegation wrappers for external agent CLIs (Claude, Codex, Gemini)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

_STRICT = ConfigDict(strict=True)

_TEN_MB = 10 * 1024 * 1024


class CLIType(StrEnum):
    CLAUDE = "claude"
    CODEX = "codex"
    GEMINI = "gemini"


class CLIDelegation(BaseModel):
    """Specification for delegating work to a CLI agent."""

    model_config = _STRICT
    cli: CLIType
    prompt: str
    working_directory: str
    timeout_seconds: float = 1800.0
    max_output_bytes: int = _TEN_MB


class CLIResult(BaseModel):
    """Result from a CLI agent execution."""

    model_config = _STRICT
    cli: CLIType
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    files_changed: list[str] = []


# -- Command construction --


def _build_command(delegation: CLIDelegation) -> list[str]:
    """Build the subprocess argument list for the given CLI type."""
    match delegation.cli:
        case CLIType.CLAUDE:
            return ["claude", "-p", delegation.prompt]
        case CLIType.CODEX:
            return ["codex", "exec", delegation.prompt]
        case CLIType.GEMINI:
            return ["gemini", "-p", delegation.prompt]


# -- Async execution --


async def _read_stream(
    stream: asyncio.StreamReader | None, limit: int
) -> str:
    """Read from an async stream up to *limit* bytes."""
    if stream is None:
        return ""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await stream.read(4096)
        if not chunk:
            break
        remaining = limit - total
        if remaining <= 0:
            break
        chunks.append(chunk[:remaining])
        total += len(chunks[-1])
    return b"".join(chunks).decode("utf-8", errors="replace")


async def run_cli(delegation: CLIDelegation) -> CLIResult:
    """Run an external CLI agent as a subprocess.

    Enforces timeout and output-size limits.
    """
    cmd = _build_command(delegation)
    start = time.monotonic()

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=delegation.working_directory,
    )

    try:
        stdout_text, stderr_text = await asyncio.wait_for(
            asyncio.gather(
                _read_stream(proc.stdout, delegation.max_output_bytes),
                _read_stream(proc.stderr, delegation.max_output_bytes),
            ),
            timeout=delegation.timeout_seconds,
        )
        await proc.wait()
        exit_code = proc.returncode or 0
    except TimeoutError:
        proc.kill()
        await proc.wait()
        elapsed = time.monotonic() - start
        return CLIResult(
            cli=delegation.cli,
            exit_code=-1,
            stdout="",
            stderr=f"Process killed after {elapsed:.1f}s (timeout)",
            duration_seconds=elapsed,
        )

    elapsed = time.monotonic() - start
    return CLIResult(
        cli=delegation.cli,
        exit_code=exit_code,
        stdout=stdout_text,
        stderr=stderr_text,
        duration_seconds=elapsed,
    )


# -- Sync wrapper --


def run_cli_sync(delegation: CLIDelegation) -> CLIResult:
    """Synchronous wrapper around :func:`run_cli`."""
    return asyncio.run(run_cli(delegation))


# -- Handler factory --

NodeHandler = Callable[[dict[str, Any]], dict[str, Any]]


def cli_handler_factory(
    cli_type: CLIType,
    prompt_template: str,
) -> NodeHandler:
    """Return a handler compatible with ``GraphEngine.register_handler()``.

    The handler formats *prompt_template* with graph state values,
    delegates to the CLI, and returns the result dict.
    """

    def handler(state: dict[str, Any]) -> dict[str, Any]:
        prompt = prompt_template.format(**state)
        delegation = CLIDelegation(
            cli=cli_type,
            prompt=prompt,
            working_directory=state.get("working_directory", "."),
        )
        result = run_cli_sync(delegation)
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.exit_code,
        }

    return handler
