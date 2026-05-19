from __future__ import annotations

import importlib
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest


class _CaptureCodeSink:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def code(self, *args: object, **kwargs: object) -> None:
        self.calls.append((args, kwargs))

    def __call__(self, *args: object, **kwargs: object) -> None:
        self.calls.append((args, kwargs))


def _import_agilab_module(module_name: str):
    src_root = Path(__file__).resolve().parents[1] / "src"
    package_root = src_root / "agilab"
    src_root_str = str(src_root)
    package_root_str = str(package_root)
    if src_root_str not in sys.path:
        sys.path.insert(0, src_root_str)
    pkg = sys.modules.get("agilab")
    if pkg is None or not hasattr(pkg, "__path__"):
        pkg = types.ModuleType("agilab")
        pkg.__path__ = [package_root_str]
        sys.modules["agilab"] = pkg
    else:
        package_path = list(pkg.__path__)
        if package_root_str not in package_path:
            pkg.__path__ = [package_root_str, *package_path]
    importlib.invalidate_caches()
    return importlib.import_module(module_name)


orchestrate_page_support = _import_agilab_module("agilab.orchestrate_page_support")

from agi_env.snippet_contract import CURRENT_SNIPPET_API


def _touch_fake_venv_python(venv: Path) -> Path:
    python = orchestrate_page_support._venv_python_path(venv)
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_text("# fake python for probe tests\n", encoding="utf-8")
    return python


def _seed_fake_venv_modules(venv: Path, *modules: str) -> Path:
    _touch_fake_venv_python(venv)
    if sys.platform.startswith("win"):
        site_packages = venv / "Lib" / "site-packages"
    else:
        site_packages = venv / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    site_packages.mkdir(parents=True, exist_ok=True)
    for module in modules:
        package_dir = site_packages / module
        package_dir.mkdir(parents=True, exist_ok=True)
        (package_dir / "__init__.py").write_text("", encoding="utf-8")
        if module == "agi_cluster":
            distributor_dir = package_dir / "agi_distributor"
            distributor_dir.mkdir(parents=True, exist_ok=True)
            (distributor_dir / "__init__.py").write_text("class StageRequest: ...\n", encoding="utf-8")
    return site_packages


def test_build_install_and_run_snippets_embed_expected_values():
    env = SimpleNamespace(apps_path="/tmp/apps", app="demo_project", is_source_env=False)

    install_snippet = orchestrate_page_support.build_install_snippet(
        env=env,
        verbose=2,
        mode=7,
        scheduler='"127.0.0.1:8786"',
        workers="{'127.0.0.1': 1}",
        workers_data_path='"/tmp/share"',
    )
    run_snippet = orchestrate_page_support.build_run_snippet(
        env=env,
        verbose=3,
        run_mode=15,
        scheduler='"127.0.0.1:8786"',
        workers="{'127.0.0.1': 2}",
        workers_data_path='"/tmp/share"',
        rapids_enabled=True,
        benchmark_best_single_node=True,
        run_args={"foo": "bar", "n": 2},
    )

    assert 'APP = "demo_project"' in install_snippet
    assert "modes_enabled=7" in install_snippet
    assert 'scheduler="127.0.0.1"' in install_snippet
    assert 'workers_data_path="/tmp/share"' in install_snippet
    assert f'AGILAB_SNIPPET_API = "{CURRENT_SNIPPET_API}"' in install_snippet
    assert "# app: demo_project" in install_snippet
    assert "require_supported_snippet_api(AGILAB_SNIPPET_API)" in install_snippet
    assert "RunRequest(" in run_snippet
    assert "mode=15" in run_snippet
    assert 'scheduler="127.0.0.1:8786"' in run_snippet
    assert 'workers_data_path="/tmp/share"' in run_snippet
    assert "rapids_enabled=True" in run_snippet
    assert "benchmark_best_single_node=True" in run_snippet
    assert 'RUN_PARAMS = json.loads(\'{"foo": "bar", "n": 2}\')' in run_snippet
    assert f'AGILAB_SNIPPET_API = "{CURRENT_SNIPPET_API}"' in run_snippet


def test_build_run_snippet_uses_stages_and_accepts_legacy_args_key():
    env = SimpleNamespace(apps_path="/tmp/apps", app="demo_project", is_source_env=False)

    run_snippet = orchestrate_page_support.build_run_snippet(
        env=env,
        verbose=1,
        run_mode=0,
        scheduler="None",
        workers="None",
        run_args={"stages": [{"name": "prepare", "args": {"n": 2}}]},
    )

    assert "StageRequest(" in run_snippet
    assert "RunRequest(" in run_snippet
    assert "stages=run_stages" in run_snippet
    assert "RUN_STAGES_PAYLOAD" in run_snippet

    legacy_run_snippet = orchestrate_page_support.build_run_snippet(
        env=env,
        verbose=1,
        run_mode=0,
        scheduler="None",
        workers="None",
        run_args={"args": [{"name": "prepare", "args": {"n": 2}}]},
    )

    assert "RUN_STAGES_PAYLOAD" in legacy_run_snippet
    assert '"name": "prepare"' in legacy_run_snippet

    with pytest.raises(ValueError, match="cannot contain both legacy key 'args' and current key 'stages'"):
        orchestrate_page_support.build_run_snippet(
            env=env,
            verbose=1,
            run_mode=0,
            scheduler="None",
            workers="None",
            run_args={
                "args": [{"name": "legacy"}],
                "stages": [{"name": "current"}],
            },
        )


def test_build_agi_snippets_do_not_inject_source_core_paths_for_source_env():
    env = SimpleNamespace(
        apps_path="/repo/src/agilab/apps",
        app="demo_project",
        is_source_env=True,
    )

    run_snippet = orchestrate_page_support.build_run_snippet(
        env=env,
        verbose=1,
        run_mode=0,
        scheduler="None",
        workers="None",
        run_args={},
    )
    distrib_snippet = orchestrate_page_support.build_distribution_snippet(
        env=env,
        verbose=1,
        scheduler="None",
        workers="None",
        args_serialized="",
    )
    install_snippet = orchestrate_page_support.build_install_snippet(
        env=env,
        verbose=1,
        mode=0,
        scheduler="None",
        workers="None",
        workers_data_path="None",
    )

    assert "import sys" not in run_snippet
    assert "from pathlib import Path" not in run_snippet
    assert "def _inject_source_core_paths() -> None:" not in run_snippet
    assert "def _inject_source_core_paths() -> None:" not in distrib_snippet
    assert "def _inject_source_core_paths() -> None:" not in install_snippet


def test_build_install_snippet_strips_scheduler_port_only_for_install() -> None:
    env = SimpleNamespace(apps_path="/tmp/apps", app="demo_project", is_source_env=False)

    install_snippet = orchestrate_page_support.build_install_snippet(
        env=env,
        verbose=1,
        mode=15,
        scheduler='"192.168.20.111:8786"',
        workers="{'192.168.20.111': 1, '192.168.20.15': 1}",
        workers_data_path='"/cluster/share"',
    )
    run_snippet = orchestrate_page_support.build_run_snippet(
        env=env,
        verbose=1,
        run_mode=15,
        scheduler='"192.168.20.111:8786"',
        workers="{'192.168.20.111': 1, '192.168.20.15': 1}",
        workers_data_path='"/cluster/share"',
        run_args={},
    )

    assert 'scheduler="192.168.20.111"' in install_snippet
    assert 'scheduler="192.168.20.111:8786"' in run_snippet

    non_source_snippet = orchestrate_page_support.build_run_snippet(
        env=SimpleNamespace(apps_path="/repo/src/agilab/apps", app="demo_project", is_source_env=False),
        verbose=1,
        run_mode=0,
        scheduler="None",
        workers="None",
        run_args={},
    )
    assert "import sys" not in non_source_snippet
    assert "def _inject_source_core_paths() -> None:" not in non_source_snippet


def test_build_distribution_snippet_omits_blank_args_payload():
    snippet = orchestrate_page_support.build_distribution_snippet(
        env=SimpleNamespace(apps_path="/tmp/apps", app="demo_project", is_source_env=False),
        verbose=1,
        scheduler="None",
        workers="None",
        args_serialized="",
    )

    assert "get_distrib" in snippet
    assert "workers=None" in snippet
    assert f'AGILAB_SNIPPET_API = "{CURRENT_SNIPPET_API}"' in snippet
    assert ",\n        \n" not in snippet


def test_orchestrate_snippets_preserve_builtin_apps_path(tmp_path: Path):
    apps_path = tmp_path / "apps"
    builtin_apps = apps_path / "builtin"
    (builtin_apps / "flight_telemetry_project").mkdir(parents=True)
    env = SimpleNamespace(apps_path=apps_path, app="flight_telemetry_project", is_source_env=True)

    run_snippet = orchestrate_page_support.build_run_snippet(
        env=env,
        verbose=1,
        run_mode=0,
        scheduler="None",
        workers="None",
        run_args={},
    )
    distrib_snippet = orchestrate_page_support.build_distribution_snippet(
        env=env,
        verbose=1,
        scheduler="None",
        workers="None",
        args_serialized="",
    )
    install_snippet = orchestrate_page_support.build_install_snippet(
        env=env,
        verbose=1,
        mode=0,
        scheduler="None",
        workers="None",
        workers_data_path="None",
    )

    expected = f'APPS_PATH = "{builtin_apps}"'
    assert expected in run_snippet
    assert expected in distrib_snippet
    assert expected in install_snippet


def test_merge_app_settings_sources_merges_args_but_keeps_cluster_file_backed():
    merged = orchestrate_page_support.merge_app_settings_sources(
        {
            "args": {"data_in": "file/input"},
            "cluster": {"cluster_enabled": False, "pool": False},
            "verbose": 1,
        },
        {
            "args": {"data_out": "session/output"},
            "cluster": {"cluster_enabled": True, "pool": True},
            "verbose": 3,
        },
    )

    assert merged == {
        "args": {"data_in": "file/input", "data_out": "session/output"},
        "cluster": {"cluster_enabled": False, "pool": False},
        "verbose": 3,
    }


def test_merge_app_settings_sources_ignores_session_only_cluster_snapshot():
    merged = orchestrate_page_support.merge_app_settings_sources(
        {},
        {
            "args": {"data_in": "session/input"},
            "cluster": {"cluster_enabled": True},
        },
    )

    assert merged["args"] == {"data_in": "session/input"}
    assert merged["cluster"] == {}


def test_resolve_requested_run_mode_switches_between_single_and_benchmark_modes():
    cluster_params = {"pool": True, "cython": True, "rapids": True}

    assert orchestrate_page_support.resolve_requested_run_mode(
        cluster_params,
        cluster_enabled=False,
        benchmark_enabled=False,
    ) == 11
    assert orchestrate_page_support.resolve_requested_run_mode(
        cluster_params,
        cluster_enabled=False,
        benchmark_enabled=True,
    ) == [0, 1, 2, 3, 8, 9, 10, 11]
    assert orchestrate_page_support.resolve_requested_run_mode(
        cluster_params,
        cluster_enabled=True,
        benchmark_enabled=True,
        benchmark_modes=[0, 7, 15, 99],
    ) == [0, 7, 15]


def test_benchmark_mode_helpers_expose_only_enabled_capabilities():
    cluster_params = {"pool": True, "cython": False, "rapids": True}

    assert orchestrate_page_support.available_benchmark_modes(
        cluster_params,
        cluster_enabled=False,
    ) == [0, 1, 8, 9]
    assert orchestrate_page_support.available_benchmark_modes(
        cluster_params,
        cluster_enabled=True,
    ) == [0, 1, 4, 5, 8, 9, 12, 13]
    assert orchestrate_page_support.sanitize_benchmark_modes(
        [13, "bad", 99, 1, "1"],
        [0, 1, 13],
    ) == [1, 13]
    assert orchestrate_page_support.benchmark_mode_label(13) == "13: rapids and dask and pool"
    assert orchestrate_page_support.order_benchmark_display_columns(
        ["order", "mode", "nodes", "node", "variant", "seconds"]
    ) == ["order", "variant", "nodes", "node", "mode", "seconds"]
    fake_column_config = SimpleNamespace(
        TextColumn=lambda label, **kwargs: {"label": label, **kwargs}
    )
    column_config = orchestrate_page_support.benchmark_dataframe_column_config(
        fake_column_config
    )
    assert column_config["mode"]["label"] == "mode"
    assert "4-slot execution signature" in column_config["mode"]["help"]
    assert "Dask/cluster" in column_config["mode"]["help"]
    assert "process or thread backend" in column_config["mode"]["help"]
    assert "`r d c p`" in orchestrate_page_support.BENCHMARK_MODE_LEGEND_MARKDOWN
    assert "worker pool" in orchestrate_page_support.BENCHMARK_MODE_LEGEND_MARKDOWN
    assert "`____` local Python" in orchestrate_page_support.BENCHMARK_MODE_LEGEND_MARKDOWN
    assert "`_d__` Dask only" in orchestrate_page_support.BENCHMARK_MODE_LEGEND_MARKDOWN


def test_benchmark_rows_with_delta_percent_adds_relative_gap():
    rows = orchestrate_page_support.benchmark_rows_with_delta_percent(
        {
            "0": {"mode": "python", "seconds": 10.0},
            "1": {"mode": "pool", "seconds": 12.5},
            "2": {"mode": "cython", "seconds": "5"},
        }
    )

    assert rows["2"]["delta (%)"] == 0.0
    assert rows["0"]["delta (%)"] == 100.0
    assert rows["1"]["delta (%)"] == 150.0


def test_benchmark_rows_with_delta_percent_handles_zero_and_invalid_seconds():
    rows = orchestrate_page_support.benchmark_rows_with_delta_percent(
        {
            "0": {"mode": "best", "seconds": 0.0},
            "1": {"mode": "slower", "seconds": 2.0},
            "2": {"mode": "unknown", "seconds": "n/a"},
            "meta": "kept",
        }
    )

    assert rows["0"]["delta (%)"] == 0.0
    assert rows["1"]["delta (%)"] is None
    assert "delta (%)" not in rows["2"]
    assert rows["meta"] == "kept"


def test_benchmark_rows_hide_best_node_non_rapids_when_rapids_counterpart_exists():
    rows = orchestrate_page_support.benchmark_rows_with_delta_percent(
        {
            "4:best-node": {
                "variant": "best-node",
                "node": "192.0.2.10",
                "mode": "_d__",
                "seconds": 2.0,
            },
            "12:best-node": {
                "variant": "best-node",
                "node": "192.0.2.10",
                "mode": "rd__",
                "seconds": 1.0,
            },
            "4": {
                "variant": "cluster",
                "node": "cluster",
                "mode": "_d__",
                "seconds": 3.0,
            },
        }
    )

    assert "4:best-node" not in rows
    assert rows["12:best-node"]["delta (%)"] == 0.0
    assert rows["4"]["delta (%)"] == 200.0


def test_benchmark_workers_data_path_requires_shared_path_for_remote_dask(tmp_path):
    local_share = tmp_path / "localshare"
    local_share.mkdir()

    assert orchestrate_page_support.benchmark_workers_data_path_issue(
        modes=[0, 1],
        workers={"192.168.1.20": 1},
        workers_data_path="",
        local_share_path=local_share,
    ) == ""
    assert "require Workers Data Path" in orchestrate_page_support.benchmark_workers_data_path_issue(
        modes=[4],
        workers={"192.168.1.20": 1},
        workers_data_path="",
        local_share_path=local_share,
    )
    assert "local share" in orchestrate_page_support.benchmark_workers_data_path_issue(
        modes=[4],
        workers={"192.168.1.20": 1},
        workers_data_path=str(local_share),
        local_share_path=local_share,
    )
    assert orchestrate_page_support.benchmark_workers_data_path_issue(
        modes=[4],
        workers={"127.0.0.1": 1},
        workers_data_path=str(local_share),
        local_share_path=local_share,
    ) == ""
    assert orchestrate_page_support.benchmark_workers_data_path_issue(
        modes=[4],
        workers={"192.168.1.20": 1},
        workers_data_path="/mnt/shared/agilab",
        local_share_path=local_share,
    ) == ""


def test_serialize_args_payload_and_optional_exprs_cover_string_and_mapping_cases():
    payload = orchestrate_page_support.serialize_args_payload(
        {"dataset": "flight/source", "limit": 5, "enabled": True}
    )

    assert payload == 'dataset="flight/source", limit=5, enabled=True'
    assert orchestrate_page_support.optional_string_expr(True, "tcp://127.0.0.1:8786") == '"tcp://127.0.0.1:8786"'
    assert orchestrate_page_support.optional_string_expr(False, "ignored") == "None"
    assert orchestrate_page_support.optional_python_expr(True, {"127.0.0.1": 1}) == "{'127.0.0.1': 1}"
    assert orchestrate_page_support.optional_python_expr(False, {"127.0.0.1": 1}) == "None"


def test_run_mode_helpers_cover_label_generation():
    run_mode = orchestrate_page_support.compute_run_mode(
        {"pool": True, "cython": True, "rapids": True},
        cluster_enabled=True,
    )

    assert run_mode == 15
    assert orchestrate_page_support.describe_run_mode(run_mode, False) == "Run mode 15: rapids and dask and pool and cython"
    assert (
        orchestrate_page_support.describe_run_mode([0, 7, 15], True)
        == "Run mode benchmark (selected modes: 0, 7, 15)"
    )


def test_configured_cluster_share_matches_resolved_paths(tmp_path):
    home = tmp_path / "home"
    cluster_share = home / "clustershare" / "agi"
    cluster_share.mkdir(parents=True)

    assert orchestrate_page_support.configured_cluster_share_matches(
        cluster_share,
        cluster_share_path="clustershare/agi",
        home_abs=home,
    )
    assert orchestrate_page_support.configured_cluster_share_matches(
        "clustershare/agi",
        cluster_share_path=cluster_share,
        home_abs=home,
    )
    assert not orchestrate_page_support.configured_cluster_share_matches(
        home / "localshare" / "agi",
        cluster_share_path="clustershare/agi",
        home_abs=home,
    )
    assert not orchestrate_page_support.configured_cluster_share_matches(
        cluster_share,
        cluster_share_path="",
        home_abs=home,
    )


def test_reassign_distribution_plan_uses_stable_selection_keys_and_preserves_defaults():
    workers = ["10.0.0.1-1", "10.0.0.2-1"]
    work_plan_metadata = [[("A", 2)], [("B", 3)]]
    work_plan = [[["a.csv"]], [["b.csv"]]]
    selection_key = orchestrate_page_support.workplan_selection_key("A", 0, 0)

    new_metadata, new_plan = orchestrate_page_support.reassign_distribution_plan(
        workers=workers,
        work_plan_metadata=work_plan_metadata,
        work_plan=work_plan,
        selections={selection_key: "10.0.0.2-1"},
    )

    assert new_metadata == [[], [("A", 2), ("B", 3)]]
    assert new_plan == [[], [["a.csv"], ["b.csv"]]]

    unchanged_metadata, unchanged_plan = orchestrate_page_support.reassign_distribution_plan(
        workers=workers,
        work_plan_metadata=work_plan_metadata,
        work_plan=work_plan,
        selections={},
    )

    assert unchanged_metadata == [[("A", 2)], [("B", 3)]]
    assert unchanged_plan == [[["a.csv"]], [["b.csv"]]]


def test_update_distribution_payload_replaces_target_args_and_plan():
    updated = orchestrate_page_support.update_distribution_payload(
        {"workers": {"127.0.0.1": 1}, "unchanged": True},
        target_args={"foo": "bar"},
        work_plan_metadata=[[("A", 1)]],
        work_plan=[[["a.csv"]]],
    )

    assert updated == {
        "workers": {"127.0.0.1": 1},
        "unchanged": True,
        "target_args": {"foo": "bar"},
        "work_plan_metadata": [[("A", 1)]],
        "work_plan": [[["a.csv"]]],
    }


def test_strip_ansi_removes_escape_sequences():
    assert orchestrate_page_support.strip_ansi("\x1b[31merror\x1b[0m") == "error"


def test_is_dask_shutdown_noise_matches_known_lines():
    assert orchestrate_page_support.is_dask_shutdown_noise("Stream is closed")
    assert orchestrate_page_support.is_dask_shutdown_noise("File \"/usr/local/lib/python3.11/site-packages/distributed/comm.py\", line 1")
    assert orchestrate_page_support.is_dask_shutdown_noise("Traceback (most recent call last):")


def test_filter_noise_lines_removes_shutdown_lines_and_keeps_others():
    text = "\n".join(
        [
            "normal message",
            "StreamClosedError",
            "another line",
            "stream is closed",
        ]
    )
    assert orchestrate_page_support.filter_noise_lines(text) == "normal message\nanother line"


def test_format_log_block_orders_latest_first_and_limits():
    text = "\n".join(f"line {i}" for i in range(1, 6))
    assert orchestrate_page_support.format_log_block(text, newest_first=True, max_lines=3) == "line 5\nline 4\nline 3"
    assert orchestrate_page_support.format_log_block(text, newest_first=False, max_lines=3) == "line 3\nline 4\nline 5"


def test_filter_warning_messages_removes_virtual_env_mismatch():
    log = "\n".join(
        [
            "normal warning",
            "VIRTUAL_ENV=/tmp/.venv does not match the project environment path",
            "final",
        ]
    )
    assert (
        orchestrate_page_support.filter_warning_messages(log)
        == "normal warning\nfinal"
    )


def test_orchestrate_page_support_additional_helper_edges(tmp_path: Path, monkeypatch):
    builtin_active = tmp_path / "apps" / "builtin" / "demo_project"
    builtin_active.mkdir(parents=True)
    assert orchestrate_page_support.snippet_apps_path(
        SimpleNamespace(apps_path=tmp_path / "apps", app="demo_project", active_app=builtin_active)
    ) == str(builtin_active.parent)
    assert orchestrate_page_support.snippet_apps_path(SimpleNamespace(apps_path="", app="", active_app=None)) == ""
    with monkeypatch.context() as path_monkeypatch:
        original_exists = Path.exists

        def _exists_or_raise(self):
            if self == tmp_path / "apps" / "builtin" / "demo_project":
                raise OSError("exists failed")
            return original_exists(self)

        path_monkeypatch.setattr(Path, "exists", _exists_or_raise)
        assert orchestrate_page_support.snippet_apps_path(
            SimpleNamespace(apps_path=tmp_path / "apps", app="demo_project", active_app=None)
        ) == str(tmp_path / "apps")

    assert orchestrate_page_support.is_dask_shutdown_noise("") is False
    assert orchestrate_page_support.is_dask_shutdown_noise("The above exception was the direct cause") is True
    assert orchestrate_page_support.is_dask_shutdown_noise("Traceback") is True
    assert orchestrate_page_support.format_log_block("") == ""

    assert orchestrate_page_support._split_run_request_payload({"stages": None})[1] == []
    with pytest.raises(TypeError, match="stages"):
        orchestrate_page_support._split_run_request_payload({"stages": "bad"})
    assert orchestrate_page_support.resolve_project_change_args_override(
        is_args_from_ui=False,
        args_project="a",
        previous_project="a",
        app_settings_snapshot={"args": {"x": 1}},
    ) is None
    assert orchestrate_page_support.resolve_project_change_args_override(
        is_args_from_ui=True,
        args_project="a",
        previous_project="a",
        app_settings_snapshot={"args": {}},
    ) is None
    assert orchestrate_page_support.resolve_project_change_args_override(
        is_args_from_ui=True,
        args_project="a",
        previous_project="b",
        app_settings_snapshot={"args": {"x": 1}},
    ) is None
    assert orchestrate_page_support.resolve_project_change_args_override(
        is_args_from_ui=True,
        args_project="a",
        previous_project="a",
        app_settings_snapshot="bad",
    ) is None
    assert orchestrate_page_support.resolve_project_change_args_override(
        is_args_from_ui=True,
        args_project="a",
        previous_project="a",
        app_settings_snapshot={"args": "bad"},
    ) is None
    assert orchestrate_page_support._install_scheduler_expr(None) is None
    assert orchestrate_page_support._install_scheduler_expr(json.dumps(123)) == json.dumps(123)
    assert orchestrate_page_support._install_scheduler_expr(json.dumps("192.168.20.111:8786")) == json.dumps(
        "192.168.20.111"
    )

    assert orchestrate_page_support.merge_app_settings_sources({"args": "bad"}, {"args": {"x": 1}})["args"] == {"x": 1}
    assert orchestrate_page_support.optional_python_expr(True, []) == "None"
    assert orchestrate_page_support._install_scheduler_expr('"not-a-host-port"') == '"not-a-host-port"'
    assert orchestrate_page_support._install_scheduler_expr('{"not": "a string"}') == '{"not": "a string"}'

    assert orchestrate_page_support.available_benchmark_modes(
        {"pool": False, "cython": False, "rapids": False},
        cluster_enabled=False,
    ) == [0]
    assert orchestrate_page_support.benchmark_mode_label(-1) == "-1: unknown"
    assert orchestrate_page_support._best_node_rapids_counterpart_key("bad") is None
    assert orchestrate_page_support._best_node_rapids_counterpart_key("x:best-node") is None
    assert orchestrate_page_support._best_node_rapids_counterpart_key("8:best-node") is None
    assert orchestrate_page_support.benchmark_rows_with_delta_percent({"meta": "kept"}) == {"meta": "kept"}
    assert orchestrate_page_support.sanitize_benchmark_modes("1", [1]) == []
    assert orchestrate_page_support.order_benchmark_display_columns(["seconds", "value"]) == ["seconds", "value"]
    assert orchestrate_page_support.benchmark_dataframe_column_config(SimpleNamespace()) == {}

    assert orchestrate_page_support._worker_host("ssh://agi@[2001:db8::1]:22") == "2001:db8::1"
    assert orchestrate_page_support._worker_host("agi@192.168.1.5:22") == "192.168.1.5"
    assert orchestrate_page_support.has_nonlocal_workers("bad") is False
    assert orchestrate_page_support._resolved_path(None) is None
    assert orchestrate_page_support._resolved_path("\0bad") is None
    assert orchestrate_page_support.describe_run_mode([], True) == "Run mode benchmark (no mode selected)"
    assert orchestrate_page_support.describe_run_mode(99, False) == "Run mode unknown"

    reassigned_meta, reassigned_plan = orchestrate_page_support.reassign_distribution_plan(
        workers=["w1"],
        work_plan_metadata=[[("A", 1)], [("B", 1)]],
        work_plan=[[["a"]], [["b"]]],
        selections={orchestrate_page_support.workplan_selection_key("B", 1, 0): "missing"},
    )
    assert reassigned_meta == [[("A", 1)]]
    assert reassigned_plan == [[["a"]]]

    buffer: list[str] = []
    traceback_state = {"active": True}
    orchestrate_page_support.append_log_lines(buffer, "\nkept\n", cluster_verbose=1, traceback_state=traceback_state)
    assert buffer == ["kept"]
    assert traceback_state["active"] is False

    verbose_buffer: list[str] = []
    orchestrate_page_support.append_log_lines(
        verbose_buffer,
        "Traceback (most recent call last):\nkept",
        cluster_verbose=2,
        traceback_state={"active": False},
    )
    assert verbose_buffer == ["Traceback (most recent call last):", "kept"]

    code_sink = _CaptureCodeSink()
    orchestrate_page_support.display_log(
        stdout="",
        stderr="",
        session_state={},
        strip_ansi_fn=orchestrate_page_support.strip_ansi,
        code_fn=code_sink,
    )
    assert code_sink.calls[-1][0][0] == "No logs available"

    state: dict[str, object] = {}
    orchestrate_page_support.init_session_state(state, {"a": 1})
    orchestrate_page_support.clear_log(state)
    assert state["a"] == 1
    assert state["log_text"] == ""
    assert orchestrate_page_support.update_delete_confirm_state(
        state,
        "confirm",
        delete_armed_clicked=True,
        delete_cancel_clicked=False,
    ) is True
    assert state["confirm"] is True
    assert orchestrate_page_support.update_delete_confirm_state(
        state,
        "confirm",
        delete_armed_clicked=False,
        delete_cancel_clicked=True,
    ) is True
    assert "confirm" not in state
    assert orchestrate_page_support.update_delete_confirm_state(
        state,
        "confirm",
        delete_armed_clicked=False,
        delete_cancel_clicked=False,
    ) is False

    cleared: list[str] = []
    orchestrate_page_support.clear_cached_distribution(SimpleNamespace(clear=lambda: cleared.append("dist")))
    orchestrate_page_support.clear_mount_table_cache(SimpleNamespace(cache_clear=lambda: cleared.append("mount")))
    assert cleared == ["dist", "mount"]

    class BadResolvePath:
        def __init__(self, value):
            self.path = Path(str(value))

        def is_absolute(self):
            return self.path.is_absolute()

        def __truediv__(self, other):
            return BadResolvePath(self.path / Path(str(other)))

        def expanduser(self):
            self.path = self.path.expanduser()
            return self

        def resolve(self, *args, **kwargs):
            raise OSError("cannot resolve")

        def __str__(self):
            return str(self.path)

    assert str(orchestrate_page_support.resolve_share_candidate("share", tmp_path, path_type=BadResolvePath)) == str(
        tmp_path / "share"
    )
    assert orchestrate_page_support.configured_cluster_share_matches(
        object(),
        cluster_share_path="share",
        home_abs=tmp_path,
        path_type=lambda _value: (_ for _ in ()).throw(TypeError("bad path")),
    ) is False

    benchmark_file = tmp_path / "benchmark.json"
    benchmark_file.write_text("{}", encoding="utf-8")
    assert orchestrate_page_support.benchmark_display_date(benchmark_file, "manual") == "manual"
    assert orchestrate_page_support.benchmark_display_date(tmp_path / "missing.json", "") == ""


def test_log_indicates_install_failure():
    assert not orchestrate_page_support.log_indicates_install_failure(["all good", "installation complete"])
    assert not orchestrate_page_support.log_indicates_install_failure(
        [
            "Remote command stderr: error: Permission denied (os error 13)",
            "Failed to update uv on 192.168.20.15 (skipping self update): Process exited with non-zero exit status 2",
            "None",
            "Process finished",
        ]
    )
    assert not orchestrate_page_support.log_indicates_install_failure(
        [
            "error: Self-update is only available for uv binaries installed via the standalone installation scripts.",
            "Command failed with exit code 2: uv --quiet self update",
            "Failed to update uv (skipping self update): Command failed with exit code 2",
            "Installing manager: uv --quiet sync --dev --project flight_telemetry_project",
            "Process finished",
        ]
    )
    assert orchestrate_page_support.log_indicates_install_failure(["TRACEBACK", "Command failed with exit code 1"])
    assert orchestrate_page_support.log_indicates_install_failure(
        ["worker deploy failed: Process exited with non-zero exit status 2"]
    )
    assert orchestrate_page_support.log_indicates_install_failure(
        ["Failed to extract '/tmp/dataset.7z': not a 7z file"]
    )
    assert not orchestrate_page_support.log_indicates_install_failure([])


def test_app_install_status_rejects_stale_worker_venv_missing_core_import(tmp_path: Path) -> None:
    active_app = tmp_path / "mission_decision_project"
    worker_root = tmp_path / "wenv" / "mission_decision_worker"
    manager_venv = active_app / ".venv"
    worker_venv = worker_root / ".venv"
    _seed_fake_venv_modules(manager_venv, "agi_env", "agi_node", "agi_cluster")
    _seed_fake_venv_modules(worker_venv, "agi_node")
    env = SimpleNamespace(active_app=active_app, wenv_abs=worker_root)

    status = orchestrate_page_support.app_install_status(env)

    assert status["manager_ready"] is True
    assert status["worker_ready"] is False
    assert status["worker_exists"] is True
    assert status["worker_missing_modules"] == ("agi_env",)
    assert status["worker_problem"] == "missing modules: agi_env"
    assert orchestrate_page_support.is_app_installed(env) is False


def test_app_install_status_reports_missing_env_and_python(tmp_path: Path, monkeypatch) -> None:
    missing_venv = tmp_path / "missing"
    missing_status = orchestrate_page_support._venv_import_status(missing_venv, ("agi_env",))
    assert missing_status["exists"] is False
    assert missing_status["missing_modules"] == ("agi_env",)
    assert "environment path does not exist" in missing_status["problem"]

    empty_venv = tmp_path / "empty"
    empty_venv.mkdir()
    python_missing_status = orchestrate_page_support._venv_import_status(empty_venv, ("agi_env",))
    assert python_missing_status["exists"] is True
    assert python_missing_status["missing_modules"] == ("python",)
    assert "python executable is missing" in python_missing_status["problem"]

    lib_root = tmp_path / "lib-root"
    assert orchestrate_page_support._module_available_on_root(lib_root, "standalone") is False
    (lib_root / "standalone.py").parent.mkdir(parents=True, exist_ok=True)
    (lib_root / "standalone.py").write_text("", encoding="utf-8")
    assert orchestrate_page_support._module_available_on_root(lib_root, "standalone") is True
    assert orchestrate_page_support._drop_shadowed_best_node_non_rapids_rows(
        {
            "4:best-node": {"variant": "best-node", "node": "alpha"},
            "12:best-node": "not a mapping",
            "5:best-node": {"variant": "other", "node": "alpha"},
            "13:best-node": {"variant": "best-node", "node": "alpha"},
            "6:best-node": {"variant": "best-node", "node": "alpha"},
            "14:best-node": {"variant": "best-node", "node": "beta"},
        }
    ) == {
        "4:best-node": {"variant": "best-node", "node": "alpha"},
        "12:best-node": "not a mapping",
        "5:best-node": {"variant": "other", "node": "alpha"},
        "13:best-node": {"variant": "best-node", "node": "alpha"},
        "6:best-node": {"variant": "best-node", "node": "alpha"},
        "14:best-node": {"variant": "best-node", "node": "beta"},
    }

    site_packages = tmp_path / "site-packages"
    site_packages.mkdir()
    editable = tmp_path / "editable"
    editable.mkdir()
    (site_packages / "editable.pth").write_text("# comment\nimport site\nrelative-missing\n" + str(editable), encoding="utf-8")
    assert orchestrate_page_support._pth_import_roots(site_packages) == (editable.resolve(strict=False),)

    with monkeypatch.context() as path_monkeypatch:
        path_monkeypatch.setattr(
            Path,
            "glob",
            lambda self, pattern: (_ for _ in ()).throw(OSError("glob failed"))
            if self == site_packages and pattern == "*.pth"
            else (),
        )
        assert orchestrate_page_support._pth_import_roots(site_packages) == ()

    unreadable_pth = site_packages / "unreadable.pth"
    unreadable_pth.write_text(str(editable), encoding="utf-8")
    with monkeypatch.context() as path_monkeypatch:
        original_read_text = Path.read_text

        def _read_text_or_raise(self, *args, **kwargs):
            if self == unreadable_pth:
                raise OSError("unreadable")
            return original_read_text(self, *args, **kwargs)

        path_monkeypatch.setattr(Path, "read_text", _read_text_or_raise)
        assert editable.resolve(strict=False) in orchestrate_page_support._pth_import_roots(site_packages)

    with monkeypatch.context() as path_monkeypatch:
        original_resolve = Path.resolve

        def _resolve_or_raise(self, *args, **kwargs):
            if self == editable:
                raise OSError("resolve failed")
            return original_resolve(self, *args, **kwargs)

        path_monkeypatch.setattr(Path, "resolve", _resolve_or_raise)
        assert editable in orchestrate_page_support._pth_import_roots(site_packages)

    source_root = tmp_path / "source-root"
    module_dir = source_root / "pkg"
    module_dir.mkdir(parents=True)
    (module_dir / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    assert orchestrate_page_support._symbol_available_on_root(source_root, "pkg", "VALUE") is True
    with monkeypatch.context() as path_monkeypatch:
        original_read_text = Path.read_text

        def _source_read_text_or_raise(self, *args, **kwargs):
            if self == module_dir / "__init__.py":
                raise OSError("unreadable source")
            return original_read_text(self, *args, **kwargs)

        path_monkeypatch.setattr(Path, "read_text", _source_read_text_or_raise)
        assert orchestrate_page_support._symbol_available_on_root(source_root, "pkg", "VALUE") is False


def test_dataframe_preview_state_roundtrip_cleans_export_flags():
    state: dict[str, object] = {
        "loaded_df": "df",
        "loaded_graph": "graph",
        "loaded_source_path": "source.csv",
        "df_cols": ("a", "b"),
        "selected_cols": ("a",),
        "check_all": False,
        "_force_export_open": True,
        "dataframe_deleted": True,
        "export_col_0": False,
        "export_col_stale": True,
    }

    snapshot = orchestrate_page_support.capture_dataframe_preview_state(state)
    assert snapshot["df_cols"] == ["a", "b"]
    assert snapshot["selected_cols"] == ["a"]

    restore_state = {"export_col_0": False, "export_col_stale": True}
    orchestrate_page_support.restore_dataframe_preview_state(
        restore_state,
        {
            "loaded_df": "df2",
            "loaded_graph": None,
            "loaded_source_path": "",
            "df_cols": ["x", "y"],
            "selected_cols": ["z"],
            "check_all": True,
            "force_export_open": True,
            "dataframe_deleted": True,
        },
    )

    assert restore_state["loaded_df"] == "df2"
    assert "loaded_graph" not in restore_state
    assert "loaded_source_path" not in restore_state
    assert restore_state["selected_cols"] == ["x", "y"]
    assert restore_state["check_all"] is True
    assert restore_state["export_col_0"] is True
    assert restore_state["export_col_1"] is True
    assert "export_col_stale" not in restore_state

    orchestrate_page_support.toggle_select_all(restore_state)
    assert restore_state["selected_cols"] == ["x", "y"]
    restore_state["check_all"] = False
    orchestrate_page_support.toggle_select_all(restore_state)
    assert restore_state["selected_cols"] == []
    restore_state["export_col_0"] = True
    restore_state["export_col_1"] = False
    orchestrate_page_support.update_select_all(restore_state)
    assert restore_state["check_all"] is False
    assert restore_state["selected_cols"] == ["x"]


def test_app_install_status_requires_manager_agi_cluster_import(tmp_path: Path) -> None:
    active_app = tmp_path / "mission_decision_project"
    worker_root = tmp_path / "wenv" / "mission_decision_worker"
    manager_venv = active_app / ".venv"
    worker_venv = worker_root / ".venv"
    _seed_fake_venv_modules(manager_venv, "agi_env", "agi_node")
    _seed_fake_venv_modules(worker_venv, "agi_env", "agi_node")
    env = SimpleNamespace(active_app=active_app, wenv_abs=worker_root)

    status = orchestrate_page_support.app_install_status(env)

    assert status["manager_ready"] is False
    assert status["worker_ready"] is True
    assert status["manager_missing_modules"] == ("agi_cluster",)
    assert status["manager_problem"] == "missing modules: agi_cluster"


def test_app_install_status_rejects_stale_manager_missing_stage_request(tmp_path: Path) -> None:
    active_app = tmp_path / "weather_forecast_project"
    worker_root = tmp_path / "wenv" / "weather_forecast_worker"
    manager_site = _seed_fake_venv_modules(active_app / ".venv", "agi_env", "agi_node", "agi_cluster")
    worker_site = _seed_fake_venv_modules(worker_root / ".venv", "agi_env", "agi_node")
    stale_distributor = manager_site / "agi_cluster" / "agi_distributor"
    stale_distributor.mkdir(parents=True, exist_ok=True)
    (stale_distributor / "__init__.py").write_text("class StepRequest: ...\n", encoding="utf-8")
    env = SimpleNamespace(active_app=active_app, wenv_abs=worker_root)

    status = orchestrate_page_support.app_install_status(env)

    assert worker_site.exists()
    assert status["manager_ready"] is False
    assert status["worker_ready"] is True
    assert status["manager_missing_symbols"] == ("agi_cluster.agi_distributor.StageRequest",)
    assert status["manager_problem"] == "missing symbols: agi_cluster.agi_distributor.StageRequest"


def test_app_install_status_detects_editable_pth_import_roots(tmp_path: Path) -> None:
    active_app = tmp_path / "mission_decision_project"
    worker_root = tmp_path / "wenv" / "mission_decision_worker"
    manager_site = _seed_fake_venv_modules(active_app / ".venv", "agi_cluster")
    worker_site = _seed_fake_venv_modules(worker_root / ".venv")
    editable_core = tmp_path / "editable-core"
    for module in ("agi_env", "agi_node"):
        package_dir = editable_core / module
        package_dir.mkdir(parents=True, exist_ok=True)
        (package_dir / "__init__.py").write_text("", encoding="utf-8")
    (manager_site / "__editable__.agi_env-2026.5.7.pth").write_text(str(editable_core), encoding="utf-8")
    (worker_site / "__editable__.agi_env-2026.5.7.pth").write_text(str(editable_core), encoding="utf-8")
    env = SimpleNamespace(active_app=active_app, wenv_abs=worker_root)

    status = orchestrate_page_support.app_install_status(env)

    assert status["manager_ready"] is True
    assert status["worker_ready"] is True


def test_append_log_lines_filters_tracebacks_and_dask_noise():
    buffer: list[str] = []
    state = {"active": False}
    orchestrate_page_support.append_log_lines(
        buffer,
        "\n".join(["normal", "Traceback (most recent call last):", "stream is closed", "", "next"]),
        cluster_verbose=1,
        traceback_state=state,
    )
    assert buffer == ["normal", "next"]
    assert state["active"] is False


def test_update_log_helper_updates_session_state_and_trims_output():
    sink = _CaptureCodeSink()
    session_state: dict[str, object] = {}
    traceback_state = {"active": False}

    for i in range(1, 5):
        orchestrate_page_support.update_log(
            session_state,
            sink,
            f"line {i}",
            max_lines=3,
            cluster_verbose=2,
            traceback_state=traceback_state,
            strip_ansi_fn=orchestrate_page_support.strip_ansi,
            is_dask_shutdown_noise_fn=orchestrate_page_support.is_dask_shutdown_noise,
            log_display_max_lines=2,
            live_log_min_height=160,
        )

    assert session_state["log_text"] == "line 2\nline 3\nline 4\n"
    assert sink.calls[-1][0][0] == "line 3\nline 4"
    assert sink.calls[-1][1]["language"] == "python"
    assert sink.calls[-1][1]["height"] == 160


def test_update_log_helper_ignores_traceback_and_dask_noise_at_low_verbosity():
    sink = _CaptureCodeSink()
    session_state: dict[str, object] = {"cluster_verbose": 1}
    traceback_state = {"active": False}

    for message in [
        "normal",
        "Traceback (most recent call last):",
        "stream is closed",
        "",
        "after traceback",
    ]:
        orchestrate_page_support.update_log(
            session_state,
            sink,
            message,
            max_lines=10,
            cluster_verbose=1,
            traceback_state=traceback_state,
            strip_ansi_fn=orchestrate_page_support.strip_ansi,
            is_dask_shutdown_noise_fn=orchestrate_page_support.is_dask_shutdown_noise,
            log_display_max_lines=10,
            live_log_min_height=100,
        )

    assert session_state["log_text"] == "normal\nafter traceback\n"
    assert traceback_state["active"] is False
    assert sink.calls[-1][0][0] == "normal\nafter traceback"


def test_display_log_helper_warns_on_warning_stderr_and_uses_stderr_path():
    warnings: list[str] = []
    errors: list[str] = []
    code_sink = _CaptureCodeSink()

    def _warn(message: str) -> None:
        warnings.append(message)

    def _err(message: str) -> None:
        errors.append(message)

    orchestrate_page_support.display_log(
        stdout="normal output\nwarning: deprecated option\n",
        stderr="",
        session_state={},
        strip_ansi_fn=orchestrate_page_support.strip_ansi,
        filter_warning_messages_fn=lambda text: text,
        format_log_block_fn=lambda text: text,
        warning_fn=_warn,
        error_fn=_err,
        code_fn=code_sink,
        log_display_max_lines=250,
        log_display_height=300,
    )

    assert warnings == ["Warnings occurred during cluster installation:"]
    assert errors == []
    assert code_sink.calls[-1][0][0] == "normal output\nwarning: deprecated option"


def test_display_log_helper_uses_cached_stdout_when_missing_and_shows_stderr_errors():
    errors: list[str] = []
    warning_messages: list[str] = []
    code_sink = _CaptureCodeSink()

    orchestrate_page_support.display_log(
        stdout="",
        stderr="something failed",
        session_state={"log_text": "fallback log"},
        strip_ansi_fn=orchestrate_page_support.strip_ansi,
        filter_warning_messages_fn=lambda text: text,
        format_log_block_fn=lambda text: text,
        warning_fn=lambda message: warning_messages.append(message),
        error_fn=lambda message: errors.append(message),
        code_fn=code_sink,
        log_display_max_lines=250,
        log_display_height=300,
    )

    assert warning_messages == []
    assert errors == ["Errors occurred during cluster installation:"]
    assert code_sink.calls[-1][0][0] == "something failed"


def test_capture_and_restore_dataframe_preview_state_round_trip():
    session_state: dict[str, object] = {
        "loaded_df": {"rows": 1},
        "loaded_graph": {"nodes": 3},
        "loaded_source_path": "/tmp/source.csv",
        "df_cols": ["a", "b"],
        "selected_cols": ["a"],
        "check_all": False,
        "_force_export_open": True,
        "dataframe_deleted": False,
        "export_col_0": True,
        "export_col_1": False,
    }

    captured = orchestrate_page_support.capture_dataframe_preview_state(session_state)
    assert captured["loaded_df"] == {"rows": 1}
    assert captured["df_cols"] == ["a", "b"]
    assert captured["selected_cols"] == ["a"]

    target: dict[str, object] = {}
    orchestrate_page_support.restore_dataframe_preview_state(
        target,
        payload={
            "loaded_df": "restored_df",
            "loaded_graph": "restored_graph",
            "loaded_source_path": "/tmp/restored.csv",
            "df_cols": ["x", "y"],
            "selected_cols": ["y"],
            "check_all": True,
            "force_export_open": False,
            "dataframe_deleted": True,
        },
    )

    assert target["loaded_df"] == "restored_df"
    assert target["loaded_graph"] == "restored_graph"
    assert target["loaded_source_path"] == "/tmp/restored.csv"
    assert target["df_cols"] == ["x", "y"]
    assert target["selected_cols"] == ["x", "y"]
    assert target["check_all"] is True
    assert target["_force_export_open"] is False
    assert target["dataframe_deleted"] is True
    assert target["export_col_0"] is True
    assert target["export_col_1"] is True


def test_select_all_state_helpers_update_columns():
    session_state: dict[str, object] = {
        "df_cols": ["a", "b", "c"],
        "selected_cols": ["a"],
        "check_all": False,
    }
    orchestrate_page_support.toggle_select_all(session_state)
    assert session_state["selected_cols"] == []

    session_state["check_all"] = True
    orchestrate_page_support.toggle_select_all(session_state)
    assert session_state["selected_cols"] == ["a", "b", "c"]

    session_state.update({"export_col_0": True, "export_col_1": True, "export_col_2": False})
    orchestrate_page_support.update_select_all(session_state)
    assert session_state["check_all"] is False
    assert session_state["selected_cols"] == ["a", "b"]
