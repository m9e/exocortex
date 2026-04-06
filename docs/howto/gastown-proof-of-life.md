# Gas Town Proof of Life

Goal: prove Gas Town works as Gas Town, not as an exocortex plugin.

This guide keeps all mutable state in disposable paths under:

- `/Users/matt/code/exocortex/exocortex/.local/instances/gastown`

Source repo:

- `/Users/matt/code/exocortex/gastown`

Primary upstream reference:

- [Gas Town README](https://github.com/steveyegge/gastown/blob/main/README.md)

## What Counts As Success

- `gt` builds and runs
- a disposable town initializes
- a sacrificial rig repo is added
- a crew workspace is created
- a convoy can be created and listed
- no exocortex git metadata is touched

## Prereqs

Per the upstream README:

- Go 1.25+
- Git 2.25+
- Dolt 1.82.4+
- beads `bd` 0.55.4+
- sqlite3
- tmux 3.0+
- one agent runtime such as Codex or Claude

Verify quickly:

```bash
go version
git --version
dolt --version
bd --version
sqlite3 --version
tmux -V
codex --version
```

## Steps

1. Build a local `gt` from the sibling clone.

```bash
cd /Users/matt/code/exocortex/gastown
go build -o ./bin/gt ./cmd/gt
./bin/gt --help
```

2. Create a disposable town root and sacrificial repo.

```bash
mkdir -p /Users/matt/code/exocortex/exocortex/.local/instances/gastown/repos/smoke-repo
mkdir -p /Users/matt/code/exocortex/exocortex/.local/instances/gastown/town

cd /Users/matt/code/exocortex/exocortex/.local/instances/gastown/repos/smoke-repo
git init -b main
printf '# gastown smoke repo\n' > README.md
git add README.md
git commit -m 'initial commit'
```

3. Initialize the town and list configured agent presets.

```bash
cd /Users/matt/code/exocortex/gastown
PATH="$PWD/bin:$PATH" gt install /Users/matt/code/exocortex/exocortex/.local/instances/gastown/town --git

cd /Users/matt/code/exocortex/exocortex/.local/instances/gastown/town
PATH="/Users/matt/code/exocortex/gastown/bin:$PATH" gt config agent list
```

4. Add the sacrificial rig and create your crew workspace.

```bash
PATH="/Users/matt/code/exocortex/gastown/bin:$PATH" \
  gt rig add smoke /Users/matt/code/exocortex/exocortex/.local/instances/gastown/repos/smoke-repo

PATH="/Users/matt/code/exocortex/gastown/bin:$PATH" \
  gt crew add matt --rig smoke
```

If `gt rig add` rejects a local repo path in this build, switch to a sacrificial remote repository URL. Do not point it at exocortex and do not point it at the canonical Gas Town source clone.

5. Create the smallest useful tracked work item.

```bash
cd /Users/matt/code/exocortex/exocortex/.local/instances/gastown/town
PATH="/Users/matt/code/exocortex/gastown/bin:$PATH" \
  gt convoy create "Smoke test" --human

PATH="/Users/matt/code/exocortex/gastown/bin:$PATH" \
  gt convoy list
```

6. Inspect where state landed.

```bash
find /Users/matt/code/exocortex/exocortex/.local/instances/gastown/town -maxdepth 4 | head -200
git -C /Users/matt/code/exocortex/exocortex/.local/instances/gastown/repos/smoke-repo worktree list
```

Expected result:

- the town owns the crew, hook, and convoy state
- any worktrees stay under the disposable town/smoke repo paths

## Optional Mayor Check

Only after the above is green:

```bash
cd /Users/matt/code/exocortex/exocortex/.local/instances/gastown/town
PATH="/Users/matt/code/exocortex/gastown/bin:$PATH" gt mayor attach
```

That is the point where you can touch it hands-on and get a feel for how Gas Town wants to be used.

## Stop Condition

Stop once:

- `gt convoy list` works
- the crew workspace exists
- you can see the state layout and it is clearly not contaminating exocortex

Do not push deeper into autonomous flows until that isolation story feels boring.
