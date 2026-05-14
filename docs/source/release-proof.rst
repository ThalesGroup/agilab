Release Proof
=============

.. This page is generated from docs/source/data/release_proof.toml by
   tools/release_proof_report.py. Edit the TOML and rerender.

This page is the public verification index for the current AGILAB release. It
records install, CI, demo, and scope evidence in one place so reviewers can
check the release without inferring status from scattered badges.

Current public release
----------------------

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - Item
     - Public evidence
   * - Package version
     - ``agilab[examples]==2026.05.14`` on `PyPI <https://pypi.org/project/agilab/>`__
   * - GitHub release
     - `v2026.05.14 <https://github.com/ThalesGroup/agilab/releases/tag/v2026.05.14>`__
   * - Hosted demo
     - `jpmorard/agilab <https://huggingface.co/spaces/jpmorard/agilab>`__ at Space commit ``9f1dbbdd91ca7dda5416db0ca982017c6d818ca4``
   * - Public guardrails
     - `repo-guardrails run 25864838455 <https://github.com/ThalesGroup/agilab/actions/runs/25864838455>`__ passed repository guardrails and clean package first-proof jobs
   * - Docs source guard
     - `docs-source-guard run 25856345228 <https://github.com/ThalesGroup/agilab/actions/runs/25856345228>`__ passed docs mirror and release-proof consistency checks
   * - Docs publish
     - `docs-publish run 25856345229 <https://github.com/ThalesGroup/agilab/actions/runs/25856345229>`__ built the public documentation from the managed docs mirror
   * - Coverage
     - `coverage run 25864838468 <https://github.com/ThalesGroup/agilab/actions/runs/25864838468>`__ passed component coverage and badge freshness checks
   * - PyPI publish
     - `pypi-publish run 25864840946 <https://github.com/ThalesGroup/agilab/actions/runs/25864840946>`__ passed the public release proof workflow gate

What was proved
---------------

- A clean package install can run the public first proof:

  .. code-block:: bash

     python -m pip install "agilab[examples]==2026.05.14"
     python -m agilab.lab_run first-proof --json --max-seconds 60

- The public GitHub Actions matrix validated the packaged first proof on
  Ubuntu, macOS, and Windows runners.
- The release proof records the hosted Hugging Face Space URL and commit. Live
  public-demo availability is checked only when a public-demo-smoke run is
  pinned or supplied separately.
- The checked-in ``docs/source/data/ui_robot_evidence.json`` records the latest
  successful all-built-in UI robot matrix sweep, including app/page/widget
  counts and zero detected UI failures.
- The public demo scope includes the lightweight ``flight_telemetry_project``
  and ``weather_forecast_project`` routes documented in :doc:`agilab-demo`.
- The release tag, PyPI package, public documentation, and hosted demo point to
  the same public product story: browser preview, local first proof, then
  source-checkout expansion.

How to verify it again
----------------------

Use the package route when you want to prove the released artifact rather than
the current source checkout:

.. code-block:: bash

   python -m venv .venv
   . .venv/bin/activate
   python -m pip install --upgrade pip
   python -m pip install "agilab[examples]==2026.05.14"
   python -m agilab.lab_run first-proof --json --max-seconds 60

Use :doc:`quick-start` when you want the fuller source-checkout path with the
built-in app installation and Streamlit UI.

Maintainer refresh
------------------

Maintainers can refresh the manifest from local release evidence and GitHub
Actions evidence, render the page, and run the same consistency checks with one
command:

.. code-block:: bash

   uv --preview-features extra-build-dependencies run python tools/ui_robot_evidence.py --compact
   uv --preview-features extra-build-dependencies run python tools/release_proof_report.py --refresh-from-local --refresh-from-github --render --check --check-github-runs --compact

Pass ``--github-release-tag``, ``--github-release-url``, ``--hf-space-commit``,
or ``--github-head-sha`` only when public evidence changes outside the default
local repository and latest successful ``main`` workflow state. Use
``tools/ui_robot_evidence.py --run-id <run>`` when the release should pin a
specific UI robot evidence run.

Scope and limits
----------------

This evidence proves the public package smoke, hosted demo identity, and
documented first-proof routes. It proves live hosted-demo availability only
when a public-demo-smoke run is pinned or supplied separately. It does not
certify every remote cluster topology, every GPU stack, private app
repositories, cloud accounts, security posture, or long-running production
operations. Those areas remain environment-dependent and are tracked in
:doc:`compatibility-matrix`.

Related pages
-------------

- :doc:`quick-start`
- :doc:`demos`
- :doc:`agilab-demo`
- :doc:`compatibility-matrix`
- :doc:`agilab-mlops-positioning`
