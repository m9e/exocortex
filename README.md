# Exocortex

Exocortex is the executive core for a broader worker-fabric system.

The current repository owns:

- the graph execution engine
- the API and control plane for that engine
- the bootstrap harness for external worker fabrics

The current repository lives at `/Users/matt/code/exocortex/exocortex`.

The major upstream worker substrates are expected as sibling clones under the parent workspace root:

- `/Users/matt/code/exocortex/openclaw`
- `/Users/matt/code/exocortex/gastown`
- `/Users/matt/code/exocortex/deer-flow`

## Architecture

The design center is documented in [arch.md](/Users/matt/code/exocortex/exocortex/arch.md).

Operating model:

- exocortex is the executive core
- OpenClaw is the ghost/runtime substrate
- Gas Town is the repo-swarm substrate
- DeerFlow is the open-ended research substrate

Bootstrap work is tracked in [docs/bootstrap/roadmap.md](/Users/matt/code/exocortex/exocortex/docs/bootstrap/roadmap.md).

## Toolchain

Use `uv` and Python 3.12 for all repo work.

Examples:

```bash
uv run pytest -q
uv run pytest tests/unit
uv run pytest tests/integration
uv run python -m exocortex api
uv run python -m exocortex target list
```

Do not use bare `pytest` here. On this machine it resolves to Python 3.10 and fails on `StrEnum` and `datetime.UTC`.

## Repo Layout

```text
src/exocortex/core/       Graph engine and state management
src/exocortex/api/        FastAPI routes and app wiring
src/exocortex/agents/     CLI delegation helpers
src/exocortex/targets/    Worker-fabric registry, adapters, hosting, tty bridge
config/                   Target manifests
docs/bootstrap/           Bootstrap milestones and operating notes
tests/                    Unit and integration tests
```

## Target Harness

The target harness is additive. It provides:

- a manifest-driven registry of worker fabrics
- sibling-path guardrails so nested tracked repos are rejected
- a thin container host driver
- tmux-backed command and terminal access
- CLI and REST endpoints for lifecycle and proof-of-life actions

Configured targets are listed from `config/targets.local.toml` when present, otherwise `config/targets.example.toml`.

## Commands

### Graph engine/API

```bash
uv run python -m exocortex api
```

### Target harness

```bash
uv run python -m exocortex target list
uv run python -m exocortex target show openclaw
uv run python -m exocortex target health openclaw
uv run python -m exocortex target proof openclaw
```

### Quality

```bash
uv run pytest -q
uv run ruff check src tests
uv run mypy src
```
