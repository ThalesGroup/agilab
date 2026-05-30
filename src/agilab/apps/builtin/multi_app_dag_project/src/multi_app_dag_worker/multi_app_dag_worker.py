"""No-op worker for the planning-only multi-app DAG project."""

from agi_node.polars_worker.polars_worker import PolarsWorker


class MultiAppDagWorker(PolarsWorker):
    """Worker placeholder so the built-in project follows AGILAB app layout."""

    pass
