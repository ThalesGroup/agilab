#!/bin/bash

# Script: install_Agi_apps.sh
# Purpose: Install the apps

# Exit immediately if a command fails
set -e

#source "$HOME/.local/bin/env"
source "$HOME/.local/share/agilab/.env"

APP_INSTALL="uv run -p $AGI_PYTHON_VERSION --project ../fwk/core/managers python install.py"

# List only the apps that you want to install
INCLUDED_APPS=(
    "my-code-project"
    "flight-project"
)

# Colors
BLUE='\033[1;34m'
GREEN='\033[1;32m'
RED='\033[1;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}Retrieving all apps...${NC}"

apps=()

# Loop through each directory ending with '/'
for dir in */; do
    if [ -d "$dir" ]; then
        dir_name=$(basename "$dir")

        # Only add the directory if its name is in the INCLUDED_APPS list and it matches the pattern '-project'
        if [[ " ${INCLUDED_APPS[*]} " == *" $dir_name "* ]] && [[ "$dir_name" =~ -project$ ]]; then
            apps+=("$dir_name")
        fi
    fi
done

echo -e "${BLUE}Apps to install:${NC} ${apps[*]}"

for app in "${apps[@]}"; do
    echo -e "${BLUE}Installing $app...${NC}"
    if eval "$APP_INSTALL $app --apps-dir $(pwd) --install-type 1"; then
        echo -e "${GREEN}✓ '$app' successfully installed.${NC}"
    else
        echo -e "${RED}✗ '$app' installation failed.${NC}"
        exit 1
    fi
done

# Final Message
echo -e "${GREEN}Installation of apps complete!${NC}"
