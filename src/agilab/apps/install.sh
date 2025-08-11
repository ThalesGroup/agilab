#!/usr/bin/env bash
# install_agilab_apps.sh — auto-detect thales-agilab and (re)create app symlinks
set -euo pipefail

# Colors
BLUE='\033[1;34m'; GREEN='\033[1;32m'; YELLOW='\033[1;33m'; RED='\033[1;31m'; NC='\033[0m'

# Env + Python version normalization
source "$HOME/.local/share/agilab/.env"
AGI_PYTHON_VERSION=$(echo "$AGI_PYTHON_VERSION" | sed -E 's/^([0-9]+\.[0-9]+\.[0-9]+(\+freethreaded)?).*/\1/')
export AGI_PYTHON_VERSION

# Installer entrypoint (relative to src/agilab/apps)
APP_INSTALL="uv -q run -p $AGI_PYTHON_VERSION --project ../core/cluster python install.py"

PUBLIC_AGILAB="$(cat $HOME/.local/share/agilab/.agilab-path)"
PRIVATE_AGILAB=""

# Default app list matching your repo (only *_project)
declare -a PRIVATE_APPS=(
  flight_trajectory_project
  sat_trajectory_project
  link_sim_project
  # flight_legacy_project
)

declare -a PUBLIC_APPS=(
  mycode_project
  flight_project
)

# Merge both into INCLUDED_APPS
declare -a INCLUDED_APPS=("${PRIVATE_APPS[@]}" "${PUBLIC_APPS[@]}")

# DEST_BASE default (overridable by env); where links are created
: "${DEST_BASE:=$(pwd)}"
mkdir -p -- "$DEST_BASE"

echo "create symlink for apps: ${PRIVATE_APPS[@]}"

if (( ${#PRIVATE_APPS[@]} == 0 )); then
  echo -e "${RED}Error:${NC} No apps specified."
  exit 2
fi

echo -e "${YELLOW}Installing Apps...${NC}"
echo -e "${YELLOW}Working directory:${NC} $(pwd)"
echo -e "${YELLOW}Destination base:${NC} $(cd -- "$DEST_BASE" && pwd -P)"

# Normalize & filter: only keep *_project; skip 'apps' & pure numbers
declare -a clean=()
dest_base_basename="$(basename -- "$DEST_BASE")"

for a in "${PRIVATE_APPS[@]}"; do
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
PRIVATE_APPS=("${clean[@]:-}")
if (( ${#PRIVATE_APPS[@]} == 0 )); then
  echo -e "${RED}Error:${NC} No valid app names after filtering."
  exit 2
fi

echo -e "${YELLOW}Apps to link:${NC} ${PRIVATE_APPS[*]}"

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

if [[ -z "$PRIVATE_AGILAB" ]]; then
  if ! PRIVATE_AGILAB="$(find_thales_agilab 5)"; then
    echo -e "${RED}Error:${NC} Could not locate '*/src/agilab/apps' from $HOME."
    exit 1
  fi
fi

TARGET_BASE="$PRIVATE_AGILAB/src/agilab/apps"
[[ -d "$TARGET_BASE" ]] || { echo -e "${RED}Error:${NC} Missing directory: $TARGET_BASE"; exit 1; }

echo -e "${YELLOW}Using PRIVATE_AGILAB:${NC} $PRIVATE_AGILAB"
echo -e "${YELLOW}Link target base:${NC} $TARGET_BASE"
echo

# Create / refresh symlinks
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

# Build the list of apps present in DEST_BASE (only *_project + included)
declare -a apps=()
while IFS= read -r -d '' dir; do
  dir_name="$(basename -- "$dir")"
  # keep only names present in PRIVATE_APPS (already filtered to *_project)
  if [[ " ${INCLUDED_APPS[*]} " == *" $dir_name "* ]]; then
    apps+=("$dir_name")
  fi
done < <(find "$DEST_BASE" -mindepth 1 -maxdepth 1 -type d -name '*_project' -print0)

echo -e "${BLUE}Apps to install:${NC} ${apps[*]:-<none>}"

# Where APP_INSTALL's relative path (../core/cluster) is valid:
#   apps cwd -> ../core/cluster == "$PRIVATE_AGILAB/src/agilab/core/cluster"
pushd -- "$PUBLIC_AGILAB/apps" >/dev/null

# Allow overriding install type via env; default 1
INSTALL_TYPE="${INSTALL_TYPE:-1}"

for app in "${apps[@]}"; do
  echo -e "${BLUE}Installing $app...${NC}"
  if eval "$APP_INSTALL \"$app\" --apps-dir \"$(pwd)\" --install-type \"$INSTALL_TYPE\""; then
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

# Final Message
if (( status == 0 )); then
  echo -e "${GREEN}Installation of apps complete!${NC}"
else
  echo -e "${YELLOW}Installation finished with some errors (status=$status).${NC}"
fi

# Patch PyCharm interpreter settings in workspace.xml if the patcher exists
if [[ -f "$PUBLIC_AGILAB/src/agilab/apps/patch_workspace.py" ]]; then
  echo -e "${BLUE}Patching PyCharm workspace.xml interpreter settings...${NC}"
  ( cd "$PUBLIC_AGILAB/src/agilab/apps" && uv run python patch_workspace.py )
else
  echo -e "${YELLOW}patch_workspace.py not found; skipping interpreter patch.${NC}"
fi

exit "$status"
