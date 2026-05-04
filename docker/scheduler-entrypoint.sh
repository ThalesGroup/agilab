#!/bin/bash
set -e

# Set root password from CLUSTER_CREDENTIALS so workers can sshfs-mount from this container
if [[ -n "${CLUSTER_CREDENTIALS}" && "${CLUSTER_CREDENTIALS}" == *:* ]]; then
    echo "root:${CLUSTER_CREDENTIALS#*:}" | chpasswd
fi

# Start SSH daemon (workers mount clustershare from this container via sshfs)
/usr/sbin/sshd

# Pre-populate ~/.ssh/config with known worker hostnames so the LAN discovery
# script finds them by name instead of raw IPs.
# DOCKER_WORKERS: comma-separated list, e.g. "worker-1,worker-2"
mkdir -p /root/.ssh
chmod 700 /root/.ssh
if [[ -n "${DOCKER_WORKERS:-}" ]]; then
    IFS=',' read -ra _workers <<< "$DOCKER_WORKERS"
    for _w in "${_workers[@]}"; do
        _w="${_w// /}"
        [[ -z "$_w" ]] && continue
        if ! grep -q "^Host ${_w}$" /root/.ssh/config 2>/dev/null; then
            printf '\nHost %s\n  HostName %s\n  User root\n  StrictHostKeyChecking no\n  UserKnownHostsFile /dev/null\n' \
                "$_w" "$_w" >> /root/.ssh/config
        fi
    done
fi

exec uv --preview-features extra-build-dependencies run streamlit run \
    /app/src/agilab/About_agilab.py -- --apps-path /app/src/agilab/apps
