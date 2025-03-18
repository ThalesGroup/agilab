#!/bin/bash
set -e

home=$(pwd)

# List of component to build
SUBDIRS=("src/fwk/env" "src/fwk/core" "src/fwk/lab")
rm -fr test
mkdir test

for dir in "${SUBDIRS[@]}"; do
  pushd "$dir" > /dev/null
  rm -rf dist
  uv build --wheel
  echo mv dist/*.whl $home/test
  mv dist/*.whl $home/test
  popd > /dev/null
done

# Install all wheels from the test directory
pushd test
uv init
uv sync --upgrade
uv add *.whl
uv run streamlit run ../src/fwk/lab/src/agi_lab/AGILAB.py
popd > /dev/null