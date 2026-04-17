from __future__ import annotations

from pathlib import Path
from typing import Iterable, Iterator, Optional, Sequence
import glob
import os
import re

import pandas as pd


def _normalize_extension(ext: str) -> str:
    ext = (ext or "").strip()
    if not ext:
        return ""
    return f".{ext.lstrip('.')}"


def get_first_match_and_keyword(
    string_list: Sequence[object], keywords_to_find: Sequence[object]
) -> tuple[Optional[str], Optional[str]]:
    """
    Find the first occurrence of any keyword in any string.

    Returns:
        A tuple ``(matched_text, matched_keyword)`` or ``(None, None)`` when
        no match is found.
    """

    if not string_list or not keywords_to_find:
        return None, None

    for text_string in string_list:
        if not isinstance(text_string, str):
            print(f"Warning: Item in string_list is not a string: {text_string}")
            continue
        for keyword_pattern in keywords_to_find:
            if not isinstance(keyword_pattern, str) or not keyword_pattern:
                print(
                    f"Warning: Item in keywords_to_find is not a valid string: {keyword_pattern}"
                )
                continue
            if re.search(re.escape(keyword_pattern), text_string, re.IGNORECASE):
                return text_string, keyword_pattern
    return None, None


def _without_hidden_entries(
    directory: Path, paths: Iterable[Path]
) -> list[Path]:
    return [
        p
        for p in paths
        if not any(part.startswith(".") for part in p.relative_to(directory).parts)
    ]


def find_files(
    directory: str | Path,
    ext: str = ".csv",
    recursive: bool = True,
    *,
    path_type=Path,
    diagnose_data_directory_fn=lambda directory: None,
) -> list[Path]:
    """
    Return matching files from a directory, skipping hidden paths.
    """

    directory = path_type(directory)
    if not directory.is_dir():
        diagnosis = diagnose_data_directory_fn(directory)
        message = diagnosis or (
            f"{directory} is not a valid directory. "
            "If this path resides on a shared file mount, the shared file server may be down."
        )
        raise NotADirectoryError(message)

    normalized_ext = _normalize_extension(ext)
    if recursive:
        candidates = directory.rglob(f"*{normalized_ext}")
    else:
        candidates = directory.glob(f"*/*{normalized_ext}")

    visible_paths = _without_hidden_entries(directory, candidates)
    return sorted(visible_paths, key=lambda path: path.relative_to(directory).as_posix())


def load_df(
    path: str | Path,
    nrows=None,
    with_index: bool = True,
    cache_buster=None,
    *,
    path_type=Path,
) -> pd.DataFrame | None:
    """
    Load a dataset from a file or directory.
    """

    _ = cache_buster
    path = path_type(path)
    if not path.exists():
        return None

    df: pd.DataFrame | None = None
    if path.is_dir():
        files = sorted(
            list(path.rglob("*.parquet"))
            + list(path.rglob("*.csv"))
            + list(path.rglob("*.json"))
        )
        if not files:
            return None

        parquet_files = [f for f in files if f.suffix == ".parquet"]
        csv_files = [f for f in files if f.suffix == ".csv"]
        json_files = [f for f in files if f.suffix == ".json"]

        if parquet_files:
            df = pd.concat([pd.read_parquet(f) for f in parquet_files], ignore_index=True)
        elif csv_files:
            frames: list[pd.DataFrame] = []
            for file in csv_files:
                try:
                    frames.append(
                        pd.read_csv(file, nrows=nrows, encoding="utf-8", index_col=None)
                    )
                except UnicodeDecodeError:
                    frames.append(
                        pd.read_csv(
                            file,
                            nrows=nrows,
                            encoding="latin-1",
                            index_col=None,
                        )
                    )
            df = pd.concat(frames, ignore_index=True)
        elif json_files:
            df = pd.concat(
                [pd.read_json(file, orient="records") for file in json_files],
                ignore_index=True,
            )
    elif path.is_file():
        if path.suffix == ".csv":
            try:
                df = pd.read_csv(path, nrows=nrows, encoding="utf-8", index_col=None)
            except UnicodeDecodeError:
                df = pd.read_csv(path, nrows=nrows, encoding="latin-1", index_col=None)
        elif path.suffix == ".parquet":
            df = pd.read_parquet(path)
        elif path.suffix == ".json":
            df = pd.read_json(path, orient="records")
        else:
            return None
    else:
        return None

    if df is None:
        return None

    if "index" in df.columns:
        df = df.drop(columns=["index"])

    if with_index and not df.empty:
        col_name, keyword = get_first_match_and_keyword(
            df.columns.tolist(),
            ["time", "date"],
        )
        if col_name:
            if keyword == "time":
                df["index"] = pd.to_timedelta(df[col_name], unit="s")
            elif keyword == "date":
                df["index"] = pd.to_datetime(df[col_name], errors="coerce")
            df.set_index("index", inplace=True, drop=True)
        else:
            df.set_index(df.columns[0], inplace=True, drop=False)

    return df


def get_df_index(df_files, df_file):
    """
    Find the selected DataFrame file index in a list.
    """

    df_file_path = Path(df_file) if df_file else None
    if df_file_path and df_file_path.exists():
        try:
            return df_files.index(str(df_file_path))
        except ValueError:
            return None
    elif df_files:
        return 0
    return None


def list_views(views_root):
    """
    List all view Python files under the given root.
    """

    pattern = os.path.join(str(views_root), "**", "*.py")
    pages = [
        py_file
        for py_file in glob.glob(pattern, recursive=True)
        if not py_file.endswith("__init__.py")
    ]
    return sorted(pages)


def read_file_lines(filepath) -> Iterator[str]:
    """
    Read lines from a file, trimmed of trailing newline.
    """

    with open(filepath, "r") as file:
        for line in file:
            yield line.rstrip("\n")


def scan_dir(path: str | Path) -> list[str]:
    """
    List immediate subdirectories from a path in sorted order.
    """

    return sorted(
        [entry.name for entry in os.scandir(path) if entry.is_dir()]
        if os.path.exists(path)
        else []
    )
