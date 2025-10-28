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

echo -e "${GREEN}Checking installation...${NC}"
uv run -p "$AGI_PYTHON_VERSION" --no-sync --preview-features python-upgrade -m pytest

echo -e "${BLUE}Running core test suite with coverage...${NC}"
uv run -p "$AGI_PYTHON_VERSION" --no-sync --preview-features python-upgrade -m pytest \
  src/agilab/core/test \
  --cov=src/agilab/core \
  --cov-report=term-missing \
  --cov-report=xml

popd > /dev/null
