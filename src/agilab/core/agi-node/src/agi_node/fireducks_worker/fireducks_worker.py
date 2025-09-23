# BSD 3-Clause License
#
# [License Text Remains Unchanged]
#
# (Include the full BSD 3-Clause License text here)

"""
Fireducks worker implementation.

The :class:`FireducksWorker` bridges AGILab's worker lifecycle with the
`fireducks` dataframe engine.  It extends :class:`PandasWorker` so that existing
pipelines can progressively adopt FireDucks without rewriting the surrounding
infrastructure.  Results returned from ``work_pool`` or passed to ``work_done``
may be native FireDucks objects, pandas DataFrames, or any object exposing a
``to_pandas``/``to_df`` conversion method.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

try:  # pragma: no cover - optional dependency
    import fireducks  # noqa: F401
    _HAS_FIREDUCKS = True
except ImportError:  # pragma: no cover - optional dependency
    fireducks = None  # type: ignore
    _HAS_FIREDUCKS = False

from agi_node.pandas_worker import PandasWorker

logger = logging.getLogger(__name__)


class FireducksWorker(PandasWorker):
    """Worker harness for FireDucks-backed dataframe workloads."""

    def __init__(self, *args, **kwargs) -> None:  # pragma: no cover - thin wrapper
        if not _HAS_FIREDUCKS:
            logger.warning(
                "fireducks is not installed; FireducksWorker will fall back to pandas operations."
            )
        super().__init__(*args, **kwargs)

    @staticmethod
    def _ensure_pandas(df: Any) -> pd.DataFrame | None:
        """Normalise FireDucks results to a pandas DataFrame."""
        if df is None:
            return None

        # FireDucks objects typically expose ``to_pandas`` or ``to_df``.
        for attr in ("to_pandas", "to_df", "df"):
            if hasattr(df, attr):
                candidate = getattr(df, attr)
                try:
                    if callable(candidate):
                        converted = candidate()
                    else:
                        converted = candidate
                    return FireducksWorker._ensure_pandas(converted)
                except Exception as exc:  # pragma: no cover - defensive guard
                    logger.debug("Failed to convert using %s: %s", attr, exc)

        if isinstance(df, pd.DataFrame):
            return df

        # Fallback: try constructing a DataFrame directly.
        try:
            return pd.DataFrame(df)
        except Exception as exc:  # pragma: no cover - defensive guard
            raise TypeError(
                "FireducksWorker expected a FireDucks or pandas DataFrame compatible object"
            ) from exc

    def work_pool(self, x: Any = None) -> pd.DataFrame:
        """Execute a single task and return a pandas DataFrame."""
        logger.info("fireducks.work_pool")
        result = self._actual_work_pool(x)
        df = self._ensure_pandas(result)
        return df if df is not None else pd.DataFrame()

    def work_done(self, df: Any = None) -> None:
        """Normalise the dataframe before delegating to :class:`PandasWorker`."""
        df_pd = self._ensure_pandas(df)
        super().work_done(df_pd if df_pd is not None else pd.DataFrame())
