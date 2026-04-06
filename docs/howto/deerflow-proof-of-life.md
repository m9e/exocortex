# DeerFlow Proof of Life

Goal: prove DeerFlow boots roughly like standalone, with the smallest reasonable live model configuration.

Source repo:

- `/Users/matt/code/exocortex/deer-flow`

Primary upstream references:

- [DeerFlow Install](https://github.com/bytedance/deer-flow/blob/main/Install.md)
- [DeerFlow README](https://github.com/bytedance/deer-flow/blob/main/README.md)

## What Counts As Success

- `config.yaml` exists
- Docker prerequisites are prepared
- Docker services start
- the web interface comes up on `http://localhost:2026`
- DeerFlow is using a real configured model path rather than a placeholder

## Recommended Model Path For Right Now

Use tokenator Kimi first.

Why:

- it is up now
- it already has a live `Kimi-K2.5` deployment
- the runtime endpoint is OpenAI-compatible once resolved through the Kamiwaza SDK

Use [the shared Kamiwaza prep](/Users/matt/code/exocortex/exocortex/docs/howto/README.md) first.

## Steps

1. Confirm the repo root looks sane.

```bash
cd /Users/matt/code/exocortex/deer-flow
test -f Makefile
test -d backend
test -d frontend
test -f config.example.yaml
```

2. Generate local configuration files if needed.

```bash
cd /Users/matt/code/exocortex/deer-flow
test -f config.yaml || make config
```

3. Resolve the current tokenator runtime endpoint and keep it handy.

Use the shared Kamiwaza prep guide. You want:

- `KAMIWAZA_API_KEY`
- `TOKENATOR_RUNTIME_ENDPOINT`

4. Add one live model entry to `config.yaml`.

Minimal example:

```yaml
models:
  - name: kimi-k2-5
    display_name: Kimi K2.5 (Tokenator)
    use: langchain_openai:ChatOpenAI
    model: Kimi-K2.5
    api_key: $KAMIWAZA_API_KEY
    base_url: PASTE_CURRENT_TOKENATOR_RUNTIME_ENDPOINT_HERE
    max_tokens: 4096
    temperature: 0.2
```

Notes:

- paste the current SDK-resolved endpoint literally
- keep `api_key` env-backed
- rerun the endpoint lookup if tokenator rotates deployments

5. Prepare Docker prerequisites.

```bash
cd /Users/matt/code/exocortex/deer-flow
docker info >/dev/null
make docker-init
```

6. Start the services.

```bash
cd /Users/matt/code/exocortex/deer-flow
make docker-start
```

7. Verify the minimal standalone surface.

```bash
curl http://localhost:2026
curl http://localhost:2026/api/models
```

Expected result:

- the web interface responds on `http://localhost:2026`
- `/api/models` shows the configured model entry or at least a healthy API response

## Optional Local-Only Fallback

When `eschaton.local` is back up, you can use it as a direct OpenAI-compatible provider instead of tokenator.

First verify:

```bash
curl http://eschaton.local:61113/v1/models
```

If that works, replace the model block with a direct `glm-5` entry:

```yaml
models:
  - name: glm-5
    display_name: GLM-5 (eschaton)
    use: langchain_openai:ChatOpenAI
    model: glm-5
    api_key: $OPENAI_API_KEY
    base_url: http://eschaton.local:61113/v1
    max_tokens: 4096
    temperature: 0.2
```

Use this only when the local endpoint is actually alive.

## Stop Condition

Stop once:

- DeerFlow is reachable on `http://localhost:2026`
- it has at least one real model wired in
- you can see a healthy API surface without moving into deeper feature work
