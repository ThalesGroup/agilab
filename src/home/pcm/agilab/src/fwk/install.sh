#!/bin/bash

# Script: install_Agi_framework.sh
# Purpose: Install the fwk

# Exit immediately if a command exits wi  th a non-zero status
set -e
set -o pipefail

echo "Installing framework from $(pwd)..."

echo "Resolving env and core path inside tomls"
echo "Installing env..."
pushd env > /dev/null
echo uv sync --dev --directory $1
uv sync --dev --directory $1
uv pip install -e .
popd > /dev/null

echo "Installing core..."
pushd core > /dev/null
echo uv sync --extra managers --group rapids --dev --directory $1
uv sync --extra managers --group rapids --dev --directory $1
uv pip install -e .
popd > /dev/null

echo "Installing gui..."
pushd gui > /dev/null
uv sync --directory $1
popd > /dev/null

echo "Checking installation..."
uv run --project core/managers python run-all-test.py
