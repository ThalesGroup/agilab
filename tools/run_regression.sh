#!/usr/bin/env bash
set -euo pipefail

# Run the full pytest suite using uv and the repo interpreter.
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export PYTHONUNBUFFERED=1
export UV_NO_SYNC=1

# Load APPS_REPOSITORY from the agilab env file if not already set.
if [[ -z "${APPS_REPOSITORY:-}" ]]; then
  env_file="$HOME/.local/share/agilab/.env"
  if [[ -f "$env_file" ]]; then
    # shellcheck disable=SC2046
    export $(grep -E '^[A-Z0-9_]+=.*' "$env_file")
  fi
fi
# Strip surrounding quotes in APPS_REPOSITORY if present
if [[ -n "${APPS_REPOSITORY:-}" ]]; then
  APPS_REPOSITORY="${APPS_REPOSITORY%\"}"
  APPS_REPOSITORY="${APPS_REPOSITORY#\"}"
fi

RUN_APPS=${RUN_APPS:-1}

# echo "install apps"
# $(pwd)/src/agilab/install_app.sh

# Core/Env regression
uv run pytest "$@"

# App-by-app regression to avoid cross-import clashes (apps can have duplicate module basenames).
if [[ "$RUN_APPS" != "0" ]]; then
  echo "APPS_REPOSITORY=${APPS_REPOSITORY:-unset}"
  app_list=$(find src/agilab/apps -maxdepth 2 -type d -name "*_project")
  if [[ -n "${APPS_REPOSITORY:-}" && -d "${APPS_REPOSITORY}" ]]; then
    app_list+=" "$(find "${APPS_REPOSITORY}" -maxdepth 3 -type d -name "*_project")
  fi
  # normalize whitespace
  app_list=$(printf "%s\n" "$app_list" | tr ' ' '\n' | grep -v '^$' || true)
  if [[ -z "$app_list" ]]; then
    echo "No app projects found (APPS_REPOSITORY=${APPS_REPOSITORY:-unset}), skipping app tests."
  fi
  app_count=$(printf "%s\n" "$app_list" | grep -c . || true)
  echo "Found ${app_count} app projects to test."

  while IFS= read -r app_dir; do
    [[ -z "$app_dir" ]] && continue
    echo "== Running app tests in $app_dir =="
    app_base="$(basename "$app_dir")"
    app_name="${app_base%_project}"
    # example_app relies on a worker that may not exist locally; skip to avoid install failures
    if [[ "$app_name" == "example_app" ]]; then
      echo "Skipping $app_dir (example_app worker not provisioned)."
      continue
    fi

    install_script="$HOME/log/execute/${app_name}/AGI_install_${app_name}.py"
    agi_cluster_proj="$(pwd)/src/agilab/core/agi-cluster"
    if [[ -f "$install_script" && ! -x "$app_dir/.venv/bin/pytest" ]]; then
      echo "  provisioning venv via $install_script ..."
      (cd "$app_dir" && uv run --project "$agi_cluster_proj" python "$install_script") || true
    fi

    if [[ -x "$app_dir/.venv/bin/pytest" ]]; then
      (cd "$app_dir" && uv run --python "$app_dir/.venv/bin/python" pytest) || true
    elif command -v pytest >/dev/null 2>&1; then
      (cd "$app_dir" && uv run pytest) || true
    else
      echo "Skipping $app_dir (no pytest available)"
    fi
  done <<< "$app_list"
fi
