FROM ghcr.io/astral-sh/uv:bookworm-slim

LABEL maintainer="Jean-Pierre Morard"
LABEL description="AGILAB main application container"

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    wget \
    unzip \
    git \
    ca-certificates \
    libssl-dev \
    zlib1g-dev \
    libbz2-dev \
    libsqlite3-dev \
    libxml2-dev \
    liblzma-dev \
    llvm \
    llvm-dev \
    p7zip-full \
    libffi-dev \
    clang \
    locales \
    && rm -rf /var/lib/apt/lists/*

RUN locale-gen en_US.UTF-8
ENV LC_ALL=en_US.UTF-8
ENV LANG=en_US.UTF-8

WORKDIR /app

# Only runtime sources — test/, tools/, docs/ are dev-only
COPY src/ ./src/
COPY pyproject.toml ./pyproject.toml
COPY uv_config.toml ./uv_config.toml
COPY docker/install.sh ./install.sh

ENV AGI_PYTHON_VERSION="3.13.9"
ENV AGI_PYTHON_FREE_THREADED="0"
ENV CLUSTER_CREDENTIALS="root:password"
ENV OPENAI_API_KEY="dummykey"
ENV APPS_REPOSITORY=""
ENV OLLAMA_HOST="http://ollama:11434"

RUN mkdir -p /root/.agilab \
    && mkdir -p /root/.local/share/agilab \
    && mkdir -p /root/log/install_logs

RUN chmod +x ./install.sh && \
    ./install.sh --install-path /app --source local --install-apps

EXPOSE 8501

CMD ["bash", "-c", \
    "uv --preview-features extra-build-dependencies run streamlit run \
     /app/src/agilab/About_agilab.py -- --apps-path /app/src/agilab/apps"]
