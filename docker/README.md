# AGILAB Docker Deployment

This repository contains Docker configurations for running AGILAB with offline LLM capabilities using a multi-container architecture.

## Architecture

The setup consists of two containers:

1. **agilab-main**: Main AGILAB application with Streamlit GUI
2. **agilab-ollama**: Offline LLM service running Ollama with Mistral and GPT-OSS models

## Prerequisites

- Docker Engine 20.10+
- Docker Compose v2.0+
- At least 8GB RAM (16GB recommended for LLM models)
- 20GB free disk space (for models and dependencies)

## Quick Start

### Using Docker Compose (Recommended)

1. **Set environment variables** (optional):
   ```bash
   export OPENAI_API_KEY="your-api-key"
   export CLUSTER_CREDENTIALS="user:password"
   ```

2. **Start all services**:
   ```bash
   docker compose -f docker/docker-compose.yml up -d
   ```

3. **Access the application**:
   - AGILAB GUI: http://localhost:8501
   - Ollama API: http://localhost:11434

4**Stop services**:
   ```bash
   docker compose down
   ```

### Manual Build and Run

#### Build the main AGILAB image:
```bash
docker buildx build -f docker/Dockerfile -t agilab .
```

#### Build the Ollama LLM image:
```bash
docker buildx build -f docker/Dockerfile-Ollama -t agilab-ollama .
```

#### Create a network:
```bash
docker network create agilab-network
```

#### Run Ollama container:
```bash
docker run -d \
  --name agilab-ollama \
  --network agilab-network \
  -p 11434:11434 \
  -v ollama-models:/root/.ollama \
  agilab-ollama
```

#### Run AGILAB container:
```bash
docker run -d \
  --name agilab-main \
  --network agilab-network \
  -p 8501:8501 \
  -e OPENAI_API_KEY="your-api-key" \
  -e OLLAMA_HOST="http://agilab-ollama:11434" \
  agilab
```

## Configuration

### Environment Variables

#### Main Application (agilab)
- `OPENAI_API_KEY`: OpenAI API key (default: "dummykey")
- `CLUSTER_CREDENTIALS`: SSH credentials for cluster access (default: "root:password")
- `AGI_PYTHON_VERSION`: Python version to use (default: "3.13.9")
- `AGI_PYTHON_FREE_THREADED`: Enable free-threaded Python (default: "0")
- `OLLAMA_HOST`: Ollama service URL (default: "http://ollama:11434")

#### Ollama Container
The Ollama container automatically pulls the following models on first startup:
- `mistral:instruct` (~4GB)
- `gpt-oss:20b` (~12GB)

**Note**: Initial startup may take 15-30 minutes to download models.

### Volume Mounts

Persistent data is stored in Docker volumes:
- `agilab-logs`: Application logs
- `agilab-config`: AGILAB configuration
- `ollama-models`: Ollama model storage
- `ollama-logs`: Ollama service logs