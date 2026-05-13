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
   distributed orchestration to become a WORKFLOW stage.

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

This shared-filesystem check is only required when at least one configured
worker is remote. For a local-only Dask cluster, for example workers configured
as ``127.0.0.1`` or ``localhost``, the scheduler and workers already see the
same local filesystem. In that case an APFS path such as
``/Users/<user>/clustershare/<name>`` is valid, no SSHFS mount is required, and
ORCHESTRATE should not report the path as a remote-share problem.

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

Windows managers can run discovery when the OpenSSH client is installed; AGILAB
parses Windows ``ipconfig`` and ``arp -a`` output to find local LAN candidates.
Windows remote workers are not covered by this cluster proof yet. Worker
probing, SSHFS setup, and generated install/run commands currently assume a
POSIX shell on Linux or macOS workers.

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

The generated SSHFS mount is intentionally non-interactive and conservative:
it uses ``reconnect``, ``ServerAliveInterval=15``,
``ServerAliveCountMax=3``, ``BatchMode=yes``,
``StrictHostKeyChecking=yes``, and ``noexec``. This means workers must already
trust the scheduler host key in ``known_hosts``; AGILAB will not silently accept
a new host key during deployment. If an existing mount points to another
scheduler source, or if a stale/unwritable SSHFS mount is found, AGILAB tries to
unmount it with ``fusermount3``, ``fusermount``, or ``umount`` before
remounting.

The same contract is used by ORCHESTRATE ``INSTALL``. Keep ``AGI_CLUSTER_SHARE``
as the scheduler-side shared root, keep **Workers Data Path** pointing to the
worker-visible mount target, and let the remote deployment mount the scheduler
share with ``sshfs`` before worker post-install hooks read datasets or write
outputs. Do not clear the cluster-share path just because workers are remote;
fix SSHFS, reverse SSH, or mount permissions instead.

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

SSHFS prerequisites by operating system
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

AGILAB's automatic SSHFS setup runs on each remote worker over SSH. The worker
must therefore provide a POSIX shell, ``sshfs``, a FUSE implementation, reverse
SSH back to the scheduler, and a trusted scheduler host key.

Linux worker
""""""""""""

On Debian or Ubuntu workers:

.. code-block:: bash

   sudo apt-get update
   sudo apt-get install -y sshfs
   command -v sshfs

Then verify reverse SSH from the worker to the scheduler account:

.. code-block:: bash

   scheduler_user="<scheduler-user>"
   scheduler_host="<scheduler-host>"
   ssh -o BatchMode=yes "$scheduler_user@$scheduler_host" hostname

If host-key trust is missing, verify the scheduler fingerprint out of band, then
seed the worker ``known_hosts`` file:

.. code-block:: bash

   scheduler_host="<scheduler-host>"
   mkdir -p ~/.ssh
   chmod 700 ~/.ssh
   ssh-keyscan -H -t ed25519,rsa,ecdsa "$scheduler_host" >> ~/.ssh/known_hosts

For Fedora/RHEL-family workers, install the distribution SSHFS/FUSE package
(``sshfs`` or ``fuse-sshfs`` depending on the release), then rerun the same
``command -v sshfs`` and reverse-SSH checks.

macOS worker
""""""""""""

On macOS workers, make the SSHFS prerequisite explicit before running
``--setup-share``:

- install a FUSE-backed SSHFS implementation such as FUSE-T SSHFS or
  macFUSE plus SSHFS
- ensure ``sshfs`` is visible to non-interactive SSH commands, for example
  ``ssh <worker> 'command -v sshfs'``
- ensure the worker can SSH back to the scheduler user referenced by
  ``--scheduler``, because the worker-side mount command reads
  ``<scheduler-user>@<scheduler>:/...``
- ensure the worker trusts the scheduler host key before running
  ``--setup-share`` or ORCHESTRATE ``INSTALL``. For a new scheduler host, verify
  the fingerprint out of band, then seed ``known_hosts`` on the worker with
  ``ssh-keyscan -H <scheduler-host> >> ~/.ssh/known_hosts``.

On older macOS hosts, Homebrew may exist at ``/usr/local/Homebrew/bin/brew``
without being on the SSH ``PATH``. If ``command -v brew`` is empty, check that
location before assuming no package manager exists. If ``sshfs`` lands under
``/usr/local/bin``, add that directory to the remote user's non-interactive shell
startup, then re-check with ``ssh <worker> 'command -v sshfs'``.

Typical FUSE-T SSHFS setup:

.. code-block:: bash

   HOMEBREW_NO_AUTO_UPDATE=1 brew install macos-fuse-t/homebrew-cask/fuse-t-sshfs
   command -v sshfs

If non-interactive SSH cannot see Homebrew binaries, add the Homebrew binary
directory to the remote user's shell startup:

.. code-block:: bash

   case ":$PATH:" in
     *:/opt/homebrew/bin:*) ;;
     *) export PATH="/opt/homebrew/bin:$PATH" ;;
   esac
   case ":$PATH:" in
     *:/usr/local/bin:*) ;;
     *) export PATH="/usr/local/bin:$PATH" ;;
   esac

Then verify reverse SSH and host-key trust exactly as for Linux workers.

Windows manager or scheduler
""""""""""""""""""""""""""""

Windows can be used as an AGILAB UI/manager or scheduler for a cluster whose
remote workers are Linux/macOS. Install and enable the OpenSSH client, then use
the same AGILAB doctor commands from PowerShell:

.. code-block:: powershell

   Get-WindowsCapability -Online -Name OpenSSH.Client*
   Add-WindowsCapability -Online -Name OpenSSH.Client~~~~0.0.1.0
   ssh -V

Keep the cluster-share setting portable when workers are not Windows:

.. code-block:: powershell

   $env:AGI_CLUSTER_SHARE = "clustershare/agilab-two-node"

Seed SSH host trust from PowerShell when the Windows scheduler must SSH to a
worker:

.. code-block:: powershell

   $workerHost = "<worker-host>"
   New-Item -ItemType Directory -Force "$HOME\.ssh" | Out-Null
   ssh-keyscan -H -t ed25519,rsa,ecdsa $workerHost | Out-File -Append -Encoding ascii "$HOME\.ssh\known_hosts"

Windows as a remote cluster worker is a separate support target and is not
covered by the automatic SSHFS setup today. The generated remote setup commands
expect POSIX tools such as ``mount``, ``sshfs``, ``fusermount3``/``fusermount``,
or ``umount``. If you need a Windows worker, treat it as a manual validation
target first, for example with WinFsp/SSHFS-Win, and do not rely on
``--setup-share sshfs --apply`` until AGILAB has explicit Windows-worker
support.

Cleanup or scheduler switch
^^^^^^^^^^^^^^^^^^^^^^^^^^^

If a worker is moved to another scheduler, or an SSHFS session is left stale
after a crash, unmount the old target on the worker before rerunning setup:

.. code-block:: bash

   ssh <worker-user>@<worker-host> '
     REMOTE_SHARE="$HOME/clustershare/agilab-two-node"
     fusermount3 -u "$REMOTE_SHARE" 2>/dev/null ||
       fusermount -u "$REMOTE_SHARE" 2>/dev/null ||
       umount "$REMOTE_SHARE" 2>/dev/null ||
       true
   '

Then rerun ``agilab doctor --cluster --setup-share sshfs --apply`` or
ORCHESTRATE ``INSTALL``. The automatic installer already attempts this cleanup
for stale, unexpected-source, or unwritable mounts, but doing it manually makes
scheduler switches explicit and easier to audit.

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
