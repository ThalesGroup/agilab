#!/bin/bash
# Script: install_Agi_apps.sh
# Purpose: Install the apps (apps-only; no positional args required)

set -euo pipefail

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

TARGET_BASE="$AGILAB_PRIVATE/src/agilab/apps"
[[ -d "$TARGET_BASE" ]] || { echo -e "${RED}Error:${NC} Missing directory: $TARGET_BASE"; exit 1; }

INSTALL_TYPE="${INSTALL_TYPE:-1}"

export AGI_PYTHON_VERSION
export PYTHONPATH="$PWD:${PYTHONPATH-}"

# --- App lists (merge private + public) --------------------------------------

# Destination base for creating local app symlinks (defaults to current dir)
: "${DEST_BASE:=$(pwd)}"
mkdir -p -- "$DEST_BASE"
echo -e "${YELLOW}Destination base:${NC} $(cd -- "$DEST_BASE" && pwd -P)"
echo -e "${YELLOW}Using AGILAB_PRIVATE:${NC} $AGILAB_PRIVATE"
echo -e "${YELLOW}Link target base:${NC} $TARGET_BASE\n"

declare -a PRIVATE_APPS=(
   flight_trajectory_project
   sat_trajectory_project
   link_sim_project
   sb3_trainer_project
)

# --- Build the list of apps present locally (only *_project) -----------------
declare -a PUBLIC_APPS=()
while IFS= read -r -d '' dir; do
  dir_name="$(basename -- "$dir")"
  PUBLIC_APPS+=("$dir_name")
done < <(find "$DEST_BASE" -mindepth 1 -maxdepth 1 -type d -name '*_project' -print0)

if [[ -z "$AGILAB_PRIVATE" ]]; then
  declare -a INCLUDED_APPS=("${PUBLIC_APPS[@]}")
else
  declare -a INCLUDED_APPS=("${PRIVATE_APPS[@]}" "${PUBLIC_APPS[@]}")
fi

echo -e "${BLUE}Apps to install:${NC} ${INCLUDED_APPS[*]:-<none>}\n"

# --- Ensure local symlinks exist/refresh in DEST_BASE ------------------------
pushd "$AGILAB_PRIVATE/src/agilab" >/dev/null
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

status=0
for app in "${PRIVATE_APPS[@]}"; do
  app_target="$TARGET_BASE/$app"
  app_dest="$DEST_BASE/$app"

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

# --- Run installer for each app (stable CWD so ../core/cluster resolves) -----
pushd -- "$AGILAB_PUBLIC/apps" >/dev/null

for app in "${INCLUDED_APPS[@]}"; do
  echo -e "${BLUE}Installing $app...${NC}"
  if uv -q run -p "$AGI_PYTHON_VERSION" --project ../core/cluster python install.py \
      "$AGILAB_PUBLIC/apps/$app" --install-type "$INSTALL_TYPE"; then
    echo -e "${GREEN}✓ '$app' successfully installed.${NC}"
    echo -e "${GREEN}Checking installation...${NC}"
    if pushd -- "$app" >/dev/null; then
      if [[ -f run-all-test.py ]]; then
        uv run -p "$AGI_PYTHON_VERSION" python run-all-test.py
      else
        echo -e "${BLUE}No run-all-test.py in $app, skipping tests.${NC}"
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
