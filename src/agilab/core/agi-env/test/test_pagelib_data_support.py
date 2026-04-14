from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from agi_env import pagelib_data_support as support


def test_get_first_match_and_keyword_skips_invalid_items_and_finds_first_match(capsys):
    text, keyword = support.get_first_match_and_keyword(
        [123, "mission-time"],
        [None, "time"],
    )

    captured = capsys.readouterr()
    assert text == "mission-time"
    assert keyword == "time"
    assert "not a string" in captured.out
    assert "not a valid string" in captured.out


def test_get_first_match_and_keyword_handles_empty_inputs():
    assert support.get_first_match_and_keyword([], ["time"]) == (None, None)
    assert support.get_first_match_and_keyword(["alpha"], []) == (None, None)


def test_find_files_filters_hidden_entries_and_respects_recursive_flag(tmp_path):
    root_csv = tmp_path / "root.csv"
    root_csv.write_text("value\n1\n", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    nested_csv = nested / "inner.csv"
    nested_csv.write_text("value\n2\n", encoding="utf-8")
    hidden = tmp_path / ".hidden"
    hidden.mkdir()
    (hidden / "ignored.csv").write_text("value\n3\n", encoding="utf-8")

    recursive = sorted(path.relative_to(tmp_path).as_posix() for path in support.find_files(tmp_path, ".csv", True))
    non_recursive = sorted(path.relative_to(tmp_path).as_posix() for path in support.find_files(tmp_path, ".csv", False))

    assert recursive == ["nested/inner.csv", "root.csv"]
    assert non_recursive == ["nested/inner.csv"]


def test_find_files_raises_with_diagnosis_message(tmp_path):
    missing = tmp_path / "missing"

    with pytest.raises(NotADirectoryError, match="share unavailable"):
        support.find_files(
            missing,
            diagnose_data_directory_fn=lambda _path: "share unavailable",
        )


def test_find_files_raises_with_generic_message_when_no_diagnosis(tmp_path):
    missing = tmp_path / "missing"

    with pytest.raises(NotADirectoryError, match="not a valid directory"):
        support.find_files(
            missing,
            diagnose_data_directory_fn=lambda _path: None,
        )


def test_load_df_supports_parquet_csv_and_json_inputs(tmp_path):
    csv_path = tmp_path / "time.csv"
    csv_path.write_text(
        "time,value\n1,10\n",
        encoding="utf-8",
    )
    json_path = tmp_path / "items.json"
    json_path.write_text('[{"name": "a"}]', encoding="utf-8")

    loaded_csv = support.load_df(csv_path)
    assert loaded_csv is not None
    assert pd.api.types.is_timedelta64_dtype(loaded_csv.index.dtype)

    loaded_json = support.load_df(json_path, with_index=False)
    assert list(loaded_json["name"]) == ["a"]


def test_load_df_folder_loads_json_directory_when_present(tmp_path):
    folder = tmp_path / "dataset"
    folder.mkdir()
    (folder / "a.json").write_text('[{"value": 1}]', encoding="utf-8")

    df = support.load_df(folder, with_index=False)
    assert df is not None
    assert list(df["value"]) == [1]


def test_load_df_preserves_latin1_csv_and_unsupported_returns_none(tmp_path):
    latin1_csv = tmp_path / "latin1.csv"
    latin1_csv.write_bytes("name,value\ncaf\xe9,3\n".encode("latin-1"))
    df = support.load_df(latin1_csv, with_index=False)
    assert df is not None
    assert df.iloc[0]["name"] == "café"
    assert df.index.tolist() == [0]

    assert support.load_df(tmp_path / "unsupported.md") is None


def test_get_df_index_read_files_and_default_behavior(tmp_path):
    target = tmp_path / "a.csv"
    assert support.get_df_index([str(target)], target) == 0
    assert support.get_df_index([], target) is None
    assert support.get_df_index([str(tmp_path / "x.csv")], tmp_path / "missing.csv") == 0


def test_list_views_and_read_file_lines_and_scan_dir(tmp_path):
    views = tmp_path / "views"
    views.mkdir()
    (views / "demo.py").write_text("print('ok')\n", encoding="utf-8")
    (views / "__init__.py").write_text("", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()

    assert support.list_views(views) == [str(views / "demo.py")]

    data = tmp_path / "data.csv"
    data.write_text("a\n1\n", encoding="utf-8")
    assert list(support.read_file_lines(data)) == ["a", "1"]

    assert sorted(support.scan_dir(tmp_path)) == ["nested", "views"]
