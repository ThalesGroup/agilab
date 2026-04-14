from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from agi_env import pagelib_preview_support as preview_support


def test_resolve_preview_nrows_prefers_explicit_then_session_and_treats_zero_as_none():
    assert preview_support.resolve_preview_nrows(None, "7") == 7
    assert preview_support.resolve_preview_nrows(3, "7") == 3
    assert preview_support.resolve_preview_nrows(0, "7") is None
    assert preview_support.resolve_preview_nrows(None, 0) is None
    assert preview_support.resolve_preview_nrows(None, "bad") is None


def test_build_dataframe_preview_returns_caption_only_when_truncated():
    df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6], "c": [7, 8, 9]})

    preview, caption = preview_support.build_dataframe_preview(
        df,
        max_rows=2,
        max_cols=2,
        truncation_label="Preview cut",
    )

    assert list(preview.columns) == ["a", "b"]
    assert len(preview) == 2
    assert caption == "Preview cut: showing first 2 of 3 rows, showing first 2 of 3 columns."

    full_preview, full_caption = preview_support.build_dataframe_preview(
        df,
        max_rows=5,
        max_cols=5,
    )
    assert full_preview.equals(df)
    assert full_caption is None


def test_build_dataframe_preview_requires_dataframe():
    with pytest.raises(TypeError, match="pandas DataFrame"):
        preview_support.build_dataframe_preview(["not", "a", "df"], max_rows=1, max_cols=1)


def test_resolve_export_target_expands_user_and_env(monkeypatch, tmp_path):
    monkeypatch.setenv("PAGELIB_EXPORT_ROOT", str(tmp_path))

    path, error = preview_support.resolve_export_target("$PAGELIB_EXPORT_ROOT/out.csv")

    assert error is None
    assert path == tmp_path / "out.csv"


def test_resolve_export_target_rejects_blank_and_directories(tmp_path):
    path, error = preview_support.resolve_export_target("   ")
    assert path is None
    assert error == "Please provide a filename for the export."

    directory = tmp_path / "folder"
    directory.mkdir()
    path, error = preview_support.resolve_export_target(directory)
    assert path is None
    assert error == f"{Path(directory)} is a directory instead of a filename."
