"""Default worker implementation for the minimal_app project.

This worker simply inherits the PolarsWorker so that projects with minimal
requirements still provide a concrete worker class.  Downstream installers rely
on the class name ``MinimalAppWorker`` to determine the runtime bundle to ship.
"""

from agi_node.polars_worker.polars_worker import PolarsWorker


class MinimalAppWorker(PolarsWorker):
    """Polars worker used by the minimal_app sample application."""

    pass
