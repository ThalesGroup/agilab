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
     - ``agilab[examples]==2026.07.31`` on `PyPI <https://pypi.org/project/agilab/>`__
   * - GitHub release
     - `v2026.07.31 <https://github.com/ThalesGroup/agilab/releases/tag/v2026.07.31>`__
   * - Dataset release
     - `datasets-f3c9b30733ce0232 <https://github.com/ThalesGroup/agilab/releases/tag/datasets-f3c9b30733ce0232>`__ for ``12`` tracked dataset files; manifest ``f3c9b30733ce02322da542deae8ae6edb70082f537764570816413b321a4cd8f``
   * - Hosted demo
     - `jpmorard/agilab <https://huggingface.co/spaces/jpmorard/agilab>`__ at Space commit ``85f28330cd50f810f0e229816e45c7ee5b1bffae``
   * - Public guardrails
     - `repo-guardrails run 30618909264 <https://github.com/ThalesGroup/agilab/actions/runs/30618909264>`__ at commit ``bae393fe6aef`` passed repository guardrails; skipped jobs remain out of scope unless separately evidenced
   * - Docs source guard
     - `docs-source-guard run 30618909234 <https://github.com/ThalesGroup/agilab/actions/runs/30618909234>`__ at commit ``bae393fe6aef`` passed docs mirror and release-proof consistency checks; canonical private-source drift is not checked by public CI
   * - Docs publish
     - `docs-publish run 30619166574 <https://github.com/ThalesGroup/agilab/actions/runs/30619166574>`__ at commit ``81797b8193f6`` built the public documentation from the managed docs mirror
   * - Coverage
     - `coverage run 30618909177 <https://github.com/ThalesGroup/agilab/actions/runs/30618909177>`__ at commit ``bae393fe6aef`` passed component coverage and badge freshness checks
   * - PyPI publish
     - `pypi-publish run 30616241713 <https://github.com/ThalesGroup/agilab/actions/runs/30616241713>`__ at commit ``3e88def4dda5`` tested and published the release artifacts from the recorded release commit

What was proved
---------------

- A clean package install can run the public first proof:

  .. code-block:: bash

     python -m pip install "agilab[examples]==2026.07.31"
     python -m agilab.lab_run first-proof --json --max-seconds 60

- The pinned GitHub Actions rows record successful repository, documentation,
  coverage, and release-publication workflows at their exact commits. A
  successful workflow is not presented as proof for jobs that the workflow
  skipped.
- The release proof records the hosted Hugging Face Space URL and commit. Live
  public-demo availability is checked only when a public-demo-smoke run is
  pinned or supplied separately.
- The checked-in ``docs/source/data/ui_robot_evidence.json`` records a
  successful historical UI robot baseline. It is not release-bound UI proof for
  this release because its commit and 10-app inventory predate the 14-app
  release inventory. Use ``tools/ui_robot_coverage_contract.py --json`` and the
  local ``ui-robot-matrix`` profile to verify the current checkout. Historical
  UI robot baseline: run ``25577485125``, commit ``2a36df530b48``, generated
  ``2026-05-08T20:34:30Z``. It records ``10`` apps while this release expects
  ``14``; it is not UI proof for this release.
- The public demo scope includes the lightweight ``flight_telemetry_project``
  and ``weather_forecast_project`` routes documented in :doc:`agilab-demo` and
  aligned with the packaged examples catalog.
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
   python -m pip install "agilab[examples]==2026.07.31"
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
local repository and latest successful ``main`` workflow state. Set
``ui_robot.mode = "release"`` only when the evidence head commit and app count
match the represented release; otherwise keep the artifact labeled as a
historical baseline.

Scope and limits
----------------

This evidence proves the public package smoke, hosted demo identity, and
documented first-proof routes. It proves live hosted-demo availability only
when a public-demo-smoke run is pinned or supplied separately. The checked-in
UI robot artifact is a historical baseline and does not prove the current
release UI matrix. This page does not certify every remote cluster topology,
every GPU stack, private app repositories, cloud accounts, security posture, or
long-running production operations. Those areas remain environment-dependent
and are tracked in :doc:`compatibility-matrix`.

Related pages
-------------

- :doc:`quick-start`
- :doc:`demos`
- :doc:`agilab-demo`
- :doc:`compatibility-matrix`
- :doc:`agilab-mlops-positioning`
