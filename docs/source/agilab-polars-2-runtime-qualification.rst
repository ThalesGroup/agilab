Polars 2 runtime qualification
==============================

AGILAB's worker packages accept Polars 2. A green default test suite alone does
not establish which Polars version it imported: application and template
environments can retain a separate ``polars<2`` constraint.

Start with local validation. The opt-in ``polars-2-runtime`` parity profile
tests **Polars 2.0.0 and Pydantic 2.14.0 together** on the current host and Python.
For runner-specific checks, the ``agilab-polars-2-runtime-qualification``
GitHub Actions workflow is manual-only (``workflow_dispatch``). Its six independent
cells cover Ubuntu and Windows with Python 3.12, 3.13 and 3.14. Pull requests and
pushes do not launch this matrix. Normal core jobs, application dependency bounds
and required branch checks retain their existing contracts.

What is exercised
-----------------

The fixed suite combines Polars worker input/output and execution-state tests,
capacity and distribution cleanup boundaries, the dynamic worker import guard,
and argument validation and native web form normalization. It runs eight
existing test modules; each receipt records the actual collected and passed
counts per source file. A cell fails if it skips or deselects tests, omits one
of the eight modules, collects nothing, returns a failure,
or cannot produce matching JUnit evidence.

The SDK continues to load application workers dynamically. The qualification
helper observes SDK modules already loaded by these tests and records their
source paths and hashes; it does not bind or import an application worker class.

Run one cell locally
--------------------

From the source checkout, use the existing local workflow entrypoint:

.. code-block:: bash

   ./dev flow polars-2-runtime

The profile uses the current interpreter's Python minor and operating system,
all five editable SDK packages, and the exact dependency versions below.
Each invocation defaults to a fresh
``test-results/polars-2-runtime-local-<unique-id>`` directory. Pass
``--polars-output-dir <fresh-directory>`` to choose an explicit destination.
The helper refuses to overwrite existing evidence, including an explicitly
selected directory. This artifact-producing profile always executes,
including when ``--result-cache`` is supplied. The default parity profile set excludes it, and ``./dev flow`` requires an
explicit profile before starting work.

The equivalent direct command makes the host expectations explicit. The example
below targets Linux/Python 3.13; change the Python and platform values together
for the host being tested. The isolated environment avoids resolving the root
application's optional app packages, which can select a different Polars major.

.. code-block:: bash

   uv --preview-features extra-build-dependencies run --isolated --no-project \
     --python 3.13 \
     --with-editable ./src/agilab/core/agi-env \
     --with-editable ./src/agilab/core/agi-node \
     --with-editable ./src/agilab/core/agi-cluster \
     --with-editable ./src/agilab/core/agi-core \
     --with-editable ./src/agilab/lib/agi-web \
     --with polars==2.0.0 --with pydantic==2.14.0 \
     --with "pytest==9.1.1" --with "pytest-asyncio>=1.3,<2" \
     --with sqlalchemy --with fastparquet \
     python tools/testing/agilab_polars_2_runtime_qualification.py \
     --source-sha "$(git rev-parse HEAD)" \
     --expected-python 3.13 --expected-platform Linux \
     --output-dir test-results/polars-2-runtime-local

Set both ``--python`` and ``--expected-python`` to the matching minor, and use ``--expected-platform Windows`` on Windows
or ``Darwin`` on macOS. The Windows command can run in Git Bash, as the workflow
does. Choose a new output directory for each run; evidence is never overwritten.
For the hosted matrix, use Actions → ``agilab-polars-2-runtime-qualification``
→ **Run workflow** on the intended commit. This workflow requires an explicit manual dispatch.

Read the evidence
-----------------

Each artifact is named for its operating system, Python minor and run attempt.
It contains:

* ``agilab-polars-2-runtime-qualification.json``: source commit, hashes, actual
  Python/platform, imported dependency versions and files before pytest, during
  its session-finish hook, and after cleanup; observed SDK sources, outcomes
  and artifact checksums.
* ``agilab-polars-2-runtime-qualification.xml``: JUnit test outcomes.
* ``agilab-polars-2-runtime-qualification.log``: pytest output.

The helper clears inherited pytest selection and plugin variables, then checks
module and distribution versions in the process that runs the tests. Dependency paths use ``$DISTRIBUTION_ROOT`` and SDK paths are relative to
the checkout; arbitrary environment values and credentials are excluded.
The reported source SHA must match the checked-out commit. A direct local call
may omit ``--source-sha`` to record the actual local HEAD. The hosted workflow
passes its exact tested commit explicitly. Source hashes also bind the moved
local helper and the parity profile that declares its dependencies.

Scope of the result
-------------------

A successful six-cell run qualifies these exact dependency versions and focused
tests on the hosted Ubuntu/Windows runners. It does not certify every built-in
or private app under Polars 2, later dependency releases, free-threaded Python,
remote deployment, or performance on a smaller physical machine. Application
and worker environments keep their own declared constraints. The artifact's
source hashes bind the result to the tested source; Windows checkout hashes
may differ only by a verified LF-to-CRLF conversion from the committed Git
blobs. Use current receipts when making a compatibility claim.


Related locked-tool checks
--------------------------

CI release-tool lock files can be checked locally without installing their
packages:

.. code-block:: bash

   ./dev flow ci-tool-lock-integrity

This portable check reuses ``tools/ci_tool_lock_integrity.py``. The separate
``ci-tool-lock-audit`` profile explicitly opts in to a fresh installation of the
hash-locked auditor and a live advisory lookup. Each lock is audited separately
in the same private auditor environment, so differing pins remain independent.
These locks target Linux x86_64
and Python 3.13; that profile refuses other hosts before installation. A portable
integrity pass on macOS is not Linux installation or runtime qualification.

.. code-block:: bash

   ./dev flow ci-tool-lock-audit

Both profiles are opt-in; profileless flow does not add these installs.
The live audit always bypasses result caching. The manual-only
``ci-tool-lock-integrity`` workflow retains the Linux clean-install and import
smokes for every release-tool lock.

Release workflows invoke ``tools/setup_locked_python_tools.py`` after pinned
uv 0.10.7 setup and before credential-bearing steps. The installer validates an
exact repository-relative ``.github/requirements/ci-*.txt`` path, rejects
redirected files, creates a fresh environment, and installs with
``--require-hashes --no-build --no-cache``. Workflow environment exports are
written only after installation succeeds. Neither manual qualification workflow
is a required branch check; release approvals, signatures and required checks
remain in force.
