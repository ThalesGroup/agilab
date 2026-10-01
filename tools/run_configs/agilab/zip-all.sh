#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

# Generated from PyCharm run configuration: zip_all
cd "$REPO_ROOT"
export PYTHONUNBUFFERED="1"
export UV_NO_SYNC="1"
# Let uv select the run-config project .venv instead of a stale activated shell.
unset VIRTUAL_ENV
# Set AGILAB_RUNCONFIG_INPUT_FILE_PROMPT to override this PyCharm input.
if [[ ${AGILAB_RUNCONFIG_INPUT_FILE_PROMPT+x} ]]; then
    AGILAB_RUNCONFIG_VALUE_0="${AGILAB_RUNCONFIG_INPUT_FILE_PROMPT}"
else
    AGILAB_RUNCONFIG_VALUE_0=''
fi
if [[ -z "${AGILAB_RUNCONFIG_VALUE_0}" ]]; then
    printf '%s\n' 'Set AGILAB_RUNCONFIG_INPUT_FILE_PROMPT before running this wrapper.' >&2
    exit 2
fi
uv run python "${REPO_ROOT}"/tools/zip_all.py --dir2zip "${AGILAB_RUNCONFIG_VALUE_0}" --follow-app-links --exclude-dir docs --exclude-dir codex
