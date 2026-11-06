AGILAB local validation
=======================

Portable validation runs on the current host, with macOS as the usual maintainer
entry point. Use the existing ``./dev`` and ``tools/workflow_parity.py`` commands::

   ./dev --print-only ci
   ./dev ci
   ./dev ci --receipt reports/local-validation/agilab-local-validation.json
   ./dev flow root-tests core-tests

``./dev ci`` checks tracked-source policy, entrypoint syntax, release and app
contracts, skill integrity, lint, fast repository contracts and public docs
source guards. Browsers, native compilation, dependency boundary installs,
coverage and hosted services require explicit profiles. Use ``--no-sync`` only
with an already prepared developer environment. Do not export ``UV_NO_SYNC``
over nested isolated qualification commands.

Opt-in qualification
--------------------

.. list-table::
   :header-rows: 1
   :widths: 30 44 26

   * - Former hosted job or surface
     - Local command
     - Remaining boundary
   * - repo-guardrails / local-only-policy
     - ``./dev ci``; ``./dev flow guardrails-extended``
     - Extended checks need browser, Node and supply-chain tools; APT setup remains Linux-only.
   * - base-python-compat
     - ``./dev flow base-python-compat``
     - Isolated Python 3.12/3.14, Pillow 13 and DuckDB 1.4/2.0 on this host.
   * - clean-public-install
     - ``./dev flow public-install``
     - Exact manifest-pinned PyPI package, installed first-proof and isolated home; other OSes remain separate.
   * - root-test-suite
     - ``./dev flow root-tests setuptools-native``
     - Canonical isolated collection and actual SDK-selected native compilation at setuptools 83.0.0/84.2.1; no skipped compile claim.
   * - windows-core-tests
     - ``./dev flow core-tests`` for current-host tests
     - The Windows manual workflow retains the actual junction-before-target-read test and warning audit.
   * - coverage / agi-env, agi-core, agi-gui, agi-web, aggregate
     - ``./dev flow coverage`` or explicit component profiles
     - Fresh XML, GUI-observed core, source inventories and badge drift; real Python 3.14t and standalone Python 3.12 telemetry remain in GUI coverage.
   * - docs-source-guard
     - ``./dev flow docs-guard``
     - Read-only integrity and proof checks plus their regression tests.
   * - docs-publish build
     - ``./dev docs`` then ``./dev flow docs``
     - Refresh the source stamp, then verify and build Sphinx. Graphviz must already be installed.
   * - ui-robot-matrix
     - ``./dev flow ui-robot-matrix``
     - Planned shards, strict trends, manifests, aggregate coverage and failure-bundle replay on this host.
   * - CI tool locks
     - ``./dev flow ci-tool-lock-integrity``; opt-in ``ci-tool-lock-audit``
     - Locked advisory audit keeps its Linux x86_64 / Python 3.13 contract.
   * - Polars 2 runtime
     - ``./dev flow polars-2-runtime``
     - Explicit isolated same-process evidence on the recorded host.
   * - Public demo smoke
     - ``uv run python tools/hf_space_smoke.py --json``
     - Network/service observation; hosted install/visual robot profiles remain opt-in.
   * - ensure-roadmap-label
     - GitHub-only label administration
     - Run locally with ``gh label create roadmap --force --color 0E8A16 --description 'Roadmap votes and roadmap-planning issues'`` when label maintenance is requested.
   * - pypi-pending-trusted-publisher / pypi-release-retention
     - Existing explicit maintainer workflows and local retention tooling
     - Account configuration and read-only cleanup planning retain their gates.
   * - Release planning, audit, SBOM and preflight
     - Existing ``./dev release`` and supply-chain tools
     - Publication, signing and credentials retain their existing gates.

``./dev badge`` verifies freshness; it does not run coverage. ``./dev flow badges`` regenerates SVGs from XML; it does not run tests. Component percentages
remain bound to their actual source and platform evidence. A Mac run proves
neither Windows junction behaviour nor a full hosted OS/Python matrix.

GitHub exceptions
-----------------

All current and future workflow files permit only explicit manual triggers.
The repository Actions policy remains disabled. ``./dev local`` and the local
pre-push hook inventory every workflow; pre-push verifies nominated commit trees.
Missing, malformed, duplicate and automatic event declarations fail closed.
The coverage badge discloses
``main`` / ``workflow_dispatch`` and its trusted postflight compares the actual
public image with that completed manual run. Run that verifier locally afterward
with ``python tools/coverage_badge_guard.py --check-public-workflow --workflow-run-id <id>``.
There is no automatic postflight Actions chain. It is not the status of local validation.

Pages remains an explicit manual publisher. Generated ``docs/html`` and coverage
outputs are ignored, so a fresh hosted checkout cannot upload a local build.
There is no trusted local-artifact upload channel in this migration. The manual
Pages job therefore still rebuilds only this checkout's public ``docs/source``
before the existing Pages/OIDC deployment, when publication is explicitly requested. No arbitrary URL download, private
documentation import or generated HTML commit is introduced.

PyPI/TestPyPI trusted publishing, GitHub Release and dataset artifacts, artifact
attestations, Hugging Face publication, Actions-token signing qualification and
current-run artifact identity keep their existing service permissions and gates.
This migration does not dispatch workflows, enable Actions, publish a site or
release, or change repository branch protections.

Local evidence
--------------

Real tagged publication requires ``./dev flow coverage --receipt reports/local-validation/agilab-coverage.json``
after release source preparation, including versions, pins, badges and generated
docs. The tagged publisher verifies and reuses that receipt without cleaning or
regenerating covered XML. Other local preflight guards remain enabled, and the
receipt is checked again just before upload. A source or artifact change requires
fresh local qualification; it never dispatches portable coverage implicitly.

Use ``--receipt`` for a fresh execution with the source inventory, input hashes,
verifier hash, Python identity, configuration, terminal results and declared
artifacts. Receipt runs and artifact-producing profiles never reuse result
caches. Plan-only commands cannot write a success receipt::

   ./dev ci --receipt reports/local-validation/agilab-local-validation.json
   uv run python tools/workflow_parity.py --verify-receipt reports/local-validation/agilab-local-validation.json
   uv run python tools/release_proof_report.py --check --check-github-runs --local-validation-receipt reports/local-validation/agilab-local-validation.json

Release proof accepts repeated verified local receipts for portable workflow
checks. Incomplete sets remain missing or failed: repo guardrails also need
extended, compatibility and public-install qualification; coverage needs all
components and badge verification. Pages/publication still use real GitHub
evidence. Historical release evidence remains until its owner refreshes it;
a new local source check is not a new public release.

A receipt hash proves byte identity and detects stale source or artifacts. It
does not authenticate the producer or provide independent attestation. Required
artifacts, executed JUnit cases and current driver dependencies/configuration are
verified; isolated child binary verification limits remain explicit in the receipt. Retain
raw logs and failure diagnostics, and report unrun profiles explicitly.
