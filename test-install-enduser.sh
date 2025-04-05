#!/bin/bash
set -e

home=$(pwd)

# List of components to build
SUBDIRS=("fwk/env" "fwk/core" "fwk/gui")

# Prepare output directory
mkdir -p "$home/../agi-pypi"
rm  -f "$home/../agi-pypi/*.whl"
rm  -f "$home/../agi-pypi/*.gz"
rm  -fr "$home/../agi-pypi/.venv"
rm  -f "$home/../agi-pypi/uv.lock"
rm  -f "$home/../agi-pypi/pyproject.toml"

# Build the main project as a sdist and move it
rm -rf dist
rm -rf build
uv build --sdist
mv dist/*.gz "$home/../agi-pypi"

# Loop through each subdirectory and build accordingly
for subdir in "${SUBDIRS[@]}"; do
  pushd "src/$subdir" > /dev/null
  rm -rf dist  # clean previous builds
  rm -rf build
  uv build --wheel
  mv dist/*.whl "$home/../agi-pypi"
  popd > /dev/null
done

pushd "$home/../agi-pypi"
rm -fr .venv uv.lock
if [ ! -f pyproject.toml ]; then
    uv init --bare
fi
uv add  *.whl *.gz
popd