#!/usr/bin/env bash
set -euo pipefail
set -o pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT_DIR/log/aider"
CONFIG_FILE="$ROOT_DIR/.aider.conf.yml"
DEFAULT_MODEL="${AGILAB_AIDER_MODEL:-qwen-local}"

COMMON_ARGS=(
  "--config" "$CONFIG_FILE"
  "--model" "$DEFAULT_MODEL"
)

usage() {
  cat <<'USAGE'
Usage:
  ./tools/aider_workflow.sh chat [file...]
  ./tools/aider_workflow.sh exec "<prompt>" [file...]
  ./tools/aider_workflow.sh review [file...]
  ./tools/aider_workflow.sh help

Environment:
  AGILAB_AIDER_MODEL  Model or alias to pass to aider --model
                      Default: qwen-local

Notes:
  - Interactive chat runs in the repo root without tee-based logging.
  - Non-interactive modes log to log/aider/<mode>-YYYYmmdd-HHMMSS.log
  - Repo defaults come from .aider.conf.yml
USAGE
}

log_and_run() {
  local mode="$1"
  shift
  mkdir -p "$LOG_DIR"
  local log_file="$LOG_DIR/${mode}-$(date +"%Y%m%d-%H%M%S").log"
  local full_cmd=(aider "$@")

  set +e
  {
    printf "[aider-workflow] executing:"
    printf " %q" "${full_cmd[@]}"
    echo
    echo "[aider-workflow] log: $log_file"
  } | tee "$log_file"

  (
    cd "$ROOT_DIR"
    aider "$@"
  ) 2>&1 | tee -a "$log_file"
  local status=${PIPESTATUS[0]}
  set -e

  if (( status != 0 )); then
    echo "[aider-workflow] command failed (exit $status)" | tee -a "$log_file" >&2
    return $status
  fi
}

run_interactive() {
  cd "$ROOT_DIR"
  exec aider "${COMMON_ARGS[@]}" "$@"
}

MODE="${1:-help}"
shift || true

case "$MODE" in
  chat)
    run_interactive "$@"
    ;;
  exec)
    if [[ -z "${1:-}" ]]; then
      echo "error: exec requires a prompt" >&2
      usage
      exit 1
    fi
    prompt="$1"
    shift
    log_and_run exec "${COMMON_ARGS[@]}" --message "$prompt" "$@"
    ;;
  review)
    log_and_run review "${COMMON_ARGS[@]}" --message "/ask Review the supplied files or repo context for bugs, regressions, and missing tests. Findings first." "$@"
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
