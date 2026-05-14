from __future__ import annotations

import builtins
import importlib
import importlib.util
import json
from importlib.machinery import ModuleSpec
import os
import sys
import tempfile
from pathlib import Path, PosixPath
from types import SimpleNamespace
import types

import pytest
from streamlit.errors import StreamlitAPIException


class _CaptureCodeSink:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def code(self, *args: object, **kwargs: object) -> None:
        self.calls.append((args, kwargs))

    def __call__(self, *args: object, **kwargs: object) -> None:
        self.calls.append((args, kwargs))


class _NotebookExpanderStreamlit:
    def __init__(self, *, fail_on_info: bool = False) -> None:
        self.session_state: dict[str, str] = {}
        self.captions: list[str] = []
        self.expanders: list[tuple[str, bool]] = []
        self.infos: list[str] = []
        self.downloads: list[tuple[str, dict[str, object]]] = []
        self._fail_on_info = fail_on_info

    def expander(self, label: str, *, expanded: bool = False):
        self.expanders.append((label, expanded))
        return self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def caption(self, message: str) -> None:
        self.captions.append(message)

    def info(self, message: str) -> None:
        if self._fail_on_info:
            raise AssertionError("download render should not show the empty-state info")
        self.infos.append(message)

    def download_button(self, label: str, **kwargs: object) -> None:
        self.downloads.append((label, kwargs))


def _import_agilab_module(module_name: str):
    src_root = Path(__file__).resolve().parents[1] / "src"
    package_root = src_root / "agilab"
    src_root_str = str(src_root)
    package_root_str = str(package_root)
    if src_root_str not in sys.path:
        sys.path.insert(0, src_root_str)
    pkg = types.ModuleType("agilab")
    pkg.__path__ = [package_root_str]
    pkg.__file__ = str(package_root / "__init__.py")
    pkg.__package__ = "agilab"
    spec = ModuleSpec("agilab", loader=None, is_package=True)
    spec.submodule_search_locations = [package_root_str]
    pkg.__spec__ = spec
    sys.modules["agilab"] = pkg
    importlib.invalidate_caches()
    return importlib.import_module(module_name)


def _prime_current_agilab_package() -> None:
    src_root = Path(__file__).resolve().parents[1] / "src"
    package_root = src_root / "agilab"
    src_root_str = str(src_root)
    package_root_str = str(package_root)
    if src_root_str not in sys.path:
        sys.path.insert(0, src_root_str)
    pkg = types.ModuleType("agilab")
    pkg.__path__ = [package_root_str]
    pkg.__file__ = str(package_root / "__init__.py")
    pkg.__package__ = "agilab"
    spec = ModuleSpec("agilab", loader=None, is_package=True)
    spec.submodule_search_locations = [package_root_str]
    pkg.__spec__ = spec
    sys.modules["agilab"] = pkg


def _load_orchestrate_page_helpers_module():
    _prime_current_agilab_package()
    module_path = Path("src/agilab/orchestrate_page_helpers.py")
    spec = importlib.util.spec_from_file_location("agilab_orchestrate_page_helpers_tests", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_orchestrate_page_helpers_module_with_import_failures(monkeypatch, names_to_fail: set[str]):
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

    for name in names_to_fail:
        sys.modules.pop(name, None)

    real_import = builtins.__import__
    real_import_module = importlib.import_module

    def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in names_to_fail:
            exc = ModuleNotFoundError(f"forced missing {name}")
            exc.name = name
            raise exc
        return real_import(name, globals, locals, fromlist, level)

    def _fake_import_module(name, package=None):
        if name in names_to_fail:
            exc = ModuleNotFoundError(f"forced missing {name}")
            exc.name = name
            raise exc
        return real_import_module(name, package)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    monkeypatch.setattr(importlib, "import_module", _fake_import_module)

    module_path = Path("src/agilab/orchestrate_page_helpers.py")
    spec = importlib.util.spec_from_file_location("agilab_orchestrate_page_helpers_fallback_tests", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_orchestrate_module():
    _prime_current_agilab_package()
    module_path = Path("src/agilab/pages/2_ORCHESTRATE.py")
    spec = importlib.util.spec_from_file_location("agilab_orchestrate_page_tests", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_orchestrate_module_with_mixed_checkout(monkeypatch, stale_root: Path):
    src_root = Path(__file__).resolve().parents[1] / "src"
    src_root_str = str(src_root)
    if src_root_str not in sys.path:
        sys.path.insert(0, src_root_str)
    pkg = types.ModuleType("agilab")
    pkg.__path__ = [str(stale_root)]
    pkg.__file__ = str(stale_root / "__init__.py")
    pkg.__package__ = "agilab"
    spec_pkg = ModuleSpec("agilab", loader=None, is_package=True)
    spec_pkg.submodule_search_locations = [str(stale_root)]
    pkg.__spec__ = spec_pkg
    monkeypatch.setitem(sys.modules, "agilab", pkg)

    module_path = Path("src/agilab/pages/2_ORCHESTRATE.py")
    spec = importlib.util.spec_from_file_location("agilab_orchestrate_page_importerror_tests", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


orchestrate_page_support = _import_agilab_module("agilab.orchestrate_page_support")


def test_page_helpers_rerun_fragment_or_app_falls_back_on_streamlit_api_error():
    module = _load_orchestrate_page_helpers_module()
    calls: list[tuple[str, object | None]] = []

    def _rerun(*, scope=None):
        calls.append(("rerun", scope))
        if scope == "fragment":
            raise StreamlitAPIException("bad scope")

    module.rerun_fragment_or_app(_rerun, StreamlitAPIException)

    assert calls == [("rerun", "fragment"), ("rerun", None)]


def test_page_helpers_fallback_loader_handles_missing_support_imports(monkeypatch):
    module = _load_orchestrate_page_helpers_module_with_import_failures(
        monkeypatch,
        {"agilab.orchestrate_page_support", "agilab.orchestrate_support"},
    )

    payload: dict[str, object] = {}
    module.init_session_state(payload, {"answer": 42})

    assert payload["answer"] == 42
    resolved = module.resolve_share_candidate("clustershare", "/home/agi")
    assert resolved.name == "clustershare"
    assert str(resolved).endswith("/home/agi/clustershare")
    assert module.configured_cluster_share_matches(
        resolved,
        cluster_share_path="clustershare",
        home_abs="/home/agi",
    )
    assert module.looks_like_shared_path(Path("/mnt/share"), Path("/repo")) is True


def test_orchestrate_page_raises_mixed_checkout_error(monkeypatch, tmp_path):
    stale_root = tmp_path / "stale" / "agilab"
    stale_root.mkdir(parents=True)

    with pytest.raises(ImportError, match="Mixed AGILAB checkout detected"):
        _load_orchestrate_module_with_mixed_checkout(monkeypatch, stale_root)


def test_page_helpers_delegate_scheduler_worker_and_safe_eval(monkeypatch):
    module = _load_orchestrate_page_helpers_module()
    captured = {}

    def _fake_scheduler(value, *, is_valid_ip, on_error):
        captured["scheduler"] = (value, is_valid_ip("127.0.0.1"))
        on_error("scheduler-error")
        return "scheduler"

    def _fake_workers(value, *, is_valid_ip, on_error, default_workers=None):
        captured["workers"] = (value, is_valid_ip("127.0.0.1"), default_workers)
        on_error("workers-error")
        return {"127.0.0.1": 2}

    def _fake_safe_eval(expression, expected_type, error_message, *, on_error):
        captured["safe_eval"] = (expression, expected_type, error_message)
        on_error("safe-eval-error")
        return 7

    monkeypatch.setattr(module, "_parse_and_validate_scheduler_impl", _fake_scheduler)
    monkeypatch.setattr(module, "_parse_and_validate_workers_impl", _fake_workers)
    monkeypatch.setattr(module, "_safe_eval_impl", _fake_safe_eval)

    errors: list[str] = []
    assert module.parse_and_validate_scheduler("127.0.0.1:9000", is_valid_ip=lambda ip: ip == "127.0.0.1", on_error=errors.append) == "scheduler"
    assert module.parse_and_validate_workers("127.0.0.1:2", is_valid_ip=lambda ip: ip == "127.0.0.1", on_error=errors.append, default_workers={"a": 1}) == {"127.0.0.1": 2}
    assert module.safe_eval("1 + 1", int, "bad", on_error=errors.append) == 7

    assert captured["scheduler"] == ("127.0.0.1:9000", True)
    assert captured["workers"] == ("127.0.0.1:2", True, {"a": 1})
    assert captured["safe_eval"] == ("1 + 1", int, "bad")
    assert errors == ["scheduler-error", "workers-error", "safe-eval-error"]


def test_page_helpers_delegate_state_log_and_install_wrappers(monkeypatch, tmp_path):
    module = _load_orchestrate_page_helpers_module()
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        module,
        "_init_session_state_impl",
        lambda session_state, defaults: session_state.update(defaults),
    )
    monkeypatch.setattr(
        module,
        "_clear_log_impl",
        lambda session_state: session_state.clear(),
    )
    monkeypatch.setattr(
        module,
        "_update_log_impl",
        lambda *args, **kwargs: captured.setdefault("update_log", (args, kwargs)),
    )
    monkeypatch.setattr(
        module,
        "_append_log_lines_impl",
        lambda *args, **kwargs: captured.setdefault("append_log_lines", (args, kwargs)),
    )
    monkeypatch.setattr(module, "_log_indicates_install_failure_impl", lambda lines: lines == ["failed"])
    monkeypatch.setattr(module, "_clear_cached_distribution_impl", lambda load_distribution_fn: load_distribution_fn())
    monkeypatch.setattr(module, "_clear_mount_table_cache_impl", lambda mount_table: mount_table.cache_clear())
    monkeypatch.setattr(
        module,
        "_resolve_share_candidate_impl",
        lambda path_value, home_abs, *, path_type=Path: path_type(home_abs) / str(path_value),
    )
    monkeypatch.setattr(
        module,
        "_display_log_impl",
        lambda *args, **kwargs: captured.setdefault("display_log", (args, kwargs)),
    )
    monkeypatch.setattr(module, "_toggle_select_all_impl", lambda session_state: session_state.__setitem__("all", True))
    monkeypatch.setattr(module, "_update_select_all_impl", lambda session_state: session_state.__setitem__("updated", True))
    monkeypatch.setattr(module, "_capture_dataframe_preview_state_impl", lambda session_state: {"preview": dict(session_state)})
    monkeypatch.setattr(module, "_restore_dataframe_preview_state_impl", lambda session_state, payload: session_state.update(payload))
    monkeypatch.setattr(module, "_is_app_installed_impl", lambda env: getattr(env, "ready", False))
    monkeypatch.setattr(module, "_app_install_status_impl", lambda env: {"ready": getattr(env, "ready", False)})

    session_state = {"x": 1}
    module.init_session_state(session_state, {"answer": 42})
    assert session_state["answer"] == 42
    module.clear_log(session_state)
    assert session_state == {}

    traceback_state = {"active": True}
    module.update_log(
        session_state,
        "placeholder",
        "message",
        max_lines=10,
        cluster_verbose=1,
        traceback_state=traceback_state,
        strip_ansi_fn=str,
        is_dask_shutdown_noise_fn=lambda _line: False,
        log_display_max_lines=50,
        live_log_min_height=120,
    )
    module.reset_traceback_skip(traceback_state)
    assert traceback_state["active"] is False

    module.append_log_lines(
        [],
        "payload",
        cluster_verbose=1,
        traceback_state={"active": False},
        is_dask_shutdown_noise_fn=lambda _line: False,
    )
    assert module.log_indicates_install_failure(["failed"]) is True

    query_params: dict[str, object] = {}
    module.set_active_app_query_param(query_params, "demo_project", streamlit_api_exception=StreamlitAPIException)
    assert query_params["active_app"] == "demo_project"

    calls = {"distribution": 0, "mount": 0}
    module.clear_cached_distribution(lambda: calls.__setitem__("distribution", calls["distribution"] + 1))
    module.clear_mount_table_cache(SimpleNamespace(cache_clear=lambda: calls.__setitem__("mount", calls["mount"] + 1)))
    assert calls == {"distribution": 1, "mount": 1}

    assert module.resolve_share_candidate("clustershare", "/home/agi") == Path("/home/agi/clustershare")
    assert module.configured_cluster_share_matches(
        Path("/home/agi/clustershare"),
        cluster_share_path="clustershare",
        home_abs="/home/agi",
    )
    assert module.benchmark_display_date(tmp_path / "missing", "already-set") == "already-set"

    module.display_log(
        "stdout",
        "stderr",
        session_state={},
        strip_ansi_fn=str,
    )
    toggle_state: dict[str, object] = {}
    module.toggle_select_all(toggle_state)
    module.update_select_all(toggle_state)
    assert toggle_state == {"all": True, "updated": True}

    preview = module.capture_dataframe_preview_state({"a": 1})
    restored: dict[str, object] = {}
    module.restore_dataframe_preview_state(restored, {"restored": 1})
    assert preview == {"preview": {"a": 1}}
    assert restored == {"restored": 1}
    assert module.is_app_installed(SimpleNamespace(ready=True)) is True
    assert module.app_install_status(SimpleNamespace(ready=True)) == {"ready": True}

    assert "update_log" in captured
    assert "append_log_lines" in captured
    assert "display_log" in captured


def test_page_helpers_looks_like_shared_path_delegates_project_root(monkeypatch, tmp_path):
    module = _load_orchestrate_page_helpers_module()
    captured = {}

    def _fake_impl(path, *, project_root):
        captured["value"] = (path, project_root)
        return True

    monkeypatch.setattr(module, "_looks_like_shared_path_impl", _fake_impl)

    candidate = tmp_path / "clustershare"
    project_root = tmp_path / "repo"

    assert module.looks_like_shared_path(candidate, project_root) is True
    assert captured["value"] == (candidate, project_root)


def test_page_helpers_import_fallback_raises_when_local_specs_are_missing():
    original_spec = importlib.util.spec_from_file_location

    with pytest.MonkeyPatch.context() as mp:
        def _page_support_missing(name, location, *args, **kwargs):
            if name == "agilab_orchestrate_page_support_fallback":
                return None
            return original_spec(name, location, *args, **kwargs)

        mp.setattr(importlib.util, "spec_from_file_location", _page_support_missing)
        with pytest.raises(ModuleNotFoundError, match="orchestrate_page_support"):
            _load_orchestrate_page_helpers_module_with_import_failures(mp, {"agilab.orchestrate_page_support"})

    with pytest.MonkeyPatch.context() as mp:
        def _support_missing(name, location, *args, **kwargs):
            if name == "agilab_orchestrate_support_fallback":
                return None
            return original_spec(name, location, *args, **kwargs)

        mp.setattr(importlib.util, "spec_from_file_location", _support_missing)
        with pytest.raises(ModuleNotFoundError, match="orchestrate_support"):
            _load_orchestrate_page_helpers_module_with_import_failures(mp, {"agilab.orchestrate_support"})


def test_orchestrate_page_support_snippet_and_mode_helpers():
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
        workers_data_path='"/tmp/share"',
        rapids_enabled=True,
        benchmark_best_single_node=True,
        run_args={"foo": "bar", "n": 2},
    )
    distrib_snippet = orchestrate_page_support.build_distribution_snippet(
        env=env,
        verbose=1,
        scheduler="None",
        workers="None",
        args_serialized="",
    )

    assert 'APP = "demo_project"' in install_snippet
    assert "modes_enabled=7" in install_snippet
    assert 'workers_data_path="/tmp/share"' in install_snippet
    assert "RunRequest(" in run_snippet
    assert "mode=15" in run_snippet
    assert 'workers_data_path="/tmp/share"' in run_snippet
    assert "rapids_enabled=True" in run_snippet
    assert "benchmark_best_single_node=True" in run_snippet
    assert 'RUN_PARAMS = json.loads(\'{"foo": "bar", "n": 2}\')' in run_snippet
    assert "get_distrib" in distrib_snippet
    assert "workers=None" in distrib_snippet
    assert ",\n        \n" not in distrib_snippet

    payload = orchestrate_page_support.serialize_args_payload(
        {"dataset": "flight/source", "limit": 5, "enabled": True}
    )
    assert payload == 'dataset="flight/source", limit=5, enabled=True'
    assert orchestrate_page_support.optional_string_expr(True, "tcp://127.0.0.1:8786") == '"tcp://127.0.0.1:8786"'
    assert orchestrate_page_support.optional_string_expr(False, "ignored") == "None"
    assert orchestrate_page_support.optional_python_expr(True, {"127.0.0.1": 1}) == "{'127.0.0.1': 1}"
    assert orchestrate_page_support.optional_python_expr(False, {"127.0.0.1": 1}) == "None"

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
    assert orchestrate_page_support.order_benchmark_display_columns(
        ["order", "mode", "nodes", "node", "variant", "seconds"]
    ) == ["order", "variant", "nodes", "node", "mode", "seconds"]


def test_orchestrate_notebook_document_exports_current_recipe():
    module = _load_orchestrate_module()
    env = SimpleNamespace(app="demo_project", target="demo")
    snippets = [
        ("INSTALL", "print('install')\n"),
        ("RUN", "print('run')"),
    ]

    document = module._orchestrate_notebook_document(env, snippets)

    assert module._orchestrate_snippet_state_key(env, "run") == "orchestrate:notebook_snippet:demo_project:run"
    assert document["nbformat"] == 4
    assert document["nbformat_minor"] == 5
    assert document["metadata"]["agilab"]["schema"] == "agilab.orchestrate_notebook.v1"
    assert document["metadata"]["agilab"]["app"] == "demo_project"
    assert document["metadata"]["agilab"]["snippet_labels"] == ["INSTALL", "RUN"]
    assert any(
        "Notebook import remains on the WORKFLOW page" in "".join(cell["source"])
        for cell in document["cells"]
    )
    code_cells = [cell for cell in document["cells"] if cell["cell_type"] == "code"]
    assert ["".join(cell["source"]) for cell in code_cells] == ["print('install')\n", "print('run')\n"]


def test_orchestrate_notebook_snippet_store_and_empty_render(monkeypatch):
    module = _load_orchestrate_module()
    fake_st = _NotebookExpanderStreamlit()
    monkeypatch.setattr(module, "st", fake_st)
    env = SimpleNamespace(target="fallback_project")

    module._store_orchestrate_notebook_snippet(env, "run", "print('run')")
    key = "orchestrate:notebook_snippet:fallback_project:run"
    assert fake_st.session_state[key] == "print('run')"

    module._store_orchestrate_notebook_snippet(env, "run", None)
    assert key not in fake_st.session_state

    module._render_orchestrate_notebook_expander(env)

    assert fake_st.expanders == [("Notebook", False)]
    assert fake_st.downloads == []
    assert fake_st.infos == [
        "No orchestration snippets are available yet. Configure INSTALL, CHECK distribute, or RUN first."
    ]


def test_orchestrate_notebook_expander_downloads_available_snippets(monkeypatch):
    module = _load_orchestrate_module()
    fake_st = _NotebookExpanderStreamlit(fail_on_info=True)
    monkeypatch.setattr(module, "st", fake_st)
    env = SimpleNamespace(app="demo_project", target="fallback")
    module._store_orchestrate_notebook_snippet(env, "install", "print('install')")
    module._store_orchestrate_notebook_snippet(env, "distribution", "")
    module._store_orchestrate_notebook_snippet(env, "run", "print('run')")

    module._render_orchestrate_notebook_expander(env)

    assert fake_st.expanders == [("Notebook", False)]
    assert len(fake_st.downloads) == 1
    label, kwargs = fake_st.downloads[0]
    assert label == "Download orchestration notebook"
    assert kwargs["file_name"] == "demo_project_orchestrate.ipynb"
    assert kwargs["mime"] == "application/x-ipynb+json"
    assert kwargs["key"] == "orchestrate:notebook_download:demo_project"

    payload = json.loads(kwargs["data"].decode("utf-8"))
    assert payload["metadata"]["agilab"]["snippet_labels"] == ["INSTALL", "RUN"]
    code_sources = [
        "".join(cell["source"])
        for cell in payload["cells"]
        if cell["cell_type"] == "code"
    ]
    assert code_sources == ["print('install')\n", "print('run')\n"]
    assert fake_st.captions[-1] == "Includes: INSTALL, RUN"


def test_orchestrate_page_support_distribution_plan_helpers():
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


def test_apply_distribution_plan_action_updates_distribution_tree_json(tmp_path):
    module = _load_orchestrate_module()
    dist_tree_path = tmp_path / "distribution_tree.json"
    dist_tree_path.write_text(
        json.dumps(
            {
                "workers": {"10.0.0.1": 1, "10.0.0.2": 1},
                "target_args": {"old": True},
                "work_plan_metadata": [[["A", 2]], [["B", 3]]],
                "work_plan": [[["a.csv"]], [["b.csv"]]],
                "keep": "unchanged",
            }
        ),
        encoding="utf-8",
    )
    workers = ["10.0.0.1-1", "10.0.0.2-1"]
    selection_key = orchestrate_page_support.workplan_selection_key("A", 0, 0)

    result = module._apply_distribution_plan_action(
        dist_tree_path=dist_tree_path,
        workers=workers,
        work_plan_metadata=[[["A", 2]], [["B", 3]]],
        work_plan=[[["a.csv"]], [["b.csv"]]],
        selections={selection_key: "10.0.0.2-1"},
        target_args={"new": "value"},
    )

    saved = json.loads(dist_tree_path.read_text(encoding="utf-8"))
    assert result.status == "success"
    assert result.title == "Distribution plan updated."
    assert saved["keep"] == "unchanged"
    assert saved["target_args"] == {"new": "value"}
    assert saved["work_plan_metadata"] == [[], [["A", 2], ["B", 3]]]
    assert saved["work_plan"] == [[], [["a.csv"], ["b.csv"]]]


def test_apply_distribution_plan_action_reports_missing_distribution_plan(tmp_path):
    module = _load_orchestrate_module()
    dist_tree_path = tmp_path / "missing.json"

    result = module._apply_distribution_plan_action(
        dist_tree_path=dist_tree_path,
        workers=["10.0.0.1-1"],
        work_plan_metadata=[[["A", 1]]],
        work_plan=[[["a.csv"]]],
        selections={},
        target_args={},
    )

    assert result.status == "error"
    assert result.title == "Distribution plan file does not exist."
    assert "CHECK distribute" in str(result.next_action)
    assert result.data["dist_tree_path"] == dist_tree_path


def test_apply_distribution_plan_action_reports_invalid_distribution_plan(tmp_path):
    module = _load_orchestrate_module()
    dist_tree_path = tmp_path / "distribution_tree.json"
    dist_tree_path.write_text("{bad json", encoding="utf-8")

    result = module._apply_distribution_plan_action(
        dist_tree_path=dist_tree_path,
        workers=["10.0.0.1-1"],
        work_plan_metadata=[[["A", 1]]],
        work_plan=[[["a.csv"]]],
        selections={},
        target_args={},
    )

    assert result.status == "error"
    assert result.title == "Distribution plan file is not valid JSON."
    assert "CHECK distribute" in str(result.next_action)


def test_apply_distribution_plan_action_reports_unserializable_payload(tmp_path):
    module = _load_orchestrate_module()
    dist_tree_path = tmp_path / "distribution_tree.json"
    original_payload = {
        "workers": {"10.0.0.1": 1},
        "target_args": {"old": True},
        "work_plan_metadata": [[["A", 1]]],
        "work_plan": [[["a.csv"]]],
    }
    dist_tree_path.write_text(json.dumps(original_payload), encoding="utf-8")

    result = module._apply_distribution_plan_action(
        dist_tree_path=dist_tree_path,
        workers=["10.0.0.1-1"],
        work_plan_metadata=[[["A", 1]]],
        work_plan=[[["a.csv"]]],
        selections={},
        target_args={"bad": object()},
    )

    assert result.status == "error"
    assert result.title == "Distribution plan could not be saved."
    assert json.loads(dist_tree_path.read_text(encoding="utf-8")) == original_payload


def test_orchestrate_page_support_log_filters_and_display_helpers():
    assert orchestrate_page_support.strip_ansi("\x1b[31merror\x1b[0m") == "error"
    assert orchestrate_page_support.is_dask_shutdown_noise("Stream is closed")
    assert orchestrate_page_support.is_dask_shutdown_noise('File "/usr/local/lib/python3.11/site-packages/distributed/comm.py", line 1')
    assert orchestrate_page_support.is_dask_shutdown_noise("Traceback (most recent call last):")

    text = "\n".join(["normal message", "StreamClosedError", "another line", "stream is closed"])
    assert orchestrate_page_support.filter_noise_lines(text) == "normal message\nanother line"

    block = "\n".join(f"line {i}" for i in range(1, 6))
    assert orchestrate_page_support.format_log_block(block, newest_first=True, max_lines=3) == "line 5\nline 4\nline 3"
    assert orchestrate_page_support.format_log_block(block, newest_first=False, max_lines=3) == "line 3\nline 4\nline 5"

    log = "\n".join(
        [
            "normal warning",
            "VIRTUAL_ENV=/tmp/.venv does not match the project environment path .venv",
            "final",
        ]
    )
    assert orchestrate_page_support.filter_warning_messages(log) == "normal warning\nfinal"
    assert not orchestrate_page_support.log_indicates_install_failure(["all good", "installation complete"])
    assert not orchestrate_page_support.log_indicates_install_failure(
        [
            "Remote command stderr: error: Permission denied (os error 13)",
            "Failed to update uv on 192.168.20.15 (skipping self update): Process exited with non-zero exit status 2",
            "None",
            "Process finished",
        ]
    )
    assert orchestrate_page_support.log_indicates_install_failure(["TRACEBACK", "Command failed with exit code 1"])
    assert orchestrate_page_support.log_indicates_install_failure(
        ["worker deploy failed: Process exited with non-zero exit status 2"]
    )

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

    warnings: list[str] = []
    errors: list[str] = []
    code_sink = _CaptureCodeSink()
    orchestrate_page_support.display_log(
        stdout="normal output\nwarning: deprecated option\n",
        stderr="",
        session_state={},
        strip_ansi_fn=orchestrate_page_support.strip_ansi,
        filter_warning_messages_fn=lambda value: value,
        format_log_block_fn=lambda value: value,
        warning_fn=warnings.append,
        error_fn=errors.append,
        code_fn=code_sink,
        log_display_height=300,
    )
    assert warnings == ["Warnings occurred during cluster installation:"]
    assert errors == []

    warnings.clear()
    errors.clear()
    code_sink = _CaptureCodeSink()
    orchestrate_page_support.display_log(
        stdout="",
        stderr="something failed",
        session_state={"log_text": "fallback log"},
        strip_ansi_fn=orchestrate_page_support.strip_ansi,
        filter_warning_messages_fn=lambda value: value,
        format_log_block_fn=lambda value: value,
        warning_fn=warnings.append,
        error_fn=errors.append,
        code_fn=code_sink,
        log_display_height=300,
    )
    assert warnings == []
    assert errors == ["Errors occurred during cluster installation:"]
    assert code_sink.calls[-1][0][0] == "something failed"


def test_orchestrate_page_support_dataframe_state_helpers():
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

    select_state: dict[str, object] = {
        "df_cols": ["a", "b", "c"],
        "selected_cols": ["a"],
        "check_all": False,
    }
    orchestrate_page_support.toggle_select_all(select_state)
    assert select_state["selected_cols"] == []
    select_state["check_all"] = True
    orchestrate_page_support.toggle_select_all(select_state)
    assert select_state["selected_cols"] == ["a", "b", "c"]
    select_state.update({"export_col_0": True, "export_col_1": True, "export_col_2": False})
    orchestrate_page_support.update_select_all(select_state)
    assert select_state["check_all"] is False
    assert select_state["selected_cols"] == ["a", "b"]


def test_orchestrate_page_support_additional_edge_branches(tmp_path):
    assert orchestrate_page_support.is_dask_shutdown_noise("") is False
    assert orchestrate_page_support.is_dask_shutdown_noise(
        "The above exception was the direct cause of the following exception:"
    ) is True
    assert orchestrate_page_support.is_dask_shutdown_noise("Traceback") is True
    assert orchestrate_page_support.format_log_block("", newest_first=False, max_lines=3) == ""
    assert orchestrate_page_support.describe_run_mode(-1, False) == "Run mode unknown"
    snippet = orchestrate_page_support.build_distribution_snippet(
        env=SimpleNamespace(apps_path="/tmp/apps", app="demo_project"),
        verbose=1,
        scheduler='"127.0.0.1:8786"',
        workers="{'127.0.0.1': 1}",
        args_serialized='foo="bar"',
    )
    assert 'foo="bar"' in snippet

    metadata, plan = orchestrate_page_support.reassign_distribution_plan(
        workers=["10.0.0.1-1"],
        work_plan_metadata=[[("A", 1)], [("B", 2)]],
        work_plan=[[["a.csv"]], [["b.csv"]]],
        selections={
            orchestrate_page_support.workplan_selection_key("B", 1, 0): "missing-worker",
        },
    )
    assert metadata == [[("A", 1)]]
    assert plan == [[["a.csv"]]]

    buffer: list[str] = []
    orchestrate_page_support.append_log_lines(
        buffer,
        "first\n\nsecond",
        cluster_verbose=2,
        traceback_state={"active": False},
    )
    assert buffer == ["first", "second"]

    trace_state = {"active": True}
    sink = _CaptureCodeSink()
    session_state = {"log_text": "before\n"}
    orchestrate_page_support.update_log(
        session_state,
        sink,
        "",
        max_lines=10,
        cluster_verbose=1,
        traceback_state=trace_state,
        strip_ansi_fn=orchestrate_page_support.strip_ansi,
        is_dask_shutdown_noise_fn=orchestrate_page_support.is_dask_shutdown_noise,
        log_display_max_lines=5,
        live_log_min_height=100,
    )
    assert trace_state["active"] is False
    orchestrate_page_support.update_log(
        session_state,
        sink,
        "Traceback (most recent call last):",
        max_lines=10,
        cluster_verbose=1,
        traceback_state=trace_state,
        strip_ansi_fn=orchestrate_page_support.strip_ansi,
        is_dask_shutdown_noise_fn=orchestrate_page_support.is_dask_shutdown_noise,
        log_display_max_lines=5,
        live_log_min_height=100,
    )
    assert trace_state["active"] is True
    orchestrate_page_support.update_log(
        session_state,
        sink,
        "StreamClosedError",
        max_lines=10,
        cluster_verbose=1,
        traceback_state={"active": False},
        strip_ansi_fn=orchestrate_page_support.strip_ansi,
        is_dask_shutdown_noise_fn=orchestrate_page_support.is_dask_shutdown_noise,
        log_display_max_lines=5,
        live_log_min_height=100,
    )
    assert session_state["log_text"] == "before\n"

    code_sink = _CaptureCodeSink()
    orchestrate_page_support.display_log(
        stdout="",
        stderr="",
        session_state={},
        strip_ansi_fn=orchestrate_page_support.strip_ansi,
        filter_warning_messages_fn=lambda value: value,
        format_log_block_fn=lambda value: value,
        warning_fn=lambda _message: None,
        error_fn=lambda _message: None,
        code_fn=code_sink,
        log_display_height=250,
    )
    assert code_sink.calls[-1][0][0] == "No logs available"

    session_state = {"log_text": "busy"}
    orchestrate_page_support.clear_log(session_state)
    assert session_state["log_text"] == ""

    orchestrate_page_support.clear_cached_distribution(lambda: None)
    orchestrate_page_support.clear_mount_table_cache(object())
    stamped = tmp_path / "benchmark.txt"
    stamped.write_text("x", encoding="utf-8")
    assert orchestrate_page_support.benchmark_display_date(stamped, "preset") == "preset"
    auto_date = orchestrate_page_support.benchmark_display_date(stamped, "")
    assert auto_date
    assert auto_date.count(":") == 2
    assert orchestrate_page_support.benchmark_display_date(tmp_path / "missing", "") == ""
    assert orchestrate_page_support.log_indicates_install_failure([]) is False

    restored = {
        "export_col_0": True,
        "loaded_graph": "stale",
        "loaded_source_path": "stale",
    }
    orchestrate_page_support.restore_dataframe_preview_state(restored, {})
    assert "loaded_graph" not in restored
    assert "loaded_source_path" not in restored
    assert "export_col_0" not in restored
    assert restored["selected_cols"] == []

    toggle_state = {"check_all": False, "df_cols": ["a", "b"]}
    orchestrate_page_support.toggle_select_all(toggle_state)
    assert toggle_state["selected_cols"] == []

    update_state = {"df_cols": "oops", "export_col_0": True}
    orchestrate_page_support.update_select_all(update_state)
    assert update_state["check_all"] is True
    assert update_state["selected_cols"] == []


def test_update_delete_confirm_state_sets_and_clears_flag(monkeypatch):
    module = _load_orchestrate_module()
    fake_st = SimpleNamespace(session_state={})
    monkeypatch.setattr(module, "st", fake_st)

    rerun_needed = module._update_delete_confirm_state(
        "delete_key",
        delete_armed_clicked=True,
        delete_cancel_clicked=False,
    )
    assert rerun_needed is True
    assert fake_st.session_state["delete_key"] is True

    rerun_needed = module._update_delete_confirm_state(
        "delete_key",
        delete_armed_clicked=False,
        delete_cancel_clicked=True,
    )
    assert rerun_needed is True
    assert "delete_key" not in fake_st.session_state

    rerun_needed = module._update_delete_confirm_state(
        "delete_key",
        delete_armed_clicked=False,
        delete_cancel_clicked=False,
    )
    assert rerun_needed is False


def test_is_app_installed_requires_manager_and_worker_venvs():
    module = _load_orchestrate_module()

    def seed_fake_venv(venv: Path, *modules: str) -> None:
        python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        python.parent.mkdir(parents=True, exist_ok=True)
        python.write_text("# fake python for install status test\n", encoding="utf-8")
        if os.name == "nt":
            site_packages = venv / "Lib" / "site-packages"
        else:
            site_packages = venv / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
        site_packages.mkdir(parents=True, exist_ok=True)
        for module_name in modules:
            package_dir = site_packages / module_name
            package_dir.mkdir(parents=True, exist_ok=True)
            (package_dir / "__init__.py").write_text("", encoding="utf-8")
            if module_name == "agi_cluster":
                distributor_dir = package_dir / "agi_distributor"
                distributor_dir.mkdir(parents=True, exist_ok=True)
                (distributor_dir / "__init__.py").write_text("class StageRequest: ...\n", encoding="utf-8")

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        active_app = root / "flight_trajectory_project"
        worker_root = root / "wenv" / "flight_trajectory_worker"
        active_app.mkdir(parents=True)
        worker_root.mkdir(parents=True)

        env = SimpleNamespace(active_app=active_app, wenv_abs=worker_root)

        status = module._app_install_status(env)
        assert status["manager_ready"] is False
        assert status["worker_ready"] is False
        assert module._is_app_installed(env) is False

        seed_fake_venv(active_app / ".venv", "agi_env", "agi_node", "agi_cluster")
        status = module._app_install_status(env)
        assert status["manager_ready"] is True
        assert status["worker_ready"] is False
        assert module._is_app_installed(env) is False

        seed_fake_venv(worker_root / ".venv", "agi_env", "agi_node")
        status = module._app_install_status(env)
        assert status["manager_ready"] is True
        assert status["worker_ready"] is True
        assert module._is_app_installed(env) is True


def test_install_status_warning_skips_first_launch_missing_manager(tmp_path: Path):
    module = _load_orchestrate_module()
    install_status = {
        "manager_ready": False,
        "worker_ready": True,
        "manager_exists": False,
        "worker_exists": True,
        "manager_problem": f"environment path does not exist: {tmp_path / 'flight_telemetry_project' / '.venv'}",
        "worker_problem": "",
    }

    assert module._install_status_warning_message(install_status) is None
    label, caption = module._runtime_status_label(install_status)
    assert label == "Needs INSTALL"
    assert caption == "Manager environment has not been created yet. Run INSTALL before RUN."


def test_install_status_warning_reports_existing_stale_environment():
    module = _load_orchestrate_module()
    install_status = {
        "manager_ready": False,
        "worker_ready": True,
        "manager_exists": True,
        "worker_exists": True,
        "manager_problem": "missing modules: agi_cluster",
        "worker_problem": "",
    }

    warning = module._install_status_warning_message(install_status)
    assert warning is not None
    assert "Environment install is incomplete or stale" in warning
    assert "missing modules: agi_cluster" in warning
    label, caption = module._runtime_status_label(install_status)
    assert label == "Needs INSTALL"
    assert caption == "missing modules: agi_cluster"


def test_set_active_app_query_param_ignores_streamlit_api_errors(monkeypatch):
    module = _load_orchestrate_module()

    class _BrokenQueryParams(dict):
        def __setitem__(self, key, value):
            raise StreamlitAPIException("no runtime")

    monkeypatch.setattr(module, "st", SimpleNamespace(query_params=_BrokenQueryParams()))

    module._set_active_app_query_param("demo_project")


def test_clear_cached_distribution_calls_clear_when_available():
    module = _load_orchestrate_module()
    called = {"count": 0}
    module.load_distribution.clear = lambda: called.__setitem__("count", called["count"] + 1)

    module._clear_cached_distribution()

    assert called["count"] == 1


@pytest.mark.asyncio
async def test_check_distribution_action_reports_success_and_uses_controller_runtime(tmp_path: Path):
    module = _load_orchestrate_module()
    controller_root = tmp_path / "controller"
    project_path = tmp_path / "project"
    captured: dict[str, object] = {}

    async def _run_agi(cmd, log_callback=None, venv=None):
        captured["cmd"] = cmd
        captured["venv"] = venv
        log_callback("building distribution")
        return "distribution ready", ""

    env = SimpleNamespace(
        run_agi=_run_agi,
        snippet_tail="pass",
        is_source_env=True,
        is_worker_env=False,
        agi_cluster=controller_root,
    )

    result = await module._check_distribution_action(
        env,
        cmd="asyncio.run(main())",
        project_path=project_path,
    )

    assert result.status == "success"
    assert result.title == "Distribution built successfully."
    assert captured == {"cmd": "pass", "venv": controller_root}
    assert result.data["runtime_root"] == controller_root
    assert result.data["dist_log"] == ("building distribution", "distribution ready")


@pytest.mark.asyncio
async def test_check_distribution_action_accepts_stderr_when_process_succeeds(tmp_path: Path):
    module = _load_orchestrate_module()
    project_path = tmp_path / "project"
    captured: dict[str, object] = {}

    async def _run_agi(cmd, log_callback=None, venv=None):
        captured["cmd"] = cmd
        captured["venv"] = venv
        log_callback("building distribution")
        return "partial output", "worker failed"

    env = SimpleNamespace(
        run_agi=_run_agi,
        snippet_tail="pass",
        is_source_env=False,
        is_worker_env=False,
    )

    result = await module._check_distribution_action(
        env,
        cmd="asyncio.run(main())",
        project_path=project_path,
    )

    assert result.status == "success"
    assert result.title == "Distribution built successfully."
    assert result.detail is None
    assert captured == {"cmd": "pass", "venv": project_path}
    assert result.data["runtime_root"] == project_path
    assert result.data["stderr"] == "worker failed"
    assert result.data["dist_log"] == (
        "building distribution",
        "worker failed",
        "partial output",
    )


@pytest.mark.asyncio
async def test_check_distribution_action_prefers_controller_runtime_when_available(tmp_path: Path):
    module = _load_orchestrate_module()
    controller_root = tmp_path / "controller"
    project_path = tmp_path / "project"
    captured: dict[str, object] = {}

    async def _run_agi(cmd, log_callback=None, venv=None):
        captured["cmd"] = cmd
        captured["venv"] = venv
        log_callback("building distribution")
        return "distribution ready", ""

    env = SimpleNamespace(
        run_agi=_run_agi,
        snippet_tail="pass",
        is_source_env=False,
        is_worker_env=False,
        agi_cluster=controller_root,
    )

    result = await module._check_distribution_action(
        env,
        cmd="asyncio.run(main())",
        project_path=project_path,
    )

    assert result.status == "success"
    assert captured == {"cmd": "pass", "venv": controller_root}
    assert result.data["runtime_root"] == controller_root


@pytest.mark.asyncio
async def test_check_distribution_action_accepts_noisy_stderr_logs(tmp_path: Path):
    module = _load_orchestrate_module()
    project_path = tmp_path / "project"
    stderr_log = "\n".join(
        [
            "flight_telemetry_project.runtime_misc_support.initialize_runtime_state AGI instance created for target flight with verbosity 1",
            "WARNING: Cache entry deserialization failed, entry ignored",
            "flight_telemetry_project.execution_support.run @python3.13: export PATH=\"~/.local/bin:$PATH\";uv --quiet run --no-sync python '/Users/agi/wenv/cli.py' kill 92836",
            "flight_telemetry_project.runtime_distribution_support.run_local debug=False",
            "flight_telemetry_project.execution_support.run_async Executing in /Users/agi/wenv/flight_worker: uv --quiet run --preview-features python-upgrade --no-sync --project /Users/agi/wenv/flight_worker --python 3.13.13 python -c \"from pathlib import Path",
            "from agi_env import AgiEnv",
            "from agi_node.agi_dispatcher import  BaseWorker",
            "import asyncio",
            "async def main():",
            "  env = AgiEnv(apps_path=Path('/Users/agi/PycharmProjects/agilab/src/agilab/apps/builtin'), app='flight_telemetry_project', verbose=1)",
            "  BaseWorker._new(env=env, mode=48, verbose=1, args={'data_source': 'file', 'data_in': 'flight/dataset', 'data_out': 'flight/dataframe', 'files': '*', 'nfile': 1, 'nskip': 0, 'nread': 0, 'sampling_rate': 1.0, 'datemin': '2020-01-01', 'datemax': '2021-01-01', 'output_format': 'parquet', 'reset_target': False})",
            "  res = await BaseWorker._run(env=env, mode=48, workers={'127.0.0.1': 2}, args={'data_source': 'file', 'data_in': 'flight/dataset', 'data_out': 'flight/dataframe', 'files': '*', 'nfile': 1, 'nskip': 0, 'nread': 0, 'sampling_rate': 1.0, 'datemin': '2020-01-01', 'datemax': '2021-01-01', 'output_format': 'parquet', 'reset_target': False})",
            "  print(res)",
            "if __name__ == '__main__':",
            "  asyncio.run(main())\"",
        ]
    )

    async def _run_agi(cmd, log_callback=None, venv=None):
        log_callback("building distribution")
        return "None", stderr_log

    env = SimpleNamespace(
        run_agi=_run_agi,
        snippet_tail="pass",
        is_source_env=False,
        is_worker_env=False,
    )

    result = await module._check_distribution_action(
        env,
        cmd="asyncio.run(main())",
        project_path=project_path,
    )

    assert result.status == "success"
    assert result.title == "Distribution built successfully."
    assert result.data["stderr"] == stderr_log
    assert result.data["dist_log"] == ("building distribution", *stderr_log.splitlines(), "None")


@pytest.mark.asyncio
async def test_check_distribution_action_reports_run_exception(tmp_path: Path):
    module = _load_orchestrate_module()

    async def _run_agi(_cmd, log_callback=None, venv=None):
        raise RuntimeError("cluster unavailable")

    env = SimpleNamespace(
        run_agi=_run_agi,
        snippet_tail="pass",
        is_source_env=False,
        is_worker_env=False,
    )

    result = await module._check_distribution_action(
        env,
        cmd="asyncio.run(main())",
        project_path=tmp_path / "project",
    )

    assert result.status == "error"
    assert result.title == "Distribution build failed."
    assert result.detail == "cluster unavailable"
    assert result.data["dist_log"] == ("ERROR: cluster unavailable",)


@pytest.mark.asyncio
async def test_install_worker_action_reports_success(tmp_path: Path):
    module = _load_orchestrate_module()
    captured: dict[str, object] = {}
    local_log = ["=== Install request ==="]

    async def _run_agi(cmd, log_callback=None, venv=None):
        captured["cmd"] = cmd
        captured["venv"] = venv
        log_callback("installing worker")
        return "None\nProcess finished", ""

    env = SimpleNamespace(run_agi=_run_agi)

    result = await module._install_worker_action(
        env,
        install_command="install command",
        venv=tmp_path,
        local_log=local_log,
    )

    assert result.status == "success"
    assert result.title == "Cluster installation completed."
    assert captured == {"cmd": "install command", "venv": None}
    assert result.data["stdout"] == "None\nProcess finished"
    assert result.data["stderr"] == ""
    assert result.data["venv"] == tmp_path
    assert result.data["install_log"] == (
        "=== Install request ===",
        "installing worker",
        "None",
        "Process finished",
        "✅ Install complete.",
    )


@pytest.mark.asyncio
async def test_install_worker_action_reports_success_with_empty_output(tmp_path: Path):
    module = _load_orchestrate_module()
    local_log: list[str] = []

    async def _run_agi(_cmd, log_callback=None, venv=None):
        return "", ""

    env = SimpleNamespace(run_agi=_run_agi)

    result = await module._install_worker_action(
        env,
        install_command="install command",
        venv=tmp_path,
        local_log=local_log,
    )

    assert result.status == "success"
    assert result.title == "Cluster installation completed."
    assert result.detail is None
    assert result.data["install_log"] == ("✅ Install complete.",)


@pytest.mark.asyncio
async def test_install_worker_action_allows_benign_returned_stderr(tmp_path: Path):
    module = _load_orchestrate_module()
    local_log: list[str] = []

    async def _run_agi(_cmd, log_callback=None, venv=None):
        return "", "warning: package manager wrote a non-fatal warning to stderr"

    env = SimpleNamespace(run_agi=_run_agi)

    result = await module._install_worker_action(
        env,
        install_command="install command",
        venv=tmp_path,
        local_log=local_log,
    )

    assert result.status == "success"
    assert result.title == "Cluster installation completed."
    assert result.detail is None
    assert result.data["stderr"] == "warning: package manager wrote a non-fatal warning to stderr"
    assert result.data["install_log"] == (
        "warning: package manager wrote a non-fatal warning to stderr",
        "✅ Install complete.",
    )


@pytest.mark.asyncio
async def test_install_worker_action_reports_fatal_returned_stderr(tmp_path: Path):
    module = _load_orchestrate_module()
    local_log: list[str] = []

    async def _run_agi(_cmd, log_callback=None, venv=None):
        return "", "RuntimeError: Command failed with exit code 1"

    env = SimpleNamespace(run_agi=_run_agi)

    result = await module._install_worker_action(
        env,
        install_command="install command",
        venv=tmp_path,
        local_log=local_log,
    )

    assert result.status == "error"
    assert result.title == "Cluster installation failed."
    assert result.detail == "RuntimeError: Command failed with exit code 1"
    assert result.data["install_log"] == (
        "RuntimeError: Command failed with exit code 1",
        "❌ Install finished with errors. Check logs above.",
    )


@pytest.mark.asyncio
async def test_install_worker_action_allows_benign_worker_stderr_log(tmp_path: Path):
    module = _load_orchestrate_module()
    local_log: list[str] = []

    async def _run_agi(_cmd, log_callback=None, venv=None):
        log_callback("Remote command stderr: error: Permission denied (os error 13)")
        log_callback(
            "Failed to update uv on 192.168.20.15 (skipping self update): "
            "Process exited with non-zero exit status 2"
        )
        return "done", ""

    env = SimpleNamespace(run_agi=_run_agi)

    result = await module._install_worker_action(
        env,
        install_command="install command",
        venv=tmp_path,
        local_log=local_log,
    )

    assert result.status == "success"
    assert result.title == "Cluster installation completed."
    assert result.detail is None
    assert result.data["stderr"] == ""
    assert result.data["install_log"] == (
        "Remote command stderr: error: Permission denied (os error 13)",
        "Failed to update uv on 192.168.20.15 (skipping self update): "
        "Process exited with non-zero exit status 2",
        "done",
        "✅ Install complete.",
    )


@pytest.mark.asyncio
async def test_install_worker_action_reports_log_detected_failure(tmp_path: Path):
    module = _load_orchestrate_module()
    local_log: list[str] = []

    async def _run_agi(_cmd, log_callback=None, venv=None):
        log_callback("TRACEBACK")
        log_callback("RuntimeError: Command failed with exit code 1")
        return "", ""

    env = SimpleNamespace(run_agi=_run_agi)

    result = await module._install_worker_action(
        env,
        install_command="install command",
        venv=tmp_path,
        local_log=local_log,
    )

    assert result.status == "error"
    assert result.detail == "Detected install failure in logs."
    assert "rerun INSTALL" in str(result.next_action)


@pytest.mark.asyncio
async def test_install_worker_action_reports_run_exception(tmp_path: Path):
    module = _load_orchestrate_module()
    local_log: list[str] = []

    async def _run_agi(_cmd, log_callback=None, venv=None):
        raise RuntimeError("uv missing")

    env = SimpleNamespace(run_agi=_run_agi)

    result = await module._install_worker_action(
        env,
        install_command="install command",
        venv=tmp_path,
        local_log=local_log,
    )

    assert result.status == "error"
    assert result.detail == "uv missing"
    assert result.data["install_log"] == (
        "ERROR: uv missing",
        "❌ Install finished with errors. Check logs above.",
    )


def test_clear_mount_table_cache_calls_cache_clear_when_available(monkeypatch):
    module = _load_orchestrate_module()
    called = {"count": 0}
    monkeypatch.setattr(module, "_mount_table", SimpleNamespace(cache_clear=lambda: called.__setitem__("count", called["count"] + 1)))

    module._clear_mount_table_cache()

    assert called["count"] == 1


def test_resolve_share_candidate_falls_back_when_resolve_fails(monkeypatch):
    module = _load_orchestrate_module()

    class _BrokenPath(PosixPath):

        def resolve(self, strict=False):
            raise OSError("broken link")

    monkeypatch.setattr(module, "Path", _BrokenPath)

    resolved = module._resolve_share_candidate("clustershare", "/home/agi")

    assert str(resolved) == "/home/agi/clustershare"


def test_app_args_env_uses_cluster_share_instead_of_stale_local_share(tmp_path):
    module = _load_orchestrate_module()
    local_share = tmp_path / "localshare" / "agi"
    cluster_share = tmp_path / "clustershare" / "agi"
    local_share.mkdir(parents=True)
    cluster_share.mkdir(parents=True)
    env = SimpleNamespace(
        home_abs=tmp_path,
        agi_share_path=Path("localshare/agi"),
        agi_share_path_abs=local_share,
        AGI_LOCAL_SHARE=str(local_share),
        AGI_CLUSTER_SHARE=str(cluster_share),
        envars={},
        share_root_path=lambda: local_share,
    )

    args_env = module._app_args_env_for_cluster(
        env,
        {
            "cluster_enabled": True,
            "workers_data_path": str(local_share),
        },
    )

    assert args_env is not env
    assert args_env.share_root_path() == cluster_share
    assert args_env.agi_share_path == cluster_share
    assert args_env.agi_share_path_abs == cluster_share
    assert args_env.resolve_share_path("flight/dataset") == cluster_share / "flight/dataset"
    assert args_env.envars["AGI_CLUSTER_SHARE"] == str(cluster_share)


def test_cluster_args_share_warning_accepts_configured_cluster_share(tmp_path):
    module = _load_orchestrate_module()
    local_share = tmp_path / "localshare" / "agi"
    cluster_share = tmp_path / "clustershare" / "agi"
    local_share.mkdir(parents=True)
    cluster_share.mkdir(parents=True)
    env = SimpleNamespace(
        home_abs=tmp_path,
        agi_share_path=Path("localshare/agi"),
        AGI_LOCAL_SHARE=str(local_share),
        AGI_CLUSTER_SHARE=str(cluster_share),
        envars={},
    )

    warning = module._cluster_args_share_warning(
        env,
        {
            "cluster_enabled": True,
            "workers_data_path": str(cluster_share),
        },
    )

    assert warning is None


def test_cluster_args_share_warning_accepts_sshfs_contract_with_local_scheduler_source(monkeypatch, tmp_path):
    module = _load_orchestrate_module()
    monkeypatch.setattr(module, "_looks_like_shared_path", lambda _path: False)
    monkeypatch.setattr(module, "_fstype_for_path", lambda _path: "apfs")
    local_share = tmp_path / "localshare" / "agi"
    scheduler_share = tmp_path / "clustershare" / "agi"
    local_share.mkdir(parents=True)
    scheduler_share.mkdir(parents=True)
    env = SimpleNamespace(
        home_abs=tmp_path,
        agi_share_path=Path("localshare/agi"),
        AGI_LOCAL_SHARE=str(local_share),
        AGI_CLUSTER_SHARE=str(scheduler_share),
        envars={},
    )

    warning = module._cluster_args_share_warning(
        env,
        {
            "cluster_enabled": True,
            "workers_data_path": "/home/agi/clustershare/agi",
            "workers": {"192.168.20.130": 1},
        },
    )

    assert warning is None


def test_cluster_args_share_warning_accepts_local_cluster_on_local_filesystem(monkeypatch, tmp_path):
    module = _load_orchestrate_module()
    monkeypatch.setattr(module, "_looks_like_shared_path", lambda _path: False)
    monkeypatch.setattr(module, "_fstype_for_path", lambda _path: "apfs")
    local_share = tmp_path / "localshare" / "agi"
    scheduler_share = tmp_path / "clustershare" / "agi"
    local_share.mkdir(parents=True)
    scheduler_share.mkdir(parents=True)
    env = SimpleNamespace(
        home_abs=tmp_path,
        agi_share_path=Path("localshare/agi"),
        AGI_LOCAL_SHARE=str(local_share),
        AGI_CLUSTER_SHARE=str(scheduler_share),
        envars={},
    )

    warning = module._cluster_args_share_warning(
        env,
        {
            "cluster_enabled": True,
            "workers_data_path": "/home/agi/clustershare/agi",
            "workers": {"127.0.0.1": 2},
        },
    )

    assert warning is None


def test_cluster_args_share_warning_accepts_cluster_share_as_active_share_path(monkeypatch, tmp_path):
    module = _load_orchestrate_module()
    monkeypatch.setattr(module, "_looks_like_shared_path", lambda _path: False)
    monkeypatch.setattr(module, "_fstype_for_path", lambda _path: "apfs")
    local_share = tmp_path / "localshare" / "agi"
    scheduler_share = tmp_path / "clustershare" / "agi"
    local_share.mkdir(parents=True)
    scheduler_share.mkdir(parents=True)
    env = SimpleNamespace(
        home_abs=tmp_path,
        agi_share_path=scheduler_share,
        agi_share_path_abs=scheduler_share,
        AGI_LOCAL_SHARE=str(local_share),
        AGI_CLUSTER_SHARE=str(scheduler_share),
        envars={
            "AGI_LOCAL_SHARE": str(local_share),
            "AGI_CLUSTER_SHARE": str(scheduler_share),
        },
    )

    warning = module._cluster_args_share_warning(
        env,
        {
            "cluster_enabled": True,
            "workers_data_path": str(scheduler_share),
            "workers": {"192.168.20.130": 1},
        },
    )

    assert warning is None


def test_cluster_args_share_warning_rejects_cluster_share_that_points_to_local_share(monkeypatch, tmp_path):
    module = _load_orchestrate_module()
    monkeypatch.setattr(module, "_looks_like_shared_path", lambda _path: False)
    monkeypatch.setattr(module, "_fstype_for_path", lambda _path: "apfs")
    local_share = tmp_path / "localshare" / "agi"
    local_share.mkdir(parents=True)
    env = SimpleNamespace(
        home_abs=tmp_path,
        agi_share_path=Path("localshare/agi"),
        AGI_LOCAL_SHARE=str(local_share),
        AGI_CLUSTER_SHARE=str(local_share),
        envars={},
    )

    warning = module._cluster_args_share_warning(
        env,
        {
            "cluster_enabled": True,
            "workers_data_path": "/home/agi/clustershare/agi",
            "workers": {"192.168.20.130": 1},
        },
    )

    assert warning is not None
    assert "worker-side SSHFS/shared mount target" in warning


def test_cluster_args_share_warning_reports_stale_local_workers_path(monkeypatch, tmp_path):
    module = _load_orchestrate_module()
    monkeypatch.setattr(module, "_looks_like_shared_path", lambda _path: False)
    local_share = tmp_path / "localshare" / "agi"
    local_share.mkdir(parents=True)
    env = SimpleNamespace(
        home_abs=tmp_path,
        agi_share_path=Path("localshare/agi"),
        AGI_LOCAL_SHARE=str(local_share),
        AGI_CLUSTER_SHARE="",
        envars={},
    )

    warning = module._cluster_args_share_warning(
        env,
        {
            "cluster_enabled": True,
            "workers_data_path": str(local_share),
            "workers": {"192.168.20.130": 1},
        },
    )

    assert warning is not None
    assert "appears local" in warning
    assert "worker-side SSHFS/shared mount target" in warning
    assert str(local_share) in warning


def test_benchmark_display_date_uses_mtime_fallback(tmp_path: Path, monkeypatch):
    module = _load_orchestrate_module()
    benchmark = tmp_path / "benchmark.json"
    benchmark.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(os.path, "getmtime", lambda _path: 0)

    date_value = module._benchmark_display_date(benchmark, "")

    assert date_value == module.datetime.fromtimestamp(0).strftime("%Y-%m-%d %H:%M:%S")


def test_benchmark_display_date_returns_empty_string_when_stat_fails(tmp_path: Path, monkeypatch):
    module = _load_orchestrate_module()
    benchmark = tmp_path / "benchmark.json"
    benchmark.write_text("{}", encoding="utf-8")

    def _raise_stat(_path):
        raise OSError("missing")

    monkeypatch.setattr(os.path, "getmtime", _raise_stat)

    date_value = module._benchmark_display_date(benchmark, "")

    assert date_value == ""


def test_benchmark_display_date_imports_os_when_not_provided(tmp_path: Path, monkeypatch):
    module = _load_orchestrate_page_helpers_module()
    benchmark = tmp_path / "benchmark.json"
    benchmark.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("os.path.getmtime", lambda _path: 0)

    assert module.benchmark_display_date(benchmark, "") == module.datetime.fromtimestamp(0).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
