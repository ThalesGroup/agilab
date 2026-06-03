Kubernetes Job preview
======================

AGILAB does not claim to be a production Kubernetes platform. The first
Kubernetes integration is intentionally smaller: generate a deterministic
``batch/v1`` Job manifest that runs one AGILAB command in a container, then lets
Kubernetes own scheduling, logs, pod lifecycle, and cluster policy.

Use this route after the local first proof works and when you want to validate
that a packaged AGILAB command can run inside an existing Kubernetes cluster.

What is supported
-----------------

- generate a Kubernetes ``Job`` manifest from the AGILAB CLI
- label the Job with the active AGILAB app and backend
- pass environment variables to the runner container
- mount an optional PersistentVolumeClaim for artifacts
- emit YAML or JSON that can be used with ``kubectl apply -f``

What is intentionally not claimed yet
-------------------------------------

- Helm chart ownership
- production ingress, TLS, service mesh, or observability stacks
- multi-tenant RBAC policy design
- GPU scheduling policy
- autoscaling
- Kubernetes-native Dask orchestration
- managed secrets backend integration

Generate a Job manifest
-----------------------

Pick an image that already contains AGILAB and the app payload you want to run.
The default command is the packaged first proof:
``python -m agilab.lab_run first-proof --json --max-seconds 60``.

.. code-block:: bash

   agilab kubernetes-job \
     --app flight_telemetry_project \
     --image ghcr.io/thalesgroup/agilab:2026.05.25 \
     --namespace agilab \
     --pvc agilab-artifacts \
     --output /tmp/agilab-flight-first-proof-job.yaml

Review the file, then apply it with your normal Kubernetes controls:

.. code-block:: bash

   kubectl apply -f /tmp/agilab-flight-first-proof-job.yaml
   kubectl logs job/agilab-flight-telemetry-project -n agilab

Run another AGILAB command
--------------------------

Pass the container command after ``--``:

.. code-block:: bash

   agilab kubernetes-job \
     --app flight_telemetry_project \
     --image ghcr.io/thalesgroup/agilab:2026.05.25 \
     --env OPENAI_MODEL=gpt-4.1-mini \
     --output /tmp/agilab-job.yaml \
     -- \
     python -m agilab.lab_run first-proof --json --with-ui

The generated manifest records that command in an annotation and sets these
runner environment variables:

- ``AGILAB_ACTIVE_APP``
- ``AGILAB_EXECUTION_BACKEND=kubernetes-job``
- ``AGILAB_EXPORT_DIR``

Artifact handoff
----------------

When ``--pvc`` is provided, the Job mounts that PersistentVolumeClaim at
``/agilab/export`` by default. Use ``--mount-path`` if your image expects another
artifact directory.

This is a preview contract, not a full AGILAB distributed runtime backend. The
next useful step is to connect this manifest generator to ORCHESTRATE so the UI
can emit a Kubernetes Job preview beside the existing local and Dask snippets.
