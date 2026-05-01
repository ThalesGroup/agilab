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
     - ``agilab==2026.05.01.post1`` on `PyPI <https://pypi.org/project/agilab/>`__
   * - GitHub release
     - `v2026.05.01-2 <https://github.com/ThalesGroup/agilab/releases/tag/v2026.05.01-2>`__
   * - Hosted demo
     - `jpmorard/agilab <https://huggingface.co/spaces/jpmorard/agilab>`__ at Space commit ``bd6b51281025f7c7f4ae5e8a7f864165e8f8247e``
   * - Public guardrails
     - `repo-guardrails run 25210998552 <https://github.com/ThalesGroup/agilab/actions/runs/25210998552>`__ passed hosted demo smoke, local-only policy, and clean package install jobs on macOS, Ubuntu, and Windows
   * - CI maintenance confirmation
     - `repo-guardrails run 25211182797 <https://github.com/ThalesGroup/agilab/actions/runs/25211182797>`__ passed after the artifact upload action maintenance update

What was proved
---------------

- A clean package install can run the public first proof:

  .. code-block:: bash

     python -m pip install agilab==2026.05.01.post1
     agilab first-proof --json --max-seconds 60

- The public GitHub Actions matrix validated the packaged first proof on
  Ubuntu, macOS, and Windows runners.
- The hosted Hugging Face Space opened the public AGILAB demo route during the
  release guardrail run.
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
   python -m pip install agilab==2026.05.01.post1
   agilab first-proof --json --max-seconds 60

Use :doc:`quick-start` when you want the fuller source-checkout path with the
built-in app installation and Streamlit UI.

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
