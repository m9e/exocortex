"""Tests for the container host driver command shaping."""

from __future__ import annotations

import subprocess
from pathlib import Path

from exocortex.targets.host import ContainerHostDriver
from exocortex.targets.models import TargetPaths, TargetSpec


def _target(tmp_path: Path) -> tuple[TargetSpec, TargetPaths]:
    source_path = tmp_path / "openclaw"
    source_path.mkdir()
    target = TargetSpec(
        name="openclaw",
        path=source_path,
        origin="git@github.com:matt/openclaw.git",
        upstream="https://github.com/openclaw/openclaw.git",
        branch="main",
        runtime="openclaw",
        proof_command="printf proof",
        health_command="printf health",
        state_root=tmp_path / "state",
    )
    paths = TargetPaths(
        source=source_path,
        state_root=tmp_path / "state",
        logs_dir=tmp_path / "logs",
    )
    return target, paths


class RecordingContainerHostDriver(ContainerHostDriver):
    def __init__(self, repo_root: Path, responses: list[subprocess.CompletedProcess[str]]) -> None:
        super().__init__(repo_root, preferred_engine="docker")
        self.engine = "docker"
        self._responses = list(responses)
        self.calls: list[list[str]] = []

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        return self._responses.pop(0)


class TestContainerHostDriver:
    def test_start_target_builds_expected_run_command(self, tmp_path: Path) -> None:
        target, paths = _target(tmp_path)
        driver = RecordingContainerHostDriver(
            tmp_path,
            [
                subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="missing"),
                subprocess.CompletedProcess(args=[], returncode=0, stdout="abc123\n", stderr=""),
            ],
        )

        result = driver.start_target(target, paths)

        assert result.ok is True
        run_cmd = driver.calls[-1]
        assert run_cmd[0:3] == ["docker", "run", "-d"]
        assert target.runtime_image() in run_cmd
        assert f"{paths.source}:/workspace" in run_cmd
        assert f"{paths.state_root}:/runtime" in run_cmd

    def test_ensure_tmux_session_installs_or_reuses_tmux(self, tmp_path: Path) -> None:
        target, paths = _target(tmp_path)
        driver = RecordingContainerHostDriver(
            tmp_path,
            [
                subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="missing"),
                subprocess.CompletedProcess(args=[], returncode=0, stdout="abc123\n", stderr=""),
                subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
            ],
        )

        result = driver.ensure_tmux_session(target, paths)

        assert result.ok is True
        exec_cmd = driver.calls[-1]
        assert exec_cmd[0:3] == ["docker", "exec", target.container_name()]
        assert "apt-get install -y tmux" in exec_cmd[-1]

    def test_start_target_returns_unavailable_when_engine_missing(self, tmp_path: Path) -> None:
        target, paths = _target(tmp_path)
        driver = ContainerHostDriver(tmp_path)
        driver.engine = None

        result = driver.start_target(target, paths)

        assert result.ok is False
        assert result.exit_code == 127
