
#!/bin/bash

# Script: install_Agi_apps.sh
# Purpose: Install the apps

# Exit immediately if a command exits with a non-zero status
set -e

APP_INSTALL="uv run --project ../fwk/core/managers python install.py"

# List only the apps that you want to install
INCLUDED_APPS=(
    "my-code-project"
    "flight-project"
)

# Function to check if an element is in an array
containsElement () {
  local element
  for element in "${@:2}"; do
    if [[ "$element" == "$1" ]]; then
      return 0
    fi
  done
  return 1
}

main() {
  echo "Retrieving all apps..."

  apps=()

  # Loop through each directory ending with '/'
  for dir in */; do
      if [ -d "$dir" ]; then
          dir_name=$(basename "$dir")

          # Only add the directory if its name is in the INCLUDED_APPS list and it matches the pattern '-project'
          if containsElement "$dir_name" "${INCLUDED_APPS[@]}" && [[ "$dir_name" =~ -project$ ]]; then
              apps+=("$dir_name")
          fi
      fi
  done

  echo "Apps to install: ${apps[@]}"

  for app in "${apps[@]}"; do
      echo "Installing $app..."
      if eval "$APP_INSTALL $app"; then
          echo "✓ '$app' successfully installed."
      else
          echo "✗ '$app' installation failed."
          exit 1
      fi
  done

  # Final Message
  echo "Installation of apps complete!"
}

main