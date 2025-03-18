#!/bin/bash

PYTHON_VERSION="3.12"
RED='\033[0;31m'
NC='\033[0m' # No Color

Agi_PATH_FILE="$HOME/.local/share/agilab/.agi-path"
if [ -f "$Agi_PATH_FILE" ]; then
    AgiROOT="$(cat "$Agi_PATH_FILE")"
else
    echo -e "${RED}Please install agilab before running it!${NC}"
fi
AgiPROJECT="$AgiROOT/agi"
AgiLAB="$AgiPROJECT/fwk/lab"
AgiEDIT="$AgiLAB/src/agi_lab/AGILab.py"

echo "Running 'uv run streamlit run "$AgiEDIT"' from '$AgiLAB'"

cd $AgiLAB
uv run streamlit run $AgiEDIT