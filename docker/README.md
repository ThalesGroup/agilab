[![PyPI version](https://img.shields.io/badge/PyPI-2026.4.25-informational?logo=pypi)](https://pypi.org/project/agilab)
[![License: BSD 3-Clause](https://img.shields.io/badge/License-BSD%203--Clause-blue.svg)](https://opensource.org/licenses/BSD-3-Clause)
[![GitHub](https://img.shields.io/badge/GitHub-ThalesGroup%2Fagilab-black?logo=github)](https://github.com/ThalesGroup/agilab)

# AGILAB Docker Deployment

Docker setup for running AGILAB standalone or as a simulated cluster with worker nodes.

## Architecture

### Standalone (default)

| Container | Image | Role |
|---|---|---|
| `agilab` | built from `docker/Dockerfile` | Streamlit UI + scheduler (port 8501) |
| `agilab-ollama` | `ollama/ollama` | Offline LLM inference API (port 11434) |

### Cluster mode

| Container | Image | Role |
|---|---|---|
| `agilab` | built from `docker/Dockerfile` | Streamlit UI + scheduler + sshd |
| `agilab-worker-1` | built from `docker/Dockerfile-Worker` | Worker node (sshd port 22) |
| `agilab-worker-2` | built from `docker/Dockerfile-Worker` | Worker node (sshd port 22) |
| `agilab-ollama` | `ollama/ollama` | Offline LLM inference API (port 11434) |

In cluster mode the scheduler SSHes into workers to distribute jobs, and workers
sshfs-mount `/root/clustershare` from the scheduler to share datasets.

## Prerequisites

- Docker Engine 24.0+
- Docker Compose 2.22+
- `/dev/fuse` available on the host (required by workers for sshfs — present by default on Linux)
- 8 GB RAM minimum (16 GB recommended when using LLM models)
- 20 GB free disk space

## Quick Start

### Standalone

1. **Set environment variables** (optional):
   ```bash
   export OPENAI_API_KEY="your-api-key"
   export CLUSTER_CREDENTIALS="user:password"
   ```

2. **Start services**:
   ```bash
   docker compose -f docker/docker-compose.yml up -d agilab ollama
   ```

3. **Pull an LLM model** (first time only — persisted in `ollama-models` volume):
   ```bash
   docker exec agilab-ollama ollama pull qwen3-coder:30b-a3b-q4_K_M
   ```
   Other supported local models: `gpt-oss:20b`, `qwen2.5-coder:latest`,
   `deepseek-coder:latest`, `qwen3:30b-a3b-instruct-2507-q4_K_M`,
   `ministral-3:14b-instruct-2512-q4_K_M`, `phi4-mini:3.8b-q4_K_M`.
   See [ollama.com/library](https://ollama.com/library).

4. **Access the UI**: http://localhost:8501

5. **Stop**:
   ```bash
   docker compose -f docker/docker-compose.yml down
   ```

### Cluster mode (scheduler + 2 workers)

```bash
# Start the full cluster (add ollama if needed)
docker compose -f docker/docker-compose.yml up -d agilab worker-1 worker-2

# Check all nodes are up
docker compose -f docker/docker-compose.yml ps

# In the AGILAB UI, configure workers:
#   Scheduler: agilab:22
#   Workers:   root@worker-1, root@worker-2
#   CLUSTER_CREDENTIALS: root:password
```

Workers require `CAP_SYS_ADMIN` and `/dev/fuse` for sshfs mounts — both are set
in `docker-compose.yml`. On some Linux distributions you may also need:
```bash
sudo modprobe fuse
```

## Development Workflow

For fast iteration without rebuilding, use Docker Compose `watch`.
It syncs `src/` into the running container on save — Streamlit hot-reloads automatically:

```bash
docker compose -f docker/docker-compose.yml up -d
docker compose -f docker/docker-compose.yml watch
```

Rebuild only when `pyproject.toml` or `docker/install.sh` changes:
```bash
docker compose -f docker/docker-compose.yml build
docker compose -f docker/docker-compose.yml up -d
```

## Manual Build and Run

**Scheduler image** (from repo root):
```bash
docker buildx build -f docker/Dockerfile -t agilab .
```

**Worker image**:
```bash
docker buildx build -f docker/Dockerfile-Worker -t agilab-worker .
```

**Standalone run** (no Ollama):
```bash
docker run -d \
  --name agilab \
  -p 8501:8501 \
  -e OPENAI_API_KEY="your-api-key" \
  agilab
```

**Manual cluster run**:
```bash
docker network create agilab-network

docker run -d --name agilab --hostname agilab \
  --network agilab-network -p 8501:8501 \
  -e CLUSTER_CREDENTIALS="root:password" \
  -v cluster-share:/root/clustershare \
  agilab

docker run -d --name agilab-worker-1 --hostname worker-1 \
  --network agilab-network \
  --device /dev/fuse --cap-add SYS_ADMIN \
  --security-opt apparmor:unconfined \
  -e CLUSTER_CREDENTIALS="root:password" \
  agilab-worker
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `OPENAI_API_KEY` | `dummykey` | OpenAI API key |
| `CLUSTER_CREDENTIALS` | `root:password` | SSH credentials — format `user:password` |
| `AGI_PYTHON_VERSION` | `3.13.9` | Python version managed by uv |
| `AGI_PYTHON_FREE_THREADED` | `0` | Enable free-threaded Python build |
| `OLLAMA_HOST` | `http://agilab-ollama:11434` | Ollama service endpoint |
| `APPS_REPOSITORY` | _(empty)_ | Optional external apps repository path |

## Volumes

| Volume | Used by | Description |
|---|---|---|
| `agilab-logs` | scheduler | Application logs |
| `agilab-config` | scheduler | AGILAB configuration (`~/.agilab`) |
| `cluster-share` | scheduler | Shared dataset directory mounted by workers via sshfs |
| `ollama-models` | ollama | Model storage (persists across restarts) |

## Files

| File | Description |
|---|---|
| `Dockerfile` | Scheduler image (Streamlit + sshd) |
| `Dockerfile-Worker` | Worker image (sshd + agi-node + agi-cluster) |
| `scheduler-entrypoint.sh` | Sets SSH password, starts sshd and Streamlit |
| `worker-entrypoint.sh` | Sets SSH password, writes `.env`, starts sshd |
| `docker-compose.yml` | Full cluster: scheduler + 2 workers + ollama |
| `install.sh` | Lightweight install script for Docker builds |

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
