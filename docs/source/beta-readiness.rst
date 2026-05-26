Beta Readiness
==============

AGILAB's public beta claim is intentionally narrow. The release is ready for a
beta promotion only when the local release gates, public documentation, and
GitHub evidence agree.

Scope
-----

The beta scope covers:

- local reproducible execution
- Dask-based distributed execution
- Streamlit UI workflows for trusted operators
- package-mode install and first-proof evidence
- notebook and Quarto report handoff
- MLflow tracking handoff
- public Hugging Face demo evidence

The production claim remains experimental. Shared workspaces, exposed UIs,
remote workers, credentials, sensitive data, and regulated workflows still need a
deployment threat model, auth/TLS controls, secrets management, and
organization-specific validation.

Required local gates
--------------------

Before release, run the release-preflight parity set:

.. code-block:: bash

   uv --preview-features extra-build-dependencies run python tools/workflow_parity.py \
     --profile agi-env \
     --profile agi-core-combined \
     --profile agi-gui \
     --profile docs \
     --profile installer \
     --profile shared-core-typing \
     --profile ty-typing \
     --profile dependency-policy

Then run the first-proof and publish rehearsal checks:

.. code-block:: bash

   uv --preview-features extra-build-dependencies run python tools/newcomer_first_proof.py --with-run
   uv --preview-features extra-build-dependencies run python tools/pypi_publish.py --repo testpypi --dry-run --verbose

For a final promotion, include the public demo smoke:

.. code-block:: bash

   uv --preview-features extra-build-dependencies run python tools/hf_space_smoke.py --json

Readiness command
-----------------

Use the gate summary before deciding:

.. code-block:: bash

   uv --preview-features extra-build-dependencies run python tools/beta_readiness.py --json

For the final public gate:

.. code-block:: bash

   uv --preview-features extra-build-dependencies run python tools/beta_readiness.py --final --include-network --json

Release boundary
----------------

The release should not be promoted when:

- the working tree is dirty
- ``HEAD`` does not match ``origin/main``
- release-preflight profiles drift from the PyPI publisher workflow
- public docs disagree with the maturity snapshot
- package classifiers drift from the intended public status
- GitHub guardrail or coverage workflows fail on the release commit

Passing the beta gate means AGILAB is suitable for the documented trusted-operator
experimentation and validation workflows. It does not mean AGILAB is a complete
production MLOps platform.
