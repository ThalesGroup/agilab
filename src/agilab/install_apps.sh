#!/bin/bash
# Script: install_Agi_apps.sh
# Purpose: Install the apps (apps-only; no positional args required)
# macOS-friendly: avoid `mapfile`, keep POSIX-ish constructs for Bash 3.2

set -euo pipefail

export AGI_PYTHON_VERSION
export PYTHONPATH="$PWD:${PYTHONPATH-}"

UV_PREVIEW=(uv --preview-features extra-build-dependencies)

# Capture potential overrides before arrays are declared (preserves set -u semantics)
PUBLIC_PAGES_FROM_ENV="${PUBLIC_PAGES-}"
PUBLIC_APPS_FROM_ENV="${PUBLIC_APPS-}"

# Colors for output
RED='\033[1;31m'
GREEN='\033[1;32m'
BLUE='\033[1;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Load env + normalize Python version
# shellcheck source=/dev/null
source "$HOME/.local/share/agilab/.env"

AGI_PYTHON_VERSION=$(echo "${AGI_PYTHON_VERSION:-}" | sed -E 's/^([0-9]+\.[0-9]+\.[0-9]+(\+freethreaded)?).*/\1/')

AGILAB_PUBLIC="$(cat "$HOME/.local/share/agilab/.agilab-path")"
AGILAB_PRIVATE="${AGILAB_PRIVATE:-}"

PAGES_TARGET_BASE="$AGILAB_PRIVATE/src/agilab/apps-pages"
APPS_TARGET_BASE="$AGILAB_PRIVATE/src/agilab/apps"
[[ -d "$PAGES_TARGET_BASE" ]] || { echo -e "${RED}Error:${NC} Missing directory: $PAGES_TARGET_BASE"; exit 1; }
[[ -d "$APPS_TARGET_BASE" ]] || { echo -e "${RED}Error:${NC} Missing directory: $APPS_TARGET_BASE"; exit 1; }


# --- Ensure arrays exist (avoids 'unbound variable' with set -u) -------------
# We declare them empty up front; later code can append or overwrite freely.
# This prevents errors like: ${PRIVATE_PAGES[@]}: unbound variable
declare -a PUBLIC_PAGES=()
declare -a PRIVATE_PAGES=()
declare -a PUBLIC_APPS=(
  mycode_project
  flight_project
)
declare -a PRIVATE_APPS=(
  example_app_project
  example_app_project
  example_app_project
  example_app_project
)

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


# --- App lists (merge private + public) --------------------------------------

# Destination base for creating local app symlinks (defaults to current dir)
: "${APPS_DEST_BASE:="$AGILAB_PUBLIC/apps"}"
: "${PAGES_DEST_BASE:="$AGILAB_PUBLIC/apps-pages"}"

mkdir -p -- "$APPS_DEST_BASE"
mkdir -p -- "$PAGES_DEST_BASE"

resolve_physical_dir() {
  (cd "$1" >/dev/null 2>&1 && pwd -P)
}

APPS_DEST_REAL=$(resolve_physical_dir "$APPS_DEST_BASE")
APPS_TARGET_REAL=$(resolve_physical_dir "$APPS_TARGET_BASE")
PAGES_DEST_REAL=$(resolve_physical_dir "$PAGES_DEST_BASE")
PAGES_TARGET_REAL=$(resolve_physical_dir "$PAGES_TARGET_BASE")

SKIP_PRIVATE_APPS=0
SKIP_PRIVATE_PAGES=0

if [[ "$APPS_DEST_REAL" == "$APPS_TARGET_REAL" ]]; then
  echo -e "${YELLOW}Warning:${NC} apps destination resolves inside the private tree; skipping private app symlink refresh to avoid self-links."\
  " (dest=$APPS_DEST_REAL)."
  SKIP_PRIVATE_APPS=1
fi

if [[ "$PAGES_DEST_REAL" == "$PAGES_TARGET_REAL" ]]; then
  echo -e "${YELLOW}Warning:${NC} pages destination resolves inside the private tree; skipping private page symlink refresh to avoid self-links."\
  " (dest=$PAGES_DEST_REAL)."
  SKIP_PRIVATE_PAGES=1
fi

echo -e "${BLUE}Using AGILAB_PRIVATE:${NC} $AGILAB_PRIVATE"
echo -e "${BLUE}(Apps) Destination base:${NC} $APPS_DEST_BASE"
echo -e "${BLUE}(Apps) Link target base:${NC} $APPS_TARGET_BASE\n"
echo -e "${BLUE}(Pages) Destination base:${NC} $PAGES_DEST_BASE"
echo -e "${BLUE}(Pages) Link target base:${NC} $PAGES_TARGET_BASE\n"


# --- PUBLIC_PAGES: allow manual override via env ------------------------------
# You can set PUBLIC_PAGES or PUBLIC_PAGES_OVERRIDE to a comma/space/newline
# separated list (e.g. "home dashboard,foo-view\nbar-view").
if [[ -n "${PUBLIC_PAGES_OVERRIDE-}" && -n "${PUBLIC_PAGES_OVERRIDE//[[:space:]]/}" ]]; then
  parse_list_to_array PUBLIC_PAGES "$PUBLIC_PAGES_OVERRIDE"
  echo -e "${BLUE}(Pages) Override enabled via PUBLIC_PAGES_OVERRIDE:${NC} ${PUBLIC_PAGES[*]}"
elif [[ -n "${PUBLIC_PAGES_FROM_ENV}" && -n "${PUBLIC_PAGES_FROM_ENV//[[:space:]]/}" ]]; then
  parse_list_to_array PUBLIC_PAGES "$PUBLIC_PAGES_FROM_ENV"
  echo -e "${BLUE}(Pages) Override enabled via PUBLIC_PAGES:${NC} ${PUBLIC_PAGES[*]}"
else
  while IFS= read -r -d '' dir; do
    dir_name="$(basename -- "$dir")"
    if [[ " ${PUBLIC_PAGES[@]-} " != *" ${dir_name} "* ]]; then
      PUBLIC_PAGES+=("$dir_name")
    fi
  done < <(find "$PAGES_DEST_BASE" -mindepth 1 -maxdepth 1 -type d ! -name ".venv" -print0)
fi

declare -a INCLUDED_PAGES=()
if [[ -z "$AGILAB_PRIVATE" ]]; then
  INCLUDED_PAGES=(${PUBLIC_PAGES+"${PUBLIC_PAGES[@]}"})
else
  INCLUDED_PAGES=(${PUBLIC_PAGES+"${PUBLIC_PAGES[@]}"} ${PRIVATE_PAGES+"${PRIVATE_PAGES[@]}"})
fi

# --- PUBLIC_APPS: allow manual override via env ------------------------------
# You can set PUBLIC_APPS or PUBLIC_APPS_OVERRIDE to a comma/space/newline
# separated list (e.g. "foo_project,bar_project baz_project").
if [[ -n "${PUBLIC_APPS_OVERRIDE-}" && -n "${PUBLIC_APPS_OVERRIDE//[[:space:]]/}" ]]; then
  parse_list_to_array PUBLIC_APPS "$PUBLIC_APPS_OVERRIDE"
  echo -e "${BLUE}(Apps) Override enabled via PUBLIC_APPS_OVERRIDE:${NC} ${PUBLIC_APPS[*]}"
elif [[ -n "${PUBLIC_APPS_FROM_ENV}" && -n "${PUBLIC_APPS_FROM_ENV//[[:space:]]/}" ]]; then
  parse_list_to_array PUBLIC_APPS "$PUBLIC_APPS_FROM_ENV"
  echo -e "${BLUE}(Apps) Override enabled via PUBLIC_APPS:${NC} ${PUBLIC_APPS[*]}"
else
  while IFS= read -r -d '' dir; do
    dir_name="$(basename -- "$dir")"
    if [[ " ${PUBLIC_APPS[@]-} " != *" ${dir_name} "* ]]; then
      PUBLIC_APPS+=("$dir_name")
    fi
  done < <(find "$APPS_DEST_BASE" -mindepth 1 -maxdepth 1 -type d -name '*_project' -print0)
fi

declare -a INCLUDED_APPS=()
if [[ -z "$AGILAB_PRIVATE" ]]; then
  INCLUDED_APPS=(${PUBLIC_APPS+"${PUBLIC_APPS[@]}"})
else
  INCLUDED_APPS=(${PUBLIC_APPS+"${PUBLIC_APPS[@]}"} ${PRIVATE_APPS+"${PRIVATE_APPS[@]}"})
fi

echo -e "${BLUE}Apps to install:${NC} ${INCLUDED_APPS[*]:-<none>}\n"
echo -e "${BLUE}Pages to install:${NC} ${INCLUDED_PAGES[*]:-<none>}\n"

# --- Ensure local symlinks exist/refresh in DEST_BASE ------------------------
if [[ -n "$AGILAB_PRIVATE" ]]; then
  pushd "$AGILAB_PRIVATE/src/agilab" > /dev/null
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
print(f"Private core -> {p}")
PY

    private_templates_dir="apps/templates"
    public_templates_dir="$AGILAB_PUBLIC/apps/templates"
    if [[ -d "$public_templates_dir" ]]; then
      mkdir -p apps
      if [[ -e "$private_templates_dir" && ! -L "$private_templates_dir" ]]; then
        echo -e "${YELLOW}Replacing private templates directory with symlink -> ${public_templates_dir}.${NC}"
        rm -rf -- "$private_templates_dir"
      fi
      if [[ ! -e "$private_templates_dir" ]]; then
        ln -s "$public_templates_dir" "$private_templates_dir"
        echo -e "${BLUE}Linked private templates to ${public_templates_dir}.${NC}"
      fi
    else
      echo -e "${YELLOW}Warning:${NC} expected templates at $public_templates_dir not found; skipping templates link."
    fi
  popd >/dev/null
fi

status=0
# Safe loop if PRIVATE_PAGES is unset/empty with `set -u`
if (( SKIP_PRIVATE_PAGES == 0 )); then
for page in ${PRIVATE_PAGES+"${PRIVATE_PAGES[@]}"}; do
  page_target="$PAGES_TARGET_BASE/$page"
  page_dest="$PAGES_DEST_BASE/$page"

  if [[ ! -e "$page_target" ]]; then
    echo -e "${YELLOW}Skipping private page '${page}': missing target $page_target.${NC}"
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

# Safe loop if PRIVATE_APPS is unset/empty with `set -u`
if (( SKIP_PRIVATE_APPS == 0 )); then
for app in ${PRIVATE_APPS+"${PRIVATE_APPS[@]}"}; do
  app_target="$APPS_TARGET_BASE/$app"
  app_dest="$APPS_DEST_BASE/$app"

  if [[ ! -e "$app_target" ]]; then
    echo -e "${YELLOW}Skipping private app '${app}': missing target $app_target.${NC}"
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

# --- Final Message -----------------------------------------------------------
if (( status == 0 )); then
  ln -s "examples" {$AGILAB_PRIVATE}/docs/source
  echo -e "${GREEN}Installation of apps complete!${NC}"
else
  echo -e "${YELLOW}Installation finished with some errors (status=$status).${NC}"
fi

exit "$status"
