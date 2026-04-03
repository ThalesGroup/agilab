agi-distributor API
===================

``agi_distributor`` packages applications, ships the required artefacts to the
selected workers, and runs the chosen execution mode across the cluster.

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
