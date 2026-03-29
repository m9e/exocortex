"""Target adapter implementations for OpenClaw, Gas Town, and DeerFlow."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Protocol

from exocortex.targets.host import CommandResult, HostDriver
from exocortex.targets.models import TargetPaths, TargetSpec


class TargetAdapter(Protocol):
    """Behavior surface expected from a worker-fabric adapter."""

    def prepare_source(self, target: TargetSpec) -> Path: ...

    def prepare_runtime(self, target: TargetSpec) -> TargetPaths: ...

    def start(self, target: TargetSpec) -> CommandResult: ...

    def healthcheck(self, target: TargetSpec) -> CommandResult: ...

    def proof_of_life(self, target: TargetSpec) -> CommandResult: ...

    def stop(self, target: TargetSpec) -> CommandResult: ...

    def remove(self, target: TargetSpec, *, purge_state: bool = False) -> CommandResult: ...


class BaseTargetAdapter:
    """Shared target harness behavior used by all runtime-specific adapters."""

    expected_markers: tuple[str, ...] = ()

    def __init__(self, repo_root: Path, host_driver: HostDriver) -> None:
        self.repo_root = repo_root.resolve(strict=False)
        self.host_driver = host_driver

    def prepare_source(self, target: TargetSpec) -> Path:
        target.validate_source_policy(self.repo_root)
        source_path = target.resolved_source_path()
        if not source_path.exists():
            raise FileNotFoundError(f"Target source path does not exist: {source_path}")
        if not source_path.is_dir():
            raise FileNotFoundError(f"Target source path is not a directory: {source_path}")
        for marker in self.expected_markers:
            if not (source_path / marker).exists():
                raise FileNotFoundError(
                    f"Target '{target.name}' is missing expected marker '{marker}' in {source_path}"
                )
        return source_path

    def prepare_runtime(self, target: TargetSpec) -> TargetPaths:
        logs_dir = (self.repo_root / ".local" / "logs" / target.name).resolve(strict=False)
        state_root = target.resolved_state_root(self.repo_root)
        logs_dir.mkdir(parents=True, exist_ok=True)
        state_root.mkdir(parents=True, exist_ok=True)
        return TargetPaths(
            source=target.resolved_source_path(),
            state_root=state_root,
            logs_dir=logs_dir,
        )

    def start(self, target: TargetSpec) -> CommandResult:
        self.prepare_source(target)
        paths = self.prepare_runtime(target)
        return self.host_driver.start_target(target, paths)

    def healthcheck(self, target: TargetSpec) -> CommandResult:
        source_path = self.prepare_source(target)
        self.prepare_runtime(target)
        return self._run_host_command(target.health_command, cwd=source_path)

    def proof_of_life(self, target: TargetSpec) -> CommandResult:
        source_path = self.prepare_source(target)
        self.prepare_runtime(target)
        return self._run_host_command(target.proof_command, cwd=source_path)

    def stop(self, target: TargetSpec) -> CommandResult:
        self.prepare_runtime(target)
        return self.host_driver.stop_target(target)

    def remove(self, target: TargetSpec, *, purge_state: bool = False) -> CommandResult:
        paths = self.prepare_runtime(target)
        return self.host_driver.remove_target(target, paths, purge_state=purge_state)

    @staticmethod
    def _run_host_command(command: str, *, cwd: Path) -> CommandResult:
        proc = subprocess.run(
            ["bash", "-lc", command],
            cwd=cwd,
            capture_output=True,
            text=True,
        )
        return CommandResult(
            ok=proc.returncode == 0,
            exit_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            source="host",
        )


class OpenClawAdapter(BaseTargetAdapter):
    expected_markers = ("package.json",)


class GasTownAdapter(BaseTargetAdapter):
    expected_markers = ("go.mod",)


class DeerFlowAdapter(BaseTargetAdapter):
    expected_markers = ("Makefile",)


def adapter_for(target: TargetSpec, repo_root: Path, host_driver: HostDriver) -> TargetAdapter:
    match target.runtime:
        case "openclaw":
            return OpenClawAdapter(repo_root, host_driver)
        case "gastown":
            return GasTownAdapter(repo_root, host_driver)
        case "deerflow":
            return DeerFlowAdapter(repo_root, host_driver)
        case _:
            return BaseTargetAdapter(repo_root, host_driver)
