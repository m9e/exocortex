"""Tests for CLI delegation wrappers.

All tests mock asyncio.create_subprocess_exec — no real CLIs are invoked.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from exocortex.agents.cli import (
    CLIDelegation,
    CLIResult,
    CLIType,
    _build_command,
    cli_handler_factory,
    run_cli,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_process(
    stdout: bytes = b"",
    stderr: bytes = b"",
    returncode: int = 0,
    hang: bool = False,
) -> AsyncMock:
    """Build a mock that behaves like an asyncio subprocess."""
    proc = AsyncMock()
    proc.returncode = returncode

    # Build stream readers that yield data once then EOF
    stdout_reader = AsyncMock(spec=asyncio.StreamReader)
    stderr_reader = AsyncMock(spec=asyncio.StreamReader)

    if hang:
        # Simulate a process that never finishes reading
        async def _hang_read(_n: int = 4096) -> bytes:
            await asyncio.sleep(3600)
            return b""  # pragma: no cover

        stdout_reader.read = _hang_read
        stderr_reader.read = _hang_read
        proc.wait = AsyncMock(side_effect=asyncio.sleep(3600))
    else:
        stdout_reader.read = AsyncMock(side_effect=[stdout, b""])
        stderr_reader.read = AsyncMock(side_effect=[stderr, b""])
        proc.wait = AsyncMock(return_value=None)

    proc.stdout = stdout_reader
    proc.stderr = stderr_reader
    proc.kill = MagicMock()
    return proc


# ---------------------------------------------------------------------------
# Model construction
# ---------------------------------------------------------------------------


class TestCLIDelegationModel:
    def test_claude_delegation(self) -> None:
        d = CLIDelegation(
            cli=CLIType.CLAUDE,
            prompt="Summarize this repo",
            working_directory="/tmp/repo",
        )
        assert d.cli == CLIType.CLAUDE
        assert d.timeout_seconds == 1800.0
        assert d.max_output_bytes == 10 * 1024 * 1024

    def test_codex_delegation(self) -> None:
        d = CLIDelegation(
            cli=CLIType.CODEX,
            prompt="Fix the tests",
            working_directory="/tmp/repo",
            timeout_seconds=60.0,
        )
        assert d.cli == CLIType.CODEX
        assert d.timeout_seconds == 60.0

    def test_gemini_delegation(self) -> None:
        d = CLIDelegation(
            cli=CLIType.GEMINI,
            prompt="Review PR",
            working_directory="/home/user/code",
            max_output_bytes=1024,
        )
        assert d.cli == CLIType.GEMINI
        assert d.max_output_bytes == 1024


class TestCLIResultModel:
    def test_result_construction(self) -> None:
        r = CLIResult(
            cli=CLIType.CLAUDE,
            exit_code=0,
            stdout="ok",
            stderr="",
            duration_seconds=1.5,
            files_changed=["src/main.py"],
        )
        assert r.exit_code == 0
        assert r.files_changed == ["src/main.py"]

    def test_result_defaults(self) -> None:
        r = CLIResult(
            cli=CLIType.CODEX,
            exit_code=1,
            stdout="",
            stderr="error",
            duration_seconds=0.1,
        )
        assert r.files_changed == []


# ---------------------------------------------------------------------------
# Command construction
# ---------------------------------------------------------------------------


class TestCommandConstruction:
    def test_claude_command(self) -> None:
        d = CLIDelegation(cli=CLIType.CLAUDE, prompt="hello", working_directory="/tmp")
        assert _build_command(d) == ["claude", "-p", "hello"]

    def test_codex_command(self) -> None:
        d = CLIDelegation(cli=CLIType.CODEX, prompt="fix bug", working_directory="/tmp")
        assert _build_command(d) == ["codex", "exec", "fix bug"]

    def test_gemini_command(self) -> None:
        d = CLIDelegation(cli=CLIType.GEMINI, prompt="review", working_directory="/tmp")
        assert _build_command(d) == ["gemini", "-p", "review"]


# ---------------------------------------------------------------------------
# Subprocess execution (mocked)
# ---------------------------------------------------------------------------


class TestRunCLI:
    @pytest.mark.asyncio
    async def test_successful_run(self) -> None:
        proc = _make_mock_process(stdout=b"output here", returncode=0)

        with patch(
            "exocortex.agents.cli.asyncio.create_subprocess_exec", return_value=proc
        ) as mock_exec:
            d = CLIDelegation(cli=CLIType.CLAUDE, prompt="hi", working_directory="/tmp")
            result = await run_cli(d)

        mock_exec.assert_awaited_once()
        assert result.exit_code == 0
        assert result.stdout == "output here"
        assert result.duration_seconds > 0

    @pytest.mark.asyncio
    async def test_nonzero_exit_code(self) -> None:
        proc = _make_mock_process(stderr=b"failed", returncode=1)

        with patch("exocortex.agents.cli.asyncio.create_subprocess_exec", return_value=proc):
            d = CLIDelegation(cli=CLIType.CODEX, prompt="bad", working_directory="/tmp")
            result = await run_cli(d)

        assert result.exit_code == 1
        assert result.stderr == "failed"

    @pytest.mark.asyncio
    async def test_cli_type_preserved_in_result(self) -> None:
        proc = _make_mock_process()

        with patch("exocortex.agents.cli.asyncio.create_subprocess_exec", return_value=proc):
            d = CLIDelegation(cli=CLIType.GEMINI, prompt="x", working_directory="/tmp")
            result = await run_cli(d)

        assert result.cli == CLIType.GEMINI


# ---------------------------------------------------------------------------
# Timeout enforcement
# ---------------------------------------------------------------------------


class TestTimeout:
    @pytest.mark.asyncio
    async def test_timeout_kills_process(self) -> None:
        proc = _make_mock_process(hang=True)
        # Override kill/wait for the timeout path
        proc.kill = MagicMock()
        proc.wait = AsyncMock(return_value=None)

        with patch("exocortex.agents.cli.asyncio.create_subprocess_exec", return_value=proc):
            d = CLIDelegation(
                cli=CLIType.CLAUDE,
                prompt="slow",
                working_directory="/tmp",
                timeout_seconds=0.05,
            )
            result = await run_cli(d)

        assert result.exit_code == -1
        assert "timeout" in result.stderr.lower()
        proc.kill.assert_called_once()


# ---------------------------------------------------------------------------
# Output truncation
# ---------------------------------------------------------------------------


class TestOutputTruncation:
    @pytest.mark.asyncio
    async def test_stdout_truncated_at_max_bytes(self) -> None:
        big_output = b"x" * 2000
        proc = _make_mock_process(stdout=big_output)

        with patch("exocortex.agents.cli.asyncio.create_subprocess_exec", return_value=proc):
            d = CLIDelegation(
                cli=CLIType.CLAUDE,
                prompt="big",
                working_directory="/tmp",
                max_output_bytes=100,
            )
            result = await run_cli(d)

        assert len(result.stdout) <= 100

    @pytest.mark.asyncio
    async def test_stderr_truncated_at_max_bytes(self) -> None:
        big_err = b"e" * 5000
        proc = _make_mock_process(stderr=big_err)

        with patch("exocortex.agents.cli.asyncio.create_subprocess_exec", return_value=proc):
            d = CLIDelegation(
                cli=CLIType.CODEX,
                prompt="err",
                working_directory="/tmp",
                max_output_bytes=200,
            )
            result = await run_cli(d)

        assert len(result.stderr) <= 200


# ---------------------------------------------------------------------------
# Handler factory
# ---------------------------------------------------------------------------


class TestCLIHandlerFactory:
    def test_returns_callable(self) -> None:
        handler = cli_handler_factory(CLIType.CLAUDE, "Review {file}")
        assert callable(handler)

    def test_handler_output_structure(self) -> None:
        proc = _make_mock_process(stdout=b"done", stderr=b"warn", returncode=0)

        with patch("exocortex.agents.cli.asyncio.create_subprocess_exec", return_value=proc):
            handler = cli_handler_factory(CLIType.CLAUDE, "Review {file}")
            state: dict[str, Any] = {
                "file": "main.py",
                "working_directory": "/tmp",
            }
            output = handler(state)

        assert "stdout" in output
        assert "stderr" in output
        assert "exit_code" in output
        assert output["stdout"] == "done"
        assert output["exit_code"] == 0

    def test_handler_formats_prompt(self) -> None:
        proc = _make_mock_process()
        calls: list[tuple[Any, ...]] = []

        async def _capture(*args: Any, **kwargs: Any) -> AsyncMock:
            calls.append(args)
            return proc

        with patch("exocortex.agents.cli.asyncio.create_subprocess_exec", side_effect=_capture):
            handler = cli_handler_factory(CLIType.GEMINI, "Summarize {topic} in {language}")
            handler(
                {
                    "topic": "graphs",
                    "language": "English",
                    "working_directory": "/code",
                }
            )

        # The prompt should have been formatted into the command
        assert len(calls) == 1
        cmd_args = calls[0]
        assert "Summarize graphs in English" in cmd_args

    def test_handler_uses_working_directory_from_state(self) -> None:
        proc = _make_mock_process()
        captured_kwargs: list[dict[str, Any]] = []

        async def _capture(*args: Any, **kwargs: Any) -> AsyncMock:
            captured_kwargs.append(kwargs)
            return proc

        with patch("exocortex.agents.cli.asyncio.create_subprocess_exec", side_effect=_capture):
            handler = cli_handler_factory(CLIType.CODEX, "fix {bug}")
            handler(
                {
                    "bug": "null pointer",
                    "working_directory": "/my/project",
                }
            )

        assert captured_kwargs[0]["cwd"] == "/my/project"
