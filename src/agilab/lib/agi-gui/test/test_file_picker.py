from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from agi_gui.file_picker import (
    FilePickerRoot,
    is_path_under_root,
    list_file_picker_entries,
    normalize_file_patterns,
    normalize_file_picker_roots,
    resolve_under_roots,
    safe_upload_target,
    selected_paths_from_dataframe_state,
)


def test_normalize_roots_accepts_mapping_and_rejects_duplicates(tmp_path: Path) -> None:
    roots = normalize_file_picker_roots({"Project": tmp_path})

    assert roots == (FilePickerRoot(label="Project", path=tmp_path.resolve()),)

    with pytest.raises(ValueError, match="Duplicate"):
        normalize_file_picker_roots(
            [
                FilePickerRoot("Project", tmp_path),
                FilePickerRoot("Project", tmp_path / "other"),
            ]
        )


def test_file_patterns_default_to_match_all() -> None:
    assert normalize_file_patterns(None) == ("*",)
    assert normalize_file_patterns(["", " *.csv ", "*.json"]) == ("*.csv", "*.json")


def test_list_entries_is_sorted_filters_hidden_and_patterns(tmp_path: Path) -> None:
    (tmp_path / "zeta.csv").write_text("z\n", encoding="utf-8")
    (tmp_path / "alpha.JSON").write_text("{}\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("skip\n", encoding="utf-8")
    (tmp_path / ".hidden.csv").write_text("skip\n", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "beta.csv").write_text("b\n", encoding="utf-8")

    entries = list_file_picker_entries(tmp_path, patterns=["*.csv", "*.json"], allow_dirs=False)

    assert [entry.relative_path for entry in entries] == [
        "alpha.JSON",
        "nested/beta.csv",
        "zeta.csv",
    ]
    assert [entry.type for entry in entries] == ["json", "csv", "csv"]


def test_list_entries_can_include_directories(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "out.csv").write_text("x\n", encoding="utf-8")

    entries = list_file_picker_entries(tmp_path, patterns="*.csv", allow_dirs=True)

    assert [entry.relative_path for entry in entries] == ["data", "data/out.csv"]
    assert entries[0].type == "dir"


def test_resolve_under_roots_rejects_escape_and_symlink(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    inside = root / "inside.csv"
    inside.write_text("ok\n", encoding="utf-8")
    outside = tmp_path / "outside.csv"
    outside.write_text("no\n", encoding="utf-8")
    symlink = root / "outside-link.csv"

    assert resolve_under_roots("inside.csv", {"Project": root}) == inside.resolve()
    assert is_path_under_root(inside, root)

    with pytest.raises(ValueError, match="configured roots"):
        resolve_under_roots(outside, {"Project": root})
    try:
        symlink.symlink_to(outside)
    except OSError:
        return
    with pytest.raises(ValueError, match="configured roots"):
        resolve_under_roots(symlink, {"Project": root})


def test_safe_upload_target_preserves_directory_uploads_and_blocks_traversal(tmp_path: Path) -> None:
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()

    target = safe_upload_target(upload_dir, "nested/out.csv", {"Uploads": upload_dir})

    assert target == upload_dir / "nested" / "out.csv"
    with pytest.raises(ValueError, match="Unsafe upload filename"):
        safe_upload_target(upload_dir, "../out.csv", {"Uploads": upload_dir})
    with pytest.raises(ValueError, match="Unsafe upload filename"):
        safe_upload_target(upload_dir, r"..\out.csv", {"Uploads": upload_dir})


def test_selected_paths_from_dataframe_state_supports_object_and_dict_state() -> None:
    rows = [
        {"path": "/tmp/first.csv"},
        {"path": "/tmp/second.csv"},
    ]
    object_state = SimpleNamespace(selection=SimpleNamespace(rows=[1]))

    assert selected_paths_from_dataframe_state(object_state, rows) == ["/tmp/second.csv"]
    assert selected_paths_from_dataframe_state({"selection": {"rows": [0, 99]}}, rows) == ["/tmp/first.csv"]
