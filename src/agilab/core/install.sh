#!/bin/bash

# Script: install_Agi_framework.sh
# Purpose: Install the framework

# Exit immediately if a command fails
set -e
set -o pipefail

#source "$HOME/.local/bin/env"
source "$HOME/.local/share/agilab/.env"
AGI_PYTHON_VERSION=$(echo "$AGI_PYTHON_VERSION" | sed -E 's/^([0-9]+\.[0-9]+\.[0-9]+(\+freethreaded)?).*/\1/')
export AGI_PYTHON_VERSION


BLUE='\033[1;34m'
GREEN='\033[1;32m'
NC='\033[0m' # No Color
echo -e "${BLUE}Installing framework from $(pwd)...${NC}"
echo -e "${BLUE}Python Version: $AGI_PYTHON_VERSION${NC}"

echo -e "${BLUE}Installing agi-cluster...${NC}"
pushd cluster > /dev/null
echo "uv sync -p $AGI_PYTHON_VERSION --dev"
uv sync -p "$AGI_PYTHON_VERSION" --dev
uv run python -m ensurepip
uv pip install -e .
uv pip install -e ../node
uv pip install -e ../env

popd > /dev/null

echo -e "${BLUE}Installing agi-node...${NC}"
pushd node > /dev/null
echo "uv sync -p $AGI_PYTHON_VERSION --dev"
uv sync -p "$AGI_PYTHON_VERSION" --dev
uv run python -m ensurepip
uv pip install -e .
uv pip install -e ../env
popd > /dev/null

echo -e "${BLUE}Installing agi-env...${NC}"
pushd env > /dev/null
echo "uv sync -p $AGI_PYTHON_VERSION --dev"
uv sync -p "$AGI_PYTHON_VERSION" --dev
uv run python -m ensurepip
uv pip install -e .
popd > /dev/null

echo -e "${BLUE}Installing agilab...${NC}"
pushd ../../.. > /dev/null
uv sync -p "$AGI_PYTHON_VERSION" --dev
uv run python -m ensurepip
echo $(pwd)
uv pip install -e .
uv pip install -e src/agilab/core/env
uv pip install -e src/agilab/core/node
uv pip install -e src/agilab/core/cluster
popd > /dev/null

echo -e "${GREEN}Checking installation...${NC}"
uv run -p "$AGI_PYTHON_VERSION" --project cluster python run-all-test.py

