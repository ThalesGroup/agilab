#!/usr/bin/env bash
set -euo pipefail
set -o pipefail

# Professional Codex CLI wrapper for this repository.
# - review: run Codex code review on current working tree
# - exec: ask Codex to implement a change
# - apply: apply a previously generated task diff by id

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT_DIR/log/codex"
MODEL_ARGS=()
PROFILE_ARGS=()

if [[ -n "${CODEX_CLI_MODEL:-}" ]]; then
  MODEL_ARGS+=("-m" "$CODEX_CLI_MODEL")
fi

if [[ -n "${CODEX_CLI_PROFILE:-}" ]]; then
  PROFILE_ARGS+=("-p" "$CODEX_CLI_PROFILE")
fi

COMMON_ARGS=(
  "-C" "$ROOT_DIR"
  "-a" "on-request"
  "-s" "workspace-write"
)

if (( ${#MODEL_ARGS[@]} > 0 )); then
  COMMON_ARGS+=("${MODEL_ARGS[@]}")
fi

if (( ${#PROFILE_ARGS[@]} > 0 )); then
  COMMON_ARGS+=("${PROFILE_ARGS[@]}")
fi

usage() {
  cat <<'USAGE'
Usage:
  ./tools/codex_workflow.sh review [review-args...]
  ./tools/codex_workflow.sh exec "<prompt>" [exec-args...]
  ./tools/codex_workflow.sh apply <task-id>
  ./tools/codex_workflow.sh help

Environment:
  CODEX_CLI_MODEL   Optional model override passed as -m to codex
  CODEX_CLI_PROFILE Optional profile override passed as -p to codex

Notes:
  - Logs are written to log/codex/<mode>-YYYYmmdd-HHMMSS.log
  - Uses sandboxed workspace-write mode with on-request approvals by default
USAGE
}

log_and_run() {
  local mode="$1"
  shift
  mkdir -p "$LOG_DIR"
  local log_file="$LOG_DIR/${mode}-$(date +"%Y%m%d-%H%M%S").log"
  local full_cmd=(codex "$@")

  set +e
  {
    printf "[codex-workflow] executing:"
    printf " %q" "${full_cmd[@]}"
    echo
    echo "[codex-workflow] log: $log_file"
  } | tee "$log_file"

  codex "$@" 2>&1 | tee -a "$log_file"
  local status=${PIPESTATUS[0]}
  set -e

  if (( status != 0 )); then
    echo "[codex-workflow] command failed (exit $status)" | tee -a "$log_file" >&2
    return $status
  fi
}

MODE="${1:-help}"
shift || true

case "$MODE" in
  review)
    log_and_run review "${COMMON_ARGS[@]}" review --uncommitted "$@"
    ;;
  exec)
    log_and_run exec "${COMMON_ARGS[@]}" exec "$@"
    ;;
  apply)
    if [[ -z "${1:-}" ]]; then
      echo "error: apply requires task id" >&2
      usage
      exit 1
    fi
    log_and_run apply "${COMMON_ARGS[@]}" apply "$1"
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
