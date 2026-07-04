from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


def streamlit_fragment(
    st_module: Any,
    *,
    run_every: str | int | float | None = None,
    parallel: bool = False,
) -> Callable[[F], F]:
    """Return a Streamlit fragment decorator with a safe pre-1.58 fallback.

    Streamlit 1.58 adds ``parallel=True`` to ``st.fragment``. AGILAB can use it
    for independent background-style panels while keeping older 1.57 runtimes
    usable during source or app-template validation.
    """

    fragment = getattr(st_module, "fragment", None)
    if not callable(fragment):
        return lambda func: func

    kwargs: dict[str, Any] = {}
    if run_every is not None:
        kwargs["run_every"] = run_every
    if parallel:
        kwargs["parallel"] = True

    if not kwargs:
        return fragment

    try:
        return fragment(**kwargs)
    except TypeError:
        if "parallel" in kwargs:
            kwargs.pop("parallel", None)
        if not kwargs:
            return fragment
        try:
            return fragment(**kwargs)
        except TypeError:
            return fragment


def render_paginated_dataframe(
    st_module: Any,
    data: Any,
    *,
    key: str,
    page_size: int = 100,
    max_visible_pages: int = 7,
    pagination_width: str = "content",
    show_caption: bool = True,
    **dataframe_kwargs: Any,
) -> Any:
    """Render a dataframe-like object with Streamlit 1.58 pagination when present."""

    total_rows = _row_count(data)
    pagination = getattr(st_module, "pagination", None)
    if (
        total_rows is None
        or total_rows <= max(1, int(page_size))
        or not callable(pagination)
    ):
        return st_module.dataframe(data, **dataframe_kwargs)

    normalized_page_size = max(1, int(page_size))
    page_count = max(1, math.ceil(total_rows / normalized_page_size))
    selected_page = pagination(
        page_count,
        key=f"{key}:pagination",
        max_visible_pages=max_visible_pages,
        width=pagination_width,
    )
    try:
        page_number = int(selected_page)
    except (TypeError, ValueError):
        page_number = 1
    page_number = min(max(page_number, 1), page_count)
    start = (page_number - 1) * normalized_page_size
    stop = min(start + normalized_page_size, total_rows)
    if show_caption:
        st_module.caption(f"Rows {start + 1}-{stop} of {total_rows}")
    return st_module.dataframe(_slice_rows(data, start, stop), **dataframe_kwargs)


def _row_count(data: Any) -> int | None:
    try:
        return int(len(data))
    except (TypeError, ValueError):
        return None


def _slice_rows(data: Any, start: int, stop: int) -> Any:
    iloc = getattr(data, "iloc", None)
    if iloc is not None:
        return iloc[start:stop]
    try:
        return data[start:stop]
    except (KeyError, TypeError):
        return data
