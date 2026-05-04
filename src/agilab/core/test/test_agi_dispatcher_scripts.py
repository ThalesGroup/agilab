import os
import builtins
import json
import runpy
import shutil
import subprocess
import sys
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import py7zr
import pytest

from agi_node.agi_dispatcher import build as build_mod
from agi_node.agi_dispatcher import cython_type_preprocess as type_preprocess_mod
from agi_node.agi_dispatcher import post_install as post_mod
from agi_node.agi_dispatcher import pre_install as pre_mod


@pytest.fixture(autouse=True)
def _restore_cwd_after_build_script_tests():
    original_cwd = Path.cwd()
    try:
        yield
    finally:
        os.chdir(original_cwd)


def test_pre_install_get_decorator_name_variants():
    tree = pre_mod.parso.parse("@alpha\n@beta(1)\ndef func():\n    return 1\n")
    decorated = tree.children[0]
    decorators = decorated.children[0].children
    assert pre_mod.get_decorator_name(decorators[0]) == "alpha"
    assert pre_mod.get_decorator_name(decorators[1]) == "beta"


def test_pre_install_get_decorator_name_falls_back_to_raw_code():
    decorator = SimpleNamespace(children=[], get_code=lambda: "@fallback")

    assert pre_mod.get_decorator_name(decorator) == "@fallback"


def test_pre_install_get_decorator_name_falls_back_for_empty_atom_expr_and_unknown_expr():
    atom_expr = SimpleNamespace(
        type="atom_expr",
        children=[SimpleNamespace(type="operator", value="@")],
    )
    unknown_expr = SimpleNamespace(type="trailer")

    atom_decorator = SimpleNamespace(children=[None, atom_expr], get_code=lambda: "@atom_fallback")
    unknown_decorator = SimpleNamespace(children=[None, unknown_expr], get_code=lambda: "@unknown_fallback")

    assert pre_mod.get_decorator_name(atom_decorator) == "@atom_fallback"
    assert pre_mod.get_decorator_name(unknown_decorator) == "@unknown_fallback"


def test_pre_install_remove_decorators_by_name():
    source = "@keep\n@drop\ndef func():\n    return 1\n"
    out = pre_mod.remove_decorators(source, decorator_names=["drop"], verbose=False)
    assert "@drop" not in out
    assert "@keep" in out
    assert "def func" in out


def test_pre_install_process_decorators_handles_missing_parent_entry(monkeypatch):
    decorator = SimpleNamespace(parent=SimpleNamespace(children=[]))
    node = SimpleNamespace(
        type="funcdef",
        name=SimpleNamespace(value="demo"),
        get_decorators=lambda: [decorator],
    )
    logs = []

    monkeypatch.setattr(pre_mod, "get_decorator_name", lambda _decorator: "drop")
    monkeypatch.setattr(pre_mod.AgiEnv, "log_info", staticmethod(logs.append))

    pre_mod.process_decorators(node, ["drop"], verbose=False)

    assert any("not found in parent's children" in line for line in logs)


def test_pre_install_process_decorators_removes_following_newline(monkeypatch):
    newline = SimpleNamespace(type="newline")
    decorator = SimpleNamespace()
    parent = SimpleNamespace(children=[decorator, newline])
    decorator.parent = parent
    node = SimpleNamespace(
        type="funcdef",
        name=SimpleNamespace(value="demo"),
        get_decorators=lambda: [decorator],
    )

    monkeypatch.setattr(pre_mod, "get_decorator_name", lambda _decorator: "drop")
    monkeypatch.setattr(pre_mod.AgiEnv, "log_info", staticmethod(lambda *_args, **_kwargs: None))

    pre_mod.process_decorators(node, ["drop"], verbose=False)

    assert parent.children == []


def test_pre_install_remove_decorators_defaults_and_verbose_logging(monkeypatch):
    logs = []
    monkeypatch.setattr(pre_mod.AgiEnv, "log_info", staticmethod(logs.append))

    out = pre_mod.remove_decorators("def func():\n    return 1\n", decorator_names=None, verbose=3)

    assert out.startswith("def func")
    assert any("Processing funcdef 'func'" in line for line in logs)


def test_pre_install_prepare_for_cython_writes_pyx(tmp_path, monkeypatch):
    worker_py = tmp_path / "demo_worker.py"
    worker_py.write_text("value = 1\n", encoding="utf-8")

    monkeypatch.setattr(
        pre_mod,
        "remove_decorators",
        lambda source, verbose=True: source.replace("value", "prepared"),
    )
    args = Namespace(
        worker_path=str(worker_py),
        cython_target_src_ext=".py",
        type_preprocess=False,
        verbose=False,
    )
    pre_mod.prepare_for_cython(args)

    pyx_path = worker_py.with_suffix(".pyx")
    assert pyx_path.exists()
    assert "prepared = 1" in pyx_path.read_text(encoding="utf-8")


def test_pre_install_prepare_for_cython_can_type_preprocess(tmp_path, monkeypatch):
    worker_py = tmp_path / "demo_worker.py"
    worker_py.write_text(
        "def run(values):\n"
        "    total = 0.0\n"
        "    for i in range(len(values)):\n"
        "        total += 1.0\n"
        "    return total\n",
        encoding="utf-8",
    )
    logs = []
    monkeypatch.setattr(pre_mod.AgiEnv, "log_info", staticmethod(logs.append))

    pre_mod.prepare_for_cython(
        Namespace(
            worker_path=str(worker_py),
            cython_target_src_ext=".py",
            type_preprocess=True,
            verbose=False,
        )
    )

    pyx_text = worker_py.with_suffix(".pyx").read_text(encoding="utf-8")
    assert "cdef Py_ssize_t i" in pyx_text
    assert "cdef double total" in pyx_text
    assert any("Cython type preprocessing inserted 2" in line for line in logs)


def test_cython_type_preprocess_skips_dynamic_reassignments():
    preview = type_preprocess_mod.analyze_source(
        "def run(values):\n"
        "    total = 0.0\n"
        "    total = values[0]\n"
        "    ok = True\n"
        "    return total, ok\n"
    )

    typed = {(item.name, item.cython_type) for item in preview.typed_variables}
    skipped = {item.name for item in preview.skipped}
    assert typed == {("ok", "bint")}
    assert "total" in skipped


def test_cython_type_preprocess_handles_complex_function_shapes():
    source = (
        "class Worker:\r\n"
        "    async def compute(self, values, *extra, scale=1.0, **kw):\r\n"
        "        \"\"\"Worker method.\"\"\"\r\n"
        "        total = -1.0\r\n"
        "        count = len(values)\r\n"
        "        repeated = len(values) + len(values)\r\n"
        "        ratio = float(count) + 1.0\r\n"
        "        ok = count > 0\r\n"
        "        flag = bool(values)\r\n"
        "        label = 'demo'\r\n"
        "        pair_a, pair_b = (1.0, 2.0)\r\n"
        "        annotated: float = 0.0\r\n"
        "        maybe: int\r\n"
        "        total += 1.0\r\n"
        "        for i in range(count):\r\n"
        "            total += 1.0\r\n"
        "        for item in values:\r\n"
        "            label = item\r\n"
        "        with context() as resource:\r\n"
        "            ok = bool(resource)\r\n"
        "        try:\r\n"
        "            risky()\r\n"
        "        except Exception as exc:\r\n"
        "            label = str(exc)\r\n"
        "        if (walrus := len(values)):\r\n"
        "            ok = True\r\n"
        "        async for record in stream():\r\n"
        "            label = record\r\n"
        "        async with manager() as cm:\r\n"
        "            label = cm\r\n"
        "        def inner():\r\n"
        "            nested = 1.0\r\n"
        "        class Local:\r\n"
        "            pass\r\n"
        "        return total\r\n"
    )

    preview = type_preprocess_mod.analyze_source(source, filename="worker.py")
    pyx_source = type_preprocess_mod.render_pyx(source, preview)
    report = preview.to_report(input_path="worker.py", output_path="worker.pyx")
    typed = {(item.function, item.name, item.cython_type) for item in preview.typed_variables}
    skipped = {item.name: item.reason for item in preview.skipped}

    assert ("Worker.compute", "count", "Py_ssize_t") in typed
    assert ("Worker.compute", "flag", "bint") in typed
    assert ("Worker.compute", "i", "Py_ssize_t") in typed
    assert ("Worker.compute", "ratio", "double") in typed
    assert ("Worker.compute", "repeated", "Py_ssize_t") in typed
    assert "label" in skipped
    assert "pair_a" in skipped
    assert "resource" in skipped
    assert "record" in skipped
    assert "cm" in skipped
    assert report["input"] == "worker.py"
    assert report["output"] == "worker.pyx"
    assert "\r\n        cdef Py_ssize_t count\r\n" in pyx_source


def test_cython_type_preprocess_respects_global_and_nonlocal_targets():
    source = """
def use_global():
    global shared
    shared = 1.0
    local = 1.0
    return local

def outer():
    value = 0.0
    def inner():
        nonlocal value
        value = 1.0
        return value
    return inner()
"""

    preview = type_preprocess_mod.analyze_source(source)
    typed = {(item.function, item.name) for item in preview.typed_variables}

    assert ("use_global", "local") in typed
    assert ("use_global", "shared") not in typed
    assert ("outer", "value") in typed
    assert ("outer.inner", "value") not in typed


def test_cython_type_preprocess_cli_writes_reports_and_handles_empty_inputs(
    tmp_path,
    capsys,
):
    input_path = tmp_path / "worker.py"
    output_path = tmp_path / "worker.pyx"
    report_path = tmp_path / "report.json"
    input_path.write_text(
        "def run(values):\n"
        "    total = 0.0\n"
        "    for i in range(len(values)):\n"
        "        total += 1.0\n"
        "    return total\n",
        encoding="utf-8",
    )

    exit_code = type_preprocess_mod.main(
        [
            str(input_path),
            "--output",
            str(output_path),
            "--report-json",
            str(report_path),
            "--json",
            "--fail-on-empty",
        ]
    )

    printed_report = json.loads(capsys.readouterr().out)
    stored_report = json.loads(report_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert printed_report["input"] == str(input_path)
    assert stored_report["output"] == str(output_path)
    assert "cdef double total" in output_path.read_text(encoding="utf-8")

    empty_path = tmp_path / "empty.py"
    empty_path.write_text("def run():\n    return object()\n", encoding="utf-8")

    assert type_preprocess_mod.main([str(empty_path), "--fail-on-empty"]) == 2
    assert "def run():" in capsys.readouterr().out


def test_pre_install_main_dispatches_prepare_for_cython(monkeypatch, tmp_path):
    worker_py = tmp_path / "demo_worker.py"
    calls = {}

    monkeypatch.setattr(pre_mod, "prepare_for_cython", lambda args: calls.setdefault("worker_path", args.worker_path))
    monkeypatch.setattr(
        pre_mod.sys,
        "argv",
        [
            "pre_install.py",
            "remove_decorators",
            "--worker_path",
            str(worker_py),
        ],
    )

    pre_mod.main()

    assert calls["worker_path"] == str(worker_py)


def test_pre_install_module_runs_main_when_invoked_as_script(tmp_path, monkeypatch):
    worker_py = tmp_path / "demo_worker.py"
    worker_py.write_text("@drop\nvalue = 1\n", encoding="utf-8")
    monkeypatch.setattr(
        pre_mod.sys,
        "argv",
        [
            "pre_install.py",
            "remove_decorators",
            "--worker_path",
            str(worker_py),
        ],
    )

    runpy.run_module("agi_node.agi_dispatcher.pre_install", run_name="__main__")

    assert worker_py.with_suffix(".pyx").exists()


def test_pre_install_ensure_agi_env_finds_source_layout(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    candidate = workspace / "agilab" / "core" / "agi-env" / "src" / "agi_env"
    candidate.mkdir(parents=True)
    (candidate / "__init__.py").write_text("class AgiEnv:\n    pass\n", encoding="utf-8")

    monkeypatch.setattr(
        pre_mod,
        "__file__",
        str(workspace / "agilab" / "core" / "agi-node" / "src" / "agi_node" / "agi_dispatcher" / "pre_install.py"),
        raising=False,
    )
    monkeypatch.setattr(pre_mod.sys, "path", list(pre_mod.sys.path), raising=False)

    original_import = builtins.__import__
    original_agi_env = pre_mod.sys.modules.pop("agi_env", None)

    def _patched_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "agi_env" and str(candidate.parent) not in pre_mod.sys.path:
            raise ModuleNotFoundError("agi_env")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _patched_import)
    try:
        pre_mod._ensure_agi_env()
        assert str(candidate.parent) in pre_mod.sys.path
    finally:
        pre_mod.sys.modules.pop("agi_env", None)
        if original_agi_env is not None:
            pre_mod.sys.modules["agi_env"] = original_agi_env


def test_pre_install_ensure_agi_env_raises_when_source_layout_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(pre_mod, "__file__", str(tmp_path / "x" / "y" / "pre_install.py"), raising=False)
    monkeypatch.setattr(pre_mod.sys, "path", list(pre_mod.sys.path), raising=False)

    original_import = builtins.__import__
    original_agi_env = pre_mod.sys.modules.pop("agi_env", None)

    def _patched_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "agi_env":
            raise ModuleNotFoundError("agi_env")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _patched_import)
    try:
        with pytest.raises(ModuleNotFoundError, match="Unable to locate the agi_env package"):
            pre_mod._ensure_agi_env()
    finally:
        pre_mod.sys.modules.pop("agi_env", None)
        if original_agi_env is not None:
            pre_mod.sys.modules["agi_env"] = original_agi_env


def test_post_install_module_bootstraps_agi_env_from_source_layout(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    dispatcher_dir = workspace / "agilab" / "core" / "agi-node" / "src" / "agi_node" / "agi_dispatcher"
    dispatcher_dir.mkdir(parents=True)
    source_script = Path(post_mod.__file__).resolve()
    (dispatcher_dir / "post_install.py").write_text(source_script.read_text(encoding="utf-8"), encoding="utf-8")
    bootstrap_script = source_script.parent / "bootstrap_source_paths.py"
    (dispatcher_dir / "bootstrap_source_paths.py").write_text(
        bootstrap_script.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    candidate = workspace / "agilab" / "core" / "agi-env" / "src" / "agi_env"
    candidate.mkdir(parents=True)
    (candidate / "__init__.py").write_text("class AgiEnv:\n    pass\n", encoding="utf-8")

    original_sys_path = list(sys.path)
    original_agi_env = sys.modules.pop("agi_env", None)
    sys.path.insert(0, str(dispatcher_dir))

    original_import = builtins.__import__

    def _patched_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "agi_env" and str(candidate.parent) not in sys.path:
            raise ModuleNotFoundError("agi_env")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _patched_import)
    try:
        runpy.run_path(str(dispatcher_dir / "post_install.py"), run_name="post_install_bootstrap_test")
        assert str(candidate.parent) in sys.path
        assert Path(sys.modules["agi_env"].__file__).resolve() == (candidate / "__init__.py").resolve()
    finally:
        sys.path[:] = original_sys_path
        sys.modules.pop("agi_env", None)
        if original_agi_env is not None:
            sys.modules["agi_env"] = original_agi_env


def test_post_iter_data_files_and_has_samples(tmp_path):
    data_dir = tmp_path / "dataset"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "a.csv").write_text("x\n1\n", encoding="utf-8")
    (data_dir / "b.parquet").write_text("pq", encoding="utf-8")
    (data_dir / "._ignored.csv").write_text("hidden", encoding="utf-8")
    files = post_mod._iter_data_files(data_dir)
    assert [p.name for p in files] == ["a.csv", "b.parquet"]
    assert post_mod._has_samples(data_dir) is True


def test_post_dir_is_duplicate_of(tmp_path):
    src_dir = tmp_path / "src"
    ref_dir = tmp_path / "ref"
    src_dir.mkdir()
    ref_dir.mkdir()

    (src_dir / "a.csv").write_text("111", encoding="utf-8")
    (src_dir / "b.csv").write_text("222", encoding="utf-8")
    (ref_dir / "a.csv").write_text("111", encoding="utf-8")
    (ref_dir / "b.csv").write_text("222", encoding="utf-8")
    (ref_dir / "c.csv").write_text("333", encoding="utf-8")

    assert post_mod._dir_is_duplicate_of(src_dir, ref_dir) is True
    (src_dir / "extra.txt").write_text("x", encoding="utf-8")
    assert post_mod._dir_is_duplicate_of(src_dir, ref_dir) is False


def test_post_generated_trajectory_name_detection():
    assert post_mod._looks_like_generated_trajectory(Path("sat_trajectory.csv"))
    assert post_mod._looks_like_generated_trajectory(Path("starlink-2026.csv"))
    assert post_mod._looks_like_generated_trajectory(Path("flight_traj.parquet"))
    assert post_mod._looks_like_generated_trajectory(Path("flight_traj.csv"))
    assert post_mod._looks_like_generated_trajectory(Path("flight_trajectory.pq"))
    assert not post_mod._looks_like_generated_trajectory(Path("baseline.csv"))


def test_post_folder_looks_large_for_generated_or_many_files(tmp_path):
    generated = tmp_path / "generated"
    generated.mkdir()
    (generated / "a_trajectory.csv").write_text("x", encoding="utf-8")
    (generated / "b.csv").write_text("y", encoding="utf-8")
    assert post_mod._folder_looks_large(generated) is True

    many = tmp_path / "many"
    many.mkdir()
    for idx in range(25):
        (many / f"{idx}.csv").write_text("1", encoding="utf-8")
    assert post_mod._folder_looks_large(many) is True


def test_post_folder_looks_large_for_big_file(tmp_path):
    big = tmp_path / "big"
    big.mkdir()
    (big / "a.csv").write_bytes(b"x" * 1_100_000)
    (big / "b.csv").write_text("small", encoding="utf-8")

    assert post_mod._folder_looks_large(big) is True


def test_post_try_link_dir_replaces_empty_dir(tmp_path):
    link_path = tmp_path / "dataset" / "sat"
    target_path = tmp_path / "trajectory"
    target_path.mkdir(parents=True, exist_ok=True)
    (target_path / "a.csv").write_text("1", encoding="utf-8")
    (target_path / "b.csv").write_text("2", encoding="utf-8")

    link_path.mkdir(parents=True, exist_ok=True)
    ok = post_mod._try_link_dir(link_path, target_path)
    assert ok is True
    assert link_path.exists()
    assert link_path.resolve(strict=False) == target_path.resolve(strict=False)


def test_post_try_link_dir_keeps_matching_symlink_and_rejects_sample_dir(tmp_path):
    target_path = tmp_path / "trajectory"
    target_path.mkdir(parents=True, exist_ok=True)
    (target_path / "a.csv").write_text("1", encoding="utf-8")
    (target_path / "b.csv").write_text("2", encoding="utf-8")

    symlink_path = tmp_path / "dataset" / "sat"
    symlink_path.parent.mkdir(parents=True, exist_ok=True)
    symlink_path.symlink_to(target_path, target_is_directory=True)
    assert post_mod._try_link_dir(symlink_path, target_path) is True

    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "a.csv").write_text("1", encoding="utf-8")
    (occupied / "b.csv").write_text("2", encoding="utf-8")
    assert post_mod._try_link_dir(occupied, target_path) is False


def test_post_dataset_archive_candidates_deduplicates(tmp_path):
    class DummyEnv:
        share_target_name = "mycode"
        dataset_archive = tmp_path / "dataset.7z"
        agilab_pck = tmp_path

    env = DummyEnv()
    candidates = post_mod._dataset_archive_candidates(env)
    assert len(candidates) == 2
    assert candidates[0] == env.dataset_archive
    assert candidates[1].name == "dataset.7z"
    assert "apps" in candidates[1].as_posix()


def test_post_build_env_uses_parent_directory_and_name(monkeypatch, tmp_path):
    captured = {}

    class DummyEnv:
        def __init__(self, *, apps_path, app):
            captured["apps_path"] = apps_path
            captured["app"] = app

    monkeypatch.setattr(post_mod, "AgiEnv", DummyEnv)
    monkeypatch.setattr(post_mod, "_packaged_apps_path", lambda: None)

    post_mod._build_env(tmp_path / "demo_project")

    assert captured == {"apps_path": tmp_path, "app": "demo_project"}


def test_post_build_env_worker_name_uses_packaged_apps_root(monkeypatch, tmp_path):
    captured = {}
    packaged_apps = tmp_path / "site-packages" / "agilab" / "apps"

    class DummyEnv:
        def __init__(self, *, apps_path, app):
            captured["apps_path"] = apps_path
            captured["app"] = app

    monkeypatch.setattr(post_mod, "AgiEnv", DummyEnv)
    monkeypatch.setattr(post_mod, "_packaged_apps_path", lambda: packaged_apps)

    post_mod._build_env(tmp_path / "wenv" / "demo_worker")

    assert captured == {"apps_path": packaged_apps, "app": "demo_project"}


def test_post_extract_archive_uses_py7zr_extractall(monkeypatch, tmp_path):
    archive = tmp_path / "dataset.7z"
    archive.write_text("placeholder", encoding="utf-8")
    extracted = {}

    class _Archive:
        def __init__(self, path, mode="r"):
            extracted["path"] = Path(path)
            extracted["mode"] = mode

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extractall(self, *, path):
            extracted["dest"] = Path(path)

    monkeypatch.setattr(post_mod.py7zr, "SevenZipFile", _Archive)
    dest = tmp_path / "dataset"

    post_mod._extract_archive(archive, dest)

    assert extracted == {"path": archive, "mode": "r", "dest": dest}


def test_post_extract_archive_missing_file_is_noop_and_large_folder_handles_stat_error(tmp_path, monkeypatch):
    post_mod._extract_archive(tmp_path / "missing.7z", tmp_path / "dest")
    assert not (tmp_path / "dest").exists()

    folder = tmp_path / "folder"
    folder.mkdir()
    a = folder / "a.csv"
    b = folder / "b.csv"
    a.write_text("1", encoding="utf-8")
    b.write_text("2", encoding="utf-8")

    original_stat = Path.stat

    def _broken_stat(self, *args, **kwargs):
        if self == a:
            raise OSError("boom")
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(post_mod.Path, "stat", _broken_stat, raising=False)
    assert post_mod._folder_looks_large(folder) is False


def test_post_try_link_dir_returns_false_on_setup_and_symlink_failures(tmp_path, monkeypatch):
    link_path = tmp_path / "dataset" / "sat"
    target_path = tmp_path / "trajectory"
    target_path.mkdir(parents=True, exist_ok=True)
    (target_path / "a.csv").write_text("1", encoding="utf-8")
    (target_path / "b.csv").write_text("2", encoding="utf-8")

    monkeypatch.setattr(post_mod.Path, "mkdir", lambda self, *args, **kwargs: (_ for _ in ()).throw(OSError("mkdir denied")), raising=False)
    assert post_mod._try_link_dir(link_path, target_path) is False

    monkeypatch.undo()
    existing = tmp_path / "existing"
    existing.symlink_to(tmp_path / "wrong-target", target_is_directory=True)
    monkeypatch.setattr(post_mod.os, "symlink", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("symlink denied")))
    assert post_mod._try_link_dir(existing, target_path) is False


def test_post_try_link_dir_propagates_unexpected_setup_bug(tmp_path, monkeypatch):
    link_path = tmp_path / "dataset" / "sat"
    target_path = tmp_path / "trajectory"
    target_path.mkdir(parents=True, exist_ok=True)
    (target_path / "a.csv").write_text("1", encoding="utf-8")
    (target_path / "b.csv").write_text("2", encoding="utf-8")

    monkeypatch.setattr(
        post_mod.Path,
        "mkdir",
        lambda self, *args, **kwargs: (_ for _ in ()).throw(RuntimeError("mkdir bug")),
        raising=False,
    )

    with pytest.raises(RuntimeError, match="mkdir bug"):
        post_mod._try_link_dir(link_path, target_path)


def test_post_try_link_dir_returns_false_when_broken_symlink_cannot_be_removed(tmp_path, monkeypatch):
    link_path = tmp_path / "dataset" / "sat"
    wrong_target = tmp_path / "wrong-target"
    target_path = tmp_path / "trajectory"
    wrong_target.mkdir(parents=True, exist_ok=True)
    target_path.mkdir(parents=True, exist_ok=True)
    (target_path / "a.csv").write_text("1", encoding="utf-8")
    (target_path / "b.csv").write_text("2", encoding="utf-8")
    link_path.parent.mkdir(parents=True, exist_ok=True)
    link_path.symlink_to(wrong_target, target_is_directory=True)

    original_resolve = Path.resolve
    original_unlink = Path.unlink

    def _patched_resolve(self, *args, **kwargs):
        if self == link_path:
            raise OSError("resolve failed")
        return original_resolve(self, *args, **kwargs)

    def _patched_unlink(self, *args, **kwargs):
        if self == link_path:
            raise OSError("unlink failed")
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(post_mod.Path, "resolve", _patched_resolve, raising=False)
    monkeypatch.setattr(post_mod.Path, "unlink", _patched_unlink, raising=False)

    assert post_mod._try_link_dir(link_path, target_path) is False


def test_post_try_link_dir_rejects_non_sample_dir_with_visible_files(tmp_path):
    link_path = tmp_path / "dataset" / "sat"
    target_path = tmp_path / "trajectory"
    target_path.mkdir(parents=True, exist_ok=True)
    (target_path / "a.csv").write_text("1", encoding="utf-8")
    (target_path / "b.csv").write_text("2", encoding="utf-8")
    link_path.mkdir(parents=True, exist_ok=True)
    (link_path / "keep.txt").write_text("keep", encoding="utf-8")

    assert post_mod._try_link_dir(link_path, target_path) is False


def test_post_try_link_dir_returns_false_when_existing_dir_probe_raises(tmp_path, monkeypatch):
    link_path = tmp_path / "dataset" / "sat"
    target_path = tmp_path / "trajectory"
    target_path.mkdir(parents=True, exist_ok=True)
    (target_path / "a.csv").write_text("1", encoding="utf-8")
    (target_path / "b.csv").write_text("2", encoding="utf-8")
    link_path.mkdir(parents=True, exist_ok=True)

    original_iterdir = Path.iterdir

    def _patched_iterdir(self):
        if self == link_path:
            raise OSError("scan failed")
        return original_iterdir(self)

    monkeypatch.setattr(post_mod.Path, "iterdir", _patched_iterdir, raising=False)

    assert post_mod._try_link_dir(link_path, target_path) is False


def test_post_try_link_dir_windows_junction_fallbacks(tmp_path, monkeypatch):
    link_path = tmp_path / "dataset" / "sat"
    target_path = tmp_path / "trajectory"
    target_path.mkdir(parents=True, exist_ok=True)
    (target_path / "a.csv").write_text("1", encoding="utf-8")
    (target_path / "b.csv").write_text("2", encoding="utf-8")

    calls = []
    monkeypatch.setattr(post_mod.os, "name", "nt", raising=False)
    monkeypatch.setattr(post_mod, "Path", type(tmp_path))
    monkeypatch.setattr(post_mod.os, "symlink", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("symlink denied")))
    monkeypatch.setattr(
        subprocess,
        "check_call",
        lambda args, stdout=None, stderr=None: calls.append(tuple(args)),
    )

    assert post_mod._try_link_dir(link_path, target_path) is True
    assert calls == [("cmd", "/c", "mklink", "/J", str(link_path), str(target_path))]

    failing = tmp_path / "dataset" / "sat_fail"
    monkeypatch.setattr(
        subprocess,
        "check_call",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("mklink failed")),
    )
    assert post_mod._try_link_dir(failing, target_path) is False


def test_post_dataset_archive_candidates_handles_resolve_failure(monkeypatch, tmp_path):
    class DummyEnv:
        share_target_name = "mycode"
        dataset_archive = tmp_path / "dataset.7z"
        agilab_pck = tmp_path

    original_resolve = Path.resolve

    def _patched_resolve(self, *args, **kwargs):
        if self == DummyEnv.dataset_archive:
            raise OSError("boom")
        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(post_mod.Path, "resolve", _patched_resolve, raising=False)

    candidates = post_mod._dataset_archive_candidates(DummyEnv())

    assert len(candidates) == 2
    assert candidates[0] == DummyEnv.dataset_archive


def test_post_dataset_archive_candidates_propagates_unexpected_resolve_bug(monkeypatch, tmp_path):
    class DummyEnv:
        share_target_name = "mycode"
        dataset_archive = tmp_path / "dataset.7z"
        agilab_pck = tmp_path

    original_resolve = Path.resolve

    def _patched_resolve(self, *args, **kwargs):
        if self == DummyEnv.dataset_archive:
            raise RuntimeError("resolve bug")
        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(post_mod.Path, "resolve", _patched_resolve, raising=False)

    with pytest.raises(RuntimeError, match="resolve bug"):
        post_mod._dataset_archive_candidates(DummyEnv())


def test_post_dataset_archive_candidates_skips_non_path_and_duplicate_packaged_archive(tmp_path):
    packaged = tmp_path / "apps" / "mycode_project" / "src" / "mycode_worker" / "dataset.7z"

    class NonPathEnv:
        share_target_name = "mycode"
        dataset_archive = "dataset.7z"
        agilab_pck = tmp_path

    class DuplicateEnv:
        share_target_name = "mycode"
        dataset_archive = packaged
        agilab_pck = tmp_path

    assert post_mod._dataset_archive_candidates(NonPathEnv()) == [packaged]
    assert post_mod._dataset_archive_candidates(DuplicateEnv()) == [packaged]


def test_post_dir_is_duplicate_of_false_branches(tmp_path):
    missing = tmp_path / "missing"
    ref = tmp_path / "ref"
    ref.mkdir()
    (ref / "a.csv").write_text("1", encoding="utf-8")
    (ref / "b.csv").write_text("2", encoding="utf-8")
    assert post_mod._dir_is_duplicate_of(missing, ref) is False

    src_one = tmp_path / "src_one"
    src_one.mkdir()
    (src_one / "a.csv").write_text("1", encoding="utf-8")
    assert post_mod._dir_is_duplicate_of(src_one, ref) is False

    ref_one = tmp_path / "ref_one"
    ref_one.mkdir()
    (ref_one / "a.csv").write_text("1", encoding="utf-8")
    src_two = tmp_path / "src_two"
    src_two.mkdir()
    (src_two / "a.csv").write_text("1", encoding="utf-8")
    (src_two / "b.csv").write_text("2", encoding="utf-8")
    assert post_mod._dir_is_duplicate_of(src_two, ref_one) is False

    ref_mismatch = tmp_path / "ref_mismatch"
    ref_mismatch.mkdir()
    (ref_mismatch / "a.csv").write_text("1", encoding="utf-8")
    (ref_mismatch / "b.csv").write_text("333", encoding="utf-8")
    assert post_mod._dir_is_duplicate_of(src_two, ref_mismatch) is False


def test_post_main_returns_usage_on_invalid_args(capsys):
    assert post_mod.main([]) == 1
    captured = capsys.readouterr()
    assert "Usage: python post_install.py <app>" in captured.out


def test_post_main_reports_missing_archive_and_returns_zero(tmp_path, monkeypatch, capsys):
    dataset_archive = tmp_path / "missing.7z"
    dest_arg = tmp_path / "share" / "demo"
    env = SimpleNamespace(
        share_target_name="demo",
        dataset_archive=dataset_archive,
        agilab_pck=tmp_path,
        resolve_share_path=lambda _target: dest_arg,
        unzip_data=lambda *_args, **_kwargs: None,
        share_root_path=lambda: tmp_path / "share",
    )
    monkeypatch.setattr(post_mod, "_build_env", lambda _app_arg: env)

    result = post_mod.main([str(tmp_path / "demo_project")])

    assert result == 0
    captured = capsys.readouterr()
    assert "dataset archive not found for 'demo'" in captured.out


def test_post_main_relinks_duplicate_sat_folder_to_preferred_dataset(tmp_path, monkeypatch, capsys):
    dataset_archive = tmp_path / "dataset.7z"
    dataset_archive.write_text("placeholder", encoding="utf-8")
    dest_arg = tmp_path / "share" / "demo"
    dataset_root = dest_arg / "dataset"
    sat_folder = dataset_root / "sat"
    sat_folder.mkdir(parents=True, exist_ok=True)
    (sat_folder / "a.csv").write_text("1", encoding="utf-8")
    (sat_folder / "b.csv").write_text("2", encoding="utf-8")

    share_root = tmp_path / "shared-root"
    preferred = share_root / "sat_trajectory" / "dataset" / "Trajectory"
    preferred.mkdir(parents=True, exist_ok=True)
    (preferred / "a.csv").write_text("1", encoding="utf-8")
    (preferred / "b.csv").write_text("2", encoding="utf-8")

    env = SimpleNamespace(
        share_target_name="demo",
        dataset_archive=dataset_archive,
        agilab_pck=tmp_path,
        resolve_share_path=lambda _target: dest_arg,
        unzip_data=lambda *_args, **_kwargs: None,
        share_root_path=lambda: share_root,
    )
    monkeypatch.setattr(post_mod, "_build_env", lambda _app_arg: env)

    result = post_mod.main([str(tmp_path / "demo_project")])

    assert result == 0
    assert sat_folder.is_symlink()
    assert sat_folder.resolve(strict=False) == preferred.resolve(strict=False)
    assert "deduplicated" in capsys.readouterr().out


def test_post_main_relinks_existing_sat_symlink_to_preferred_dataset(tmp_path, monkeypatch, capsys):
    dataset_archive = tmp_path / "dataset.7z"
    dataset_archive.write_text("placeholder", encoding="utf-8")
    dest_arg = tmp_path / "share" / "demo"
    dataset_root = dest_arg / "dataset"
    sat_folder = dataset_root / "sat"
    sat_folder.parent.mkdir(parents=True, exist_ok=True)

    share_root = tmp_path / "shared-root"
    preferred = share_root / "sat_trajectory" / "dataset" / "Trajectory"
    current = share_root / "sat_trajectory" / "dataframe" / "Trajectory"
    preferred.mkdir(parents=True, exist_ok=True)
    current.mkdir(parents=True, exist_ok=True)
    for folder in (preferred, current):
        (folder / "a.csv").write_text("1", encoding="utf-8")
        (folder / "b.csv").write_text("2", encoding="utf-8")
    sat_folder.symlink_to(current, target_is_directory=True)

    env = SimpleNamespace(
        share_target_name="demo",
        dataset_archive=dataset_archive,
        agilab_pck=tmp_path,
        resolve_share_path=lambda _target: dest_arg,
        unzip_data=lambda *_args, **_kwargs: None,
        share_root_path=lambda: share_root,
    )
    monkeypatch.setattr(post_mod, "_build_env", lambda _app_arg: env)

    result = post_mod.main([str(tmp_path / "demo_project")])

    assert result == 0
    assert sat_folder.is_symlink()
    assert sat_folder.resolve(strict=False) == preferred.resolve(strict=False)
    assert "relinked" in capsys.readouterr().out


def test_post_main_preserves_existing_sat_folder_when_requested(tmp_path, monkeypatch, capsys):
    dataset_archive = tmp_path / "dataset.7z"
    dataset_archive.write_text("placeholder", encoding="utf-8")
    dest_arg = tmp_path / "share" / "demo"
    dataset_root = dest_arg / "dataset"
    sat_folder = dataset_root / "sat"
    sat_folder.mkdir(parents=True, exist_ok=True)
    (sat_folder / "existing-a.csv").write_text("1", encoding="utf-8")
    (sat_folder / "existing-b.csv").write_text("2", encoding="utf-8")

    share_root = tmp_path / "shared-root"
    preferred = share_root / "sat_trajectory" / "dataset" / "Trajectory"
    preferred.mkdir(parents=True, exist_ok=True)
    (preferred / "a.csv").write_text("1", encoding="utf-8")
    (preferred / "b.csv").write_text("2", encoding="utf-8")

    env = SimpleNamespace(
        share_target_name="demo",
        dataset_archive=dataset_archive,
        agilab_pck=tmp_path,
        resolve_share_path=lambda _target: dest_arg,
        unzip_data=lambda *_args, **_kwargs: None,
        share_root_path=lambda: share_root,
    )
    monkeypatch.setattr(post_mod, "_build_env", lambda _app_arg: env)
    monkeypatch.setenv("AGILAB_PRESERVE_LINK_SIM_SAT", "1")

    result = post_mod.main([str(tmp_path / "demo_project")])

    assert result == 0
    assert sat_folder.is_dir()
    assert sat_folder.is_symlink() is False
    assert (sat_folder / "existing-a.csv").exists()
    assert "linked" not in capsys.readouterr().out


def test_post_main_replaces_large_sat_folder_with_preferred_dataset(tmp_path, monkeypatch, capsys):
    dataset_archive = tmp_path / "dataset.7z"
    dataset_archive.write_text("placeholder", encoding="utf-8")
    dest_arg = tmp_path / "share" / "demo"
    dataset_root = dest_arg / "dataset"
    sat_folder = dataset_root / "sat"
    sat_folder.mkdir(parents=True, exist_ok=True)
    for idx in range(25):
        (sat_folder / f"generated_{idx}_trajectory.csv").write_text("x", encoding="utf-8")

    share_root = tmp_path / "shared-root"
    preferred = share_root / "sat_trajectory" / "dataset" / "Trajectory"
    preferred.mkdir(parents=True, exist_ok=True)
    (preferred / "a.csv").write_text("1", encoding="utf-8")
    (preferred / "b.csv").write_text("2", encoding="utf-8")

    env = SimpleNamespace(
        share_target_name="demo",
        dataset_archive=dataset_archive,
        agilab_pck=tmp_path,
        resolve_share_path=lambda _target: dest_arg,
        unzip_data=lambda *_args, **_kwargs: None,
        share_root_path=lambda: share_root,
    )
    monkeypatch.setattr(post_mod, "_build_env", lambda _app_arg: env)

    result = post_mod.main([str(tmp_path / "demo_project")])

    assert result == 0
    assert sat_folder.is_symlink()
    assert sat_folder.resolve(strict=False) == preferred.resolve(strict=False)
    assert "replaced large" in capsys.readouterr().out


def test_post_main_copies_trajectory_files_when_linking_fails(tmp_path, monkeypatch, capsys):
    dataset_archive = tmp_path / "dataset.7z"
    dataset_archive.write_text("placeholder", encoding="utf-8")
    dest_arg = tmp_path / "share" / "demo"
    dataset_root = dest_arg / "dataset"
    trajectory_folder = dataset_root / "Trajectory"
    trajectory_folder.mkdir(parents=True, exist_ok=True)
    (trajectory_folder / "a.csv").write_text("1", encoding="utf-8")
    (trajectory_folder / "b.csv").write_text("2", encoding="utf-8")

    env = SimpleNamespace(
        share_target_name="demo",
        dataset_archive=dataset_archive,
        agilab_pck=tmp_path,
        resolve_share_path=lambda _target: dest_arg,
        unzip_data=lambda *_args, **_kwargs: None,
        share_root_path=lambda: tmp_path / "share-root",
    )
    monkeypatch.setattr(post_mod, "_build_env", lambda _app_arg: env)
    monkeypatch.setattr(post_mod, "_try_link_dir", lambda *_args, **_kwargs: False)

    result = post_mod.main([str(tmp_path / "demo_project")])

    sat_folder = dataset_root / "sat"
    assert result == 0
    assert (sat_folder / "a.csv").exists()
    assert (sat_folder / "b.csv").exists()
    assert "copied 2 trajectory file(s)" in capsys.readouterr().out


def test_post_main_extracts_optional_trajectory_archive_and_links_sat_folder(tmp_path, monkeypatch, capsys):
    dataset_archive = tmp_path / "dataset.7z"
    dataset_archive.write_text("placeholder", encoding="utf-8")
    dest_arg = tmp_path / "share" / "demo"
    dataset_root = dest_arg / "dataset"
    trajectory_archive = dataset_archive.parent / "Trajectory.7z"
    trajectory_archive.write_text("placeholder", encoding="utf-8")
    extracted = {}

    env = SimpleNamespace(
        share_target_name="demo",
        dataset_archive=dataset_archive,
        agilab_pck=tmp_path,
        resolve_share_path=lambda _target: dest_arg,
        unzip_data=lambda *_args, **_kwargs: None,
        share_root_path=lambda: tmp_path / "share-root",
    )

    def _fake_extract(archive, dest):
        extracted["archive"] = archive
        extracted["dest"] = dest
        trajectory_folder = dataset_root / "Trajectory"
        trajectory_folder.mkdir(parents=True, exist_ok=True)
        (trajectory_folder / "a.csv").write_text("1", encoding="utf-8")
        (trajectory_folder / "b.csv").write_text("2", encoding="utf-8")

    monkeypatch.setattr(post_mod, "_build_env", lambda _app_arg: env)
    monkeypatch.setattr(post_mod, "_extract_archive", _fake_extract)

    result = post_mod.main([str(tmp_path / "demo_project")])

    sat_folder = dataset_root / "sat"
    assert result == 0
    assert extracted == {"archive": trajectory_archive, "dest": dataset_root}
    assert sat_folder.is_symlink()
    assert sat_folder.resolve(strict=False) == (dataset_root / "Trajectory").resolve(strict=False)
    out = capsys.readouterr().out
    assert "extracting optional trajectories" in out
    assert "linked" in out


def test_post_main_reports_optional_dataset_seeding_exception(tmp_path, monkeypatch, capsys):
    dataset_archive = tmp_path / "dataset.7z"
    dataset_archive.write_text("placeholder", encoding="utf-8")
    dest_arg = tmp_path / "share" / "demo"
    env = SimpleNamespace(
        share_target_name="demo",
        dataset_archive=dataset_archive,
        agilab_pck=tmp_path,
        resolve_share_path=lambda _target: dest_arg,
        unzip_data=lambda *_args, **_kwargs: None,
        share_root_path=lambda: (_ for _ in ()).throw(
            RuntimeError("agi_share_path is not configured; cannot resolve shared storage path.")
        ),
    )
    monkeypatch.setattr(post_mod, "_build_env", lambda _app_arg: env)

    result = post_mod.main([str(tmp_path / "demo_project")])

    assert result == 0
    assert "optional dataset seeding shared-root lookup skipped: agi_share_path is not configured" in capsys.readouterr().out


def test_post_main_skips_optional_dataset_seeding_oserror(tmp_path, monkeypatch, capsys):
    dataset_archive = tmp_path / "dataset.7z"
    dataset_archive.write_text("placeholder", encoding="utf-8")
    dest_arg = tmp_path / "share" / "demo"
    env = SimpleNamespace(
        share_target_name="demo",
        dataset_archive=dataset_archive,
        agilab_pck=tmp_path,
        resolve_share_path=lambda _target: dest_arg,
        unzip_data=lambda *_args, **_kwargs: None,
        share_root_path=lambda: tmp_path / "share-root",
    )
    monkeypatch.setattr(post_mod, "_build_env", lambda _app_arg: env)
    monkeypatch.setattr(
        post_mod,
        "_seed_optional_dataset",
        lambda **_kwargs: (_ for _ in ()).throw(OSError("seed denied")),
    )

    result = post_mod.main([str(tmp_path / "demo_project")])

    assert result == 0
    assert "optional dataset seeding skipped: seed denied" in capsys.readouterr().out


def test_post_optional_dataset_seeding_error_classifier():
    assert post_mod._is_optional_dataset_seeding_error(OSError("disk denied")) is True
    assert post_mod._is_optional_dataset_seeding_error(shutil.Error("copy failed")) is True
    assert post_mod._is_optional_dataset_seeding_error(py7zr.Bad7zFile("bad archive")) is True
    assert post_mod._is_optional_dataset_seeding_error(
        RuntimeError("agi_share_path is not configured; cannot resolve shared storage path.")
    ) is True
    assert post_mod._is_optional_dataset_seeding_error(RuntimeError("unexpected bug")) is False


def test_post_main_returns_zero_when_deduplicate_cleanup_fails(tmp_path, monkeypatch, capsys):
    dataset_archive = tmp_path / "dataset.7z"
    dataset_archive.write_text("placeholder", encoding="utf-8")
    dest_arg = tmp_path / "share" / "demo"
    dataset_root = dest_arg / "dataset"
    sat_folder = dataset_root / "sat"
    sat_folder.mkdir(parents=True, exist_ok=True)
    (sat_folder / "a.csv").write_text("1", encoding="utf-8")
    (sat_folder / "b.csv").write_text("2", encoding="utf-8")

    share_root = tmp_path / "shared-root"
    preferred = share_root / "sat_trajectory" / "dataset" / "Trajectory"
    preferred.mkdir(parents=True, exist_ok=True)
    (preferred / "a.csv").write_text("1", encoding="utf-8")
    (preferred / "b.csv").write_text("2", encoding="utf-8")

    env = SimpleNamespace(
        share_target_name="demo",
        dataset_archive=dataset_archive,
        agilab_pck=tmp_path,
        resolve_share_path=lambda _target: dest_arg,
        unzip_data=lambda *_args, **_kwargs: None,
        share_root_path=lambda: share_root,
    )
    monkeypatch.setattr(post_mod, "_build_env", lambda _app_arg: env)
    monkeypatch.setattr(
        post_mod.shutil,
        "rmtree",
        lambda path, ignore_errors=False: (_ for _ in ()).throw(OSError("cleanup denied")) if Path(path) == sat_folder else None,
    )

    result = post_mod.main([str(tmp_path / "demo_project")])

    assert result == 0
    assert sat_folder.is_dir()
    assert "deduplicated" not in capsys.readouterr().out


def test_post_main_returns_zero_when_large_cleanup_fails(tmp_path, monkeypatch, capsys):
    dataset_archive = tmp_path / "dataset.7z"
    dataset_archive.write_text("placeholder", encoding="utf-8")
    dest_arg = tmp_path / "share" / "demo"
    dataset_root = dest_arg / "dataset"
    sat_folder = dataset_root / "sat"
    sat_folder.mkdir(parents=True, exist_ok=True)
    for idx in range(25):
        (sat_folder / f"generated_{idx}_trajectory.csv").write_text("x", encoding="utf-8")

    share_root = tmp_path / "shared-root"
    preferred = share_root / "sat_trajectory" / "dataset" / "Trajectory"
    preferred.mkdir(parents=True, exist_ok=True)
    (preferred / "a.csv").write_text("1", encoding="utf-8")
    (preferred / "b.csv").write_text("2", encoding="utf-8")

    env = SimpleNamespace(
        share_target_name="demo",
        dataset_archive=dataset_archive,
        agilab_pck=tmp_path,
        resolve_share_path=lambda _target: dest_arg,
        unzip_data=lambda *_args, **_kwargs: None,
        share_root_path=lambda: share_root,
    )
    monkeypatch.setattr(post_mod, "_build_env", lambda _app_arg: env)
    monkeypatch.setattr(post_mod, "_dir_is_duplicate_of", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        post_mod.shutil,
        "rmtree",
        lambda path, ignore_errors=False: (_ for _ in ()).throw(OSError("cleanup denied")) if Path(path) == sat_folder else None,
    )

    result = post_mod.main([str(tmp_path / "demo_project")])

    assert result == 0
    assert sat_folder.is_dir()
    assert "replaced large" not in capsys.readouterr().out


def test_post_main_returns_zero_when_trajectory_archive_extracts_no_samples(tmp_path, monkeypatch, capsys):
    dataset_archive = tmp_path / "dataset.7z"
    dataset_archive.write_text("placeholder", encoding="utf-8")
    trajectory_archive = dataset_archive.parent / "Trajectory.7z"
    trajectory_archive.write_text("placeholder", encoding="utf-8")
    dest_arg = tmp_path / "share" / "demo"

    env = SimpleNamespace(
        share_target_name="demo",
        dataset_archive=dataset_archive,
        agilab_pck=tmp_path,
        resolve_share_path=lambda _target: dest_arg,
        unzip_data=lambda *_args, **_kwargs: None,
        share_root_path=lambda: tmp_path / "share-root",
    )

    extracted = {}

    def _fake_extract(archive, dest):
        extracted["archive"] = archive
        extracted["dest"] = dest
        trajectory_folder = Path(dest) / "Trajectory"
        trajectory_folder.mkdir(parents=True, exist_ok=True)
        (trajectory_folder / "only-one.csv").write_text("1", encoding="utf-8")

    monkeypatch.setattr(post_mod, "_build_env", lambda _app_arg: env)
    monkeypatch.setattr(post_mod, "_extract_archive", _fake_extract)

    result = post_mod.main([str(tmp_path / "demo_project")])

    assert result == 0
    assert extracted == {"archive": trajectory_archive, "dest": dest_arg / "dataset"}
    assert not (dest_arg / "dataset" / "sat").exists()
    out = capsys.readouterr().out
    assert "extracting optional trajectories" in out
    assert "linked" not in out


def test_post_folder_looks_large_requires_two_files(tmp_path):
    folder = tmp_path / "folder"
    folder.mkdir()
    (folder / "only.csv").write_text("1", encoding="utf-8")

    assert post_mod._folder_looks_large(folder) is False


def test_post_main_returns_zero_when_existing_sat_samples_have_no_preferred_source(tmp_path, monkeypatch):
    dataset_archive = tmp_path / "dataset.7z"
    dataset_archive.write_text("x", encoding="utf-8")
    dest_arg = tmp_path / "share-dest"

    def _fake_unzip(_archive, dest):
        sat = Path(dest) / "dataset" / "sat"
        sat.mkdir(parents=True, exist_ok=True)
        (sat / "a.csv").write_text("1", encoding="utf-8")
        (sat / "b.csv").write_text("2", encoding="utf-8")

    env = SimpleNamespace(
        share_target_name="demo",
        dataset_archive=dataset_archive,
        agilab_pck=tmp_path / "pkg",
        resolve_share_path=lambda _target: dest_arg,
        unzip_data=_fake_unzip,
        share_root_path=lambda: tmp_path / "share-root",
    )

    monkeypatch.setattr(post_mod, "_build_env", lambda _app_arg: env)
    monkeypatch.setattr(post_mod, "_dataset_archive_candidates", lambda _env: [dataset_archive])
    monkeypatch.setattr(
        post_mod,
        "_try_link_dir",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("linking should not be attempted")),
    )

    assert post_mod.main([str(tmp_path / "demo_project")]) == 0


def test_post_main_keeps_non_sat_trajectory_symlink_without_relink(tmp_path, monkeypatch):
    dataset_archive = tmp_path / "dataset.7z"
    dataset_archive.write_text("x", encoding="utf-8")
    dest_arg = tmp_path / "share-dest"
    share_root = tmp_path / "share-root"
    sat_folder = dest_arg / "dataset" / "sat"
    current = tmp_path / "external-sat"
    preferred = share_root / "sat_trajectory" / "dataset" / "Trajectory"
    current.mkdir(parents=True, exist_ok=True)
    preferred.mkdir(parents=True, exist_ok=True)
    for folder, names in ((current, ("x.csv", "y.csv")), (preferred, ("a.csv", "b.csv"))):
        for name in names:
            (folder / name).write_text("1", encoding="utf-8")

    def _fake_unzip(_archive, dest):
        current_sat = Path(dest) / "dataset" / "sat"
        current_sat.parent.mkdir(parents=True, exist_ok=True)
        current_sat.symlink_to(current, target_is_directory=True)

    env = SimpleNamespace(
        share_target_name="demo",
        dataset_archive=dataset_archive,
        agilab_pck=tmp_path / "pkg",
        resolve_share_path=lambda _target: dest_arg,
        unzip_data=_fake_unzip,
        share_root_path=lambda: share_root,
    )

    monkeypatch.setattr(post_mod, "_build_env", lambda _app_arg: env)
    monkeypatch.setattr(post_mod, "_dataset_archive_candidates", lambda _env: [dataset_archive])
    monkeypatch.setattr(
        post_mod,
        "_try_link_dir",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("relink should not be attempted")),
    )

    assert post_mod.main([str(tmp_path / "demo_project")]) == 0
    assert sat_folder.is_symlink()
    assert sat_folder.resolve(strict=False) == current.resolve(strict=False)


def test_post_main_returns_zero_when_sat_trajectory_relink_fails(tmp_path, monkeypatch, capsys):
    dataset_archive = tmp_path / "dataset.7z"
    dataset_archive.write_text("x", encoding="utf-8")
    dest_arg = tmp_path / "share-dest"
    share_root = tmp_path / "share-root"
    sat_folder = dest_arg / "dataset" / "sat"
    current = share_root / "sat_trajectory" / "dataframe" / "Trajectory"
    preferred = share_root / "sat_trajectory" / "dataset" / "Trajectory"
    current.mkdir(parents=True, exist_ok=True)
    preferred.mkdir(parents=True, exist_ok=True)
    for folder in (current, preferred):
        (folder / "a.csv").write_text("1", encoding="utf-8")
        (folder / "b.csv").write_text("2", encoding="utf-8")

    def _fake_unzip(_archive, dest):
        current_sat = Path(dest) / "dataset" / "sat"
        current_sat.parent.mkdir(parents=True, exist_ok=True)
        current_sat.symlink_to(current, target_is_directory=True)

    env = SimpleNamespace(
        share_target_name="demo",
        dataset_archive=dataset_archive,
        agilab_pck=tmp_path / "pkg",
        resolve_share_path=lambda _target: dest_arg,
        unzip_data=_fake_unzip,
        share_root_path=lambda: share_root,
    )

    monkeypatch.setattr(post_mod, "_build_env", lambda _app_arg: env)
    monkeypatch.setattr(post_mod, "_dataset_archive_candidates", lambda _env: [dataset_archive])
    monkeypatch.setattr(post_mod, "_try_link_dir", lambda *_args, **_kwargs: False)

    assert post_mod.main([str(tmp_path / "demo_project")]) == 0
    assert sat_folder.is_symlink()
    assert sat_folder.resolve(strict=False) == current.resolve(strict=False)
    assert "relinked" not in capsys.readouterr().out


def test_post_main_copy_fallback_skips_existing_destinations(tmp_path, monkeypatch, capsys):
    dataset_archive = tmp_path / "dataset.7z"
    dataset_archive.write_text("x", encoding="utf-8")
    dest_arg = tmp_path / "share-dest"
    sat_folder = dest_arg / "dataset" / "sat"
    trajectory_folder = dest_arg / "dataset" / "Trajectory"

    def _fake_unzip(_archive, dest):
        current_sat = Path(dest) / "dataset" / "sat"
        current_trajectory = Path(dest) / "dataset" / "Trajectory"
        current_sat.mkdir(parents=True, exist_ok=True)
        current_trajectory.mkdir(parents=True, exist_ok=True)
        for name in ("a.csv", "b.csv"):
            (current_sat / name).write_text("existing", encoding="utf-8")
            (current_trajectory / name).write_text("new", encoding="utf-8")

    env = SimpleNamespace(
        share_target_name="demo",
        dataset_archive=dataset_archive,
        agilab_pck=tmp_path / "pkg",
        resolve_share_path=lambda _target: dest_arg,
        unzip_data=_fake_unzip,
        share_root_path=lambda: tmp_path / "share-root",
    )

    original_has_samples = post_mod._has_samples

    def _patched_has_samples(path):
        if Path(path) == sat_folder:
            return False
        return original_has_samples(path)

    monkeypatch.setattr(post_mod, "_build_env", lambda _app_arg: env)
    monkeypatch.setattr(post_mod, "_dataset_archive_candidates", lambda _env: [dataset_archive])
    monkeypatch.setattr(post_mod, "_try_link_dir", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(post_mod, "_has_samples", _patched_has_samples)

    assert post_mod.main([str(tmp_path / "demo_project")]) == 0
    assert (sat_folder / "a.csv").read_text(encoding="utf-8") == "existing"
    assert (sat_folder / "b.csv").read_text(encoding="utf-8") == "existing"
    assert trajectory_folder.exists()
    assert "copied" not in capsys.readouterr().out


def test_post_main_returns_zero_when_duplicate_relink_fails(tmp_path, monkeypatch, capsys):
    dataset_archive = tmp_path / "dataset.7z"
    dataset_archive.write_text("x", encoding="utf-8")
    dest_arg = tmp_path / "share" / "demo"
    dataset_root = dest_arg / "dataset"
    sat_folder = dataset_root / "sat"
    sat_folder.mkdir(parents=True, exist_ok=True)
    (sat_folder / "a.csv").write_text("1", encoding="utf-8")
    (sat_folder / "b.csv").write_text("2", encoding="utf-8")

    share_root = tmp_path / "shared-root"
    preferred = share_root / "sat_trajectory" / "dataset" / "Trajectory"
    preferred.mkdir(parents=True, exist_ok=True)
    (preferred / "a.csv").write_text("1", encoding="utf-8")
    (preferred / "b.csv").write_text("2", encoding="utf-8")

    env = SimpleNamespace(
        share_target_name="demo",
        dataset_archive=dataset_archive,
        agilab_pck=tmp_path,
        resolve_share_path=lambda _target: dest_arg,
        unzip_data=lambda *_args, **_kwargs: None,
        share_root_path=lambda: share_root,
    )
    monkeypatch.setattr(post_mod, "_build_env", lambda _app_arg: env)
    monkeypatch.setattr(post_mod, "_try_link_dir", lambda *_args, **_kwargs: False)

    assert post_mod.main([str(tmp_path / "demo_project")]) == 0
    assert not sat_folder.exists()
    assert "deduplicated" not in capsys.readouterr().out


def test_post_main_returns_zero_when_large_relink_fails(tmp_path, monkeypatch, capsys):
    dataset_archive = tmp_path / "dataset.7z"
    dataset_archive.write_text("x", encoding="utf-8")
    dest_arg = tmp_path / "share" / "demo"
    dataset_root = dest_arg / "dataset"
    sat_folder = dataset_root / "sat"
    sat_folder.mkdir(parents=True, exist_ok=True)
    for idx in range(25):
        (sat_folder / f"generated_{idx}_trajectory.csv").write_text("x", encoding="utf-8")

    share_root = tmp_path / "shared-root"
    preferred = share_root / "sat_trajectory" / "dataset" / "Trajectory"
    preferred.mkdir(parents=True, exist_ok=True)
    (preferred / "a.csv").write_text("1", encoding="utf-8")
    (preferred / "b.csv").write_text("2", encoding="utf-8")

    env = SimpleNamespace(
        share_target_name="demo",
        dataset_archive=dataset_archive,
        agilab_pck=tmp_path,
        resolve_share_path=lambda _target: dest_arg,
        unzip_data=lambda *_args, **_kwargs: None,
        share_root_path=lambda: share_root,
    )
    monkeypatch.setattr(post_mod, "_build_env", lambda _app_arg: env)
    monkeypatch.setattr(post_mod, "_dir_is_duplicate_of", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(post_mod, "_try_link_dir", lambda *_args, **_kwargs: False)

    assert post_mod.main([str(tmp_path / "demo_project")]) == 0
    assert not sat_folder.exists()
    assert "replaced large" not in capsys.readouterr().out


def test_post_main_ignores_symlink_resolution_errors_before_returning(tmp_path, monkeypatch):
    dataset_archive = tmp_path / "dataset.7z"
    dataset_archive.write_text("x", encoding="utf-8")
    dest_arg = tmp_path / "share-dest"
    sat_folder = dest_arg / "dataset" / "sat"
    share_root = tmp_path / "share-root"
    current = tmp_path / "current"
    preferred = share_root / "sat_trajectory" / "dataset" / "Trajectory"
    current.mkdir(parents=True, exist_ok=True)
    preferred.mkdir(parents=True, exist_ok=True)
    for folder, names in ((current, ("x.csv", "y.csv")), (preferred, ("a.csv", "b.csv"))):
        for name in names:
            (folder / name).write_text("1", encoding="utf-8")

    def _fake_unzip(_archive, dest):
        current_sat = Path(dest) / "dataset" / "sat"
        current_sat.parent.mkdir(parents=True, exist_ok=True)
        current_sat.symlink_to(current, target_is_directory=True)

    env = SimpleNamespace(
        share_target_name="demo",
        dataset_archive=dataset_archive,
        agilab_pck=tmp_path / "pkg",
        resolve_share_path=lambda _target: dest_arg,
        unzip_data=_fake_unzip,
        share_root_path=lambda: share_root,
    )

    original_resolve = Path.resolve

    def _patched_resolve(self, *args, **kwargs):
        if self == sat_folder:
            raise OSError("resolve failed")
        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(post_mod, "_build_env", lambda _app_arg: env)
    monkeypatch.setattr(post_mod, "_dataset_archive_candidates", lambda _env: [dataset_archive])
    monkeypatch.setattr(post_mod.Path, "resolve", _patched_resolve, raising=False)

    assert post_mod.main([str(tmp_path / "demo_project")]) == 0


def test_post_main_propagates_unexpected_symlink_resolution_bug(tmp_path, monkeypatch):
    dataset_archive = tmp_path / "dataset.7z"
    dataset_archive.write_text("x", encoding="utf-8")
    dest_arg = tmp_path / "share-dest"
    sat_folder = dest_arg / "dataset" / "sat"
    share_root = tmp_path / "share-root"
    current = tmp_path / "current"
    preferred = share_root / "sat_trajectory" / "dataset" / "Trajectory"
    current.mkdir(parents=True, exist_ok=True)
    preferred.mkdir(parents=True, exist_ok=True)
    for folder, names in ((current, ("x.csv", "y.csv")), (preferred, ("a.csv", "b.csv"))):
        for name in names:
            (folder / name).write_text("1", encoding="utf-8")

    def _fake_unzip(_archive, dest):
        current_sat = Path(dest) / "dataset" / "sat"
        current_sat.parent.mkdir(parents=True, exist_ok=True)
        current_sat.symlink_to(current, target_is_directory=True)

    env = SimpleNamespace(
        share_target_name="demo",
        dataset_archive=dataset_archive,
        agilab_pck=tmp_path / "pkg",
        resolve_share_path=lambda _target: dest_arg,
        unzip_data=_fake_unzip,
        share_root_path=lambda: share_root,
    )

    original_resolve = Path.resolve

    def _patched_resolve(self, *args, **kwargs):
        if self == sat_folder:
            raise RuntimeError("resolve bug")
        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(post_mod, "_build_env", lambda _app_arg: env)
    monkeypatch.setattr(post_mod, "_dataset_archive_candidates", lambda _env: [dataset_archive])
    monkeypatch.setattr(post_mod.Path, "resolve", _patched_resolve, raising=False)

    with pytest.raises(RuntimeError, match="resolve bug"):
        post_mod.main([str(tmp_path / "demo_project")])


def test_post_main_returns_zero_when_preferred_link_fails_without_trajectory_fallback(tmp_path, monkeypatch):
    dataset_archive = tmp_path / "dataset.7z"
    dataset_archive.write_text("x", encoding="utf-8")
    dest_arg = tmp_path / "share-dest"
    share_root = tmp_path / "share-root"
    preferred = share_root / "sat_trajectory" / "dataset" / "Trajectory"
    preferred.mkdir(parents=True, exist_ok=True)
    (preferred / "a.csv").write_text("1", encoding="utf-8")
    (preferred / "b.csv").write_text("2", encoding="utf-8")

    def _fake_unzip(_archive, dest):
        (Path(dest) / "dataset").mkdir(parents=True, exist_ok=True)

    env = SimpleNamespace(
        share_target_name="demo",
        dataset_archive=dataset_archive,
        agilab_pck=tmp_path / "pkg",
        resolve_share_path=lambda _target: dest_arg,
        unzip_data=_fake_unzip,
        share_root_path=lambda: share_root,
    )

    monkeypatch.setattr(post_mod, "_build_env", lambda _app_arg: env)
    monkeypatch.setattr(post_mod, "_dataset_archive_candidates", lambda _env: [dataset_archive])
    monkeypatch.setattr(post_mod, "_try_link_dir", lambda *_args, **_kwargs: False)

    assert post_mod.main([str(tmp_path / "demo_project")]) == 0
    assert not (dest_arg / "dataset" / "sat").exists()


def test_post_install_module_runs_main_when_invoked_as_script(monkeypatch, capsys):
    monkeypatch.setattr(post_mod.sys, "argv", ["post_install.py"])

    with pytest.raises(SystemExit) as excinfo:
        runpy.run_module("agi_node.agi_dispatcher.post_install", run_name="__main__")

    assert excinfo.value.code == 1
    assert "Usage: python post_install.py <app>" in capsys.readouterr().out


def test_build_module_runs_main_when_invoked_as_script_and_tolerates_hacl_mkdir_failure(monkeypatch):
    original_mkdir = Path.mkdir

    def _patched_mkdir(self, *args, **kwargs):
        if self.as_posix() == "Modules/_hacl":
            raise OSError("mkdir denied")
        return original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", _patched_mkdir, raising=False)
    monkeypatch.setattr(build_mod.sys, "argv", ["build.py", "bdist_egg", "-d", ""])

    with pytest.raises(SystemExit):
        runpy.run_module("agi_node.agi_dispatcher.build", run_name="__main__")


def test_build_ensure_hacl_dir_ignores_oserror():
    calls = []
    logs = []

    class DummyPath:
        def __init__(self, raw_path):
            self.raw_path = raw_path
            calls.append(raw_path)

        def __str__(self):
            return self.raw_path

        def mkdir(self, parents=False, exist_ok=False):
            raise OSError("mkdir denied")

    build_mod._ensure_hacl_dir(
        log=SimpleNamespace(info=lambda message: logs.append(message)),
        path_factory=DummyPath,
    )

    assert calls == ["Modules/_hacl"]
    assert logs == ["mkdir Modules/_hacl"]


def test_build_ensure_hacl_dir_propagates_unexpected_mkdir_bug():
    class DummyPath:
        def __init__(self, raw_path):
            self.raw_path = raw_path

        def __str__(self):
            return self.raw_path

        def mkdir(self, parents=False, exist_ok=False):
            raise RuntimeError("mkdir bug")

    with pytest.raises(RuntimeError, match="mkdir bug"):
        build_mod._ensure_hacl_dir(
            log=SimpleNamespace(info=lambda *_args, **_kwargs: None),
            path_factory=DummyPath,
        )


def test_build_parse_custom_args_and_remaining():
    opts = build_mod.parse_custom_args(
        ["build_ext", "--packages", "a,b", "-b", "/tmp/out", "--flag"],
        Path("/tmp/app"),
    )
    assert opts.command == "build_ext"
    assert opts.packages == ["a", "b"]
    assert opts.build_dir == "/tmp/out"
    assert opts.remaining == ["--flag"]


def test_build_parse_custom_args_rejects_missing_required_output_dirs(tmp_path):
    with pytest.raises(SystemExit):
        build_mod.parse_custom_args(["build_ext", "-b", ""], tmp_path / "app")

    with pytest.raises(SystemExit):
        build_mod.parse_custom_args(["bdist_egg", "-d", ""], tmp_path / "app")


def test_build_truncate_path_at_segment_uses_last_match():
    path = "/x/alpha_worker/y/beta_worker/file.py"
    truncated = build_mod.truncate_path_at_segment(path)
    assert truncated.as_posix() == "/x/alpha_worker/y/beta_worker"
    with pytest.raises(ValueError):
        build_mod.truncate_path_at_segment("/x/no/segment/here.py")


def test_build_find_sys_prefix_prefers_python_dirs(tmp_path):
    python_dir = tmp_path / "Python313"
    python_dir.mkdir(parents=True, exist_ok=True)
    build_mod.AgiEnv.logger = type("Logger", (), {"info": staticmethod(lambda *_args, **_kwargs: None)})()
    assert build_mod.find_sys_prefix(str(tmp_path)) == str(python_dir)


def test_build_find_sys_prefix_falls_back_to_sys_prefix(tmp_path, monkeypatch):
    monkeypatch.setattr(build_mod.sys, "prefix", str(tmp_path / "fallback-prefix"), raising=False)
    build_mod.AgiEnv.logger = type("Logger", (), {"info": staticmethod(lambda *_args, **_kwargs: None)})()

    assert build_mod.find_sys_prefix(str(tmp_path)) == str(tmp_path / "fallback-prefix")


def test_build_fix_windows_drive(monkeypatch):
    monkeypatch.setattr(build_mod.os, "name", "nt", raising=False)
    assert build_mod._fix_windows_drive(r"C:Users\me") == r"C:\Users\me"
    assert build_mod._fix_windows_drive(r"C:\Users\me") == r"C:\Users\me"


def test_build_relative_to_home():
    home = Path.home()
    inside = home / "tmp" / "demo"
    outside = Path("/tmp/agilab-demo-outside")
    assert build_mod._relative_to_home(inside) == Path("tmp") / "demo"
    assert build_mod._relative_to_home(outside) == outside


def test_build_keep_lflag(tmp_path):
    existing = tmp_path / "libs"
    existing.mkdir(parents=True, exist_ok=True)
    assert build_mod._keep_lflag("-Wl,--as-needed") is True
    assert build_mod._keep_lflag(f"-L{existing}") is True
    assert build_mod._keep_lflag("-L/definitely/missing/path") is False


def test_build_sanitize_build_ext_link_settings(tmp_path):
    existing = tmp_path / "libs"
    existing.mkdir(parents=True, exist_ok=True)

    library_dirs, extra_link_args = build_mod._sanitize_build_ext_link_settings(
        [str(existing), "/definitely/missing/library"],
        [f"-L{existing}", "-L/definitely/missing/library", "-Wl,--as-needed"],
    )

    assert library_dirs == [str(existing)]
    assert extra_link_args == [f"-L{existing}", "-Wl,--as-needed"]


def test_build_ext_compile_config_covers_platform_and_free_threading():
    compile_args, define_macros, compiler_directives = build_mod._build_ext_compile_config(
        sys_platform="darwin",
        pyvers_worker="3.13",
    )
    assert compile_args == [
        "-Wno-unknown-warning-option",
        "-Wno-unreachable-code-fallthrough",
    ]
    assert define_macros == [("CYTHON_FALLTHROUGH", "")]
    assert compiler_directives == {}

    compile_args, define_macros, compiler_directives = build_mod._build_ext_compile_config(
        sys_platform="win32",
        pyvers_worker="3.13t",
    )
    assert compile_args == []
    assert ("CYTHON_FALLTHROUGH", "") in define_macros
    assert ("Py_GIL_DISABLED", "1") in define_macros
    assert compiler_directives == {"freethreading_compatible": True}


def test_build_worker_extension_uses_expected_fields(tmp_path):
    extension = build_mod._build_worker_extension(
        worker_module="demo_worker",
        src_rel=Path("src") / "demo_worker" / "demo_worker.pyx",
        prefix=tmp_path / "prefix",
        extra_compile_args=["-Wfoo"],
        define_macros=[("CYTHON_FALLTHROUGH", ""), ("Py_GIL_DISABLED", "1")],
        library_dirs=[str(tmp_path / "libs")],
        extra_link_args=["-L/tmp/libs", "-Wl,--as-needed"],
    )

    assert extension.name == "demo_worker_cy"
    assert extension.sources == ["src/demo_worker/demo_worker.pyx"]
    assert extension.include_dirs == [str(tmp_path / "prefix" / "include")]
    assert extension.extra_compile_args == ["-Wfoo"]
    assert ("Py_GIL_DISABLED", "1") in extension.define_macros
    assert extension.library_dirs == [str(tmp_path / "libs")]
    assert extension.extra_link_args == ["-L/tmp/libs", "-Wl,--as-needed"]


def test_resolve_cython_cache_option_defaults_to_agilab_cache(tmp_path):
    class PathFactory:
        @classmethod
        def home(cls):
            return tmp_path / "home"

        def __init__(self, raw_path):
            self.path = Path(raw_path)

        def expanduser(self):
            return self.path.expanduser()

    assert build_mod._resolve_cython_cache_option(environ={}, path_cls=PathFactory) == str(
        tmp_path / "home" / ".cache" / "agilab" / "cython"
    )
    assert build_mod._resolve_cython_cache_option(
        environ={"AGILAB_CYTHON_CACHE": "off"},
        path_cls=PathFactory,
    ) is False
    assert build_mod._resolve_cython_cache_option(
        environ={"AGILAB_CYTHON_CACHE": str(tmp_path / "custom-cache")},
        path_cls=PathFactory,
    ) == str(tmp_path / "custom-cache")


def test_cythonize_worker_extension_passes_quiet_directives_and_cache(tmp_path):
    extension = build_mod._build_worker_extension(
        worker_module="demo_worker",
        src_rel=Path("src") / "demo_worker" / "demo_worker.pyx",
        prefix=tmp_path / "prefix",
        extra_compile_args=[],
        define_macros=[("CYTHON_FALLTHROUGH", "")],
        library_dirs=[],
        extra_link_args=[],
    )
    cythonize_calls = []

    result = build_mod._cythonize_worker_extension(
        extension=extension,
        compiler_directives={"freethreading_compatible": True},
        quiet=True,
        cythonize_fn=lambda modules, language_level=3, quiet=False, compiler_directives=None, cache=False: (
            cythonize_calls.append((modules, language_level, quiet, compiler_directives, cache)) or ["ext_mod"]
        ),
        resolve_cython_cache_option_fn=lambda: str(tmp_path / "cython-cache"),
    )

    assert result == ["ext_mod"]
    assert cythonize_calls == [
        ([extension], 3, True, {"freethreading_compatible": True}, str(tmp_path / "cython-cache"))
    ]


def test_build_remove_decorators_command_quotes_worker_path():
    command = build_mod._build_remove_decorators_command("workers/demo worker.py")

    assert "remove_decorators" in command
    assert '--worker_path "workers/demo worker.py"' in command


def test_postprocess_bdist_egg_output_unpacks_and_cleans_links(tmp_path):
    out_dir = tmp_path / "worker_home" / "demo_project"
    dist_dir = out_dir / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    egg_path = dist_dir / "demo_worker-0.1.0.egg"
    with ZipFile(egg_path, "w") as zf:
        zf.writestr("demo_worker/__init__.py", "")
        zf.writestr("demo_worker/app_args_form.py", "package_file = True\n")
        zf.writestr("app_args_form.py", "import streamlit\n")
        zf.writestr("demo_args_form.py", "import streamlit\n")
        zf.writestr("__pycache__/app_args_form.cpython-313.pyc", b"")

    env = SimpleNamespace(worker_path="workers/demo_worker.py")
    links_created = [tmp_path / "src" / "demo_worker" / "module_link"]
    cleanup_calls = []
    os_calls = []
    log_lines = []

    build_mod._postprocess_bdist_egg_output(
        env=env,
        out_dir=out_dir,
        links_created=links_created,
        cleanup_links_fn=lambda links: cleanup_calls.append(list(links)),
        os_system_fn=lambda cmd: os_calls.append(cmd) or 0,
        log=SimpleNamespace(info=lambda message: log_lines.append(message)),
    )

    assert (out_dir / "src" / "demo_worker" / "__init__.py").exists()
    assert any("mkdir" in line for line in log_lines)
    assert os_calls and "remove_decorators" in os_calls[0]
    assert cleanup_calls == [links_created]


def test_unpack_worker_eggs_uses_default_zipfile_and_logger(tmp_path):
    dist_dir = tmp_path / "dist"
    dest_src = tmp_path / "src"
    dist_dir.mkdir()
    egg_path = dist_dir / "demo_worker-0.1.0.egg"
    with ZipFile(egg_path, "w") as zf:
        zf.writestr("demo_worker/__init__.py", "")
        zf.writestr("demo_worker/app_args_form.py", "package_file = True\n")
        zf.writestr("app_args_form.py", "import streamlit\n")
        zf.writestr("demo_args_form.py", "import streamlit\n")
        zf.writestr("__pycache__/app_args_form.cpython-313.pyc", b"")

    log_lines: list[str] = []
    build_mod.AgiEnv.logger = SimpleNamespace(
        info=lambda message, *args: log_lines.append(str(message % args if args else message))
    )

    build_mod._unpack_worker_eggs(
        dist_dir=dist_dir,
        dest_src=dest_src,
    )

    assert (dest_src / "demo_worker" / "__init__.py").exists()
    assert (dest_src / "demo_worker" / "app_args_form.py").exists()
    assert not (dest_src / "app_args_form.py").exists()
    assert not (dest_src / "demo_args_form.py").exists()
    assert not (dest_src / "__pycache__" / "app_args_form.cpython-313.pyc").exists()
    assert any("mkdir" in line for line in log_lines)
    assert any("Unpacking" in line for line in log_lines)
    assert any("Removed UI-only worker artifact" in line for line in log_lines)


def test_purge_top_level_ui_build_artifacts_removes_stale_build_cache(tmp_path):
    app_root = tmp_path / "demo_project"
    build_lib = app_root / "build" / "lib"
    package_dir = build_lib / "demo_worker"
    pycache_dir = build_lib / "__pycache__"
    package_dir.mkdir(parents=True)
    pycache_dir.mkdir()
    (build_lib / "app_args_form.py").write_text("import streamlit\n", encoding="utf-8")
    (build_lib / "demo_args_form.py").write_text("import streamlit\n", encoding="utf-8")
    (pycache_dir / "app_args_form.cpython-313.pyc").write_bytes(b"")
    (package_dir / "app_args_form.py").write_text("keep = True\n", encoding="utf-8")

    log_lines = []
    removed = build_mod._purge_top_level_ui_build_artifacts(
        app_root,
        log=SimpleNamespace(info=lambda message, *args: log_lines.append(str(message % args if args else message))),
    )

    assert {path.name for path in removed} == {
        "app_args_form.py",
        "demo_args_form.py",
        "app_args_form.cpython-313.pyc",
    }
    assert not (build_lib / "app_args_form.py").exists()
    assert not (build_lib / "demo_args_form.py").exists()
    assert not (pycache_dir / "app_args_form.cpython-313.pyc").exists()
    assert (package_dir / "app_args_form.py").exists()
    assert any("Removed UI-only worker artifact" in line for line in log_lines)


def test_resolve_worker_python_path_prefers_home_and_falls_back_to_cwd(tmp_path, monkeypatch):
    worker_home = tmp_path / "home"
    cwd_root = tmp_path / "cwd"
    home_candidate = worker_home / "workers" / "demo_worker.py"
    cwd_candidate = cwd_root / "workers" / "demo_worker.py"
    cwd_candidate.parent.mkdir(parents=True, exist_ok=True)
    cwd_candidate.write_text("value = 1\n", encoding="utf-8")
    monkeypatch.chdir(cwd_root)

    env = SimpleNamespace(worker_path="workers/demo_worker.py", home_abs=str(worker_home))
    original_resolve = build_mod.Path.resolve

    def _patched_resolve(self, *args, **kwargs):
        if self == home_candidate:
            raise OSError("resolve failed")
        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(build_mod.Path, "resolve", _patched_resolve, raising=False)

    assert build_mod._resolve_worker_python_path(env) == cwd_candidate.resolve()


def test_ensure_worker_cython_source_runs_pre_install_when_pyx_missing(tmp_path):
    worker_py = tmp_path / "workers" / "demo_worker.py"
    worker_py.parent.mkdir(parents=True, exist_ok=True)
    worker_py.write_text("value = 1\n", encoding="utf-8")
    pre_script = tmp_path / "pre_install.py"
    pre_script.write_text("print('ok')\n", encoding="utf-8")
    run_calls = []
    log_lines = []

    build_mod._ensure_worker_cython_source(
        SimpleNamespace(worker_path=str(worker_py), home_abs=str(tmp_path), verbose=2),
        resolve_pre_install_script_fn=lambda _env: pre_script,
        subprocess_run=lambda cmd, check=True: run_calls.append((cmd, check)),
        log=SimpleNamespace(info=lambda *args: log_lines.append(args)),
    )

    assert run_calls == [
        (
            [
                build_mod.sys.executable,
                str(pre_script),
                "remove_decorators",
                "--worker_path",
                str(worker_py),
                "--verbose",
            ],
            True,
        )
    ]
    assert log_lines and "Ensuring Cython source via pre_install" in str(log_lines[0][0])


def test_resolve_cython_type_preprocess_option_from_environment():
    assert build_mod._resolve_cython_type_preprocess_option(environ={}) is False
    assert build_mod._resolve_cython_type_preprocess_option(
        environ={"AGILAB_CYTHON_TYPE_PREPROCESS": "1"}
    ) is True
    assert build_mod._resolve_cython_type_preprocess_option(
        environ={"AGILAB_CYTHON_TYPE_PREPROCESS": "off"}
    ) is False


def test_ensure_worker_cython_source_passes_type_preprocess_when_enabled(tmp_path):
    worker_py = tmp_path / "workers" / "demo_worker.py"
    worker_py.parent.mkdir(parents=True, exist_ok=True)
    worker_py.write_text("value = 1\n", encoding="utf-8")
    pre_script = tmp_path / "pre_install.py"
    pre_script.write_text("print('ok')\n", encoding="utf-8")
    run_calls = []

    build_mod._ensure_worker_cython_source(
        SimpleNamespace(worker_path=str(worker_py), home_abs=str(tmp_path), verbose=0),
        resolve_pre_install_script_fn=lambda _env: pre_script,
        resolve_cython_type_preprocess_option_fn=lambda: True,
        subprocess_run=lambda cmd, check=True: run_calls.append((cmd, check)),
        log=SimpleNamespace(info=lambda *args: None),
    )

    assert run_calls == [
        (
            [
                build_mod.sys.executable,
                str(pre_script),
                "remove_decorators",
                "--worker_path",
                str(worker_py),
                "--type-preprocess",
            ],
            True,
        )
    ]


def test_resolve_build_output_normalizes_filelike_path_and_relative_home(tmp_path):
    worker_home = tmp_path / "home"
    filelike_out = worker_home / "exports" / "demo_worker.whl"
    filelike_out.parent.mkdir(parents=True, exist_ok=True)
    warnings_seen = []

    outdir, out_arg, target_module = build_mod._resolve_build_output(
        filelike_out,
        home_abs=worker_home,
        log=SimpleNamespace(
            warning=lambda *args: warnings_seen.append(" ".join(str(arg) for arg in args)),
            error=lambda *_args: None,
        ),
    )

    assert outdir == filelike_out
    assert out_arg == "exports"
    assert target_module == "demo_worker.whl".replace("-", "_")
    assert any("looks like a file" in line for line in warnings_seen)


def test_build_setuptools_argv_handles_relative_and_absolute_out_arg(tmp_path):
    relative_argv = build_mod._build_setuptools_argv(
        prog_name="build.py",
        command="build_ext",
        home_abs=tmp_path / "home",
        out_arg="exports",
    )
    absolute_argv = build_mod._build_setuptools_argv(
        prog_name="build.py",
        command="bdist_egg",
        home_abs=tmp_path / "home",
        out_arg=str(tmp_path / "external" / "demo_worker"),
    )

    assert relative_argv == ["build.py", "build_ext", "-b", tmp_path / "home" / "exports" / "dist"]
    assert absolute_argv == [
        "build.py",
        "bdist_egg",
        "-d",
        tmp_path / "external" / "demo_worker" / "dist",
    ]


def test_ensure_build_readme_creates_placeholder_once(tmp_path):
    readme = tmp_path / "README.md"

    created = build_mod._ensure_build_readme(readme)
    initial_text = readme.read_text(encoding="utf-8")
    readme.write_text("existing", encoding="utf-8")
    reused = build_mod._ensure_build_readme(readme)

    assert created == readme
    assert reused == readme
    assert initial_text == "a README.md file is required"
    assert readme.read_text(encoding="utf-8") == "existing"


def test_build_setup_kwargs_uses_find_packages_and_ext_modules():
    kwargs = build_mod._build_setup_kwargs(
        worker_module="demo_worker",
        ext_modules=["ext_mod"],
        find_packages_fn=lambda where="src": ["demo_worker", "demo_worker.subpkg"],
    )

    assert kwargs == {
        "name": "demo_worker",
        "version": "0.1.0",
        "package_dir": {"": "src"},
        "packages": ["demo_worker", "demo_worker.subpkg"],
        "py_modules": [],
        "include_package_data": True,
        "package_data": {"": ["*.7z"]},
        "ext_modules": ["ext_mod"],
        "zip_safe": False,
    }


def test_configure_build_ext_modules_orchestrates_helper_calls(tmp_path):
    build_extension_calls = []
    cythonize_calls = []
    log_lines = []

    result = build_mod._configure_build_ext_modules(
        active_app=tmp_path / "demo_project",
        build_dir=str(tmp_path / "out"),
        remaining_args=["--quiet"],
        worker_module="demo_worker",
        pyvers_worker="3.13t",
        find_sys_prefix_fn=lambda _base: str(tmp_path / "prefix"),
        sanitize_build_ext_link_settings_fn=lambda _lib, _link: (["/tmp/lib"], ["-Wl,--as-needed"]),
        build_ext_compile_config_fn=lambda **_kwargs: (
            ["-Wfoo"],
            [("CYTHON_FALLTHROUGH", ""), ("Py_GIL_DISABLED", "1")],
            {"freethreading_compatible": True},
        ),
        ensure_hacl_dir_fn=lambda: log_lines.append(("ensure_hacl_dir",)),
        build_worker_extension_fn=lambda **kwargs: (
            build_extension_calls.append(kwargs) or "ext_def"
        ),
        cythonize_worker_extension_fn=lambda **kwargs: (
            cythonize_calls.append(kwargs) or ["ext_mod"]
        ),
        log=SimpleNamespace(info=lambda *args: log_lines.append(args)),
    )

    assert result == ["ext_mod"]
    assert build_extension_calls == [
        {
            "worker_module": "demo_worker",
            "src_rel": Path("src") / "demo_worker" / "demo_worker.pyx",
            "prefix": tmp_path / "prefix",
            "extra_compile_args": ["-Wfoo"],
            "define_macros": [("CYTHON_FALLTHROUGH", ""), ("Py_GIL_DISABLED", "1")],
            "library_dirs": ["/tmp/lib"],
            "extra_link_args": ["-Wl,--as-needed"],
        }
    ]
    assert cythonize_calls == [
        {
            "extension": "ext_def",
            "compiler_directives": {"freethreading_compatible": True},
            "quiet": True,
        }
    ]
    assert any(args[0] == "cwd: " + str(tmp_path / "demo_project") for args in log_lines if args)
    assert any(args[0] == "build_dir: " + str(tmp_path / "out") for args in log_lines if args)


def test_prepare_bdist_egg_sources_changes_cwd_and_aggregates_links(tmp_path):
    app_dir = tmp_path / "demo_project"
    chdir_calls = []
    symlink_calls = []

    links = build_mod._prepare_bdist_egg_sources(
        env=SimpleNamespace(active_app=app_dir),
        packages=["pkg_a", "pkg_b"],
        create_symlink_for_module_fn=lambda env, module: (
            symlink_calls.append((env.active_app, module)) or [tmp_path / module]
        ),
        chdir_fn=lambda path: chdir_calls.append(path),
    )

    assert chdir_calls == [app_dir]
    assert symlink_calls == [(app_dir, "pkg_a"), (app_dir, "pkg_b")]
    assert links == [tmp_path / "pkg_a", tmp_path / "pkg_b"]


def test_prepare_build_ext_command_validates_path_and_ensures_cython_source(tmp_path):
    env = SimpleNamespace(worker_path="workers/demo_worker.py")
    truncate_calls = []
    ensure_calls = []

    build_mod._prepare_build_ext_command(
        env=env,
        build_dir=str(tmp_path / "exports" / "demo_worker"),
        truncate_path_at_segment_fn=lambda path: truncate_calls.append(path) or Path(path),
        ensure_worker_cython_source_fn=lambda arg: ensure_calls.append(arg),
    )

    assert truncate_calls == [str(tmp_path / "exports" / "demo_worker")]
    assert ensure_calls == [env]


def test_prepare_build_ext_command_logs_and_reraises_truncate_failure(tmp_path):
    errors = []

    with pytest.raises(ValueError, match="bad path"):
        build_mod._prepare_build_ext_command(
            env=SimpleNamespace(worker_path="workers/demo_worker.py"),
            build_dir=str(tmp_path / "invalid"),
            truncate_path_at_segment_fn=lambda _path: (_ for _ in ()).throw(ValueError("bad path")),
            ensure_worker_cython_source_fn=lambda _env: None,
            log=SimpleNamespace(error=lambda *args: errors.append(" ".join(str(arg) for arg in args))),
        )

    assert errors == ["bad path"]


def test_prepare_build_ext_command_requires_build_dir():
    errors = []

    with pytest.raises(ValueError, match="requires --build-dir/-b argument"):
        build_mod._prepare_build_ext_command(
            env=SimpleNamespace(worker_path="workers/demo_worker.py"),
            build_dir=None,
            ensure_worker_cython_source_fn=lambda _env: pytest.fail("unexpected cython source generation"),
            log=SimpleNamespace(error=lambda message, *args: errors.append(str(message % args if args else message))),
        )

    assert errors == ["build_ext requires --build-dir/-b argument"]


def test_prepare_setup_artifacts_orchestrates_build_ext_and_purge(tmp_path):
    env = SimpleNamespace(
        active_app=tmp_path / "demo_project",
        is_worker_env=False,
        pyvers_worker="3.13t",
    )
    purge_calls = []
    configure_calls = []
    log_lines = []

    ext_modules, links_created = build_mod._prepare_setup_artifacts(
        env=env,
        cmd="build_ext",
        active_app=tmp_path / "demo_project",
        build_dir=str(tmp_path / "out"),
        remaining_args=["--quiet"],
        packages=["pkg_a"],
        worker_module="demo_worker",
        purge_worker_venv_artifacts_fn=lambda app_root, worker_module: (
            purge_calls.append((app_root, worker_module)) or [tmp_path / "purged" / ".venv"]
        ),
        configure_build_ext_modules_fn=lambda **kwargs: (
            configure_calls.append(kwargs) or ["ext_mod"]
        ),
        prepare_bdist_egg_sources_fn=lambda **_kwargs: (_ for _ in ()).throw(AssertionError("bdist helper should not run")),
        log=SimpleNamespace(info=lambda *args: log_lines.append(args)),
    )

    assert ext_modules == ["ext_mod"]
    assert links_created == []
    assert purge_calls == [(env.active_app, "demo_worker")]
    assert configure_calls == [
        {
            "active_app": tmp_path / "demo_project",
            "build_dir": str(tmp_path / "out"),
            "remaining_args": ["--quiet"],
            "worker_module": "demo_worker",
            "pyvers_worker": "3.13t",
        }
    ]
    assert any("Purged nested worker virtualenv artifacts before %s: %s" in args[0] for args in log_lines)


def test_prepare_setup_artifacts_orchestrates_bdist_egg_sources(tmp_path):
    env = SimpleNamespace(
        active_app=tmp_path / "demo_project",
        is_worker_env=False,
        pyvers_worker="3.13",
    )
    purge_calls = []
    bdist_calls = []

    ext_modules, links_created = build_mod._prepare_setup_artifacts(
        env=env,
        cmd="bdist_egg",
        active_app=tmp_path / "demo_project",
        build_dir=str(tmp_path / "out"),
        remaining_args=[],
        packages=["pkg_a", "pkg_b"],
        worker_module="demo_worker",
        purge_worker_venv_artifacts_fn=lambda app_root, worker_module: (
            purge_calls.append((app_root, worker_module)) or []
        ),
        configure_build_ext_modules_fn=lambda **_kwargs: (_ for _ in ()).throw(AssertionError("build_ext helper should not run")),
        prepare_bdist_egg_sources_fn=lambda **kwargs: (
            bdist_calls.append(kwargs) or [tmp_path / "pkg_a", tmp_path / "pkg_b"]
        ),
    )

    assert ext_modules == []
    assert links_created == [tmp_path / "pkg_a", tmp_path / "pkg_b"]
    assert purge_calls == [(env.active_app, "demo_worker")]
    assert bdist_calls == [
        {
            "env": env,
            "packages": ["pkg_a", "pkg_b"],
        }
    ]


def test_finalize_setup_artifacts_runs_bdist_postprocess(tmp_path):
    env = SimpleNamespace(home_abs=str(tmp_path / "home"), is_worker_env=False)
    postprocess_calls = []
    links_created = [tmp_path / "src" / "demo_worker" / "module_link"]

    build_mod._finalize_setup_artifacts(
        env=env,
        cmd="bdist_egg",
        out_arg="exports/demo_worker",
        links_created=links_created,
        postprocess_bdist_egg_output_fn=lambda **kwargs: postprocess_calls.append(kwargs),
    )

    assert postprocess_calls == [
        {
            "env": env,
            "out_dir": Path(env.home_abs) / "exports/demo_worker",
            "links_created": links_created,
        }
    ]


def test_finalize_setup_artifacts_skips_non_bdist_or_worker_env(tmp_path):
    calls = []

    build_mod._finalize_setup_artifacts(
        env=SimpleNamespace(home_abs=str(tmp_path / "home"), is_worker_env=False),
        cmd="build_ext",
        out_arg="exports/demo_worker",
        links_created=[],
        postprocess_bdist_egg_output_fn=lambda **kwargs: calls.append(kwargs),
    )
    build_mod._finalize_setup_artifacts(
        env=SimpleNamespace(home_abs=str(tmp_path / "home"), is_worker_env=True),
        cmd="bdist_egg",
        out_arg="exports/demo_worker",
        links_created=[],
        postprocess_bdist_egg_output_fn=lambda **kwargs: calls.append(kwargs),
    )

    assert calls == []


def test_build_inject_shared_site_packages_appends_candidates_once(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    monkeypatch.setattr(build_mod.Path, "home", staticmethod(lambda: fake_home))
    monkeypatch.setattr(build_mod.sys, "path", [], raising=False)
    monkeypatch.setattr(build_mod.sys, "version_info", SimpleNamespace(major=3, minor=13), raising=False)

    build_mod._inject_shared_site_packages()
    build_mod._inject_shared_site_packages()

    expected = [
        str(fake_home / "agilab/.venv/lib/python3.13/site-packages"),
        str(fake_home / ".agilab/.venv/lib/python3.13/site-packages"),
    ]
    assert build_mod.sys.path == expected


def test_build_create_symlink_for_module_uses_symlink_on_unmanaged_host(tmp_path, monkeypatch):
    src_abs = tmp_path / "app-src" / "demo_worker"
    src_abs.mkdir(parents=True, exist_ok=True)
    env = SimpleNamespace(
        agi_node=tmp_path / "agi-node",
        agi_env=tmp_path / "agi-env",
        target_worker="demo_worker",
        app_src=tmp_path / "app-src",
    )

    created = []
    monkeypatch.setattr(build_mod.AgiEnv, "_is_managed_pc", False, raising=False)
    monkeypatch.setattr(build_mod.AgiEnv, "logger", _DummyLogger(), raising=False)
    monkeypatch.setattr(build_mod.AgiEnv, "create_symlink", lambda src, dest: created.append((Path(src), Path(dest))))
    monkeypatch.setattr(build_mod.os, "link", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("hard link should not be used")))

    links = build_mod.create_symlink_for_module(env, "demo_worker")

    assert len(links) == 1
    assert created[0][0] == src_abs
    assert created[0][1] == links[0]
    assert links[0].name == "demo_worker"


def test_build_create_symlink_for_module_falls_back_to_hard_link(tmp_path, monkeypatch):
    src_abs = tmp_path / "agi-env" / "agi_env" / "pkg"
    src_abs.mkdir(parents=True, exist_ok=True)
    env = SimpleNamespace(
        agi_node=tmp_path / "agi-node",
        agi_env=tmp_path / "agi-env",
        target_worker="demo_worker",
        app_src=tmp_path / "app-src",
    )

    created_hard_links = []
    build_mod.AgiEnv.logger = SimpleNamespace(
        info=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
        error=lambda *args, **kwargs: None,
        debug=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(build_mod.AgiEnv, "_is_managed_pc", False, raising=False)
    monkeypatch.setattr(
        build_mod.AgiEnv,
        "create_symlink",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("no symlink")),
    )
    monkeypatch.setattr(build_mod.os, "link", lambda src, dest: created_hard_links.append((Path(src), Path(dest))))

    links = build_mod.create_symlink_for_module(env, "agi_env.pkg")

    assert len(links) == 1
    assert created_hard_links[0][0] == src_abs
    assert created_hard_links[0][1] == links[0]
    assert links[0].name == "pkg"


def test_build_create_symlink_for_module_uses_agi_node_namespace_for_other_packages(tmp_path, monkeypatch):
    src_abs = tmp_path / "agi-node" / "src" / "agi_node" / "shared" / "pkg"
    src_abs.mkdir(parents=True, exist_ok=True)
    env = SimpleNamespace(
        agi_node=tmp_path / "agi-node",
        agi_env=tmp_path / "agi-env",
        target_worker="demo_worker",
        app_src=tmp_path / "app-src",
    )

    created = []
    monkeypatch.setattr(build_mod.AgiEnv, "_is_managed_pc", False, raising=False)
    monkeypatch.setattr(build_mod.AgiEnv, "logger", _DummyLogger(), raising=False)
    monkeypatch.setattr(build_mod.AgiEnv, "create_symlink", lambda src, dest: created.append((Path(src), Path(dest))))
    monkeypatch.setattr(build_mod.os, "link", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("hard link should not be used")))

    links = build_mod.create_symlink_for_module(env, "shared.pkg")

    assert len(links) == 1
    assert created[0][0] == src_abs
    assert created[0][1] == links[0]
    assert links[0].as_posix().endswith("src/agi_node/shared/pkg")


def test_build_cleanup_links_removes_empty_parent_tree(tmp_path):
    link = tmp_path / "src" / "agi_node" / "demo_worker"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.write_text("x", encoding="utf-8")

    build_mod.AgiEnv.logger = SimpleNamespace(
        info=lambda *_args, **_kwargs: None,
        warning=lambda *_args, **_kwargs: None,
        error=lambda *_args, **_kwargs: None,
        debug=lambda *_args, **_kwargs: None,
    )
    build_mod.cleanup_links([link])

    assert not link.exists()
    assert not link.parent.exists()


def test_build_cleanup_links_stops_when_parent_not_empty(tmp_path):
    link = tmp_path / "src" / "agi_node" / "demo_worker"
    sibling = tmp_path / "src" / "agi_node" / "keep.txt"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.write_text("x", encoding="utf-8")
    sibling.write_text("keep", encoding="utf-8")

    build_mod.AgiEnv.logger = SimpleNamespace(
        info=lambda *_args, **_kwargs: None,
        warning=lambda *_args, **_kwargs: None,
        error=lambda *_args, **_kwargs: None,
        debug=lambda *_args, **_kwargs: None,
    )
    build_mod.cleanup_links([link])

    assert not link.exists()
    assert sibling.exists()
    assert link.parent.exists()


def test_build_cleanup_links_removes_directory_targets(tmp_path):
    target = tmp_path / "src" / "agi_node" / "demo_worker"
    target.mkdir(parents=True, exist_ok=True)
    (target / "payload.txt").write_text("x", encoding="utf-8")

    build_mod.AgiEnv.logger = SimpleNamespace(
        info=lambda *_args, **_kwargs: None,
        warning=lambda *_args, **_kwargs: None,
        error=lambda *_args, **_kwargs: None,
        debug=lambda *_args, **_kwargs: None,
    )
    build_mod.cleanup_links([target])

    assert not target.exists()


def test_build_cleanup_links_stops_on_parent_rmdir_oserror(tmp_path, monkeypatch):
    target = tmp_path / "src" / "agi_node" / "demo_worker.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("x", encoding="utf-8")

    original_rmdir = Path.rmdir

    def _patched_rmdir(self):
        if self == target.parent:
            raise OSError("busy")
        return original_rmdir(self)

    monkeypatch.setattr(build_mod.Path, "rmdir", _patched_rmdir, raising=False)
    build_mod.AgiEnv.logger = SimpleNamespace(
        info=lambda *_args, **_kwargs: None,
        warning=lambda *_args, **_kwargs: None,
        error=lambda *_args, **_kwargs: None,
        debug=lambda *_args, **_kwargs: None,
    )

    build_mod.cleanup_links([target])

    assert not target.exists()
    assert target.parent.exists()


def test_build_cleanup_links_logs_warning_when_link_probe_raises(tmp_path, monkeypatch):
    target = tmp_path / "src" / "agi_node" / "demo_worker.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("x", encoding="utf-8")
    warnings_seen = []

    monkeypatch.setattr(build_mod.AgiEnv, "logger", SimpleNamespace(
        info=lambda *_args, **_kwargs: None,
        warning=lambda *args, **_kwargs: warnings_seen.append(" ".join(str(arg) for arg in args)),
        error=lambda *_args, **_kwargs: None,
        debug=lambda *_args, **_kwargs: None,
    ), raising=False)

    original_exists = Path.exists

    def _patched_exists(self):
        if self == target:
            raise OSError("probe failed")
        return original_exists(self)

    monkeypatch.setattr(build_mod.Path, "exists", _patched_exists, raising=False)

    build_mod.cleanup_links([target])

    assert any("Failed to remove" in line for line in warnings_seen)


def test_build_cleanup_links_propagates_unexpected_probe_bug(tmp_path, monkeypatch):
    target = tmp_path / "src" / "agi_node" / "demo_worker.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("x", encoding="utf-8")

    original_exists = Path.exists

    def _patched_exists(self):
        if self == target:
            raise RuntimeError("probe bug")
        return original_exists(self)

    monkeypatch.setattr(build_mod.Path, "exists", _patched_exists, raising=False)

    with pytest.raises(RuntimeError, match="probe bug"):
        build_mod.cleanup_links([target])


def test_post_main_invalid_args_returns_usage_code():
    assert post_mod.main([]) == 1
    assert post_mod.main(["a", "b"]) == 1


def test_post_main_relative_app_arg_uses_home_wenv(tmp_path, monkeypatch):
    captured = {}

    class DummyEnv:
        share_target_name = "demo"
        dataset_archive = tmp_path / "missing.7z"
        agilab_pck = tmp_path / "pkg"

        def resolve_share_path(self, _target):
            return tmp_path / "share"

        def unzip_data(self, _archive, _dest):
            raise AssertionError("unzip_data should not be called when archive is missing")

        def share_root_path(self):
            return tmp_path / "share-root"

    monkeypatch.setattr(post_mod.Path, "home", staticmethod(lambda: tmp_path))

    def _fake_build_env(app_arg):
        captured["app_arg"] = app_arg
        return DummyEnv()

    monkeypatch.setattr(post_mod, "_build_env", _fake_build_env)
    monkeypatch.setattr(post_mod, "_dataset_archive_candidates", lambda _env: [tmp_path / "missing.7z"])

    assert post_mod.main(["demo_project"]) == 0
    assert captured["app_arg"] == tmp_path / "wenv" / "demo_project"


def test_post_main_missing_archive_returns_zero_without_unzip(tmp_path, monkeypatch):
    flags = {"unzipped": False}

    class DummyEnv:
        share_target_name = "demo"
        dataset_archive = tmp_path / "missing.7z"
        agilab_pck = tmp_path / "pkg"

        def resolve_share_path(self, _target):
            return tmp_path / "share"

        def unzip_data(self, _archive, _dest):
            flags["unzipped"] = True

        def share_root_path(self):
            return tmp_path / "share-root"

    monkeypatch.setattr(post_mod, "_build_env", lambda _app_arg: DummyEnv())
    monkeypatch.setattr(post_mod, "_dataset_archive_candidates", lambda _env: [tmp_path / "missing.7z"])

    assert post_mod.main([str(tmp_path / "demo_project")]) == 0
    assert flags["unzipped"] is False


def test_post_main_links_preferred_sat_trajectory(tmp_path, monkeypatch):
    dataset_archive = tmp_path / "dataset.7z"
    dataset_archive.write_text("x", encoding="utf-8")
    share_root = tmp_path / "share"
    preferred = share_root / "sat_trajectory" / "dataset" / "Trajectory"
    preferred.mkdir(parents=True, exist_ok=True)
    (preferred / "a.csv").write_text("1", encoding="utf-8")
    (preferred / "b.csv").write_text("2", encoding="utf-8")

    class DummyEnv:
        def __init__(self):
            self.share_target_name = "demo"
            self.dataset_archive = dataset_archive
            self.agilab_pck = tmp_path / "pkg"

        def resolve_share_path(self, _target):
            return tmp_path / "share-dest"

        def unzip_data(self, _archive, dest):
            (Path(dest) / "dataset").mkdir(parents=True, exist_ok=True)

        def share_root_path(self):
            return share_root

    link_calls = []

    def _fake_try_link(link_path, target_path):
        link_calls.append((Path(link_path), Path(target_path)))
        return True

    monkeypatch.setattr(post_mod, "_build_env", lambda _app_arg: DummyEnv())
    monkeypatch.setattr(post_mod, "_dataset_archive_candidates", lambda _env: [dataset_archive])
    monkeypatch.setattr(post_mod, "_try_link_dir", _fake_try_link)

    assert post_mod.main([str(tmp_path / "demo_project")]) == 0
    assert len(link_calls) == 1
    assert link_calls[0][0].name == "sat"
    assert link_calls[0][1] == preferred


def test_post_main_respects_preserve_existing_sat_flag(tmp_path, monkeypatch):
    dataset_archive = tmp_path / "dataset.7z"
    dataset_archive.write_text("x", encoding="utf-8")
    share_root = tmp_path / "share"
    preferred = share_root / "sat_trajectory" / "dataset" / "Trajectory"
    preferred.mkdir(parents=True, exist_ok=True)
    (preferred / "a.csv").write_text("1", encoding="utf-8")
    (preferred / "b.csv").write_text("2", encoding="utf-8")

    class DummyEnv:
        def __init__(self):
            self.share_target_name = "demo"
            self.dataset_archive = dataset_archive
            self.agilab_pck = tmp_path / "pkg"

        def resolve_share_path(self, _target):
            return tmp_path / "share-dest"

        def unzip_data(self, _archive, dest):
            sat = Path(dest) / "dataset" / "sat"
            sat.mkdir(parents=True, exist_ok=True)
            (sat / "x.csv").write_text("1", encoding="utf-8")
            (sat / "y.csv").write_text("2", encoding="utf-8")

        def share_root_path(self):
            return share_root

    called = {"link": False}

    monkeypatch.setattr(post_mod, "_build_env", lambda _app_arg: DummyEnv())
    monkeypatch.setattr(post_mod, "_dataset_archive_candidates", lambda _env: [dataset_archive])
    monkeypatch.setenv("AGILAB_PRESERVE_LINK_SIM_SAT", "1")
    monkeypatch.setattr(post_mod, "_try_link_dir", lambda *_args, **_kwargs: called.update(link=True))

    assert post_mod.main([str(tmp_path / "demo_project")]) == 0
    assert called["link"] is False


def test_post_main_keeps_existing_preferred_sat_symlink(tmp_path, monkeypatch):
    dataset_archive = tmp_path / "dataset.7z"
    dataset_archive.write_text("x", encoding="utf-8")
    share_root = tmp_path / "share"
    preferred = share_root / "sat_trajectory" / "dataset" / "Trajectory"
    preferred.mkdir(parents=True, exist_ok=True)
    (preferred / "a.csv").write_text("1", encoding="utf-8")
    (preferred / "b.csv").write_text("2", encoding="utf-8")

    class DummyEnv:
        def __init__(self):
            self.share_target_name = "demo"
            self.dataset_archive = dataset_archive
            self.agilab_pck = tmp_path / "pkg"

        def resolve_share_path(self, _target):
            return tmp_path / "share-dest"

        def unzip_data(self, _archive, dest):
            dataset_root = Path(dest) / "dataset"
            dataset_root.mkdir(parents=True, exist_ok=True)
            (dataset_root / "sat").symlink_to(preferred, target_is_directory=True)

        def share_root_path(self):
            return share_root

    called = {"link": False}

    monkeypatch.setattr(post_mod, "_build_env", lambda _app_arg: DummyEnv())
    monkeypatch.setattr(post_mod, "_dataset_archive_candidates", lambda _env: [dataset_archive])
    monkeypatch.setattr(post_mod, "_try_link_dir", lambda *_args, **_kwargs: called.update(link=True))

    assert post_mod.main([str(tmp_path / "demo_project")]) == 0
    assert called["link"] is False


def test_post_main_extracts_then_copies_when_link_unavailable(tmp_path, monkeypatch):
    dataset_archive = tmp_path / "dataset.7z"
    dataset_archive.write_text("x", encoding="utf-8")
    trajectory_archive = tmp_path / "Trajectory.7z"
    trajectory_archive.write_text("x", encoding="utf-8")

    class DummyEnv:
        def __init__(self):
            self.share_target_name = "demo"
            self.dataset_archive = dataset_archive
            self.agilab_pck = tmp_path / "pkg"

        def resolve_share_path(self, _target):
            return tmp_path / "share-dest"

        def unzip_data(self, _archive, dest):
            (Path(dest) / "dataset" / "sat").mkdir(parents=True, exist_ok=True)

        def share_root_path(self):
            return tmp_path / "share"

    def _fake_extract(_archive, dest):
        traj = Path(dest) / "Trajectory"
        traj.mkdir(parents=True, exist_ok=True)
        (traj / "a.csv").write_text("1", encoding="utf-8")
        (traj / "b.csv").write_text("2", encoding="utf-8")

    monkeypatch.setattr(post_mod, "_build_env", lambda _app_arg: DummyEnv())
    monkeypatch.setattr(post_mod, "_dataset_archive_candidates", lambda _env: [dataset_archive])
    monkeypatch.setattr(post_mod, "_extract_archive", _fake_extract)
    monkeypatch.setattr(post_mod, "_try_link_dir", lambda *_args, **_kwargs: False)

    assert post_mod.main([str(tmp_path / "demo_project")]) == 0
    sat = tmp_path / "share-dest" / "dataset" / "sat"
    assert (sat / "a.csv").exists()
    assert (sat / "b.csv").exists()


def test_post_main_ignores_optional_seeding_exception(tmp_path, monkeypatch):
    dataset_archive = tmp_path / "dataset.7z"
    dataset_archive.write_text("x", encoding="utf-8")

    class DummyEnv:
        def __init__(self):
            self.share_target_name = "demo"
            self.dataset_archive = dataset_archive
            self.agilab_pck = tmp_path / "pkg"

        def resolve_share_path(self, _target):
            return tmp_path / "share-dest"

        def unzip_data(self, _archive, dest):
            (Path(dest) / "dataset").mkdir(parents=True, exist_ok=True)

        def share_root_path(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(post_mod, "_build_env", lambda _app_arg: DummyEnv())
    monkeypatch.setattr(post_mod, "_dataset_archive_candidates", lambda _env: [dataset_archive])

    assert post_mod.main([str(tmp_path / "demo_project")]) == 0


class _DummyLogger:
    def info(self, *_args, **_kwargs):
        return None

    def warning(self, *_args, **_kwargs):
        return None

    def error(self, *_args, **_kwargs):
        return None

    def debug(self, *_args, **_kwargs):
        return None


def test_build_create_symlink_for_module_hardlink_fallback(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source_file = tmp_path / "app" / "demo_worker" / "module_a"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_text("payload", encoding="utf-8")

    env = SimpleNamespace(
        agi_node=tmp_path / "agi_node",
        agi_env=tmp_path / "agi_env",
        target_worker="demo_worker",
        app_src=tmp_path / "app",
    )

    monkeypatch.setattr(build_mod.AgiEnv, "_is_managed_pc", False, raising=False)
    monkeypatch.setattr(build_mod.AgiEnv, "logger", _DummyLogger(), raising=False)
    monkeypatch.setattr(
        build_mod.AgiEnv,
        "create_symlink",
        staticmethod(lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("symlink disabled"))),
        raising=False,
    )

    links = build_mod.create_symlink_for_module(env, "demo_worker.module_a")
    assert len(links) == 1
    dest = links[0]
    assert dest.exists()
    assert os.path.samefile(dest, source_file)


def test_build_create_symlink_for_module_managed_pc_raises_on_junction_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source_file = tmp_path / "app" / "demo_worker" / "module_a"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_text("payload", encoding="utf-8")

    env = SimpleNamespace(
        agi_node=tmp_path / "agi_node",
        agi_env=tmp_path / "agi_env",
        target_worker="demo_worker",
        app_src=tmp_path / "app",
    )

    monkeypatch.setattr(build_mod.AgiEnv, "_is_managed_pc", True, raising=False)
    monkeypatch.setattr(build_mod.AgiEnv, "logger", _DummyLogger(), raising=False)
    monkeypatch.setattr(
        build_mod.AgiEnv,
        "create_junction_windows",
        staticmethod(lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("junction disabled"))),
        raising=False,
    )

    with pytest.raises(OSError, match="junction disabled"):
        build_mod.create_symlink_for_module(env, "demo_worker.module_a")


def test_build_create_symlink_for_module_returns_empty_when_dest_exists(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source_file = tmp_path / "app" / "demo_worker" / "module_a"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_text("payload", encoding="utf-8")
    dest = tmp_path / "src" / "demo_worker" / "module_a"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("existing", encoding="utf-8")

    env = SimpleNamespace(
        agi_node=tmp_path / "agi_node",
        agi_env=tmp_path / "agi_env",
        target_worker="demo_worker",
        app_src=tmp_path / "app",
    )

    monkeypatch.setattr(build_mod.AgiEnv, "_is_managed_pc", False, raising=False)
    monkeypatch.setattr(build_mod.AgiEnv, "logger", _DummyLogger(), raising=False)

    assert build_mod.create_symlink_for_module(env, "demo_worker.module_a") == []


def test_build_create_symlink_for_module_raises_when_dest_absolute_fails(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source_file = tmp_path / "app" / "demo_worker" / "module_a"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_text("payload", encoding="utf-8")

    env = SimpleNamespace(
        agi_node=tmp_path / "agi_node",
        agi_env=tmp_path / "agi_env",
        target_worker="demo_worker",
        app_src=tmp_path / "app",
    )

    monkeypatch.setattr(build_mod.AgiEnv, "logger", _DummyLogger(), raising=False)
    original_absolute = build_mod.Path.absolute

    def _patched_absolute(self):
        if self == build_mod.Path("src") / "demo_worker" / "module_a":
            raise FileNotFoundError("missing source")
        return original_absolute(self)

    monkeypatch.setattr(build_mod.Path, "absolute", _patched_absolute, raising=False)

    with pytest.raises(FileNotFoundError, match="Source path does not exist"):
        build_mod.create_symlink_for_module(env, "demo_worker.module_a")


def test_build_create_symlink_for_module_raises_when_hard_link_fails(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source_file = tmp_path / "app" / "demo_worker" / "module_a"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_text("payload", encoding="utf-8")

    env = SimpleNamespace(
        agi_node=tmp_path / "agi_node",
        agi_env=tmp_path / "agi_env",
        target_worker="demo_worker",
        app_src=tmp_path / "app",
    )

    monkeypatch.setattr(build_mod.AgiEnv, "_is_managed_pc", False, raising=False)
    monkeypatch.setattr(build_mod.AgiEnv, "logger", _DummyLogger(), raising=False)
    monkeypatch.setattr(
        build_mod.AgiEnv,
        "create_symlink",
        staticmethod(lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("symlink disabled"))),
        raising=False,
    )
    monkeypatch.setattr(
        build_mod.os,
        "link",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("hard link disabled")),
    )

    with pytest.raises(OSError, match="hard link disabled"):
        build_mod.create_symlink_for_module(env, "demo_worker.module_a")


def test_build_create_symlink_for_module_propagates_unexpected_symlink_bug(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source_file = tmp_path / "app" / "demo_worker" / "module_a"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_text("payload", encoding="utf-8")

    env = SimpleNamespace(
        agi_node=tmp_path / "agi_node",
        agi_env=tmp_path / "agi_env",
        target_worker="demo_worker",
        app_src=tmp_path / "app",
    )

    monkeypatch.setattr(build_mod.AgiEnv, "_is_managed_pc", False, raising=False)
    monkeypatch.setattr(build_mod.AgiEnv, "logger", _DummyLogger(), raising=False)
    monkeypatch.setattr(
        build_mod.AgiEnv,
        "create_symlink",
        staticmethod(lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("symlink bug"))),
        raising=False,
    )
    monkeypatch.setattr(
        build_mod.os,
        "link",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("hard link fallback should not run")),
    )

    with pytest.raises(RuntimeError, match="symlink bug"):
        build_mod.create_symlink_for_module(env, "demo_worker.module_a")


def test_build_cleanup_links_removes_file_and_empty_parents(tmp_path):
    target = tmp_path / "a" / "agi_node" / "demo" / "payload.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("x", encoding="utf-8")
    build_mod.AgiEnv.logger = type(
        "Logger",
        (),
        {
            "info": staticmethod(lambda *_args, **_kwargs: None),
            "warning": staticmethod(lambda *_args, **_kwargs: None),
        },
    )()

    build_mod.cleanup_links([target])
    assert not target.exists()
    assert not (tmp_path / "a" / "agi_node" / "demo").exists()


def test_build_force_remove_tree_handles_missing_and_chmod_failure(tmp_path, monkeypatch):
    missing = tmp_path / "missing"
    build_mod._force_remove_tree(missing)
    assert not missing.exists()

    target = tmp_path / "target"
    target.mkdir(parents=True, exist_ok=True)
    (target / "payload.txt").write_text("x", encoding="utf-8")
    run_calls = []

    monkeypatch.setattr(build_mod.os, "name", "posix", raising=False)
    monkeypatch.setattr(build_mod.os, "chmod", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("chmod denied")))
    monkeypatch.setattr(build_mod.subprocess, "run", lambda args, check=False, capture_output=True: run_calls.append((args, check, capture_output)))

    build_mod._force_remove_tree(target)

    assert not target.exists()
    assert run_calls == [(["chmod", "-R", "u+rwx", str(target)], False, True)]


def test_build_force_remove_tree_windows_skips_recursive_chmod(tmp_path, monkeypatch):
    target = tmp_path / "target"
    target.mkdir(parents=True, exist_ok=True)
    removed = []
    run_calls = []
    posix_path_cls = type(Path("/tmp"))

    monkeypatch.setattr(build_mod.os, "name", "nt", raising=False)
    monkeypatch.setattr(build_mod.os, "chmod", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(build_mod.subprocess, "run", lambda *args, **kwargs: run_calls.append((args, kwargs)))
    monkeypatch.setattr(build_mod.shutil, "rmtree", lambda path: removed.append(posix_path_cls(path)))

    build_mod._force_remove_tree(target)

    assert len(removed) == 1
    assert str(removed[0]).replace("\\", "/").endswith("/target")
    assert run_calls == []


def test_build_force_remove_tree_propagates_unexpected_chmod_bug(tmp_path, monkeypatch):
    target = tmp_path / "target"
    target.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(build_mod.os, "chmod", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("chmod bug")))
    monkeypatch.setattr(
        build_mod.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("recursive chmod should not run")),
    )

    with pytest.raises(RuntimeError, match="chmod bug"):
        build_mod._force_remove_tree(target)


def test_build_purge_worker_venv_artifacts_removes_unique_candidates(tmp_path, monkeypatch):
    app_root = tmp_path / "app"
    worker_module = "demo_worker"
    candidates = [
        app_root / "src" / worker_module / ".venv",
        app_root / "build" / "lib" / worker_module / ".venv",
        app_root / "build" / "bdist.any" / "egg" / worker_module / ".venv",
    ]
    for candidate in candidates:
        candidate.mkdir(parents=True, exist_ok=True)

    build_mod.logger = _DummyLogger()
    removed = []
    monkeypatch.setattr(build_mod, "_force_remove_tree", lambda path: removed.append(path))

    result = build_mod._purge_worker_venv_artifacts(app_root, worker_module)

    assert result == [candidate.resolve(strict=False) for candidate in candidates]
    assert removed == result


def test_build_main_build_ext_without_app_path_uses_script_dir_and_logs_purged_venvs(tmp_path, monkeypatch):
    script_dir = tmp_path / "scripts"
    script_dir.mkdir(parents=True, exist_ok=True)
    worker_home = tmp_path / "home"
    worker_file = worker_home / "workers" / "demo_worker.py"
    worker_file.parent.mkdir(parents=True, exist_ok=True)
    worker_file.write_text("value = 1\n", encoding="utf-8")
    worker_file.with_suffix(".pyx").write_text("value = 1\n", encoding="utf-8")
    out_dir = worker_home / "demo_worker"
    out_dir.mkdir(parents=True, exist_ok=True)
    (script_dir / "README.md").write_text("existing", encoding="utf-8")
    purged = [tmp_path / "purged" / ".venv"]
    logger_info = []

    class DummyAgiEnv:
        logger = _DummyLogger()
        _is_managed_pc = False
        init_args = None

        def __init__(self, *, apps_path=None, active_app, verbose):
            DummyAgiEnv.init_args = {
                "apps_path": apps_path,
                "active_app": active_app,
                "verbose": verbose,
            }
            self.home_abs = str(worker_home)
            self.worker_path = str(worker_file)
            self.pre_install = None
            self.verbose = verbose
            self.pyvers_worker = "3.13"
            self.is_worker_env = False
            self.active_app = Path(active_app)
            self.target_worker = "demo_worker"
            self.agi_node = tmp_path / "agi_node"
            self.agi_env = tmp_path / "agi_env"
            self.app_src = script_dir

    monkeypatch.setattr(build_mod, "__file__", str(script_dir / "build.py"), raising=False)
    monkeypatch.setattr(build_mod, "AgiEnv", DummyAgiEnv)
    monkeypatch.setattr(build_mod, "find_sys_prefix", lambda _base: str(tmp_path / "prefix"))
    monkeypatch.setattr(build_mod, "find_packages", lambda where="src": ["demo_worker"])
    monkeypatch.setattr(build_mod, "_purge_worker_venv_artifacts", lambda *_args, **_kwargs: purged)
    monkeypatch.setattr(build_mod, "logger", SimpleNamespace(info=lambda *args, **_kwargs: logger_info.append(args)))
    monkeypatch.setattr(build_mod, "cythonize", lambda modules, **_kwargs: ["ext_mod"])
    setup_calls = []
    monkeypatch.setattr(build_mod, "setup", lambda **kwargs: setup_calls.append(kwargs))

    build_mod.main(["build_ext", "-b", str(out_dir)])

    assert DummyAgiEnv.init_args is not None
    assert DummyAgiEnv.init_args["apps_path"] is None
    assert Path(DummyAgiEnv.init_args["active_app"]) == script_dir
    assert any("Purged nested worker virtualenv artifacts before %s: %s" in args[0] for args in logger_info)
    assert setup_calls and setup_calls[0]["name"] == "demo_worker"


def test_build_main_build_ext_invokes_pre_install_and_setup(tmp_path, monkeypatch):
    app_dir = tmp_path / "demo_project"
    (app_dir / "src" / "demo_worker").mkdir(parents=True, exist_ok=True)
    worker_home = tmp_path / "home"
    worker_file = worker_home / "workers" / "demo_worker.py"
    worker_file.parent.mkdir(parents=True, exist_ok=True)
    worker_file.write_text("value = 1\n", encoding="utf-8")
    pre_script = tmp_path / "pre_install.py"
    pre_script.write_text("print('ok')\n", encoding="utf-8")
    out_dir = worker_home / "demo_worker"
    out_dir.mkdir(parents=True, exist_ok=True)

    class DummyAgiEnv:
        logger = _DummyLogger()
        _is_managed_pc = False

        @staticmethod
        def create_symlink(src, dest):
            os.symlink(src, dest)

        @staticmethod
        def create_junction_windows(_src, _dest):
            return None

        init_args = None

        def __init__(self, *, apps_path=None, active_app, verbose):
            DummyAgiEnv.init_args = {
                "apps_path": apps_path,
                "active_app": active_app,
                "verbose": verbose,
            }
            self.home_abs = str(worker_home)
            self.worker_path = str(worker_file.relative_to(worker_home))
            self.pre_install = str(pre_script)
            self.verbose = verbose
            self.pyvers_worker = "3.13"
            self.is_worker_env = True
            self.active_app = app_dir
            self.target_worker = "demo_worker"
            self.agi_node = tmp_path / "agi_node"
            self.agi_env = tmp_path / "agi_env"
            self.app_src = app_dir

    monkeypatch.setattr(build_mod, "AgiEnv", DummyAgiEnv)
    monkeypatch.setattr(build_mod, "find_sys_prefix", lambda _base: str(tmp_path / "prefix"))
    monkeypatch.setattr(build_mod, "find_packages", lambda where="src": ["demo_worker"])

    run_calls = []
    monkeypatch.setattr(build_mod.subprocess, "run", lambda cmd, check=True: run_calls.append((cmd, check)))
    cythonize_calls = []
    monkeypatch.setattr(
        build_mod,
        "cythonize",
        lambda modules, language_level=3, quiet=False, compiler_directives=None, cache=False: (
            cythonize_calls.append((modules, quiet, compiler_directives)) or ["ext_mod"]
        ),
    )
    setup_calls = []
    monkeypatch.setattr(build_mod, "setup", lambda **kwargs: setup_calls.append(kwargs))

    build_mod.main(
        [
            "--app-path",
            str(app_dir),
            "build_ext",
            "-b",
            str(out_dir),
            "--packages",
            "pkg_a,pkg_b",
            "--quiet",
        ]
    )

    assert DummyAgiEnv.init_args is not None
    assert DummyAgiEnv.init_args["apps_path"] is None
    assert Path(DummyAgiEnv.init_args["active_app"]) == app_dir
    assert run_calls, "Expected pre_install subprocess to run when .pyx is missing"
    assert cythonize_calls, "Expected Cythonize to be invoked for build_ext"
    assert cythonize_calls[0][1] is True, "Expected quiet=True when --quiet is passed"
    assert setup_calls and setup_calls[0]["name"] == "demo_worker"


def test_resolve_pre_install_script_falls_back_to_installed_module(tmp_path, monkeypatch):
    missing_pre_script = tmp_path / "missing_pre_install.py"
    fallback_script = tmp_path / "fallback_pre_install.py"
    fallback_script.write_text("print('fallback')\n", encoding="utf-8")

    monkeypatch.setattr(
        build_mod,
        "_load_pre_install_module",
        lambda: SimpleNamespace(__file__=str(fallback_script)),
    )

    env = SimpleNamespace(pre_install=str(missing_pre_script))

    assert build_mod._resolve_pre_install_script(env) == fallback_script.resolve()


def test_resolve_pre_install_script_handles_missing_module_and_missing_raw_path(tmp_path, monkeypatch):
    missing_pre_script = tmp_path / "missing_pre_install.py"

    monkeypatch.setattr(
        build_mod,
        "_load_pre_install_module",
        lambda: (_ for _ in ()).throw(ModuleNotFoundError("no module")),
    )

    env = SimpleNamespace(pre_install=str(missing_pre_script))
    assert build_mod._resolve_pre_install_script(env) == missing_pre_script

    assert build_mod._resolve_pre_install_script(SimpleNamespace(pre_install=None)) is None


def test_build_main_build_ext_uses_fallback_pre_install_module(tmp_path, monkeypatch):
    app_dir = tmp_path / "demo_project"
    (app_dir / "src" / "demo_worker").mkdir(parents=True, exist_ok=True)
    worker_home = tmp_path / "home"
    worker_file = worker_home / "workers" / "demo_worker.py"
    worker_file.parent.mkdir(parents=True, exist_ok=True)
    worker_file.write_text("value = 1\n", encoding="utf-8")
    fallback_pre_script = tmp_path / "fallback_pre_install.py"
    fallback_pre_script.write_text("print('ok')\n", encoding="utf-8")
    out_dir = worker_home / "demo_worker"
    out_dir.mkdir(parents=True, exist_ok=True)

    class DummyAgiEnv:
        logger = _DummyLogger()
        _is_managed_pc = False

        def __init__(self, *, apps_path=None, active_app, verbose):
            self.home_abs = str(worker_home)
            self.worker_path = str(worker_file.relative_to(worker_home))
            self.pre_install = str(tmp_path / "missing_pre_install.py")
            self.verbose = verbose
            self.pyvers_worker = "3.13"
            self.is_worker_env = True
            self.active_app = app_dir
            self.target_worker = "demo_worker"
            self.agi_node = tmp_path / "agi_node"
            self.agi_env = tmp_path / "agi_env"
            self.app_src = app_dir

    monkeypatch.setattr(build_mod, "AgiEnv", DummyAgiEnv)
    monkeypatch.setattr(
        build_mod,
        "_load_pre_install_module",
        lambda: SimpleNamespace(__file__=str(fallback_pre_script)),
    )
    monkeypatch.setattr(build_mod, "find_sys_prefix", lambda _base: str(tmp_path / "prefix"))
    monkeypatch.setattr(build_mod, "find_packages", lambda where="src": ["demo_worker"])

    run_calls = []
    monkeypatch.setattr(build_mod.subprocess, "run", lambda cmd, check=True: run_calls.append((cmd, check)))
    monkeypatch.setattr(build_mod, "cythonize", lambda modules, **_kwargs: ["ext_mod"])
    monkeypatch.setattr(build_mod, "setup", lambda **_kwargs: None)

    build_mod.main(
        [
            "--app-path",
            str(app_dir),
            "build_ext",
            "-b",
            str(out_dir),
            "--quiet",
        ]
    )

    assert run_calls
    assert run_calls[0][0][1] == str(fallback_pre_script.resolve())


def test_build_main_build_ext_rejects_missing_outdir(tmp_path, monkeypatch):
    app_dir = tmp_path / "demo_project"
    app_dir.mkdir(parents=True, exist_ok=True)

    class DummyAgiEnv:
        logger = _DummyLogger()
        _is_managed_pc = False

        def __init__(self, *, apps_path=None, active_app, verbose):
            self.home_abs = str(tmp_path / "home")
            self.worker_path = "workers/demo_worker.py"
            self.pre_install = None
            self.verbose = verbose
            self.pyvers_worker = "3.13"
            self.is_worker_env = True
            self.active_app = app_dir
            self.target_worker = "demo_worker"
            self.agi_node = tmp_path / "agi_node"
            self.agi_env = tmp_path / "agi_env"
            self.app_src = app_dir

    monkeypatch.setattr(build_mod, "AgiEnv", DummyAgiEnv)
    monkeypatch.setattr(
        build_mod,
        "parse_custom_args",
        lambda _remaining, _active_app: Namespace(
            command="build_ext",
            packages=[],
            build_dir=None,
            dist_dir=str(tmp_path / "out"),
            remaining=[],
        ),
    )

    with pytest.raises(RuntimeError, match="Cannot determine target package name"):
        build_mod.main(["--app-path", str(app_dir)])


def test_build_main_build_ext_logs_truncate_path_failure(tmp_path, monkeypatch):
    app_dir = tmp_path / "demo_project"
    app_dir.mkdir(parents=True, exist_ok=True)
    errors = []

    class DummyLoggerWithError(_DummyLogger):
        def error(self, *args, **_kwargs):
            errors.append(" ".join(str(arg) for arg in args))

    class DummyAgiEnv:
        logger = DummyLoggerWithError()
        _is_managed_pc = False

        def __init__(self, *, apps_path=None, active_app, verbose):
            self.home_abs = str(tmp_path / "home")
            self.worker_path = "workers/demo_worker.py"
            self.pre_install = None
            self.verbose = verbose
            self.pyvers_worker = "3.13"
            self.is_worker_env = True
            self.active_app = app_dir
            self.target_worker = "demo_worker"
            self.agi_node = tmp_path / "agi_node"
            self.agi_env = tmp_path / "agi_env"
            self.app_src = app_dir

    monkeypatch.setattr(build_mod, "AgiEnv", DummyAgiEnv)
    monkeypatch.setattr(
        build_mod,
        "parse_custom_args",
        lambda _remaining, _active_app: Namespace(
            command="build_ext",
            packages=[],
            build_dir=str(tmp_path / "invalid"),
            dist_dir=str(tmp_path / "out"),
            remaining=[],
        ),
    )
    monkeypatch.setattr(build_mod, "truncate_path_at_segment", lambda _path: (_ for _ in ()).throw(ValueError("bad path")))

    with pytest.raises(ValueError, match="bad path"):
        build_mod.main(["--app-path", str(app_dir)])

    assert any("bad path" in line for line in errors)


def test_build_main_build_ext_free_threaded_nonquiet_uses_worker_resolve_fallback(tmp_path, monkeypatch):
    app_dir = tmp_path / "demo_project"
    (app_dir / "src" / "demo_worker").mkdir(parents=True, exist_ok=True)
    worker_home = tmp_path / "home"
    worker_file = worker_home / "workers" / "demo_worker.py"
    worker_file.parent.mkdir(parents=True, exist_ok=True)
    worker_file.write_text("value = 1\n", encoding="utf-8")
    pre_script = tmp_path / "pre_install.py"
    pre_script.write_text("print('ok')\n", encoding="utf-8")
    out_dir = worker_home / "demo_worker"
    out_dir.mkdir(parents=True, exist_ok=True)

    class DummyAgiEnv:
        logger = _DummyLogger()
        _is_managed_pc = False

        init_args = None

        def __init__(self, *, apps_path=None, active_app, verbose):
            DummyAgiEnv.init_args = {
                "apps_path": apps_path,
                "active_app": active_app,
                "verbose": verbose,
            }
            self.home_abs = str(worker_home)
            self.worker_path = "workers/demo_worker.py"
            self.pre_install = str(pre_script)
            self.verbose = verbose
            self.pyvers_worker = "3.13t"
            self.is_worker_env = True
            self.active_app = app_dir
            self.target_worker = "demo_worker"
            self.agi_node = tmp_path / "agi_node"
            self.agi_env = tmp_path / "agi_env"
            self.app_src = app_dir

    original_resolve = build_mod.Path.resolve
    fallback_target = worker_home / "workers" / "demo_worker.py"

    def _patched_resolve(self, *args, **kwargs):
        if self == fallback_target:
            raise OSError("resolve failed")
        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(build_mod, "AgiEnv", DummyAgiEnv)
    monkeypatch.setattr(build_mod.Path, "resolve", _patched_resolve, raising=False)
    monkeypatch.setattr(build_mod, "find_sys_prefix", lambda _base: str(tmp_path / "prefix"))
    monkeypatch.setattr(build_mod, "find_packages", lambda where="src": ["demo_worker"])
    monkeypatch.setattr(build_mod.sys, "platform", "win32", raising=False)

    run_calls = []
    monkeypatch.setattr(build_mod.subprocess, "run", lambda cmd, check=True: run_calls.append((cmd, check)))
    cythonize_calls = []

    def _fake_cythonize(modules, language_level=3, quiet=False, compiler_directives=None, cache=False):
        cythonize_calls.append((modules, quiet, compiler_directives))
        return ["ext_mod"]

    monkeypatch.setattr(build_mod, "cythonize", _fake_cythonize)
    setup_calls = []
    monkeypatch.setattr(build_mod, "setup", lambda **kwargs: setup_calls.append(kwargs))

    build_mod.main(
        [
            "--app-path",
            str(app_dir),
            "build_ext",
            "-b",
            str(out_dir),
            "--packages",
            "pkg_a",
        ]
    )

    assert run_calls, "Expected pre_install subprocess to run when .pyx is missing"
    assert "--verbose" in run_calls[0][0]
    assert cythonize_calls and cythonize_calls[0][1] is False
    ext = cythonize_calls[0][0][0]
    assert ("Py_GIL_DISABLED", "1") in ext.define_macros
    assert cythonize_calls[0][2] == {"freethreading_compatible": True}
    assert setup_calls and setup_calls[0]["name"] == "demo_worker"


def test_build_main_build_ext_propagates_unexpected_worker_resolve_bug(tmp_path, monkeypatch):
    app_dir = tmp_path / "demo_project"
    (app_dir / "src" / "demo_worker").mkdir(parents=True, exist_ok=True)
    worker_home = tmp_path / "home"
    worker_file = worker_home / "workers" / "demo_worker.py"
    worker_file.parent.mkdir(parents=True, exist_ok=True)
    worker_file.write_text("value = 1\n", encoding="utf-8")
    pre_script = tmp_path / "pre_install.py"
    pre_script.write_text("print('ok')\n", encoding="utf-8")
    out_dir = worker_home / "demo_worker"
    out_dir.mkdir(parents=True, exist_ok=True)

    class DummyAgiEnv:
        logger = _DummyLogger()
        _is_managed_pc = False

        def __init__(self, *, apps_path=None, active_app, verbose):
            self.home_abs = str(worker_home)
            self.worker_path = "workers/demo_worker.py"
            self.pre_install = str(pre_script)
            self.verbose = verbose
            self.pyvers_worker = "3.13"
            self.is_worker_env = True
            self.active_app = app_dir
            self.target_worker = "demo_worker"
            self.agi_node = tmp_path / "agi_node"
            self.agi_env = tmp_path / "agi_env"
            self.app_src = app_dir

    original_resolve = build_mod.Path.resolve
    fallback_target = worker_home / "workers" / "demo_worker.py"

    def _patched_resolve(self, *args, **kwargs):
        if self == fallback_target:
            raise RuntimeError("resolve bug")
        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(build_mod, "AgiEnv", DummyAgiEnv)
    monkeypatch.setattr(build_mod.Path, "resolve", _patched_resolve, raising=False)
    monkeypatch.setattr(build_mod, "find_sys_prefix", lambda _base: str(tmp_path / "prefix"))
    monkeypatch.setattr(build_mod, "find_packages", lambda where="src": ["demo_worker"])
    monkeypatch.setattr(build_mod, "cythonize", lambda modules, **_kwargs: ["ext_mod"])
    monkeypatch.setattr(build_mod, "setup", lambda **_kwargs: None)

    with pytest.raises(RuntimeError, match="resolve bug"):
        build_mod.main(
            [
                "--app-path",
                str(app_dir),
                "build_ext",
                "-b",
                str(out_dir),
            ]
        )


def test_build_main_bdist_egg_unpacks_and_cleans_links(tmp_path, monkeypatch):
    app_dir = tmp_path / "demo_project"
    app_dir.mkdir(parents=True, exist_ok=True)
    worker_home = tmp_path / "home"
    out_dir = worker_home / "demo_project"
    dist_dir = out_dir / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)

    egg_path = dist_dir / "demo_worker-0.1.0.egg"
    with ZipFile(egg_path, "w") as zf:
        zf.writestr("demo_worker/__init__.py", "")

    class DummyAgiEnv:
        logger = _DummyLogger()
        _is_managed_pc = False

        @staticmethod
        def create_symlink(src, dest):
            os.symlink(src, dest)

        @staticmethod
        def create_junction_windows(_src, _dest):
            return None

        init_args = None

        def __init__(self, *, apps_path=None, active_app, verbose):
            DummyAgiEnv.init_args = {
                "apps_path": apps_path,
                "active_app": active_app,
                "verbose": verbose,
            }
            self.home_abs = str(worker_home)
            self.worker_path = "workers/demo_worker.py"
            self.pre_install = None
            self.verbose = verbose
            self.pyvers_worker = "3.13"
            self.is_worker_env = False
            self.active_app = app_dir
            self.target_worker = "demo_worker"
            self.agi_node = tmp_path / "agi_node"
            self.agi_env = tmp_path / "agi_env"
            self.app_src = app_dir

    monkeypatch.setattr(build_mod, "AgiEnv", DummyAgiEnv)
    monkeypatch.setattr(build_mod, "find_packages", lambda where="src": ["demo_worker"])
    monkeypatch.setattr(build_mod, "setup", lambda **_kwargs: None)

    links_created = [tmp_path / "src" / "demo_worker" / "module_link"]
    links_created[0].parent.mkdir(parents=True, exist_ok=True)
    links_created[0].write_text("x", encoding="utf-8")
    monkeypatch.setattr(build_mod, "create_symlink_for_module", lambda *_args, **_kwargs: links_created)

    cleanup_calls = []
    monkeypatch.setattr(build_mod, "cleanup_links", lambda links: cleanup_calls.append(list(links)))
    os_calls = []
    monkeypatch.setattr(build_mod.os, "system", lambda cmd: os_calls.append(cmd) or 0)

    build_mod.main(
        [
            "--app-path",
            str(app_dir),
            "bdist_egg",
            "-d",
            str(out_dir),
            "--packages",
            "agi_env.tools",
        ]
    )

    assert DummyAgiEnv.init_args is not None
    assert DummyAgiEnv.init_args["apps_path"] is None
    assert Path(DummyAgiEnv.init_args["active_app"]) == app_dir
    extracted = out_dir / "src" / "demo_worker" / "__init__.py"
    assert extracted.exists()
    assert os_calls and "remove_decorators" in os_calls[0]
    assert cleanup_calls and cleanup_calls[0] == links_created


def test_build_main_bdist_egg_filelike_outdir_uses_parent_directory(tmp_path, monkeypatch):
    app_dir = tmp_path / "demo_project"
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "README.md").write_text("existing", encoding="utf-8")
    worker_home = tmp_path / "home"
    filelike_out = worker_home / "exports" / "demo_worker.whl"
    filelike_out.parent.mkdir(parents=True, exist_ok=True)
    warnings_seen = []

    class DummyAgiEnv:
        logger = SimpleNamespace(
            info=lambda *_args, **_kwargs: None,
            warning=lambda *args, **_kwargs: warnings_seen.append(" ".join(str(arg) for arg in args)),
            error=lambda *_args, **_kwargs: None,
            debug=lambda *_args, **_kwargs: None,
        )
        _is_managed_pc = False

        def __init__(self, *, apps_path=None, active_app, verbose):
            self.home_abs = str(worker_home)
            self.worker_path = str(worker_home / "workers" / "demo_worker.py")
            self.pre_install = None
            self.verbose = verbose
            self.pyvers_worker = "3.13"
            self.is_worker_env = True
            self.active_app = app_dir
            self.target_worker = "demo_worker"
            self.agi_node = tmp_path / "agi_node"
            self.agi_env = tmp_path / "agi_env"
            self.app_src = app_dir

    monkeypatch.setattr(build_mod, "AgiEnv", DummyAgiEnv)
    monkeypatch.setattr(build_mod, "find_packages", lambda where="src": [])
    setup_calls = []
    monkeypatch.setattr(build_mod, "setup", lambda **kwargs: setup_calls.append(kwargs))

    build_mod.main(
        [
            "--app-path",
            str(app_dir),
            "bdist_egg",
            "-d",
            str(filelike_out),
        ]
    )

    assert any("looks like a file" in line for line in warnings_seen)
    assert Path(build_mod.sys.argv[3]) == worker_home / "exports" / "dist"
    assert setup_calls


def test_build_main_bdist_egg_outdir_outside_home_uses_absolute_fallback(tmp_path, monkeypatch):
    app_dir = tmp_path / "demo_project"
    app_dir.mkdir(parents=True, exist_ok=True)
    worker_home = tmp_path / "home"
    external_out = tmp_path / "external" / "demo_worker"
    external_out.mkdir(parents=True, exist_ok=True)

    class DummyAgiEnv:
        logger = _DummyLogger()
        _is_managed_pc = False

        def __init__(self, *, apps_path=None, active_app, verbose):
            self.home_abs = str(worker_home)
            self.worker_path = str(worker_home / "workers" / "demo_worker.py")
            self.pre_install = None
            self.verbose = verbose
            self.pyvers_worker = "3.13"
            self.is_worker_env = True
            self.active_app = app_dir
            self.target_worker = "demo_worker"
            self.agi_node = tmp_path / "agi_node"
            self.agi_env = tmp_path / "agi_env"
            self.app_src = app_dir

    monkeypatch.setattr(build_mod, "AgiEnv", DummyAgiEnv)
    monkeypatch.setattr(build_mod, "find_packages", lambda where="src": [])
    monkeypatch.setattr(build_mod, "setup", lambda **_kwargs: None)

    build_mod.main(
        [
            "--app-path",
            str(app_dir),
            "bdist_egg",
            "-d",
            str(external_out),
        ]
    )

    assert Path(build_mod.sys.argv[3]) == external_out / "dist"


def test_build_main_bdist_egg_propagates_unexpected_relative_to_bug(tmp_path, monkeypatch):
    app_dir = tmp_path / "demo_project"
    app_dir.mkdir(parents=True, exist_ok=True)
    worker_home = tmp_path / "home"
    external_out = tmp_path / "external" / "demo_worker"
    external_out.mkdir(parents=True, exist_ok=True)

    class DummyAgiEnv:
        logger = _DummyLogger()
        _is_managed_pc = False

        def __init__(self, *, apps_path=None, active_app, verbose):
            self.home_abs = str(worker_home)
            self.worker_path = str(worker_home / "workers" / "demo_worker.py")
            self.pre_install = None
            self.verbose = verbose
            self.pyvers_worker = "3.13"
            self.is_worker_env = True
            self.active_app = app_dir
            self.target_worker = "demo_worker"
            self.agi_node = tmp_path / "agi_node"
            self.agi_env = tmp_path / "agi_env"
            self.app_src = app_dir

    original_relative_to = build_mod.Path.relative_to

    def _patched_relative_to(self, *args, **kwargs):
        if self == external_out:
            raise RuntimeError("relative_to bug")
        return original_relative_to(self, *args, **kwargs)

    monkeypatch.setattr(build_mod, "AgiEnv", DummyAgiEnv)
    monkeypatch.setattr(build_mod.Path, "relative_to", _patched_relative_to, raising=False)
    monkeypatch.setattr(build_mod, "find_packages", lambda where="src": [])
    monkeypatch.setattr(build_mod, "setup", lambda **_kwargs: None)

    with pytest.raises(RuntimeError, match="relative_to bug"):
        build_mod.main(
            [
                "--app-path",
                str(app_dir),
                "bdist_egg",
                "-d",
                str(external_out),
            ]
        )
