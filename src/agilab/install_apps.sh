#!/bin/bash
set -e
set -o pipefail

# --- Ensure arrays exist (avoids 'unbound variable' with set -u) -------------
# We declare them empty up front; later code can append or overwrite freely.
# This prevents errors like: ${REPOSITORY_PAGES[@]}: unbound variable
declare -a BUILTIN_PAGES=()
declare -a REPOSITORY_PAGES=()
BUILTIN_APPS_ENV="${BUILTIN_APPS:-}"
unset BUILTIN_APPS
declare -a BUILTIN_APPS=(
  mycode_project
  flight_project
  uav_relay_queue_project
)
declare -a REPOSITORY_APPS=()
declare -a INVALID_REPOSITORY_APPS=()

declare -a DEFAULT_APPS_ORDER=(
  flight_project
  flight_trajectory_project
  flowsynth_project
  ilp_project
  link_sim_project
  mycode_project
  network_sim_project
  rssi_predictor_project
  satcom_sim_project
  sat_trajectory_project
  sb3_trainer_project
  uav_relay_queue_project
)

declare -a DEFAULT_SELECTED_APPS=(
  flight_project
  mycode_project
  sat_trajectory_project
  flight_trajectory_project
  link_sim_project
  network_sim_project
  ilp_project
  sb3_trainer_project
)

declare -a INCLUDED_APPS=()
declare -a INCLUDED_PAGES=()
declare -a SKIPPED_APP_TESTS=()
DATA_CHECK_MESSAGE=""
DATA_URI_PATH=""
PROMPT_FOR_APPS=1
FORCE_APP_SELECTION=0
FORCE_ALL_APPS=0
ALL_APPS_SENTINEL="${INSTALL_ALL_SENTINEL:-__AGILAB_ALL_APPS__}"
BUILTIN_ONLY_SENTINEL="${INSTALL_BUILTIN_SENTINEL:-__AGILAB_BUILTIN_APPS__}"
NEED_APP_DISCOVERY=1
FORCE_BUILTIN_ONLY=0
FILTER_BUILTINS_BY_DEFAULT=1
declare -a BUILTIN_SKIP_BY_DEFAULT=()
INSTALLED_APPS_FILE="${INSTALLED_APPS_FILE:-$HOME/.local/share/agilab/installed_apps.txt}"


# Load env + normalize Python version
# shellcheck source=/dev/null
source "$HOME/.local/share/agilab/.env"

# Colors for output
RED='\033[1;31m'
GREEN='\033[1;32m'
BLUE='\033[1;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

START_TIME=$(date +%s)

UV_PREVIEW=(uv --preview-features extra-build-dependencies)

DO_TEST_APPS=0
LINK_COMPATIBLE_VENVS="${AGILAB_LINK_COMPATIBLE_VENVS:-1}"

BUILTIN_PAGES_FROM_ENV="${BUILTIN_PAGES-}"
BUILTIN_APPS_FROM_ENV="${BUILTIN_APPS_ENV-}"

AGI_PYTHON_VERSION=$(echo "${AGI_PYTHON_VERSION:-}" | sed -E 's/^([0-9]+\.[0-9]+\.[0-9]+(\+freethreaded)?).*/\1/')
AGILAB_REPO="$(cat "$HOME/.local/share/agilab/.agilab-path")"
VENV_LINK_REPORT="${AGILAB_VENV_LINK_REPORT:-$HOME/.local/share/agilab/venv_link_report.json}"
APPS_REPOSITORY="${APPS_REPOSITORY:-}"
CORE_EDITABLE_PACKAGES=(
  --with-editable "$AGILAB_REPO/core/agi-env"
  --with-editable "$AGILAB_REPO/lib/agi-gui"
  --with-editable "$AGILAB_REPO/core/agi-node"
  --with-editable "$AGILAB_REPO/core/agi-cluster"
  --with-editable "$AGILAB_REPO/core/agi-core"
)

PAGES_TARGET_BASE=""
APPS_TARGET_BASE=""
SKIP_REPOSITORY_APPS=1
SKIP_REPOSITORY_PAGES=1

# (macOS-safe helpers remain below)
# --- Helpers -----------------------------------------------------------------
# parse_list_to_array <array_var_name> <raw_string>
# Accepts comma/semicolon/whitespace/newline-delimited strings and fills array.
# Avoids `mapfile` for macOS' older Bash (3.2). No GNU-only flags required.
parse_list_to_array() {
  local __out="$1"; shift || true
  local raw="${1-}"
  local -a __items=()
  local line q qitems=""
  # Normalize delimiters to one-per-line, drop empties
  while IFS= read -r line; do
    [[ -n "$line" ]] && __items+=("$line")
  done < <(
    printf '%s\n' "$raw" \
      | tr ',;' '\n' \
      | tr -s '[:space:]' '\n' \
      | sed '/^$/d'
  )
  # Safely assign to the named array (portable to Bash 3.2)
  for line in "${__items[@]}"; do
    printf -v q '%q' "$line"
    qitems+=" $q"
  done
  # shellcheck disable=SC2086
  eval "$__out=($qitems)"
}

discover_repo_dir() {
  local root="$1"
  local name="$2"
  local candidate
  [[ -z "$root" ]] && return 1

  # Prefer the direct repository child first. Recursive discovery is only a
  # fallback for older layouts that keep the real tree under a nested mirror.
  for candidate in "$root/$name" "$root/src/agilab/$name"; do
    [[ -d "$candidate" ]] || continue
    if [[ "$name" == "apps" ]]; then
      if find "$candidate" -maxdepth 1 -type d -name '*_project' -print -quit | grep -q .; then
        printf '%s\n' "$candidate"
        return 0
      fi
    elif [[ "$name" == "apps-pages" ]]; then
      if find "$candidate" -maxdepth 1 -type d ! -name '.venv' -print -quit | grep -q .; then
        printf '%s\n' "$candidate"
        return 0
      fi
    else
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  while IFS= read -r candidate; do
    [[ -z "$candidate" ]] && continue
    if [[ "$name" == "apps" ]]; then
      if find "$candidate" -maxdepth 1 -type d -name '*_project' -print -quit | grep -q .; then
        printf '%s\n' "$candidate"
        return 0
      fi
    elif [[ "$name" == "apps-pages" ]]; then
      if find "$candidate" -maxdepth 1 -type d ! -name '.venv' -print -quit | grep -q .; then
        printf '%s\n' "$candidate"
        return 0
      fi
    else
      printf '%s\n' "$candidate"
      return 0
    fi
  done < <(find "$root" -maxdepth 5 -type d -name "$name" -print 2>/dev/null)
  return 1
}

resolve_physical_dir() {
  (cd "$1" >/dev/null 2>&1 && pwd -P)
}

is_truthy() {
  local raw
  raw="$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]')"
  case "$raw" in
    1|true|yes|on|enabled) return 0 ;;
    *) return 1 ;;
  esac
}

apps_repository_in_allowlist() {
  local repo="$1"
  local physical_repo="$2"
  local raw_allowlist="${AGILAB_APPS_REPOSITORY_ALLOWLIST:-}"
  local -a entries=()
  local entry physical_entry

  [[ -n "${raw_allowlist//[[:space:],;]/}" ]] || return 1
  parse_list_to_array entries "$raw_allowlist"
  for entry in "${entries[@]}"; do
    [[ -z "$entry" ]] && continue
    if [[ "$entry" == "$repo" || "$entry" == "$physical_repo" ]]; then
      return 0
    fi
    if [[ -e "$entry" ]]; then
      physical_entry="$(resolve_physical_dir "$entry" 2>/dev/null || true)"
      if [[ -n "$physical_entry" && "$physical_entry" == "$physical_repo" ]]; then
        return 0
      fi
    fi
  done
  return 1
}

validate_apps_repository_policy() {
  local repo="$1"
  local physical_repo=""
  local strict=0
  local allow_floating=0
  local head_ref=""
  local tag_ref=""

  [[ -n "$repo" ]] || return 0
  physical_repo="$(resolve_physical_dir "$repo" 2>/dev/null || printf '%s' "$repo")"
  if is_truthy "${AGILAB_STRICT_APPS_REPOSITORY:-}" || is_truthy "${AGILAB_SHARED_MODE:-}"; then
    strict=1
  fi
  if is_truthy "${AGILAB_ALLOW_FLOATING_APPS_REPOSITORY:-}" || is_truthy "${AGILAB_DEV_APPS_REPOSITORY:-}"; then
    allow_floating=1
  fi

  if (( strict )); then
    if [[ -z "${AGILAB_APPS_REPOSITORY_ALLOWLIST:-}" ]]; then
      echo -e "${RED}Error:${NC} Strict APPS_REPOSITORY mode requires AGILAB_APPS_REPOSITORY_ALLOWLIST." >&2
      exit 1
    fi
    if ! apps_repository_in_allowlist "$repo" "$physical_repo"; then
      echo -e "${RED}Error:${NC} APPS_REPOSITORY is not in AGILAB_APPS_REPOSITORY_ALLOWLIST: $repo" >&2
      exit 1
    fi
  elif [[ -n "${AGILAB_APPS_REPOSITORY_ALLOWLIST:-}" ]] && ! apps_repository_in_allowlist "$repo" "$physical_repo"; then
    echo -e "${YELLOW}Warning:${NC} APPS_REPOSITORY is not in AGILAB_APPS_REPOSITORY_ALLOWLIST: $repo" >&2
  fi

  if ! git -C "$repo" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    if (( strict )); then
      echo -e "${RED}Error:${NC} Strict APPS_REPOSITORY mode requires a Git checkout pinned to a commit SHA or immutable tag." >&2
      exit 1
    fi
    echo -e "${YELLOW}Warning:${NC} APPS_REPOSITORY is not a Git checkout; review it before shared use." >&2
    return 0
  fi

  head_ref="$(git -C "$repo" symbolic-ref -q --short HEAD 2>/dev/null || true)"
  if [[ -n "$head_ref" ]]; then
    if (( strict && ! allow_floating )); then
      echo -e "${RED}Error:${NC} APPS_REPOSITORY is on floating branch '$head_ref'. Checkout a reviewed commit SHA or immutable tag, or set AGILAB_DEV_APPS_REPOSITORY=1 for an explicit dev install." >&2
      exit 1
    fi
    echo -e "${YELLOW}Warning:${NC} APPS_REPOSITORY is on floating branch '$head_ref'; pin to a reviewed commit or immutable tag before shared use." >&2
    return 0
  fi

  tag_ref="$(git -C "$repo" describe --exact-match --tags HEAD 2>/dev/null || true)"
  if [[ -n "$tag_ref" ]]; then
    echo -e "${BLUE}APPS_REPOSITORY pinned to tag:${NC} $tag_ref"
  else
    echo -e "${BLUE}APPS_REPOSITORY pinned to detached commit:${NC} $(git -C "$repo" rev-parse --short HEAD 2>/dev/null || true)"
  fi
}

# Detect whether an application's data directory is reachable. Returns:
#   0 - data root accessible
#   2 - data root unavailable (e.g. NFS share offline)
# Other return codes bubble up for unexpected failures so callers can react.
app_dir_on_disk() {
  local rel="$1"
  local base="$AGILAB_REPO/apps"
  if [[ -d "$base/builtin/$rel" ]]; then
    printf '%s/builtin/%s' "$base" "$rel"
  else
    printf '%s/%s' "$base" "$rel"
  fi
}

app_has_required_sources() {
  local app_dir="$1"
  local app_name manager_name
  local pyproject manager worker

  app_name="$(basename -- "$app_dir")"
  manager_name="${app_name%_project}"

  pyproject="$app_dir/pyproject.toml"
  manager="$app_dir/src/$manager_name/$manager_name.py"
  worker="$app_dir/src/${manager_name}_worker/${manager_name}_worker.py"

  [[ -f "$pyproject" && -f "$manager" && -f "$worker" ]]
}

page_has_required_sources() {
  local page_dir="$1"
  local page_name pyproject source_match

  page_name="$(basename -- "$page_dir")"
  case "$page_name" in
    ""|.*|.venv|__pycache__|templates|*.previous.*)
      return 1
      ;;
  esac

  pyproject="$page_dir/pyproject.toml"
  [[ -f "$pyproject" ]] || return 1
  grep -Fq '[project.entry-points."agilab.pages"]' "$pyproject" || return 1

  if [[ -f "$page_dir/$page_name.py" || -f "$page_dir/main.py" || -f "$page_dir/app.py" ]]; then
    return 0
  fi
  if [[ -f "$page_dir/src/$page_name/$page_name.py" \
     || -f "$page_dir/src/$page_name/main.py" \
     || -f "$page_dir/src/$page_name/app.py" ]]; then
    return 0
  fi

  source_match="$(
    find "$page_dir/src" \
      -mindepth 2 \
      -maxdepth 2 \
      -type f \
      \( -name "${page_name}.py" -o -name "view_*.py" -o -name "main.py" -o -name "app.py" \) \
      -print -quit 2>/dev/null || true
  )"
  [[ -n "$source_match" ]]
}

app_has_collectable_pytests() {
  local app_dir="${1:-.}"

  find "$app_dir/test" "$app_dir/tests" \
    -type f \
    \( -name 'test_*.py' -o -name '*_test.py' \) \
    -print -quit 2>/dev/null | grep -q .
}

check_data_mount() {
  local app="$1"
  local app_path
  app_path="$(app_dir_on_disk "$app")"
  local output rc marker

  DATA_CHECK_MESSAGE=""
  DATA_URI_PATH=""

  if ! output=$(
    "${UV_PREVIEW[@]}" -q run -p "$AGI_PYTHON_VERSION" --project ../core/agi-cluster python - "$app_path" <<'PY' 2>&1
from pathlib import Path
import sys
from agi_env import AgiEnv

app_path = Path(sys.argv[1])
try:
    env = AgiEnv(apps_path=app_path.parent, app=app_path.name, verbose=0)
except FileNotFoundError as exc:
    sys.stdout.write(f"DATA_UNAVAILABLE::{exc}")
    sys.exit(3)
except Exception as exc:
    sys.stdout.write(f"DATA_ERROR::{type(exc).__name__}:{exc}")
    sys.exit(4)
else:
    data_root = (env.home_abs / env.data_rel).expanduser()
    sys.stdout.write(f"DATA_OK::{data_root}")
PY
  ); then
    rc=$?
    marker=$(printf '%s\n' "$output" | tail -n 1)
    if [[ "$marker" == DATA_UNAVAILABLE::* ]]; then
      DATA_CHECK_MESSAGE="${marker#DATA_UNAVAILABLE::}"
      return 2
    fi
    if [[ "$marker" == DATA_ERROR::* ]]; then
      DATA_CHECK_MESSAGE="${marker#DATA_ERROR::}"
      return $rc
    fi
    DATA_CHECK_MESSAGE="$marker"
    return $rc
  fi

  marker=$(printf '%s\n' "$output" | tail -n 1)
  if [[ "$marker" == DATA_OK::* ]]; then
    DATA_URI_PATH="${marker#DATA_OK::}"
    return 0
  fi

  DATA_CHECK_MESSAGE="$marker"
  return 0
}

usage() {
  cat <<'EOF'
Usage: install_apps.sh [--test-apps]
  --test-apps      Run pytest for each app after installation (implies --install-apps)
  --link-compatible-venvs
                   Link app/page/worker venvs to compatible larger envs after install (default)
  --no-link-compatible-venvs
                   Disable compatible venv linking
  --help           Show this message and exit
EOF
}


while [[ $# -gt 0 ]]; do
  case "$1" in
    --test-apps) DO_TEST_APPS=1;;
    --link-compatible-venvs) LINK_COMPATIBLE_VENVS=1;;
    --no-link-compatible-venvs) LINK_COMPATIBLE_VENVS=0;;
    --help|-h) usage; exit 0;;
    *)
      echo -e "${RED}Error:${NC} Unknown option '$1'" >&2
      usage
      exit 1
      ;;
  esac
  shift
done

# Return 0 if the needle exists in the haystack list.
in_list() {
  local needle="$1"; shift
  local item
  for item in "$@"; do
    [[ "$item" == "$needle" ]] && return 0
  done
  return 1
}

if [[ -n "$APPS_REPOSITORY" ]]; then
  validate_apps_repository_policy "$APPS_REPOSITORY"
  if PAGES_TARGET_BASE=$(discover_repo_dir "$APPS_REPOSITORY" "apps-pages"); then
    SKIP_REPOSITORY_PAGES=0
  else
    echo -e "${BLUE}apps-pages not present under $APPS_REPOSITORY; repository pages will be skipped.${NC}"
  fi
  if APPS_TARGET_BASE=$(discover_repo_dir "$APPS_REPOSITORY" "apps"); then
    SKIP_REPOSITORY_APPS=0
  else
    echo -e "${BLUE}apps not present under $APPS_REPOSITORY; repository apps will be skipped.${NC}"
  fi
  if (( SKIP_REPOSITORY_APPS && SKIP_REPOSITORY_PAGES )); then
    echo -e "${RED}Error:${NC} Neither 'apps' nor 'apps-pages' directories were found under $APPS_REPOSITORY" >&2
    exit 1
  fi
fi


# Append items to the referenced array, ensuring uniqueness while preserving order.
append_unique() {
  local __name="$1"
  shift
  local item existing
  # shellcheck disable=SC1083,SC2086
  eval "set -- \${${__name}[@]}"
  local current=("$@")
  shift $(( $# )) 2>/dev/null || true
  local new_items=("$@")

  for item in "${new_items[@]}"; do
    [[ -z "$item" ]] && continue
    for existing in "${current[@]}"; do
      [[ "$existing" == "$item" ]] && continue 2
    done
    current+=("$item")
  done

  printf -v "${__name}" '%s ' "${current[@]}"
  # Trim trailing space
  # shellcheck disable=SC2086
  eval "${__name}=(\${${__name}%% })"
}

backup_existing_path() {
  local path="$1"
  local stamp backup suffix
  stamp="$(date +%Y%m%d%H%M%S)"
  backup="${path}.previous.${stamp}"
  suffix=0
  while [[ -e "$backup" || -L "$backup" ]]; do
    suffix=$((suffix + 1))
    backup="${path}.previous.${stamp}.${suffix}"
  done
  mv -- "$path" "$backup"
  printf '%s\n' "$backup"
}

refresh_repository_link() {
  local kind="$1"
  local dest="$2"
  local target="$3"
  local backup

  if [[ -L "$dest" ]]; then
    echo -e "${BLUE}${kind} '$dest' is a symlink. Recreating -> '$target'...${NC}"
    rm -f -- "$dest"
    ln -s -- "$target" "$dest"
  elif [[ ! -e "$dest" ]]; then
    echo -e "${BLUE}${kind} '$dest' does not exist. Creating symlink -> '$target'...${NC}"
    ln -s -- "$target" "$dest"
  else
    backup="$(backup_existing_path "$dest")"
    echo -e "${YELLOW}${kind} '$dest' exists and is not a symlink. Moved to '$backup' and linking -> '$target'.${NC}"
    ln -s -- "$target" "$dest"
  fi
}

unlink_linked_venv() {
  local venv_path="$1"
  local label="${2:-$1}"
  if [[ -L "$venv_path" ]]; then
    echo -e "${BLUE}Refreshing linked venv for ${label}: unlinking ${venv_path}.${NC}"
    rm -f -- "$venv_path"
  fi
}

link_compatible_venvs() {
  case "$LINK_COMPATIBLE_VENVS" in
    0|false|False|FALSE|no|No|NO)
      echo -e "${BLUE}Compatible venv linking disabled.${NC}"
      return 0
      ;;
  esac

  local linker="$AGILAB_REPO/venv_linker.py"
  if [[ ! -f "$linker" ]]; then
    echo -e "${YELLOW}Warning:${NC} compatible venv linker not found at $linker; keeping isolated venvs."
    return 0
  fi

  local -a root_paths=()
  local -a root_args=()
  local root existing duplicate
  for root in "$AGILAB_REPO/apps" "$AGILAB_REPO/apps-pages" "$APPS_TARGET_BASE" "$PAGES_TARGET_BASE" "$HOME/wenv"; do
    [[ -n "$root" && -d "$root" ]] || continue
    duplicate=0
    for existing in "${root_paths[@]}"; do
      [[ "$existing" == "$root" ]] && duplicate=1 && break
    done
    (( duplicate )) && continue
    root_paths+=("$root")
    root_args+=(--root "$root")
  done

  if (( ${#root_args[@]} == 0 )); then
    return 0
  fi

  mkdir -p -- "$(dirname "$VENV_LINK_REPORT")"
  echo -e "${BLUE}Linking compatible virtual environments...${NC}"
  if "${UV_PREVIEW[@]}" run -p "$AGI_PYTHON_VERSION" --no-project --with packaging python "$linker" \
    --apply \
    --report "$VENV_LINK_REPORT" \
    "${root_args[@]}"; then
    echo -e "${GREEN}Compatible venv link report:${NC} $VENV_LINK_REPORT"
  else
    echo -e "${YELLOW}Warning:${NC} compatible venv linking failed; keeping installed venvs."
  fi
}

# Destination base for creating local app symlinks (defaults to current dir)
: "${APPS_DEST_BASE:="$AGILAB_REPO/apps"}"
: "${PAGES_DEST_BASE:="$AGILAB_REPO/apps-pages"}"

mkdir -p -- "$APPS_DEST_BASE"
mkdir -p -- "$PAGES_DEST_BASE"
mkdir -p -- "$APPS_DEST_BASE/builtin"

BUILTIN_APPS_ROOT="$APPS_DEST_BASE/builtin"

APPS_DEST_REAL=$(resolve_physical_dir "$APPS_DEST_BASE")
PAGES_DEST_REAL=$(resolve_physical_dir "$PAGES_DEST_BASE")
APPS_TARGET_REAL=""
PAGES_TARGET_REAL=""

if (( SKIP_REPOSITORY_APPS == 0 )); then
  APPS_TARGET_REAL=$(resolve_physical_dir "$APPS_TARGET_BASE")
  if [[ "$APPS_DEST_REAL" == "$APPS_TARGET_REAL" ]]; then
    echo -e "${YELLOW}Warning:${NC} apps destination resolves inside the repository tree; skipping repository app symlink refresh to avoid self-links."\
    " (dest=$APPS_DEST_REAL)."
    SKIP_REPOSITORY_APPS=1
  fi
fi

if (( SKIP_REPOSITORY_PAGES == 0 )); then
  PAGES_TARGET_REAL=$(resolve_physical_dir "$PAGES_TARGET_BASE")
  if [[ "$PAGES_DEST_REAL" == "$PAGES_TARGET_REAL" ]]; then
    echo -e "${YELLOW}Warning:${NC} pages destination resolves inside the repository tree; skipping repository page symlink refresh to avoid self-links."\
    " (dest=$PAGES_DEST_REAL)."
    SKIP_REPOSITORY_PAGES=1
  fi
fi

echo -e "${BLUE}Using APPS_REPOSITORY:${NC} $APPS_REPOSITORY"
echo -e "${BLUE}(Apps) Destination base:${NC} $APPS_DEST_BASE"
echo -e "${BLUE}(Apps) Link target base:${NC} $APPS_TARGET_BASE"
echo -e "${BLUE}(Pages) Destination base:${NC} $PAGES_DEST_BASE"
echo -e "${BLUE}(Pages) Link target base:${NC} $PAGES_TARGET_BASE"

# --- BUILTIN_PAGES: allow manual override via env ----------------------------
# You can set BUILTIN_PAGES or BUILTIN_PAGES_OVERRIDE to a comma/space/newline
# separated list (e.g. "home dashboard,foo-view\nbar-view").
if [[ -n "${BUILTIN_PAGES_OVERRIDE-}" && -n "${BUILTIN_PAGES_OVERRIDE//[[:space:]]/}" ]]; then
  parse_list_to_array BUILTIN_PAGES "$BUILTIN_PAGES_OVERRIDE"
  echo -e "${BLUE}(Pages) Override enabled via BUILTIN_PAGES_OVERRIDE:${NC} ${BUILTIN_PAGES[*]}"
elif [[ -n "${BUILTIN_PAGES_FROM_ENV}" && -n "${BUILTIN_PAGES_FROM_ENV//[[:space:]]/}" ]]; then
  parse_list_to_array BUILTIN_PAGES "$BUILTIN_PAGES_FROM_ENV"
  echo -e "${BLUE}(Pages) Override enabled via BUILTIN_PAGES:${NC} ${BUILTIN_PAGES[*]}"
else
  while IFS= read -r -d '' dir; do
    dir_name="$(basename -- "$dir")"
    if page_has_required_sources "$dir" && [[ " ${BUILTIN_PAGES[@]-} " != *" ${dir_name} "* ]]; then
      BUILTIN_PAGES+=("$dir_name")
    fi
  done < <(find "$PAGES_DEST_BASE" -mindepth 1 -maxdepth 1 -type d -print0)
fi

if (( SKIP_REPOSITORY_PAGES == 0 )); then
  declare -a repository_pages_found=()
  while IFS= read -r -d '' dir; do
    if page_has_required_sources "$dir"; then
      repository_pages_found+=("$(basename -- "$dir")")
    fi
  done < <(find "$PAGES_TARGET_BASE" -mindepth 1 -maxdepth 1 -type d -print0)
  if (( ${#repository_pages_found[@]} )); then
    REPOSITORY_PAGES=("${repository_pages_found[@]}")
  else
    REPOSITORY_PAGES=()
  fi
fi

if (( SKIP_REPOSITORY_PAGES == 0 )); then
  INCLUDED_PAGES=(${BUILTIN_PAGES+"${BUILTIN_PAGES[@]}"} ${REPOSITORY_PAGES+"${REPOSITORY_PAGES[@]}"})
else
  INCLUDED_PAGES=(${BUILTIN_PAGES+"${BUILTIN_PAGES[@]}"})
fi

declare -a ALL_PAGES=()
declare -a INCLUDED_PAGES_UNIQ=()

for item in "${BUILTIN_PAGES[@]}"; do
  [[ -z "$item" ]] && continue
  if [[ " ${ALL_PAGES[*]} " != *" ${item} "* ]]; then
    ALL_PAGES+=("$item")
  fi
done
if (( SKIP_REPOSITORY_PAGES == 0 )); then
  for item in "${REPOSITORY_PAGES[@]}"; do
    [[ -z "$item" ]] && continue
    if [[ " ${ALL_PAGES[*]} " != *" ${item} "* ]]; then
      ALL_PAGES+=("$item")
    fi
  done
fi
for item in "${INCLUDED_PAGES[@]}"; do
  [[ -z "$item" ]] && continue
  if [[ " ${INCLUDED_PAGES_UNIQ[*]} " != *" ${item} "* ]]; then
    INCLUDED_PAGES_UNIQ+=("$item")
  fi
done

# --- BUILTIN_APPS: allow manual override via env -----------------------------
# You can set BUILTIN_APPS or BUILTIN_APPS_OVERRIDE to a comma/space/newline
# separated list (e.g. "foo_project,bar_project baz_project"). Passing the
# sentinel "__AGILAB_ALL_APPS__" (wired through --install-apps all) skips the
# picker but keeps the default "install everything" selection.
if [[ -n "${BUILTIN_APPS_OVERRIDE-}" && -n "${BUILTIN_APPS_OVERRIDE//[[:space:]]/}" ]]; then
  FILTER_BUILTINS_BY_DEFAULT=0
  if [[ "${BUILTIN_APPS_OVERRIDE}" == "$ALL_APPS_SENTINEL" ]]; then
    PROMPT_FOR_APPS=0
    NEED_APP_DISCOVERY=1
    FORCE_ALL_APPS=1
    echo -e "${BLUE}(Apps) Full install requested via BUILTIN_APPS_OVERRIDE; installing every installable app.${NC}"
  elif [[ "${BUILTIN_APPS_OVERRIDE}" == "$BUILTIN_ONLY_SENTINEL" ]]; then
    PROMPT_FOR_APPS=0
    NEED_APP_DISCOVERY=1
    FORCE_BUILTIN_ONLY=1
    SKIP_REPOSITORY_APPS=1
    echo -e "${BLUE}(Apps) Built-in install requested; repository apps will be skipped.${NC}"
  else
    parse_list_to_array BUILTIN_APPS "$BUILTIN_APPS_OVERRIDE"
    echo -e "${BLUE}(Apps) Override enabled via BUILTIN_APPS_OVERRIDE:${NC} ${BUILTIN_APPS[*]}"
    PROMPT_FOR_APPS=0
    FORCE_APP_SELECTION=1
    NEED_APP_DISCOVERY=0
  fi
elif [[ -n "${BUILTIN_APPS_FROM_ENV}" && -n "${BUILTIN_APPS_FROM_ENV//[[:space:]]/}" ]]; then
  FILTER_BUILTINS_BY_DEFAULT=0
  if [[ "${BUILTIN_APPS_FROM_ENV}" == "$ALL_APPS_SENTINEL" ]]; then
    PROMPT_FOR_APPS=0
    NEED_APP_DISCOVERY=1
    FORCE_ALL_APPS=1
    echo -e "${BLUE}(Apps) Full install requested (--install-apps all); installing every installable app.${NC}"
  elif [[ "${BUILTIN_APPS_FROM_ENV}" == "$BUILTIN_ONLY_SENTINEL" ]]; then
    PROMPT_FOR_APPS=0
    NEED_APP_DISCOVERY=1
    FORCE_BUILTIN_ONLY=1
    SKIP_REPOSITORY_APPS=1
    echo -e "${BLUE}(Apps) Built-in install requested (--install-apps builtin); repository apps will be skipped.${NC}"
  else
    parse_list_to_array BUILTIN_APPS "$BUILTIN_APPS_FROM_ENV"
    echo -e "${BLUE}(Apps) Override enabled via BUILTIN_APPS:${NC} ${BUILTIN_APPS[*]}"
    PROMPT_FOR_APPS=0
    FORCE_APP_SELECTION=1
    NEED_APP_DISCOVERY=0
  fi
fi

if (( NEED_APP_DISCOVERY )); then
  if [[ -d "$BUILTIN_APPS_ROOT" ]]; then
    while IFS= read -r -d '' dir; do
      dir_name="$(basename -- "$dir")"
      if [[ " ${BUILTIN_APPS[@]-} " != *" ${dir_name} "* ]]; then
        BUILTIN_APPS+=("$dir_name")
      fi
    done < <(find "$BUILTIN_APPS_ROOT" -mindepth 1 -maxdepth 1 -type d -name '*_project' -print0)
  fi
fi

if (( SKIP_REPOSITORY_APPS == 0 )); then
  declare -a repository_apps_found=()

  if [[ -d "$APPS_TARGET_BASE" ]]; then
    while IFS= read -r -d '' dir; do
      if app_has_required_sources "$dir"; then
        repository_apps_found+=("$(basename -- "$dir")")
      else
        INVALID_REPOSITORY_APPS+=("$(basename -- "$dir")")
      fi
    done < <(find "$APPS_TARGET_BASE" -mindepth 1 -maxdepth 1 -type d -name '*_project' -print0)
  fi

  if (( ${#repository_apps_found[@]} )); then
    REPOSITORY_APPS=("${repository_apps_found[@]}")
  else
    REPOSITORY_APPS=()
  fi
fi

if (( FORCE_BUILTIN_ONLY )); then
  REPOSITORY_APPS=()
fi

declare -a SELECTED_REPOSITORY_APPS=()
if (( SKIP_REPOSITORY_APPS == 0 )); then
  if (( FORCE_ALL_APPS )); then
    SELECTED_REPOSITORY_APPS=(${REPOSITORY_APPS+"${REPOSITORY_APPS[@]}"})
  else
    for app in ${REPOSITORY_APPS+"${REPOSITORY_APPS[@]}"}; do
      if in_list "$app" "${DEFAULT_SELECTED_APPS[@]}"; then
        SELECTED_REPOSITORY_APPS+=("$app")
      fi
    done
  fi
fi

declare -a SELECTED_BUILTIN_APPS=()
declare -a BUILTIN_SKIPPED_BY_DEFAULT=()
if (( FILTER_BUILTINS_BY_DEFAULT )); then
  for app in "${BUILTIN_APPS[@]}"; do
    skip=0
    for blocked in "${BUILTIN_SKIP_BY_DEFAULT[@]}"; do
      if [[ "$app" == "$blocked" ]]; then
        skip=1
        break
      fi
    done
    if (( skip )); then
      BUILTIN_SKIPPED_BY_DEFAULT+=("$app")
      continue
    fi
    SELECTED_BUILTIN_APPS+=("$app")
  done
else
  SELECTED_BUILTIN_APPS=(${BUILTIN_APPS+"${BUILTIN_APPS[@]}"})
fi

if (( FILTER_BUILTINS_BY_DEFAULT )) && (( ${#BUILTIN_SKIPPED_BY_DEFAULT[@]} )); then
  echo -e "${YELLOW}(Apps) Skipping built-ins by default:${NC} ${BUILTIN_SKIPPED_BY_DEFAULT[*]}"
  echo -e "${YELLOW}Tip:${NC} Pass --install-apps <name|all> or select them from the picker to include them."
fi

if (( ${#INVALID_REPOSITORY_APPS[@]} )); then
  echo -e "${YELLOW}(Apps) Skipping incomplete repository apps:${NC} ${INVALID_REPOSITORY_APPS[*]}"
fi

if (( FORCE_APP_SELECTION )); then
  INCLUDED_APPS=(${BUILTIN_APPS+"${BUILTIN_APPS[@]}"})
elif (( SKIP_REPOSITORY_APPS == 0 )); then
  INCLUDED_APPS=(${SELECTED_BUILTIN_APPS+"${SELECTED_BUILTIN_APPS[@]}"} ${SELECTED_REPOSITORY_APPS+"${SELECTED_REPOSITORY_APPS[@]}"})
else
  INCLUDED_APPS=(${SELECTED_BUILTIN_APPS+"${SELECTED_BUILTIN_APPS[@]}"})
fi
declare -a ALL_APPS=()
declare -a INCLUDED_APPS_UNIQ=()

for item in "${BUILTIN_APPS[@]}"; do
  [[ -z "$item" ]] && continue
  if [[ " ${ALL_APPS[*]} " != *" ${item} "* ]]; then
    ALL_APPS+=("$item")
  fi
done
if (( ! FORCE_APP_SELECTION && SKIP_REPOSITORY_APPS == 0 )); then
  for item in "${REPOSITORY_APPS[@]}"; do
    [[ -z "$item" ]] && continue
    if [[ " ${ALL_APPS[*]} " != *" ${item} "* ]]; then
      ALL_APPS+=("$item")
    fi
  done
fi
for item in "${INCLUDED_APPS[@]}"; do
  [[ -z "$item" ]] && continue
  if [[ " ${INCLUDED_APPS_UNIQ[*]} " != *" ${item} "* ]]; then
    INCLUDED_APPS_UNIQ+=("$item")
  fi
done

# Apply stable ordering for display (and for "defaults" selection markers).
if (( ${#DEFAULT_APPS_ORDER[@]} )); then
  declare -a ordered_all_apps=()
  for preferred in "${DEFAULT_APPS_ORDER[@]}"; do
    for item in "${ALL_APPS[@]}"; do
      [[ "$item" == "$preferred" ]] && ordered_all_apps+=("$item") && break
    done
  done
  for item in "${ALL_APPS[@]}"; do
    if ! in_list "$item" "${ordered_all_apps[@]}"; then
      ordered_all_apps+=("$item")
    fi
  done
  ALL_APPS=("${ordered_all_apps[@]}")

  declare -a ordered_included_apps=()
  for preferred in "${DEFAULT_APPS_ORDER[@]}"; do
    for item in "${INCLUDED_APPS_UNIQ[@]}"; do
      [[ "$item" == "$preferred" ]] && ordered_included_apps+=("$item") && break
    done
  done
  for item in "${INCLUDED_APPS_UNIQ[@]}"; do
    if ! in_list "$item" "${ordered_included_apps[@]}"; then
      ordered_included_apps+=("$item")
    fi
  done
  INCLUDED_APPS_UNIQ=("${ordered_included_apps[@]}")
fi

# Offer an interactive picker when we still need confirmation.
if (( PROMPT_FOR_APPS )); then
  if [[ -t 0 ]]; then
    declare -a PROMPT_APPS=()
    if (( ${#ALL_APPS[@]} )); then
      PROMPT_APPS=("${ALL_APPS[@]}")
    else
      PROMPT_APPS=("${INCLUDED_APPS_UNIQ[@]}")
    fi
    echo -e "${BLUE}Available apps:${NC}"
    for idx in "${!PROMPT_APPS[@]}"; do
      app="${PROMPT_APPS[$idx]}"
      marker="[ ]"
      if [[ " ${INCLUDED_APPS_UNIQ[*]} " == *" ${app} "* ]]; then
        marker="[x]"
      fi
      printf "  %2d) %s %s\n" $((idx + 1)) "$marker" "$app"
    done
    read -rp "Numbers/ranges (1 3-5, blank = defaults): " selection
    if [[ -n "$selection" ]]; then
      selection="${selection//,/ }"
      declare -a picked=()
      for token in $selection; do
        if [[ "$token" =~ ^([0-9]+)-([0-9]+)$ ]]; then
          start=${BASH_REMATCH[1]}
          end=${BASH_REMATCH[2]}
          if (( end < start )); then
            echo -e "${YELLOW}Ignoring invalid range: $token${NC}"
            continue
          fi
          for ((num=start; num<=end; num++)); do
            idx=$((num - 1))
            if (( idx >= 0 && idx < ${#PROMPT_APPS[@]} )); then
              picked+=("${PROMPT_APPS[$idx]}")
            else
              echo -e "${YELLOW}Ignoring out-of-range selection: $num${NC}"
            fi
          done
        elif [[ "$token" =~ ^[0-9]+$ ]]; then
          idx=$((token - 1))
          if (( idx >= 0 && idx < ${#PROMPT_APPS[@]} )); then
            picked+=("${PROMPT_APPS[$idx]}")
          else
            echo -e "${YELLOW}Ignoring out-of-range selection: $token${NC}"
          fi
        else
          echo -e "${YELLOW}Ignoring invalid selection: $token${NC}"
        fi
      done
      if (( ${#picked[@]} )); then
        declare -a unique_picked=()
        for item in "${picked[@]}"; do
          [[ -z "$item" ]] && continue
          if [[ " ${unique_picked[*]} " != *" ${item} "* ]]; then
            unique_picked+=("$item")
          fi
        done
        INCLUDED_APPS_UNIQ=("${unique_picked[@]}")
      else
        echo -e "${YELLOW}No valid selections detected; keeping defaults.${NC}"
      fi
    fi
  else
    echo -e "${YELLOW}Non-interactive session detected; installing default apps: ${INCLUDED_APPS_UNIQ[*]}.${NC}"
  fi
fi

declare -a FILTERED_PAGES=()
declare -a FILTERED_APPS=()

for item in "${ALL_PAGES[@]}"; do
  [[ -z "$item" ]] && continue
  if [[ " ${INCLUDED_PAGES_UNIQ[*]} " != *" ${item} "* ]]; then
    FILTERED_PAGES+=("$item")
  fi
done
for item in "${ALL_APPS[@]}"; do
  [[ -z "$item" ]] && continue
  if [[ " ${INCLUDED_APPS_UNIQ[*]} " != *" ${item} "* ]]; then
    FILTERED_APPS+=("$item")
  fi
done

if (( ${#INCLUDED_PAGES_UNIQ[@]} )); then
  echo -e "${BLUE}Pages selected for install:${NC} ${INCLUDED_PAGES_UNIQ[*]}"
else
  echo -e "${YELLOW}No pages selected for install.${NC}"
fi
if (( ${#FILTERED_PAGES[@]} )); then
  echo -e "${YELLOW}Pages filtered out:${NC} ${FILTERED_PAGES[*]}"
fi
if (( ${#INCLUDED_APPS_UNIQ[@]} )); then
  echo -e "${BLUE}Apps selected for install:${NC} ${INCLUDED_APPS_UNIQ[*]}"
else
  echo -e "${YELLOW}No apps selected for install.${NC}"
fi
if (( ${#FILTERED_APPS[@]} )); then
  echo -e "${YELLOW}Apps filtered out:${NC} ${FILTERED_APPS[*]}"
fi

if [[ -n "$INSTALLED_APPS_FILE" ]]; then
  mkdir -p -- "$(dirname "$INSTALLED_APPS_FILE")"
  if (( ${#INCLUDED_APPS_UNIQ[@]} )); then
    printf "%s\n" "${INCLUDED_APPS_UNIQ[@]}" > "$INSTALLED_APPS_FILE"
  else
    : > "$INSTALLED_APPS_FILE"
  fi
  echo -e "${BLUE}Installed apps manifest:${NC} $INSTALLED_APPS_FILE"
fi

# --- Ensure local symlinks exist/refresh in DEST_BASE ------------------------
if (( SKIP_REPOSITORY_APPS == 0 )); then
  repo_agilab_dir="$(dirname "$APPS_TARGET_BASE")"
  if [[ -d "$repo_agilab_dir" ]]; then
    pushd "$repo_agilab_dir" > /dev/null
    rm -f core
    if [[ -d "$AGILAB_REPO/core" ]]; then
      target="$AGILAB_REPO/core"
    elif [[ -d "$AGILAB_REPO/src/agilab/core" ]]; then
      target="$AGILAB_REPO/src/agilab/core"
    else
      echo "ERROR: can't find 'core' under \$AGILAB_REPO ($AGILAB_REPO)."
      echo "Tried: \$AGILAB_REPO/core and \$AGILAB_REPO/src/agilab/core"
      exit 1
    fi
    ln -s "$target" core
    sleep 3
    "${UV_PREVIEW[@]}" run python - <<'PY'
import pathlib
p = pathlib.Path("core").resolve()
print(f"Repository core -> {p}")
PY
    sleep 3
    repo_templates_dir="apps/templates"
    public_templates_dir="$AGILAB_REPO/apps/templates"
    if [[ -d "$public_templates_dir" ]]; then
      mkdir -p apps
      if [[ -L "$repo_templates_dir" ]]; then
        link_target="$(readlink "$repo_templates_dir")"
        # Normalize relative targets so we can safely compare paths
        if [[ "$link_target" != "$public_templates_dir" ]]; then
          echo -e "${YELLOW}Removing stale templates symlink -> ${link_target}.${NC}"
          rm -f -- "$repo_templates_dir"
        fi
      elif [[ -e "$repo_templates_dir" ]]; then
        echo -e "${YELLOW}Replacing repository templates directory with symlink -> ${public_templates_dir}.${NC}"
        rm -rf -- "$repo_templates_dir"
      fi
      if [[ ! -e "$repo_templates_dir" ]]; then
        ln -s "$public_templates_dir" "$repo_templates_dir"
        echo -e "${BLUE}Linked repository templates to ${public_templates_dir}.${NC}"
      fi
    else
      echo -e "${YELLOW}Warning:${NC} expected templates at $public_templates_dir not found; skipping templates link."
    fi
    popd >/dev/null
  fi
fi

status=0
# Safe loop if REPOSITORY_PAGES is unset/empty with `set -u`
if (( SKIP_REPOSITORY_PAGES == 0 )); then
for page in ${REPOSITORY_PAGES+"${REPOSITORY_PAGES[@]}"}; do
  page_target="$PAGES_TARGET_BASE/$page"
  page_dest="$PAGES_DEST_BASE/$page"

  if [[ ! -e "$page_target" ]]; then
    echo -e "${YELLOW}Skipping repository page '${page}': missing target $page_target.${NC}"
    continue
  fi

  refresh_repository_link "Page" "$page_dest" "$page_target"
done
fi

# Safe loop if REPOSITORY_APPS is unset/empty with `set -u`
if (( SKIP_REPOSITORY_APPS == 0 )); then
for app in ${REPOSITORY_APPS+"${REPOSITORY_APPS[@]}"}; do
  app_target="$APPS_TARGET_BASE/$app"
  app_dest="$APPS_DEST_BASE/$app"

  if [[ ! -e "$app_target" ]]; then
    echo -e "${YELLOW}Skipping repository app '${app}': missing target $app_target.${NC}"
    continue
  fi

  refresh_repository_link "App" "$app_dest" "$app_target"
done
fi

append_unique INCLUDED_APPS_UNIQ ${INCLUDED_APPS+"${INCLUDED_APPS[@]}"} 
INCLUDED_PAGES=("${INCLUDED_PAGES_UNIQ[@]}")
INCLUDED_APPS=("${INCLUDED_APPS_UNIQ[@]}")

# --- Run installer for each page (stable CWD so ../core/agi-cluster resolves) -----
pushd -- "$AGILAB_REPO/apps-pages" >/dev/null

for page in ${INCLUDED_PAGES+"${INCLUDED_PAGES[@]}"}; do
    echo -e "${BLUE}Installing $page...${NC}"
    page_dir="$AGILAB_REPO/apps-pages/$page"
    if ! page_has_required_sources "$page_dir"; then
        echo -e "${YELLOW}Skipping page '$page': not an installable AGILAB page project.${NC}"
        continue
    fi
    pushd "$page_dir" >/dev/null
    unlink_linked_venv ".venv" "$page"
    ${UV_PREVIEW[@]} sync --project . --preview-features python-upgrade
    status=$?
    if (( status != 0 )); then
        echo -e "${RED}Error during 'uv sync' for page '$page'.${NC}"
    fi
    popd >/dev/null
done

popd >/dev/null

# --- Run installer for each app (stable CWD so ../core/agi-cluster resolves) -----
pushd -- "$AGILAB_REPO/apps" >/dev/null

for app in ${INCLUDED_APPS+"${INCLUDED_APPS[@]}"}; do
  app_name="$app"
  if [[ "$app_name" != *_project && "$app_name" != *_worker ]]; then
    candidate="${app_name}_project"
    if [[ -d "$candidate" || -d "builtin/$candidate" ]]; then
      app_name="$candidate"
    fi
  fi
  if [[ -d "builtin/$app_name" ]]; then
    app_dir_rel="builtin/$app_name"
  elif [[ -d "$app_name" ]]; then
    app_dir_rel="$app_name"
  else
    echo -e "${YELLOW}Skipping '$app': directory not found in apps/ or apps/builtin/.${NC}"
    continue
  fi
  if ! check_data_mount "$app_name"; then
    rc=$?
    if (( rc == 2 )); then
      SKIPPED_APP_TESTS+=("$app_name")
      echo -e "${YELLOW}Warning:${NC} data storage unavailable for '$app_name' (${DATA_CHECK_MESSAGE}). Skipping install/apps-test stage."
      continue
    fi
    echo -e "${RED}Error checking data availability for '$app_name':${NC} ${DATA_CHECK_MESSAGE:-"unknown error"}"
    status=1
    continue
  fi

	  echo -e "${BLUE}Installing $app_name...${NC}"
	  unlink_linked_venv "${AGILAB_REPO}/apps/$app_dir_rel/.venv" "$app_name"
	  worker_env_name="$app_name"
	  if [[ "$worker_env_name" == *_project ]]; then
	    worker_env_name="${worker_env_name%_project}_worker"
	  fi
	  echo "cleanup wenv/$worker_env_name"
	  rm -fr "$HOME/wenv/$worker_env_name"

  echo "${UV_PREVIEW[@]} -q run -p \"$AGI_PYTHON_VERSION\" --project ../core/agi-cluster python install.py \"${AGILAB_REPO}/apps/$app_dir_rel\""
  if "${UV_PREVIEW[@]}" -q run -p "$AGI_PYTHON_VERSION" --project ../core/agi-cluster python install.py \
    "${AGILAB_REPO}/apps/$app_dir_rel"; then
      echo -e "${GREEN}✓ '$app_name' successfully installed.${NC}"
      if (( DO_TEST_APPS )); then
        echo -e "${GREEN}Checking installation...${NC}"
        if pushd -- "$app_dir_rel" >/dev/null; then
        ran_app_test=0
        if [[ -f app_test.py ]]; then
          echo "${UV_PREVIEW[@]} run -p \"$AGI_PYTHON_VERSION\" ${CORE_EDITABLE_PACKAGES[*]} python app_test.py"
          "${UV_PREVIEW[@]}" run -p "$AGI_PYTHON_VERSION" "${CORE_EDITABLE_PACKAGES[@]}" python app_test.py
          ran_app_test=1
        else
            if app_has_collectable_pytests .; then
              if (( DO_TEST_APPS )); then
                echo -e "${BLUE}No app_test.py in $app_name; pytest suite under test/ will run via --test-apps pass.${NC}"
              else
                echo -e "${BLUE}No app_test.py in $app_name; pytest suite detected under test/ (run with --test-apps to execute).${NC}"
              fi
            else
              echo -e "${BLUE}No app_test.py or collectable pytest files in $app_name, skipping tests.${NC}"
            fi
        fi
        popd >/dev/null
        if (( ran_app_test )); then
          echo -e "${GREEN}All ${app_name} tests finished.${NC}"
        fi
        else
        echo -e "${YELLOW}Warning:${NC} could not enter '$app' to run tests."
        fi
      fi
  else
      echo -e "${RED}✗ '$app_name' installation failed.${NC}"
      status=1
  fi
done

popd >/dev/null

# --- Optional pytest pass for apps -------------------------------------------
if (( DO_TEST_APPS )); then
  echo -e "${BLUE}Running pytest for installed apps...${NC}"
  pushd -- "$AGILAB_REPO/apps" >/dev/null
for app in ${INCLUDED_APPS+"${INCLUDED_APPS[@]}"}; do
  app_name="$app"
  if [[ "$app_name" != *_project && "$app_name" != *_worker ]]; then
    candidate="${app_name}_project"
    if [[ -d "$candidate" || -d "builtin/$candidate" ]]; then
      app_name="$candidate"
    fi
  fi
  if [[ -d "builtin/$app_name" ]]; then
    app_dir_rel="builtin/$app_name"
  elif [[ -d "$app_name" ]]; then
    app_dir_rel="$app_name"
  else
    echo -e "${YELLOW}Skipping pytest for '$app_name': directory not found.${NC}"
    continue
  fi
  if [[ " ${SKIPPED_APP_TESTS[*]} " == *" $app_name "* ]]; then
    echo -e "${YELLOW}Skipping pytest for '$app_name': data storage unavailable earlier.${NC}"
    continue
  fi
  echo -e "${BLUE}[pytest] $app_name${NC}"
  if pushd -- "$app_dir_rel" >/dev/null; then
    if ! app_has_collectable_pytests .; then
      echo -e "${YELLOW}No collectable pytest files found for '$app_name', skipping.${NC}"
      popd >/dev/null
      continue
    fi
    if "${UV_PREVIEW[@]}" run -p "$AGI_PYTHON_VERSION" "${CORE_EDITABLE_PACKAGES[@]}" --project . --with pytest --with pytest-cov pytest; then
      echo -e "${GREEN}✓ pytest succeeded for '$app_name'.${NC}"
      else
        rc=$?
        if (( rc == 5 )); then
          echo -e "${YELLOW}No tests collected for '$app_name'.${NC}"
        else
          echo -e "${RED}✗ pytest failed for '$app_name' (exit code $rc).${NC}"
          status=1
        fi
      fi
      popd >/dev/null
    else
      echo -e "${YELLOW}Warning:${NC} could not enter '$app' to run pytest."
      status=1
    fi
  done
  popd >/dev/null
fi

link_compatible_venvs

# --- Final Message -----------------------------------------------------------
if (( status == 0 )); then
    if [[ -n "$APPS_REPOSITORY" ]]; then
        repo_examples_dir="${APPS_REPOSITORY}/examples"
        docs_examples_dir="${APPS_REPOSITORY}/docs/source/examples"
        if [[ -d "$repo_examples_dir" ]]; then
            if [[ -L "$docs_examples_dir" ]]; then
                current_examples_target="$(readlink "$docs_examples_dir")"
                if [[ "$current_examples_target" != "$repo_examples_dir" ]]; then
                    rm -f -- "$docs_examples_dir"
                    ln -s -- "$repo_examples_dir" "$docs_examples_dir"
                fi
            elif [[ ! -e "$docs_examples_dir" ]]; then
                ln -s -- "$repo_examples_dir" "$docs_examples_dir"
            fi
        fi
    fi
    echo -e "${GREEN}Installation of apps complete!${NC}"
else
    echo -e "${YELLOW}Installation finished with some errors (status=$status).${NC}"
fi

if (( ${#SKIPPED_APP_TESTS[@]} )); then
    echo -e "${YELLOW}apps-test bypassed for:${NC} ${SKIPPED_APP_TESTS[*]}"
fi

END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))
ELAPSED_MIN=$((ELAPSED / 60))
ELAPSED_SEC=$((ELAPSED % 60))
echo -e "${BLUE}install_apps.sh duration: ${ELAPSED_MIN}m ${ELAPSED_SEC}s${NC}"

exit "$status"
