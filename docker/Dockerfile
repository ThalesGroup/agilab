FROM ubuntu:latest
LABEL authors="Julien BESTARD"

FROM python:3.11-slim

# Install system dependencies using APT (Debian-based)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl wget unzip \
    software-properties-common libssl-dev zlib1g-dev \
    libbz2-dev libreadline-dev libsqlite3-dev libxml2-dev \
    liblzma-dev llvm llvm-dev tk-dev p7zip-full libffi-dev clang \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    cp /root/.local/bin/uv /usr/local/bin/uv && \
    uv --version

WORKDIR /app
COPY src/ ./src/
COPY docker/install.sh ./install.sh

ENV CLUSTER_CREDENTIALS="user:password"
ENV PYTHON_VERSION="3.12"
ENV OPENAI_API_KEY="dummkykey"

RUN chmod +x ./install.sh
RUN ./install.sh

EXPOSE 8501

CMD ["bash", "-c", "uv run --project /app/src/agilab/gui streamlit run /app/src/agilab/gui/src/agi_gui/AGILAB.py -- --install-type 1 --openai-api-key $OPENAI_API_KEY --apps-dir /app/src/agilab/apps"]
