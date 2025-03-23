#!/bin/bash
set -e

home=$(pwd)

# List of components to build
SUBDIRS=("src/fwk/env" "src/fwk/core" "src/fwk/gui")

# Prepare output directory
rm -fr "$home/../agi-pypi"
mkdir  "$home/../agi-pypi"

# Build the main project (if needed) as a wheel and move it
uv build --sdist
mv dist/*.tar.gz "$home/../agi-pypi"

# Loop through each subdirectory and build accordingly
for dir in "${SUBDIRS[@]}"; do
  pushd "$dir" > /dev/null
  rm -rf dist  # clean previous builds
  # Build wheel for env and core
  uv build --wheel
  # Move the resulting .whl to the agi-pypi directory
  mv dist/*.whl "$home/../agi-pypi"
  popd > /dev/null
done

pushd "$home/../agi-pypi" > /dev/null
uv init --bare
uv add *.whl   # include both wheels and sdist in the environment
uv run agilab
popd > /dev/null
