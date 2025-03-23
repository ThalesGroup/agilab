#!/bin/bash
set -e

home=$(pwd)

# List of components to build
SUBDIRS=("src/fwk/env" "src/fwk/core" "src/fwk/gui")

# Prepare output directory
rm -fr "$home/../agi-pypi"
mkdir  "$home/../agi-pypi"

# (Optional pushd/popd to create and then return from the agi-pypi directory)
pushd "$home/../agi-pypi" > /dev/null
popd > /dev/null

# Build the main project (if needed) as a wheel and move it
uv build --sdidst
mv dist/*.tar.gz "$home/../agi-pypi"

# Loop through each subdirectory and build accordingly
for dir in "${SUBDIRS[@]}"; do
  pushd "$dir" > /dev/null
  rm -rf dist  # clean previous builds

  if [[ "$dir" == "src/fwk/gui" ]]; then
    # Build source distribution for GUI
    uv build --wheel
    # Move the resulting .tar.gz (sdist) to the agi-pypi directory
    mv dist/*.whl "$home/../agi-pypi"
  else
    # Build wheel for env and core
    uv build --wheel
    # Move the resulting .whl to the agi-pypi directory
    mv dist/*.whl "$home/../agi-pypi"
  fi

  popd > /dev/null
done

# Initialize and run within the agi-pypi directory (if required by the environment)
pushd "$home/../agi-pypi" > /dev/null
uv init --bare
uv add *.whl  *.tar.gz   # include both wheels and sdist in the environment
uv run agilab
popd > /dev/null
