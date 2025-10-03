"""Default worker implementation for the mycode project.

This worker simply inherits the PolarsWorker so that projects with minimal
requirements still provide a concrete worker class.  Downstream installers rely
on the class name ``MycodeWorker`` to determine the runtime bundle to ship.
"""

from agi_node.polars_worker.polars_worker import PolarsWorker


class MycodeWorker(PolarsWorker):
    """Polars worker used by the mycode sample application."""

    pass
