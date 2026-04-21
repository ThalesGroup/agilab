Compatibility Matrix
====================

This page is the first shipped version of an AGILAB compatibility and
certification matrix.

It is intentionally narrow. The goal is to make the currently supported public
paths explicit now, instead of waiting for a larger automation project.

For this page, ``validated`` means the path has an explicit local proof,
regression coverage, or workflow-parity validation in the public AGILAB
repository. It does **not** mean a formal release certification program is in
place yet.

The machine-readable source for this page is:

- :download:`compatibility_matrix.toml <data/compatibility_matrix.toml>`

Current public matrix
---------------------

.. list-table::
   :header-rows: 1
   :widths: 22 12 18 24 24

   * - Slice
     - Status
     - Primary proof
     - Scope
     - Limits
   * - Source checkout first proof
     - validated
     - ``uv run python tools/newcomer_first_proof.py``
     - Public built-in ``flight_project`` path, local execution, and the
       recommended newcomer workflow
     - No SSH, no private apps, no packaged install
   * - Web UI local first proof
     - validated
     - ``uv run streamlit run src/agilab/About_agilab.py``
     - ``PROJECT -> ORCHESTRATE -> ANALYSIS`` on the local built-in app path,
       with fresh output under ``~/log/execute/flight/``
     - Not a remote cluster proof
   * - Hosted AGILAB demo
     - documented
     - :doc:`demos` plus the public hosted demo link
     - Public hosted single-machine web UI demo on the public built-in app path
     - Demo environment only; hosted availability may vary; not a remote cluster proof
   * - Service-mode operator surface
     - validated
     - ORCHESTRATE service controls and health gate
     - Start / status / health / stop operator flow and SLA thresholds
     - Does not certify every remote topology or deployment policy
   * - Notebook quickstart
     - documented
     - ``examples/notebook_quickstart/agi_core_first_run.ipynb``
     - Public notebook-first route for users who intentionally start from
       ``agi-core``
     - Not the recommended first proof path
   * - Published package route
     - documented
     - ``uv pip install agilab`` then ``uv run agilab``
     - Fast packaged install for public evaluation outside the source checkout
     - Less representative of the full source workflow than the built-in first proof

How to use this matrix
----------------------

Use it to answer three concrete questions:

1. Which public path should a newcomer trust first?
2. Which routes are currently validated versus only documented?
3. Which paths still need broader certification or automation work?

Use :doc:`newcomer-guide` and :doc:`quick-start` for the actual onboarding
flow. This page is only the support-status map.

What remains roadmap work
-------------------------

This first matrix closes the small, manual version of the compatibility item.
The larger roadmap work is still open:

- automatic generation from workflow evidence
- promotion from a documented matrix to a workflow-backed compatibility report
- integration with the first-proof wizard so newcomers land on one validated
  path instead of choosing routes too early
- per-release compatibility status
- stronger app/core revision traceability
- explicit certification for more than the public newcomer/operator slices
