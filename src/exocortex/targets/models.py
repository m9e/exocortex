"""Manifest, runtime, and API-facing models for worker-fabric targets."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

_RUNTIME_IMAGES = {
    "openclaw": "node:24-bookworm",
    "gastown": "golang:1.25-bookworm",
    "deerflow": "python:3.12-bookworm",
}


class TargetSpec(BaseModel):
    """A configured worker-fabric target loaded from the manifest."""

    name: str
    path: Path
    origin: str
    upstream: str
    branch: str
    runtime: str
    proof_command: str
    health_command: str
    state_root: Path
    image: str | None = None
    container_workdir: str = "/workspace"

    @field_validator("path", "state_root", mode="before")
    @classmethod
    def _coerce_path(cls, value: str | Path) -> Path:
        return Path(value).expanduser()

    def resolved_source_path(self) -> Path:
        return self.path.resolve(strict=False)

    def resolved_state_root(self, repo_root: Path) -> Path:
        state_root = self.state_root.expanduser()
        if state_root.is_absolute():
            return state_root.resolve(strict=False)
        return (repo_root / state_root).resolve(strict=False)

    def validate_source_policy(self, repo_root: Path) -> None:
        source_path = self.resolved_source_path()
        repo_root = repo_root.resolve(strict=False)
        if source_path == repo_root or source_path.is_relative_to(repo_root):
            raise ValueError(
                f"Target '{self.name}' source path must live outside the repo root: {source_path}"
            )

    def runtime_image(self) -> str:
        return self.image or _RUNTIME_IMAGES.get(self.runtime, "debian:bookworm")

    def container_name(self) -> str:
        return f"exocortex-target-{self.name}"

    def tmux_session_name(self) -> str:
        return f"exocortex-{self.name}"


class TargetPaths(BaseModel):
    """Resolved filesystem paths for a target."""

    source: Path
    state_root: Path
    logs_dir: Path


class TargetContainerInfo(BaseModel):
    """Observed container runtime status for a target."""

    name: str
    engine: str | None = None
    status: str = Field(default="unavailable")
    running: bool = Field(default=False)
    image: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    exit_code: int | None = None


class TargetTmuxInfo(BaseModel):
    """Observed tmux runtime status for a target."""

    session_name: str
    status: str = Field(default="absent")
    attached: bool | None = None


class TargetSummary(BaseModel):
    """Lightweight target listing used by CLI and API responses."""

    id: str
    runtime: str
    source_exists: bool
    manifest_path: Path
    container_status: str
    tmux_status: str


class TargetDetail(BaseModel):
    """Detailed target view used by the API."""

    id: str
    runtime: str
    origin: str
    upstream: str
    branch: str
    proof_command: str
    health_command: str
    manifest_path: Path
    paths: TargetPaths
    source_exists: bool
    container: TargetContainerInfo
    tmux: TargetTmuxInfo
