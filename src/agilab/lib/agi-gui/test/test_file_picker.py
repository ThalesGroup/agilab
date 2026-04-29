from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from agi_gui.file_picker import (
    FilePickerRoot,
    _button_label,
    _initial_selection,
    _safe_relative_posix,
    _validated_selection,
    agi_file_picker,
    is_path_under_root,
    list_file_picker_entries,
    normalize_file_patterns,
    normalize_file_picker_roots,
    resolve_under_roots,
    safe_upload_target,
    selected_paths_from_dataframe_state,
)


class _Popover:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _UploadedFile:
    def __init__(self, name: str, payload: bytes):
        self.name = name
        self._payload = payload

    def getbuffer(self) -> bytes:
        return self._payload


class _FakeStreamlit:
    def __init__(
        self,
        *,
        text_values: dict[str, str] | None = None,
        button_values: dict[str, bool] | None = None,
        checkbox_values: dict[str, bool] | None = None,
        dataframe_state=None,
        pills_value: str | None = None,
        uploads: list[_UploadedFile] | None = None,
    ):
        self.session_state: dict[str, object] = {}
        self.text_values = text_values or {}
        self.button_values = button_values or {}
        self.checkbox_values = checkbox_values or {}
        self.dataframe_state = dataframe_state or {"selection": {"rows": []}}
        self.pills_value = pills_value
        self.uploads = uploads
        self.captions: list[str] = []
        self.dataframes: list[dict[str, object]] = []
        self.errors: list[str] = []
        self.popovers: list[str] = []
        self.reruns = 0

    def popover(self, label, **_kwargs):
        self.popovers.append(str(label))
        return _Popover()

    def pills(self, _label, options, **_kwargs):
        return self.pills_value or options[0]

    def text_input(self, _label, *, key, **_kwargs):
        return self.text_values.get(key, str(self.session_state.get(key, "")))

    def checkbox(self, _label, *, key, **_kwargs):
        return self.checkbox_values.get(key, bool(self.session_state.get(key, False)))

    def dataframe(self, rows, **kwargs):
        self.dataframes.append({"rows": rows, **kwargs})
        return self.dataframe_state

    def caption(self, message):
        self.captions.append(str(message))

    def button(self, _label, *, key, disabled=False, **_kwargs):
        return False if disabled else self.button_values.get(key, False)

    def error(self, message):
        self.errors.append(str(message))

    def rerun(self):
        self.reruns += 1

    def file_uploader(self, _label, **_kwargs):
        return self.uploads


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


def test_normalize_roots_fills_blank_label_and_rejects_empty_roots(tmp_path: Path) -> None:
    roots = normalize_file_picker_roots({"": tmp_path / "exports"})

    assert roots == (FilePickerRoot(label="exports", path=(tmp_path / "exports").resolve(strict=False)),)
    with pytest.raises(ValueError, match="At least one"):
        normalize_file_picker_roots([])


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


def test_list_entries_handles_limits_missing_roots_and_large_files(tmp_path: Path) -> None:
    (tmp_path / "big.bin").write_bytes(b"x" * 2048)
    (tmp_path / "small.txt").write_text("x\n", encoding="utf-8")
    broken = tmp_path / "broken-link.csv"
    try:
        broken.symlink_to(tmp_path / "missing-target.csv")
    except OSError:
        broken = tmp_path / "uncreated-broken-link.csv"

    entries = list_file_picker_entries(tmp_path, recursive=False, max_entries=1)
    all_entries = list_file_picker_entries(tmp_path, recursive=False, max_entries=10)

    assert len(entries) == 1
    assert entries[0].size == "2.0 KB"
    assert broken.name not in {entry.name for entry in all_entries}
    assert list_file_picker_entries(tmp_path, allow_files=False, allow_dirs=False) == []
    assert list_file_picker_entries(tmp_path / "missing") == []
    with pytest.raises(ValueError, match="max_entries"):
        list_file_picker_entries(tmp_path, max_entries=0)


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
    with pytest.raises(ValueError, match="configured roots"):
        resolve_under_roots("missing.csv", {"Project": root})
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
    outside = tmp_path / "outside"
    outside.mkdir()
    symlink_dir = upload_dir / "link"
    try:
        symlink_dir.symlink_to(outside, target_is_directory=True)
    except OSError:
        return
    with pytest.raises(ValueError, match="Unsafe upload filename"):
        safe_upload_target(upload_dir, "link/out.csv", {"Uploads": upload_dir})


def test_selected_paths_from_dataframe_state_supports_object_and_dict_state() -> None:
    rows = [
        {"path": "/tmp/first.csv"},
        {"path": "/tmp/second.csv"},
    ]
    object_state = SimpleNamespace(selection=SimpleNamespace(rows=[1]))

    assert selected_paths_from_dataframe_state(object_state, rows) == ["/tmp/second.csv"]
    assert selected_paths_from_dataframe_state({"selection": {"rows": [0, 99]}}, rows) == ["/tmp/first.csv"]
    assert selected_paths_from_dataframe_state({"selection": {"rows": None}}, rows) == []
    assert selected_paths_from_dataframe_state({"selection": {"rows": [0]}}, [{"name": "missing"}]) == []


def test_helper_edges_for_defaults_labels_and_relative_paths(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    inside = root / "inside.csv"
    inside.write_text("ok\n", encoding="utf-8")
    outside = tmp_path / "outside.csv"
    outside.write_text("no\n", encoding="utf-8")
    roots = (FilePickerRoot("Project", root.resolve()),)

    assert resolve_under_roots("future.csv", roots, must_exist=False) == (root / "future.csv").resolve(strict=False)
    assert _initial_selection([inside, outside], roots, "multi") == [str(inside.resolve())]
    assert _validated_selection(str(inside), roots, "single") == [str(inside.resolve())]
    assert _validated_selection([outside], roots, "multi") == []
    assert _validated_selection(object(), roots, "single") == []
    assert _safe_relative_posix(outside, root) == outside.as_posix()
    assert _button_label("Browse", [], "single") == "Browse"
    assert _button_label("Browse", [str(inside)], "single") == "Browse: inside.csv"
    assert _button_label("Browse", [str(inside)], "multi") == "Browse (1)"


def test_agi_file_picker_selects_dataframe_row(tmp_path: Path, monkeypatch) -> None:
    selected_file = tmp_path / "alpha.csv"
    selected_file.write_text("a\n", encoding="utf-8")
    (tmp_path / "beta.txt").write_text("b\n", encoding="utf-8")
    fake_st = _FakeStreamlit(dataframe_state={"selection": {"rows": [0]}})
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)

    result = agi_file_picker(
        "Browse",
        roots={"Project": tmp_path},
        key="picker",
        patterns="*.csv",
    )

    assert result == str(selected_file.resolve())
    assert fake_st.popovers == ["Browse"]
    assert fake_st.dataframes[0]["selection_mode"] == "single-row"
    assert fake_st.dataframes[0]["column_order"] == ("relative_path", "type", "size", "modified")


def test_agi_file_picker_handles_multi_root_empty_search_and_manual_error(tmp_path: Path, monkeypatch) -> None:
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    root_a.mkdir()
    root_b.mkdir()
    outside = tmp_path / "outside.csv"
    outside.write_text("no\n", encoding="utf-8")
    fake_st = _FakeStreamlit(
        text_values={
            "picker:query": "missing",
            "picker:manual_path": str(outside),
        },
        button_values={"picker:use_manual_path": True},
        pills_value="unknown",
    )
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)

    result = agi_file_picker(
        "Browse",
        roots={"A": root_a, "B": root_b},
        key="picker",
        selection_mode="multi",
    )

    assert result == []
    assert fake_st.captions == ["No matching files."]
    assert fake_st.errors and "configured roots" in fake_st.errors[0]


def test_agi_file_picker_manual_path_updates_selection(tmp_path: Path, monkeypatch) -> None:
    selected_file = tmp_path / "picked.csv"
    selected_file.write_text("x\n", encoding="utf-8")
    fake_st = _FakeStreamlit(
        text_values={"picker:manual_path": str(selected_file)},
        button_values={"picker:use_manual_path": True},
    )
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)

    result = agi_file_picker("Browse", roots={"Project": tmp_path}, key="picker")

    assert result == str(selected_file.resolve())
    assert fake_st.session_state["picker:selected_paths"] == [str(selected_file.resolve())]
    assert fake_st.reruns == 1


def test_agi_file_picker_upload_saves_files(tmp_path: Path, monkeypatch) -> None:
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    fake_st = _FakeStreamlit(
        uploads=[_UploadedFile("nested/new.csv", b"payload")],
    )
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)

    result = agi_file_picker(
        "Upload",
        roots={"Uploads": upload_dir},
        key="picker",
        selection_mode="multi",
        allow_upload=True,
        upload_dir=upload_dir,
        upload_types=["csv"],
    )

    saved_file = upload_dir / "nested" / "new.csv"
    assert result == [str(saved_file.resolve())]
    assert saved_file.read_bytes() == b"payload"
    assert fake_st.reruns == 1


def test_agi_file_picker_rejects_invalid_selection_mode(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="selection_mode"):
        agi_file_picker("Browse", roots={"Project": tmp_path}, key="picker", selection_mode="bad")
