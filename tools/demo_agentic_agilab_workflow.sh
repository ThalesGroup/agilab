#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'EOF'
Usage:
  tools/demo_agentic_agilab_workflow.sh [--agent codex] [--prompt TEXT] [--base origin/main]
  tools/demo_agentic_agilab_workflow.sh [--output-root DIR] [--dry-run] [--include-command-args]

What it demonstrates:
  1. Tokki/repo session preflight.
  2. AGILAB context routing for the task and changed files.
  3. AGILAB impact validation for the same changed files.
  4. A traced agilab agent-run evidence manifest.
  5. Handoff, next-action, validation, and context cards for another agent.

The generated evidence is written under artifacts/demo_media/agentic-workflow/evidence/
by default, which is ignored by Git.
EOF
  exit 0
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

AGENT="codex"
BASE="origin/main"
PROMPT="demo an agentic AGILAB workflow for the current changed files"
OUTPUT_ROOT="$ROOT/artifacts/demo_media/agentic-workflow/evidence"
DRY_RUN="0"
INCLUDE_COMMAND_ARGS="0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --agent)
      AGENT="$2"
      shift 2
      ;;
    --prompt)
      PROMPT="$2"
      shift 2
      ;;
    --base)
      BASE="$2"
      shift 2
      ;;
    --output-root)
      OUTPUT_ROOT="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN="1"
      shift
      ;;
    --include-command-args)
      INCLUDE_COMMAND_ARGS="1"
      shift
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 2
      ;;
  esac
done

UV=(uv --preview-features extra-build-dependencies run)
PY=("${UV[@]}" python)
AGILAB=("${UV[@]}" agilab)

CHANGED_FILES=()
while IFS= read -r path; do
  if [[ -n "$path" ]]; then
    CHANGED_FILES+=("$path")
  fi
done < <(
  {
    git diff --name-only
    git diff --cached --name-only
    git ls-files --others --exclude-standard
  } | sort -u
)

ROUTER_FILES=()
IMPACT_ARGS=()
if [[ ${#CHANGED_FILES[@]} -gt 0 ]]; then
  ROUTER_FILES=("${CHANGED_FILES[@]}")
  IMPACT_ARGS=(--files "${CHANGED_FILES[@]}")
else
  ROUTER_FILES=(tools/agent_workflows.md docs/source/agent-workflows.rst)
  IMPACT_ARGS=(--base "$BASE")
fi

STAMP="$(date +%Y%m%d-%H%M%S)"
BRANCH="$(git branch --show-current 2>/dev/null || true)"
if [[ -z "$BRANCH" ]]; then
  BRANCH="detached"
fi
RUN_ID="agentic-agilab-workflow-${STAMP}"
RUN_DIR="$OUTPUT_ROOT/$RUN_ID"
mkdir -p "$RUN_DIR"

echo "== 1. Tokki session preflight =="
if command -v tokki-gate >/dev/null 2>&1; then
  tokki-gate session-start || true
else
  echo "tokki-gate not found; continuing with AGILAB-native routing."
fi

echo
echo "== 2. AGILAB worktree scope =="
if [[ -x ./dev ]]; then
  ./dev scope || true
else
  git status --short --branch
fi

echo
echo "== 3. Context router =="
"${PY[@]}" tools/agent_context_router.py \
  --files "${ROUTER_FILES[@]}" \
  --prompt "$PROMPT" \
  --json | tee "$RUN_DIR/context_router.json"

echo
echo "== 4. Impact validation =="
"${PY[@]}" tools/impact_validate.py "${IMPACT_ARGS[@]}" | tee "$RUN_DIR/impact_validate.txt"

AGENT_RUN_ARGS=(
  --agent "$AGENT"
  --label "AGILAB agentic workflow demo"
  --run-id "$RUN_ID"
  --output-dir "$RUN_DIR"
  --cwd "$ROOT"
  --permission-level standard
  --allow-failure
  --tag demo
  --tag agentic-workflow
  --metadata "repo=agilab"
  --metadata "branch=$BRANCH"
  --metadata "changed_files=${#CHANGED_FILES[@]}"
  --protocol-adapter mcp
  --capability evidence-review
  --json
)

if [[ "$DRY_RUN" == "1" ]]; then
  AGENT_RUN_ARGS+=(--print-only)
fi

if [[ "$INCLUDE_COMMAND_ARGS" == "1" ]]; then
  AGENT_RUN_ARGS+=(--include-command-args)
fi

TRACE_COMMAND=("${UV[@]}" python tools/impact_validate.py "${IMPACT_ARGS[@]}" --json)

echo
echo "== 5. Agent-run evidence =="
"${AGILAB[@]}" agent-run "${AGENT_RUN_ARGS[@]}" -- "${TRACE_COMMAND[@]}" \
  | tee "$RUN_DIR/agent_run_manifest.printed.json"

if [[ "$DRY_RUN" != "1" ]]; then
  echo
  echo "== 6. Read-side evidence cards =="
  "${AGILAB[@]}" agent-run validate "$RUN_DIR" --json | tee "$RUN_DIR/agent_run_validation.json"
  "${AGILAB[@]}" agent-run handoff "$RUN_DIR" | tee "$RUN_DIR/agent_handoff.md"
  "${AGILAB[@]}" agent-run next "$RUN_DIR" --json | tee "$RUN_DIR/agent_next_actions.json"
  "${AGILAB[@]}" agent-run context \
    --root "$OUTPUT_ROOT" \
    --agent "$AGENT" \
    --tag agentic-workflow \
    --limit 5 \
    --json | tee "$RUN_DIR/agent_context.json"
fi

echo
echo "Demo evidence directory: $RUN_DIR"
