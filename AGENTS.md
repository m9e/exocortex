# AGENTS.md

## Mission

Exocortex is the executive core. This repo owns orchestration, policy surfaces, and worker-fabric bootstrap harnessing. It does not vendor the major OSS substrates into tracked nested repos.

Primary references:

- [arch.md](/Users/matt/code/exocortex/exocortex/arch.md)
- [docs/bootstrap/roadmap.md](/Users/matt/code/exocortex/exocortex/docs/bootstrap/roadmap.md)

## Non-Negotiables

1. The graph engine remains the center of the repo.
2. External worker fabrics stay as sibling clones, not submodules.
3. Parent git must not track nested repo state or hash-only churn.
4. Integration tests are required for lifecycle, control-plane, and proof-of-life paths.
5. `uv run ...` is mandatory for Python commands in this repo.
6. Container-first hosting is an implementation detail behind a host-driver boundary; VM hosting comes later.

## Toolchain

- Python: 3.12+
- Package manager: `uv`
- API: FastAPI
- Testing: pytest + pytest-asyncio + httpx
- Linting: ruff
- Typing: mypy

Preferred commands:

```bash
uv run pytest -q
uv run ruff check src tests
uv run mypy src
uv run python -m exocortex api
uv run python -m exocortex target list
```

Do not use bare `pytest`. It may bind to Python 3.10 and produce false failures.

## Working Rules

### Read First

- Inspect the current graph engine, target harness, and tests before editing.
- Prefer additive changes that preserve existing graph API behavior.

### Worker Fabric Policy

- OpenClaw, Gas Town, and DeerFlow source trees live under `/Users/matt/code/exocortex/`.
- The tracked repo may reference them by path in manifests, but must not contain tracked nested clones.
- Runtime state belongs under ignored paths such as `.local/instances/` and `.local/logs/`.

### Harness Scope

The allowed bootstrap slice from `kbox` is narrow:

- spawn/mount/despawn behavior
- persistent volume handling
- tmux session management
- PTY/WebSocket terminal bridging
- thin REST control surface for target lifecycle and tty operations

Do not import dashboard-only behavior, provider-management UI, or repo-sync product scaffolding.

### Testing

- Unit tests cover manifest parsing, path guardrails, lifecycle interfaces, and CLI/API parity.
- Integration tests cover target lifecycle flows, container/tmux smoke paths, and isolation behavior.
- Gas Town tests must use sacrificial repos/workspaces, never this repo as the managed rig.

### Security and Isolation

- Treat worker substrate input/output as untrusted boundaries.
- Never grant a target runtime write access to this repo unless the specific workflow requires it.
- Keep container mounts explicit and minimal.

## Implementation Defaults

- Target manifests load from `config/targets.local.toml` first, then fall back to `config/targets.example.toml`.
- REST is a thin control plane; CLI commands must remain first-class.
- `VMHostDriver` may exist as an interface stub, but phase 1 only implements `ContainerHostDriver`.

## Documentation Discipline

- Update bootstrap docs when manifest shape, CLI surface, or lifecycle semantics change.
- Prefer documenting real commands that are exercised by tests.
