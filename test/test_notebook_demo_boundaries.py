"""Regression coverage for packaged demos and shared interpreter state."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
from pathlib import Path
import shutil
import sys
from threading import Event
import tomllib
from types import ModuleType
import zipfile

import pytest

from agilab.agent_runtime import free_threading_showcase, milp_energy_showcase
from agilab.agent_runtime import notebook_showcase as iris

ROOT = Path(__file__).resolve().parents[1]


def test_every_public_demo_receipt_is_included_in_package_data():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    package = ROOT / "src/agilab"
    shipped = {
        path.relative_to(package).as_posix()
        for pattern in config["tool"]["setuptools"]["package-data"]["agilab"]
        for path in package.glob(pattern) if path.is_file()
    }
    missing = []
    for receipt in sorted((package / "resources").glob("*/result.json")):
        report = json.loads(receipt.read_text())
        if report.get("schema") != "agilab.notebook_agent.public_demo.v1":
            continue
        for name in (*report["files"], "result.json"):
            relative = (receipt.parent / name).relative_to(package).as_posix()
            if relative not in shipped:
                missing.append(relative)
    assert not missing, f"Public demo artifacts missing from wheel configuration: {missing}"


@pytest.mark.parametrize("first,second", [
    (free_threading_showcase, milp_energy_showcase),
    (milp_energy_showcase, free_threading_showcase),
])
def test_concurrent_demos_cannot_replace_each_others_pool(first, second, monkeypatch):
    """Hold one live render, then attempt the other on the caller's thread."""
    state = ModuleType("demo_concurrency_fixture")
    state.entered, state.release = Event(), Event()
    original = ModuleType("agilab_pool")
    monkeypatch.setitem(sys.modules, state.__name__, state)
    monkeypatch.setitem(sys.modules, "agilab_pool", original)
    messages = []
    monkeypatch.setattr(second.st, "info", messages.append)

    def payload(label, wait=False):
        modules = ("agilab_pool", "energy_core", "energy_runner",
                   "free_threading_core", "benchmark")
        files = {f"{name}.py": b"" for name in modules}
        files["agilab_pool.py"] = f"label = {label!r}\n".encode()
        files["app.py"] = (
            "import sys, demo_concurrency_fixture as state\n"
            "state.entered.set()\n"
            "assert state.release.wait(5), 'test coordination timed out'\n"
            f"assert sys.modules['agilab_pool'].label == {label!r}\n"
            if wait else "import demo_concurrency_fixture as state\nstate.overlapped = True\n"
        ).encode()
        return files

    with ThreadPoolExecutor(max_workers=1) as executor:
        task = executor.submit(first._run_verified_app, payload("first", wait=True))
        try:
            assert state.entered.wait(5)
            second._run_verified_app(payload("second"))
            assert not getattr(state, "overlapped", False), "Two demos replaced shared imports concurrently"
            assert messages
        finally:
            state.release.set()
            task.result(timeout=5)
    assert sys.modules["agilab_pool"] is original


@pytest.fixture
def iris_bundle(tmp_path, monkeypatch):
    target = tmp_path / "iris"
    shutil.copytree(iris.DEMO_ROOT, target, ignore=shutil.ignore_patterns("__pycache__"))
    monkeypatch.setattr(iris, "DEMO_ROOT", target)
    # The old implementation cached without any file identity in the key.
    if hasattr(iris.download_bundle, "clear"):
        iris.download_bundle.clear()
    yield target
    if hasattr(iris.download_bundle, "clear"):
        iris.download_bundle.clear()


@pytest.mark.parametrize("defect", ["empty", "missing-model", "failed", "failed-check", "extra"])
def test_iris_rejects_incomplete_receipts_and_unlisted_code(iris_bundle, defect):
    path = iris_bundle / "result.json"
    report = json.loads(path.read_text())
    if defect == "empty":
        report["files"] = {}
    elif defect == "missing-model":
        report["files"].pop("models.py")
    elif defect == "failed":
        report["status"] = "failed"
    elif defect == "failed-check":
        report["verification"]["status"] = "failed"
    else:
        (iris_bundle / "unexpected.py").write_text("value = 'unverified'\n")
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError):
        iris.load_report()


def test_iris_download_rechecks_files_after_a_successful_download(iris_bundle):
    with zipfile.ZipFile(io.BytesIO(iris.download_bundle())) as archive:
        report = json.loads(archive.read("result.json"))
        assert hashlib.sha256(archive.read("app.py")).hexdigest() == report["files"]["app.py"]
    (iris_bundle / "app.py").write_text("changed = True\n")
    with pytest.raises(ValueError, match="changed"):
        iris.download_bundle()


def test_iris_executes_the_verified_snapshot_and_restores_imports(iris_bundle, monkeypatch):
    _, payload = iris._read_verified_bundle()
    # A changed path must not replace the already verified snapshot at execution.
    (iris_bundle / "models.py").write_text("raise AssertionError('reread changed file')\n")
    (iris_bundle / "app.py").write_text("raise AssertionError('reread changed app')\n")
    original = ModuleType("models")
    monkeypatch.setitem(sys.modules, "models", original)
    from streamlit.testing.v1 import AppTest

    def page(payload):
        from agilab.agent_runtime.notebook_showcase import _run_verified_app
        _run_verified_app(payload)

    at = AppTest.from_function(page, args=(payload,), default_timeout=30).run()
    assert not at.exception
    assert any(title.value == "Iris decision lab" for title in at.title)
    assert sys.modules["models"] is original


def test_iris_invalid_receipt_shows_an_error_without_executing(iris_bundle, monkeypatch):
    from streamlit.testing.v1 import AppTest

    (iris_bundle / "result.json").write_text('{"status": "failed"}')
    monkeypatch.setattr(iris, "_run_verified_app", lambda _: pytest.fail("Unverified app executed"))
    def page():
        from agilab.agent_runtime.notebook_showcase import render
        render()

    at = AppTest.from_function(page).run()
    assert not at.exception and at.error and not at.title


@pytest.mark.parametrize("defect", ["stale", "destination-symlink", "parent-symlink", "failed-check"])
def test_iris_export_rejects_invalid_destination_and_receipt_before_writing(tmp_path, defect):
    from tools.demos.export_notebook_agent_demo import export_demo

    run = tmp_path / "run"
    project = run / "decision_lab_project"
    shutil.copytree(iris.DEMO_ROOT, project, ignore=shutil.ignore_patterns("__pycache__"))
    (project / "source").mkdir()
    shutil.copyfile(project / "LICENSE", project / "source/LICENSE")
    report = iris.load_report()
    target = tmp_path / "export"
    if defect == "failed-check":
        report["verification"]["status"] = "failed"
    else:
        preserved = tmp_path / "preserved"
        preserved.mkdir()
        (preserved / "app.py").write_text("keep existing app\n")
        if defect == "stale":
            target = preserved
        elif defect == "destination-symlink":
            target.symlink_to(preserved, target_is_directory=True)
        else:
            (tmp_path / "linked").symlink_to(preserved, target_is_directory=True)
            target = tmp_path / "linked/export"
    (run / "result.json").write_text(json.dumps(report))
    with pytest.raises(ValueError):
        export_demo(run, target)
    assert not (target / "result.json").exists()
    if defect != "failed-check":
        assert (preserved / "app.py").read_text() == "keep existing app\n"


@pytest.mark.parametrize("selected", ["forecast", "threading"])
def test_demo_does_not_consume_another_apps_analysis(selected, tmp_path, monkeypatch):
    from agilab.agent_runtime import forecast_showcase
    from streamlit.testing.v1 import AppTest

    monkeypatch.setattr(forecast_showcase, "_prepare_model", lambda _: tmp_path)
    monkeypatch.setattr(forecast_showcase, "_validate_model", lambda path: path)
    at = AppTest.from_file(iris.__file__, default_timeout=30)
    at.query_params["demo"] = selected
    foreign_result = {"another_app_result": 42}
    at.session_state["analysis"] = foreign_result
    at.run()
    assert not at.exception and not at.error
    assert at.session_state["analysis"] == foreign_result
    at.segmented_control(key="demo").set_value("iris").run()
    at.segmented_control(key="demo").set_value(selected).run()
    assert not at.exception and not at.error
    assert at.session_state["analysis"] == foreign_result
