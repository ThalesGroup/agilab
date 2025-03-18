#!/bin/bash

# Script: install_Agi_framework.sh
# Purpose: Install the fwk

resolve_packages() {
  DIR_PATH=$(readlink -f "$1")
  AGI_ENV="$(cat $HOME/.local/share/agilab/.agilab-path)/agi/fwk/env"
  AGI_CORE="$(cat $HOME/.local/share/agilab/.agilab-path)/agi/fwk/core"

  pushd "$DIR_PATH"

  if grep -q "agi-env" pyproject.toml; then
    sed -i "s|\(^\s*agi-env\s*=\s*{[^}]*path\s*=\s*['\"]\)[^'\"]*\(['\"]\)|\1$AGI_ENV\2|" pyproject.toml
  fi
  if grep -q "agi-core" pyproject.toml; then
    sed -i "s|\(^\s*agi-core\s*=\s*{[^}]*path\s*=\s*['\"]\)[^'\"]*\(['\"]\)|\1$AGI_CORE\2|" pyproject.toml
  fi

  popd
}

# Exit immediately if a command exits wi  th a non-zero status
set -e
set -o pipefail

main() {
  echo "Installing framework from $(pwd)..."

  echo "Resolving env and core path inside tomls"
  echo "Installing env..."
  pushd env
  uv sync
  uv run python3 src/agi_env/post_install.py
  uv pip install -e .
  popd

  echo "Installing core..."
  pushd core
  uv sync --extra managers --group rapids
  uv pip install -e .
  popd

  pushd lab
  uv sync
  popd

  echo "Checking installation..."
  uv run --project core/managers python run-all-test.py
}

main