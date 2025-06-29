#!/bin/bash

# Script: install_Agi_framework.sh
# Purpose: Install the framework

# Exit immediately if a command fails
set -e
set -o pipefail

#source "$HOME/.local/bin/env"
source "$HOME/.local/share/agilab/.env"

BLUE='\033[1;34m'
GREEN='\033[1;32m'
NC='\033[0m' # No Color

echo -e "${BLUE}Installing framework from $(pwd)...${NC}"
echo -e "${BLUE}Python Version: $AGI_PYTHON_VERSION${NC}"

echo -e "${BLUE}Installing env...${NC}"
pushd env > /dev/null
uv sync -p "$AGI_PYTHON_VERSION" --dev --directory "$(realpath "$1/env")"
uv run python -m ensurepip
uv pip install -e .
popd > /dev/null

echo -e "${BLUE}Installing node...${NC}"
pushd node > /dev/null
echo "uv sync -p $AGI_PYTHON_VERSION --config-file uv_config.toml --dev --directory $(realpath '$1/node')"
uv sync -p "$AGI_PYTHON_VERSION" --config-file uv_config.toml --dev --directory "$(realpath "$1/node")"
uv run python -m ensurepip
uv pip install -e .
popd > /dev/null

echo -e "${BLUE}Installing cluster...${NC}"
pushd cluster > /dev/null
echo "uv sync -p $AGI_PYTHON_VERSION --config-file uv_config.toml --dev --directory $(realpath '$1/cluster')"
uv sync -p "$AGI_PYTHON_VERSION" --config-file uv_config.toml --dev --directory "$(realpath "$1/cluster")"
uv run python -m ensurepip
uv pip install -e .
popd > /dev/null

echo -e "${BLUE}Installing gui...${NC}"
pushd ../gui > /dev/null
uv sync -p "$AGI_PYTHON_VERSION" --dev --directory "$(realpath "$1/../gui")"
uv run python -m ensurepip
popd > /dev/null

echo -e "${GREEN}Checking installation...${NC}"
uv run -p "$AGI_PYTHON_VERSION" --project cluster python run-all-test.py
