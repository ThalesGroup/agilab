#!/bin/bash
# Script: install_Agi_apps.sh
# Purpose: Install the apps (apps-only; no positional args required)
# macOS-friendly: avoid `mapfile`, keep POSIX-ish constructs for Bash 3.2

set -euo pipefail

export AGI_PYTHON_VERSION
export PYTHONPATH="$PWD:${PYTHONPATH-}"

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

VIEWS_TARGET_BASE="$AGILAB_PRIVATE/src/agilab/views"
APPS_TARGET_BASE="$AGILAB_PRIVATE/src/agilab/apps"
[[ -d "$VIEWS_TARGET_BASE" ]] || { echo -e "${RED}Error:${NC} Missing directory: $VIEWS_TARGET_BASE"; exit 1; }
[[ -d "$APPS_TARGET_BASE" ]] || { echo -e "${RED}Error:${NC} Missing directory: $APPS_TARGET_BASE"; exit 1; }

INSTALL_TYPE="${INSTALL_TYPE:-1}"


# --- Ensure arrays exist (avoids 'unbound variable' with set -u) -------------
# We declare them empty up front; later code can append or overwrite freely.
# This prevents errors like: ${PRIVATE_VIEWS[@]}: unbound variable
declare -a PUBLIC_VIEWS=()
declare -a PRIVATE_VIEWS=()
declare -a PUBLIC_APPS=(
  flight
)
declare -a PRIVATE_APPS=(
  link_sim
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
: "${APPS_DEST_BASE:="$(pwd)/apps"}"
: "${VIEWS_DEST_BASE:="$(pwd)/views"}"

mkdir -p -- "$APPS_DEST_BASE"
mkdir -p -- "$VIEWS_DEST_BASE"

echo -e "${BLUE}Using AGILAB_PRIVATE:${NC} $AGILAB_PRIVATE"
echo -e "${BLUE}(Apps) Destination base:${NC} $APPS_DEST_BASE)"
echo -e "${BLUE}(Apps) Link target base:${NC} $APPS_TARGET_BASE\n"
echo -e "${BLUE}(Views) Destination base:${NC} $VIEWS_DEST_BASE)"
echo -e "${BLUE}(Views) Link target base:${NC} $VIEWS_TARGET_BASE\n"


declare -a PUBLIC_VIEWS=(
)

declare -a PUBLIC_APPS=(
   flight_project
)

declare -a PRIVATE_VIEWS=(
)

declare -a PRIVATE_APPS=(
   #link_sim_project
   #flight_trajectory_project
   #sat_trajectory_project
   #sb3_trainer_project
)


# --- PUBLIC_VIEWS: allow manual override via env ------------------------------
# You can set PUBLIC_VIEWS or PUBLIC_VIEWS_OVERRIDE to a comma/space/newline
# separated list (e.g. "home dashboard,foo-view\nbar-view").
if [[ -n "${PUBLIC_VIEWS_OVERRIDE:-${PUBLIC_VIEWS:-}}" ]]; then
  raw="${PUBLIC_VIEWS_OVERRIDE:-${PUBLIC_VIEWS:-}}"
  # macOS-safe parsing (no `mapfile`)
  parse_list_to_array PUBLIC_VIEWS "$raw"
  echo -e "${BLUE}(Views) Override enabled. Using PUBLIC_VIEWS:${NC} ${PUBLIC_VIEWS[*]}"
else
  while IFS= read -r -d '' dir; do
    dir_name="$(basename -- "$dir")"
    PUBLIC_VIEWS+=("$dir_name")
  done < <(find "$VIEWS_DEST_BASE" -mindepth 1 -maxdepth 1 -type d ! -name ".venv" -print0)
fi

declare -a INCLUDED_VIEWS=()
if [[ -z "$AGILAB_PRIVATE" ]]; then
  INCLUDED_VIEWS=("${PUBLIC_VIEWS[@]}")
else
  # Safe even if PRIVATE_VIEWS is unset under `set -u`
  INCLUDED_VIEWS=("${PUBLIC_VIEWS[@]}" ${PRIVATE_VIEWS+"${PRIVATE_VIEWS[@]}"})
fi

# --- PUBLIC_APPS: allow manual override via env ------------------------------
# You can set PUBLIC_APPS or PUBLIC_APPS_OVERRIDE to a comma/space/newline
# separated list (e.g. "foo_project,bar_project baz_project").
if [[ -n "${PUBLIC_APPS_OVERRIDE:-${PUBLIC_APPS:-}}" ]]; then
  raw="${PUBLIC_APPS_OVERRIDE:-${PUBLIC_APPS:-}}"
  # macOS-safe parsing (no `mapfile`)
  parse_list_to_array PUBLIC_APPS "$raw"
  echo -e "${BLUE}(Apps) Override enabled. Using PUBLIC_APPS:${NC} ${PUBLIC_APPS[*]}"
else
  while IFS= read -r -d '' dir; do
    dir_name="$(basename -- "$dir")"
    PUBLIC_APPS+=("$dir_name")
  done < <(find "$APPS_DEST_BASE" -mindepth 1 -maxdepth 1 -type d -name '*_project' -print0)
fi

declare -a INCLUDED_APPS=()
if [[ -z "$AGILAB_PRIVATE" ]]; then
  INCLUDED_APPS=("${PUBLIC_APPS[@]}")
else
  # Safe even if PRIVATE_APPS is unset under `set -u`
  INCLUDED_APPS=("${PUBLIC_APPS[@]}" ${PRIVATE_APPS+"${PRIVATE_APPS[@]}"})
fi

echo -e "${BLUE}Apps to install:${NC} ${INCLUDED_APPS[*]:-<none>}\n"
echo -e "${BLUE}Views to install:${NC} ${INCLUDED_VIEWS[*]:-<none>}\n"

# --- Ensure local symlinks exist/refresh in DEST_BASE ------------------------
if [[ ! -z "$AGILAB_PRIVATE" ]]; then
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
  popd >/dev/null
fi

status=0
# Safe loop if PRIVATE_VIEWS is unset/empty with `set -u`
for view in ${PRIVATE_VIEWS+"${PRIVATE_VIEWS[@]}"}; do
  view_target="$VIEWS_TARGET_BASE/$view"
  view_dest="$VIEWS_DEST_BASE/$view"

  if [[ ! -e "$view_target" ]]; then
    echo -e "${RED}Target for '${view}' not found:${NC} $view_target — skipping."
    status=1; continue
  fi

  if [[ -L "$view_dest" ]]; then
    echo -e "${BLUE}View '$view_dest' is a symlink. Recreating -> '$view_target'...${NC}"
    rm -f -- "$view_dest"; ln -s -- "$view_target" "$view_dest"
  elif [[ ! -e "$view_dest" ]]; then
    echo -e "${BLUE}View '$view_dest' does not exist. Creating symlink -> '$view_target'...${NC}"
    ln -s -- "$view_target" "$view_dest"
  else
    echo -e "${GREEN}View '$view_dest' exists and is not a symlink. Leaving untouched.${NC}"
  fi
done

# Safe loop if PRIVATE_APPS is unset/empty with `set -u`
for app in ${PRIVATE_APPS+"${PRIVATE_APPS[@]}"}; do
  app_target="$APPS_TARGET_BASE/$app"
  app_dest="$APPS_DEST_BASE/$app"

  if [[ ! -e "$app_target" ]]; then
    echo -e "${RED}Target for '${app}' not found:${NC} $app_target — skipping."
    status=1; continue
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


# --- Run installer for each views (stable CWD so ../core/cluster resolves) -----
pushd -- "$AGILAB_PUBLIC/views" >/dev/null

for view in "${INCLUDED_VIEWS[@]}"; do
  echo -e "${BLUE}Installing $view...${NC}"
  pushd "$view" >/dev/null
  uv sync --project . --preview-features python-upgrade
  status=$(echo $?)
  if (( status != 0 )); then
    echo -e "${RED}Error during 'uv sync' for view '$view'.${NC}"
  fi
  popd >/dev/null
done

popd >/dev/null

# --- Run installer for each app (stable CWD so ../core/cluster resolves) -----
pushd -- "$AGILAB_PUBLIC/apps" >/dev/null

for app in "${INCLUDED_APPS[@]}"; do
  echo -e "${BLUE}Installing $app...${NC}"
  echo  uv -q run -p "$AGI_PYTHON_VERSION" --project ../core/cluster python install.py \
      "$AGILAB_PUBLIC/apps/$app" --install-type "$INSTALL_TYPE"
  if uv -q run -p "$AGI_PYTHON_VERSION" --project ../core/cluster python install.py \
      "$AGILAB_PUBLIC/apps/$app" --install-type "$INSTALL_TYPE"; then
    echo -e "${GREEN}✓ '$app' successfully installed.${NC}"
    echo -e "${GREEN}Checking installation...${NC}"
    if pushd -- "$app" >/dev/null; then
      if [[ -f app-test.py ]]; then
        echo uv run --no-sync -p "$AGI_PYTHON_VERSION" python app-test.py
        uv run --no-sync -p "$AGI_PYTHON_VERSION" python app-test.py
      else
        echo -e "${BLUE}No app-test.py in $app, skipping tests.${NC}"
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
  echo -e "${GREEN}Installation of apps complete!${NC}"
else
  echo -e "${YELLOW}Installation finished with some errors (status=$status).${NC}"
fi

exit "$status"
