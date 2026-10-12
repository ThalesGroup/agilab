"""Minimal UI installs must admit optional demos before scientific execution."""
from __future__ import annotations

import ast
import importlib.util
from importlib.metadata import PackageNotFoundError
from pathlib import Path
import shlex
import sys
import tomllib

import pytest
from agi_web.testing import AppTest

from agilab.demos import (
    forecast_showcase,
    free_threading_showcase,
    milp_energy_showcase,
    notebook_app_runtime as runtime,
    notebook_showcase,
    text_showcase,
)

ROOT = Path(__file__).resolve().parents[1]
DEMO_ROOTS = {
    "iris": "notebook_agent_demo", "iris_local": "notebook_agent_local_demo",
    "iris_rtx": "notebook_agent_rtx_demo", "forecast": "forecast_notebook_demo",
    "forecast_astra": "forecast_notebook_demo_astra", "forecast_rtx": "forecast_notebook_demo_rtx",
    "text": "text_notebook_demo", "text_astra": "text_notebook_demo_astra",
    "text_rtx": "text_notebook_demo_rtx", "threading": "free_threading_demo",
    "threading_astra": "free_threading_demo_astra", "threading_rtx": "free_threading_demo_rtx",
    "milp": "milp_energy_demo", "milp_astra": "milp_energy_demo_astra",
    "milp_rtx": "milp_energy_demo_rtx",
}


def _stub_app_execution(monkeypatch, tmp_path):
    calls = []
    for module in (notebook_showcase, forecast_showcase, text_showcase,
                   free_threading_showcase, milp_energy_showcase):
        monkeypatch.setattr(module, "_run_verified_app", lambda *a, **kw: calls.append((a, kw)))
    monkeypatch.setattr(forecast_showcase, "_prepare_model", lambda _path: tmp_path)
    monkeypatch.setattr(forecast_showcase, "_validate_model", lambda path: path)
    return calls


@pytest.mark.parametrize("demo", notebook_showcase.DEMO_LABELS)
def test_every_variant_admits_dependencies_after_verified_proof(monkeypatch, tmp_path, demo):
    calls = _stub_app_execution(monkeypatch, tmp_path)
    modules = runtime._DEMO_DEPENDENCIES[demo]
    absent = modules[0] if modules else None
    original = importlib.util.find_spec
    monkeypatch.setattr(runtime.importlib.util, "find_spec",
                        lambda name: None if name == absent else object() if name in modules else original(name))
    monkeypatch.setattr(runtime, "version", lambda _name: "2026.10.12")
    at = AppTest.from_string("from agilab.demos.notebook_showcase import render\nrender()", default_timeout=30)
    at.query_params["demo"] = demo
    at.run()
    assert not at.exception and not at.error
    assert at.get("download_button"), demo
    assert any(item.label == "AGILAB workflow stages" for item in at.metric), demo
    if absent is None:
        assert len(calls) == 1  # RTX threading has no optional scientific imports.
        assert not at.warning
    else:
        assert calls == [], demo
        distribution = runtime._MODULE_DISTRIBUTIONS.get(absent, absent)
        assert any(distribution in item.value for item in at.warning)
        assert any("agilab[notebook-agent]==2026.10.12" in item.value for item in at.code)
        if demo.startswith("iris"):
            assert next(button for button in at.button if button.label == "Run model and app checks").disabled


@pytest.mark.parametrize("demo", notebook_showcase.DEMO_LABELS)
def test_ready_variants_continue_to_verified_execution(monkeypatch, tmp_path, demo):
    calls = _stub_app_execution(monkeypatch, tmp_path)
    original = importlib.util.find_spec
    modules = runtime._DEMO_DEPENDENCIES[demo]
    monkeypatch.setattr(runtime.importlib.util, "find_spec",
                        lambda name: object() if name in modules else original(name))
    at = AppTest.from_string("from agilab.demos.notebook_showcase import render\nrender()", default_timeout=30)
    at.query_params["demo"] = demo
    at.run()
    assert not at.exception and not at.error
    assert len(calls) == 1, demo
    assert not any("optional scientific packages" in item.value for item in at.warning)


@pytest.mark.parametrize("demo,directory", DEMO_ROOTS.items())
def test_prerequisite_map_covers_real_sealed_runtime_imports(demo, directory):
    root = Path(notebook_showcase.__file__).parent / "resources" / directory
    sources = sorted(path for path in root.glob("*.py") if not path.name.startswith("test"))
    local = {path.stem for path in sources} | {path.name for path in root.iterdir() if path.is_dir()}
    imports = set()
    for path in sources:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".")[0])
    external = imports - sys.stdlib_module_names - local - {"agi_web"}
    assert external <= set(runtime._DEMO_DEPENDENCIES[demo]), (demo, external)
    assert set(DEMO_ROOTS) == set(notebook_showcase.DEMO_LABELS)


def test_notebook_agent_extra_supplies_runtime_distributions_without_base_ui_weight():
    from packaging.requirements import Requirement

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    requirements = {Requirement(value).name.lower(): Requirement(value)
                    for value in project["optional-dependencies"]["notebook-agent"]}
    # These three direct demo requirements were absent from the public extra.
    for name, supported in (("altair", "6.0"), ("pillow", "12.2"), ("psutil", "7.0")):
        assert requirements[name].specifier.contains(supported)
        for minimal in (project["dependencies"], project["optional-dependencies"]["ui"]):
            assert name not in {Requirement(value).name.lower() for value in minimal}
    direct = {runtime._MODULE_DISTRIBUTIONS.get(module, module).lower()
              for modules in runtime._DEMO_DEPENDENCIES.values() for module in modules}
    assert direct - {"torch", "threadpoolctl"} <= requirements.keys()
    # The two remaining imports have real providers among declared dependencies.
    assert "chronos-forecasting" in requirements and "scikit-learn" in requirements


class _GuidanceUI:
    def __init__(self):
        self.messages, self.commands, self.raw_commands = [], [], []

    def warning(self, value):
        self.messages.append(value)

    caption = info = warning

    def code(self, value, **_kwargs):
        self.raw_commands.append((value, _kwargs.get("language")))
        if _kwargs.get("language") == "bash":
            self.commands.append(shlex.split(value))


@pytest.mark.parametrize("platform", ["darwin", "linux"])
@pytest.mark.parametrize("uv,pip", [("/owned uv/bin/uv", False), (None, True), (None, False)])
def test_guidance_targets_current_environment_and_installed_version(monkeypatch, uv, pip, platform):
    ui = _GuidanceUI()
    monkeypatch.setattr(runtime, "version", lambda name: "2026.10.12")
    monkeypatch.setattr(runtime.shutil, "which", lambda name: uv)
    monkeypatch.setattr(runtime.sys, "executable", "/owned env/bin/python")
    monkeypatch.setattr(runtime.sys, "platform", platform)
    monkeypatch.setattr(runtime.importlib.util, "find_spec", lambda name: object() if pip else None)
    runtime.render_demo_dependency_guidance(ui, ("matplotlib",))
    if uv or not pip:
        assert ui.commands == [[uv or "uv", "pip", "install", "--python",
                                "/owned env/bin/python", "agilab[notebook-agent]==2026.10.12"]]
    else:
        assert ui.commands == [["/owned env/bin/python", "-m", "pip", "install",
                                "agilab[notebook-agent]==2026.10.12"]]
    assert any("restart" in message for message in ui.messages)
    if not uv and not pip:
        assert any("Install uv first" in message for message in ui.messages)


def test_source_checkout_guidance_does_not_invent_an_installed_version(monkeypatch):
    ui = _GuidanceUI()

    def absent(_name):
        raise PackageNotFoundError("agilab")

    monkeypatch.setattr(runtime, "version", absent)
    runtime.render_demo_dependency_guidance(ui, ("matplotlib",))
    assert not ui.commands
    assert any("no installed AGILAB version metadata" in message for message in ui.messages)


@pytest.mark.parametrize("uv,pip", [("C:\\AGI tools\\O'Neil\\uv.exe", False), (None, True), (None, False)])
def test_windows_guidance_invokes_quoted_executables_in_powershell(monkeypatch, uv, pip):
    ui = _GuidanceUI()
    monkeypatch.setattr(runtime, "version", lambda name: "2026.10.12")
    monkeypatch.setattr(runtime.shutil, "which", lambda name: uv)
    monkeypatch.setattr(runtime.sys, "executable", "C:\\AGI space\\O'Neil\\python.exe")
    monkeypatch.setattr(runtime.sys, "platform", "win32")
    monkeypatch.setattr(runtime.importlib.util, "find_spec", lambda name: object() if pip else None)
    runtime.render_demo_dependency_guidance(ui, ("matplotlib",))
    if uv:
        expected = ("& 'C:\\AGI tools\\O''Neil\\uv.exe' 'pip' 'install' '--python' "
                    "'C:\\AGI space\\O''Neil\\python.exe' 'agilab[notebook-agent]==2026.10.12'")
    elif pip:
        expected = ("& 'C:\\AGI space\\O''Neil\\python.exe' '-m' 'pip' 'install' "
                    "'agilab[notebook-agent]==2026.10.12'")
    else:
        expected = ("& 'uv' 'pip' 'install' '--python' 'C:\\AGI space\\O''Neil\\python.exe' "
                    "'agilab[notebook-agent]==2026.10.12'")
        assert any("Install uv first" in message for message in ui.messages)
    assert ui.raw_commands == [(expected, "powershell")]


def test_verified_bundle_failure_precedes_optional_dependency_guidance(monkeypatch):
    def invalid(_root):
        raise ValueError("artifact hash mismatch")

    def forbidden(_demo):
        raise AssertionError("dependency admission ran before sealed bundle verification")

    monkeypatch.setattr(notebook_showcase, "_read_verified_bundle", invalid)
    monkeypatch.setattr(notebook_showcase, "missing_demo_dependencies", forbidden)
    at = AppTest.from_string("from agilab.demos.notebook_showcase import render\nrender()", default_timeout=30).run()
    assert not at.exception
    assert any("artifact hash mismatch" in item.value for item in at.error)
    assert not at.warning


def test_ready_execution_failure_remains_an_execution_error(monkeypatch, tmp_path):
    _stub_app_execution(monkeypatch, tmp_path)
    monkeypatch.setattr(notebook_showcase, "missing_demo_dependencies", lambda demo: ())

    def broken(*_args, **_kwargs):
        raise ModuleNotFoundError("unexpected application import", name="unexpected_plugin")

    monkeypatch.setattr(notebook_showcase, "_run_verified_app", broken)
    at = AppTest.from_string("from agilab.demos.notebook_showcase import render\nrender()", default_timeout=30).run()
    assert at.exception
    assert "unexpected application import" in at.exception[0].message
    assert not any("optional scientific packages" in item.value for item in at.warning)


def test_dependency_probe_does_not_swallow_unrelated_import_errors(monkeypatch):
    def broken(_name):
        raise ImportError("broken scientific environment")

    monkeypatch.setattr(runtime.importlib.util, "find_spec", broken)
    with pytest.raises(ImportError, match="broken scientific environment"):
        runtime.missing_demo_dependencies("iris")
