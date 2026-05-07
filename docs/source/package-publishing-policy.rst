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

The following core runtime packages are also published to PyPI:

- ``agi-env``
- ``agi-node``
- ``agi-cluster``

They are runtime building blocks used by ``agi-core``, ``agilab``, app worker
environments, and CI validation. Their publication is intentional, but they are
not promoted as independent user products.

Published UI support package
----------------------------

``agi-gui`` is also published to PyPI from ``src/agilab/lib/agi-gui``. It is
not part of the core runtime: it depends on the headless ``agi-env`` package and
adds the Streamlit/UI dependencies used by AGILAB pages and apps-pages bundles.
Worker environments should keep using ``agi-env`` unless they explicitly need
to render UI.

Why keep them published
-----------------------

Publishing these runtime packages keeps the release process reproducible:

- ``pip install agilab`` and ``uvx agilab`` can resolve the exact package graph.
- ``agi-core`` can pin the matching ``agi-env``, ``agi-node``, and
  ``agi-cluster`` versions for a release.
- ``agilab`` can pin the matching ``agi-gui`` version for the UI/page surface
  without making worker-only installs depend on Streamlit.
- App worker environments can install the same runtime components in isolation
  from the manager environment.
- CI and release evidence can validate the same dependency graph that external
  users receive from PyPI.

Release rule
------------

For each public release, publish the runtime packages and ``agi-gui`` with the
same version as ``agilab`` and ``agi-core`` unless a deliberate packaging
migration removes that need. Do not skip ``agi-node``, ``agi-cluster``, or
``agi-gui`` from the publish matrix while ``agi-core`` and ``agilab`` depend on
them as external packages.

If AGILAB later embeds the ``agi_node`` and ``agi_cluster`` Python modules
directly into a single wheel, that migration must update dependency metadata,
installer tests, notebook examples, and the release preflight before the
standalone runtime packages can be retired from the public publish flow.

Publishing authentication
-------------------------

Real PyPI publication must use GitHub OIDC Trusted Publishing. Long-lived PyPI
API tokens are not part of the normal release path. If a package or repository
is not configured as a PyPI trusted publisher, the publish workflow should stop
with an explicit configuration error instead of falling back to a stored token.

Release evidence should continue to record the bounded nature of the public
proof: package smoke tests, docs, and hosted demos are useful evidence, but they
do not certify private clusters, sensitive-data deployments, or production
operations.

Release cadence and post releases
---------------------------------

AGILAB uses date-based public versions. A normal public release should advance
to a deliberate new version. Real PyPI publication must not silently auto-create
``.postN`` releases when a version collision is detected; the release tool is
expected to stop and require an explicit version choice instead.

``.postN`` releases are acceptable only as corrective packaging releases for an
already published date-based version. They are not the standard delivery
cadence, and multiple same-day post releases should be treated as release
process debt to review, not as a velocity metric. TestPyPI rehearsals are the
exception: retry-oriented ``.postN`` bumps are allowed there because TestPyPI is
often reused during dry runs.

Typing policy
-------------

The root package and core runtime packages set ``disallow_untyped_defs = true``
for project code. The repository also keeps a curated strict slice runnable via
``tools/shared_core_strict_typing.py`` or the ``shared-core-typing`` workflow
profile; that slice includes ``agi-core`` and selected shared support modules
and runs mypy with ``--strict``.

``ignore_missing_imports = true`` is still used at package boundaries to avoid
making third-party stub availability a blocker for runtime development. That
setting should not be read as permission for untyped AGILAB APIs: new public
runtime code should remain typed, and the curated strict slice should expand as
shared APIs stabilize.

Packaging notes
---------------

``setup.py`` is intentionally kept alongside ``pyproject.toml``. It is not a
leftover from an incomplete packaging migration. ``pyproject.toml`` remains the
canonical source for PyPI metadata, dependency resolution, and uv-based
workflows, while ``setup.py`` is the compatibility build entry point used by the
Dask worker distribution path that still emits ``.egg`` artifacts.

Removing ``setup.py`` is valid only after the worker distribution path no
longer depends on egg packaging, and that migration must update the build
helpers, installer tests, distributed execution tests, and release preflight in
the same change.
