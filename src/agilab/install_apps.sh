#!/bin/bash
set -e
set -o pipefail

# Load env + normalize Python version
# shellcheck source=/dev/null
source "$HOME/.local/share/agilab/.env"

# Colors for output
RED='\033[1;31m'
GREEN='\033[1;32m'
BLUE='\033[1;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

UV_PREVIEW=(uv --preview-features extra-build-dependencies)

DO_TEST_APPS=0

BUILTIN_PAGES_FROM_ENV="${BUILTIN_PAGES-}"
BUILTIN_APPS_FROM_ENV="${BUILTIN_APPS-}"

AGI_PYTHON_VERSION=$(echo "${AGI_PYTHON_VERSION:-}" | sed -E 's/^([0-9]+\.[0-9]+\.[0-9]+(\+freethreaded)?).*/\1/')
AGILAB_PUBLIC="$(cat "$HOME/.local/share/agilab/.agilab-path")"
AGILAB_APPS_REPOSITORY="${AGILAB_APPS_REPOSITORY:-}"

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

usage() {
  cat <<'EOF'
Usage: install_apps.sh [--test-apps]
  --test-apps      Run pytest for each app after installation (implies --install-apps)
  --help           Show this message and exit
EOF
}


while [[ $# -gt 0 ]]; do
  case "$1" in
    --test-apps) DO_TEST_APPS=1;;
    --help|-h) usage; exit 0;;
    *)
      echo -e "${RED}Error:${NC} Unknown option '$1'" >&2
      usage
      exit 1
      ;;
  esac
  shift
done

if [[ -n "$AGILAB_APPS_REPOSITORY" ]]; then
  if ! PAGES_TARGET_BASE=$(discover_repo_dir "$AGILAB_APPS_REPOSITORY" "apps-pages"); then
    echo -e "${RED}Error:${NC} Could not locate an 'apps-pages' directory under $AGILAB_APPS_REPOSITORY" >&2
    exit 1
  fi
  if ! APPS_TARGET_BASE=$(discover_repo_dir "$AGILAB_APPS_REPOSITORY" "apps"); then
    echo -e "${RED}Error:${NC} Could not locate an 'apps' directory under $AGILAB_APPS_REPOSITORY" >&2
    exit 1
  fi
  SKIP_REPOSITORY_APPS=0
  SKIP_REPOSITORY_PAGES=0
fi

# --- Ensure arrays exist (avoids 'unbound variable' with set -u) -------------
# We declare them empty up front; later code can append or overwrite freely.
# This prevents errors like: ${REPOSITORY_PAGES[@]}: unbound variable
declare -a BUILTIN_PAGES=()
declare -a REPOSITORY_PAGES=()
declare -a BUILTIN_APPS=(
  mycode_project
  flight_project
)
declare -a REPOSITORY_APPS=(
  link_sim_project
  sat_trajectory_project
  flight_trajectory_project
  ilp_project
  sb3_trainer_project
)

declare -a INCLUDED_APPS=()
declare -a INCLUDED_PAGES=()

# Destination base for creating local app symlinks (defaults to current dir)
: "${APPS_DEST_BASE:="$AGILAB_PUBLIC/apps"}"
: "${PAGES_DEST_BASE:="$AGILAB_PUBLIC/apps-pages"}"

mkdir -p -- "$APPS_DEST_BASE"
mkdir -p -- "$PAGES_DEST_BASE"

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

echo -e "${BLUE}Using AGILAB_APPS_REPOSITORY:${NC} $AGILAB_APPS_REPOSITORY"
echo -e "${BLUE}(Apps) Destination base:${NC} $APPS_DEST_BASE"
echo -e "${BLUE}(Apps) Link target base:${NC} $APPS_TARGET_BASE\n"
echo -e "${BLUE}(Pages) Destination base:${NC} $PAGES_DEST_BASE"
echo -e "${BLUE}(Pages) Link target base:${NC} $PAGES_TARGET_BASE\n"

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
    if [[ " ${BUILTIN_PAGES[@]-} " != *" ${dir_name} "* ]]; then
      BUILTIN_PAGES+=("$dir_name")
    fi
  done < <(find "$PAGES_DEST_BASE" -mindepth 1 -maxdepth 1 -type d ! -name ".venv" -print0)
fi

if (( SKIP_REPOSITORY_PAGES == 0 )); then
  declare -a repository_pages_found=()
  while IFS= read -r -d '' dir; do
    repository_pages_found+=("$(basename -- "$dir")")
  done < <(find "$PAGES_TARGET_BASE" -mindepth 1 -maxdepth 1 -type d ! -name ".venv" -print0)
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

# --- BUILTIN_APPS: allow manual override via env -----------------------------
# You can set BUILTIN_APPS or BUILTIN_APPS_OVERRIDE to a comma/space/newline
# separated list (e.g. "foo_project,bar_project baz_project").
if [[ -n "${BUILTIN_APPS_OVERRIDE-}" && -n "${BUILTIN_APPS_OVERRIDE//[[:space:]]/}" ]]; then
  parse_list_to_array BUILTIN_APPS "$BUILTIN_APPS_OVERRIDE"
  echo -e "${BLUE}(Apps) Override enabled via BUILTIN_APPS_OVERRIDE:${NC} ${BUILTIN_APPS[*]}"
elif [[ -n "${BUILTIN_APPS_FROM_ENV}" && -n "${BUILTIN_APPS_FROM_ENV//[[:space:]]/}" ]]; then
  parse_list_to_array BUILTIN_APPS "$BUILTIN_APPS_FROM_ENV"
  echo -e "${BLUE}(Apps) Override enabled via BUILTIN_APPS:${NC} ${BUILTIN_APPS[*]}"
else
  while IFS= read -r -d '' dir; do
    dir_name="$(basename -- "$dir")"
    if [[ " ${BUILTIN_APPS[@]-} " != *" ${dir_name} "* ]]; then
      BUILTIN_APPS+=("$dir_name")
    fi
  done < <(find "$APPS_DEST_BASE" -mindepth 1 -maxdepth 1 -type d -name '*_project' -print0)
fi

if (( SKIP_REPOSITORY_APPS == 0 )); then
  declare -a repository_apps_found=()

  for app in "${REPOSITORY_APPS[@]}"; do
    dir="$APPS_TARGET_BASE/${app}"
    if [[ -d "$dir" ]]; then
      repository_apps_found+=("$app")
    fi
  done

  if (( ${#repository_apps_found[@]} )); then
    REPOSITORY_APPS=("${repository_apps_found[@]}")
  else
    REPOSITORY_APPS=()
  fi
fi

if (( SKIP_REPOSITORY_APPS == 0 )); then
  INCLUDED_APPS=(${BUILTIN_APPS+"${BUILTIN_APPS[@]}"} ${REPOSITORY_APPS+"${REPOSITORY_APPS[@]}"})
else
  INCLUDED_APPS=(${BUILTIN_APPS+"${BUILTIN_APPS[@]}"})
fi

echo -e "${BLUE}Apps to install:${NC} ${INCLUDED_APPS[*]:-<none>}\n"
echo -e "${BLUE}Pages to install:${NC} ${INCLUDED_PAGES[*]:-<none>}\n"

# --- Ensure local symlinks exist/refresh in DEST_BASE ------------------------
if (( SKIP_REPOSITORY_APPS == 0 )); then
  repo_agilab_dir="$(dirname "$APPS_TARGET_BASE")"
  if [[ -d "$repo_agilab_dir" ]]; then
    pushd "$repo_agilab_dir" > /dev/null
    rm -f core
    if [[ -d "$AGILAB_PUBLIC/core" ]]; then
      target="$AGILAB_PUBLIC/core"
    elif [[ -d "$AGILAB_PUBLIC/src/agilab/core" ]]; then
      target="$AGILAB_PUBLIC/src/agilab/core"
    else
      echo "ERROR: can't find 'core' under \$AGILAB_PUBLIC ($AGILAB_PUBLIC)."
      echo "Tried: \$AGILAB_PUBLIC/core and \$AGILAB_PUBLIC/src/agilab/core"
      exit 1
    fi
    ln -s "$target" core
    uv run python - <<'PY'
import pathlib
p = pathlib.Path("core").resolve()
print(f"Repository core -> {p}")
PY

    repo_templates_dir="apps/templates"
    public_templates_dir="$AGILAB_PUBLIC/apps/templates"
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

  if [[ -L "$page_dest" ]]; then
    echo -e "${BLUE}Page '$page_dest' is a symlink. Recreating -> '$page_target'...${NC}"
    rm -f -- "$page_dest"; ln -s -- "$page_target" "$page_dest"
  elif [[ ! -e "$page_dest" ]]; then
    echo -e "${BLUE}Page '$page_dest' does not exist. Creating symlink -> '$page_target'...${NC}"
    ln -s -- "$page_target" "$page_dest"
  else
    echo -e "${GREEN}Page '$page_dest' exists and is not a symlink. Leaving untouched.${NC}"
  fi
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

  if [[ -L "$app_dest" ]]; then
    echo -e "${BLUE}App '$app_dest' is a symlink. Recreating -> '$app_target'...${NC}"
    rm -f -- "$app_dest"; ln -s -- "$app_target" "$app_dest"
  elif [[ ! -e "$app_dest" ]]; then
    echo -e "${BLUE}App '$app_dest' does not exist. Creating symlink -> '$app_target'...${NC}"
    ln -s -- "$app_target" "$app_dest"
  else
    echo -e "${GREEN}App '$app_dest' exists and is not a symlink. Leaving untouched.${NC}"
  fi
done
fi


# --- Run installer for each page (stable CWD so ../core/cluster resolves) -----
pushd -- "$AGILAB_PUBLIC/apps-pages" >/dev/null

for page in ${INCLUDED_PAGES+"${INCLUDED_PAGES[@]}"}; do
    echo -e "${BLUE}Installing $page...${NC}"
    pushd "$page" >/dev/null
    ${UV_PREVIEW[@]} sync --project . --preview-features python-upgrade
    status=$?
    if (( status != 0 )); then
        echo -e "${RED}Error during 'uv sync' for page '$page'.${NC}"
    fi
    popd >/dev/null
done

popd >/dev/null

# --- Run installer for each app (stable CWD so ../core/cluster resolves) -----
pushd -- "$AGILAB_PUBLIC/apps" >/dev/null

for app in ${INCLUDED_APPS+"${INCLUDED_APPS[@]}"}; do
echo -e "${BLUE}Installing $app...${NC}"
echo  uv -q run -p "$AGI_PYTHON_VERSION" --project ../core/cluster python install.py \
    "$AGILAB_PUBLIC/apps/$app"
if uv -q run -p "$AGI_PYTHON_VERSION" --project ../core/cluster python install.py \
    "$AGILAB_PUBLIC/apps/$app"; then
    echo -e "${GREEN}✓ '$app' successfully installed.${NC}"
    echo -e "${GREEN}Checking installation...${NC}"
    if pushd -- "$app" >/dev/null; then
    if [[ -f app_test.py ]]; then
        echo uv run --no-sync -p "$AGI_PYTHON_VERSION" python app_test.py
        uv run --no-sync -p "$AGI_PYTHON_VERSION" python app_test.py
    else
        echo -e "${BLUE}No app_test.py in $app, skipping tests.${NC}"
    fi
    popd >/dev/null
    else
    echo -e "${YELLOW}Warning:${NC} could not enter '$app' to run tests."
    fi
else
    echo -e "${RED}✗ '$app' installation failed.${NC}"
    status=1
fi
done

popd >/dev/null

# --- Optional pytest pass for apps -------------------------------------------
if (( DO_TEST_APPS )); then
  echo -e "${BLUE}Running pytest for installed apps...${NC}"
  pushd -- "$AGILAB_PUBLIC/apps" >/dev/null
  for app in ${INCLUDED_APPS+"${INCLUDED_APPS[@]}"}; do
    if [[ ! -d "$app" ]]; then
      echo -e "${YELLOW}Skipping pytest for '$app': directory not found.${NC}"
      continue
    fi
    echo -e "${BLUE}[pytest] $app${NC}"
    if pushd -- "$app" >/dev/null; then
      if uv run --no-sync -p "$AGI_PYTHON_VERSION" --project . pytest; then
        echo -e "${GREEN}✓ pytest succeeded for '$app'.${NC}"
      else
        rc=$?
        if (( rc == 5 )); then
          echo -e "${YELLOW}No tests collected for '$app'.${NC}"
        else
          echo -e "${RED}✗ pytest failed for '$app' (exit code $rc).${NC}"
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

# --- Final Message -----------------------------------------------------------
if (( status == 0 )); then
    if [[ -n "$AGILAB_APPS_REPOSITORY" ]]; then
        ln -s "examples" "${AGILAB_APPS_REPOSITORY}/docs/source"
    fi
    echo -e "${GREEN}Installation of apps complete!${NC}"
else
    echo -e "${YELLOW}Installation finished with some errors (status=$status).${NC}"
fi

exit "$status"
