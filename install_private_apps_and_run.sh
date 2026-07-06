#!/usr/bin/env bash
set -euo pipefail

CHECKOUT="${AGILAB_CHECKOUT:-$HOME/PycharmProjects/agilab}"
APPS_REPO="${APPS_REPO:-}"

export AGI_PYTHON_VERSION="${AGI_PYTHON_VERSION:-3.14.6}"
export AGI_PYTHON_FREE_THREADED=0
if [[ -z "${AGI_PYTHON_UV_SPEC:-}" ]]; then
  case "$AGI_PYTHON_VERSION" in
    3.14|3.14.*) AGI_PYTHON_UV_SPEC="${AGI_PYTHON_VERSION}+gil" ;;
    *) AGI_PYTHON_UV_SPEC="$AGI_PYTHON_VERSION" ;;
  esac
fi
export AGI_PYTHON_UV_SPEC
export AGILAB_REFRESH_WORKER_ENVS="${AGILAB_REFRESH_WORKER_ENVS:-1}"

if [[ ! -d "$CHECKOUT" ]]; then
  echo "AGILAB checkout not found: $CHECKOUT" >&2
  exit 1
fi

if [[ ! -d "$APPS_REPO" ]]; then
  echo "Apps repository not found. Set APPS_REPO=/path/to/private-or-external-apps-repo." >&2
  exit 1
fi

cd "$CHECKOUT"

uv --preview-features extra-build-dependencies run --no-project -p "$AGI_PYTHON_UV_SPEC" python - <<'PY'
import sys

print("Using Python:", sys.executable)
print("Version:", sys.version)

if "t" in getattr(sys, "abiflags", "") or getattr(sys, "_is_gil_enabled", lambda: True)() is False:
    raise SystemExit("ERROR: selected Python is freethreaded; aborting")
PY

uv cache clean polars polars-runtime-32 >/dev/null || true

rm -rf \
  .venv \
  src/agilab/core/agi-env/.venv \
  src/agilab/core/agi-node/.venv \
  src/agilab/core/agi-cluster/.venv \
  src/agilab/core/agi-core/.venv

./install.sh \
  --apps-repository "$APPS_REPO" \
  --install-apps all

uv --preview-features extra-build-dependencies run --extra ui \
  streamlit run src/agilab/main_page.py "$@"
