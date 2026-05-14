from __future__ import annotations

from pathlib import Path

from agi_env import pagelib_navigation_support as nav_support


def test_ensure_csv_files_state_initializes_defaults_and_keeps_existing_dataset_files(tmp_path):
    datadir = tmp_path / "datasets"
    datadir.mkdir()
    first = datadir / "first.csv"
    second = datadir / "second.csv"
    first.write_text("a\n1\n", encoding="utf-8")
    second.write_text("a\n2\n", encoding="utf-8")

    state = {"dataset_files": ["stale-entry"]}

    nav_support.ensure_csv_files_state(state, datadir, [first, second])

    assert state["csv_files"] == [first, second]
    assert state["dataset_files"] == ["stale-entry"]
    assert state["df_file"] == "first.csv"


def test_clear_dataframe_selection_state_and_copy_widget_value():
    state = {
        "df_file": "a.csv",
        "csv_files": ["a.csv"],
        "dataset_files": ["a.csv"],
        "input_datadir": "/tmp/next",
    }

    nav_support.clear_dataframe_selection_state(state)
    nav_support.copy_widget_value(state, "datadir", "input_datadir")

    assert "df_file" not in state
    assert "csv_files" not in state
    assert "dataset_files" not in state
    assert state["datadir"] == "/tmp/next"


def test_build_project_selection_keeps_current_project_visible_when_truncated():
    projects = [f"demo_{idx:03d}_project" for idx in range(60)]
    current = projects[-1]

    selection = nav_support.build_project_selection(projects, current, "demo_", limit=50)

    assert selection.shortlist[0] == current
    assert len(selection.shortlist) == 51
    assert selection.total_matches == 60
    assert selection.default_index == 0
    assert selection.needs_caption is True


def test_build_project_selection_handles_empty_search():
    selection = nav_support.build_project_selection(["alpha", "beta"], "alpha", "zzz")

    assert selection.shortlist == []
    assert selection.total_matches == 0
    assert selection.default_index == 0
    assert selection.needs_caption is False


def test_normalize_query_param_value_and_active_app_candidates(tmp_path):
    apps_root = tmp_path / "apps"
    builtin_root = apps_root / "builtin"
    builtin_root.mkdir(parents=True)

    assert nav_support.normalize_query_param_value(["a", "flight"]) == "flight"
    assert nav_support.normalize_query_param_value("flight") == "flight"
    assert nav_support.normalize_query_param_value(None) is None

    candidates = nav_support.active_app_candidates(
        "flight",
        apps_root,
        ["flight_telemetry_project"],
        preferred_base=tmp_path / "preferred",
    )

    assert candidates[0] == Path("flight").expanduser()
    assert builtin_root / "flight_telemetry_project" in candidates
    assert len(candidates) == len(set(candidates))


def test_resolve_default_selection_and_sidebar_dataframe_selection(tmp_path):
    export_root = tmp_path / "export"
    lab_dir = export_root / "lab_a"
    lab_dir.mkdir(parents=True)
    default_df = lab_dir / "default_df"
    other_df = lab_dir / "other.csv"
    default_df.write_text("a\n1\n", encoding="utf-8")
    other_df.write_text("a\n2\n", encoding="utf-8")

    selected, index = nav_support.resolve_default_selection(["lab_a", "lab_b"], None, "lab_b")
    assert selected == "lab_b"
    assert index == 1

    sidebar = nav_support.build_sidebar_dataframe_selection(
        export_root,
        "lab_a",
        [other_df, default_df],
        None,
        "lab_a",
    )

    assert sidebar.module_path == Path("lab_a")
    assert sidebar.df_files_rel == [Path("lab_a/default_df"), Path("lab_a/other.csv")]
    assert sidebar.index_page == Path("lab_a/default_df")
    assert sidebar.key_df == "lab_a/default_dfdf"
    assert sidebar.default_index == 0


def test_resolve_default_selection_handles_empty_preferred_and_plain_default():
    assert nav_support.resolve_default_selection([], "lab_a", "lab_b") == (None, 0)
    assert nav_support.resolve_default_selection(["lab_a", "lab_b"], "lab_a", "lab_b") == (
        "lab_a",
        0,
    )
    assert nav_support.resolve_default_selection(["lab_a", "lab_b"], "missing", None) == (
        "lab_a",
        0,
    )


def test_resolve_selected_df_path_handles_relative_absolute_and_fallback(tmp_path):
    export_root = tmp_path / "export"
    export_root.mkdir()
    explicit = tmp_path / "absolute.csv"
    explicit.write_text("a\n1\n", encoding="utf-8")

    rel_path = nav_support.resolve_selected_df_path(
        "lab_a/data.csv",
        export_root=export_root,
    )
    assert rel_path == export_root / "lab_a/data.csv"

    abs_path = nav_support.resolve_selected_df_path(explicit, export_root=export_root)
    assert abs_path == explicit

    fallback = nav_support.resolve_selected_df_path(
        None,
        fallback_df_file=explicit,
        export_root=export_root,
    )
    assert fallback == explicit
