agi-distributor API
===================

``agi_distributor`` packages applications, ships the required artefacts to the
selected workers, and runs the chosen execution mode across the cluster.

Understanding ``modes_enabled`` and ``mode``
--------------------------------------------

The first thing to know before reading the examples is that AGILAB encodes
execution toggles as a small bitmask.

.. list-table::
   :header-rows: 1
   :widths: 18 18 64

   * - Parameter
     - Used by
     - Meaning
   * - ``modes_enabled``
     - ``AGI.install(...)``
     - Bitmask of the execution capabilities that should be prepared during
       install.
   * - ``mode``
     - ``AGI.run(...)``
     - One concrete execution mode selected for the current run.

The current bit values are:

.. list-table::
   :header-rows: 1
   :widths: 20 14 66

   * - Toggle
     - Bit value
     - Meaning
   * - ``pool``
     - ``1``
     - Multiprocessing / worker-pool path.
   * - ``cython``
     - ``2``
     - Compiled worker path when available.
   * - ``cluster_enabled``
     - ``4``
     - Distributed Dask scheduler / remote worker path.
   * - ``rapids``
     - ``8``
     - RAPIDS / GPU path when supported.

Examples:

- ``13 = 4 + 8 + 1 = cluster + rapids + pool``
- ``15 = 4 + 8 + 2 + 1 = cluster + rapids + cython + pool``

This is why the install examples below use ``modes_enabled=13`` or
``modes_enabled=15``, while the run examples use matching ``mode=13`` or
``mode=15`` values.

In normal usage, these values are generated from the UI toggles rather than
typed manually.

Usage Example
-------------

Installation
^^^^^^^^^^^^

Install the ``mycode`` example:

.. literalinclude:: examples/mycode/AGI.install-mycode.py
   :language: python

Install the ``flight`` example:

.. literalinclude:: examples/flight/AGI.install-flight.py
   :language: python

Distribute
^^^^^^^^^^

Create the distribution bundle that will be sent to the workers:

.. literalinclude:: examples/mycode/AGI.get_distrib-mycode.py
   :language: python

Equivalent example for ``flight``:

.. literalinclude:: examples/flight/AGI.get_distrib-flight.py
   :language: python

Run
^^^

Run the installed project locally or through the configured cluster target:

.. literalinclude:: examples/mycode/AGI.run-mycode.py
   :language: python

Equivalent example for ``flight``:

.. literalinclude:: examples/flight/AGI.run-flight.py
   :language: python

Reference
----------

.. figure:: diagrams/packages_agi_distributor.svg
   :alt: Packages diagram for agi_distributor
   :align: center
   :class: diagram-panel diagram-standard

.. figure:: diagrams/classes_agi_distributor.svg
   :alt: Classes diagram for agi_distributor
   :align: center
   :class: diagram-panel diagram-xl

.. automodule:: agi_cluster.agi_distributor.agi_distributor
   :members:
   :show-inheritance:
