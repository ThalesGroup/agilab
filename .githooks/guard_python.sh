# Shared interpreter selection for agilab git hooks. Sourced, not executed.
#
# Hooks must also work in fresh worktrees that have no .venv yet: a bare
# `uv run` there bootstraps the full project environment from scratch, which
# fails on interpreters without prebuilt wheels (e.g. free-threaded CPython
# building polars from source). Prefer the project environment when it
# exists, then the main checkout's environment, then plain python3 for the
# stdlib-only guards.
run_guard_python() {
  if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
    uv --preview-features extra-build-dependencies run python "$@"
    return
  fi
  local common_dir main_root
  common_dir="$(git -C "$ROOT_DIR" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
  main_root="${common_dir%/.git}"
  if [[ -n "$main_root" && "$main_root" != "$ROOT_DIR" && -x "$main_root/.venv/bin/python" ]]; then
    echo "[agilab hooks] no local .venv; using main checkout interpreter at $main_root/.venv" >&2
    "$main_root/.venv/bin/python" "$@"
    return
  fi
  echo "[agilab hooks] no project venv found; falling back to python3" >&2
  python3 "$@"
}
