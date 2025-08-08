#!/usr/bin/env bash
# link_apps.sh — create/refresh app symlinks pointing to thales-agilab/src/agilab/apps/<app>
# Usage:
#   ./link_apps.sh app1 app2 ...
#   INCLUDED_APPS="app1 app2" ./link_apps.sh
#   apps=(app1 app2) ./link_apps.sh
#
# Optional env:
#   THALES_AGILAB_ROOT=/abs/path/to/thales-agilab
#   DEST_BASE=/where/links/should/live   (default: ".")
#
set -euo pipefail

# Colors
BLUE='\033[1;34m'; GREEN='\033[1;32m'; YELLOW='\033[1;33m'; RED='\033[1;31m'; NC='\033[0m'

echo -e "${YELLOW}CWD:${NC} $(pwd)"

# Directory where this script lives (resolves symlinks)
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"

# ---------- Resolve app list ----------
declare -a INCLUDED_APPS=()

# 1) From CLI args
if (( $# > 0 )); then
  INCLUDED_APPS=("$@")
fi

# 2) From env var INCLUDED_APPS (space-separated)
if (( ${#INCLUDED_APPS[@]} == 0 )) && [[ -n "${INCLUDED_APPS:-}" ]]; then
  # shellcheck disable=SC2206 # intentional word splitting
  INCLUDED_APPS=(${INCLUDED_APPS})
fi

# 3) From predeclared Bash array: apps=(...)
if (( ${#INCLUDED_APPS[@]} == 0 )) && declare -p apps &>/dev/null; then
  # shellcheck disable=SC2154 # apps may be defined by caller
  INCLUDED_APPS=("${apps[@]}")
fi

if (( ${#INCLUDED_APPS[@]} == 0 )); then
  echo -e "${RED}No apps provided.${NC} Pass apps as args, set INCLUDED_APPS env, or define a Bash array 'apps'."
  echo "Example: INCLUDED_APPS='flight_project sat_trajectory_project' $0"
  exit 2
fi

# Where to create the symlinks (default current directory)
DEST_BASE="${DEST_BASE:-.}"
mkdir -p -- "$DEST_BASE"

# ---------- Locate thales-agilab ----------
find_thales_agilab() {
  local d="$SCRIPT_DIR"
  while [[ "$d" != "/" ]]; do
    if [[ -d "$d/thales-agilab/src/agilab/apps" ]]; then
      printf "%s\n" "$d/thales-agilab"
      return 0
    fi
    d="$(dirname -- "$d")"
  done
  return 1
}

THALES_AGILAB_ROOT="${THALES_AGILAB_ROOT:-}"
if [[ -z "$THALES_AGILAB_ROOT" ]]; then
  if ! THALES_AGILAB_ROOT="$(find_thales_agilab)"; then
    echo -e "${RED}Could not locate 'thales-agilab/src/agilab/apps' by walking up from:${NC} $SCRIPT_DIR"
    echo -e "${RED}Tip:${NC} export THALES_AGILAB_ROOT=/absolute/path/to/thales-agilab and re-run."
    exit 1
  fi
fi

TARGET_BASE="$THALES_AGILAB_ROOT/src/agilab/apps"
if [[ ! -d "$TARGET_BASE" ]]; then
  echo -e "${RED}Missing directory:${NC} $TARGET_BASE"
  exit 1
fi

echo -e "${YELLOW}Using THALES_AGILAB_ROOT:${NC} $THALES_AGILAB_ROOT"
echo -e "${YELLOW}Link target base:${NC} $TARGET_BASE"
echo -e "${YELLOW}Destination base:${NC} $(cd -- "$DEST_BASE" && pwd -P)"
echo

# ---------- Create/refresh symlinks ----------
status=0
for app in "${INCLUDED_APPS[@]}"; do
  app_dest="$DEST_BASE/$app"       # where the link will be created
  app_target="$TARGET_BASE/$app"   # the absolute target

  if [[ ! -e "$app_target" ]]; then
    echo -e "${RED}Target for '${app}' does not exist:${NC} $app_target — skipping."
    status=1
    continue
  fi

  # If destination exists and is a symlink (even broken), replace it
  if [[ -L "$app_dest" ]]; then
    echo -e "${BLUE}${app_dest}${NC} is a symlink. Recreating -> ${app_target}"
    rm -f -- "$app_dest"
    ln -s -- "$app_target" "$app_dest"
  elif [[ ! -e "$app_dest" ]]; then
    echo -e "${BLUE}Creating symlink:${NC} $app_dest -> $app_target"
    ln -s -- "$app_target" "$app_dest"
  else
    # Exists and is not a symlink (real dir or file) — leave it
    echo -e "${GREEN}${app_dest}${NC} exists and is not a symlink. Leaving untouched."
  fi
done

exit "$status"
