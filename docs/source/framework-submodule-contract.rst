Pinned public framework submodule
=================================

This page is a contributor/reference note for repositories that pin the public
AGILab framework as a Git submodule instead of relying on an implicit local
checkout.

Those repositories depend on the shared AGILab core packages:

- ``agi-env``
- ``agi-node``
- ``agi-cluster``
- ``agi-core``

Recommended default
-------------------

Use the pinned Git submodule at::

   .external/agilab

and the default core root is::

   .external/agilab/src/agilab/core

Why this is the default
-----------------------

Older local workflows often relied on a machine-specific symlink or on an
implicit sibling checkout. That was convenient, but it made the effective
framework revision less explicit:

- a fresh clone was not always enough to reproduce the setup
- local developers, CI, and reviewers could silently use different framework revisions
- the effective framework version was not pinned inside the repository boundary

The pinned submodule fixes that by making the framework revision explicit in Git
history and by giving CI, developers, and auditors the same default source.

Supported resolution order
--------------------------

``tools/run_app_tests.py`` resolves the shared core in this order:

1. ``--core-root`` explicit override
2. ``.external/agilab/src/agilab/core`` pinned submodule
3. ``AGILAB_CORE_ROOT`` environment override
4. ``../agilab/src/agilab/core`` legacy sibling checkout

Local workflow
--------------

Initialise the submodule after cloning::

   git submodule update --init --recursive

Then launch the framework from the pinned checkout::

   cd .external/agilab
   uv run streamlit run src/agilab/agilab.py -- --apps-dir "/path/to/private-apps-repo/apps"

Consequences
------------

- default local and CI behavior is reproducible
- framework upgrades become explicit submodule updates
- ad-hoc local overrides remain possible, but they are no longer the default
