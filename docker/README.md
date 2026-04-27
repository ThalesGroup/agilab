[![PyPI version](https://img.shields.io/badge/PyPI-2026.4.25-informational?logo=pypi)](https://pypi.org/project/agilab)
[![License: BSD 3-Clause](https://img.shields.io/badge/License-BSD%203--Clause-blue.svg)](https://opensource.org/licenses/BSD-3-Clause)
[![GitHub](https://img.shields.io/badge/GitHub-ThalesGroup%2Fagilab-black?logo=github)](https://github.com/ThalesGroup/agilab)

# AGILAB Docker Deployment

Docker setup for running AGILAB with optional offline LLM support via Ollama.

## Architecture

| Container | Image | Role |
|---|---|---|
| `agilab` | built from `docker/Dockerfile` | AGILAB Streamlit GUI (port 8501) |
| `agilab-ollama` | `ollama/ollama` (official) | Offline LLM inference API (port 11434) |

## Prerequisites

- Docker Engine 24.0+
- Docker Compose 2.22+ (for `watch` dev mode)
- 8 GB RAM minimum (16 GB recommended when using LLM models)
- 20 GB free disk space

## Quick Start

1. **Set environment variables** (optional):
   ```bash
   export OPENAI_API_KEY="your-api-key"
   export CLUSTER_CREDENTIALS="user:password"
   ```

2. **Start all services**:
   ```bash
   docker compose -f docker/docker-compose.yml up -d
   ```

3. **Pull an LLM model** (first time only — persisted in the `ollama-models` volume):
   ```bash
   docker exec agilab-ollama ollama pull mistral:instruct
   ```
   Other models: `llama3`, `gemma3`, `phi4`, `qwen2.5-coder` — see [ollama.com/library](https://ollama.com/library).

4. **Access the application**: http://localhost:8501

5. **Stop services**:
   ```bash
   docker compose -f docker/docker-compose.yml down
   ```

## Development Workflow

For fast iteration without rebuilding the image, use Docker Compose `watch`.
It syncs `src/` into the running container on every save — Streamlit detects the change and hot-reloads automatically:

```bash
docker compose -f docker/docker-compose.yml up -d
docker compose -f docker/docker-compose.yml watch
```

A full rebuild is only needed when dependencies or the install chain change:

```bash
# Rebuild when pyproject.toml or docker/install.sh changes
docker compose -f docker/docker-compose.yml build
docker compose -f docker/docker-compose.yml up -d
```

## Manual Build and Run

**Build the AGILAB image** (from repo root):
```bash
docker buildx build -f docker/Dockerfile -t agilab .
```

**Run standalone** (no Ollama):
```bash
docker run -d \
  --name agilab \
  -p 8501:8501 \
  -e OPENAI_API_KEY="your-api-key" \
  agilab
```

**Run with Ollama**:
```bash
docker network create agilab-network

docker run -d \
  --name agilab-ollama \
  --network agilab-network \
  -p 11434:11434 \
  -v ollama-models:/root/.ollama \
  ollama/ollama

docker exec agilab-ollama ollama pull mistral:instruct

docker run -d \
  --name agilab \
  --network agilab-network \
  -p 8501:8501 \
  -e OPENAI_API_KEY="your-api-key" \
  -e OLLAMA_HOST="http://agilab-ollama:11434" \
  agilab
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `OPENAI_API_KEY` | `dummykey` | OpenAI API key |
| `CLUSTER_CREDENTIALS` | `root:password` | SSH credentials for cluster access |
| `AGI_PYTHON_VERSION` | `3.13.9` | Python version managed by uv |
| `AGI_PYTHON_FREE_THREADED` | `0` | Enable free-threaded Python build |
| `OLLAMA_HOST` | `http://agilab-ollama:11434` | Ollama service endpoint |
| `APPS_REPOSITORY` | _(empty)_ | Optional external apps repository path |

## Volumes

| Volume | Description |
|---|---|
| `agilab-logs` | Application logs |
| `agilab-config` | AGILAB configuration |
| `ollama-models` | Ollama model storage (persists across restarts) |

## GPU Support (optional)

To enable GPU acceleration for Ollama, add a `deploy` section to the `ollama` service in `docker-compose.yml`:

```yaml
ollama:
  image: ollama/ollama
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            count: all
            capabilities: [gpu]
```

Requires [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html).
