Package publishing policy
=========================

AGILAB publishes a small set of Python packages to PyPI so public installs,
notebook examples, worker environments, and release evidence can resolve the
same versioned runtime without relying on a source checkout.

User-facing install surfaces
----------------------------

For public users, the supported entry points are:

- ``agilab``: the top-level CLI package. Add the ``ui`` extra for the local
  Streamlit web interface, or the ``examples`` extra for public built-in apps
  and notebooks.
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

Published app/example asset package
-----------------------------------

``agi-apps`` is published to PyPI as a wheel from
``src/agilab/lib/agi-apps``. The ``agi-apps`` wheel is published to PyPI as a
wheel-only asset. It carries the public ``agilab.apps`` and
``agilab.examples`` payload: built-in projects, the app installer script,
sample data, notebooks, and learning examples. The root ``agilab`` wheel stays
lean; ``agilab[ui]`` and
``agilab[examples]`` pull ``agi-apps`` when the packaged first-proof or demo
assets are needed.

Published page-bundle asset package
-----------------------------------

``agi-pages`` is published to PyPI as a wheel from
``src/agilab/lib/agi-pages``. The ``agi-pages`` wheel is published to PyPI as a
wheel-only asset. It carries the public analysis page bundles that used to be
embedded in the root
``agilab`` wheel under ``apps-pages``. The package exposes
``agi_pages.bundles_root()`` so ``agi-env`` can discover installed page bundles
without making base ``agilab`` depend on them. ``agilab[ui]`` pulls
``agi-pages`` for the local ANALYSIS page; ``agilab[pages]`` installs the page
payload separately when operators want that asset surface without the full UI
profile.

Why keep them published
-----------------------

Publishing these runtime packages keeps the release process reproducible:

- ``pip install agilab`` and ``uvx agilab`` can resolve the exact base package
  graph for CLI and first-proof checks.
- ``pip install "agilab[ui]"`` installs the matching ``agi-gui`` package and
  Streamlit page dependencies for the local web interface, plus ``agi-apps`` and
  ``agi-pages`` so the UI opens with public built-in projects and analysis views
  available.
- ``pip install "agilab[examples]"`` installs ``agi-apps`` plus notebook/demo
  helper dependencies for public packaged examples.
- ``pip install "agilab[pages]"`` installs ``agi-pages`` for analysis page
  bundle discovery without also pulling public built-in apps.
- ``agi-core`` can pin the matching ``agi-env``, ``agi-node``, and
  ``agi-cluster`` versions for a release.
- ``agilab[ui]`` can pin the matching ``agi-gui`` version for the UI/page
  surface without making CLI/core installs depend on Streamlit.
- App worker environments can install the same runtime components in isolation
  from the manager environment.
- CI and release evidence can validate the same dependency graph that external
  users receive from PyPI.

Release rule
------------

For each public release, publish the runtime packages, ``agi-gui``,
``agi-pages``, and ``agi-apps`` with the same version as ``agilab`` and
``agi-core`` unless a
deliberate packaging migration removes that need. Do not skip ``agi-node``,
``agi-cluster``, ``agi-gui``, ``agi-pages``, or ``agi-apps`` from the publish
matrix while ``agi-core`` and the ``agilab[ui]`` / ``agilab[examples]`` /
``agilab[pages]`` extras depend on
them as external packages.

If AGILAB later embeds the ``agi_node`` and ``agi_cluster`` Python modules
directly into a single wheel, that migration must update dependency metadata,
installer tests, notebook examples, and the release preflight before the
standalone runtime packages can be retired from the public publish flow.

Release synchronization contract
--------------------------------

Release automation is intentionally conservative because AGILAB publishes an
umbrella package plus several runtime packages. A public release must have one
planned version and one committed dependency graph before files are uploaded to
real PyPI.

The release commit should synchronize:

- the root ``agilab`` version,
- ``agi-core``, ``agi-env``, ``agi-node``, ``agi-cluster``, ``agi-gui``,
  ``agi-pages``, and ``agi-apps``
  package versions,
- internal runtime dependency pins used by the published wheels,
- built-in app version metadata and lower-bound runtime requirements,
- public README badges, release proof references, and docs mirror stamp when
  they changed.

Real PyPI publication may skip distributions that already exist for the exact
same release graph, but it must not rewrite versions or dependency metadata
during the upload job. If the release needs a different version, choose it
explicitly, regenerate the release commit, rerun preflight, and publish from
that committed state. TestPyPI rehearsals may still use retry-oriented
``.postN`` versions, but those rehearsals are not the source of truth for a
real release.

The required preflight is the place to catch synchronization drift. It should
validate package metadata, internal pins, dependency-policy hygiene, docs mirror
integrity, installer behavior, and release-proof consistency before either the
library packages or the umbrella ``agilab`` wheel are uploaded.

Publishing authentication
-------------------------

Real PyPI publication must use GitHub OIDC Trusted Publishing. Long-lived PyPI
API tokens are not part of the normal release path. If a package or repository
is not configured as a PyPI trusted publisher, the publish workflow should stop
with an explicit configuration error instead of falling back to a stored token.

Each PyPI project must have a GitHub trusted publisher entry matching the
release workflow claims exactly. The workflow renders the same contract with
``tools/pypi_trusted_publisher_contract.py`` before publication and appends the
per-package claim to the GitHub step summary before each upload. A PyPI
``invalid-publisher`` error means the GitHub OIDC token was valid, but the PyPI
project did not have a matching publisher entry or one of the fields differed.

Configure these entries in each PyPI project under
``Settings > Publishing > Trusted publishers > Add GitHub publisher``:

.. list-table::
   :header-rows: 1

   * - PyPI project
     - Owner
     - Repository
     - Workflow
     - Environment
   * - ``agi-env``
     - ``ThalesGroup``
     - ``agilab``
     - ``pypi-publish.yaml``
     - ``pypi-agi-env``
   * - ``agi-gui``
     - ``ThalesGroup``
     - ``agilab``
     - ``pypi-publish.yaml``
     - ``pypi-agi-gui``
   * - ``agi-pages``
     - ``ThalesGroup``
     - ``agilab``
     - ``pypi-publish.yaml``
     - ``pypi-agi-pages``
   * - ``agi-node``
     - ``ThalesGroup``
     - ``agilab``
     - ``pypi-publish.yaml``
     - ``pypi-agi-node``
   * - ``agi-cluster``
     - ``ThalesGroup``
     - ``agilab``
     - ``pypi-publish.yaml``
     - ``pypi-agi-cluster``
   * - ``agi-core``
     - ``ThalesGroup``
     - ``agilab``
     - ``pypi-publish.yaml``
     - ``pypi-agi-core``
   * - ``agi-apps``
     - ``ThalesGroup``
     - ``agilab``
     - ``pypi-publish.yaml``
     - ``pypi-agi-apps``
   * - ``agilab``
     - ``ThalesGroup``
     - ``agilab``
     - ``pypi-publish.yaml``
     - ``pypi-agilab``

The corresponding OIDC subject for each row is
``repo:ThalesGroup/agilab:environment:<environment>``.

The local ``tools/pypi_publish.py`` helper may still build packages and publish
to TestPyPI for rehearsals, but local twine upload to real PyPI is disabled by
default. Real PyPI files should come from ``.github/workflows/pypi-publish.yaml``
so PyPI metadata shows Trusted Publishing/OIDC provenance. Any break-glass local
twine upload requires ``AGILAB_ALLOW_LOCAL_PYPI_TWINE=1`` and a documented
release exception.

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
