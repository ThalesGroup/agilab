Beta readiness
==============

AGILAB now uses the PyPI ``Beta`` classifier after a single release candidate
proved that the public adoption path is repeatable.
This page is the maintainer checklist for that decision. It is intentionally
stricter than the normal release preflight because a classifier change is a
public maturity signal, not just a version bump.

Decision rule
-------------

Promote the next public release to beta when all of these are true:

- The repository is clean and ``HEAD`` matches ``origin/main``.
- All release-package classifiers are switched together from the previous
  ``Alpha`` classifier to ``Development Status :: 4 - Beta``.
- The full PyPI release preflight passes locally.
- The built-in ``flight_telemetry_project`` first proof passes from a clean install path.
- The public Hugging Face Space is public, running, and serves the same SHA as
  the uploaded Space repository.
- The Space source tree contains only public app entries under
  ``src/agilab/apps``.
- Public docs no longer describe the promoted release as pre-beta software.
- The release notes state the beta scope clearly: experimentation and
  engineering prototyping, not production serving or enterprise MLOps.

Executable gate
---------------

Use the beta readiness tool before editing classifiers:

.. code-block:: bash

   uv --preview-features extra-build-dependencies run python tools/beta_readiness.py

This planning mode checks that the release machinery, public app tree, and beta
documentation are present. It intentionally allows the previous ``Alpha``
classifier so maintainers can run it before making the classifier change.

After the classifier and docs wording have been updated for the release
candidate, run the strict final gate:

.. code-block:: bash

   uv --preview-features extra-build-dependencies run python tools/beta_readiness.py --final --include-network

The strict gate fails if any release package still carries the alpha classifier,
if the local checkout is dirty, if the branch is not aligned with
``origin/main``, or if the Hugging Face Space is not public and running the
current uploaded SHA.

Final RC commands
-----------------

The beta gate prints the final release-candidate commands. Run them before
publishing a beta-classified package:

.. code-block:: bash

   uv --preview-features extra-build-dependencies run python tools/workflow_parity.py --profile agi-env --profile agi-core-combined --profile agi-gui --profile docs --profile installer --profile shared-core-typing --profile dependency-policy
   uv --preview-features extra-build-dependencies run python tools/workflow_parity.py --profile security-adoption
   uv --preview-features extra-build-dependencies run python tools/newcomer_first_proof.py --with-install
   uv --preview-features extra-build-dependencies run python tools/pypi_publish.py --repo testpypi --dry-run --verbose
   uv --preview-features extra-build-dependencies run python tools/hf_space_smoke.py --json

The ``security-adoption`` profile writes ``test-results/security-check.json``
using the ``shared`` adoption profile. It remains non-blocking unless
``AGILAB_SECURITY_CHECK_STRICT=1`` is set; with that variable enabled, missing
shared-deployment controls such as SBOM evidence, app-repository allowlists, or
public-bind controls fail the gate.

If any command fails, keep the public classifier at alpha and fix the underlying
reproducibility, install, demo, or publication issue first.

Scope of beta
-------------

The first beta should mean:

- The public demo and local first proof are reliable enough for external
  evaluators.
- The project has repeatable release gates, docs, and packaging evidence.
- Built-in examples can be installed and inspected without private repositories.

It should not imply:

- Production model serving.
- Feature-store, drift-monitoring, or online retraining coverage.
- Enterprise governance, audit workflow, or hardened multi-tenant deployment.
- Cloud/Kubernetes production parity.

Keep that scope explicit in release notes and public documentation.
