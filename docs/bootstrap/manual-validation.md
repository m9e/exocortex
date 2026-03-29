# Manual Validation Plans

Upstream steps below were checked against official project docs on March 27, 2026.

References:

- OpenClaw getting started: <https://docs.openclaw.ai/start/getting-started>
- OpenClaw source build notes: <https://github.com/openclaw/openclaw/blob/main/README.md>
- Gas Town README: <https://github.com/steveyegge/gastown/blob/main/README.md>
- DeerFlow install instructions: <https://github.com/bytedance/deer-flow/blob/main/Install.md>

## Why This Exists

The current exocortex harness is intentionally narrow.

- `target health` and `target proof` run the configured command on the host in the sibling clone.
- `target start` creates an idle container with the source mounted at `/workspace` and the target state mounted at `/runtime`.
- `target tmux up` ensures a tmux session exists inside that container.
- The harness does not yet auto-bootstrap the full upstream app inside the container.

That means the right early-phase manual test shape is:

1. prove the upstream target works natively from its sibling clone
2. prove exocortex can host and inspect that target cleanly
3. prove parent git state stays free of nested-repo or gitlink noise

## Shared Guardrails

Expected source layout:

- `/Users/matt/code/exocortex`
- `/Users/matt/code/exocortex/exocortex`
- `/Users/matt/code/exocortex/openclaw`
- `/Users/matt/code/exocortex/gastown`
- `/Users/matt/code/exocortex/deer-flow`

Runtime state should stay under ignored repo-local paths such as:

- `/Users/matt/code/exocortex/exocortex/.local/instances/openclaw`
- `/Users/matt/code/exocortex/exocortex/.local/instances/gastown`
- `/Users/matt/code/exocortex/exocortex/.local/instances/deerflow`

Before and after every target exercise, run:

```bash
git -C /Users/matt/code/exocortex/exocortex submodule status
git -C /Users/matt/code/exocortex/exocortex ls-files --stage | awk '$1 == 160000 { print $0 }'
git -C /Users/matt/code/exocortex/exocortex status --short
```

Expected result:

- `git submodule status` prints nothing
- `git ls-files --stage ... 160000` prints nothing
- `git status --short` shows no new parent-repo changes caused by the target exercise

Optional ignored-state check:

```bash
git -C /Users/matt/code/exocortex/exocortex status --short --ignored .local config/targets.local.toml
```

Expected result:

- ignored runtime state may show up as ignored
- nothing under `.local/` or `config/targets.local.toml` should become tracked

## Recommended Order

Run these in this order:

1. exocortex shim smoke
2. OpenClaw
3. Gas Town
4. DeerFlow

That sequence moves from lowest-risk harness plumbing to the targets with more external prerequisites.

## Exocortex Shim Smoke

Purpose:

- prove container spawn, source mount, runtime mount, tmux bring-up, command execution, capture, stop, and cleanup
- prove the parent repo does not gain submodule or gitlink state

This path was exercised locally against a disposable manifest using `python:3.12-slim`.

Notes:

- the default OpenClaw runtime image is `node:24-bookworm`
- if that image is not already local, the first run will pull it
- for a pure shim smoke, use a locally available image first

### Steps

1. Create a disposable target root outside the repo.

```bash
tmpdir="$(mktemp -d /tmp/exocortex-shim.XXXXXX)"
mkdir -p "$tmpdir/source" "$tmpdir/config"
printf '{"name":"shim-openclaw"}\n' > "$tmpdir/source/package.json"
cat > "$tmpdir/config/targets.toml" <<EOF
[targets.openclaw]
name = "openclaw"
path = "$tmpdir/source"
origin = "git@github.com:matt/openclaw.git"
upstream = "https://github.com/openclaw/openclaw.git"
branch = "main"
runtime = "openclaw"
proof_command = "printf proof"
health_command = "printf health"
state_root = "$tmpdir/state"
EOF
```

2. Prove manifest and host-side commands work.

```bash
EXOCORTEX_TARGETS_FILE="$tmpdir/config/targets.toml" \
  uv run python -m exocortex target show openclaw

EXOCORTEX_TARGETS_FILE="$tmpdir/config/targets.toml" \
  uv run python -m exocortex target health openclaw

EXOCORTEX_TARGETS_FILE="$tmpdir/config/targets.toml" \
  uv run python -m exocortex target proof openclaw
```

Expected result:

- `show` reports the disposable manifest path and source path
- `health` prints `health`
- `proof` prints `proof`

3. Start the runtime container with a local image.

```bash
EXOCORTEX_TARGETS_FILE="$tmpdir/config/targets.toml" \
  uv run python -m exocortex target start openclaw --image python:3.12-slim
```

Expected result:

- stdout is a container id

4. Bring up tmux in the container.

```bash
EXOCORTEX_TARGETS_FILE="$tmpdir/config/targets.toml" \
  uv run python -m exocortex target tmux up openclaw --image python:3.12-slim
```

Expected result:

- exit code `0`
- tmux is installed in the container if it was absent

5. Verify mounts from inside the tmux session.

```bash
EXOCORTEX_TARGETS_FILE="$tmpdir/config/targets.toml" \
  uv run python -m exocortex target tmux exec openclaw \
  'pwd && ls -la /workspace && ls -la /runtime && echo shim-ok'
```

Expected result:

- `pwd` prints `/workspace`
- `package.json` is visible in `/workspace`
- `/runtime` exists
- output includes `shim-ok`

6. Verify mount wiring from Docker.

```bash
docker inspect exocortex-target-openclaw \
  --format '{{.State.Status}}|{{range .Mounts}}{{.Source}}=>{{.Destination}};{{end}}'
```

Expected result:

- container status is `running`
- one mount ends with `=>/workspace`
- one mount ends with `=>/runtime`

7. Capture the current tmux pane.

```bash
EXOCORTEX_TARGETS_FILE="$tmpdir/config/targets.toml" \
  uv run python -m exocortex target tmux capture openclaw --lines 80
```

Expected result:

- captured pane shows the command from step 5 and its output

8. Stop and remove the container, then purge disposable state.

```bash
EXOCORTEX_TARGETS_FILE="$tmpdir/config/targets.toml" \
  uv run python -m exocortex target stop openclaw

EXOCORTEX_TARGETS_FILE="$tmpdir/config/targets.toml" \
  uv run python -m exocortex target rm openclaw --purge-state
```

Expected result:

- `stop` prints the container name
- `rm --purge-state` prints the container name and the purged state-root path

9. Run the shared guardrail commands.

Success means:

- the shim works end to end
- no submodule or gitlink state appears in the parent repo

## OpenClaw Manual Plan

Purpose:

- prove the sibling clone builds and answers basic CLI commands
- prove the exocortex harness can host that clone cleanly
- defer real channel integration until after the basic runtime path is reliable

### Preconditions

- sibling clone exists at `/Users/matt/code/exocortex/openclaw`
- Node.js 24 is preferred and Node.js 22.14+ is supported
- `pnpm` is available

### Steps

1. Confirm the clone is a sibling repo, not nested in exocortex.

```bash
git -C /Users/matt/code/exocortex/openclaw remote -v
git -C /Users/matt/code/exocortex/openclaw status --short
```

Expected result:

- `origin` points at your fork
- `upstream` points at `openclaw/openclaw`
- the sibling clone is independently healthy

2. Run the native source bootstrap from the sibling clone.

```bash
cd /Users/matt/code/exocortex/openclaw
pnpm install
pnpm ui:build
pnpm build
pnpm openclaw --help
pnpm openclaw doctor
```

Expected result:

- install and build succeed
- `pnpm openclaw --help` prints CLI help
- `pnpm openclaw doctor` reports either success or concrete configuration warnings rather than a crash

3. Optional native gateway proof.

```bash
cd /Users/matt/code/exocortex/openclaw
pnpm openclaw onboard --install-daemon
openclaw gateway status
```

Expected result:

- onboarding completes once you provide model-provider details
- `openclaw gateway status` reports the gateway on port `18789`

4. Check the exocortex manifest view before starting the harness.

```bash
uv run python -m exocortex target show openclaw
uv run python -m exocortex target health openclaw
uv run python -m exocortex target proof openclaw
```

Expected result:

- manifest paths point at the sibling clone
- `health` runs `pnpm openclaw --help` on the host
- `proof` runs `pnpm openclaw doctor` on the host

5. Prove the harness can host the OpenClaw clone.

```bash
uv run python -m exocortex target start openclaw --image node:24-bookworm
uv run python -m exocortex target tmux up openclaw --image node:24-bookworm
uv run python -m exocortex target tmux exec openclaw \
  'node --version && pwd && ls -la /workspace | head && ls -la /runtime'
```

Expected result:

- the container starts
- tmux comes up
- `/workspace` is the mounted sibling clone
- `/runtime` is the target-local ignored state root

6. Optional container-side build proof.

```bash
uv run python -m exocortex target tmux exec openclaw \
  'cd /workspace && pnpm install && pnpm ui:build && pnpm build'
```

Expected result:

- the container can build from the mounted source

Use this only after the native source bootstrap is already green. It is slower and can be noisy on first run.

7. Optional long-running gateway proof under the harness.

```bash
uv run python -m exocortex target tmux exec openclaw \
  'cd /workspace && pnpm gateway:watch'
```

Expected result:

- the tmux pane shows the dev gateway starting rather than exiting immediately

Because this is long-running, use `target tmux capture openclaw` to inspect it instead of expecting the CLI call to return quickly.

8. Run the shared guardrail commands.

Success means:

- OpenClaw works from the sibling clone
- the harness can host and inspect it without nesting repo state into exocortex

## Gas Town Manual Plan

Purpose:

- learn the system hands-on in a disposable town
- prove worktrees, hooks, and crew state stay isolated from this repo and from the canonical sibling clone
- avoid using exocortex or the sibling `gastown` source clone as the rig target

### Preconditions

- sibling clone exists at `/Users/matt/code/exocortex/gastown`
- prerequisites from the official README are present:
  - Go 1.25+
  - Git 2.25+
  - Dolt 1.82.4+
  - beads `bd` 0.55.4+
  - sqlite3
  - tmux 3.0+
  - at least one agent runtime such as Codex or Claude

### Steps

1. Verify prerequisites and source health.

```bash
go version
git --version
dolt --version
bd --version
sqlite3 --version
tmux -V
codex --version
git -C /Users/matt/code/exocortex/gastown remote -v
git -C /Users/matt/code/exocortex/gastown status --short
```

Expected result:

- prerequisites exist
- the sibling clone is separate from exocortex

2. Build a local `gt` binary from the sibling clone if you do not already have a good install.

```bash
cd /Users/matt/code/exocortex/gastown
go build -o ./bin/gt ./cmd/gt
./bin/gt --help
```

Expected result:

- the binary builds and prints help

3. Prepare an isolated town root and a sacrificial rig repo.

```bash
mkdir -p /Users/matt/code/exocortex/exocortex/.local/instances/gastown/repos/smoke-repo
mkdir -p /Users/matt/code/exocortex/exocortex/.local/instances/gastown/town

cd /Users/matt/code/exocortex/exocortex/.local/instances/gastown/repos/smoke-repo
git init -b main
printf '# gastown smoke repo\n' > README.md
git add README.md
git commit -m 'initial commit'
```

Expected result:

- the rig target is a disposable git repo
- it is not the exocortex repo
- it is not the canonical sibling `gastown` source clone

4. Initialize a disposable town.

```bash
cd /Users/matt/code/exocortex/gastown
PATH="$PWD/bin:$PATH" gt install /Users/matt/code/exocortex/exocortex/.local/instances/gastown/town --git
cd /Users/matt/code/exocortex/exocortex/.local/instances/gastown/town
PATH="/Users/matt/code/exocortex/gastown/bin:$PATH" gt config agent list
```

Expected result:

- the town initializes
- agent presets are listed

5. Add the sacrificial rig and create your crew workspace.

```bash
PATH="/Users/matt/code/exocortex/gastown/bin:$PATH" \
  gt rig add smoke /Users/matt/code/exocortex/exocortex/.local/instances/gastown/repos/smoke-repo

PATH="/Users/matt/code/exocortex/gastown/bin:$PATH" \
  gt crew add matt --rig smoke
```

Expected result:

- the rig exists under the disposable town
- the crew workspace is created under the disposable town

If your build of `gt rig add` rejects a local repo path, switch this step to a sacrificial remote repository URL. Do not point it at exocortex or the canonical sibling clone.

6. Inspect where Gas Town put things.

```bash
find /Users/matt/code/exocortex/exocortex/.local/instances/gastown/town -maxdepth 4 | head -200
git -C /Users/matt/code/exocortex/exocortex/.local/instances/gastown/repos/smoke-repo worktree list
```

Expected result:

- crew, rig, and hook-like state live under the disposable town root
- any Git worktrees point into disposable state, not into exocortex

7. Exercise a minimal non-Mayor workflow first.

```bash
cd /Users/matt/code/exocortex/exocortex/.local/instances/gastown/town
PATH="/Users/matt/code/exocortex/gastown/bin:$PATH" \
  gt convoy create "Smoke test" --human
PATH="/Users/matt/code/exocortex/gastown/bin:$PATH" \
  gt convoy list
```

Expected result:

- convoy creation works
- you can inspect state without committing to a larger Mayor session yet

8. Optional runtime-touch step for Codex.

```bash
cd /Users/matt/code/exocortex/exocortex/.local/instances/gastown/town
PATH="/Users/matt/code/exocortex/gastown/bin:$PATH" \
  gt sling <bead-id> smoke --agent codex
```

Expected result:

- the bead is assigned into the disposable rig
- any runtime-specific state still lands under the disposable town or sacrificial repo workspace

Replace `<bead-id>` with a real issue id created in your town. Keep this manual until the isolation story feels solid.

9. Optional Mayor session once the above is green.

```bash
cd /Users/matt/code/exocortex/exocortex/.local/instances/gastown/town
PATH="/Users/matt/code/exocortex/gastown/bin:$PATH" gt mayor attach
```

Expected result:

- you can enter the Mayor and inspect the system directly

10. Run the shared guardrail commands.

Success means:

- Gas Town is usable without touching exocortex git metadata
- worktrees and hook state are confined to the disposable town and sacrificial rig

## DeerFlow Manual Plan

Purpose:

- prove the sibling clone is in a sane installable state
- follow the upstream Docker-first bootstrap boundary without pretending the full app is already proven
- keep secrets and model config handling explicit

### Preconditions

- sibling clone exists at `/Users/matt/code/exocortex/deer-flow`
- Docker daemon is available if you want the preferred path

### Steps

1. Confirm the sibling clone looks like the DeerFlow repo root.

```bash
cd /Users/matt/code/exocortex/deer-flow
test -f Makefile
test -d backend
test -d frontend
test -f config.example.yaml
git remote -v
git status --short
```

Expected result:

- root markers are present
- `origin` is your fork and `upstream` is `bytedance/deer-flow`

2. Create `config.yaml` if it is missing.

```bash
cd /Users/matt/code/exocortex/deer-flow
test -f config.yaml || make config
```

Expected result:

- `config.yaml` exists

3. Prefer the Docker path when Docker is available.

```bash
cd /Users/matt/code/exocortex/deer-flow
docker info >/dev/null
make docker-init
```

Expected result:

- Docker is reachable
- `make docker-init` completes
- this only proves prerequisites were prepared

4. Inspect `config.yaml` only for model placeholders and referenced env vars.

Expected result:

- you know whether a `models` entry is still missing
- you know which variable names still need values

Do not inspect `.env` or other secret-bearing files just to prove this step.

5. Stop at the upstream setup boundary unless you explicitly want launch verification.

Recommended next command from the upstream install instructions:

```bash
cd /Users/matt/code/exocortex/deer-flow
make docker-start
```

Expected result:

- services begin their real startup path

6. Map DeerFlow into the exocortex harness only after steps 1 through 5 are green.

```bash
uv run python -m exocortex target show deerflow
uv run python -m exocortex target health deerflow
uv run python -m exocortex target proof deerflow
uv run python -m exocortex target start deerflow --image python:3.12-bookworm
uv run python -m exocortex target tmux up deerflow --image python:3.12-bookworm
uv run python -m exocortex target tmux exec deerflow \
  'python --version && pwd && ls -la /workspace | head && ls -la /runtime'
```

Expected result:

- host-side `health` runs `make check`
- host-side `proof` runs `make docker-init`
- the harness can mount the sibling clone and isolated runtime state

7. Run the shared guardrail commands.

Success means:

- DeerFlow is prepared via the upstream path
- exocortex can host the repo without changing parent git metadata

## Exit Criteria For This Phase

This phase is good enough to move on when all of the following are true:

- the shim smoke passes cleanly
- OpenClaw works natively and mounts cleanly under the harness
- Gas Town can create a disposable town and isolated rig without contaminating exocortex
- DeerFlow reaches the upstream Docker setup boundary and mounts cleanly under the harness
- `git submodule status` stays empty in exocortex
- `git ls-files --stage | awk '$1 == 160000 { print $0 }'` stays empty in exocortex

## Known Gaps

- the harness does not yet launch the full upstream targets automatically inside the container
- `target health` and `target proof` are host-side checks today
- OpenClaw channel integration, Gas Town autonomous multi-agent workflows, and DeerFlow real model-backed execution should all wait until these manual baby steps feel boring and repeatable
