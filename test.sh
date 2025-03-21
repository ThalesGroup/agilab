#!/bin/bash
set -e

home=$(pwd)


# List of component to build
SUBDIRS=("src/fwk/env" "src/fwk/core" "src/fwk/gui")

rm -fr $home/../test
mkdir  $home/../test
pushd $home/../test
popd > /dev/null

uv build --wheel
mv dist/*.whl $home/../test

for dir in "${SUBDIRS[@]}"; do
  pushd "$dir" > /dev/null
  rm -rf dist
  uv build --wheel
  echo mv dist/*.whl $home/../test
  mv dist/*.whl $home/../test
  popd > /dev/null
done

pushd $home/../test
uv init
uv add *.whl
uv sync --upgrade
uv run agilab
popd > /dev/null