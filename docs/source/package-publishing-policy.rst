Package publishing policy
=========================

AGILAB publishes a small set of Python packages to PyPI so public installs,
notebook examples, worker environments, and release evidence can resolve the
same versioned runtime without relying on a source checkout.

User-facing install surfaces
----------------------------

For public users, the supported entry points are:

- ``agilab``: the top-level UI and CLI package.
- ``agi-core``: the compact notebook/API runtime used by the public notebook
  examples.

Documentation, release notes, quick starts, and demos should point users to
those surfaces first.

Internal runtime packages
-------------------------

The following packages are also published to PyPI:

- ``agi-env``
- ``agi-node``
- ``agi-cluster``

They are runtime building blocks used by ``agi-core``, ``agilab``, app worker
environments, and CI validation. Their publication is intentional, but they are
not promoted as independent user products.

Why keep them published
-----------------------

Publishing these runtime packages keeps the release process reproducible:

- ``pip install agilab`` and ``uvx agilab`` can resolve the exact package graph.
- ``agi-core`` can pin the matching ``agi-env``, ``agi-node``, and
  ``agi-cluster`` versions for a release.
- App worker environments can install the same runtime components in isolation
  from the manager environment.
- CI and release evidence can validate the same dependency graph that external
  users receive from PyPI.

Release rule
------------

For each public release, publish the runtime packages with the same version as
``agilab`` and ``agi-core`` unless a deliberate packaging migration removes that
need. Do not skip ``agi-node`` or ``agi-cluster`` from the publish matrix while
``agi-core`` depends on them as external packages.

If AGILAB later embeds the ``agi_node`` and ``agi_cluster`` Python modules
directly into a single wheel, that migration must update dependency metadata,
installer tests, notebook examples, and the release preflight before the
standalone runtime packages can be retired from the public publish flow.
