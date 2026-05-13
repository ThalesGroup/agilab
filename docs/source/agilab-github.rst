**AGILab project**
------------------

- `AGILab on GitHub <https://github.com/ThalesGroup/agilab/>`_

**AGILab components**
---------------------

The public distribution is split into install surfaces, runtime components,
and payload bundles. ``agilab`` is the product entry point, ``agi-core`` is the
compact Python/runtime API, and the remaining packages are published so
releases can install only the pieces they need. See
:doc:`package-publishing-policy` for the release and versioning contract.

.. list-table::
   :header-rows: 1
   :widths: 22 48 30

   * - Package
     - Role
     - Typical installer
   * - `agilab on PyPI <https://pypi.org/project/agilab/>`_
     - Product package, CLI entry point, Streamlit page shell, and public extras.
     - ``pip install agilab`` or ``pip install "agilab[ui]"``
   * - `agi-core on PyPI <https://pypi.org/project/agi-core/>`_
     - Compact API package that pins the matching runtime stack for notebooks and programmatic runs.
     - ``pip install agi-core``
   * - `agi-env on PyPI <https://pypi.org/project/agi-env/>`_
     - Headless environment, app settings, runtime path, and artifact helpers.
     - Pulled by ``agi-core`` and worker/runtime installs.
   * - `agi-node on PyPI <https://pypi.org/project/agi-node/>`_
     - Worker base classes, dispatcher utilities, build hooks, and packaged runtime helpers.
     - Pulled by ``agi-core`` and app worker environments.
   * - `agi-cluster on PyPI <https://pypi.org/project/agi-cluster/>`_
     - Local/distributed execution, Dask/SSH orchestration, and install/run APIs.
     - Pulled by ``agi-core``.
   * - `agi-gui on PyPI <https://pypi.org/project/agi-gui/>`_
     - Streamlit helper package for UI pages and page widgets.
     - Pulled by ``agilab[ui]``.
   * - `agi-pages on PyPI <https://pypi.org/project/agi-pages/>`_
     - Umbrella for public analysis page bundles and page-bundle discovery helpers.
     - Pulled by ``agilab[ui]`` or ``agilab[pages]``.
   * - `agi-apps on PyPI <https://pypi.org/project/agi-apps/>`_
     - Umbrella for public app packages, app catalog metadata, and example assets.
     - Pulled by ``agilab[ui]`` or ``agilab[examples]``.

Per-app packages such as ``agi-app-flight-project`` and page bundles such as
``view-maps`` are payload packages behind the ``agi-apps`` and ``agi-pages``
umbrellas. They are published separately so app/page payloads can evolve
without forcing every runtime component to carry those assets.
