"""Tests for target manifest loading and source-path guardrails."""

from __future__ import annotations

from pathlib import Path

import pytest

from exocortex.targets.registry import TargetRegistry


def _write_manifest(manifest_path: Path, source_path: Path) -> None:
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


class TestTargetRegistry:
    def test_loads_manifest_and_resolves_state_root(self, tmp_path: Path) -> None:
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        source_path = tmp_path / "openclaw"
        source_path.mkdir()
        manifest_path = repo_root / "config" / "targets.example.toml"
        _write_manifest(manifest_path, source_path)

        registry = TargetRegistry.load_default(repo_root)
        target = registry.get("openclaw")

        assert target is not None
        assert registry.manifest_path == manifest_path.resolve(strict=False)
        assert target.resolved_source_path() == source_path.resolve(strict=False)
        assert target.resolved_state_root(repo_root) == (
            repo_root / ".local" / "instances" / "openclaw"
        ).resolve(strict=False)
        assert target.runtime_image() == "node:24-bookworm"

    def test_rejects_source_path_inside_repo_root(self, tmp_path: Path) -> None:
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        nested_source = repo_root / "openclaw"
        nested_source.mkdir()
        manifest_path = repo_root / "config" / "targets.example.toml"
        _write_manifest(manifest_path, nested_source)

        with pytest.raises(ValueError, match="outside the repo root"):
            TargetRegistry.load_default(repo_root)
