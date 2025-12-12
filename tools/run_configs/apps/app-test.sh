#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

# Generated from PyCharm run configuration: app-test
export PYTHONUNBUFFERED="1"
uv run python $REPO_ROOT/src/agilab/apps/$Prompt:Enter app manager name:flight$_project/app_test.py
