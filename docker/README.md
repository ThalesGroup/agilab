# AGILAB Docker (scratch)

Experimental, leaner Docker setup for AGILAB. Compared to `docker/Dockerfile` this version:

- Uses `ghcr.io/astral-sh/uv:bookworm-slim` as base — uv is pre-installed, no install step needed
- Drops `libreadline-dev` and `tk-dev` — not needed for headless Streamlit
- Does not copy `test/`, `tools/`, `docs/` — runtime only
- Adds `OLLAMA_HOST` env var
- Uses the mandatory `--preview-features extra-build-dependencies` flag in the launch command

## Build

From the repo root:

```bash
docker buildx build -f docker-scratch/Dockerfile -t agilab:scratch .
```

## Run

Standalone (no Ollama):

```bash
docker run -d \
  --name agilab \
  -p 8501:8501 \
  -e OPENAI_API_KEY="your-api-key" \
  agilab:scratch
```

With Ollama (offline LLM):

```bash
docker network create agilab-network

docker run -d \
  --name agilab-ollama \
  --network agilab-network \
  -p 11434:11434 \
  -v ollama-models:/root/.ollama \
  ollama/ollama

# Pull a model once (persisted in the volume)
docker exec agilab-ollama ollama pull mistral:instruct

docker run -d \
  --name agilab \
  --network agilab-network \
  -p 8501:8501 \
  -e OPENAI_API_KEY="your-api-key" \
  -e OLLAMA_HOST="http://agilab-ollama:11434" \
  agilab:scratch
```

Access the GUI at http://localhost:8501.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `OPENAI_API_KEY` | `dummykey` | OpenAI API key |
| `CLUSTER_CREDENTIALS` | `root:password` | SSH credentials for cluster access |
| `AGI_PYTHON_VERSION` | `3.13.9` | Python version managed by uv |
| `AGI_PYTHON_FREE_THREADED` | `0` | Enable free-threaded Python build |
| `OLLAMA_HOST` | `http://ollama:11434` | Ollama service endpoint |
| `APPS_REPOSITORY` | _(empty)_ | Optional external apps repository path |

## Differences from `docker/Dockerfile`

| | `docker/Dockerfile` | `docker-scratch/Dockerfile` |
|---|---|---|
| Base image | `ubuntu:24.04` | `ghcr.io/astral-sh/uv:bookworm-slim` |
| uv install | Manual curl + copy | Pre-installed in base image |
| `libreadline-dev` | Yes | No |
| `tk-dev` | Yes | No |
| `test/` `tools/` `docs/` copied | Yes | No |
| `OLLAMA_HOST` env | No | Yes |
| `uv run` flag | Missing `--preview-features` | Correct |
