Project and packages
====================

- `AGILab on GitHub <https://github.com/ThalesGroup/agilab/>`_

AGILab components
-----------------

The public distribution is split into install surfaces, runtime components,
and payload bundles. ``agilab`` is the product entry point, ``agi-core`` is the
compact Python/runtime API, and the remaining packages are published so
releases can install only the pieces they need. See
:doc:`package-publishing-policy` for the release and versioning contract.

Read the repository and package split as three planes:

* **Control plane**: product entry points, runtime APIs, environment
  resolution, worker packaging, and local/distributed execution.
* **Payload plane**: apps, page bundles, templates, notebooks, examples, and
  PyPI payload umbrellas.
* **Evidence plane**: proof, audits, release contracts, supply-chain evidence,
  UI robot outputs, docs mirror, and agent/runbook automation.

The three planes are released together so users can install a bounded runtime
while maintainers can prove the matching payload and evidence contracts.

.. list-table:: AGILab component packages
   :header-rows: 1
   :widths: 26 42 32
   :class: agilab-components-table

   * - Package
     - Role
     - Typical installer
   * - `agilab on PyPI <https://pypi.org/project/agilab/>`_
     - Product CLI, UI shell, and public extras.
     - ``pip install "agilab[ui]"``
   * - `agi-core on PyPI <https://pypi.org/project/agi-core/>`_
     - Compact Python API and matched runtime stack.
     - ``pip install agi-core``
   * - `agi-env on PyPI <https://pypi.org/project/agi-env/>`_
     - Environment, settings, paths, and artifacts.
     - Pulled by runtime installs.
   * - `agi-node on PyPI <https://pypi.org/project/agi-node/>`_
     - Worker classes, dispatch, and build hooks.
     - Pulled by worker installs.
   * - `agi-cluster on PyPI <https://pypi.org/project/agi-cluster/>`_
     - Local, Dask, SSH, and install/run APIs.
     - Pulled by ``agi-core``.
   * - `agi-gui on PyPI <https://pypi.org/project/agi-gui/>`_
     - Streamlit page and widget helpers.
     - Pulled by ``agilab[ui]``.
   * - `agi-web on PyPI <https://pypi.org/project/agi-web/>`_
     - Portable web component contracts for rich UI islands.
     - Pulled by ``agilab[ui]``.
   * - `agi-pages on PyPI <https://pypi.org/project/agi-pages/>`_
     - Umbrella for public analysis page bundles.
     - Pulled by ``agilab[pages]``.
   * - `agi-apps on PyPI <https://pypi.org/project/agi-apps/>`_
     - Umbrella for public app packages and catalog metadata.
     - Pulled by ``agilab[examples]``.

Per-app packages such as ``agi-app-flight-telemetry`` and page bundles such as
``agi-page-geospatial-map`` are payload packages behind the ``agi-apps`` and ``agi-pages``
umbrellas. They are published separately so app/page payloads can evolve
without forcing every runtime component to carry those assets.
