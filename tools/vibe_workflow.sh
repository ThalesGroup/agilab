#!/usr/bin/env bash
set -euo pipefail
set -o pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT_DIR/log/vibe"
VIBE_COMMAND="${AGILAB_VIBE_COMMAND:-vibe}"

usage() {
  cat <<'USAGE'
Usage:
  ./tools/vibe_workflow.sh chat [vibe-arg...]
  ./tools/vibe_workflow.sh exec "<prompt>"
  ./tools/vibe_workflow.sh review ["<prompt>"]
  ./tools/vibe_workflow.sh setup
  ./tools/vibe_workflow.sh help

Environment:
  AGILAB_VIBE_COMMAND  Vibe executable to run
                       Default: vibe

Notes:
  - Interactive chat runs in the repo root without tee-based logging.
  - Non-interactive modes log to log/vibe/<mode>-YYYYmmdd-HHMMSS.log
  - Programmatic mode delegates to Vibe's documented vibe "<prompt>" command shape.
  - Model/provider selection stays in Vibe's own ~/.vibe/config.toml.
USAGE
}

require_vibe() {
  if ! command -v "$VIBE_COMMAND" >/dev/null 2>&1; then
    echo "error: '$VIBE_COMMAND' is not on PATH. Install mistral-vibe or set AGILAB_VIBE_COMMAND." >&2
    exit 127
  fi
}

log_and_run() {
  local mode="$1"
  shift
  mkdir -p "$LOG_DIR"
  local log_file="$LOG_DIR/${mode}-$(date +"%Y%m%d-%H%M%S").log"
  local full_cmd=("$VIBE_COMMAND" "$@")

  set +e
  {
    printf "[vibe-workflow] executing:"
    printf " %q" "${full_cmd[@]}"
    echo
    echo "[vibe-workflow] log: $log_file"
  } | tee "$log_file"

  (
    cd "$ROOT_DIR"
    "$VIBE_COMMAND" "$@"
  ) 2>&1 | tee -a "$log_file"
  local status=${PIPESTATUS[0]}
  set -e

  if (( status != 0 )); then
    echo "[vibe-workflow] command failed (exit $status)" | tee -a "$log_file" >&2
    return $status
  fi
}

run_interactive() {
  cd "$ROOT_DIR"
  exec "$VIBE_COMMAND" "$@"
}

MODE="${1:-help}"
shift || true

case "$MODE" in
  chat)
    require_vibe
    run_interactive "$@"
    ;;
  exec)
    if [[ -z "${1:-}" ]]; then
      echo "error: exec requires a prompt" >&2
      usage
      exit 1
    fi
    require_vibe
    prompt="$1"
    log_and_run exec "$prompt"
    ;;
  review)
    require_vibe
    prompt="${1:-Review the current repo state for bugs, regressions, and missing tests. Findings first.}"
    log_and_run review "$prompt"
    ;;
  setup)
    require_vibe
    cd "$ROOT_DIR"
    exec "$VIBE_COMMAND" --setup
    ;;
  help|--help|-h)
    usage
    ;;
  *)
    echo "error: unknown mode '$MODE'" >&2
    usage
    exit 1
    ;;
esac
