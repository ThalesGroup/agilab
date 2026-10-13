Polars 2 runtime qualification
==============================

AGILAB's worker packages accept Polars 2. A green default test suite alone does
not establish which Polars version it imported: application and template
environments can retain a separate ``polars<2`` constraint.

The ``agilab-polars-2-runtime-qualification`` GitHub Actions workflow tests
**Polars 2.0.0 and Pydantic 2.14.0 together** on Ubuntu and Windows, with Python
3.12, 3.13 and 3.14. The six cells are independent and failures remain visible.
The normal core jobs and application dependency bounds remain unchanged.

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

From the source checkout, use an isolated environment with all five editable
packages. This avoids resolving the root application's optional app packages,
which can select a different Polars major version.

.. code-block:: bash

   uv --preview-features extra-build-dependencies run --isolated --no-project \
     --with-editable ./src/agilab/core/agi-env \
     --with-editable ./src/agilab/core/agi-node \
     --with-editable ./src/agilab/core/agi-cluster \
     --with-editable ./src/agilab/core/agi-core \
     --with-editable ./src/agilab/lib/agi-web \
     --with polars==2.0.0 --with pydantic==2.14.0 \
     --with "pytest>=9,<10" --with "pytest-asyncio>=1.3,<2" \
     --with sqlalchemy --with fastparquet \
     python .github/scripts/agilab_polars_2_runtime_qualification.py \
     --source-sha "$(git rev-parse HEAD)" \
     --expected-python 3.13 --expected-platform Linux \
     --output-dir test-results/polars-2-runtime-local

Use the matching Python minor and ``--expected-platform Windows`` on Windows
or ``Darwin`` on macOS. The Windows command can run in Git Bash, as the workflow
does. Choose a new output directory for each run; evidence is never overwritten.
For the hosted matrix, use Actions → ``agilab-polars-2-runtime-qualification``
→ **Run workflow** on the intended commit, or inspect its pull-request run.

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
The reported source SHA must match the checked-out commit. For pull requests,
this is the tested merge commit, which is distinct from the branch head.

Scope of the result
-------------------

A successful six-cell run qualifies these exact dependency versions and focused
tests on the hosted Ubuntu/Windows runners. It does not certify every built-in
or private app under Polars 2, later dependency releases, free-threaded Python,
remote deployment, or performance on a smaller physical machine. Application
and worker environments keep their own declared constraints. The artifact's
source hashes bind the result to the tested source; use current receipts when
making a compatibility claim.
