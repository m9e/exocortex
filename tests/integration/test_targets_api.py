"""Integration tests for the target lifecycle API surface."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from exocortex.api.app import create_app
from exocortex.targets.host import CommandResult, TerminalContext, TmuxExecResult
from exocortex.targets.models import TargetContainerInfo, TargetSpec, TargetTmuxInfo
from exocortex.targets.registry import TargetRegistry
from exocortex.targets.service import TargetService


def _write_manifest(repo_root: Path, source_path: Path) -> None:
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
        return "tmux capture"

    def send_tmux_input(self, target: TargetSpec, text: str, *, enter: bool) -> CommandResult:
        return CommandResult(True, 0, "input sent\n", "", "fake")

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
            output="exec output",
            capture="tmux capture",
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
def client(tmp_path: Path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    source_path = tmp_path / "openclaw"
    source_path.mkdir()
    (source_path / "package.json").write_text("{}\n")
    _write_manifest(repo_root, source_path)

    app = create_app()
    with TestClient(app) as test_client:
        test_client.app.state.target_service = TargetService(
            repo_root=repo_root,
            registry=TargetRegistry.load_default(repo_root),
            host_driver=FakeHostDriver(),
        )
        yield test_client


class TestTargetRoutes:
    def test_list_and_detail(self, client: TestClient) -> None:
        list_response = client.get("/targets")
        detail_response = client.get("/targets/openclaw")

        assert list_response.status_code == 200
        assert list_response.json()[0]["id"] == "openclaw"
        assert detail_response.status_code == 200
        assert detail_response.json()["id"] == "openclaw"

    def test_health_proof_and_lifecycle(self, client: TestClient) -> None:
        assert client.post("/targets/openclaw/health").status_code == 200
        assert client.post("/targets/openclaw/proof").status_code == 200
        assert client.post("/targets/openclaw/start").status_code == 200
        assert client.post("/targets/openclaw/tmux/up").status_code == 200
        capture = client.get("/targets/openclaw/tmux/capture")
        assert capture.status_code == 200
        assert capture.json()["content"] == "tmux capture"
        exec_response = client.post("/targets/openclaw/tmux/exec", json={"command": "echo hi"})
        assert exec_response.status_code == 200
        assert exec_response.json()["completed"] is True

    def test_terminal_websocket(self, client: TestClient) -> None:
        with client.websocket_connect("/ws/targets/openclaw") as websocket:
            messages = [websocket.receive_json() for _ in range(2)]
            websocket.close()

        states = [msg.get("state") for msg in messages if msg.get("type") == "status"]

        assert "connecting" in states
        assert "ready" in states
