FROM ubuntu:24.04
LABEL authors="Julien BESTARD"
LABEL description="AGILAB main application container"

# Prevent interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies
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
    libreadline-dev \
    libsqlite3-dev \
    libxml2-dev \
    liblzma-dev \
    llvm \
    llvm-dev \
    tk-dev \
    p7zip-full \
    libffi-dev \
    clang \
    locales \
    && rm -rf /var/lib/apt/lists/*

# Set up locale
RUN locale-gen en_US.UTF-8
ENV LC_ALL=en_US.UTF-8
ENV LANG=en_US.UTF-8

# Install uv package manager
RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    cp /root/.local/bin/uv /usr/local/bin/uv && \
    uv --version

# Set working directory
WORKDIR /app

# Copy source files
COPY src/ ./src/
COPY pyproject.toml ./pyproject.toml
COPY uv_config.toml ./uv_config.toml
COPY test/ ./test/
COPY tools/ ./tools/
COPY docs/ ./docs/
COPY docker/install.sh ./install.sh

# Environment variables for installation
ENV CLUSTER_CREDENTIALS="root:password"
ENV AGI_PYTHON_VERSION="3.13.9"
ENV AGI_PYTHON_FREE_THREADED="0"
ENV OPENAI_API_KEY="dummykey"
ENV APPS_REPOSITORY=""

# Create necessary directories
RUN mkdir -p /root/.agilab \
    && mkdir -p /root/.local/share/agilab \
    && mkdir -p /root/log/install_logs


RUN chmod +x ./install.sh && \
    ./install.sh \
        --cluster-ssh-credentials "$CLUSTER_CREDENTIALS" \
        --openai-api-key "$OPENAI_API_KEY" \
        --install-path /app \
        --source local \
        --install-apps

# Expose Streamlit port
EXPOSE 8501

# Default command to run the GUI
CMD ["bash", "-c", "uv run streamlit run /app/src/agilab/About_agilab.py -- --apps-path /app/src/agilab/apps"]
