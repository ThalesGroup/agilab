#!/bin/bash
set -eux

home=$(pwd)



# Prepare output directory
rm  -rf "$home/../agi-space"
mkdir -p "$home/../agi-space"

# Build the main project as a sdist and move it
rm -rf dist
rm -rf build
uv build --sdist
mv dist/*.gz "$home/../agi-space"

pushd "src/fwk/core/agi-core" > /dev/null
rm -rf dist  # clean previous builds
rm -rf build
uv build --wheel
mv dist/*.whl "$home/../agi-space"
popd > /dev/null

pushd "$home/../agi-space"
rm -fr .venv uv.lock
if [ ! -f pyproject.toml ]; then
    uv init --bare
fi
uv add  *.whl *.gz
popd