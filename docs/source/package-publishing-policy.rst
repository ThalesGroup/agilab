Package publishing policy
=========================

AGILAB publishes a coordinated set of Python packages to PyPI so public
installs, notebook examples, worker environments, and release evidence can
resolve the same versioned runtime without relying on a source checkout.

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
adds the Streamlit/UI dependencies used by AGILAB pages and page bundles.
Worker environments should keep using ``agi-env`` unless they explicitly need
to render UI.

Archived page-bundle packages
-----------------------------

The public analysis pages are built as self-contained page-bundle package
artifacts. Each package carries one generic analysis page bundle and is
uploaded to the GitHub Release distribution archive until its PyPI Trusted
Publisher entry is configured:

- ``view-barycentric-graph``
- ``view-data-io-decision``
- ``view-forecast-analysis``
- ``view-inference-analysis``
- ``view-maps``
- ``view-maps-3d``
- ``view-maps-network``
- ``view-queue-resilience``
- ``view-relay-resilience``
- ``view-release-decision``
- ``view-shap-explanation``
- ``view-training-analysis``

These packages are built as both wheels and source distributions. Their names
stay app-agnostic because page bundles must be reusable by AGILAB apps and
exported notebooks.

Published page-bundle umbrella package
--------------------------------------

``agi-pages`` is published to PyPI from ``src/agilab/lib/agi-pages`` as both a
wheel and source distribution. It is an umbrella/provider package for page
bundle discovery and exposes ``agi_pages.bundles_root()`` plus
bundle-resolution helpers so ``agi-env`` and exported notebooks can discover
installed page bundles without making base ``agilab`` depend on them.
``agilab[ui]`` pulls ``agi-pages`` for the local ANALYSIS page;
``agilab[pages]`` installs the page provider without the full UI profile.

Archived app project packages
-----------------------------

The public built-in app projects are built as self-contained app project
package artifacts. Each package carries one project payload and exposes it
through the ``agilab.apps`` entry point group so ``agi-env`` can resolve
installed apps without the monorepo checkout once that package is installed:

- ``agi-app-data-io-2026-project``
- ``agi-app-execution-pandas-project``
- ``agi-app-execution-polars-project``
- ``agi-app-flight-project``
- ``agi-app-global-dag-project``
- ``agi-app-meteo-forecast-project``
- ``agi-app-mycode-project``
- ``agi-app-tescia-diagnostic-project``
- ``agi-app-uav-queue-project``
- ``agi-app-uav-relay-queue-project``

These packages are built as both wheels and source distributions and uploaded
to the GitHub Release distribution archive until their PyPI Trusted Publisher
entries are configured. The payload is staged during package build, with local
virtual environments, compiled artifacts, locks, and generated build outputs
excluded.

Published app/example umbrella package
--------------------------------------

``agi-apps`` is published to PyPI from ``src/agilab/lib/agi-apps`` as both a
wheel and source distribution. It is an umbrella/catalog package: it keeps the
lightweight ``agilab.apps.install`` helper and ``agilab.examples`` learning
assets while the per-app payload packages remain independently versioned
release artifacts. The root ``agilab`` wheel stays lean; ``agilab[ui]`` and
``agilab[examples]`` pull ``agi-apps`` when the packaged first-proof or demo
assets are needed.

Why keep them published
-----------------------

Publishing these runtime packages keeps the release process reproducible:

- ``pip install agilab`` and ``uvx agilab`` can resolve the exact base package
  graph for CLI and first-proof checks.
- ``pip install "agilab[ui]"`` installs the matching ``agi-gui`` package and
  Streamlit page dependencies for the local web interface, plus ``agi-apps``,
  its per-app project dependencies, and ``agi-pages`` so the UI opens with
  public built-in projects and analysis views available.
- ``pip install "agilab[examples]"`` installs ``agi-apps`` and its per-app
  project dependencies plus notebook/demo helper dependencies for public
  packaged examples.
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

For each public release, publish only the packages whose own payload or curated
dependency graph changed. AGILAB uses independent version tracks:

- runtime components such as ``agi-env``, ``agi-node``, ``agi-cluster``, and
  ``agi-gui`` version the implementation they carry;
- bundle packages such as ``agi-core``, ``agi-pages``, ``agi-apps``, and the
  root ``agilab`` version the curated dependency graph they expose;
- payload packages such as ``view-*`` and ``agi-app-*-project`` version the
  page or app payload they carry and are archived with release artifacts until
  their PyPI publishers are configured.

Bundle packages should exact-pin the component versions they curate for
reproducible installs. Payload packages should declare compatible AGILAB runtime
ranges instead of exact-pinning every AGILAB release, so a runtime patch does
not force republishing unchanged pages or apps. Do not skip ``agi-node``,
``agi-cluster``, ``agi-gui``, ``agi-pages``, ``agi-apps``, or the root
``agilab`` package from the PyPI publish matrix when their own version or
dependency graph changed. Keep page-bundle and app-project payload packages in
the release artifact matrix even when their PyPI upload flag is disabled.

If AGILAB later embeds the ``agi_node`` and ``agi_cluster`` Python modules
directly into a single wheel, that migration must update dependency metadata,
installer tests, notebook examples, and the release preflight before the
standalone runtime packages can be retired from the public publish flow.

Release synchronization contract
--------------------------------

Release automation is intentionally conservative because AGILAB publishes
components, bundles, and payload packages. A public release may have several
package versions, but it must have one committed dependency graph before files
are uploaded to real PyPI.

The release commit should synchronize:

- the root ``agilab`` version when the top-level bundle changes,
- each changed component, bundle, page payload, or app payload package version,
- exact internal dependency pins used by bundle packages,
- compatible runtime lower bounds used by page/app payload packages,
- built-in app payload metadata and runtime requirements,
- public README badges, release proof references, and docs mirror stamp when
  they changed.

Real PyPI publication may skip distributions that already exist for the same
package version, but it must not rewrite versions or dependency metadata during
the upload job. If a package needs a different version, choose it explicitly,
regenerate the release commit, rerun preflight, and publish from that committed
state. TestPyPI rehearsals may still use retry-oriented ``.postN`` versions,
but those rehearsals are not the source of truth for a real release.

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

Each PyPI project selected for upload must have a GitHub trusted publisher entry
matching the release workflow claims exactly. The workflow renders the same contract with
``tools/pypi_trusted_publisher_contract.py`` before publication and appends the
per-package claim to the GitHub step summary before each upload. A PyPI
``invalid-publisher`` error means the GitHub OIDC token was valid, but the PyPI
project did not have a matching publisher entry or one of the fields differed.

Configure these entries in each PyPI project under
``Settings > Publishing > Trusted publishers > Add GitHub publisher``. Entries
for archived payload packages are activation targets for future PyPI uploads;
the current PyPI release path only requests OIDC tokens for packages marked
``publish_to_pypi=true`` in ``tools/release_plan.py``:

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
   * - ``view-barycentric-graph``
     - ``ThalesGroup``
     - ``agilab``
     - ``pypi-publish.yaml``
     - ``pypi-view-barycentric-graph``
   * - ``view-data-io-decision``
     - ``ThalesGroup``
     - ``agilab``
     - ``pypi-publish.yaml``
     - ``pypi-view-data-io-decision``
   * - ``view-forecast-analysis``
     - ``ThalesGroup``
     - ``agilab``
     - ``pypi-publish.yaml``
     - ``pypi-view-forecast-analysis``
   * - ``view-inference-analysis``
     - ``ThalesGroup``
     - ``agilab``
     - ``pypi-publish.yaml``
     - ``pypi-view-inference-analysis``
   * - ``view-maps``
     - ``ThalesGroup``
     - ``agilab``
     - ``pypi-publish.yaml``
     - ``pypi-view-maps``
   * - ``view-maps-3d``
     - ``ThalesGroup``
     - ``agilab``
     - ``pypi-publish.yaml``
     - ``pypi-view-maps-3d``
   * - ``view-maps-network``
     - ``ThalesGroup``
     - ``agilab``
     - ``pypi-publish.yaml``
     - ``pypi-view-maps-network``
   * - ``view-queue-resilience``
     - ``ThalesGroup``
     - ``agilab``
     - ``pypi-publish.yaml``
     - ``pypi-view-queue-resilience``
   * - ``view-relay-resilience``
     - ``ThalesGroup``
     - ``agilab``
     - ``pypi-publish.yaml``
     - ``pypi-view-relay-resilience``
   * - ``view-release-decision``
     - ``ThalesGroup``
     - ``agilab``
     - ``pypi-publish.yaml``
     - ``pypi-view-release-decision``
   * - ``view-shap-explanation``
     - ``ThalesGroup``
     - ``agilab``
     - ``pypi-publish.yaml``
     - ``pypi-view-shap-explanation``
   * - ``view-training-analysis``
     - ``ThalesGroup``
     - ``agilab``
     - ``pypi-publish.yaml``
     - ``pypi-view-training-analysis``
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
   * - ``agi-app-data-io-2026-project``
     - ``ThalesGroup``
     - ``agilab``
     - ``pypi-publish.yaml``
     - ``pypi-agi-app-data-io-2026-project``
   * - ``agi-app-execution-pandas-project``
     - ``ThalesGroup``
     - ``agilab``
     - ``pypi-publish.yaml``
     - ``pypi-agi-app-execution-pandas-project``
   * - ``agi-app-execution-polars-project``
     - ``ThalesGroup``
     - ``agilab``
     - ``pypi-publish.yaml``
     - ``pypi-agi-app-execution-polars-project``
   * - ``agi-app-flight-project``
     - ``ThalesGroup``
     - ``agilab``
     - ``pypi-publish.yaml``
     - ``pypi-agi-app-flight-project``
   * - ``agi-app-global-dag-project``
     - ``ThalesGroup``
     - ``agilab``
     - ``pypi-publish.yaml``
     - ``pypi-agi-app-global-dag-project``
   * - ``agi-app-meteo-forecast-project``
     - ``ThalesGroup``
     - ``agilab``
     - ``pypi-publish.yaml``
     - ``pypi-agi-app-meteo-forecast-project``
   * - ``agi-app-mycode-project``
     - ``ThalesGroup``
     - ``agilab``
     - ``pypi-publish.yaml``
     - ``pypi-agi-app-mycode-project``
   * - ``agi-app-tescia-diagnostic-project``
     - ``ThalesGroup``
     - ``agilab``
     - ``pypi-publish.yaml``
     - ``pypi-agi-app-tescia-diagnostic-project``
   * - ``agi-app-uav-queue-project``
     - ``ThalesGroup``
     - ``agilab``
     - ``pypi-publish.yaml``
     - ``pypi-agi-app-uav-queue-project``
   * - ``agi-app-uav-relay-queue-project``
     - ``ThalesGroup``
     - ``agilab``
     - ``pypi-publish.yaml``
     - ``pypi-agi-app-uav-relay-queue-project``
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

GitHub deployment environments
------------------------------

The real PyPI workflow uses one GitHub deployment environment per PyPI project
so Trusted Publishing receives a project-specific OIDC claim:

- ``pypi-agi-env``
- ``pypi-agi-node``
- ``pypi-agi-cluster``
- ``pypi-agi-core``
- ``pypi-agi-gui``
- ``pypi-view-barycentric-graph``
- ``pypi-view-data-io-decision``
- ``pypi-view-forecast-analysis``
- ``pypi-view-inference-analysis``
- ``pypi-view-maps``
- ``pypi-view-maps-3d``
- ``pypi-view-maps-network``
- ``pypi-view-queue-resilience``
- ``pypi-view-relay-resilience``
- ``pypi-view-release-decision``
- ``pypi-view-shap-explanation``
- ``pypi-view-training-analysis``
- ``pypi-agi-pages``
- ``pypi-agi-app-data-io-2026-project``
- ``pypi-agi-app-execution-pandas-project``
- ``pypi-agi-app-execution-polars-project``
- ``pypi-agi-app-flight-project``
- ``pypi-agi-app-global-dag-project``
- ``pypi-agi-app-meteo-forecast-project``
- ``pypi-agi-app-mycode-project``
- ``pypi-agi-app-tescia-diagnostic-project``
- ``pypi-agi-app-uav-queue-project``
- ``pypi-agi-app-uav-relay-queue-project``
- ``pypi-agi-apps``
- ``pypi-agilab``

The old bare ``pypi`` environment belongs to the retired single-package
publisher and must not be recreated or referenced by workflows. If GitHub's
repository landing page shows ``pypi inactive`` in the Deployments widget, it is
stale deployment history, not a current AGILAB component. Maintainers should
delete only the retired ``pypi`` deployment records/environment and keep the
package-specific environments above.

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
