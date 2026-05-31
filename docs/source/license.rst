Licenses
========

There are three distinct license scopes to keep in mind when reading this documentation:

- **AGILab source code license**: defined by the repository root ``LICENSE`` and attributions in ``NOTICE``.
- **Vendored third-party assets**: copied source or assets carry attribution under ``LICENSES/`` when required.
- **Python dependency inventories**: the generated pages below list package metadata resolved from the public package split.

The dependency inventories are generated with ``tools/generate_docs_license_inventories.py`` from
``tools/package_split_contract.py`` and the relevant ``pyproject.toml`` files. They are audit aids, not
a substitute for legal review before changing redistribution scope.

Review notes
------------

- AGILAB-owned distributions are normalized to ``BSD-3-Clause`` when external package metadata is incomplete.
- GPL/LGPL/EPL/MPL/CDDL-style strings are surfaced as review flags on the generated pages.
- Runtime and transitive dependencies can appear here even when no source is vendored in this repository.

Vendored third-party assets
---------------------------

The dependency inventories do not replace vendored attribution. Current vendored attribution includes
``LICENSES/LICENSE-MIT-barviz-mod`` for the adapted barycentric visualization code used by
``agi-page-simplex-map``.

Top-level package
-----------------

.. toctree::
   :maxdepth: 1
   :caption: Top-level package

   agilab <agilab-licenses>

Runtime packages
----------------

.. toctree::
   :maxdepth: 1
   :caption: Runtime packages

   agi-env <agi-env-licenses>
   agi-node <agi-node-licenses>
   agi-cluster <agi-cluster-licenses>
   agi-core <agi-core-licenses>

UI and page packages
--------------------

.. toctree::
   :maxdepth: 1
   :caption: UI and page packages

   agi-gui <agi-gui-licenses>
   agi-web <agi-web-licenses>
   agi-page-app-ui <agi-page-app-ui-licenses>
   agi-page-simplex-map <agi-page-simplex-map-licenses>
   agi-page-decision-evidence <agi-page-decision-evidence-licenses>
   agi-page-timeseries-forecast <agi-page-timeseries-forecast-licenses>
   agi-page-inference-report <agi-page-inference-report-licenses>
   agi-page-live-artifacts <agi-page-live-artifacts-licenses>
   agi-page-geospatial-map <agi-page-geospatial-map-licenses>
   agi-page-geospatial-3d <agi-page-geospatial-3d-licenses>
   agi-page-network-map <agi-page-network-map-licenses>
   agi-page-routing-model-comparison <agi-page-routing-model-comparison-licenses>
   agi-page-queue-health <agi-page-queue-health-licenses>
   agi-page-relay-health <agi-page-relay-health-licenses>
   agi-page-scenario-cockpit <agi-page-scenario-cockpit-licenses>
   agi-page-promotion-gate <agi-page-promotion-gate-licenses>
   agi-page-feature-attribution <agi-page-feature-attribution-licenses>
   agi-page-training-report <agi-page-training-report-licenses>
   agi-pages <agi-pages-licenses>

App packages
------------

.. toctree::
   :maxdepth: 1
   :caption: App packages

   agi-app-mission-decision <agi-app-mission-decision-licenses>
   agi-app-pandas-execution <agi-app-pandas-execution-licenses>
   agi-app-polars-execution <agi-app-polars-execution-licenses>
   agi-app-flight-telemetry <agi-app-flight-telemetry-licenses>
   agi-app-multi-dag <agi-app-multi-dag-licenses>
   agi-app-weather-forecast <agi-app-weather-forecast-licenses>
   agi-app-sklearn-pipeline <agi-app-sklearn-pipeline-licenses>
   agi-app-data-quality-gate <agi-app-data-quality-gate-licenses>
   agi-app-pytorch-playground <agi-app-pytorch-playground-licenses>
   agi-app-tescia-diagnostic <agi-app-tescia-diagnostic-licenses>
   agi-app-uav-queue <agi-app-uav-queue-licenses>
   agi-app-uav-relay-queue <agi-app-uav-relay-queue-licenses>
   agi-apps <agi-apps-licenses>
