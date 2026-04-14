from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path
from types import SimpleNamespace


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


def test_build_install_and_run_snippets_embed_expected_values():
    env = SimpleNamespace(apps_path="/tmp/apps", app="demo_project")

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
        args_serialized='foo="bar", n=2',
    )

    assert 'APP = "demo_project"' in install_snippet
    assert "modes_enabled=7" in install_snippet
    assert 'workers_data_path="/tmp/share"' in install_snippet
    assert "mode=15" in run_snippet
    assert 'foo="bar", n=2' in run_snippet


def test_build_distribution_snippet_omits_blank_args_payload():
    snippet = orchestrate_page_support.build_distribution_snippet(
        env=SimpleNamespace(apps_path="/tmp/apps", app="demo_project"),
        verbose=1,
        scheduler="None",
        workers="None",
        args_serialized="",
    )

    assert "get_distrib" in snippet
    assert "workers=None" in snippet
    assert ",\n        \n" not in snippet


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
    assert orchestrate_page_support.describe_run_mode(None, True) == "Run mode benchmark (all modes)"


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
