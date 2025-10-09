#!/usr/bin/env bash
set -euo pipefail

# Generated from PyCharm run configuration: zip_all
cd /Users/jpm/PycharmProjects/agilab
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1
uv run python /Users/jpm/PycharmProjects/agilab/tools/zip_all.py --dir2zip src --zipfile src.zip
