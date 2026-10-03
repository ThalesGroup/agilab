# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS

"""Notebook adapter for recorded resilience artifacts."""

from __future__ import annotations

from typing import Any

from agi_pages.queue_resilience import render_queue_resilience_notebook


def render_inline(
    *, page: str, record: dict[str, Any], export_payload: dict[str, Any]
) -> list[Any]:
    import pandas as pd
    from IPython.display import Markdown

    try:
        import plotly.graph_objects as go
    except ImportError:
        go = None
    return render_queue_resilience_notebook(
        page=page,
        record=record,
        export_payload=export_payload,
        pandas=pd,
        markdown=Markdown,
        plotly=go,
    )
