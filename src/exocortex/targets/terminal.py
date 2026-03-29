"""PTY-backed terminal bridge for tmux-attached target sessions."""

from __future__ import annotations

import asyncio
import json
import os
import pty
import select
import signal
import struct
import termios
import time
from contextlib import suppress
from dataclasses import dataclass

from fastapi import WebSocket
from fastapi.websockets import WebSocketDisconnect

from exocortex.targets.host import TerminalContext

PING_STATUS = {"type": "status", "state": "heartbeat"}


@dataclass
class TerminalBridgeConfig:
    """Runtime options for the terminal bridge."""

    idle_timeout: float = 600.0
    heartbeat_interval: float = 30.0
    read_chunk_size: int = 4096


class TerminalBridge:
    """Proxy bytes between a PTY-backed process and a websocket client."""

    def __init__(
        self,
        context: TerminalContext,
        *,
        config: TerminalBridgeConfig | None = None,
    ) -> None:
        self.context = context
        self.command = list(context.command or self._default_command(context))
        self.config = config or TerminalBridgeConfig()

        self._master_fd: int | None = None
        self._slave_fd: int | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._closed = asyncio.Event()
        self._last_client_activity = time.monotonic()

    async def run(self, websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.send_json({"type": "status", "state": "connecting"})
        try:
            await self._spawn_process()
        except Exception as exc:
            await websocket.send_json(
                {"type": "error", "message": f"Failed to launch terminal: {exc}"}
            )
            await websocket.close(code=1011)
            return

        await websocket.send_json({"type": "status", "state": "ready"})

        tasks = [
            asyncio.create_task(self._pump_output(websocket)),
            asyncio.create_task(self._consume_input(websocket)),
            asyncio.create_task(self._watch_process(websocket)),
            asyncio.create_task(self._idle_watchdog(websocket)),
        ]

        try:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                error = task.exception()
                if error is not None:
                    await websocket.send_json(
                        {"type": "error", "message": f"Terminal bridge interrupted: {error}"}
                    )
                    await websocket.close(code=1011)
                    break
        finally:
            await self._cleanup()

    async def _spawn_process(self) -> None:
        master_fd, slave_fd = pty.openpty()
        self._master_fd = master_fd
        self._slave_fd = slave_fd

        env = os.environ.copy()
        env.setdefault("TERM", "tmux-256color")
        env.setdefault("LANG", "C.UTF-8")
        env.setdefault("LC_ALL", "C.UTF-8")

        self._process = await asyncio.create_subprocess_exec(
            *self.command,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            env=env,
        )

    async def _pump_output(self, websocket: WebSocket) -> None:
        if self._master_fd is None:
            return
        while not self._closed.is_set():
            data = await asyncio.to_thread(
                self._read_chunk,
                self._master_fd,
                max(64, self.config.read_chunk_size),
            )
            if data is None:
                continue
            if isinstance(data, bool):
                break
            if not data:
                break
            text = data.decode("utf-8", errors="ignore")
            if text:
                await websocket.send_json({"type": "output", "data": text})

    async def _consume_input(self, websocket: WebSocket) -> None:
        if self._master_fd is None:
            return

        while not self._closed.is_set():
            try:
                message = await websocket.receive_text()
            except (RuntimeError, WebSocketDisconnect):
                break

            self._last_client_activity = time.monotonic()
            try:
                payload = json.loads(message)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "Invalid JSON payload."})
                continue

            msg_type = payload.get("type")
            if msg_type == "input":
                data = payload.get("data", "")
                if not isinstance(data, str):
                    await websocket.send_json(
                        {"type": "error", "message": "Invalid input payload."}
                    )
                    continue
                await asyncio.to_thread(os.write, self._master_fd, data.encode("utf-8"))
            elif msg_type == "resize":
                cols = payload.get("cols")
                rows = payload.get("rows")
                if isinstance(cols, int) and isinstance(rows, int):
                    self._set_winsize(rows, cols)
                    await self._request_redraw()
            elif msg_type == "heartbeat":
                await websocket.send_json(PING_STATUS)
            else:
                await websocket.send_json({"type": "error", "message": "Unknown message type."})

    async def _watch_process(self, websocket: WebSocket) -> None:
        if self._process is None:
            return
        await self._process.wait()
        self._closed.set()
        await websocket.send_json(
            {"type": "status", "state": "terminated", "code": self._process.returncode}
        )
        with suppress(RuntimeError):
            await websocket.close(code=1000)

    async def _idle_watchdog(self, websocket: WebSocket) -> None:
        if self.config.idle_timeout <= 0:
            return
        interval = max(5.0, self.config.heartbeat_interval)
        while not self._closed.is_set():
            await asyncio.sleep(interval)
            if self._closed.is_set():
                break
            elapsed = time.monotonic() - self._last_client_activity
            if elapsed >= self.config.idle_timeout:
                await websocket.send_json(
                    {"type": "status", "state": "idle-timeout", "elapsed": elapsed}
                )
                await websocket.close(code=4000)
                self._closed.set()
                break

    async def _cleanup(self) -> None:
        self._closed.set()
        if self._process and self._process.returncode is None:
            self._process.send_signal(signal.SIGTERM)
            try:
                await asyncio.wait_for(self._process.wait(), timeout=2.0)
            except TimeoutError:
                self._process.kill()
                await self._process.wait()
        if self._master_fd is not None:
            with suppress(OSError):
                os.close(self._master_fd)
        if self._slave_fd is not None:
            with suppress(OSError):
                os.close(self._slave_fd)

    def _set_winsize(self, rows: int, cols: int) -> None:
        if self._slave_fd is None:
            return
        rows = max(1, rows)
        cols = max(1, cols)
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        try:
            import fcntl

            fcntl.ioctl(self._slave_fd, termios.TIOCSWINSZ, winsize)
        except OSError:
            pass

    async def _request_redraw(self) -> None:
        if self._master_fd is None:
            return
        with suppress(OSError):
            await asyncio.to_thread(os.write, self._master_fd, b"\x0c")

    @staticmethod
    def _read_chunk(fd: int, chunk_size: int) -> bytes | None | bool:
        try:
            readable, _, _ = select.select([fd], [], [], 0.25)
        except OSError:
            return False
        if not readable:
            return None
        try:
            return os.read(fd, chunk_size)
        except OSError:
            return False

    @staticmethod
    def _default_command(context: TerminalContext) -> list[str]:
        if context.container_engine is None:
            raise RuntimeError("No container engine available for terminal attach.")
        return [
            context.container_engine,
            "exec",
            "-it",
            "-e",
            "TERM=tmux-256color",
            "-e",
            "LANG=C.UTF-8",
            "-e",
            "LC_ALL=C.UTF-8",
            context.container_name,
            "tmux",
            "attach-session",
            "-t",
            context.tmux_session,
        ]
