# Worker Fabric Bootstrap Roadmap

## Objective

Bootstrap the initial worker-fabric control plane around exocortex without polluting parent git state or collapsing the upstream runtimes into this repo.

Manual baby-step validation is tracked in [manual-validation.md](/Users/matt/code/exocortex/exocortex/docs/bootstrap/manual-validation.md).
Target-specific proof-of-life guides live in [docs/howto/README.md](/Users/matt/code/exocortex/exocortex/docs/howto/README.md).

## Phase 1

- Add repo bootstrap docs and operator rules.
- Introduce manifest-driven target registry.
- Implement container-first host driver with tmux-backed lifecycle primitives.
- Expose thin CLI and REST/WebSocket control surfaces.
- Keep all runtime artifacts under ignored local state directories.

## Phase 2

- Stand up repeatable proof-of-life flows for OpenClaw, Gas Town, and DeerFlow.
- Make Gas Town easy to enter and inspect directly in a disposable workspace.
- Validate that proof-of-life flows do not require parent-repo git mutations.

## Phase 3

- Add substrate discovery and status reporting from the executive core.
- Expose health, proof, and runtime metadata through a unified registry.
- Prepare the host-driver seam for later VM-native execution on Linux.

## Ground Rules

- Forks are sibling clones under `/Users/matt/code/exocortex/`.
- No submodules.
- No tracked nested repos.
- `uv run ...` is the canonical Python invocation path.
- Integration tests matter more than superficial unit coverage for harness behavior.
