Newcomer Guide
==============

If you are new to AGILab, optimize for one outcome only: one successful local
run of the built-in ``flight_project`` from the web UI.

This page gives the mental model only. :doc:`quick-start` owns the exact
commands. :doc:`newcomer-troubleshooting` owns the first-failure path.

Fast adoption ladder
--------------------

Use this order when you need the quickest route to confidence:

.. list-table::
   :header-rows: 1

   * - Stage
     - What to do
     - Why it matters
   * - Browser preview
     - Open :doc:`agilab-demo`.
     - Confirms the public UI shape before you install anything.
   * - Local first proof
     - Follow :doc:`quick-start` with the built-in ``flight_project``.
     - Exercises the real source-checkout install, run, and analysis path.
   * - Evidence record
     - Keep ``~/log/execute/flight/run_manifest.json`` from
       ``tools/newcomer_first_proof.py --json``.
     - Gives support, contributors, and future runs the same baseline.
   * - Expansion
     - Move to notebooks, package mode, private apps, or cluster work.
     - Prevents day-1 failures from mixing product, app, and infrastructure
       variables.

Choose one route
----------------

.. list-table::
   :header-rows: 1

   * - Goal
     - Route
     - Use when
   * - See the UI now
     - :doc:`agilab-demo`
     - You want a browser-only look at the AGILAB web UI before installing
       anything.
   * - Prove it locally
     - :doc:`quick-start`
     - You want the real source-checkout path with ``flight_project``. Target:
       pass the first proof in 10 minutes.
   * - Use the API/notebook
     - :doc:`notebook-quickstart`
     - You want the smaller ``AgiEnv`` / ``AGI.run(...)`` surface before the
       full UI.

The first proof is deliberately narrow:
use a source checkout, run the built-in ``flight_project`` locally from the
web UI, and confirm a visible result under ``~/log/execute/flight/``.
The landing page first-proof wizard now enforces that same single actionable
route, reads ``run_manifest.json``, and shows a recovery checklist with exact
evidence commands before you branch out.

That is enough for day 1. Do not widen the problem to notebooks, package mode,
private apps, or cluster setup until this path works once and the manifest gives
you a passing baseline.

This also means PyCharm is not part of the day-1 contract. AGILAB keeps
PyCharm run configurations for developers who want IDE debugging, but the
newcomer route is shell + browser first. The same install, execute, and
analysis path can be driven from commands, the web UI, or checked-in wrappers.

Adoption evidence
-----------------

On April 24, 2026, the source-checkout first-proof smoke passed locally in
``5.86s`` against the ``600s`` target. On April 25, 2026, the same
source-checkout proof passed on a fresh external machine in ``26.87s``:

.. code-block:: bash

   uv --preview-features extra-build-dependencies run python tools/newcomer_first_proof.py --json

The JSON proof writes ``~/log/execute/flight/run_manifest.json``. That manifest
is the portable first-proof run record: command, Python/platform context, active
app, timing, artifact references, and validation status.

That supports an ``Ease of adoption`` score of ``4.0 / 5``: the public demo
works, the first routes are explicit, PyCharm is optional, installer tests are
opt-in, and the source-checkout proof now has local, fresh external macOS,
repeatable Flight cluster doctor, AI Lightning, Hugging Face, bare-metal
cluster, and VM-based cluster validation.
It is not scored higher yet because Azure, AWS, and GCP deployment validation
remains open.

Repeatable cluster proof
------------------------

After the local first proof works, use the Flight cluster doctor for a small
two-node validation. It creates tiny synthetic Flight CSVs, mirrors them to the
remote worker under the same ``$HOME/localshare/...`` path, then validates the
cluster-share contract before running compute: the scheduler writes a sentinel
under ``--cluster-share`` and each remote worker must read it through
``--remote-cluster-share``. After ``AGI.install`` plus ``AGI.run`` in Dask mode,
the scheduler must also see the worker outputs through the local cluster-share
path. A remote-only output directory is reported as a failure because it does not
prove a shared cluster filesystem.

First mount or otherwise expose the same backing directory on every node. For
example, the scheduler might use ``/Users/agi/clustershare/agilab-two-node``
while the worker sees the same storage at
``/Users/jpm/clustershare/agilab-two-node``.

If you do not know which LAN machines are ready to use, run discovery first:

.. code-block:: bash

   agilab doctor --discover-lan --remote-user jpm

The discovery pass combines passive sources such as ``known_hosts``, SSH config,
the ARP table, and the local AGILAB LAN cache with a bounded SSH-port scan of
local private ``/24`` networks. It does not guess passwords. Each reachable node
is classified by SSH BatchMode auth, operating system, ``python3``, ``uv``,
``sshfs``, and reverse SSH back to the scheduler when ``--scheduler`` is
provided. Use ``--json`` or ``--summary-json`` when automation needs the
machine-readable report:

.. code-block:: bash

   agilab doctor --discover-lan \
     --remote-user jpm \
     --scheduler 192.168.3.103 \
     --cidr 192.168.3.0/24 \
     --json

Use the reported ``ready`` nodes as explicit ``--workers`` values. If discovery
reports ``ssh-auth-needed``, ``python-missing``, ``uv-missing``,
``sshfs-missing``, or ``reverse-ssh-needed``, fix that prerequisite before
running the cluster-share setup.

If the share is not mounted yet, let the doctor apply the SSHFS setup and then
validate the shared filesystem contract:

.. code-block:: bash

   agilab doctor --cluster \
     --scheduler 192.168.3.103 \
     --workers jpm@192.168.3.35 \
     --cluster-share /Users/agi/clustershare/agilab-two-node \
     --remote-cluster-share /Users/jpm/clustershare/agilab-two-node \
     --setup-share sshfs \
     --apply

This creates the local cluster-share directory, checks ``sshfs`` on each remote
worker, writes the remote ``~/.agilab/.env`` ``AGI_CLUSTER_SHARE`` value, mounts
the scheduler path on the worker when not already mounted, and runs the sentinel
share check. To inspect the commands without applying changes, print the setup
script:

On macOS workers, make the SSHFS prerequisite explicit before running
``--setup-share``:

- install a FUSE-backed SSHFS implementation such as FUSE-T SSHFS or
  macFUSE plus SSHFS
- ensure ``sshfs`` is visible to non-interactive SSH commands, for example
  ``ssh <worker> 'command -v sshfs'``
- ensure the worker can SSH back to the scheduler user referenced by
  ``--scheduler``, because the worker-side mount command reads
  ``<scheduler-user>@<scheduler>:/...``

On older macOS hosts, Homebrew may exist at ``/usr/local/Homebrew/bin/brew``
without being on the SSH ``PATH``. If ``command -v brew`` is empty, check that
location before assuming no package manager exists. If ``sshfs`` lands under
``/usr/local/bin``, add that directory to the remote user's non-interactive shell
startup, then re-check with ``ssh <worker> 'command -v sshfs'``.

.. code-block:: bash

   agilab doctor --cluster \
     --scheduler 192.168.3.103 \
     --workers jpm@192.168.3.35 \
     --cluster-share /Users/agi/clustershare/agilab-two-node \
     --remote-cluster-share /Users/jpm/clustershare/agilab-two-node \
     --print-share-setup sshfs

If you mounted the share manually, validate only the shared filesystem contract:

.. code-block:: bash

   agilab doctor --cluster \
     --scheduler 192.168.3.103 \
     --workers jpm@192.168.3.35 \
     --cluster-share /Users/agi/clustershare/agilab-two-node \
     --remote-cluster-share /Users/jpm/clustershare/agilab-two-node \
     --share-check-only

From a source checkout:

.. code-block:: bash

   uv --preview-features extra-build-dependencies run python tools/cluster_flight_validation.py \
     --cluster \
     --scheduler 192.168.3.103 \
     --workers jpm@192.168.3.35 \
     --cluster-share /Users/agi/clustershare/agilab-two-node \
     --remote-cluster-share /Users/jpm/clustershare/agilab-two-node

From an installed package, use the same doctor through the public CLI:

.. code-block:: bash

   agilab doctor --cluster \
     --scheduler 192.168.3.103 \
     --workers jpm@192.168.3.35 \
     --cluster-share /Users/agi/clustershare/agilab-two-node \
     --remote-cluster-share /Users/jpm/clustershare/agilab-two-node

This is a post-day-1 proof. It assumes SSH key access already works and that
the remote user can create ``~/localshare`` and access the mounted cluster-share
path. The narrow release gate after any share repair is the standalone
``--share-check-only`` command above; rerun the full Flight cluster validation
only when you need fresh install, compute, and output-visibility evidence.

What to ignore on day 1
-----------------------

Skip these until the local ``flight_project`` proof works once:

- cluster and SSH setup
- published-package mode
- notebook-first route
- private or optional app repositories
- IDE convenience flows
- full installer test suites unless you explicitly want validation instead of
  the fastest first proof

The four words you need
-----------------------

- **PROJECT**: where you choose the app you want to run.
- **ORCHESTRATE**: where you install and execute it.
- **ANALYSIS**: where you look at the result.
- **Worker**: the isolated runtime that actually executes the app.

Common newcomer traps
---------------------

- **Mixing package mode and source mode without being explicit**:
  pick one first, then switch deliberately.
- **Trying cluster mode before a local run succeeds**:
  local success gives you a clean baseline for later SSH debugging.
- **Expecting private or optional apps to appear automatically**:
  public built-in apps live under ``src/agilab/apps/builtin``; extra apps
  usually require ``APPS_REPOSITORY`` / ``AGILAB_APPS_REPOSITORY``.
- **Running ``uvx agilab`` from the source tree**:
  from a repository checkout, use the source commands documented in
  :doc:`quick-start` so you do not accidentally run the published wheel.
- **Assuming PyCharm is required**:
  PyCharm mirrors are useful for debugging, but the supported first proof is
  independent of PyCharm.

Where to go next
----------------

- :doc:`quick-start` for the exact first-proof commands.
- :doc:`newcomer-troubleshooting` if the local ``flight_project`` proof fails.
- :doc:`agilab-demo` if you want the public hosted web UI instead of a local
  install.
- :doc:`demos` if you want the public demo chooser.
- :doc:`notebook-quickstart` only if you intentionally choose the
  ``agi-core`` notebook path.
- :doc:`distributed-workers` only after the local proof works and you are ready
  for SSH or multi-node execution.
