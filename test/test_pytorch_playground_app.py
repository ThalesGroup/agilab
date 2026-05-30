from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import ModuleType
from types import SimpleNamespace
import zipfile

import numpy as np
import pandas as pd
import pytest


MODULE_PATH = Path(
    "src/agilab/apps/builtin/pytorch_playground_project/src/pytorch_playground/playground_ui.py"
)
APP_SURFACE_PATH = Path(
    "src/agilab/apps/builtin/pytorch_playground_project/src/pytorch_playground/app_surface.py"
)
APP_ARGS_FORM_PATH = Path("src/agilab/apps/builtin/pytorch_playground_project/src/app_args_form.py")
INIT_PATH = Path("src/agilab/lib/agi-app-pytorch-playground/src/agi_app_pytorch_playground/__init__.py")
README_PATH = Path("src/agilab/lib/agi-app-pytorch-playground/README.md")
PROJECT_PATH = Path("src/agilab/apps/builtin/pytorch_playground_project")
PACKAGE_PROJECT_PATH = Path(
    "src/agilab/lib/agi-app-pytorch-playground/src/agi_app_pytorch_playground/project/pytorch_playground_project"
)
PROJECT_SRC = PROJECT_PATH / "src"
EXPECTED_SOURCE_PAYLOAD_DIFFS = {Path("pytorch_playground_worker/pyproject.toml")}


def _load_module():
    spec = importlib.util.spec_from_file_location("pytorch_playground_app_test_module", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_app_args_form_module():
    spec = importlib.util.spec_from_file_location("pytorch_playground_app_args_form_test_module", APP_ARGS_FORM_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    module._AGILAB_APP_ARGS_FORM_IMPORT_ONLY = True
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_app_surface_module(name: str):
    spec = importlib.util.spec_from_file_location(name, APP_SURFACE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_playground_ui_import_prefers_package_when_streamlit_puts_script_dir_first(monkeypatch):
    script_dir = MODULE_PATH.resolve().parent
    project_src = PROJECT_SRC.resolve()
    original_modules = {
        name: module
        for name, module in sys.modules.items()
        if name == "pytorch_playground" or name.startswith("pytorch_playground.")
    }
    for name in original_modules:
        sys.modules.pop(name, None)

    fake_path = [
        str(script_dir),
        str(project_src),
        *[
            entry
            for entry in sys.path
            if entry not in {str(script_dir), str(project_src)}
        ],
    ]
    monkeypatch.setattr(sys, "path", fake_path)

    spec = importlib.util.spec_from_file_location("pytorch_playground_streamlit_path_order_test", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        assert sys.path[0] == str(project_src)
        assert module._playground_core.__name__ == "pytorch_playground.core"
    finally:
        sys.modules.pop(spec.name, None)
        for name in list(sys.modules):
            if name == "pytorch_playground" or name.startswith("pytorch_playground."):
                sys.modules.pop(name, None)
        sys.modules.update(original_modules)


def test_app_surface_import_prefers_package_when_streamlit_puts_script_dir_first(monkeypatch):
    script_dir = APP_SURFACE_PATH.resolve().parent
    project_src = PROJECT_SRC.resolve()
    original_modules = {
        name: module
        for name, module in sys.modules.items()
        if name == "pytorch_playground" or name.startswith("pytorch_playground.")
    }
    for name in original_modules:
        sys.modules.pop(name, None)

    fake_path = [
        str(script_dir),
        str(project_src),
        *[
            entry
            for entry in sys.path
            if entry not in {str(script_dir), str(project_src)}
        ],
    ]
    monkeypatch.setattr(sys, "path", fake_path)

    spec = importlib.util.spec_from_file_location("pytorch_playground_app_surface_path_order_test", APP_SURFACE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        imported_package = importlib.import_module("pytorch_playground")
        assert sys.path[0] == str(project_src)
        assert Path(imported_package.__file__).name == "__init__.py"
    finally:
        sys.modules.pop(spec.name, None)
        for name in list(sys.modules):
            if name == "pytorch_playground" or name.startswith("pytorch_playground."):
                sys.modules.pop(name, None)
        sys.modules.update(original_modules)


def test_app_surface_drops_shadowing_script_module(monkeypatch):
    module = _load_app_surface_module("pytorch_playground_app_surface_shadow_test")

    shadow = ModuleType("pytorch_playground")
    shadow.__file__ = str(APP_SURFACE_PATH.resolve().parent / "pytorch_playground.py")
    child = ModuleType("pytorch_playground.core")
    monkeypatch.setitem(sys.modules, "pytorch_playground", shadow)
    monkeypatch.setitem(sys.modules, "pytorch_playground.core", child)

    try:
        module._drop_shadowed_package_module()
    finally:
        sys.modules.pop(module.__name__, None)

    assert "pytorch_playground" not in sys.modules
    assert "pytorch_playground.core" not in sys.modules


def test_app_surface_keeps_real_or_unresolvable_package_modules(monkeypatch, tmp_path: Path):
    module = _load_app_surface_module("pytorch_playground_app_surface_non_shadow_test")

    package = ModuleType("pytorch_playground")
    package.__file__ = str(tmp_path / "site-packages" / "pytorch_playground" / "__init__.py")
    child = ModuleType("pytorch_playground.core")
    monkeypatch.setitem(sys.modules, "pytorch_playground", package)
    monkeypatch.setitem(sys.modules, "pytorch_playground.core", child)

    try:
        module._drop_shadowed_package_module()
        assert sys.modules["pytorch_playground"] is package
        assert sys.modules["pytorch_playground.core"] is child

        package.__file__ = object()
        module._drop_shadowed_package_module()
        assert sys.modules["pytorch_playground"] is package
    finally:
        sys.modules.pop(module.__name__, None)


def test_app_surface_resolves_equals_active_app_arg_and_path_fallback(monkeypatch, tmp_path: Path):
    module = _load_app_surface_module("pytorch_playground_app_surface_path_fallback_test")
    active_app = tmp_path / "pytorch_playground_project"
    active_app.mkdir()
    monkeypatch.setattr(sys, "argv", ["app_surface.py", f"--active-app={active_app}"])

    class _UnresolvablePath:
        def expanduser(self):
            return self

        def resolve(self):
            raise RuntimeError("synthetic path resolution failure")

    paths: list[object] = []
    bad_path = _UnresolvablePath()

    try:
        assert module._resolve_active_app_path() == active_app.resolve()
        module._append_unique_path(paths, bad_path)
        module._append_unique_path(paths, bad_path)
    finally:
        sys.modules.pop(module.__name__, None)

    assert paths == [bad_path]


def test_app_surface_app_args_form_loader_reports_missing_spec(monkeypatch):
    module = _load_app_surface_module("pytorch_playground_app_surface_form_loader_test")
    monkeypatch.setattr(module.importlib.util, "spec_from_file_location", lambda *_args, **_kwargs: None)

    try:
        with pytest.raises(ModuleNotFoundError, match="Unable to load PyTorch Playground app form"):
            module._load_app_args_form()
    finally:
        sys.modules.pop(module.__name__, None)


def test_app_surface_app_args_form_loader_marks_import_only_module(monkeypatch):
    module = _load_app_surface_module("pytorch_playground_app_surface_form_loader_success_test")
    loaded_modules: list[ModuleType] = []

    class _Loader:
        def exec_module(self, loaded_module):
            loaded_modules.append(loaded_module)

    fake_spec = SimpleNamespace(name="_fake_pytorch_playground_app_args_form", loader=_Loader())
    monkeypatch.setattr(module.importlib.util, "spec_from_file_location", lambda *_args, **_kwargs: fake_spec)
    monkeypatch.setattr(module.importlib.util, "module_from_spec", lambda spec: ModuleType(spec.name))

    try:
        loaded_module = module._load_app_args_form()
    finally:
        sys.modules.pop(module.__name__, None)
        sys.modules.pop(fake_spec.name, None)

    assert loaded_module is loaded_modules[0]
    assert loaded_module._AGILAB_APP_ARGS_FORM_IMPORT_ONLY is True


def test_app_surface_resolves_active_app_from_argv_and_evidence_dirs(monkeypatch, tmp_path: Path):
    spec = importlib.util.spec_from_file_location("pytorch_playground_app_surface_paths_test", APP_SURFACE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    app_path = tmp_path / "pytorch_playground_project"
    app_path.mkdir()
    monkeypatch.setattr(sys, "argv", ["app_surface.py", "--active-app", str(app_path)])

    env = SimpleNamespace(
        AGILAB_EXPORT_ABS=tmp_path / "export",
        target="pytorch_target",
        app="pytorch_playground_project",
    )
    args = SimpleNamespace(data_out="pytorch_playground/evidence")

    try:
        resolved = module._resolve_active_app_path()
        evidence_dirs = module._analysis_evidence_dirs(env, args, app_path)
    finally:
        sys.modules.pop(spec.name, None)

    assert resolved == app_path.resolve()
    assert evidence_dirs == [
        (tmp_path / "export" / "pytorch_target" / "pytorch_playground").resolve(),
        (tmp_path / "export" / "pytorch_playground_project" / "pytorch_playground").resolve(),
        Path("pytorch_playground/evidence").resolve(),
    ]


def test_app_surface_analysis_uses_orchestrate_args(monkeypatch):
    spec = importlib.util.spec_from_file_location("pytorch_playground_app_surface_analysis_test", APP_SURFACE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    calls: list[dict[str, object]] = []
    fake_config = SimpleNamespace(dataset="circles")
    fake_args = SimpleNamespace(
        compute_loss_landscape=True,
        landscape_resolution=17,
        landscape_span=0.4,
    )
    fake_app_args = SimpleNamespace(to_playground_config=lambda args: fake_config)
    fake_playground_ui = SimpleNamespace(main=lambda **kwargs: calls.append(kwargs))
    fake_package = ModuleType("pytorch_playground")
    fake_package.app_args = fake_app_args
    fake_package.playground_ui = fake_playground_ui
    evidence_dirs = [PROJECT_PATH.resolve() / "evidence"]

    monkeypatch.setitem(sys.modules, "pytorch_playground", fake_package)
    monkeypatch.setattr(module, "_resolve_active_app_path", lambda _active_app=None: PROJECT_PATH.resolve())
    monkeypatch.setattr(module, "_load_orchestrate_args", lambda _active_app_path: (SimpleNamespace(), fake_args))
    monkeypatch.setattr(module, "_analysis_evidence_dirs", lambda _env, _args, _path: evidence_dirs)
    monkeypatch.setattr(module, "_has_evidence", lambda paths: paths == evidence_dirs)

    try:
        module.render(mode="analysis")
    finally:
        sys.modules.pop(spec.name, None)

    assert calls == [
        {
            "config_override": fake_config,
            "preset_label": "ORCHESTRATE args",
            "interactive_controls": False,
            "compute_loss_landscape": True,
            "landscape_resolution": 17,
            "landscape_span": 0.4,
            "evidence_dirs": evidence_dirs,
            "configure_page": True,
            "compact": False,
        }
    ]


def test_app_surface_analysis_no_evidence_avoids_playground_import(monkeypatch, tmp_path: Path):
    spec = importlib.util.spec_from_file_location("pytorch_playground_app_surface_no_evidence_test", APP_SURFACE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    evidence_dirs = [tmp_path / "missing-evidence"]
    rendered: list[list[Path]] = []

    fake_package = ModuleType("pytorch_playground")

    def fail_on_import(_name: str):
        raise AssertionError("playground_ui should not be imported before evidence exists")

    fake_package.__getattr__ = fail_on_import  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "pytorch_playground", fake_package)
    monkeypatch.setattr(module, "_resolve_active_app_path", lambda _active_app=None: PROJECT_PATH.resolve())
    monkeypatch.setattr(
        module,
        "_load_orchestrate_args",
        lambda _active_app_path: (
            SimpleNamespace(AGILAB_EXPORT_ABS=tmp_path / "export", target="pytorch_playground_project"),
            SimpleNamespace(data_out=tmp_path / "evidence"),
        ),
    )
    monkeypatch.setattr(module, "_analysis_evidence_dirs", lambda _env, _args, _path: evidence_dirs)
    monkeypatch.setattr(module, "_has_evidence", lambda _paths: False)
    monkeypatch.setattr(module, "_render_missing_evidence", lambda paths, **_kwargs: rendered.append(list(paths)))

    try:
        module.render(mode="analysis")
    finally:
        sys.modules.pop(spec.name, None)

    assert rendered == [evidence_dirs]


def test_app_surface_missing_evidence_renders_page_and_checked_paths(monkeypatch, tmp_path: Path):
    module = _load_app_surface_module("pytorch_playground_app_surface_missing_evidence_render_test")
    events: list[tuple[str, object]] = []

    class _FakeStreamlit:
        def set_page_config(self, **kwargs):
            events.append(("page_config", kwargs))

        def title(self, message):
            events.append(("title", message))

        def info(self, message):
            events.append(("info", message))

        def caption(self, message):
            events.append(("caption", message))

        def code(self, body, **kwargs):
            events.append(("code", (body, kwargs)))

    evidence_path = tmp_path / "evidence"
    monkeypatch.setitem(sys.modules, "streamlit", _FakeStreamlit())

    try:
        module._render_missing_evidence([evidence_path])
    finally:
        sys.modules.pop(module.__name__, None)

    assert ("page_config", {"page_title": "PyTorch Playground", "layout": "wide"}) in events
    assert ("title", "PyTorch Playground") in events
    assert any(kind == "info" and "No exported PyTorch evidence" in message for kind, message in events)
    assert ("caption", "Checked evidence locations:") in events
    assert ("code", (str(evidence_path), {"language": "text"})) in events


def test_app_surface_full_renders_orchestrate_form_and_analysis_together(monkeypatch):
    spec = importlib.util.spec_from_file_location("pytorch_playground_app_surface_full_test", APP_SURFACE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    events: list[tuple[str, object]] = []
    fake_runtime_env = SimpleNamespace(app="pytorch_playground_project")
    fake_config = SimpleNamespace(dataset="circles")
    fake_args = SimpleNamespace(
        compute_loss_landscape=True,
        landscape_resolution=17,
        landscape_span=0.4,
    )
    evidence_dirs = [PROJECT_PATH.resolve() / "evidence"]

    class _Column:
        def __init__(self, name: str):
            self.name = name

        def __enter__(self):
            events.append((f"enter:{self.name}", self))
            return self

        def __exit__(self, *_args):
            events.append((f"exit:{self.name}", self))
            return False

        def markdown(self, message):
            events.append(("column_markdown", (self.name, message)))

        def caption(self, message):
            events.append(("column_caption", (self.name, message)))

        def button(self, *_args, **_kwargs):
            events.append(("button", self.name))
            return False

        def error(self, message):
            events.append(("column_error", message))

        def success(self, message):
            events.append(("column_success", message))

    class _FakeStreamlit:
        def set_page_config(self, **kwargs):
            events.append(("page_config", kwargs))

        def columns(self, spec):
            events.append(("columns", spec))
            return [_Column("analysis"), _Column("controls")]

        def error(self, message):
            events.append(("error", message))

    fake_app_args_form = SimpleNamespace(
        render=lambda **kwargs: events.append(("form", kwargs)),
    )
    fake_app_args = SimpleNamespace(to_playground_config=lambda args: fake_config)
    fake_playground_ui = SimpleNamespace(
        PAGE_TITLE="PyTorch Playground",
        main=lambda **kwargs: events.append(("analysis", kwargs)),
    )
    fake_package = ModuleType("pytorch_playground")
    fake_package.app_args = fake_app_args
    fake_package.playground_ui = fake_playground_ui

    monkeypatch.setitem(sys.modules, "streamlit", _FakeStreamlit())
    monkeypatch.setitem(sys.modules, "pytorch_playground", fake_package)
    monkeypatch.setattr(module, "_load_app_args_form", lambda: fake_app_args_form)
    monkeypatch.setattr(module, "_load_orchestrate_args", lambda _active_app_path: (fake_runtime_env, fake_args))
    monkeypatch.setattr(module, "_analysis_evidence_dirs", lambda _env, _args, _path: evidence_dirs)
    monkeypatch.setattr(module, "_has_evidence", lambda paths: paths == evidence_dirs)

    try:
        module.render(mode="full", active_app=PROJECT_PATH.resolve())
    finally:
        sys.modules.pop(spec.name, None)

    assert ("page_config", {"page_title": "PyTorch Playground", "layout": "wide"}) in events
    assert ("columns", [0.70, 0.30]) in events
    assert not any(kind == "column_caption" for kind, _payload in events)

    form_event = next(payload for kind, payload in events if kind == "form")
    assert form_event["env"] is fake_runtime_env
    assert form_event["wide"] is False
    assert form_event["compact"] is True

    analysis_event = next(payload for kind, payload in events if kind == "analysis")
    assert analysis_event == {
        "config_override": fake_config,
        "preset_label": "ORCHESTRATE args",
        "interactive_controls": False,
        "compute_loss_landscape": True,
        "landscape_resolution": 17,
        "landscape_span": 0.4,
        "evidence_dirs": evidence_dirs,
        "configure_page": False,
        "compact": True,
    }


def test_app_surface_run_once_uses_pytorch_worker(monkeypatch):
    spec = importlib.util.spec_from_file_location("pytorch_playground_app_surface_run_once_test", APP_SURFACE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    events: list[tuple[str, object]] = []

    class _FakeWorker:
        def start(self):
            events.append(("start", {"args": self.args, "env": self.env, "worker_id": self._worker_id}))

        def work_pool(self, item):
            events.append(("work_pool", item))
            return pd.DataFrame([{"backend": "fake"}])

    fake_worker_package = ModuleType("pytorch_playground_worker")
    fake_worker_package.__path__ = []  # type: ignore[attr-defined]
    fake_worker_module = ModuleType("pytorch_playground_worker.pytorch_playground_worker")
    fake_worker_module.PytorchPlaygroundWorker = _FakeWorker

    monkeypatch.setitem(sys.modules, "pytorch_playground_worker", fake_worker_package)
    monkeypatch.setitem(sys.modules, "pytorch_playground_worker.pytorch_playground_worker", fake_worker_module)

    runtime_env = SimpleNamespace(app="pytorch_playground_project")
    args_model = SimpleNamespace(model_dump=lambda **kwargs: {"dataset": "circles", "dump": kwargs})

    try:
        summary = module._run_playground_once(runtime_env, args_model)
    finally:
        sys.modules.pop(spec.name, None)

    assert summary.iloc[0]["backend"] == "fake"
    assert events == [
        (
            "start",
            {
                "args": {"dataset": "circles", "dump": {"mode": "json"}},
                "env": runtime_env,
                "worker_id": 0,
            },
        ),
        ("work_pool", "pytorch_playground"),
    ]


def test_app_surface_full_run_button_executes_before_analysis(monkeypatch):
    spec = importlib.util.spec_from_file_location("pytorch_playground_app_surface_full_run_test", APP_SURFACE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    events: list[tuple[str, object]] = []
    runtime_env = SimpleNamespace(app="pytorch_playground_project")
    args_model = SimpleNamespace(dataset="circles")

    class _Column:
        def __init__(self, name: str):
            self.name = name

        def __enter__(self):
            events.append((f"enter:{self.name}", self.name))
            return self

        def __exit__(self, *_args):
            events.append((f"exit:{self.name}", self.name))
            return False

        def markdown(self, message):
            events.append(("column_markdown", (self.name, message)))

        def caption(self, message):
            events.append(("column_caption", (self.name, message)))

        def button(self, label, **kwargs):
            events.append(("button", (self.name, label, kwargs)))
            return self.name == "controls"

        def error(self, message):
            events.append(("column_error", message))

        def success(self, message):
            events.append(("column_success", message))

    class _Spinner:
        def __enter__(self):
            events.append(("spinner_enter", None))
            return self

        def __exit__(self, *_args):
            events.append(("spinner_exit", None))
            return False

    class _FakeStreamlit:
        def set_page_config(self, **kwargs):
            events.append(("page_config", kwargs))

        def columns(self, spec):
            events.append(("columns", spec))
            return [_Column("analysis"), _Column("controls")]

        def spinner(self, message):
            events.append(("spinner", message))
            return _Spinner()

        def error(self, message):
            events.append(("error", message))

    fake_app_args_form = SimpleNamespace(render=lambda **kwargs: events.append(("form", kwargs)))
    fake_playground_ui = SimpleNamespace(PAGE_TITLE="PyTorch Playground")
    fake_package = ModuleType("pytorch_playground")
    fake_package.playground_ui = fake_playground_ui

    load_calls: list[Path] = []

    def _load_args(path):
        load_calls.append(path)
        return runtime_env, args_model

    monkeypatch.setitem(sys.modules, "streamlit", _FakeStreamlit())
    monkeypatch.setitem(sys.modules, "pytorch_playground", fake_package)
    monkeypatch.setattr(module, "_load_app_args_form", lambda: fake_app_args_form)
    monkeypatch.setattr(module, "_load_orchestrate_args", _load_args)
    monkeypatch.setattr(
        module,
        "_run_playground_once",
        lambda env, args: events.append(("run", {"env": env, "args": args})) or pd.DataFrame([{"backend": "fake"}]),
    )
    monkeypatch.setattr(
        module,
        "_render_analysis_surface",
        lambda path, **kwargs: events.append(("analysis", {"path": path, **kwargs})),
    )

    try:
        module.render(mode="full", active_app=PROJECT_PATH.resolve())
    finally:
        sys.modules.pop(spec.name, None)

    ordered = [kind for kind, _payload in events if kind in {"form", "button", "run", "analysis"}]
    assert ordered == ["button", "run", "form", "analysis"]
    assert (
        "button",
        ("controls", "Refresh evidence", {"type": "primary", "width": "stretch"}),
    ) in events
    assert ("spinner", "Refreshing PyTorch evidence") in events
    assert load_calls == [PROJECT_PATH.resolve(), PROJECT_PATH.resolve()]
    assert ("column_success", "Run complete. Evidence refreshed (1 row).") in events


def test_app_surface_additional_modes_and_error_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    module = _load_app_surface_module("pytorch_playground_app_surface_extra_modes_test")
    events: list[tuple[str, object]] = []

    assert module._resolve_active_app_path(tmp_path / "missing") is None
    monkeypatch.setattr(sys, "argv", ["app_surface.py"])
    assert module._resolve_active_app_path() is None

    class FakeAgiEnv:
        def __init__(self, **kwargs):
            events.append(("agi-env-init", kwargs))
            self.app_settings_file = tmp_path / "settings.toml"

        @classmethod
        def for_app(cls, **kwargs):
            events.append(("agi-env-for-app", kwargs))
            instance = cls(**kwargs)
            instance.app_settings_file.write_text("[args]\nsample_count=96\n", encoding="utf-8")
            return instance

    fake_agi_env_module = ModuleType("agi_env")
    fake_agi_env_module.AgiEnv = FakeAgiEnv
    monkeypatch.setitem(sys.modules, "agi_env", fake_agi_env_module)

    env, args_model = module._load_orchestrate_args(PROJECT_PATH.resolve())
    assert args_model.sample_count == 96
    assert events[0][0] == "agi-env-for-app"

    resolved_dirs = module._analysis_evidence_dirs(
        SimpleNamespace(resolve_share_path=lambda value: tmp_path / "share" / value),
        SimpleNamespace(data_out="relative-evidence"),
        PROJECT_PATH.resolve(),
    )
    assert resolved_dirs[-1] == (tmp_path / "share" / "relative-evidence").resolve()

    fake_package = ModuleType("pytorch_playground")
    fake_playground_ui = SimpleNamespace(
        PAGE_TITLE="PyTorch Playground",
        main=lambda **kwargs: events.append(("playground-main", kwargs)),
    )
    fake_app_args_form = SimpleNamespace(render=lambda **kwargs: events.append(("configure-form", kwargs)))
    fake_package.playground_ui = fake_playground_ui
    monkeypatch.setitem(sys.modules, "pytorch_playground", fake_package)
    monkeypatch.setattr(module, "_load_app_args_form", lambda: fake_app_args_form)

    module._render_analysis_surface(None, configure_page=False, compact=True)
    assert ("playground-main", {"configure_page": False, "compact": True}) in events

    class FakeStreamlit:
        def set_page_config(self, **kwargs):
            events.append(("page-config", kwargs))

        def error(self, message):
            events.append(("st-error", message))

    monkeypatch.setitem(sys.modules, "streamlit", FakeStreamlit())
    monkeypatch.setattr(module, "_load_orchestrate_args", lambda _path: (_ for _ in ()).throw(RuntimeError("bad args")))
    module._render_analysis_surface(PROJECT_PATH.resolve())
    assert ("st-error", "Unable to load ORCHESTRATE app arguments: bad args") in events
    module._render_full_surface(PROJECT_PATH.resolve())
    assert events[-1] == ("st-error", "Unable to load ORCHESTRATE app arguments: bad args")

    class NoMarkdownStreamlit:
        pass

    monkeypatch.setitem(sys.modules, "streamlit", NoMarkdownStreamlit())
    assert module._render_surface_styles() is None

    module._render_full_surface(None)
    assert events[-1] == ("playground-main", {})

    module.render(mode="configure", env="env", container="container")
    assert events[-1] == ("configure-form", {"env": "env", "container": "container"})

    monkeypatch.setattr(module, "_resolve_active_app_path", lambda _active_app=None: None)
    monkeypatch.setattr(
        module,
        "_render_analysis_surface",
        lambda path: events.append(("render-analysis", path)),
    )
    monkeypatch.setattr(
        module,
        "_render_full_surface",
        lambda path, **kwargs: events.append(("render-full", (path, kwargs))),
    )
    module.render(mode="analysis")
    module.render(mode="full", env="env", container="container")
    assert ("render-analysis", None) in events
    assert ("render-full", (None, {"env": "env", "container": "container"})) in events
    with pytest.raises(ValueError, match="Unsupported PyTorch Playground app surface mode"):
        module.render(mode="unknown")


def test_app_surface_run_button_idle_and_failure_paths(monkeypatch: pytest.MonkeyPatch):
    module = _load_app_surface_module("pytorch_playground_app_surface_run_edges_test")
    events: list[tuple[str, object]] = []

    class IdleContainer:
        def button(self, label, **kwargs):
            events.append(("button", (label, kwargs)))
            return False

        def error(self, message):
            events.append(("error", message))

    assert module._render_run_button(PROJECT_PATH.resolve(), container=IdleContainer()) is None
    assert events == [("button", ("Refresh evidence", {"type": "primary", "width": "stretch"}))]

    class ClickContainer(IdleContainer):
        def button(self, label, **kwargs):
            events.append(("click", label))
            return True

    monkeypatch.setattr(module, "_load_orchestrate_args", lambda _path: (_ for _ in ()).throw(RuntimeError("run failed")))
    module._render_run_button(PROJECT_PATH.resolve(), container=ClickContainer())
    assert ("error", "Run failed: run failed") in events


def test_cached_train_uses_isolated_subprocess_in_streamlit_context() -> None:
    module = _load_module()
    if module.torch is None:
        pytest.skip("torch is not installed in this validation environment")

    from streamlit.testing.v1 import AppTest

    module_path = str(MODULE_PATH.resolve())
    script = f"""
from dataclasses import asdict
import importlib.util
from pathlib import Path
import sys

import streamlit as st

path = Path({module_path!r})
spec = importlib.util.spec_from_file_location("pytorch_playground_streamlit_subprocess_regression", path)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
config = module.PlaygroundConfig(sample_count=64, epochs=1, grid_size=12, hidden_layers=(4,))
result = module._cached_train(asdict(config))
st.write(f"status={{result['status']}}")
st.write(f"backend={{result['summary'].get('backend')}}")
"""
    app = AppTest.from_string(script, default_timeout=60)
    app.run()

    assert list(app.exception) == []
    assert [item.value for item in app.markdown] == ["status=ok", "backend=torch"]


def test_isolated_runner_success_serializes_request_and_pythonpath(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    config = module.PlaygroundConfig(sample_count=24, epochs=1, grid_size=8, hidden_layers=(4,))
    captured: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        input_path = Path(cmd[-2])
        output_path = Path(cmd[-1])
        request = module.json.loads(input_path.read_text(encoding="utf-8"))
        captured["request"] = request
        captured["pythonpath"] = kwargs["env"]["PYTHONPATH"]
        output_path.write_text(
            module.json.dumps(
                module._ipc_encode(
                    {
                        "ok": True,
                        "result": {
                            "status": "ok",
                            "summary": {"backend": "torch"},
                            "history": pd.DataFrame({"epoch": [0], "train_loss": [0.4]}),
                        },
                    }
                )
            ),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    result = module._run_core_in_subprocess("train", config)

    assert result["status"] == "ok"
    assert result["summary"]["backend"] == "torch"
    assert result["history"].iloc[0]["train_loss"] == pytest.approx(0.4)
    assert captured["request"]["action"] == "train"
    assert captured["request"]["config"]["hidden_layers"] == [4]
    assert str(module._APP_SRC) in str(captured["pythonpath"]).split(module.os.pathsep)


def test_isolated_runner_failure_paths_return_displayable_error_results(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    config = module.PlaygroundConfig(sample_count=20, epochs=1, grid_size=8)

    def timeout_run(*_args, **_kwargs):
        raise module.subprocess.TimeoutExpired(cmd="python", timeout=180)

    monkeypatch.setattr(module.subprocess, "run", timeout_run)
    train_timeout = module._run_core_in_subprocess("train", config)
    landscape_timeout = module._run_core_in_subprocess("loss_landscape", config, resolution=5, span=0.2)

    assert train_timeout["status"] == "error"
    assert "timed out after 180" in train_timeout["detail"]
    assert train_timeout["samples"].shape[0] == 20
    assert landscape_timeout["status"] == "error"
    assert landscape_timeout["loss_landscape"].empty

    def nonzero_run(_cmd, **_kwargs):
        return SimpleNamespace(returncode=7, stderr="fatal line\n")

    monkeypatch.setattr(module.subprocess, "run", nonzero_run)
    train_nonzero = module._run_core_in_subprocess("train", config)
    nonzero_result = module._run_core_in_subprocess("loss_landscape", config, resolution=5, span=0.2)
    assert train_nonzero["status"] == "error"
    assert train_nonzero["history"].empty
    assert nonzero_result["status"] == "error"
    assert "exit code 7" in nonzero_result["detail"]
    assert "fatal line" in nonzero_result["detail"]

    def payload_run(payload):
        def fake_run(cmd, **_kwargs):
            Path(cmd[-1]).write_text(module.json.dumps(module._ipc_encode(payload)), encoding="utf-8")
            return SimpleNamespace(returncode=0, stderr="")

        return fake_run

    monkeypatch.setattr(module.subprocess, "run", payload_run({"ok": False, "error_type": "ValueError", "error": "bad payload"}))
    failed_payload = module._run_core_in_subprocess("train", config)
    assert failed_payload["status"] == "error"
    assert "ValueError: bad payload" in failed_payload["detail"]

    monkeypatch.setattr(module.subprocess, "run", payload_run(["not", "a", "mapping"]))
    malformed_payload = module._run_core_in_subprocess("loss_landscape", config, resolution=5, span=0.2)
    assert malformed_payload["status"] == "error"
    assert malformed_payload["landscape_summary"]["status"] == "error"

    monkeypatch.setattr(module.subprocess, "run", payload_run({"ok": True, "result": []}))
    invalid_result = module._run_core_in_subprocess("train", config)
    invalid_landscape = module._run_core_in_subprocess("loss_landscape", config, resolution=5, span=0.2)
    assert invalid_result["status"] == "error"
    assert "runner returned an invalid payload" in invalid_result["detail"]
    assert invalid_landscape["status"] == "error"
    assert invalid_landscape["loss_landscape"].empty

    def invalid_json_run(cmd, **_kwargs):
        Path(cmd[-1]).write_text("{not-json", encoding="utf-8")
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(module.subprocess, "run", invalid_json_run)
    invalid_json = module._run_core_in_subprocess("train", config)
    assert invalid_json["status"] == "error"
    assert "JSONDecodeError" in invalid_json["detail"]


def test_isolated_runner_ipc_uses_json_without_pickle() -> None:
    module = _load_module()
    frame = pd.DataFrame({"epoch": [0, 1], "train_loss": [0.5, 0.25]})

    encoded = module._ipc_encode({"history": frame, "nested": [{"grid": frame.iloc[:1]}]})
    decoded = module._ipc_decode(module.json.loads(module.json.dumps(encoded)))

    assert "pickle" not in module._ISOLATED_CORE_RUNNER
    assert decoded["history"].equals(frame)
    assert decoded["nested"][0]["grid"].equals(frame.iloc[:1])


def test_cached_train_and_loss_landscape_route_to_isolated_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    config = module.PlaygroundConfig(sample_count=28, epochs=1, grid_size=8, seed=101)
    calls: list[tuple[str, int | None, float | None]] = []

    def fake_run_core(action, _config, *, resolution=None, span=None):
        calls.append((action, resolution, span))
        if action == "train":
            return {"status": "ok", "summary": {"backend": "isolated"}}
        return {"status": "ok", "loss_landscape": pd.DataFrame(), "landscape_summary": {"points": 0}}

    monkeypatch.setattr(module, "_use_isolated_torch_training", lambda: True)
    monkeypatch.setattr(module, "_run_core_in_subprocess", fake_run_core)

    train_result = module._cached_train(module.asdict(config))
    landscape_result = module._cached_loss_landscape(module.asdict(config), resolution=7, span=0.3)

    assert train_result["summary"]["backend"] == "isolated"
    assert landscape_result["landscape_summary"]["points"] == 0
    assert calls == [("train", None, None), ("loss_landscape", 7, 0.3)]


def test_playground_ui_helper_error_and_display_edges(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    fake_st = SimpleNamespace(session_state={module.TRAINED_CONFIG_STATE_KEY: "bad payload"})
    monkeypatch.setattr(module, "st", fake_st)

    config = module.PlaygroundConfig(sample_count=64, epochs=10, grid_size=12)
    trained, preset, pending = module._resolve_trained_config(
        config,
        module.DEFAULT_PRESET,
        train_requested=False,
    )

    assert trained == config
    assert preset == module.DEFAULT_PRESET
    assert pending is False
    assert module._streamlit_script_context_active() is False
    assert module._session_state_get("missing", "fallback") == "fallback"
    monkeypatch.setattr(module, "st", SimpleNamespace())
    assert module._session_state_get("missing", "fallback") == "fallback"
    assert module._format_percent("bad") == "0%"
    assert module._format_percent(float("nan")) == "0%"
    assert module._confidence_score(pd.DataFrame({"probability": []})) == 0.0
    assert module._class_balance(pd.DataFrame({"target": []})) == "no samples"
    assert module._performance_band({"validation_accuracy": 0.95})[0] == "Strong fit"
    assert module._performance_band({"validation_accuracy": 0.80})[0] == "Learning visible"
    assert module._gap_band({"train_accuracy": 0.90, "validation_accuracy": 0.80})[0] == "Watch the gap"
    assert module._gap_band({"train_accuracy": 0.95, "validation_accuracy": 0.70})[0] == "Likely overfit"
    assert module._confidence_band(pd.DataFrame({"probability": [0.1, 0.9]}))[0] == "Decisive boundary"
    assert module._confidence_band(pd.DataFrame({"probability": [0.30, 0.70]}))[0] == "Boundary forming"


def test_playground_ui_remaining_helper_and_subprocess_edges(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    config = module.PlaygroundConfig(sample_count=16, epochs=2, grid_size=5)

    with pytest.raises(AttributeError, match="definitely_missing"):
        getattr(module, "definitely_missing")
    assert module._ipc_encode(np.array([[1, 2], [3, 4]])) == [[1, 2], [3, 4]]
    with pytest.raises(ValueError, match="invalid dataframe columns"):
        module._ipc_decode({"__type__": module._DATAFRAME_IPC_TYPE, "columns": [1], "records": []})
    with pytest.raises(ValueError, match="invalid dataframe records"):
        module._ipc_decode({"__type__": module._DATAFRAME_IPC_TYPE, "columns": ["x"], "records": {}})

    class IndexOnlyState:
        def __init__(self):
            self.values = {"present": "value"}

        def __getitem__(self, key):
            return self.values[key]

        def __setitem__(self, key, value):
            self.values[key] = value

    state = IndexOnlyState()
    monkeypatch.setattr(module, "st", SimpleNamespace(session_state=state))
    assert module._session_state_get("present", "fallback") == "value"
    assert module._session_state_get("missing", "fallback") == "fallback"
    module._session_state_set("new", "saved")
    assert state.values["new"] == "saved"
    assert module._progress_value(3, 0) == 0.0
    assert module._progress_value(99, 10) == 1.0

    events: list[tuple[str, object]] = []

    class StatusStreamlit:
        session_state = {}

        def caption(self, body):
            events.append(("caption", body))

        def progress(self, value, **kwargs):
            events.append(("progress", value))
            events.append(("progress_text", kwargs.get("text")))

        def rerun(self):
            events.append(("rerun", ""))

    monkeypatch.setattr(module, "st", StatusStreamlit())
    monkeypatch.setattr(module.time, "sleep", lambda delay: events.append(("sleep", delay)))
    module._render_live_training_status({"epoch": 1, "playing": True}, config)
    module._request_live_rerun(0.01)
    assert ("caption", "Live state: playing, epoch 1/2.") in events
    assert ("progress", 0.5) in events
    assert ("rerun", "") in events

    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{not-json", encoding="utf-8")
    list_json = tmp_path / "list.json"
    list_json.write_text("[]\n", encoding="utf-8")
    assert module._read_json_file(bad_json) == {}
    assert module._read_json_file(list_json) == {}
    empty_frame = pd.DataFrame({"x": []})
    recovered_frame = module._read_evidence_frame(tmp_path / "missing.csv", empty_frame)
    assert recovered_frame.empty
    assert recovered_frame is not empty_frame
    assert module._load_evidence_result(tmp_path / "missing-evidence") is None

    evidence_root = tmp_path / "evidence"
    (evidence_root / "config").mkdir(parents=True)
    (evidence_root / "summary").mkdir(parents=True)
    (evidence_root / "manifest.json").write_text(json.dumps({"schema": "demo"}), encoding="utf-8")
    (evidence_root / "config" / "playground_config.json").write_text(
        json.dumps({"config": {"dataset": "xor", "sample_count": 24}}),
        encoding="utf-8",
    )
    (evidence_root / "summary" / "run_summary.json").write_text(
        json.dumps({"summary": {"backend": "saved"}}),
        encoding="utf-8",
    )
    loaded = module._load_latest_evidence_result([tmp_path / "missing", evidence_root])
    assert loaded is not None
    loaded_config, loaded_result, loaded_root = loaded
    assert loaded_root == evidence_root
    assert loaded_config.dataset == "xor"
    assert loaded_result["summary"]["backend"] == "saved"

    samples = pd.DataFrame({"x1": [0.0, 1.0], "x2": [0.0, 1.0], "target": [0, 1]})
    grid = pd.DataFrame({"x1": [0.0], "x2": [0.0], "probability": [0.5]})
    history = pd.DataFrame({"epoch": [1], "train_loss": [0.5], "validation_loss": [0.6]})
    activation_maps = pd.DataFrame({"layer": [1], "neuron": [1], "x1": [0.0], "x2": [0.0], "activation": [0.3]})
    layers = pd.DataFrame({"layer": [1], "kind": ["hidden"], "weight_max_abs": [0.1], "bias_max_abs": [0.2]})
    landscape = pd.DataFrame({"alpha": [0.0], "beta": [0.0], "validation_loss": [0.4]})
    monkeypatch.setattr(module, "go", None)
    assert module._decision_figure(samples, grid, 5) is not None
    assert module._history_figure(history) is not None
    assert module._activation_figure(activation_maps, 1, 1) is not None
    assert module._network_figure(layers) is not None
    assert module._loss_landscape_figure(landscape) is not None

    def timeout_run(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="python", timeout=1)

    monkeypatch.setattr(module.subprocess, "run", timeout_run)
    assert module._run_core_in_subprocess("train", config)["status"] == "error"
    assert module._run_core_in_subprocess("loss_landscape", config)["status"] == "error"

    def failed_run(*_args, **_kwargs):
        return SimpleNamespace(returncode=2, stderr="boom\ntrace")

    monkeypatch.setattr(module.subprocess, "run", failed_run)
    assert "exit code 2" in module._run_core_in_subprocess("train", config)["detail"]

    def malformed_run(args, **_kwargs):
        Path(args[-1]).write_text("{bad-json", encoding="utf-8")
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(module.subprocess, "run", malformed_run)
    assert "JSONDecodeError" in module._run_core_in_subprocess("loss_landscape", config)["detail"]

    def invalid_payload_run(args, **_kwargs):
        Path(args[-1]).write_text(json.dumps({"ok": True, "result": []}), encoding="utf-8")
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(module.subprocess, "run", invalid_payload_run)
    assert "invalid payload" in module._run_core_in_subprocess("train", config)["detail"]


def test_pytorch_playground_experiment_coach_returns_replayable_next_configs() -> None:
    module = _load_module()
    config = module.PlaygroundConfig(
        dataset="xor",
        sample_count=128,
        hidden_layers=(32, 16),
        feature_names=("x1", "x2"),
        epochs=80,
        grid_size=56,
    )
    result = {
        "summary": {
            "train_accuracy": 0.96,
            "validation_accuracy": 0.70,
        },
        "grid": pd.DataFrame({"probability": [0.46, 0.50, 0.54]}),
    }

    recommendations = module._tuning_recommendations(config, result)
    by_title = {item["title"]: item for item in recommendations}

    assert list(by_title) == [
        "Reduce overfit",
        "Sharpen the boundary",
        "Try richer features",
    ]
    for recommendation in recommendations:
        assert recommendation["url"].startswith("?pytorch_playground=")
        decoded = module._decode_share_config(recommendation["token"])
        assert decoded is not None
        assert decoded != config

    reduce_overfit = module._decode_share_config(by_title["Reduce overfit"]["token"])
    sharpen_boundary = module._decode_share_config(by_title["Sharpen the boundary"]["token"])
    richer_features = module._decode_share_config(by_title["Try richer features"]["token"])

    assert reduce_overfit is not None
    assert sharpen_boundary is not None
    assert richer_features is not None
    assert len(reduce_overfit.hidden_layers) < len(config.hidden_layers)
    assert sharpen_boundary.epochs > config.epochs
    assert set(richer_features.feature_names) >= {"x1_x2", "x1_squared", "x2_squared"}


def test_pytorch_playground_experiment_coach_renders_replay_cards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    rendered: list[str] = []

    class FakeColumn:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    class FakeStreamlit:
        def columns(self, spec):
            count = spec if isinstance(spec, int) else len(spec)
            return [FakeColumn() for _ in range(count)]

        def markdown(self, body, **_kwargs):
            rendered.append(str(body))

    monkeypatch.setattr(module, "st", FakeStreamlit())

    config = module.PlaygroundConfig(
        feature_names=("x1", "x2"),
        hidden_layers=(16, 8),
    )
    result = {
        "summary": {"train_accuracy": 0.90, "validation_accuracy": 0.70},
        "grid": pd.DataFrame({"probability": [0.4, 0.5, 0.6]}),
    }

    module._render_experiment_coach(config, result)

    markup = "\n".join(rendered)
    assert "Experiment coach" in markup
    assert "Classic neural playgrounds expose knobs" in markup
    assert markup.count("Open replay config") == 3
    assert "Reduce overfit" in markup
    assert "?pytorch_playground=" in markup


def _runtime_payload_files(root: Path) -> set[Path]:
    return {
        path.relative_to(root)
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix not in {".c", ".pyx", ".so"}
        and "__pycache__" not in path.parts
        and ".venv" not in path.parts
        and path.suffix != ".pyc"
        and not any(part.endswith(".egg-info") for part in path.parts)
    }


def test_pytorch_playground_dataset_generation_is_deterministic() -> None:
    module = _load_module()
    config = module.PlaygroundConfig(dataset="xor", sample_count=48, noise=0.04, seed=17)

    first = module._make_dataset(config)
    second = module._make_dataset(config)

    pd.testing.assert_frame_equal(first, second)
    assert list(first.columns) == ["x1", "x2", "target"]
    assert sorted(first["target"].unique().tolist()) == [0, 1]


def test_pytorch_playground_feature_matrix_uses_selected_features() -> None:
    module = _load_module()
    samples = pd.DataFrame({"x1": [1.0, -0.5], "x2": [2.0, 0.25]})

    matrix = module._feature_matrix(samples, ("x1", "x2_squared", "x1_x2", "sin_x2"))

    np.testing.assert_allclose(
        matrix,
        np.array(
            [
                [1.0, 4.0, 2.0, 0.0],
                [-0.5, 0.0625, -0.125, np.sin(np.pi * 0.25)],
            ],
            dtype=np.float32,
        ),
        atol=1e-7,
    )


def test_pytorch_playground_hidden_layer_parser_validates_bounds() -> None:
    module = _load_module()

    assert module._parse_hidden_layers("8, 16;32") == (8, 16, 32)
    assert module._parse_hidden_layers(" ") == ()

    with pytest.raises(ValueError, match="integer"):
        module._parse_hidden_layers("8,wide")
    with pytest.raises(ValueError, match="between 1 and 256"):
        module._parse_hidden_layers("0")
    with pytest.raises(ValueError, match="at most six"):
        module._parse_hidden_layers("1,2,3,4,5,6,7")


def test_pytorch_playground_reports_missing_torch(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "torch", None)
    monkeypatch.setattr(module, "nn", None)
    config = module.PlaygroundConfig(sample_count=32, epochs=1, grid_size=12)

    result = module._train_playground(config)

    assert result["status"] == "missing_torch"
    assert result["samples"].shape[0] == 32
    assert result["history"].empty
    assert result["grid"].empty
    assert result["network_layers"].empty
    assert result["activation_maps"].empty
    assert result["summary"]["backend"] == "missing"
    landscape = module._loss_landscape(config, resolution=5, span=0.2)
    assert landscape["status"] == "missing_torch"
    assert landscape["loss_landscape"].empty


def test_pytorch_playground_share_config_round_trips_and_sanitizes() -> None:
    module = _load_module()
    config = module.PlaygroundConfig(
        dataset="spiral",
        sample_count=320,
        noise=0.21,
        train_ratio=0.85,
        hidden_layers=(16, 8),
        activation="relu",
        optimizer="SGD",
        regularization="L1",
        regularization_rate=0.015,
        learning_rate=0.015,
        epochs=120,
        batch_size=64,
        seed=42,
        feature_names=("x1", "x2", "sin_x1"),
        grid_size=64,
    )

    token = module._encode_share_config(config)
    decoded = module._decode_share_config(token)

    assert decoded == config
    assert module._config_from_query_params({"pytorch_playground": [token]}) == config
    assert module._decode_share_config("not-valid-base64") is None
    list_payload = module.base64.urlsafe_b64encode(b"[]").decode("ascii").rstrip("=")
    assert module._decode_share_config(list_payload) is None
    sanitized = module._config_from_payload(
        {
            "config": {
                "dataset": "invalid",
                "sample_count": 10_000,
                "noise": float("nan"),
                "hidden_layers": "8,wide",
                "activation": "unknown",
                "optimizer": "bad",
                "regularization": "dropout",
                "regularization_rate": 20.0,
                "feature_names": ["x1", "missing", "x2"],
            }
        }
    )
    assert sanitized.dataset == "circles"
    assert sanitized.sample_count == 1000
    assert sanitized.noise == module.PlaygroundConfig().noise
    assert sanitized.hidden_layers == module.PlaygroundConfig().hidden_layers
    assert sanitized.activation == module.PlaygroundConfig().activation
    assert sanitized.optimizer == module.PlaygroundConfig().optimizer
    assert sanitized.regularization == module.PlaygroundConfig().regularization
    assert sanitized.regularization_rate == 1.0
    assert sanitized.feature_names == ("x1", "x2")
    assert module._preset_config(module.DEFAULT_PRESET).dataset == "circles"
    assert module._preset_config(module.CUSTOM_PRESET, config) == config
    assert "URL token" in module._preset_story(module.CUSTOM_PRESET, config)
    assert module._safe_key_fragment("Hard mode: spiral") == "hard_mode_spiral"
    assert module._config_state_payload(config)["hidden_layers"] == [16, 8]
    assert module._config_signature(config) == module._config_signature(decoded)


def test_pytorch_playground_training_state_stages_control_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    fake_st = SimpleNamespace(session_state={})
    monkeypatch.setattr(module, "st", fake_st)
    first = module.PlaygroundConfig(dataset="circles", seed=1)
    second = module.PlaygroundConfig(dataset="spiral", seed=2)

    trained, preset, pending = module._resolve_trained_config(
        first,
        module.DEFAULT_PRESET,
        train_requested=False,
    )
    assert trained == first
    assert preset == module.DEFAULT_PRESET
    assert pending is False

    trained, _preset, pending = module._resolve_trained_config(
        second,
        "Hard mode: spiral",
        train_requested=False,
    )
    assert trained == first
    assert pending is True

    trained, preset, pending = module._resolve_trained_config(
        second,
        "Hard mode: spiral",
        train_requested=True,
    )
    assert trained == second
    assert preset == "Hard mode: spiral"
    assert pending is False


def test_pytorch_playground_live_training_controls_advance_and_pause(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    fake_st = SimpleNamespace(session_state={})
    monkeypatch.setattr(module, "st", fake_st)
    config = module.PlaygroundConfig(epochs=6)
    signature = module._config_signature(config)

    def fake_new_state(_config):
        return {
            "status": "ok",
            "signature": signature,
            "config": config,
            "epoch": 0,
            "playing": False,
        }

    def fake_advance(state, *, epochs=1):
        updated = dict(state)
        updated["epoch"] = min(config.epochs, int(updated["epoch"]) + int(epochs))
        if updated["epoch"] >= config.epochs:
            updated["playing"] = False
        return updated

    def fake_result(state):
        return {"status": "ok", "summary": {"epoch": int(state["epoch"])}}

    monkeypatch.setattr(module, "_new_live_training_state", fake_new_state)
    monkeypatch.setattr(module, "_advance_live_training", fake_advance)
    monkeypatch.setattr(module, "_live_training_result", fake_result)

    state, result, keep_playing = module._run_live_training_controls(
        config,
        reset_requested=False,
        step_requested=False,
        play_requested=True,
        pause_requested=False,
        epochs_per_tick=2,
    )
    assert state["epoch"] == 2
    assert state["playing"] is True
    assert result["summary"]["epoch"] == 2
    assert keep_playing is True

    state, _result, keep_playing = module._run_live_training_controls(
        config,
        reset_requested=False,
        step_requested=False,
        play_requested=False,
        pause_requested=True,
        epochs_per_tick=2,
    )
    assert state["epoch"] == 2
    assert state["playing"] is False
    assert keep_playing is False


def test_pytorch_playground_live_training_result_reports_missing_torch(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "torch", None)
    monkeypatch.setattr(module, "nn", None)
    config = module.PlaygroundConfig(sample_count=64, epochs=4)

    state = module._new_live_training_state(config)
    result = module._live_training_result(state)

    assert state["status"] == "missing_torch"
    assert result["status"] == "missing_torch"
    assert result["summary"]["backend"] == "missing"
    assert result["summary"]["target_epochs"] == 4


def test_pytorch_playground_config_and_dataset_helper_edges(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_module()

    active_app = tmp_path / "active_app"
    active_app.mkdir()
    monkeypatch.setattr(sys, "argv", ["playground_ui.py", "--active-app", str(active_app)])
    assert module._resolve_active_app() == active_app.resolve()
    monkeypatch.setattr(sys, "argv", ["playground_ui.py", "--active-app", str(tmp_path / "missing")])
    assert module._resolve_active_app() is None
    monkeypatch.setattr(sys, "argv", ["playground_ui.py"])
    assert module._resolve_active_app() is None

    default = module.PlaygroundConfig()
    assert module._bounded_int("bad", default=5, minimum=1, maximum=10) == 5
    assert module._bounded_int(99, default=5, minimum=1, maximum=10) == 10
    assert module._bounded_float(None, default=0.2, minimum=0.0, maximum=1.0) == 0.2
    assert module._bounded_float(float("inf"), default=0.2, minimum=0.0, maximum=1.0) == 0.2
    assert module._bounded_float(-2.0, default=0.2, minimum=0.0, maximum=1.0) == 0.0
    assert module._coerce_hidden_layers([4, 2]) == (4, 2)
    assert module._coerce_hidden_layers(["bad"], (3,)) == (3,)
    assert module._coerce_hidden_layers(object(), (3,)) == (3,)
    assert module._coerce_feature_names("x1, missing, sin_x2") == ("x1", "sin_x2")
    assert module._coerce_feature_names(object(), ("x2",)) == ("x2",)
    assert module._config_from_payload({"config": []}) == default
    assert module._first_query_value([]) is None
    assert module._first_query_value(None) is None
    assert module._config_from_query_params({"config": module._encode_share_config(default)}) == default

    for dataset in ("circles", "spiral", "gaussian", "invalid"):
        frame = module._make_dataset(module.PlaygroundConfig(dataset=dataset, sample_count=35, seed=5))
        assert list(frame.columns) == ["x1", "x2", "target"]
        assert len(frame) == 35
        assert set(frame["target"].unique()) <= {0, 1}

    ndarray_features = module._feature_matrix(np.array([[1.0, 2.0], [3.0, 4.0]]), ())
    np.testing.assert_allclose(ndarray_features, np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32))


def _minimal_playground_result(module, config) -> dict[str, object]:
    samples = module._make_dataset(config)
    history = pd.DataFrame(
        {
            "epoch": [0],
            "train_loss": [0.5],
            "validation_loss": [0.6],
            "train_accuracy": [0.75],
            "validation_accuracy": [0.7],
        }
    )
    grid = pd.DataFrame(
        {
            "x1": [-1.0, 1.0, -1.0, 1.0],
            "x2": [-1.0, -1.0, 1.0, 1.0],
            "probability": [0.1, 0.9, 0.2, 0.8],
        }
    )
    boundary_snapshots = grid.copy()
    boundary_snapshots.insert(0, "epoch", 0)
    loss_landscape = pd.DataFrame(
        [
            {
                "alpha": -0.2,
                "beta": -0.2,
                "train_loss": 0.62,
                "validation_loss": 0.68,
                "train_accuracy": 0.65,
                "validation_accuracy": 0.6,
                "is_center": False,
            },
            {
                "alpha": 0.0,
                "beta": 0.0,
                "train_loss": 0.5,
                "validation_loss": 0.55,
                "train_accuracy": 0.75,
                "validation_accuracy": 0.7,
                "is_center": True,
            },
        ],
        columns=module._empty_loss_landscape().columns,
    )
    return {
        "status": "ok",
        "detail": "",
        "samples": samples,
        "history": history,
        "grid": grid,
        "boundary_snapshots": boundary_snapshots,
        "network_layers": module._empty_network_layers(),
        "activation_maps": module._empty_activation_maps(),
        "loss_landscape": loss_landscape,
        "landscape_summary": module._loss_landscape_summary(loss_landscape),
        "summary": {
            "backend": "persisted",
            "samples": int(len(samples)),
            "features": int(len(config.feature_names)),
            "train_accuracy": 0.75,
            "validation_accuracy": 0.7,
            "validation_loss": 0.55,
        },
    }


def _write_playground_evidence_dir(module, root: Path, config, result: dict[str, object]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for relative_path, payload in module._evidence_artifact_files(config, result).items():
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    (root / "manifest.json").write_bytes(module._json_bytes(module._build_evidence_manifest(config, result)))


def test_pytorch_playground_evidence_pack_is_deterministic(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "torch", None)
    monkeypatch.setattr(module, "nn", None)
    config = module.PlaygroundConfig(sample_count=32, epochs=10, grid_size=12, seed=11)
    result = module._train_playground(config)
    loss_landscape = pd.DataFrame(
        [
            {
                "alpha": -0.1,
                "beta": 0.0,
                "train_loss": 0.7,
                "validation_loss": 0.8,
                "train_accuracy": 0.5,
                "validation_accuracy": 0.5,
                "is_center": False,
            },
            {
                "alpha": 0.0,
                "beta": 0.0,
                "train_loss": 0.5,
                "validation_loss": 0.6,
                "train_accuracy": 0.75,
                "validation_accuracy": 0.7,
                "is_center": True,
            },
        ],
        columns=module._empty_loss_landscape().columns,
    )
    result["loss_landscape"] = loss_landscape
    result["landscape_summary"] = module._loss_landscape_summary(loss_landscape)

    first = module._build_evidence_pack(config, result)
    second = module._build_evidence_pack(config, result)

    assert first == second
    archive_path = tmp_path / "pytorch_playground_evidence_test.zip"
    archive_path.write_bytes(first)
    with zipfile.ZipFile(archive_path, "r") as archive:
        names = archive.namelist()
        assert names == sorted(names)
        assert {
            "manifest.json",
            "config/playground_config.json",
            "data/samples.csv",
            "data/training_history.csv",
            "data/decision_grid.csv",
            "data/boundary_snapshots.csv",
            "model/network_layers.csv",
            "model/hidden_activation_maps.csv",
            "model/loss_landscape.csv",
            "reuse/train_plain_pytorch.py",
            "reuse/train_pytorch_lightning.py",
            "summary/run_summary.json",
        }.issubset(set(names))
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        sample_bytes = archive.read("data/samples.csv")
        plain_snippet_bytes = archive.read("reuse/train_plain_pytorch.py")
        lightning_snippet_bytes = archive.read("reuse/train_pytorch_lightning.py")
        boundary_snapshot_bytes = archive.read("data/boundary_snapshots.csv")
        landscape_bytes = archive.read("model/loss_landscape.csv")

    assert manifest["schema"] == module.EVIDENCE_SCHEMA
    assert manifest["app"] == "pytorch_playground_project"
    assert manifest["config_schema"] == module.CONFIG_SCHEMA
    assert manifest["row_counts"]["samples"] == 32
    assert manifest["row_counts"]["boundary_snapshots"] == 0
    assert manifest["row_counts"]["loss_landscape"] == 2
    assert manifest["landscape_summary"]["center_validation_loss"] == pytest.approx(0.6)
    assert manifest["artifacts"]["data/samples.csv"]["sha256"] == hashlib.sha256(sample_bytes).hexdigest()
    assert b"python reuse/train_plain_pytorch.py" in plain_snippet_bytes
    assert b'ROOT / "data" / "samples.csv"' in plain_snippet_bytes
    assert b"python reuse/train_pytorch_lightning.py" in lightning_snippet_bytes
    assert b'ROOT / "data" / "samples.csv"' in lightning_snippet_bytes
    assert (
        manifest["artifacts"]["reuse/train_plain_pytorch.py"]["sha256"]
        == hashlib.sha256(plain_snippet_bytes).hexdigest()
    )
    assert (
        manifest["artifacts"]["reuse/train_pytorch_lightning.py"]["sha256"]
        == hashlib.sha256(lightning_snippet_bytes).hexdigest()
    )
    assert (
        manifest["artifacts"]["data/boundary_snapshots.csv"]["sha256"]
        == hashlib.sha256(boundary_snapshot_bytes).hexdigest()
    )
    assert manifest["artifacts"]["model/loss_landscape.csv"]["sha256"] == hashlib.sha256(landscape_bytes).hexdigest()


def test_pytorch_playground_reuse_snippets_are_config_driven() -> None:
    module = _load_module()
    config = module.PlaygroundConfig(
        dataset="xor",
        sample_count=128,
        hidden_layers=(16, 8),
        activation="relu",
        optimizer="SGD",
        regularization="L1",
        regularization_rate=0.003,
        learning_rate=0.025,
        epochs=12,
        batch_size=24,
        seed=19,
        feature_names=("x1", "x2", "x1_x2"),
    )

    plain = module._plain_pytorch_reuse_snippet(config)
    lightning = module._pytorch_lightning_reuse_snippet(config)

    compile(plain, "train_plain_pytorch.py", "exec")
    compile(lightning, "train_pytorch_lightning.py", "exec")
    assert "'dataset': 'xor'" in plain
    assert "'hidden_layers': [16, 8]" in plain
    assert "'feature_names': ['x1', 'x2', 'x1_x2']" in plain
    assert "'optimizer': 'SGD'" in plain
    assert "'regularization': 'L1'" in plain
    assert "torch.optim.SGD" in plain
    assert 'ROOT / "data" / "samples.csv"' in plain
    assert "python reuse/train_plain_pytorch.py" in plain
    assert "lightning.pytorch as L" not in plain
    assert "import lightning.pytorch as L" in lightning
    assert "class PlaygroundModule(L.LightningModule)" in lightning
    assert "'learning_rate': 0.025" in lightning
    assert 'ROOT / "data" / "samples.csv"' in lightning
    assert "python reuse/train_pytorch_lightning.py" in lightning


def test_pytorch_playground_loads_latest_evidence_result(tmp_path: Path) -> None:
    module = _load_module()
    old_config = module.PlaygroundConfig(dataset="circles", sample_count=64, grid_size=12, seed=3)
    latest_config = module.PlaygroundConfig(dataset="spiral", sample_count=96, grid_size=16, seed=7)
    old_dir = tmp_path / "old"
    latest_dir = tmp_path / "latest"

    _write_playground_evidence_dir(module, old_dir, old_config, _minimal_playground_result(module, old_config))
    _write_playground_evidence_dir(
        module,
        latest_dir,
        latest_config,
        _minimal_playground_result(module, latest_config),
    )
    module.os.utime(old_dir / "manifest.json", (1, 1))
    module.os.utime(latest_dir / "manifest.json", (2, 2))

    loaded = module._load_latest_evidence_result([old_dir, latest_dir])

    assert loaded is not None
    config, result, evidence_root = loaded
    assert evidence_root == latest_dir
    assert config.dataset == "spiral"
    assert config.sample_count == 96
    assert result["status"] == "ok"
    assert result["summary"]["backend"] == "persisted"
    assert len(result["samples"]) == 96
    assert len(result["loss_landscape"]) == 2


def test_pytorch_playground_analysis_uses_evidence_without_training(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_module()

    class FakeContext:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def metric(self, *_args, **_kwargs):
            return None

    class FakeStreamlit:
        def __init__(self):
            self.query_params = {}
            self.session_state: dict[str, object] = {}
            self.sidebar = FakeContext()
            self.captions: list[str] = []
            self.downloads: list[bytes] = []
            self.code_payloads: list[tuple[str, str | None]] = []

        def set_page_config(self, **_kwargs):
            return None

        def title(self, *_args, **_kwargs):
            return None

        def caption(self, message, **_kwargs):
            self.captions.append(str(message))

        def markdown(self, *_args, **_kwargs):
            return None

        def error(self, *_args, **_kwargs):
            return None

        def warning(self, *_args, **_kwargs):
            return None

        def info(self, *_args, **_kwargs):
            return None

        def columns(self, spec):
            count = spec if isinstance(spec, int) else len(spec)
            return [FakeContext() for _ in range(count)]

        def tabs(self, labels):
            return [FakeContext() for _ in labels]

        def plotly_chart(self, *_args, **_kwargs):
            return None

        def dataframe(self, *_args, **_kwargs):
            return None

        def metric(self, *_args, **_kwargs):
            return None

        def download_button(self, _label, data, **_kwargs):
            self.downloads.append(data)
            return False

        def code(self, body, **kwargs):
            self.code_payloads.append((str(body), kwargs.get("language")))
            return None

    evidence_dir = tmp_path / "evidence"
    config = module.PlaygroundConfig(dataset="spiral", sample_count=64, grid_size=12, seed=21)
    _write_playground_evidence_dir(module, evidence_dir, config, _minimal_playground_result(module, config))

    fake_st = FakeStreamlit()
    monkeypatch.setattr(module, "st", fake_st)
    monkeypatch.setattr(module, "render_logo", lambda: None)
    monkeypatch.setattr(module, "_resolve_active_app", lambda: PROJECT_PATH.resolve())
    monkeypatch.setattr(
        module,
        "_cached_train",
        lambda _payload: (_ for _ in ()).throw(AssertionError("analysis must not train on render")),
    )
    monkeypatch.setattr(
        module,
        "_cached_loss_landscape",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("analysis must not compute landscape on render")),
    )
    monkeypatch.setattr(module, "_decision_figure", lambda *_args, **_kwargs: "decision-figure")
    monkeypatch.setattr(module, "_history_figure", lambda *_args, **_kwargs: "history-figure")
    monkeypatch.setattr(module, "_network_figure", lambda *_args, **_kwargs: "network-figure")
    monkeypatch.setattr(module, "_loss_landscape_figure", lambda *_args, **_kwargs: "landscape-figure")

    module.main(
        interactive_controls=False,
        compute_loss_landscape=True,
        evidence_dirs=[evidence_dir],
    )

    assert any(str(evidence_dir) in caption for caption in fake_st.captions)
    assert fake_st.downloads
    manifest = next(json.loads(body) for body, language in fake_st.code_payloads if language == "json")
    assert manifest["backend"] == "persisted"
    assert manifest["row_counts"]["samples"] == 64
    python_snippets = [body for body, language in fake_st.code_payloads if language == "python"]
    assert len(python_snippets) == 2
    assert "class Classifier(nn.Module)" in python_snippets[0]
    assert "class PlaygroundModule(L.LightningModule)" in python_snippets[1]


def test_pytorch_playground_loss_landscape_summary_marks_center_and_best() -> None:
    module = _load_module()
    landscape = pd.DataFrame(
        [
            {"alpha": -0.5, "beta": 0.0, "train_loss": 0.8, "validation_loss": 0.9, "train_accuracy": 0.4, "validation_accuracy": 0.4, "is_center": False},
            {"alpha": 0.0, "beta": 0.0, "train_loss": 0.4, "validation_loss": 0.5, "train_accuracy": 0.8, "validation_accuracy": 0.75, "is_center": True},
            {"alpha": 0.5, "beta": 0.0, "train_loss": 0.3, "validation_loss": 0.45, "train_accuracy": 0.85, "validation_accuracy": 0.8, "is_center": False},
        ],
        columns=module._empty_loss_landscape().columns,
    )

    summary = module._loss_landscape_summary(landscape)

    assert summary["status"] == "ok"
    assert summary["points"] == 3
    assert summary["center_validation_loss"] == pytest.approx(0.5)
    assert summary["best_validation_loss"] == pytest.approx(0.45)
    assert summary["best_delta"] == pytest.approx(-0.05)
    assert summary["sharpness"] == pytest.approx(0.4)


def test_pytorch_playground_evidence_and_figure_helpers_cover_fallbacks(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "torch", None)
    monkeypatch.setattr(module, "nn", None)

    config = module.PlaygroundConfig(sample_count=20, grid_size=3, hidden_layers=())
    samples = pd.DataFrame({"x1": [-0.5, 0.5], "x2": [0.2, -0.2], "target": [0, 1]})
    irregular_grid = pd.DataFrame(
        {
            "x1": [-1.0, 0.0, 1.0],
            "x2": [-1.0, 0.0, 1.0],
            "probability": [0.1, 0.5, 0.9],
        }
    )
    history = pd.DataFrame(
        {
            "epoch": [0, 1],
            "train_loss": [0.8, 0.4],
            "validation_loss": [0.9, 0.5],
            "train_accuracy": [0.5, 0.8],
            "validation_accuracy": [0.4, 0.7],
        }
    )
    activation_maps = pd.DataFrame(
        {
            "layer": [1, 1, 1, 1],
            "neuron": [1, 1, 1, 1],
            "x1": [-1.0, 1.0, -1.0, 1.0],
            "x2": [-1.0, -1.0, 1.0, 1.0],
            "activation": [0.0, 0.5, 0.25, 1.0],
        }
    )
    loss_landscape = pd.DataFrame(
        {
            "alpha": [-0.5, 0.0, 0.5],
            "beta": [-0.5, 0.0, 0.5],
            "train_loss": [0.7, 0.5, 0.6],
            "validation_loss": [0.8, 0.45, 0.55],
            "train_accuracy": [0.5, 0.7, 0.6],
            "validation_accuracy": [0.4, 0.8, 0.7],
            "is_center": [False, True, False],
        }
    )
    layers = pd.DataFrame(
        [
            {
                "layer": 1,
                "kind": "hidden",
                "input_features": 2,
                "output_features": 3,
                "parameters": 9,
                "weight_mean": 0.1,
                "weight_std": 0.2,
                "weight_max_abs": 0.4,
                "bias_mean": 0.0,
                "bias_std": 0.1,
                "bias_max_abs": 0.2,
            }
        ]
    )
    result = {
        "samples": samples,
        "history": history,
        "grid": irregular_grid,
        "network_layers": layers,
        "activation_maps": activation_maps,
        "loss_landscape": loss_landscape,
        "summary": {"backend": "synthetic", "samples": 2, "features": 2},
    }

    assert module._activation_module.__name__ == "_activation_module"
    with pytest.raises(RuntimeError, match="PyTorch is not available"):
        module._activation_module("relu")
    with pytest.raises(RuntimeError, match="PyTorch is not available"):
        module._build_model(2, config)
    assert module._hidden_activation_maps(object(), config, np.ones((1, 2)), np.ones((1, 2))).empty
    assert module._array_stats(np.array([])) == {"mean": 0.0, "std": 0.0, "max_abs": 0.0}
    assert module._network_layers([]).empty
    assert module._empty_loss_landscape().empty
    assert module._normalized_landscape_resolution(4) == 5
    assert module._normalized_landscape_resolution(40) == 31
    assert module._loss_landscape_summary(module._empty_loss_landscape()) == {"status": "not_computed", "points": 0}
    landscape_summary = module._loss_landscape_summary(loss_landscape)
    assert landscape_summary["status"] == "ok"
    assert landscape_summary["best_validation_loss"] == 0.45
    assert module._loss_landscape(config)["status"] == "missing_torch"
    assert module._result_frame({}, "missing", samples) is samples
    assert module._json_safe({"bad": np.float64(float("nan")), "count": np.int64(3)}) == {"bad": None, "count": 3}
    assert module._format_percent(0.812) == "81%"
    assert module._confidence_score(irregular_grid) == pytest.approx(0.5333333333333333)
    assert module._confidence_score(pd.DataFrame(columns=["x1", "x2"])) == 0.0
    assert module._class_balance(samples) == "50/50% class split"
    assert module._class_balance(pd.DataFrame()) == "no samples"
    assert module._parameter_count(layers) == 9
    assert module._parameter_count(module._empty_network_layers()) == 0
    assert module._generalization_gap({"train_accuracy": 0.9, "validation_accuracy": 0.75}) == pytest.approx(0.15)

    x_axis, y_axis = module._grid_axes(irregular_grid, 5)
    assert len(x_axis) == 2
    assert len(y_axis) == 2
    assert module._grid_axes(pd.DataFrame(), 5)[0].size == 0
    assert len(module._decision_figure(samples, irregular_grid, 5).data) == 4
    assert len(module._decision_figure(samples, pd.DataFrame(columns=["x1", "x2", "probability"]), 5).data) == 2
    assert len(module._history_figure(history).data) == 4
    assert len(module._history_figure(pd.DataFrame()).data) == 0
    assert len(module._activation_figure(activation_maps, 1, 1).data) == 1
    assert len(module._activation_figure(activation_maps, 2, 1).data) == 0
    assert len(module._network_figure(layers).data) == 2
    assert len(module._network_figure(module._empty_network_layers()).data) == 0
    assert len(module._loss_landscape_figure(loss_landscape).data) == 3
    assert len(module._loss_landscape_figure(module._empty_loss_landscape()).data) == 0

    manifest = module._build_evidence_manifest(config, result)
    assert manifest["row_counts"]["network_layers"] == 1
    assert manifest["row_counts"]["loss_landscape"] == 3
    assert set(module._evidence_artifact_files(config, {"summary": {}})) >= {
        "data/samples.csv",
        "model/network_layers.csv",
        "model/loss_landscape.csv",
    }
    assert module._cached_train(module.asdict(config))["status"] == "missing_torch"
    assert module._cached_loss_landscape(module.asdict(config), 4, 0.5)["status"] == "missing_torch"


def test_pytorch_playground_summary_uses_shared_header_style(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    rendered: list[str] = []

    class FakeColumn:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    class FakeStreamlit:
        def columns(self, spec):
            count = spec if isinstance(spec, int) else len(spec)
            return [FakeColumn() for _ in range(count)]

        def markdown(self, body, **_kwargs):
            rendered.append(str(body))

    monkeypatch.setattr(module, "st", FakeStreamlit())

    config = module.PlaygroundConfig(hidden_layers=(16, 8), feature_names=("x1", "x2"))
    samples = pd.DataFrame(
        {
            "x1": [0.0, 0.1, 0.2, 0.3],
            "x2": [0.0, 0.1, 0.2, 0.3],
            "target": [0, 0, 1, 1],
        }
    )
    result = {
        "samples": samples,
        "grid": pd.DataFrame({"probability": [0.0, 1.0]}),
        "network_layers": pd.DataFrame({"parameters": [100, 154]}),
        "summary": {
            "train_accuracy": 0.998,
            "validation_accuracy": 0.96,
            "samples": 320,
        },
    }

    module._render_compact_header(PROJECT_PATH.resolve(), "ORCHESTRATE args", config)
    module._render_summary(config, result)

    markup = "\n".join(rendered)
    assert "agilab-header-card" in markup
    assert "ORCHESTRATE args" in markup
    assert "Strong run: low overfit, clear boundary" in markup
    assert markup.count("96%") == 1
    assert "Train-val gap" in markup
    assert "3.8 pp" in markup
    assert "Decision confidence" in markup
    assert "254 params" in markup
    assert "2 hidden layer(s)" in markup
    assert "320 samples" in markup
    assert "50/50% class split" in markup
    assert "Boundary confidence" not in markup
    assert "mean distance from indecision" not in markup


def test_pytorch_playground_compact_summary_keeps_tabs_close(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    rendered: list[str] = []

    class FakeStreamlit:
        def markdown(self, body, **_kwargs):
            rendered.append(str(body))

    monkeypatch.setattr(module, "st", FakeStreamlit())

    config = module.PlaygroundConfig(hidden_layers=(16, 8), feature_names=("x1", "x2"))
    samples = pd.DataFrame(
        {
            "x1": [0.0, 0.1, 0.2, 0.3],
            "x2": [0.0, 0.1, 0.2, 0.3],
            "target": [0, 0, 1, 1],
        }
    )
    result = {
        "samples": samples,
        "grid": pd.DataFrame({"probability": [0.0, 1.0]}),
        "network_layers": pd.DataFrame({"parameters": [100, 154]}),
        "summary": {
            "train_accuracy": 0.998,
            "validation_accuracy": 0.96,
            "samples": 320,
        },
    }

    module._render_compact_header(PROJECT_PATH.resolve(), "ORCHESTRATE args", config)
    module._render_summary(config, result, compact=True)

    markup = "\n".join(rendered)
    assert "agilab-pt-compact-meta" in markup
    assert "agilab-pt-run-panel" in markup
    assert "agilab-header-card" not in markup
    assert "Strong run: low overfit" not in markup
    assert "Strong run" in markup
    assert markup.count("96%") == 1
    assert "ORCHESTRATE args" in markup
    assert "app: pytorch_playground_project" in markup
    assert "Validation" in markup
    assert "Train-val gap" in markup
    assert "Decision confidence" in markup


def test_pytorch_playground_fake_nn_covers_model_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()

    class FakeTensor:
        def __init__(self, values):
            self._values = np.asarray(values, dtype=float)

        def detach(self):
            return self

        def cpu(self):
            return self

        def numpy(self):
            return self._values

    class FakeLinear:
        def __init__(self, in_features: int, out_features: int, *, bias: bool = True):
            self.in_features = in_features
            self.out_features = out_features
            self.weight = FakeTensor(np.full((out_features, in_features), 0.25))
            self.bias = FakeTensor(np.linspace(-0.1, 0.1, out_features)) if bias else None

    class FakeSequential(list):
        def __init__(self, *layers):
            super().__init__(layers)

    fake_nn = SimpleNamespace(
        Linear=FakeLinear,
        ReLU=lambda: SimpleNamespace(kind="relu"),
        Sigmoid=lambda: SimpleNamespace(kind="sigmoid"),
        Identity=lambda: SimpleNamespace(kind="identity"),
        Tanh=lambda: SimpleNamespace(kind="tanh"),
        Sequential=FakeSequential,
    )
    monkeypatch.setattr(module, "nn", fake_nn)

    assert module._activation_module("relu").kind == "relu"
    assert module._activation_module("sigmoid").kind == "sigmoid"
    assert module._activation_module("identity").kind == "identity"
    assert module._activation_module("other").kind == "tanh"

    model = module._build_model(
        3,
        module.PlaygroundConfig(hidden_layers=(4, 2), activation="identity"),
    )
    assert [type(layer).__name__ for layer in model].count("FakeLinear") == 3
    layers = module._network_layers(model)
    assert layers["kind"].tolist() == ["hidden", "hidden", "output"]
    assert layers["parameters"].tolist() == [16, 10, 6]

    no_bias = module._network_layers([FakeLinear(2, 1, bias=False)])
    assert no_bias.iloc[0]["bias_max_abs"] == 0.0
    assert module._grid_points(module.PlaygroundConfig(grid_size=4)).shape == (144, 2)


def test_pytorch_playground_fake_torch_covers_activation_and_grid_helpers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()

    class FakeTorchTensor:
        def __init__(self, values):
            self.values = np.asarray(values, dtype=float)

        def __getitem__(self, key):
            return FakeTorchTensor(self.values[key])

        def detach(self):
            return self

        def cpu(self):
            return self

        def numpy(self):
            return self.values

    class FakeNoGrad:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    class FakeTorch:
        float32 = "float32"
        long = "long"

        @staticmethod
        def tensor(values, dtype=None):
            if dtype == FakeTorch.long:
                return np.asarray(values, dtype=np.int64)
            return FakeTorchTensor(values)

        @staticmethod
        def no_grad():
            return FakeNoGrad()

        @staticmethod
        def softmax(logits, dim=1):
            values = logits.values
            shifted = values - values.max(axis=dim, keepdims=True)
            exp = np.exp(shifted)
            return FakeTorchTensor(exp / exp.sum(axis=dim, keepdims=True))

    class FakeLinear:
        def __init__(self, in_features: int, out_features: int):
            self.in_features = in_features
            self.out_features = out_features

        def __call__(self, values):
            row_count = values.values.shape[0]
            columns = [
                values.values[:, index % values.values.shape[1]] + (index + 1) * 0.1
                for index in range(self.out_features)
            ]
            return FakeTorchTensor(np.column_stack(columns).reshape(row_count, self.out_features))

    class FakeActivation:
        def __call__(self, values):
            return values

    class FakeModel(list):
        def eval(self):
            return None

        def __call__(self, values):
            for layer in self:
                values = layer(values)
            return values

    monkeypatch.setattr(
        module,
        "nn",
        SimpleNamespace(Linear=FakeLinear),
    )
    monkeypatch.setattr(module, "torch", FakeTorch)

    config = module.PlaygroundConfig(
        sample_count=20,
        train_ratio=0.8,
        hidden_layers=(3,),
        feature_names=("x1", "x2"),
        grid_size=12,
    )
    training_data = module._prepare_training_data(config)
    assert training_data["x_train"].values.shape[1] == 2
    assert training_data["y_train"].dtype == np.int64

    model = FakeModel([FakeLinear(2, 3), FakeActivation(), FakeLinear(3, 2)])
    activation_maps = module._hidden_activation_maps(
        model,
        config,
        training_data["mean"],
        training_data["std"],
        max_neurons=2,
    )
    assert activation_maps.shape[0] == 12 * 12 * 2
    assert sorted(activation_maps["neuron"].unique().tolist()) == [1, 2]

    decision_grid = module._decision_grid(model, config, training_data["mean"], training_data["std"])
    assert decision_grid.shape[0] == 12 * 12
    assert decision_grid["probability"].between(0.0, 1.0).all()


def test_pytorch_playground_training_smoke_when_torch_is_available() -> None:
    module = _load_module()
    if module.torch is None:
        pytest.skip("torch is not installed in this validation environment")

    config = module.PlaygroundConfig(
        dataset="gaussian",
        sample_count=40,
        hidden_layers=(4,),
        epochs=2,
        batch_size=16,
        feature_names=("x1", "x2"),
        grid_size=12,
        seed=3,
    )

    result = module._train_playground(config)

    assert result["status"] == "ok"
    assert not result["history"].empty
    assert result["grid"].shape[0] == 144
    assert sorted(result["boundary_snapshots"]["epoch"].unique().tolist()) == [0, 1, 2]
    assert not result["network_layers"].empty
    assert not result["activation_maps"].empty
    assert sorted(result["activation_maps"]["layer"].unique().tolist()) == [1]
    assert 0.0 <= result["summary"]["validation_accuracy"] <= 1.0
    assert result["summary"]["backend"] == "torch"

    landscape_result = module._loss_landscape(config, resolution=5, span=0.2)
    assert landscape_result["status"] == "ok"
    assert landscape_result["loss_landscape"].shape[0] == 25
    assert landscape_result["loss_landscape"]["is_center"].sum() == 1
    assert landscape_result["landscape_summary"]["points"] == 25

    live_state = module._new_live_training_state(config)
    live_state["playing"] = True
    live_state = module._advance_live_training(live_state, epochs=1)
    live_result = module._live_training_result(live_state)
    assert live_state["epoch"] == 1
    assert live_state["playing"] is True
    assert live_result["status"] == "ok"
    assert live_result["summary"]["backend"] == "torch-live"
    assert live_result["summary"]["epoch"] == 1
    assert live_result["grid"].shape[0] == 144

    live_state = module._advance_live_training(live_state, epochs=99)
    assert live_state["epoch"] == config.epochs
    assert live_state["playing"] is False


def test_pytorch_playground_app_args_convert_to_playground_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(PROJECT_SRC.resolve()))
    app_args = importlib.import_module("pytorch_playground.app_args")

    args = app_args.PytorchPlaygroundArgs(
        hidden_layers="4, 2",
        feature_names="x1, missing, sin_x2",
        regularization="L2",
        regularization_rate=0.01,
        sample_count=96,
    )
    config = app_args.to_playground_config(args)

    assert config.hidden_layers == (4, 2)
    assert config.feature_names == ("x1", "sin_x2")
    assert config.regularization == "L2"
    assert config.regularization_rate == pytest.approx(0.01)
    assert config.sample_count == 96


def test_pytorch_playground_distribution_marks_extra_workers_idle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(PROJECT_SRC.resolve()))
    manager_module = importlib.import_module("pytorch_playground.pytorch_playground")

    manager = manager_module.PytorchPlayground.__new__(manager_module.PytorchPlayground)
    work_plan, metadata, id_name, count_name, label = manager.build_distribution(3)
    fallback_plan, fallback_metadata, *_ = manager.build_distribution("bad")

    assert work_plan == [[["pytorch_playground"]], [], []]
    assert metadata == [[{"run": "pytorch_playground", "work_items": 1}], [], []]
    assert fallback_plan == [[["pytorch_playground"]]]
    assert fallback_metadata == [[{"run": "pytorch_playground", "work_items": 1}]]
    assert (id_name, count_name, label) == ("run", "work_items", "items")


def test_pytorch_playground_manager_initialization_and_toml_edges(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.syspath_prepend(str(PROJECT_SRC.resolve()))
    manager_module = importlib.import_module("pytorch_playground.pytorch_playground")
    args_module = importlib.import_module("pytorch_playground.app_args")

    def fake_share_dir(self, env):
        self.share_checked = env

    def fake_managed_paths(self, args):
        return args

    monkeypatch.setattr(manager_module.PytorchPlayground, "_ensure_managed_pc_share_dir", fake_share_dir)
    monkeypatch.setattr(manager_module.PytorchPlayground, "_apply_managed_pc_paths", fake_managed_paths)

    class FakeEnv:
        verbose = 2
        AGILAB_EXPORT_ABS = tmp_path / "export"
        target = "custom_target"
        app = ""
        active_app = ""

        def resolve_share_path(self, value):
            return tmp_path / "share" / Path(value)

    existing = tmp_path / "share" / "pytorch_playground" / "evidence"
    existing.mkdir(parents=True)
    (existing / "stale.txt").write_text("old", encoding="utf-8")

    manager = manager_module.PytorchPlayground(
        FakeEnv(),
        data_out=Path("pytorch_playground/evidence"),
        reset_target=True,
        sample_count=96,
    )

    assert manager.verbose == 2
    assert manager.data_out == existing
    assert not (existing / "stale.txt").exists()
    assert manager.analysis_artifact_dir == tmp_path / "export" / "custom_target" / "pytorch_playground"
    assert manager.as_dict()["sample_count"] == 96

    settings_path = tmp_path / "settings.toml"
    manager.to_toml(settings_path)
    loaded = manager_module.PytorchPlayground.from_toml(
        FakeEnv(),
        settings_path=settings_path,
        sample_count=128,
    )
    assert loaded.as_dict()["sample_count"] == 128

    with pytest.raises(ValueError, match="Invalid PyTorch playground arguments"):
        manager_module.PytorchPlayground(FakeEnv(), sample_count=1)

    app_suffix = manager_module.PytorchPlaygroundApp.__new__(manager_module.PytorchPlaygroundApp)
    assert isinstance(app_suffix, manager_module.PytorchPlayground)
    assert args_module.ensure_defaults(manager.args).model_dump(mode="json") == manager.args.model_dump(mode="json")


def test_pytorch_playground_reduce_contract_merges_training_summaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(PROJECT_SRC.resolve()))
    reduction = importlib.import_module("pytorch_playground.reduction")

    partials = [
        reduction.partial_from_summary(
            {
                "samples": 64,
                "features": 2,
                "backend": "torch",
                "hidden_layers": [4, 2],
                "train_accuracy": 0.75,
                "validation_accuracy": 0.70,
                "validation_loss": 0.35,
                "loss_landscape_points": 25,
            },
            partial_id="worker-0",
        ),
        reduction.partial_from_summary(
            {
                "samples": 128,
                "features": 3,
                "backend": "missing",
                "hidden_layers": [8],
                "train_accuracy": 0.85,
                "validation_accuracy": 0.80,
                "validation_loss": 0.25,
                "loss_landscape_points": 0,
            },
            partial_id="worker-1",
        ),
    ]

    artifact = reduction.build_reduce_artifact(partials)

    assert artifact.name == reduction.REDUCE_ARTIFACT_NAME
    assert artifact.reducer == reduction.REDUCER_NAME
    assert artifact.partial_count == 2
    assert artifact.partial_ids == ("worker-0", "worker-1")
    assert artifact.payload["run_count"] == 2
    assert artifact.payload["sample_count"] == 192
    assert artifact.payload["feature_count"] == 3
    assert artifact.payload["validation_run_count"] == 2
    assert artifact.payload["train_accuracy"] == pytest.approx(0.80)
    assert artifact.payload["validation_accuracy"] == pytest.approx(0.75)
    assert artifact.payload["validation_loss"] == pytest.approx(0.30)
    assert artifact.payload["loss_landscape_points"] == 25
    assert artifact.payload["backends"] == ["missing", "torch"]
    assert artifact.payload["hidden_layer_shapes"] == ["2", "4", "8"]


def test_pytorch_playground_analysis_artifact_dir_uses_env_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.syspath_prepend(str(PROJECT_SRC.resolve()))
    manager_module = importlib.import_module("pytorch_playground.pytorch_playground")

    manager = manager_module.PytorchPlayground.__new__(manager_module.PytorchPlayground)
    manager.env = SimpleNamespace(AGILAB_EXPORT_ABS=tmp_path, app="custom_playground")

    assert manager.analysis_artifact_dir == tmp_path / "custom_playground" / "pytorch_playground"


def test_pytorch_playground_app_settings_default_to_single_worker() -> None:
    import tomllib

    settings = tomllib.loads((PROJECT_PATH / "src" / "app_settings.toml").read_text(encoding="utf-8"))

    assert settings["cluster"]["workers"] == {"127.0.0.1": 1}
    assert settings["pages"]["restrict_to_view_module"] is True
    assert settings["pages"]["view_module"] == []
    assert settings["app_surface"]["entrypoint"] == "pytorch_playground/app_surface.py"
    assert settings["app_surface"]["title"] == "PyTorch Playground"


def test_pytorch_playground_hides_distribution_preview_by_contract() -> None:
    import tomllib

    source_pyproject = tomllib.loads((PROJECT_PATH / "pyproject.toml").read_text(encoding="utf-8"))
    payload_pyproject = tomllib.loads((PACKAGE_PROJECT_PATH / "pyproject.toml").read_text(encoding="utf-8"))

    assert source_pyproject["tool"]["agilab"]["app"]["distribution_preview"] is False
    assert source_pyproject["tool"]["agilab"]["app"]["service_mode"] is False
    assert payload_pyproject["tool"]["agilab"]["app"]["distribution_preview"] is False
    assert payload_pyproject["tool"]["agilab"]["app"]["service_mode"] is False


def test_pytorch_playground_app_args_form_uses_project_scoped_static_json() -> None:
    source = (PROJECT_PATH / "src" / "app_args_form.py").read_text(encoding="utf-8")

    assert "render_form(" not in source
    assert "APP_FORM_ID" in source
    assert "FORM_FIELDS" in source
    assert "class FormField" in source
    assert "def _field_key" in source
    assert "key=key" in source
    assert "st.json(" not in source
    assert "container.multiselect(label, FEATURES, key=key)" in source
    assert "def _render_wide_args_form" in source
    assert "def _render_compact_args_form" in source
    assert "def _render_dataset_fields" not in source
    assert "def _render_model_fields" not in source
    assert "def _render_evidence_fields" not in source
    assert "def persist_current_args" in source
    assert "Quick fields are enough" not in source
    assert ".columns(" in source
    assert "Loss landscape" in source
    for label in ("Samples", "Epochs", "Learning rate", "Regularization", "Loss landscape", "Evidence path"):
        assert source.count(f'"{label}"') == 1
    assert "def _build_synced_run_snippet" in source
    assert "Synced RUN snippet" in source


def test_pytorch_playground_app_args_form_fields_are_single_source(monkeypatch: pytest.MonkeyPatch) -> None:
    form_module = _load_app_args_form_module()
    monkeypatch.setattr(form_module.st, "session_state", {})

    model_fields = set(form_module.app_args.PytorchPlaygroundArgs.model_fields)
    form_fields = {field.name for field in form_module.FORM_FIELDS}
    assert form_fields == model_fields
    assert len(form_module.FORM_FIELDS) == len(form_fields)
    assert {field.compact_group for field in form_module.FORM_FIELDS} == {"primary", "Advanced model", "Evidence"}
    assert [field.name for field in form_module._fields_for_compact_group("primary")] == [
        "dataset",
        "sample_count",
        "noise",
        "epochs",
    ]


def test_pytorch_playground_compact_app_args_form_uses_shared_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    form_module = _load_app_args_form_module()
    monkeypatch.setattr(form_module.st, "session_state", {})
    events: list[tuple[str, str, bool | None]] = []

    class FakeExpander:
        def __init__(self, label: str):
            self.label = label

        def __enter__(self):
            events.append(("expander_enter", self.label, None))
            return self

        def __exit__(self, *_args):
            events.append(("expander_exit", self.label, None))
            return False

        def text_input(self, label, *, key):
            events.append(("text_input", label, None))
            return form_module.st.session_state[key]

        def checkbox(self, label, *, key):
            events.append(("checkbox", label, None))
            return form_module.st.session_state[key]

        def number_input(self, label, *, key, disabled=False, **_kwargs):
            events.append(("number_input", label, disabled))
            return form_module.st.session_state[key]

        def slider(self, label, *, key, disabled=False, **_kwargs):
            events.append(("slider", label, disabled))
            return form_module.st.session_state[key]

        def selectbox(self, label, options, *, key):
            events.append(("selectbox", label, None))
            return form_module.st.session_state[key]

        def multiselect(self, label, _options, *, key):
            events.append(("multiselect", label, None))
            return form_module.st.session_state[key]

        def columns(self, _spec):
            raise AssertionError("compact form should stack fields instead of using columns")

    class FakeContainer(FakeExpander):
        def __init__(self):
            super().__init__("root")

        def expander(self, label, *, expanded=False):
            events.append(("expander", label, expanded))
            return FakeExpander(label)

    model = form_module.app_args.PytorchPlaygroundArgs()
    values = form_module._render_compact_args_form(
        model,
        env=SimpleNamespace(app="pytorch_playground_project"),
        container=FakeContainer(),
    )

    assert set(values) == {field.name for field in form_module.FORM_FIELDS}
    assert ("expander", "Advanced model", False) in events
    assert ("expander", "Evidence", False) in events
    assert ("slider", "Resolution", True) in events
    assert ("slider", "Span", True) in events


def test_pytorch_playground_app_args_form_renders_wide_sidebar_and_snippets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    form_module = _load_app_args_form_module()
    session_state: dict[str, object] = {}
    monkeypatch.setattr(form_module.st, "session_state", session_state)
    model = form_module.app_args.PytorchPlaygroundArgs()
    persisted: list[object] = []

    class FakeContainer:
        def __init__(self, label: str = "root"):
            self.label = label
            self.events: list[tuple[str, object]] = []

        def __enter__(self):
            self.events.append(("enter", self.label))
            return self

        def __exit__(self, *_args):
            self.events.append(("exit", self.label))
            return False

        def markdown(self, body, **_kwargs):
            self.events.append(("markdown", body))

        def caption(self, body, **_kwargs):
            self.events.append(("caption", body))

        def code(self, body, **kwargs):
            self.events.append(("code", (body, kwargs.get("language"))))

        def error(self, body, **_kwargs):
            self.events.append(("error", body))

        def expander(self, label, *, expanded=False):
            self.events.append(("expander", (label, expanded)))
            child = FakeContainer(str(label))
            child.events = self.events
            return child

        def columns(self, spec):
            count = spec if isinstance(spec, int) else len(spec)
            columns = [FakeContainer(f"column-{index}") for index in range(count)]
            for column in columns:
                column.events = self.events
            return columns

        def text_input(self, _label, *, key):
            return session_state[key]

        def checkbox(self, _label, *, key):
            return session_state[key]

        def number_input(self, _label, *, key, **_kwargs):
            return session_state[key]

        def slider(self, _label, *, key, **_kwargs):
            return session_state[key]

        def selectbox(self, _label, options, *, key):
            return session_state[key]

        def multiselect(self, _label, _options, *, key):
            return session_state[key]

    def fake_load_args_state(_env, *, args_module):
        assert args_module is form_module.app_args
        return model, {"dataset": model.dataset}, tmp_path / "app_settings.toml"

    monkeypatch.setattr(form_module, "load_args_state", fake_load_args_state)
    monkeypatch.setattr(
        form_module,
        "persist_args",
        lambda _args_module, parsed, **_kwargs: persisted.append(parsed),
    )
    monkeypatch.setattr(
        form_module,
        "_build_synced_run_snippet",
        lambda parsed, *, env: f"snippet for {parsed.dataset} in {env.app}",
    )

    env = SimpleNamespace(
        app="pytorch_playground_project",
        target="pytorch_playground_project",
        active_app=tmp_path / "apps" / "pytorch_playground_project",
        apps_path=tmp_path / "apps",
        AGILAB_EXPORT_ABS=tmp_path / "export",
    )
    wide_container = FakeContainer()
    form_module.render(env=env, container=wide_container, wide=True, compact=False)

    assert any(event == ("markdown", "### Settings") for event in wide_container.events)
    assert any(event[0] == "code" and "snippet for" in event[1][0] for event in wide_container.events)
    assert persisted[-1].dataset == model.dataset

    compact_container = FakeContainer()
    form_module.render(env=env, container=compact_container, compact=True)

    assert any(event == ("markdown", "**Settings**") for event in compact_container.events)
    assert any(event[0] == "expander" and event[1][0] == "Current run payload" for event in compact_container.events)


def test_pytorch_playground_app_args_form_fallback_snippet_edges(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    form_module = _load_app_args_form_module()
    monkeypatch.setattr(
        form_module.st,
        "session_state",
        {
            "app_settings": {
                "cluster": {
                    "cluster_enabled": True,
                    "pool": True,
                    "cython": True,
                    "rapids": True,
                    "verbose": "3",
                    "scheduler": "tcp://scheduler:8786",
                    "workers": {"worker-a": 2},
                    "workers_data_path": tmp_path / "share",
                }
            },
            "mode": 15,
        },
    )

    env = SimpleNamespace(
        app="",
        active_app=tmp_path / "apps" / "pytorch_playground_project",
        apps_path=tmp_path / "apps",
    )
    snippet = form_module._fallback_run_snippet(
        env=env,
        run_args={
            "params": {"dataset": "moons"},
            "args": {"unexpected": "mapping"},
            "data_in": "",
            "data_out": "evidence",
            "reset_target": True,
        },
    )

    assert "APP = \"pytorch_playground_project\"" in snippet
    assert "mode=15" in snippet
    assert "scheduler=\"tcp://scheduler:8786\"" in snippet
    assert "RUN_STAGES_PAYLOAD = json.loads('[]')" in snippet


def test_pytorch_playground_app_args_form_remaining_edge_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import builtins

    form_module = _load_app_args_form_module()

    class StopRender(RuntimeError):
        pass

    class FakeContainer:
        def __init__(self, label: str = "container"):
            self.label = label
            self.events: list[tuple[str, object]] = []

        def __enter__(self):
            self.events.append(("enter", self.label))
            return self

        def __exit__(self, *_args):
            self.events.append(("exit", self.label))
            return False

        def markdown(self, body):
            self.events.append(("markdown", body))

        def caption(self, body):
            self.events.append(("caption", body))

        def error(self, body):
            self.events.append(("error", body))

        def code(self, body, **kwargs):
            self.events.append(("code", (body, kwargs.get("language"))))

        def expander(self, label, *, expanded=False):
            self.events.append(("expander", (label, expanded)))
            return self

        def columns(self, spec):
            self.events.append(("columns", tuple(spec) if isinstance(spec, list) else spec))
            return [self for _ in range(len(spec) if isinstance(spec, list) else int(spec))]

        def text_input(self, _label, *, key):
            return form_module.st.session_state[key]

        def checkbox(self, _label, *, key):
            return form_module.st.session_state[key]

        def number_input(self, _label, *, key, **_kwargs):
            return form_module.st.session_state[key]

        def slider(self, _label, *, key, **_kwargs):
            return form_module.st.session_state[key]

        def selectbox(self, _label, options=None, *, key):
            return form_module.st.session_state[key]

        def multiselect(self, _label, _options, *, key):
            return form_module.st.session_state[key]

    class FakeStreamlit:
        def __init__(self):
            self.session_state: dict[str, object] = {}
            self.errors: list[str] = []
            self.sidebar = FakeContainer("sidebar")

        def error(self, message):
            self.errors.append(str(message))

        def stop(self):
            raise StopRender()

    fake_st = FakeStreamlit()
    monkeypatch.setattr(form_module, "st", fake_st)
    with pytest.raises(StopRender):
        form_module._get_env()
    assert fake_st.errors == [
        "AGILAB environment is not initialised yet. Return to the main page and try again."
    ]

    env = SimpleNamespace(
        app="",
        active_app=tmp_path / "apps" / "pytorch_playground_project",
        apps_path=tmp_path / "apps",
        target="target",
        AGILAB_EXPORT_ABS=tmp_path / "export",
        humanize_validation_errors=lambda exc: [f"humanized: {type(exc).__name__}"],
    )
    fake_st.session_state["env"] = env
    assert form_module._get_env() is env
    assert form_module._active_app_name(env) == "pytorch_playground_project"
    assert form_module._snippet_apps_path(env) == str(tmp_path / "apps")
    assert form_module._cluster_settings() == {}
    fake_st.session_state["app_settings"] = {"cluster": "bad"}
    assert form_module._cluster_settings() == {}
    fake_st.session_state["app_settings"] = {
        "cluster": {
            "cluster_enabled": True,
            "scheduler": "host",
            "workers": {"w": 1},
            "workers_data_path": "/share",
            "pool": True,
            "cython": True,
            "rapids": True,
            "verbose": "bad",
        }
    }
    assert form_module._coerce_verbose("bad") == 1
    fake_st.session_state["mode"] = 7
    assert form_module._run_mode(form_module._cluster_settings(), cluster_enabled=True) == 7
    fake_st.session_state.pop("mode")
    assert form_module._run_mode(form_module._cluster_settings(), cluster_enabled=True) == 15
    assert form_module._optional_string_expr(False, "x") == "None"
    assert form_module._optional_python_expr(True, {}) == "None"
    payload, stages, data_in, data_out, reset_target = form_module._split_run_request_payload(
        {"args": "not-list", "data_in": "in", "data_out": "out", "reset_target": True}
    )
    assert payload == {}
    assert stages == []
    assert (data_in, data_out, reset_target) == ("in", "out", True)

    model = form_module.app_args.PytorchPlaygroundArgs(compute_loss_landscape=False)
    values: dict[str, object] = {}
    resolution_field = next(field for field in form_module.FORM_FIELDS if field.name == "landscape_resolution")
    assert form_module._field_disabled(resolution_field, values, model, env=env) is True
    assert (
        form_module._feature_names(FakeContainer(), env, "feature_names", "Features", "")
        == ",".join(form_module.DEFAULT_FEATURES)
    )
    sidebar_values = form_module._render_args_form(model, env=env, container=FakeContainer(), wide=False)
    assert set(sidebar_values) == {field.name for field in form_module.FORM_FIELDS}

    fake_st.session_state = {
        "env": env,
        "app_settings": fake_st.session_state["app_settings"],
    }
    persisted: list[object] = []
    monkeypatch.setattr(
        form_module,
        "load_args_state",
        lambda _env, *, args_module: (model, {"seed": "payload"}, tmp_path / "settings.toml"),
    )
    monkeypatch.setattr(form_module, "persist_args", lambda *args, **kwargs: persisted.append((args, kwargs)))
    parsed = form_module.persist_current_args(env=env)
    assert isinstance(parsed, form_module.app_args.PytorchPlaygroundArgs)
    assert persisted

    original_import = builtins.__import__

    def fail_orchestrate_import(name, *args, **kwargs):
        if name == "agilab.orchestrate_page_support":
            raise ImportError("blocked")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fail_orchestrate_import)
    snippet = form_module._build_synced_run_snippet(parsed, env=env)
    assert "asyncio.run(main())" in snippet
    assert "RunRequest" in snippet

    monkeypatch.setattr(
        form_module.app_args,
        "to_playground_config",
        lambda _parsed: (_ for _ in ()).throw(ValueError("bad config")),
    )
    output_container = FakeContainer("output")
    form_module.render(env=env, container=output_container, compact=False)
    assert ("error", "bad config") in output_container.events


def test_pytorch_playground_source_and_packaged_payload_stay_aligned() -> None:
    source_root = PROJECT_PATH / "src"
    payload_root = PACKAGE_PROJECT_PATH / "src"
    source_files = _runtime_payload_files(source_root)
    payload_files = _runtime_payload_files(payload_root)

    assert source_files == payload_files

    mismatches = [
        str(relative)
        for relative in sorted(source_files - EXPECTED_SOURCE_PAYLOAD_DIFFS)
        if (source_root / relative).read_bytes() != (payload_root / relative).read_bytes()
    ]
    assert mismatches == []

    source_worker_manifest = (source_root / "pytorch_playground_worker" / "pyproject.toml").read_text(encoding="utf-8")
    payload_worker_manifest = (payload_root / "pytorch_playground_worker" / "pyproject.toml").read_text(encoding="utf-8")
    assert "[tool.uv.sources]" in source_worker_manifest
    assert "[tool.uv.sources]" not in payload_worker_manifest


def test_pytorch_playground_worker_exports_evidence_without_torch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.syspath_prepend(str(PROJECT_SRC.resolve()))
    core_module = importlib.import_module("pytorch_playground.core")
    worker_module = importlib.import_module("pytorch_playground_worker.pytorch_playground_worker")
    args_module = importlib.import_module("pytorch_playground.app_args")
    monkeypatch.setattr(core_module, "torch", None)
    monkeypatch.setattr(core_module, "nn", None)

    worker = worker_module.PytorchPlaygroundWorker.__new__(worker_module.PytorchPlaygroundWorker)
    worker.args = args_module.PytorchPlaygroundArgs(
        data_out=tmp_path / "out",
        sample_count=64,
        epochs=10,
        grid_size=12,
        reset_target=True,
    ).model_dump(mode="json")
    worker.env = SimpleNamespace(target="pytorch_playground_project", AGILAB_EXPORT_ABS=tmp_path / "export")
    worker._worker_id = 0

    worker.start()
    summary = worker.work_pool("pytorch_playground")

    assert summary.iloc[0]["backend"] == "missing"
    manifest = json.loads((tmp_path / "out" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["app"] == "pytorch_playground_project"
    assert (tmp_path / "out" / "pytorch_playground_evidence.zip").is_file()
    assert (tmp_path / "export" / "pytorch_playground_project" / "pytorch_playground" / "manifest.json").is_file()


def test_pytorch_playground_worker_helper_and_dispatch_edges(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.syspath_prepend(str(PROJECT_SRC.resolve()))
    worker_module = importlib.import_module("pytorch_playground_worker.pytorch_playground_worker")
    args_module = importlib.import_module("pytorch_playground.app_args")

    assert worker_module._artifact_dir(
        SimpleNamespace(AGILAB_EXPORT_ABS=tmp_path / "export", target="target"),
        "leaf",
    ) == tmp_path / "export" / "target" / "leaf"
    assert worker_module._artifact_dir(
        SimpleNamespace(resolve_share_path=lambda value: tmp_path / "share" / value),
        "leaf",
    ) == tmp_path / "share" / "leaf"
    monkeypatch.setattr(worker_module.Path, "home", staticmethod(lambda: tmp_path))
    assert worker_module._artifact_dir(SimpleNamespace(), "leaf") == tmp_path / "export" / "leaf"

    args = args_module.PytorchPlaygroundArgs(sample_count=96)
    assert worker_module._args_with_defaults(args) is args
    assert worker_module._args_with_defaults(args.model_dump(mode="json")).sample_count == 96
    assert worker_module._args_with_defaults(SimpleNamespace(sample_count=128, _private="skip")).sample_count == 128

    class ArgsObject:
        def __init__(self):
            self.sample_count = 160
            self._private = "skip"

    assert worker_module._args_with_defaults(ArgsObject()).sample_count == 160

    existing_out = tmp_path / "resolved" / "evidence"
    existing_out.mkdir(parents=True)
    (existing_out / "stale.txt").write_text("old", encoding="utf-8")
    worker = worker_module.PytorchPlaygroundWorker.__new__(worker_module.PytorchPlaygroundWorker)
    worker.args = {"data_out": "evidence", "reset_target": True, "sample_count": 96}
    worker.env = SimpleNamespace(resolve_share_path=lambda value: tmp_path / "resolved" / value, target="")
    worker._worker_id = 0
    worker.start()
    assert worker.data_out == existing_out
    assert not (existing_out / "stale.txt").exists()

    events: list[tuple[str, object]] = []
    dispatch_worker = worker_module.PytorchPlaygroundWorker.__new__(worker_module.PytorchPlaygroundWorker)
    dispatch_worker._worker_id = 0
    dispatch_worker.work_init = lambda: events.append(("init", None))
    dispatch_worker.work_pool = lambda item: events.append(("pool", item)) or pd.DataFrame([{"item": item}])
    dispatch_worker.work_done = lambda df: events.append(("done", df.iloc[0]["item"]))
    dispatch_worker.stop = lambda: events.append(("stop", None))
    worker_module.BaseWorker._t0 = None

    elapsed = dispatch_worker.works([["a", ("b", "c")]], [])

    assert elapsed >= 0
    assert events == [
        ("init", None),
        ("pool", "a"),
        ("done", "a"),
        ("pool", "b"),
        ("done", "b"),
        ("pool", "c"),
        ("done", "c"),
        ("stop", None),
    ]
    bare_worker = worker_module.PytorchPlaygroundWorker.__new__(worker_module.PytorchPlaygroundWorker)
    assert worker_module.PytorchPlaygroundWorker.work_done(bare_worker) is None


def test_pytorch_playground_worker_exports_real_torch_evidence_when_available(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.syspath_prepend(str(PROJECT_SRC.resolve()))
    core_module = importlib.import_module("pytorch_playground.core")
    if core_module.torch is None:
        pytest.skip("torch is not installed in this validation environment")

    worker_module = importlib.import_module("pytorch_playground_worker.pytorch_playground_worker")
    args_module = importlib.import_module("pytorch_playground.app_args")

    worker = worker_module.PytorchPlaygroundWorker.__new__(worker_module.PytorchPlaygroundWorker)
    worker.args = args_module.PytorchPlaygroundArgs(
        data_out=tmp_path / "out",
        dataset="gaussian",
        sample_count=64,
        hidden_layers="4",
        feature_names="x1,x2",
        epochs=10,
        batch_size=16,
        grid_size=12,
        compute_loss_landscape=True,
        landscape_resolution=5,
        landscape_span=0.2,
        reset_target=True,
    ).model_dump(mode="json")
    worker.env = SimpleNamespace(target="pytorch_playground_project", AGILAB_EXPORT_ABS=tmp_path / "export")
    worker._worker_id = 0

    worker.start()
    summary = worker.work_pool("pytorch_playground")

    assert summary.iloc[0]["backend"] == "torch"
    assert summary.iloc[0]["loss_landscape_points"] == 25
    manifest = json.loads((tmp_path / "out" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["backend"] == "torch"
    assert manifest["row_counts"]["training_history"] >= 2
    assert manifest["row_counts"]["decision_grid"] == 144
    assert manifest["row_counts"]["loss_landscape"] == 25
    assert manifest["torch_version"]
    archive_path = tmp_path / "out" / "pytorch_playground_evidence.zip"
    with zipfile.ZipFile(archive_path, "r") as archive:
        assert "manifest.json" in archive.namelist()
        assert json.loads(archive.read("manifest.json").decode("utf-8"))["backend"] == "torch"


def test_pytorch_playground_main_covers_empty_and_error_ui_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()

    class StopRender(RuntimeError):
        pass

    class FakeContext:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def metric(self, *_args, **_kwargs):
            return None

    class FakeStreamlit:
        def __init__(self, *, hidden_raw: str = "8,8", checkbox: bool = False):
            self.query_params = {}
            self.session_state: dict[str, object] = {}
            self.sidebar = FakeContext()
            self.hidden_raw = hidden_raw
            self.checkbox_value = checkbox
            self.errors: list[str] = []
            self.infos: list[str] = []
            self.warnings: list[str] = []
            self.downloads: list[bytes] = []
            self.code_payloads: list[tuple[str, str | None]] = []

        def set_page_config(self, **_kwargs):
            return None

        def title(self, *_args, **_kwargs):
            return None

        def caption(self, *_args, **_kwargs):
            return None

        def markdown(self, *_args, **_kwargs):
            return None

        def error(self, message, **_kwargs):
            self.errors.append(str(message))

        def warning(self, message, **_kwargs):
            self.warnings.append(str(message))

        def stop(self):
            raise StopRender()

        def columns(self, spec):
            count = spec if isinstance(spec, int) else len(spec)
            return [FakeContext() for _ in range(count)]

        def tabs(self, labels):
            return [FakeContext() for _ in labels]

        def selectbox(self, _label, options, index=0, **_kwargs):
            return list(options)[index]

        def slider(self, _label, _min, _max, value, **_kwargs):
            return value

        def multiselect(self, _label, _options, default=None, **_kwargs):
            return list(default or [])

        def text_input(self, _label, value="", **_kwargs):
            return self.hidden_raw

        def number_input(self, _label, value=0, **_kwargs):
            return value

        def checkbox(self, *_args, **_kwargs):
            return self.checkbox_value

        def button(self, *_args, **_kwargs):
            return False

        def plotly_chart(self, *_args, **_kwargs):
            return None

        def dataframe(self, *_args, **_kwargs):
            return None

        def info(self, message, **_kwargs):
            self.infos.append(str(message))

        def metric(self, *_args, **_kwargs):
            return None

        def download_button(self, _label, data, **_kwargs):
            self.downloads.append(data)
            return False

        def code(self, body, **kwargs):
            self.code_payloads.append((str(body), kwargs.get("language")))
            return None

        def json(self, payload, **_kwargs):
            raise AssertionError(f"st.json should not be used by PyTorch Playground: {payload!r}")

    def empty_result(status: str = "ok") -> dict[str, object]:
        return {
            "status": status,
            "detail": "missing torch detail",
            "samples": pd.DataFrame({"x1": [-0.2, 0.2], "x2": [0.1, -0.1], "target": [0, 1]}),
            "history": pd.DataFrame(
                columns=["epoch", "train_loss", "validation_loss", "train_accuracy", "validation_accuracy"]
            ),
            "grid": pd.DataFrame(columns=["x1", "x2", "probability"]),
            "network_layers": module._empty_network_layers(),
            "activation_maps": module._empty_activation_maps(),
            "summary": {"backend": status, "samples": 2, "features": 2},
        }

    invalid_st = FakeStreamlit(hidden_raw="8,wide")
    monkeypatch.setattr(module, "st", invalid_st)
    monkeypatch.setattr(module, "render_logo", lambda: None)
    monkeypatch.setattr(module, "_resolve_active_app", lambda: None)
    monkeypatch.setattr(module, "_cached_train", lambda _payload: empty_result())
    with pytest.raises(StopRender):
        module.main()
    assert invalid_st.errors == ["Hidden layer width must be an integer: wide"]

    ok_st = FakeStreamlit(checkbox=False)
    monkeypatch.setattr(module, "st", ok_st)
    monkeypatch.setattr(module, "_cached_train", lambda _payload: empty_result())
    module.main()
    assert any("Hidden activation maps" in message for message in ok_st.infos)
    assert any("Enable computation" in message for message in ok_st.infos)
    manifest = next(json.loads(body) for body, language in ok_st.code_payloads if language == "json")
    assert manifest["row_counts"]["loss_landscape"] == 0

    missing_st = FakeStreamlit(checkbox=True)
    monkeypatch.setattr(module, "st", missing_st)
    monkeypatch.setattr(module, "_cached_train", lambda _payload: empty_result("missing_torch"))
    module.main()
    assert missing_st.errors == ["missing torch detail"]
    assert any("Loss landscape is available" in message for message in missing_st.infos)


def test_pytorch_playground_main_renders_with_fake_streamlit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_module()

    class FakeContext:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def metric(self, *_args, **_kwargs):
            return None

        def plotly_chart(self, *_args, **_kwargs):
            return None

        def dataframe(self, *_args, **_kwargs):
            return None

        def selectbox(self, _label, options, index=0, **_kwargs):
            return list(options)[index]

    class FakeStreamlit:
        def __init__(self):
            self.query_params = {}
            self.session_state: dict[str, object] = {}
            self.sidebar = FakeContext()
            self.downloads: list[bytes] = []
            self.code_payloads: list[tuple[str, str | None]] = []

        def set_page_config(self, **_kwargs):
            return None

        def title(self, *_args, **_kwargs):
            return None

        def caption(self, *_args, **_kwargs):
            return None

        def markdown(self, *_args, **_kwargs):
            return None

        def error(self, *_args, **_kwargs):
            return None

        def warning(self, *_args, **_kwargs):
            return None

        def stop(self):
            raise AssertionError("stop should not be called")

        def columns(self, spec):
            count = spec if isinstance(spec, int) else len(spec)
            return [FakeContext() for _ in range(count)]

        def tabs(self, labels):
            return [FakeContext() for _ in labels]

        def selectbox(self, _label, options, index=0, **_kwargs):
            return list(options)[index]

        def slider(self, _label, _min, _max, value, **_kwargs):
            return value

        def multiselect(self, _label, _options, default=None, **_kwargs):
            return list(default or [])

        def text_input(self, _label, value="", **_kwargs):
            return value

        def number_input(self, _label, value=0, **_kwargs):
            return value

        def checkbox(self, *_args, **_kwargs):
            return True

        def button(self, *_args, **_kwargs):
            return False

        def plotly_chart(self, *_args, **_kwargs):
            return None

        def dataframe(self, *_args, **_kwargs):
            return None

        def info(self, *_args, **_kwargs):
            return None

        def metric(self, *_args, **_kwargs):
            return None

        def download_button(self, _label, data, **_kwargs):
            self.downloads.append(data)
            return False

        def code(self, body, **kwargs):
            self.code_payloads.append((str(body), kwargs.get("language")))
            return None

        def json(self, payload, **_kwargs):
            raise AssertionError(f"st.json should not be used by PyTorch Playground: {payload!r}")

    fake_st = FakeStreamlit()
    config = module.PlaygroundConfig(sample_count=64, grid_size=12, hidden_layers=(2,))
    samples = module._make_dataset(config)
    grid = pd.DataFrame(
        {
            "x1": [-1.0, 1.0, -1.0, 1.0],
            "x2": [-1.0, -1.0, 1.0, 1.0],
            "probability": [0.1, 0.9, 0.2, 0.8],
        }
    )
    history = pd.DataFrame(
        {
            "epoch": [0],
            "train_loss": [0.5],
            "validation_loss": [0.6],
            "train_accuracy": [0.7],
            "validation_accuracy": [0.8],
        }
    )
    layers = pd.DataFrame(
        [
            {
                "layer": 1,
                "kind": "hidden",
                "input_features": 2,
                "output_features": 2,
                "parameters": 6,
                "weight_mean": 0.0,
                "weight_std": 0.1,
                "weight_max_abs": 0.3,
                "bias_mean": 0.0,
                "bias_std": 0.1,
                "bias_max_abs": 0.2,
            }
        ]
    )
    activation_maps = pd.DataFrame(
        {
            "layer": [1, 1, 1, 1],
            "neuron": [1, 1, 1, 1],
            "x1": [-1.0, 1.0, -1.0, 1.0],
            "x2": [-1.0, -1.0, 1.0, 1.0],
            "activation": [0.0, 1.0, 0.4, 0.8],
        }
    )
    loss_landscape = pd.DataFrame(
        {
            "alpha": [-0.25, 0.0, 0.25],
            "beta": [-0.25, 0.0, 0.25],
            "train_loss": [0.6, 0.5, 0.7],
            "validation_loss": [0.65, 0.45, 0.75],
            "train_accuracy": [0.6, 0.7, 0.5],
            "validation_accuracy": [0.55, 0.8, 0.45],
            "is_center": [False, True, False],
        }
    )
    result = {
        "status": "ok",
        "detail": "",
        "samples": samples,
        "history": history,
        "grid": grid,
        "network_layers": layers,
        "activation_maps": activation_maps,
        "summary": {"backend": "synthetic", "samples": len(samples), "features": 2},
    }

    monkeypatch.setattr(module, "st", fake_st)
    monkeypatch.setattr(module, "render_logo", lambda: None)
    monkeypatch.setattr(module, "_resolve_active_app", lambda: tmp_path)
    monkeypatch.setattr(module, "_cached_train", lambda _payload: result)
    monkeypatch.setattr(
        module,
        "_cached_loss_landscape",
        lambda _payload, _resolution, _span: {
            "status": "ok",
            "detail": "",
            "loss_landscape": loss_landscape,
            "landscape_summary": module._loss_landscape_summary(loss_landscape),
        },
    )

    module.main()

    assert fake_st.downloads
    manifest = next(json.loads(body) for body, language in fake_st.code_payloads if language == "json")
    assert manifest["schema"] == module.EVIDENCE_SCHEMA


def test_pytorch_playground_main_live_mode_and_missing_evidence_branch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_module()

    class FakeContext:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def metric(self, *_args, **_kwargs):
            return None

        def plotly_chart(self, *_args, **_kwargs):
            return None

        def dataframe(self, *_args, **_kwargs):
            return None

        def selectbox(self, _label, options, index=0, **_kwargs):
            return list(options)[index]

        def button(self, label, **_kwargs):
            return label == "Play"

        def caption(self, *_args, **_kwargs):
            return None

        def progress(self, *_args, **_kwargs):
            return None

    class FakeStreamlit:
        def __init__(self):
            self.query_params = {}
            self.session_state: dict[str, object] = {}
            self.sidebar = FakeContext()
            self.infos: list[str] = []
            self.errors: list[str] = []
            self.warnings: list[str] = []
            self.downloads: list[bytes] = []
            self.code_payloads: list[tuple[str, str | None]] = []
            self.rerun_count = 0

        def set_page_config(self, **_kwargs):
            return None

        def title(self, *_args, **_kwargs):
            return None

        def caption(self, message="", **_kwargs):
            return None

        def markdown(self, *_args, **_kwargs):
            return None

        def error(self, message, **_kwargs):
            self.errors.append(str(message))

        def warning(self, message, **_kwargs):
            self.warnings.append(str(message))

        def columns(self, spec):
            count = spec if isinstance(spec, int) else len(spec)
            return [FakeContext() for _ in range(count)]

        def tabs(self, labels):
            return [FakeContext() for _label in labels]

        def selectbox(self, label, options, index=0, **_kwargs):
            if label == "Training mode":
                return module.LIVE_TRAINING_MODE_LABEL
            return list(options)[index]

        def slider(self, _label, _min, _max, value, **_kwargs):
            return value

        def multiselect(self, _label, _options, default=None, **_kwargs):
            return list(default or [])

        def text_input(self, _label, value="", **_kwargs):
            return value

        def number_input(self, _label, value=0, **_kwargs):
            return value

        def checkbox(self, *_args, **_kwargs):
            return False

        def button(self, label, **_kwargs):
            return label == "Play"

        def plotly_chart(self, *_args, **_kwargs):
            return None

        def dataframe(self, *_args, **_kwargs):
            return None

        def info(self, message, **_kwargs):
            self.infos.append(str(message))

        def metric(self, *_args, **_kwargs):
            return None

        def progress(self, *_args, **_kwargs):
            return None

        def download_button(self, _label, data, **_kwargs):
            self.downloads.append(data)
            return False

        def code(self, body, **kwargs):
            self.code_payloads.append((str(body), kwargs.get("language")))

        def rerun(self):
            self.rerun_count += 1

        def json(self, payload, **_kwargs):
            raise AssertionError(f"st.json should not be used by PyTorch Playground: {payload!r}")

    config = module.PlaygroundConfig(sample_count=64, grid_size=12, hidden_layers=(4,), epochs=8)
    samples = module._make_dataset(config)
    result = {
        "status": "ok",
        "detail": "",
        "samples": samples,
        "history": pd.DataFrame(
            {
                "epoch": [1],
                "train_loss": [0.5],
                "validation_loss": [0.6],
                "train_accuracy": [0.7],
                "validation_accuracy": [0.65],
            }
        ),
        "grid": pd.DataFrame({"x1": [0.0], "x2": [0.0], "probability": [0.5]}),
        "network_layers": module._empty_network_layers(),
        "activation_maps": module._empty_activation_maps(),
        "summary": {"backend": "live", "samples": len(samples), "features": 2},
    }
    fake_st = FakeStreamlit()
    monkeypatch.setattr(module, "st", fake_st)
    monkeypatch.setattr(module, "render_logo", lambda: None)
    monkeypatch.setattr(module, "_resolve_active_app", lambda: tmp_path)
    monkeypatch.setattr(module.time, "sleep", lambda _delay: None)
    monkeypatch.setattr(
        module,
        "_run_live_training_controls",
        lambda *_args, **_kwargs: (
            {"epoch": 1, "playing": True, "signature": module._config_signature(config)},
            result,
            True,
        ),
    )

    module.main()

    assert fake_st.rerun_count == 1
    assert fake_st.downloads

    analysis_st = FakeStreamlit()
    monkeypatch.setattr(module, "st", analysis_st)
    module.main(
        interactive_controls=False,
        evidence_dirs=[tmp_path / "missing"],
        configure_page=False,
    )
    assert analysis_st.infos == [
        "No exported PyTorch evidence found yet. Run the app once from ORCHESTRATE, then return to ANALYSIS."
    ]


def test_pytorch_playground_app_provider_and_package_docs(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("agi_app_pytorch_playground_init_test_module", INIT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    source_root = INIT_PATH.resolve().parents[4] / "apps" / "builtin" / "pytorch_playground_project"
    assert module.project_root() == source_root.resolve()

    fake_package_root = (
        tmp_path
        / ".venv"
        / "lib"
        / "python3.13"
        / "site-packages"
        / "agi_app_pytorch_playground"
    )
    fake_payload = fake_package_root / "project" / "pytorch_playground_project"
    fake_payload.mkdir(parents=True, exist_ok=True)
    original_file = module.__file__
    try:
        module.__file__ = str(fake_package_root / "__init__.py")
        assert module.project_root() == fake_payload
    finally:
        module.__file__ = original_file

    assert module.metadata()["project"] == "pytorch_playground_project"
    readme = README_PATH.read_text(encoding="utf-8")
    assert "pytorch_playground_project" in readme
    assert "agi-app-pytorch-playground" in readme
    assert "generic app-agnostic analysis page" in readme
