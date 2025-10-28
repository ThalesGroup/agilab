#!/bin/bash

# Script: install_Agi_framework.sh
# Purpose: Install the framework

# Exit immediately if a command fails
set -e
set -o pipefail

UV_PREVIEW=(uv --preview-features extra-build-dependencies)

#source "$HOME/.local/bin/env"
source "$HOME/.local/share/agilab/.env"
AGI_PYTHON_VERSION=$(echo "$AGI_PYTHON_VERSION" | sed -E 's/^([0-9]+\.[0-9]+\.[0-9]+(\+freethreaded)?).*/\1/')
export AGI_PYTHON_VERSION

BLUE='\033[1;34m'
GREEN='\033[1;32m'
NC='\033[0m' # No Color
echo -e "${BLUE}Installing framework from $(pwd)...${NC}"
echo -e "${BLUE}Python Version: $AGI_PYTHON_VERSION${NC}"

echo -e "${BLUE}Installing agi-env...${NC}"
pushd agi-env > /dev/null
echo "${UV_PREVIEW[*]} sync -p $AGI_PYTHON_VERSION --dev"
${UV_PREVIEW[@]} sync -p "$AGI_PYTHON_VERSION" --dev
uv run python -m ensurepip
${UV_PREVIEW[@]} pip install -e .
popd > /dev/null

echo -e "${BLUE}Installing agi-node...${NC}"
pushd agi-node > /dev/null
echo "${UV_PREVIEW[*]} sync -p $AGI_PYTHON_VERSION --dev"
${UV_PREVIEW[@]} sync -p "$AGI_PYTHON_VERSION" --dev
uv run python -m ensurepip
${UV_PREVIEW[@]} pip install -e .
${UV_PREVIEW[@]} pip install -e ../agi-env
popd > /dev/null

echo -e "${BLUE}Installing agi-cluster...${NC}"
pushd agi-cluster > /dev/null
echo "${UV_PREVIEW[*]} sync -p $AGI_PYTHON_VERSION --dev"
${UV_PREVIEW[@]} sync -p "$AGI_PYTHON_VERSION" --dev
uv run python -m ensurepip
${UV_PREVIEW[@]} pip install -e .
${UV_PREVIEW[@]} pip install -e ../agi-node
${UV_PREVIEW[@]} pip install -e ../agi-env
popd > /dev/null

echo -e "${BLUE}Installing agilab...${NC}"
pushd ../../.. > /dev/null
${UV_PREVIEW[@]} sync -p "$AGI_PYTHON_VERSION" --preview-features python-upgrade
${UV_PREVIEW[@]} pip install -e src/agilab/core/agi-env
${UV_PREVIEW[@]} pip install -e src/agilab/core/agi-node
${UV_PREVIEW[@]} pip install -e src/agilab/core/agi-cluster
${UV_PREVIEW[@]} pip install -e src/agilab/core/agi-core

COVERAGE_FILE=".coverage-agilab" \
uv run -p "$AGI_PYTHON_VERSION" --no-sync --preview-features python-upgrade -m pytest \
  src/agilab/test \
  --cov=src/agilab \
  --cov-report=term-missing \
  --cov-report=xml:coverage-agilab.xml

echo -e "${BLUE}Running agi-env test suite with coverage...${NC}"
COVERAGE_FILE=".coverage-agi-env" \
uv run -p "$AGI_PYTHON_VERSION" --no-sync --preview-features python-upgrade -m pytest \
  src/agilab/core/agi-env/test \
  --cov=src/agilab/core/agi-env/src/agi_env \
  --cov-report=term-missing \
  --cov-report=xml:coverage-agi-env.xml

echo -e "${BLUE}Running core test suite with coverage...${NC}"
COVERAGE_FILE=".coverage-agi-core" \
uv run -p "$AGI_PYTHON_VERSION" --no-sync --preview-features python-upgrade -m pytest \
  src/agilab/core/test \
  --cov=src/agilab/core \
  --cov=src/agilab/core/agi-node/src/agi_node \
  --cov=src/agilab/core/agi-cluster/src/agi_cluster \
  --cov-report=term-missing \
  --cov-report=xml:coverage-agi-core.xml

COVERAGE_FILE=".coverage-agi-core" \
uv run -p "$AGI_PYTHON_VERSION" --no-sync --preview-features python-upgrade -m coverage xml -i \
  --include="src/agilab/core/agi-node/src/agi_node/*" \
  -o coverage-agi-node.xml

COVERAGE_FILE=".coverage-agi-core" \
uv run -p "$AGI_PYTHON_VERSION" --no-sync --preview-features python-upgrade -m coverage xml -i \
  --include="src/agilab/core/agi-cluster/src/agi_cluster/*" \
  -o coverage-agi-cluster.xml


popd > /dev/null
