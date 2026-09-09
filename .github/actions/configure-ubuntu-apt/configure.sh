#!/usr/bin/env bash
# CI-only setup for Ubuntu runners. An alternate APT directory supports isolated tests.
set -euo pipefail

apt_dir="${1:-/etc/apt}"
if [[ "$apt_dir" != /* || "$apt_dir" == *\"* || "$apt_dir" == *\\* || "$apt_dir" == *$'\n'* || "$apt_dir" == *$'\r'* ]]; then
  echo "APT directory must be absolute and contain no quotes, backslashes or newlines." >&2
  exit 1
fi
ubuntu_source="$apt_dir/sources.list.d/ubuntu.sources"
if [[ ! -s "$ubuntu_source" ]]; then
  echo "Expected Ubuntu runner source file $ubuntu_source; refusing to use unrelated repositories." >&2
  exit 1
fi

# All APT callers, including Playwright's sudo subprocess, read this configuration.
# Keep the runner's archive mirrors, suites and Signed-By keyring unchanged.
# See https://manpages.ubuntu.com/manpages/noble/man5/apt.conf.5.html
mkdir -p "$apt_dir/apt.conf.d"
cat > "$apt_dir/apt.conf.d/99-agilab-ubuntu-sources" <<EOF
Dir::Etc::sourcelist "$ubuntu_source";
Dir::Etc::sourceparts "-";
APT::Update::Error-Mode "any";
EOF
echo "APT configured to use $ubuntu_source; package index errors remain fatal."
