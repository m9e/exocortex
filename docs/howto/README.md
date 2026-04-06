# Proof-of-Life How-To

This guide set is the short-path execution order for the current bootstrap phase:

1. [Gas Town Proof of Life](/Users/matt/code/exocortex/exocortex/docs/howto/gastown-proof-of-life.md)
2. [OpenClaw Proof of Life](/Users/matt/code/exocortex/exocortex/docs/howto/openclaw-proof-of-life.md)
3. [DeerFlow Proof of Life](/Users/matt/code/exocortex/exocortex/docs/howto/deerflow-proof-of-life.md)

These are intentionally minimal. The goal is “works roughly like standalone” before we start stitching targets into exocortex or hardening them further.

## Shared Kamiwaza Prep

This matters for OpenClaw now, and it is also the easiest live inference path for DeerFlow today.

Local references:

- PAT store on disk: `/Users/matt/code/stress/pat_store.yaml`
- Relevant logic in `/Users/matt/code/stress/stress.py`:
  - PAT store filename: line 117
  - PAT loader: line 348
  - endpoint-to-PAT lookup: line 405
  - Kamiwaza SDK client setup: line 570
  - direct `/v1/models` auto-lookup: line 665

What the stress harness is doing:

- PATs are keyed by endpoint hostname in `pat_store.yaml`
- direct OpenAI-compatible endpoints use `/v1/models` for model auto-discovery
- Kamiwaza control-plane endpoints use `kamiwaza-sdk` first, then switch to the returned runtime endpoint

## Current Observations

Checked on March 29, 2026:

- `https://tokenator.kamiwaza.ai/api` is up and requires auth
- `kamiwaza-sdk` on tokenator currently reports one active deployment:
  - `Kimi-K2.5`
- the deployment exposes an OpenAI-compatible runtime endpoint and `/models` returns `Kimi-K2.5`
- `http://eschaton.local:61113/v1/models` was down when checked and returned connection refused

## Resolve Tokenator Runtime Endpoint

1. Export the PAT from `pat_store.yaml` without copying it into docs or shell history by hand.

```bash
export KAMIWAZA_API_KEY="$(
python3 - <<'PY'
from pathlib import Path

for raw_line in Path('/Users/matt/code/stress/pat_store.yaml').read_text().splitlines():
    line = raw_line.strip()
    if not line or line.startswith('#') or ':' not in line:
        continue
    key, value = line.split(':', 1)
    if key.strip().lower() == 'tokenator.kamiwaza.ai':
        print(value.strip().strip('\"').strip(\"'\"), end='')
        break
PY
)"
```

2. Resolve the current runtime endpoint through the Kamiwaza SDK.

```bash
export TOKENATOR_RUNTIME_ENDPOINT="$(
python3 - <<'PY'
import os
from kamiwaza_sdk.client import KamiwazaClient

client = KamiwazaClient(
    base_url='https://tokenator.kamiwaza.ai/api',
    api_key=os.environ['KAMIWAZA_API_KEY'],
)

deployments = client.serving.list_active_deployments()

target = None
for dep in deployments:
    name = (getattr(dep, 'm_name', None) or getattr(dep, 'name', None) or '').lower()
    if 'kimi' in name and getattr(dep, 'endpoint', None):
        target = dep
        break

if target is None:
    target = next((dep for dep in deployments if getattr(dep, 'endpoint', None)), None)

if target is None:
    raise SystemExit('No active Kamiwaza deployment with an endpoint was found.')

print(target.endpoint.rstrip('/'), end='')
PY
)"
```

3. Verify the runtime endpoint and model list.

```bash
curl -ksS \
  -H "Authorization: Bearer $KAMIWAZA_API_KEY" \
  "$TOKENATOR_RUNTIME_ENDPOINT/models"
```

Expected result:

- HTTP `200`
- model list contains `Kimi-K2.5`

Important:

- do not hardcode the long tokenator runtime URL as a permanent truth; resolve it again if deployments move
- for now, treat `eschaton.local` as optional fallback only when it is back up
