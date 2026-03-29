"""Application service for target lifecycle, proof-of-life, and terminal control."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from exocortex.targets.adapters import adapter_for
from exocortex.targets.host import (
    CommandResult,
    ContainerHostDriver,
    HostDriver,
    TerminalContext,
    TmuxExecResult,
)
from exocortex.targets.models import (
    TargetDetail,
    TargetPaths,
    TargetSpec,
    TargetSummary,
)
from exocortex.targets.registry import TargetRegistry


class CommandResponse(BaseModel):
    """Serializable command result returned by the API."""

    ok: bool
    exit_code: int
    stdout: str
    stderr: str
    source: str


class StartTargetRequest(BaseModel):
    """Optional lifecycle overrides for starting a target."""

    image: str | None = None


class RemoveTargetRequest(BaseModel):
    """Payload for deleting a target runtime."""

    purge_state: bool = Field(default=False)


class TmuxUpRequest(StartTargetRequest):
    """Payload for ensuring the tmux session is available."""


class TmuxCaptureResponse(BaseModel):
    """Captured text from the active tmux pane."""

    session_name: str
    lines: int
    content: str


class TmuxInputRequest(BaseModel):
    """Keyboard input sent to the active tmux session."""

    data: str = Field(default="")
    enter: bool = Field(default=True)


class TmuxExecRequest(BaseModel):
    """Shell command executed inside the active tmux session."""

    command: str = Field(min_length=1)
    timeout_seconds: float = Field(default=15.0, ge=0.1, le=180.0)
    capture_lines: int = Field(default=400, ge=50, le=5000)


class TmuxExecResponse(BaseModel):
    """Serialized result from a tmux-backed command execution."""

    session_name: str
    command: str
    marker: str
    completed: bool
    exit_code: int | None = None
    output: str = ""
    capture: str = ""


class TargetService:
    """Facade over target registry, adapters, and host drivers."""

    def __init__(
        self,
        *,
        repo_root: Path | None = None,
        registry: TargetRegistry | None = None,
        host_driver: HostDriver | None = None,
    ) -> None:
        self.repo_root = (repo_root or Path(__file__).resolve().parents[3]).resolve(strict=False)
        self.registry = registry or TargetRegistry.load_default(self.repo_root)
        self.host_driver = host_driver or ContainerHostDriver(self.repo_root)

    async def list_targets(self) -> list[TargetSummary]:
        return [self._build_summary(target) for target in self.registry.list()]

    async def get_target(self, target_id: str) -> TargetDetail | None:
        target = self.registry.get(target_id)
        if target is None:
            return None
        return self._build_detail(target)

    async def healthcheck_target(self, target_id: str) -> CommandResult:
        return self._call_adapter(target_id, "healthcheck")

    async def proof_target(self, target_id: str) -> CommandResult:
        return self._call_adapter(target_id, "proof_of_life")

    async def start_target(self, target_id: str, payload: StartTargetRequest) -> CommandResult:
        return self._call_adapter(target_id, "start", image_override=payload.image)

    async def stop_target(self, target_id: str) -> CommandResult:
        return self._call_adapter(target_id, "stop")

    async def remove_target(
        self,
        target_id: str,
        payload: RemoveTargetRequest,
    ) -> CommandResult:
        return self._call_adapter(target_id, "remove", purge_state=payload.purge_state)

    async def tmux_up(self, target_id: str, payload: TmuxUpRequest) -> CommandResult:
        try:
            target = self._require_target(target_id, image_override=payload.image)
            adapter = adapter_for(target, self.repo_root, self.host_driver)
            adapter.prepare_source(target)
            paths = adapter.prepare_runtime(target)
            return self.host_driver.ensure_tmux_session(target, paths)
        except (FileNotFoundError, ValueError) as exc:
            return self._exception_result(exc)

    async def tmux_kill(self, target_id: str) -> CommandResult:
        try:
            target = self._require_target(target_id)
            return self.host_driver.kill_tmux_session(target)
        except ValueError as exc:
            return self._exception_result(exc)

    async def tmux_capture(self, target_id: str, lines: int) -> TmuxCaptureResponse:
        target = self._require_target(target_id)
        content = self.host_driver.capture_tmux(target, lines=lines)
        return TmuxCaptureResponse(
            session_name=target.tmux_session_name(),
            lines=lines,
            content=content,
        )

    async def tmux_input(self, target_id: str, payload: TmuxInputRequest) -> CommandResult:
        if not payload.data and not payload.enter:
            return CommandResult(False, 2, "", "Either data or enter=true is required.", "runtime")
        try:
            target = self._require_target(target_id)
            return self.host_driver.send_tmux_input(target, payload.data, enter=payload.enter)
        except ValueError as exc:
            return self._exception_result(exc)

    async def tmux_exec(self, target_id: str, payload: TmuxExecRequest) -> TmuxExecResponse:
        target = self._require_target(target_id)
        result = self.host_driver.exec_tmux(
            target,
            command=payload.command,
            timeout_seconds=payload.timeout_seconds,
            capture_lines=payload.capture_lines,
        )
        return self._tmux_exec_response(result)

    def ensure_terminal_session(self, target_id: str) -> TerminalContext:
        target = self._require_target(target_id)
        adapter = adapter_for(target, self.repo_root, self.host_driver)
        adapter.prepare_source(target)
        paths = adapter.prepare_runtime(target)
        return self.host_driver.ensure_terminal_session(target, paths)

    def _call_adapter(
        self,
        target_id: str,
        method_name: str,
        *,
        image_override: str | None = None,
        purge_state: bool = False,
    ) -> CommandResult:
        try:
            target = self._require_target(target_id, image_override=image_override)
            adapter = adapter_for(target, self.repo_root, self.host_driver)
            match method_name:
                case "start":
                    return adapter.start(target)
                case "healthcheck":
                    return adapter.healthcheck(target)
                case "proof_of_life":
                    return adapter.proof_of_life(target)
                case "stop":
                    return adapter.stop(target)
                case "remove":
                    return adapter.remove(target, purge_state=purge_state)
                case _:
                    raise ValueError(f"Unsupported adapter method: {method_name}")
        except (FileNotFoundError, ValueError) as exc:
            return self._exception_result(exc)

    def _build_summary(self, target: TargetSpec) -> TargetSummary:
        container = self.host_driver.inspect_target(target)
        tmux = self.host_driver.inspect_tmux(target)
        return TargetSummary(
            id=target.name,
            runtime=target.runtime,
            source_exists=target.resolved_source_path().exists(),
            manifest_path=self.registry.manifest_path,
            container_status=container.status,
            tmux_status=tmux.status,
        )

    def _build_detail(self, target: TargetSpec) -> TargetDetail:
        paths = self._paths_for(target)
        container = self.host_driver.inspect_target(target)
        tmux = self.host_driver.inspect_tmux(target)
        return TargetDetail(
            id=target.name,
            runtime=target.runtime,
            origin=target.origin,
            upstream=target.upstream,
            branch=target.branch,
            proof_command=target.proof_command,
            health_command=target.health_command,
            manifest_path=self.registry.manifest_path,
            paths=paths,
            source_exists=paths.source.exists(),
            container=container,
            tmux=tmux,
        )

    def _paths_for(self, target: TargetSpec) -> TargetPaths:
        return TargetPaths(
            source=target.resolved_source_path(),
            state_root=target.resolved_state_root(self.repo_root),
            logs_dir=(self.repo_root / ".local" / "logs" / target.name).resolve(strict=False),
        )

    def _require_target(
        self,
        target_id: str,
        *,
        image_override: str | None = None,
    ) -> TargetSpec:
        target = self.registry.get(target_id)
        if target is None:
            raise ValueError(f"Target '{target_id}' not found.")
        if image_override:
            return target.model_copy(update={"image": image_override})
        return target

    @staticmethod
    def _exception_result(exc: Exception) -> CommandResult:
        return CommandResult(False, 1, "", str(exc), "runtime")

    @staticmethod
    def _tmux_exec_response(result: TmuxExecResult) -> TmuxExecResponse:
        return TmuxExecResponse(
            session_name=result.session_name,
            command=result.command,
            marker=result.marker,
            completed=result.completed,
            exit_code=result.exit_code,
            output=result.output,
            capture=result.capture,
        )


def command_response(result: CommandResult) -> CommandResponse:
    return CommandResponse(
        ok=result.ok,
        exit_code=result.exit_code,
        stdout=result.stdout,
        stderr=result.stderr,
        source=result.source,
    )
