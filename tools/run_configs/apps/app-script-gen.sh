#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

# Generated from PyCharm run configuration: app_script gen
export PYTHONUNBUFFERED="1"
export UV_NO_SYNC="1"
# Let uv select the run-config project .venv instead of a stale activated shell.
unset VIRTUAL_ENV
# Set AGILAB_RUNCONFIG_INPUT_ENTER_APP_PROJECT to override this PyCharm input.
if [[ ${AGILAB_RUNCONFIG_INPUT_ENTER_APP_PROJECT+x} ]]; then
    AGILAB_RUNCONFIG_VALUE_0="${AGILAB_RUNCONFIG_INPUT_ENTER_APP_PROJECT}"
else
    AGILAB_RUNCONFIG_VALUE_0=builtin/flight_telemetry_project
fi
uv run python "${REPO_ROOT}"/pycharm/gen_app_script.py "${AGILAB_RUNCONFIG_VALUE_0}"
