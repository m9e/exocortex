"""Manifest loading and validation for worker-fabric targets."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from exocortex.targets.models import TargetSpec

DEFAULT_LOCAL_MANIFEST = Path("config/targets.local.toml")
DEFAULT_EXAMPLE_MANIFEST = Path("config/targets.example.toml")


class TargetRegistry:
    """A validated collection of worker-fabric targets."""

    def __init__(
        self,
        *,
        repo_root: Path,
        manifest_path: Path,
        targets: dict[str, TargetSpec],
    ) -> None:
        self.repo_root = repo_root.resolve(strict=False)
        self.manifest_path = manifest_path.resolve(strict=False)
        self._targets = dict(sorted(targets.items()))

    @classmethod
    def load_default(
        cls,
        repo_root: Path,
        manifest_path: Path | None = None,
    ) -> TargetRegistry:
        repo_root = repo_root.resolve(strict=False)
        chosen_path = cls._resolve_manifest_path(repo_root, manifest_path)
        if not chosen_path.exists():
            return cls(repo_root=repo_root, manifest_path=chosen_path, targets={})

        data = tomllib.loads(chosen_path.read_text())
        raw_targets = data.get("targets", {})
        if not isinstance(raw_targets, dict):
            raise ValueError("Target manifest must contain a [targets] table.")

        parsed_targets: dict[str, TargetSpec] = {}
        for key, raw_value in raw_targets.items():
            if not isinstance(raw_value, dict):
                raise ValueError(f"Target entry '{key}' must be a table.")
            payload = dict(raw_value)
            payload.setdefault("name", key)
            target = TargetSpec.model_validate(payload)
            target.validate_source_policy(repo_root)
            parsed_targets[target.name] = target

        return cls(repo_root=repo_root, manifest_path=chosen_path, targets=parsed_targets)

    @staticmethod
    def _resolve_manifest_path(repo_root: Path, explicit: Path | None) -> Path:
        if explicit is not None:
            return explicit.expanduser()
        env_path = os.environ.get("EXOCORTEX_TARGETS_FILE")
        if env_path:
            return Path(env_path).expanduser()
        local_path = repo_root / DEFAULT_LOCAL_MANIFEST
        if local_path.exists():
            return local_path
        return repo_root / DEFAULT_EXAMPLE_MANIFEST

    def list(self) -> list[TargetSpec]:
        return list(self._targets.values())

    def get(self, name: str) -> TargetSpec | None:
        return self._targets.get(name)
