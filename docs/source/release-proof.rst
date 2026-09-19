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
     - ``agilab[examples]==2026.09.09`` on `PyPI <https://pypi.org/project/agilab/>`__
   * - GitHub release
     - `v2026.09.09-1 <https://github.com/ThalesGroup/agilab/releases/tag/v2026.09.09-1>`__
   * - Dataset release
     - `datasets-535fcc176054e2fb <https://github.com/ThalesGroup/agilab/releases/tag/datasets-535fcc176054e2fb>`__ for ``10`` tracked dataset files; manifest ``535fcc176054e2fb8e39c83d428273ea52c1521eaa2c694c39c3ee5a89df8d93``
   * - Hosted demo
     - `jpmorard/agilab <https://huggingface.co/spaces/jpmorard/agilab>`__ at Space commit ``52abf142970f712a8605f3b0ff48e9b47b323e54``
   * - Public guardrails
     - `repo-guardrails run 34586112200 <https://github.com/ThalesGroup/agilab/actions/runs/34586112200>`__ at commit ``a98b63c77d37`` passed repository guardrails; skipped jobs remain out of scope unless separately evidenced
   * - Docs source guard
     - `docs-source-guard run 34501192329 <https://github.com/ThalesGroup/agilab/actions/runs/34501192329>`__ at commit ``5dd3651b8ed8`` passed docs mirror and release-proof consistency checks; canonical private-source drift is not checked by public CI
   * - Docs publish
     - `docs-publish run 34501192332 <https://github.com/ThalesGroup/agilab/actions/runs/34501192332>`__ at commit ``5dd3651b8ed8`` built the public documentation from the managed docs mirror
   * - Coverage
     - `coverage run 34577976386 <https://github.com/ThalesGroup/agilab/actions/runs/34577976386>`__ at commit ``1dc1002246fa`` passed component coverage and badge freshness checks
   * - PyPI publish
     - `pypi-publish run 34578309790 <https://github.com/ThalesGroup/agilab/actions/runs/34578309790/attempts/1>`__ at commit ``1dc1002246fa`` publication workflow for the recorded release commit; see the linked attempt for its final result

What was proved
---------------

- A clean package install can run the public first proof:

  .. code-block:: bash

     python -m pip install "agilab[examples]==2026.09.09"
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
  this release because its commit is not the release tag commit, even when its
  exact app inventory matches the 14-app release inventory. Use
  ``tools/ui_robot_coverage_contract.py --json`` and the local
  ``ui-robot-matrix`` profile to verify the current checkout. Historical UI
  robot baseline: run ``30646957592``, commit ``adf8c597b5e4``, generated
  ``2026-07-31T17:20:14Z``. It records ``14`` apps while this release expects
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
   python -m pip install "agilab[examples]==2026.09.09"
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
