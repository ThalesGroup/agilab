#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

# Generated from PyCharm run configuration: app-test
export PYTHONUNBUFFERED="1"
# Let uv select the run-config project .venv instead of a stale activated shell.
unset VIRTUAL_ENV
# Set AGILAB_RUNCONFIG_INPUT_ENTER_APP_PATH to override this PyCharm input.
if [[ ${AGILAB_RUNCONFIG_INPUT_ENTER_APP_PATH+x} ]]; then
    AGILAB_RUNCONFIG_VALUE_0="${AGILAB_RUNCONFIG_INPUT_ENTER_APP_PATH}"
else
    AGILAB_RUNCONFIG_VALUE_0=builtin/flight_telemetry_project
fi
uv run python "${REPO_ROOT}"/src/agilab/apps/"${AGILAB_RUNCONFIG_VALUE_0}"/app_test.py
