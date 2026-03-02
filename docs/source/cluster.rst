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

SSH key setup
-------------

You typically generate a key pair on the machine running AGILab and copy the
public key to each worker node so the deploy/run steps can connect without
interactive prompts.

.. toctree::
   :maxdepth: 1

   key-generation
