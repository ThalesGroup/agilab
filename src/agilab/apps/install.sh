#!/usr/bin/env bash
# install_agilab_apps.sh — auto-detect thales-agilab and (re)create app symlinks

set -euo pipefail

# ------------------
# Colors
# ------------------
BLUE='\033[1;34m'
GREEN='\033[1;32m'
YELLOW='\033[1;33m'
RED='\033[1;31m'
NC='\033[0m'

# ------------------
# Resolve INCLUDED_APPS (CLI args > env INCLUDED_APPS > bash array apps)
# No defaults — must be provided explicitly.
# ------------------
declare -a INCLUDED_APPS=(
mycode_project
flight_project
flight_trajectory
sat_trajectory
link_sim
#flight_legacy
)

DEST_BASE=$(pwd)/apps

if (( $# > 0 )); then
  INCLUDED_APPS=("$@")
elif [[ -n "${INCLUDED_APPS:-}" ]]; then
  # shellcheck disable=SC2206
  INCLUDED_APPS=(${INCLUDED_APPS})
elif declare -p apps &>/dev/null; then
  # shellcheck disable=SC2154
  INCLUDED_APPS=("${apps[@]}")
fi

# Fail if no apps provided
if (( ${#INCLUDED_APPS[@]} == 0 )); then
  echo -e "${RED}Error:${NC} No apps specified."
  echo "Usage: $0 app1 app2 ..."
  echo "   or: INCLUDED_APPS='app1 app2' $0"
  echo "   or: apps=(app1 app2); $0"
  exit 2
fi

# --- Normalize & validate app names ---
clean=()
for a in "${INCLUDED_APPS[@]}"; do
  [[ -z "${a// }" ]] && continue
  a="${a//\\//}"      # backslashes to slashes
  a="${a##*/}"        # basename
  [[ -z "${a// }" ]] && continue

  if [[ "$a" =~ ^[0-9]+$ ]]; then
    echo -e "${YELLOW}Skipping token '$a' (pure number).${NC}"
    continue
  fi

  clean+=("$a")
done
INCLUDED_APPS=("${clean[@]}")

if (( ${#INCLUDED_APPS[@]} == 0 )); then
  echo -e "${RED}Error:${NC} No valid app names after normalization."
  exit 2
fi

# Show the final app list
echo -e "${YELLOW}Apps to link:${NC} ${INCLUDED_APPS[*]}"

# ------------------
# Destination base (must be explicitly set)
# ------------------
if [[ -z "${DEST_BASE:-}" ]]; then
  echo -e "${RED}Error:${NC} DEST_BASE is not set."
  echo "Set DEST_BASE to the folder where symlinks should be created."
  exit 2
fi
mkdir -p -- "$DEST_BASE"

echo -e "${YELLOW}Installing Apps...${NC}"
echo -e "${YELLOW}Working directory:${NC} $(pwd)"
echo -e "${YELLOW}Destination base:${NC} $(cd -- "$DEST_BASE" && pwd -P)"

# ------------------
# Finder: search under $HOME (depth-limited) for */src/agilab/apps
# ------------------
find_thales_agilab() {
  local depth="${1:-5}"
  local hit
  hit="$(find "$HOME" -maxdepth "$depth" -type d -path '*/src/agilab/apps' 2>/dev/null | head -n 1)"
  if [[ -n "$hit" ]]; then
    printf '%s\n' "${hit%/src/agilab/apps}"
    return 0
  fi
  return 1
}

THALES_AGILAB_ROOT="${THALES_AGILAB_ROOT:-}"
if [[ -z "$THALES_AGILAB_ROOT" ]]; then
  if ! THALES_AGILAB_ROOT="$(find_thales_agilab 5)"; then
    echo -e "${RED}Error:${NC} Could not locate '*/src/agilab/apps' starting from $HOME."
    echo -e "${YELLOW}Hint:${NC} export THALES_AGILAB_ROOT=/absolute/path/to/thales-agilab and re-run."
    exit 1
  fi
fi

TARGET_BASE="$THALES_AGILAB_ROOT/src/agilab/apps"
if [[ ! -d "$TARGET_BASE" ]]; then
  echo -e "${RED}Error:${NC} Missing directory: $TARGET_BASE"
  exit 1
fi

echo -e "${YELLOW}Using THALES_AGILAB_ROOT:${NC} $THALES_AGILAB_ROOT"
echo -e "${YELLOW}Link target base:${NC} $TARGET_BASE"
echo

# ------------------
# Create / refresh symlinks
# ------------------
status=0
for app in "${INCLUDED_APPS[@]}"; do
  app_target="$TARGET_BASE/$app"
  app_dest="$DEST_BASE/$app"

  if [[ ! -e "$app_target" ]]; then
    echo -e "${RED}Target for '${app}' not found:${NC} $app_target — skipping."
    status=1
    continue
  fi

  if [[ -L "$app_dest" ]]; then
    echo -e "${BLUE}App '$app_dest' is a symlink. Recreating -> '$app_target'...${NC}"
    rm -f -- "$app_dest"
    ln -s -- "$app_target" "$app_dest"
  elif [[ ! -e "$app_dest" ]]; then
    echo -e "${BLUE}App '$app_dest' does not exist. Creating symlink -> '$app_target'...${NC}"
    ln -s -- "$app_target" "$app_dest"
  else
    echo -e "${GREEN}App '$app_dest' exists and is not a symlink. Leaving untouched.${NC}"
  fi
done

exit "$status"
