#!/usr/bin/env bash

# Prevent accidental pushes of local-only AGI app configuration changes.
# The script toggles Git's skip-worktree flag for app config files so they stay
# local until explicitly unlocked. It targets every tracked
# `app_args_form.py`, `app_settings.toml`, and `pre_prompt.json` file under
# `src/agilab/apps/**`.

set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  tools/preserve_app_configs.sh lock    # keep local changes out of commits/pushes
  tools/preserve_app_configs.sh unlock  # allow the files to be tracked again
  tools/preserve_app_configs.sh status  # show current skip-worktree state

The script uses `git update-index --skip-worktree` so modifications remain local.
Run `unlock` before committing if you intentionally want to push changes.
EOF
}

ensure_repo_root() {
  if ! git rev-parse --show-toplevel >/dev/null 2>&1; then
    echo "error: this script must run inside a Git repository" >&2
    exit 1
  fi
}

target_files() {
  git ls-files \
    | awk '/^src\/agilab\/apps\/.*(app_args_form\.py|app_settings\.toml|pre_prompt\.json)$/'
}

lock_files() {
  local applied=0
  while IFS= read -r file; do
    git update-index --skip-worktree "$file"
    echo "locked : $file"
    applied=1
  done < <(target_files)
  if [[ $applied -eq 0 ]]; then
    echo "no tracked files matched the preservation list" >&2
  fi
}

unlock_files() {
  local applied=0
  while IFS= read -r file; do
    git update-index --no-skip-worktree "$file"
    echo "unlocked: $file"
    applied=1
  done < <(target_files)
  if [[ $applied -eq 0 ]]; then
    echo "no tracked files matched the preservation list" >&2
  fi
}

show_status() {
  while IFS= read -r file; do
    local info
    info=$(git ls-files -v "$file" | awk '{print $1}')
    case "$info" in
      S*|s*) echo "locked : $file" ;;
      *)     echo "unlocked: $file" ;;
    esac
  done < <(target_files)
}

main() {
  ensure_repo_root
  local cmd="${1:-}"
  case "$cmd" in
    lock)
      lock_files
      ;;
    unlock)
      unlock_files
      ;;
    status)
      show_status
      ;;
    ""|-h|--help|help)
      usage
      ;;
    *)
      echo "error: unknown command '$cmd'" >&2
      usage
      exit 1
      ;;
  esac
}

main "$@"
