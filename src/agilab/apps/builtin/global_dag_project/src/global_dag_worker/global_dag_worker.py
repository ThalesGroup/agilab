"""No-op worker for the planning-only global DAG project."""

from agi_node.polars_worker.polars_worker import PolarsWorker


class GlobalDagWorker(PolarsWorker):
    """Worker placeholder so the built-in project follows AGILAB app layout."""

    pass
