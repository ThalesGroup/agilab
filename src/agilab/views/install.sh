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

TARGET_BASE="$AGILAB_PRIVATE/src/agilab/views"
[[ -d "$TARGET_BASE" ]] || { echo -e "${RED}Error:${NC} Missing directory: $TARGET_BASE"; exit 1; }

INSTALL_TYPE="${INSTALL_TYPE:-1}"

export AGI_PYTHON_VERSION
export PYTHONPATH="$PWD:${PYTHONPATH-}"

# --- App lists (merge private + public) --------------------------------------

# Destination base for creating local app symlinks (defaults to current dir)
: "${DEST_BASE:=$(pwd)}"
mkdir -p -- "$DEST_BASE"
echo -e "${YELLOW}(Views) Destination base:${NC} $(cd -- "$DEST_BASE" && pwd -P)"
echo -e "${YELLOW}(Views) Using AGILAB_PRIVATE:${NC} $AGILAB_PRIVATE"
echo -e "${YELLOW}(Views) Link target base:${NC} $TARGET_BASE\n"

declare -a PRIVATE_VIEWS=(
    maps-network-graph
)

# --- Build the list of apps present locally (only *_project) -----------------
declare -a PUBLIC_VIEWS=()
while IFS= read -r -d '' dir; do
  dir_name="$(basename -- "$dir")"
  PUBLIC_VIEWS+=("$dir_name")
done < <(find "$DEST_BASE" -mindepth 1 -maxdepth 1 -type d ! -name ".venv" -print0)

if [[ -z "$AGILAB_PRIVATE" ]]; then
  declare -a INCLUDED_VIEWS=("${PUBLIC_VIEWS[@]}")
else
  declare -a INCLUDED_VIEWS=("${PRIVATE_VIEWS[@]}" "${PUBLIC_VIEWS[@]}")
fi

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
for view in "${PRIVATE_VIEWS[@]}"; do
  view_target="$TARGET_BASE/$view"
  view_dest="$DEST_BASE/$view"

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

# --- Run installer for each app (stable CWD so ../core/cluster resolves) -----
pushd -- "$AGILAB_PUBLIC/views" >/dev/null

for view in "${INCLUDED_VIEWS[@]}"; do
  echo -e "${BLUE}Installing $view...${NC}"
  pushd "$view" >/dev/null
  uv sync --project . --preview-features extra-build-dependencies
  status=$(echo $?)
  if (( status != 0 )); then
    echo -e "${RED}Error during 'uv sync' for view '$view'.${NC}"
  fi
  popd >/dev/null
done

popd >/dev/null

# --- Final Message -----------------------------------------------------------
if (( status == 0 )); then
  echo -e "${GREEN}Installation of apps complete!${NC}"
else
  echo -e "${YELLOW}Installation finished with some errors (status=$status).${NC}"
fi

exit "$status"
