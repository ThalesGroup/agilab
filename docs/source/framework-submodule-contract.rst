Pinned public framework submodule
=================================

This repository contains private AGILab apps, not the public framework itself.
Those apps depend on the shared AGILab core packages:

- ``agi-env``
- ``agi-node``
- ``agi-cluster``
- ``agi-core``

Decision
--------

The default framework source is the pinned git submodule at::

   .external/agilab

and the default core root is::

   .external/agilab/src/agilab/core

Rationale
---------

The previous local developer workflow often relied on a machine-specific
symlink such as ``core -> ../agilab/src/agilab/core`` or on an implicit sibling
checkout. That was convenient, but it weakened the audit story:

- a fresh clone of ``thales_agilab`` was not enough to reproduce the setup
- local developers, CI, and reviewers could silently use different framework revisions
- the effective framework version was not pinned inside the private repo boundary

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
   uv run streamlit run src/agilab/agilab.py -- --apps-dir "/path/to/thales_agilab/apps"

Consequences
------------

- default local and CI behavior is reproducible
- framework upgrades become explicit submodule updates
- ad-hoc local overrides remain possible, but they are no longer the default
