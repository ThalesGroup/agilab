#!/usr/bin/env bash
# install_agilab_apps.sh — auto-detect thales-agilab and (re)create app symlinks

set -euo pipefail

# Optional env (uncomment if you use it elsewhere)
# source "$HOME/.local/share/agilab/.env" || true

# ------------------
# Colors
# ------------------
BLUE='\033[1;34m'
GREEN='\033[1;32m'
YELLOW='\033[1;33m'
RED='\033[1;31m'
NC='\033[0m'

# ------------------
# Config
# ------------------
# Provide apps one of three ways (priority order):
#   1) CLI args: ./install_agilab_apps.sh app1 app2
#   2) Env var:  INCLUDED_APPS="app1 app2" ./install_agilab_apps.sh
#   3) Bash arr: apps=(app1 app2); ./install_agilab_apps.sh
declare -a INCLUDED_APPS=()
if (( $# > 0 )); then
  INCLUDED_APPS=("$@")
elif [[ -n "${INCLUDED_APPS:-}" ]]; then
  # shellcheck disable=SC2206
  INCLUDED_APPS=(${INCLUDED_APPS})
elif declare -p apps &>/dev/null; then
  INCLUDED_APPS=("${apps[@]}")
fi

if (( ${#INCLUDED_APPS[@]} == 0 )); then
  echo -e "${RED}No apps specified.${NC}"
  echo "Usage: $0 app1 app2 ..."
  echo "   or: INCLUDED_APPS='app1 app2' $0"
  echo "   or: apps=(app1 app2); $0"
  exit 2
fi

# Where to create the links (default current dir). Override with: DEST_BASE=/path $0 ...
DEST_BASE="${DEST_BASE:-.}"
mkdir -p -- "$DEST_BASE"

echo -e "${YELLOW}Working directory:${NC} $(pwd)"
echo -e "${YELLOW}Destination base:${NC} $(cd -- "$DEST_BASE" && pwd -P)"

# ------------------
# Auto-detect thales-agilab root
# ------------------
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"

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
    echo -e "${RED}Could not locate 'thales-agilab/src/agilab/apps' starting from:${NC} $SCRIPT_DIR"
    echo -e "${RED}Hint:${NC} set THALES_AGILAB_ROOT=/absolute/path/to/thales-agilab and re-run."
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
echo

# ------------------
# Link creation
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
    # Existing symlink (even if broken): refresh it to ensure correct target
    echo -e "${BLUE}App '$app_dest' is a symlink. Recreating -> '$app_target'...${NC}"
    rm -f -- "$app_dest"
    ln -s -- "$app_target" "$app_dest"
  elif [[ ! -e "$app_dest" ]]; then
    echo -e "${BLUE}App '$app_dest' does not exist. Creating symlink -> '$app_target'...${NC}"
    ln -s -- "$app_target" "$app_dest"
  else
    # Exists and is not a symlink (real dir/file) — leave untouched
    echo -e "${GREEN}App '$app_dest' exists and is not a symlink. Leaving untouched.${NC}"
  fi
done

exit "$status"
