#!/bin/bash
set -e

home=$(pwd)

# List of components to build
SUBDIRS=("fwk/env" "fwk/core" "fwk/gui")

# Prepare output directory
rm -rf "$home/../agi-pypi"
mkdir "$home/../agi-pypi"

# Build the main project as a sdist and move it
rm -rf dist
uv build --sdist
mv dist/*.gz "$home/../agi-pypi"

# Loop through each subdirectory and build accordingly
for subdir in "${SUBDIRS[@]}"; do
  pushd "src/$subdir" > /dev/null
  rm -rf dist  # clean previous builds
  uv build --wheel
  mv dist/*.whl "$home/../agi-pypi"
  popd > /dev/null
done

uv run agilab
