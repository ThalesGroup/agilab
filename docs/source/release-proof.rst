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
     - ``agilab[examples]==2026.05.12.post2`` on `PyPI <https://pypi.org/project/agilab/>`__
   * - GitHub release
     - `v2026.05.12-5 <https://github.com/ThalesGroup/agilab/releases/tag/v2026.05.12-5>`__
   * - Hosted demo
     - `jpmorard/agilab <https://huggingface.co/spaces/jpmorard/agilab>`__ at Space commit ``7fc82dee40b39ceb71700a9c07dbbe9cf3c7711e``
   * - Public guardrails
     - `repo-guardrails run 25582096270 <https://github.com/ThalesGroup/agilab/actions/runs/25582096270>`__ passed repository guardrails and clean package first-proof jobs
   * - Docs source guard
     - `docs-source-guard run 25581456410 <https://github.com/ThalesGroup/agilab/actions/runs/25581456410>`__ passed docs mirror and release-proof consistency checks
   * - Docs publish
     - `docs-publish run 25582096237 <https://github.com/ThalesGroup/agilab/actions/runs/25582096237>`__ built the public documentation from the managed docs mirror
   * - Coverage
     - `coverage run 25582096277 <https://github.com/ThalesGroup/agilab/actions/runs/25582096277>`__ passed component coverage and badge freshness checks

What was proved
---------------

- A clean package install can run the public first proof:

  .. code-block:: bash

     python -m pip install "agilab[examples]==2026.05.12.post2"
     python -m agilab.lab_run first-proof --json --max-seconds 60

- The public GitHub Actions matrix validated the packaged first proof on
  Ubuntu, macOS, and Windows runners.
- The hosted Hugging Face Space opened the public AGILAB demo route during the
  release guardrail run.
- The checked-in ``docs/source/data/ui_robot_evidence.json`` records the latest
  successful all-built-in UI robot matrix sweep, including app/page/widget
  counts and zero detected UI failures.
- The public demo scope includes the lightweight ``flight_project`` and
  ``meteo_forecast_project`` routes documented in :doc:`agilab-demo`.
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
   python -m pip install "agilab[examples]==2026.05.12.post2"
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

This evidence proves the public package smoke, hosted demo availability at the
time of validation, and documented first-proof routes. It does not certify
every remote cluster topology, every GPU stack, private app repositories, cloud
accounts, security posture, or long-running production operations. Those areas
remain environment-dependent and are tracked in :doc:`compatibility-matrix`.

Related pages
-------------

- :doc:`quick-start`
- :doc:`demos`
- :doc:`agilab-demo`
- :doc:`compatibility-matrix`
- :doc:`agilab-mlops-positioning`
