#!/bin/bash
set -e

home=$(pwd)


# List of component to build
SUBDIRS=("src/fwk/env" "src/fwk/core" "src/fwk/gui")

rm -fr $home/../agi-pypi
mkdir  $home/../agi-pypi
pushd $home/../agi-pypi
popd > /dev/null

uv build --wheel
mv dist/*.whl $home/../agi-pypi

for dir in "${SUBDIRS[@]}"; do
  pushd "$dir" > /dev/null
  rm -rf dist
  uv build --wheel
  echo mv dist/*.whl $home/../agi-pypi
  mv dist/*.whl $home/../agi-pypi
  popd > /dev/null
done

pushd $home/../agi-pypi
uv init
uv add *.whl
uv run agilab
popd > /dev/null