#!/usr/bin/env bash
# install_agilab_apps.sh — auto-detect thales-agilab and (re)create app symlinks
set -euo pipefail

# Colors
BLUE='\033[1;34m'; GREEN='\033[1;32m'; YELLOW='\033[1;33m'; RED='\033[1;31m'; NC='\033[0m'

source "$HOME/.local/share/agilab/.env"
AGI_PYTHON_VERSION=$(echo "$AGI_PYTHON_VERSION" | sed -E 's/^([0-9]+\.[0-9]+\.[0-9]+(\+freethreaded)?).*/\1/')
export AGI_PYTHON_VERSION

APP_INSTALL="uv -q run -p $AGI_PYTHON_VERSION --project ../core/cluster python install.py"
# Default app list matching your repo (only *_project)
declare -a INCLUDED_APPS=(
  flight_trajectory_project
  sat_trajectory_project
  link_sim_project
  # flight_legacy_project
)

# DEST_BASE default (overridable by env)
: "${DEST_BASE:=$(pwd)}"
mkdir -p -- "$DEST_BASE"

echo "create symlink for apps: ${INCLUDED_APPS[@]}"

if (( ${#INCLUDED_APPS[@]} == 0 )); then
  echo -e "${RED}Error:${NC} No apps specified."; exit 2
fi

echo -e "${YELLOW}Installing Apps...${NC}"
echo -e "${YELLOW}Working directory:${NC} $(pwd)"
echo -e "${YELLOW}Destination base:${NC} $(cd -- "$DEST_BASE" && pwd -P)"

# Normalize & filter: only keep *_project; skip 'apps' & numbers
declare -a clean=()
dest_base_basename="$(basename -- "$DEST_BASE")"

for a in "${INCLUDED_APPS[@]}"; do
  [[ -z "${a// }" ]] && continue
  a="${a//\\//}"; a="${a##*/}"
  [[ -z "${a// }" ]] && continue

  # Skip pure numbers
  if [[ "$a" =~ ^[0-9]+$ ]]; then
    echo -e "${YELLOW}Skipping token '$a' (no '_project' suffix).${NC}"
    continue
  fi
  # Skip token equal to DEST_BASE basename (e.g., 'apps')
  if [[ "$a" == "$dest_base_basename" ]]; then
    echo -e "${YELLOW}Skipping token '$a' (no '_project' suffix).${NC}"
    continue
  fi
  # Enforce *_project
  if [[ ! "$a" =~ _project$ ]]; then
    echo -e "${YELLOW}Skipping token '$a' (no '_project' suffix).${NC}"
    continue
  fi

  clean+=("$a")
done

# Nounset-safe array assignment
INCLUDED_APPS=("${clean[@]:-}")
if (( ${#INCLUDED_APPS[@]} == 0 )); then
  echo -e "${RED}Error:${NC} No valid app names after filtering."; exit 2
fi

echo -e "${YELLOW}Apps to link:${NC} ${INCLUDED_APPS[*]}"

# Finder under $HOME; strip /src/agilab/apps
find_thales_agilab() {
  local depth="${1:-5}" hit
  hit="$(
    find "$HOME" \
      -maxdepth "$depth" \
      \( -path "$HOME/Music" -o -path "$HOME/Documents" -o -path "$HOME/Desktop" \
         -o -path "$HOME/Library/Mobile Documents" -o -path "$HOME/Library/Application Support" \
      \) -prune -o \
      -type d -path '*/src/agilab/apps' -print 2>/dev/null | head -n 1
  )"
  [[ -n "$hit" ]] && { printf '%s\n' "${hit%/src/agilab/apps}"; return 0; }
  return 1
}

THALES_AGILAB_ROOT="${THALES_AGILAB_ROOT:-}"
if [[ -z "$THALES_AGILAB_ROOT" ]]; then
  if ! THALES_AGILAB_ROOT="$(find_thales_agilab 5)"; then
    echo -e "${RED}Error:${NC} Could not locate '*/src/agilab/apps' from $HOME."; exit 1
  fi
fi

TARGET_BASE="$THALES_AGILAB_ROOT/src/agilab/apps"
[[ -d "$TARGET_BASE" ]] || { echo -e "${RED}Error:${NC} Missing directory: $TARGET_BASE"; exit 1; }

echo -e "${YELLOW}Using THALES_AGILAB_ROOT:${NC} $THALES_AGILAB_ROOT"
echo -e "${YELLOW}Link target base:${NC} $TARGET_BASE"
echo

# Create / refresh symlinks
status=0
for app in "${INCLUDED_APPS[@]}"; do
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


# Loop through each directory ending with '/'
for dir in $1/*/; do
    if [ -d "$dir" ]; then
        dir_name=$(basename "$dir")
        # Only add the directory if its name is in the INCLUDED_APPS list and it matches the pattern '_project'
        if [[ " ${INCLUDED_APPS[*]} " == *" $dir_name "* ]] && [[ "$dir_name" =~ _project$ ]]; then
            apps+=("$dir_name")
        fi
    fi
done

echo -e "${BLUE}Apps to install:${NC} ${apps[*]}"

pushd ../apps
for app in "${apps[@]}"; do
    echo -e "${BLUE}Installing $app...${NC}"
    if eval "$APP_INSTALL $app --apps-dir $(pwd) --install-type $2"; then
        echo -e "${GREEN}✓ '$app' successfully installed.${NC}"
        echo -e "${GREEN}Checking installation...${NC}"
        pushd $app
        if [[ -f run-all-test.py ]]; then
            uv run -p "$AGI_PYTHON_VERSION" python run-all-test.py
        else
            echo -e "${BLUE}No run-all-test.py in $app, skipping tests.${NC}"
        fi
        popd
    else
        echo -e "${RED}✗ '$app' installation failed.${NC}"
        exit 1
    fi
done
popd

# Final Message
echo -e "${GREEN}Installation of apps complete!${NC}"

# Patch PyCharm interpreter settings in workspace.xml
echo -e "${BLUE}Patching PyCharm workspace.xml interpreter settings...${NC}"
uv run python patch_workspace.py

