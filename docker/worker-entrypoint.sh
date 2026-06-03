#!/bin/bash
set -e

# Set root password from CLUSTER_CREDENTIALS (format: user:password)
if [[ -n "${CLUSTER_CREDENTIALS}" && "${CLUSTER_CREDENTIALS}" == *:* ]]; then
    echo "root:${CLUSTER_CREDENTIALS#*:}" | chpasswd
fi

# Write minimal .env so AgiEnv can initialise on this worker
mkdir -p /root/.agilab /root/.local/share/agilab
cat > /root/.agilab/.env <<EOF
CLUSTER_CREDENTIALS="${CLUSTER_CREDENTIALS:-root:password}"
AGI_PYTHON_VERSION="${AGI_PYTHON_VERSION:-3.13.9}"
AGI_PYTHON_FREE_THREADED="${AGI_PYTHON_FREE_THREADED:-0}"
AGI_CLUSTER_SHARE="/root/clustershare"
AGI_LOCAL_SHARE="/root/localshare"
IS_SOURCE_ENV="1"
EOF

mkdir -p /root/clustershare /root/localshare

exec /usr/sbin/sshd -D
