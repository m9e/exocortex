"""Tests for target service behavior and CLI integration."""

from __future__ import annotations

from pathlib import Path

import pytest

from exocortex.targets.cli import main
from exocortex.targets.host import CommandResult, TerminalContext, TmuxExecResult
from exocortex.targets.models import TargetContainerInfo, TargetSpec, TargetTmuxInfo
from exocortex.targets.registry import TargetRegistry
from exocortex.targets.service import TargetService


def _write_openclaw_manifest(repo_root: Path, source_path: Path) -> Path:
    manifest_path = repo_root / "config" / "targets.example.toml"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        "\n".join(
            [
                "[targets.openclaw]",
                'name = "openclaw"',
                f'path = "{source_path}"',
                'origin = "git@github.com:matt/openclaw.git"',
                'upstream = "https://github.com/openclaw/openclaw.git"',
                'branch = "main"',
                'runtime = "openclaw"',
                'proof_command = "printf proof"',
                'health_command = "printf health"',
                'state_root = ".local/instances/openclaw"',
            ]
        )
        + "\n"
    )
    return manifest_path


class FakeHostDriver:
    def __init__(self) -> None:
        self.started = False
        self.tmux_running = False

    def inspect_target(self, target: TargetSpec) -> TargetContainerInfo:
        status = "running" if self.started else "missing"
        return TargetContainerInfo(
            name=target.container_name(),
            engine="fake",
            status=status,
            running=self.started,
            image=target.runtime_image(),
        )

    def inspect_tmux(self, target: TargetSpec) -> TargetTmuxInfo:
        return TargetTmuxInfo(
            session_name=target.tmux_session_name(),
            status="running" if self.tmux_running else "absent",
            attached=False if self.tmux_running else None,
        )

    def start_target(self, target: TargetSpec, paths) -> CommandResult:
        self.started = True
        return CommandResult(True, 0, "started\n", "", "fake")

    def stop_target(self, target: TargetSpec) -> CommandResult:
        self.started = False
        return CommandResult(True, 0, "stopped\n", "", "fake")

    def remove_target(
        self,
        target: TargetSpec,
        paths,
        *,
        purge_state: bool = False,
    ) -> CommandResult:
        self.started = False
        self.tmux_running = False
        return CommandResult(True, 0, "removed\n", "", "fake")

    def ensure_tmux_session(self, target: TargetSpec, paths) -> CommandResult:
        self.started = True
        self.tmux_running = True
        return CommandResult(True, 0, "tmux ready\n", "", "fake")

    def kill_tmux_session(self, target: TargetSpec) -> CommandResult:
        self.tmux_running = False
        return CommandResult(True, 0, "tmux killed\n", "", "fake")

    def capture_tmux(self, target: TargetSpec, *, lines: int) -> str:
        return f"captured {lines}"

    def send_tmux_input(self, target: TargetSpec, text: str, *, enter: bool) -> CommandResult:
        return CommandResult(True, 0, f"input:{text}\n", "", "fake")

    def exec_tmux(
        self,
        target: TargetSpec,
        *,
        command: str,
        timeout_seconds: float,
        capture_lines: int,
    ) -> TmuxExecResult:
        return TmuxExecResult(
            session_name=target.tmux_session_name(),
            command=command,
            marker="marker",
            completed=True,
            exit_code=0,
            output="done",
            capture="capture",
        )

    def ensure_terminal_session(self, target: TargetSpec, paths) -> TerminalContext:
        self.started = True
        self.tmux_running = True
        return TerminalContext(
            target_id=target.name,
            container_name=target.container_name(),
            tmux_session=target.tmux_session_name(),
            command=["/bin/bash", "-lc", "printf hello; sleep 0.05"],
        )


@pytest.fixture
def repo_and_manifest(tmp_path: Path) -> tuple[Path, Path]:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    source_path = tmp_path / "openclaw"
    source_path.mkdir()
    (source_path / "package.json").write_text("{}\n")
    manifest_path = _write_openclaw_manifest(repo_root, source_path)
    return repo_root, manifest_path


class TestTargetService:
    @pytest.mark.asyncio
    async def test_lists_targets_and_runs_commands(
        self,
        repo_and_manifest: tuple[Path, Path],
    ) -> None:
        repo_root, _manifest_path = repo_and_manifest
        service = TargetService(
            repo_root=repo_root,
            registry=TargetRegistry.load_default(repo_root),
            host_driver=FakeHostDriver(),
        )

        summaries = await service.list_targets()
        health = await service.healthcheck_target("openclaw")
        proof = await service.proof_target("openclaw")

        assert summaries[0].id == "openclaw"
        assert summaries[0].container_status == "missing"
        assert health.ok is True
        assert health.stdout == "health"
        assert proof.ok is True
        assert proof.stdout == "proof"

    @pytest.mark.asyncio
    async def test_missing_target_returns_failed_result(
        self,
        repo_and_manifest: tuple[Path, Path],
    ) -> None:
        repo_root, _manifest_path = repo_and_manifest
        service = TargetService(
            repo_root=repo_root,
            registry=TargetRegistry.load_default(repo_root),
            host_driver=FakeHostDriver(),
        )

        result = await service.healthcheck_target("missing")

        assert result.ok is False
        assert "not found" in result.stderr


class TestTargetCLI:
    def test_list_and_health_commands(
        self,
        monkeypatch: pytest.MonkeyPatch,
        repo_and_manifest,
        capsys,
    ) -> None:
        _repo_root, manifest_path = repo_and_manifest
        monkeypatch.setenv("EXOCORTEX_TARGETS_FILE", str(manifest_path))

        list_rc = main(["target", "list"])
        list_output = capsys.readouterr().out

        health_rc = main(["target", "health", "openclaw"])
        health_output = capsys.readouterr().out

        assert list_rc == 0
        assert '"id": "openclaw"' in list_output
        assert health_rc == 0
        assert "health" in health_output
