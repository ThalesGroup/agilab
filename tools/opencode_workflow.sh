#!/usr/bin/env bash
set -euo pipefail
set -o pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT_DIR/log/opencode"
DEFAULT_MODEL="${AGILAB_OPENCODE_MODEL:-ollama/qwen2.5-coder:latest}"
DEFAULT_AGENT="${AGILAB_OPENCODE_AGENT:-agilab-build}"
REVIEW_AGENT="${AGILAB_OPENCODE_REVIEW_AGENT:-agilab-review}"

COMMON_ARGS=(
  "--model" "$DEFAULT_MODEL"
)

usage() {
  cat <<'USAGE'
Usage:
  ./tools/opencode_workflow.sh chat
  ./tools/opencode_workflow.sh exec "<prompt>"
  ./tools/opencode_workflow.sh review ["<prompt>"]
  ./tools/opencode_workflow.sh help

Environment:
  AGILAB_OPENCODE_MODEL         Model to pass as provider/model
                                Default: ollama/qwen2.5-coder:latest
  AGILAB_OPENCODE_AGENT         Primary agent name
                                Default: agilab-build
  AGILAB_OPENCODE_REVIEW_AGENT  Review agent name
                                Default: agilab-review

Notes:
  - Interactive chat runs in the repo root without tee-based logging.
  - Non-interactive modes log to log/opencode/<mode>-YYYYmmdd-HHMMSS.log
  - Project config comes from opencode.json and .opencode/agents/
USAGE
}

log_and_run() {
  local mode="$1"
  shift
  mkdir -p "$LOG_DIR"
  local log_file="$LOG_DIR/${mode}-$(date +"%Y%m%d-%H%M%S").log"
  local full_cmd=(opencode "$@")

  set +e
  {
    printf "[opencode-workflow] executing:"
    printf " %q" "${full_cmd[@]}"
    echo
    echo "[opencode-workflow] log: $log_file"
  } | tee "$log_file"

  (
    cd "$ROOT_DIR"
    opencode "$@"
  ) 2>&1 | tee -a "$log_file"
  local status=${PIPESTATUS[0]}
  set -e

  if (( status != 0 )); then
    echo "[opencode-workflow] command failed (exit $status)" | tee -a "$log_file" >&2
    return $status
  fi
}

run_interactive() {
  cd "$ROOT_DIR"
  exec opencode "${COMMON_ARGS[@]}" --agent "$DEFAULT_AGENT"
}

MODE="${1:-help}"
shift || true

case "$MODE" in
  chat)
    run_interactive
    ;;
  exec)
    if [[ -z "${1:-}" ]]; then
      echo "error: exec requires a prompt" >&2
      usage
      exit 1
    fi
    prompt="$1"
    log_and_run exec run "${COMMON_ARGS[@]}" --agent "$DEFAULT_AGENT" "$prompt"
    ;;
  review)
    prompt="${1:-Review the current repo state for bugs, regressions, and missing tests. Findings first.}"
    log_and_run review run "${COMMON_ARGS[@]}" --agent "$REVIEW_AGENT" "$prompt"
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
