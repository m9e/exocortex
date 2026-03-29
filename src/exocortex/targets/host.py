"""Host-driver primitives for target lifecycle and tmux-backed control."""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from shlex import quote
from typing import Protocol

from exocortex.targets.models import TargetContainerInfo, TargetPaths, TargetSpec, TargetTmuxInfo


@dataclass
class CommandResult:
    """Result from a lifecycle or shell command."""

    ok: bool
    exit_code: int
    stdout: str
    stderr: str
    source: str


@dataclass
class TmuxExecResult:
    """Captured result from a tmux-backed command execution."""

    session_name: str
    command: str
    marker: str
    completed: bool
    exit_code: int | None = None
    output: str = ""
    capture: str = ""


@dataclass
class TerminalContext:
    """Information required to attach a PTY or WebSocket terminal to a target."""

    target_id: str
    container_name: str
    tmux_session: str
    container_engine: str | None = None
    command: list[str] | None = None


class HostDriver(Protocol):
    """Common lifecycle interface for different host backends."""

    def inspect_target(self, target: TargetSpec) -> TargetContainerInfo: ...

    def inspect_tmux(self, target: TargetSpec) -> TargetTmuxInfo: ...

    def start_target(self, target: TargetSpec, paths: TargetPaths) -> CommandResult: ...

    def stop_target(self, target: TargetSpec) -> CommandResult: ...

    def remove_target(
        self,
        target: TargetSpec,
        paths: TargetPaths,
        *,
        purge_state: bool = False,
    ) -> CommandResult: ...

    def ensure_tmux_session(self, target: TargetSpec, paths: TargetPaths) -> CommandResult: ...

    def kill_tmux_session(self, target: TargetSpec) -> CommandResult: ...

    def capture_tmux(self, target: TargetSpec, *, lines: int) -> str: ...

    def send_tmux_input(self, target: TargetSpec, text: str, *, enter: bool) -> CommandResult: ...

    def exec_tmux(
        self,
        target: TargetSpec,
        *,
        command: str,
        timeout_seconds: float,
        capture_lines: int,
    ) -> TmuxExecResult: ...

    def ensure_terminal_session(
        self,
        target: TargetSpec,
        paths: TargetPaths,
    ) -> TerminalContext: ...


class ContainerHostDriver:
    """Container-backed host driver using docker or podman."""

    def __init__(
        self,
        repo_root: Path,
        *,
        preferred_engine: str | None = None,
    ) -> None:
        self.repo_root = repo_root.resolve(strict=False)
        self.engine = self._resolve_engine(preferred_engine)

    @staticmethod
    def _resolve_engine(preferred: str | None) -> str | None:
        if preferred and shutil.which(preferred):
            return preferred
        for candidate in ("docker", "podman"):
            if shutil.which(candidate):
                return candidate
        return None

    def inspect_target(self, target: TargetSpec) -> TargetContainerInfo:
        info = TargetContainerInfo(name=target.container_name(), engine=self.engine)
        if self.engine is None:
            return info

        proc = self._run(
            [
                self.engine,
                "inspect",
                target.container_name(),
                "--format",
                "{{.State.Status}}|{{.Config.Image}}|{{.State.ExitCode}}",
            ]
        )
        if proc.returncode != 0:
            return info.model_copy(update={"status": "missing"})

        raw_status, raw_image, raw_exit = (proc.stdout.strip().split("|") + ["", "", ""])[:3]
        return TargetContainerInfo(
            name=target.container_name(),
            engine=self.engine,
            status=raw_status or "unknown",
            running=raw_status == "running",
            image=raw_image or None,
            exit_code=int(raw_exit) if raw_exit.isdigit() else None,
        )

    def inspect_tmux(self, target: TargetSpec) -> TargetTmuxInfo:
        session_name = target.tmux_session_name()
        info = TargetTmuxInfo(session_name=session_name)
        container = self.inspect_target(target)
        if self.engine is None or not container.running:
            return info

        proc = self._exec_in_container(
            target,
            ["bash", "-lc", f"tmux has-session -t {quote(session_name)}"],
        )
        if proc.returncode != 0:
            return info

        attached_proc = self._exec_in_container(
            target,
            ["bash", "-lc", "tmux list-sessions -F '#{session_name}:#{session_attached}'"],
        )
        attached = None
        for line in attached_proc.stdout.splitlines():
            prefix, _, flag = line.partition(":")
            if prefix == session_name:
                attached = flag == "1"
                break

        return TargetTmuxInfo(session_name=session_name, status="running", attached=attached)

    def start_target(self, target: TargetSpec, paths: TargetPaths) -> CommandResult:
        if self.engine is None:
            return self._unavailable_result()

        container = self.inspect_target(target)
        if container.running:
            return CommandResult(True, 0, "container already running\n", "", self.engine)
        if container.status != "missing":
            proc = self._run([self.engine, "start", target.container_name()])
            return self._command_result(proc)

        paths.state_root.mkdir(parents=True, exist_ok=True)
        paths.logs_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            self.engine,
            "run",
            "-d",
            "--name",
            target.container_name(),
            "--label",
            f"exocortex.target={target.name}",
            "-w",
            target.container_workdir,
            "-v",
            f"{paths.source}:/workspace",
            "-v",
            f"{paths.state_root}:/runtime",
        ]
        for host_alias in self._host_aliases():
            cmd.extend(["--add-host", host_alias])
        cmd.extend(
            [
                target.runtime_image(),
                "bash",
                "-lc",
                "trap : TERM INT; sleep infinity & wait",
            ]
        )
        proc = self._run(cmd)
        return self._command_result(proc)

    def stop_target(self, target: TargetSpec) -> CommandResult:
        if self.engine is None:
            return self._unavailable_result()
        container = self.inspect_target(target)
        if container.status == "missing":
            return CommandResult(True, 0, "container already absent\n", "", self.engine)
        if not container.running:
            return CommandResult(True, 0, "container already stopped\n", "", self.engine)
        proc = self._run([self.engine, "stop", target.container_name()])
        return self._command_result(proc)

    def remove_target(
        self,
        target: TargetSpec,
        paths: TargetPaths,
        *,
        purge_state: bool = False,
    ) -> CommandResult:
        if self.engine is None:
            return self._unavailable_result()

        proc = self._run([self.engine, "rm", "-f", target.container_name()])
        if proc.returncode != 0 and "No such container" not in proc.stderr:
            return self._command_result(proc)

        if purge_state and paths.state_root.exists():
            shutil.rmtree(paths.state_root)

        stdout = proc.stdout
        if purge_state:
            stdout += f"purged state root {paths.state_root}\n"
        return CommandResult(True, 0, stdout or "container removed\n", "", self.engine)

    def ensure_tmux_session(self, target: TargetSpec, paths: TargetPaths) -> CommandResult:
        start_result = self.start_target(target, paths)
        if not start_result.ok:
            return start_result
        if self.engine is None:
            return self._unavailable_result()

        session = quote(target.tmux_session_name())
        workdir = quote(target.container_workdir)
        script = "\n".join(
            [
                "set -e",
                "if ! command -v tmux >/dev/null 2>&1; then",
                "  apt-get update >/dev/null",
                "  DEBIAN_FRONTEND=noninteractive apt-get install -y tmux >/dev/null",
                "fi",
                f"if ! tmux has-session -t {session} 2>/dev/null; then",
                f"  tmux new-session -d -s {session} -c {workdir}",
                "fi",
            ]
        )
        proc = self._exec_in_container(target, ["bash", "-lc", script])
        return self._command_result(proc)

    def kill_tmux_session(self, target: TargetSpec) -> CommandResult:
        if self.engine is None:
            return self._unavailable_result()
        session = quote(target.tmux_session_name())
        proc = self._exec_in_container(
            target,
            [
                "bash",
                "-lc",
                (
                    f"tmux has-session -t {session} 2>/dev/null "
                    f"&& tmux kill-session -t {session} || true"
                ),
            ],
        )
        return self._command_result(proc)

    def capture_tmux(self, target: TargetSpec, *, lines: int) -> str:
        if self.engine is None:
            raise RuntimeError("No container engine available.")
        proc = self._exec_in_container(
            target,
            [
                "tmux",
                "capture-pane",
                "-t",
                target.tmux_session_name(),
                "-p",
                "-S",
                f"-{max(1, lines)}",
            ],
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "tmux capture failed")
        return proc.stdout

    def send_tmux_input(self, target: TargetSpec, text: str, *, enter: bool) -> CommandResult:
        if self.engine is None:
            return self._unavailable_result()
        if text:
            proc = self._exec_in_container(
                target,
                [
                    "tmux",
                    "send-keys",
                    "-t",
                    target.tmux_session_name(),
                    "-l",
                    text,
                ],
            )
            if proc.returncode != 0:
                return self._command_result(proc)
        if enter:
            proc = self._exec_in_container(
                target,
                ["tmux", "send-keys", "-t", target.tmux_session_name(), "C-m"],
            )
            return self._command_result(proc)
        return CommandResult(True, 0, "input sent\n", "", self.engine)

    def exec_tmux(
        self,
        target: TargetSpec,
        *,
        command: str,
        timeout_seconds: float,
        capture_lines: int,
    ) -> TmuxExecResult:
        marker = f"__EXOCORTEX_EXEC_{int(time.time() * 1000)}__"
        start_marker = f"{marker}:START"
        end_prefix = f"{marker}:END:"
        wrapped = (
            f"printf '{start_marker}\\n'; "
            f"{command}; "
            "__exocortex_status=$?; "
            f"printf '{end_prefix}%s\\n' \"$__exocortex_status\""
        )
        send_result = self.send_tmux_input(target, wrapped, enter=True)
        if not send_result.ok:
            raise RuntimeError(send_result.stderr or send_result.stdout or "tmux exec failed")

        deadline = time.monotonic() + timeout_seconds
        end_pattern = re.compile(rf"{re.escape(end_prefix)}(\d+)")
        capture = ""
        while time.monotonic() < deadline:
            capture = self.capture_tmux(target, lines=capture_lines)
            end_match = end_pattern.search(capture)
            if end_match:
                start_index = capture.rfind(start_marker)
                body_start = start_index + len(start_marker) if start_index >= 0 else 0
                output = capture[body_start:end_match.start()]
                return TmuxExecResult(
                    session_name=target.tmux_session_name(),
                    command=command,
                    marker=marker,
                    completed=True,
                    exit_code=int(end_match.group(1)),
                    output=output.strip("\n"),
                    capture=capture,
                )
            time.sleep(0.1)

        return TmuxExecResult(
            session_name=target.tmux_session_name(),
            command=command,
            marker=marker,
            completed=False,
            capture=capture,
        )

    def ensure_terminal_session(self, target: TargetSpec, paths: TargetPaths) -> TerminalContext:
        tmux_result = self.ensure_tmux_session(target, paths)
        if not tmux_result.ok:
            raise RuntimeError(tmux_result.stderr or tmux_result.stdout or "Failed to start tmux")
        return TerminalContext(
            target_id=target.name,
            container_name=target.container_name(),
            tmux_session=target.tmux_session_name(),
            container_engine=self.engine,
        )

    def _host_aliases(self) -> list[str]:
        aliases = ["host.docker.internal:host-gateway"]
        if self.engine == "podman":
            aliases.append("host.containers.internal:host-gateway")
        return aliases

    def _exec_in_container(
        self,
        target: TargetSpec,
        args: list[str],
    ) -> subprocess.CompletedProcess[str]:
        if self.engine is None:
            return self._completed_failure("No container engine available.")
        return self._run([self.engine, "exec", target.container_name(), *args])

    @staticmethod
    def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(args, capture_output=True, text=True)

    def _unavailable_result(self) -> CommandResult:
        return CommandResult(False, 127, "", "No supported container engine found.", "runtime")

    @staticmethod
    def _completed_failure(message: str) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=[], returncode=127, stdout="", stderr=message)

    def _command_result(self, proc: subprocess.CompletedProcess[str]) -> CommandResult:
        return CommandResult(
            ok=proc.returncode == 0,
            exit_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            source=self.engine or "runtime",
        )


class VMHostDriver:
    """Deferred host-driver seam for the later VM-native runtime."""

    def inspect_target(self, target: TargetSpec) -> TargetContainerInfo:
        return TargetContainerInfo(name=target.container_name(), engine="vm", status="deferred")

    def inspect_tmux(self, target: TargetSpec) -> TargetTmuxInfo:
        return TargetTmuxInfo(session_name=target.tmux_session_name(), status="deferred")

    def start_target(self, target: TargetSpec, paths: TargetPaths) -> CommandResult:
        return CommandResult(False, 2, "", "VM host driver is not implemented yet.", "vm")

    def stop_target(self, target: TargetSpec) -> CommandResult:
        return CommandResult(False, 2, "", "VM host driver is not implemented yet.", "vm")

    def remove_target(
        self,
        target: TargetSpec,
        paths: TargetPaths,
        *,
        purge_state: bool = False,
    ) -> CommandResult:
        return CommandResult(False, 2, "", "VM host driver is not implemented yet.", "vm")

    def ensure_tmux_session(self, target: TargetSpec, paths: TargetPaths) -> CommandResult:
        return CommandResult(False, 2, "", "VM host driver is not implemented yet.", "vm")

    def kill_tmux_session(self, target: TargetSpec) -> CommandResult:
        return CommandResult(False, 2, "", "VM host driver is not implemented yet.", "vm")

    def capture_tmux(self, target: TargetSpec, *, lines: int) -> str:
        raise RuntimeError("VM host driver is not implemented yet.")

    def send_tmux_input(self, target: TargetSpec, text: str, *, enter: bool) -> CommandResult:
        return CommandResult(False, 2, "", "VM host driver is not implemented yet.", "vm")

    def exec_tmux(
        self,
        target: TargetSpec,
        *,
        command: str,
        timeout_seconds: float,
        capture_lines: int,
    ) -> TmuxExecResult:
        raise RuntimeError("VM host driver is not implemented yet.")

    def ensure_terminal_session(self, target: TargetSpec, paths: TargetPaths) -> TerminalContext:
        raise RuntimeError("VM host driver is not implemented yet.")
