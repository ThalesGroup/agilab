#!/bin/bash
# Script to launch gen-app-script.py using uv

# Exit on error
set -e

# Optional: specify Python version if needed
PYTHON_VERSION="3.13"

# Run the script
uv run -p "$PYTHON_VERSION" python pycharm/gen-app-script.py "$@"
