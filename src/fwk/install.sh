#!/bin/bash

# Script: install_Agi_framework.sh
# Purpose: Install the fwk

# Exit immediately if a command exits wi  th a non-zero status
set -e
set -o pipefail

echo "Installing framework from $(pwd)..."

echo "Installing env..."
pushd env > /dev/null
uv sync --dev --directory $(realpath "$1/env")
uv pip install -e .
popd > /dev/null

echo "Installing core..."
pushd core > /dev/null
uv sync --extra managers --group rapids --dev --directory $(realpath "$1/core")
uv pip install -e .
popd > /dev/null

echo "Installing gui..."
pushd gui > /dev/null
uv sync --dev --directory $(realpath "$1/gui")
popd > /dev/null

echo "Checking installation..."
uv run --project core/managers python run-all-test.py