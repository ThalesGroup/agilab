#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

# Generated from PyCharm run configuration: app install (local)
cd "$REPO_ROOT"
export PYTHONUNBUFFERED="1"
export UV_NO_SYNC="1"
# Let uv select the run-config project .venv instead of a stale activated shell.
unset VIRTUAL_ENV
# Set AGILAB_RUNCONFIG_INPUT_SELECTED_APP to override this PyCharm input.
if [[ ${AGILAB_RUNCONFIG_INPUT_SELECTED_APP+x} ]]; then
    AGILAB_RUNCONFIG_VALUE_0="${AGILAB_RUNCONFIG_INPUT_SELECTED_APP}"
else
    AGILAB_RUNCONFIG_VALUE_0=src/agilab/apps/builtin/flight_telemetry_project
fi
uv run python "${REPO_ROOT}"/src/agilab/apps/install.py "${AGILAB_RUNCONFIG_VALUE_0}" --install-type 1 --verbose 1
