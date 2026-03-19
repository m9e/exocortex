# AGENTS.md — Exocortex Development Standards

## Project Overview

Exocortex is an external cognitive system built around a graph execution engine.
Architecture spec: `docs/superpowers/specs/2026-03-18-exocortex-architecture-design.md`

## Stack

- **Language**: Python 3.12+
- **Package manager**: uv
- **Data models**: Pydantic v2 (strict mode, no `extra="allow"`)
- **API framework**: FastAPI + uvicorn
- **Database**: SQLite (aiosqlite, WAL mode, single-writer queue)
- **Testing**: pytest + pytest-asyncio + httpx
- **Linting**: ruff
- **Type checking**: mypy (strict)

## Commands

```bash
uv run pytest                    # Run all tests
uv run pytest tests/unit         # Unit tests only
uv run pytest tests/integration  # Integration tests only
uv run ruff check src tests      # Lint
uv run ruff format src tests     # Format
uv run mypy src                  # Type check
uv run python -m exocortex       # Run the service
```

## Coding Standards

### Models
- All Pydantic models use `model_config = ConfigDict(strict=True)` unless there's a documented reason not to
- All state schemas define explicit fields — no dynamic extension
- Parallel-writable fields must declare a `ReducerType`

### Functions
- Max 30 lines per function
- Max 200 lines per file
- Type hints on all public functions
- Docstrings on public API only (not internal helpers)

### Testing
- Every feature has unit tests
- Integration tests for anything that crosses module boundaries
- Test as you go, not at the end
- Arrange/Act/Assert structure

### Async
- All I/O operations are async
- Use `asyncio.TaskGroup` for parallel execution (Python 3.11+)
- SQLite writes go through the single writer queue — never write directly

### Security
- No `eval()`, `exec()`, or dynamic code execution anywhere
- Edge conditions use declarative `ConditionSpec` only
- Handler paths validated against allowlist before execution
- All agent output size-limited before deserialization

### Git
- Small, focused commits
- Message format: `<verb> <what>` (e.g., "Add graph node execution", "Fix reducer merge conflict")
- Never reference AI tools in commits

## Architecture Invariants

These are non-negotiable:

1. **Graph engine is the center** — everything else injects into it
2. **Forced hooks cannot be bypassed** — security and audit hooks run on every node
3. **Mutations are additive only** — no edge/node removal from running graphs
4. **Capabilities, not trust levels** — authorization is per-capability, per-domain
5. **State schemas are strict** — every field is explicitly declared
6. **Conditions are declarative** — no arbitrary code in edge conditions
7. **Protected edges are immutable** — cannot be rewired by mutations
8. **Budget enforcement is mandatory** — every run has resource limits

## File Organization

```
src/exocortex/
├── core/           # Graph engine, state, conditions, checkpoints
├── injection/      # Hook system (forced + opt-in)
├── agents/         # Agent identity, registry, CLI wrappers
├── memory/         # Memory fabric, tiers, objectives
├── compute/        # Compute discovery, NATS bus
├── security/       # Capabilities, audit, DLQ, sandbox
└── api/            # FastAPI routes and middleware
```

## Implementation Phases

Phase 1 (current): Graph engine core — graph definition, node execution, state/reducers, checkpoints, hooks, budget, cycles
Phase 2: Agent runtime — identity, registry, CLI delegation, parallel execution, fan-out, HITL
Phase 3: Memory + objectives — tiered storage, objective graph
Phase 4: Compute + bus — discovery, NATS, multi-host
Phase 5: Security hardening — full capability auth, audit trail, content pipeline, sandboxing
