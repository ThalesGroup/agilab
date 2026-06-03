Trusted shared deployment
=========================

AGILAB is a trusted-operator workbench. Shared/team use is a go only when the
operator records the hardening evidence for the actual deployment profile. This
page is the handoff checklist for a shared workstation, SSH/Dask cluster,
reviewed external apps repository, local/offline LLM profile, public UI behind
a front end, or sensitive internal dataset.

Go gate
-------

Archive these artifacts before treating a shared/team deployment as ready:

.. code-block:: bash

   uv --preview-features extra-build-dependencies run agilab security-check \
     --profile shared --strict --json > test-results/security-check.json
   uv --preview-features extra-build-dependencies run python tools/profile_supply_chain_scan.py \
     --profile all --run
   uv --preview-features extra-build-dependencies run python tools/shared_go_gate.py \
     --security-check-json test-results/security-check.json \
     --supply-chain-dir test-results/supply-chain \
     --install-profile all \
     --output test-results/shared_go_gate.json \
     --strict

The gate decision is ``go`` only when ``security-check`` passes and each
deployed install profile has fresh JSON ``pip-audit`` and CycloneDX SBOM
artifacts. Keep ``shared_go_gate.json`` with the deployment evidence.

Public UI evidence
------------------

``AGILAB_PUBLIC_BIND_OK=1`` plus an auth/TLS indicator is a runtime policy
acknowledgement, not proof that the front end is actually safe. For shared or
public profiles, write a small reviewed artifact and set
``AGILAB_PUBLIC_BIND_EVIDENCE`` to that file before running the gate. The file
should record the reverse proxy, SSO/auth control, TLS termination, network ACL,
reviewer, and date.

Cluster evidence
----------------

Rediscover workers before using a remembered IP:

The discovery command starts with ``tools/cluster_flight_validation.py --discover-lan``.

.. code-block:: bash

   uv --preview-features extra-build-dependencies run --no-sync python tools/cluster_flight_validation.py \
     --discover-lan \
     --remote-user "<worker-user>" \
     --json \
     --no-discovery-cache

Then prove the shared mount before running compute:

.. code-block:: bash

   uv --preview-features extra-build-dependencies run --no-sync python tools/cluster_flight_validation.py \
     --cluster \
     --scheduler "<scheduler-ip>" \
     --workers "<worker-user>@<worker-ip>" \
     --setup-share sshfs \
     --apply
   uv --preview-features extra-build-dependencies run --no-sync python tools/cluster_flight_validation.py \
     --cluster \
     --scheduler "<scheduler-ip>" \
     --workers "<worker-user>@<worker-ip>" \
     --share-check-only

If setup fails with scheduler SSH unreachable, enable SSH on the
scheduler/manager, install the worker public key on the scheduler, and verify
``ssh <scheduler>`` from the worker before retrying SSHFS.

What remains no-go
------------------

This gate does not turn AGILAB into a multi-tenant production MLOps control
plane. Public Streamlit without a hardened front end, regulated production
serving, enterprise governance, online monitoring, drift detection, and
audit-trail ownership remain outside the safe-as-is boundary.
