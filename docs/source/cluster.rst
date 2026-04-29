Cluster
=======

Overview
--------

A multi-node cluster is optional. It lets you run AGILab workloads at scale by
spawning workers on remote machines (typically via Dask Distributed).

Principle
---------

- A cluster is a set of machines (nodes) reachable over the network.
- One node acts as the scheduler and others act as workers (Dask terminology).
- AGILab can deploy and run your project on the nodes, but it requires SSH access
  to each machine (a running SSH server on the workers, and an SSH client on the
  machine where you launch AGILab).

Normal AGILAB Workflow
----------------------

Most users should not begin by hand-writing ``AGI.install(...)`` or
``AGI.run(...)`` code for cluster execution.

The normal workflow is:

1. Configure distributed settings in :doc:`execute-help`.
2. Let ORCHESTRATE generate the install, distribution, and run snippets for the
   current cluster definition.
3. Reuse the generated run snippet in :doc:`experiment-help` when you want the
   distributed orchestration to become a Pipeline step.

See :doc:`distributed-workers` for the practical guide.

Repeatable cluster proof
------------------------

Use this after the local :doc:`quick-start` proof works. The goal is a small,
repeatable two-node validation before broader distributed experiments.

The Flight cluster doctor creates tiny synthetic Flight CSVs, mirrors them to
the remote worker under the same ``$HOME/localshare/...`` path, then validates
the cluster-share contract before running compute:

- the scheduler writes a sentinel under ``--cluster-share``
- each remote worker must read it through ``--remote-cluster-share``
- after ``AGI.install`` plus ``AGI.run`` in Dask mode, the scheduler must see
  worker outputs through the local cluster-share path

A remote-only output directory is reported as a failure because it does not
prove a shared cluster filesystem.

Shared storage contract
^^^^^^^^^^^^^^^^^^^^^^^

First mount or otherwise expose the same backing directory on every node. The
scheduler and workers may see that storage at different local paths, but both
paths must point to the same shared filesystem.

Example placeholders:

- scheduler path: ``/path/to/scheduler/clustershare/agilab-two-node``
- worker path: ``/path/to/worker/clustershare/agilab-two-node``
- worker address: ``<worker-user>@<worker-host>``

Discover candidate workers
^^^^^^^^^^^^^^^^^^^^^^^^^^

If you do not know which LAN machines are ready to use, run discovery first:

.. code-block:: bash

   agilab doctor --discover-lan --remote-user <worker-user>

The discovery pass combines passive sources such as ``known_hosts``, SSH config,
the ARP table, and the local AGILAB LAN cache with a bounded SSH-port scan of
local private ``/24`` networks. It does not guess passwords. Each reachable node
is classified by SSH BatchMode auth, operating system, ``python3``, ``uv``,
``sshfs``, and reverse SSH back to the scheduler when ``--scheduler`` is
provided.

Use ``--json`` or ``--summary-json`` when automation needs the machine-readable
report:

.. code-block:: bash

   agilab doctor --discover-lan \
     --remote-user <worker-user> \
     --scheduler <scheduler-host> \
     --cidr <lan-cidr> \
     --json

Use the reported ``ready`` nodes as explicit ``--workers`` values. If discovery
reports ``ssh-auth-needed``, ``python-missing``, ``uv-missing``,
``sshfs-missing``, or ``reverse-ssh-needed``, fix that prerequisite before
running the cluster-share setup.

Set up and check the shared filesystem
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

If the share is not mounted yet, let the doctor apply the SSHFS setup and then
validate the shared filesystem contract:

.. code-block:: bash

   agilab doctor --cluster \
     --scheduler <scheduler-host> \
     --workers <worker-user>@<worker-host> \
     --cluster-share /path/to/scheduler/clustershare/agilab-two-node \
     --remote-cluster-share /path/to/worker/clustershare/agilab-two-node \
     --setup-share sshfs \
     --apply

This creates the local cluster-share directory, checks ``sshfs`` on each remote
worker, writes the remote ``~/.agilab/.env`` ``AGI_CLUSTER_SHARE`` value, mounts
the scheduler path on the worker when not already mounted, and runs the sentinel
share check.

To inspect the commands without applying changes:

.. code-block:: bash

   agilab doctor --cluster \
     --scheduler <scheduler-host> \
     --workers <worker-user>@<worker-host> \
     --cluster-share /path/to/scheduler/clustershare/agilab-two-node \
     --remote-cluster-share /path/to/worker/clustershare/agilab-two-node \
     --print-share-setup sshfs

If you mounted the share manually, validate only the shared filesystem contract:

.. code-block:: bash

   agilab doctor --cluster \
     --scheduler <scheduler-host> \
     --workers <worker-user>@<worker-host> \
     --cluster-share /path/to/scheduler/clustershare/agilab-two-node \
     --remote-cluster-share /path/to/worker/clustershare/agilab-two-node \
     --share-check-only

macOS SSHFS notes
^^^^^^^^^^^^^^^^^

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

Run the cluster proof
^^^^^^^^^^^^^^^^^^^^^

From a source checkout:

.. code-block:: bash

   uv --preview-features extra-build-dependencies run python tools/cluster_flight_validation.py \
     --cluster \
     --scheduler <scheduler-host> \
     --workers <worker-user>@<worker-host> \
     --cluster-share /path/to/scheduler/clustershare/agilab-two-node \
     --remote-cluster-share /path/to/worker/clustershare/agilab-two-node

From an installed package, use the same doctor through the public CLI:

.. code-block:: bash

   agilab doctor --cluster \
     --scheduler <scheduler-host> \
     --workers <worker-user>@<worker-host> \
     --cluster-share /path/to/scheduler/clustershare/agilab-two-node \
     --remote-cluster-share /path/to/worker/clustershare/agilab-two-node

The narrow release gate after any share repair is the standalone
``--share-check-only`` command above. Rerun the full Flight cluster validation
only when you need fresh install, compute, and output-visibility evidence.

For a stricter two-node proof, run with only the remote worker in
``--workers``. The install log should show AGILAB adding
``dask[distributed]`` to the generated ``wenv/<app>_worker`` environment before
launching the remote ``dask worker`` process, and the run log should show the
remote worker executing the Flight batches. The scheduler must then see the
remote outputs through ``--cluster-share``.

SSH key setup
-------------

You typically generate a key pair on the machine running AGILab and copy the
public key to each worker node so the deploy/run steps can connect without
interactive prompts.

.. toctree::
   :maxdepth: 1

   distributed-workers
   key-generation
