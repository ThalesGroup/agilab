from __future__ import annotations

import builtins
import importlib.util
import json
import os
import sys
import threading
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

MODULE_PATH = Path("src/agilab/app_surface.py")
IMPLEMENTATION_MODULE_PATH = Path("src/agilab/app_management/app_surface.py")


def _manager_site_packages(app: Path) -> Path:
    venv = app / ".venv"
    (venv / "pyvenv.cfg").parent.mkdir(parents=True, exist_ok=True)
    (venv / "pyvenv.cfg").write_text("version_info = 99.99.0\n", encoding="utf-8")
    if os.name == "nt":
        site_packages = venv / "Lib" / "site-packages"
    else:
        site_packages = venv / "lib" / "python99.99" / "site-packages"
    site_packages.mkdir(parents=True, exist_ok=True)
    return site_packages


def _write_editable_owner(
    site_packages: Path,
    *,
    distribution: str,
    project: Path,
) -> None:
    metadata = site_packages / f"{distribution}-1.0.dist-info"
    metadata.mkdir(parents=True)
    (metadata / "direct_url.json").write_text(
        json.dumps(
            {
                "url": project.resolve().as_uri(),
                "dir_info": {"editable": True},
            }
        ),
        encoding="utf-8",
    )


def _load_app_surface_module():
    spec = importlib.util.spec_from_file_location("agilab_app_surface_tests", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_base_app_surface_import_does_not_require_optional_agi_env(
    monkeypatch,
) -> None:
    real_import = builtins.__import__

    def _without_agi_env(name, *args, **kwargs):
        if name == "agi_env" or name.startswith("agi_env."):
            raise ModuleNotFoundError("No module named 'agi_env'", name="agi_env")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _without_agi_env)
    spec = importlib.util.spec_from_file_location(
        "agilab_app_surface_base_import_test",
        IMPLEMENTATION_MODULE_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    with pytest.raises(ModuleNotFoundError, match=r"agilab\[ui\]"):
        module._isolated_import_process_state()


def test_app_editable_import_roots_reports_stale_agi_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from agi_env.runtime import import_layout_support

    module = _load_app_surface_module()
    monkeypatch.delattr(
        import_layout_support,
        "hosted_editable_source_import_roots",
    )

    with pytest.raises(RuntimeError, match="AGILAB UI runtime is stale"):
        module.app_editable_import_roots(tmp_path / "demo_project")


def test_app_editable_import_roots_reports_missing_import_layout_module(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_app_surface_module()
    real_import = builtins.__import__

    def _without_import_layout(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "agi_env.runtime" and "import_layout_support" in fromlist:
            raise ImportError("cannot import name 'import_layout_support'")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _without_import_layout)

    with pytest.raises(RuntimeError, match="cannot inspect manager editables"):
        module.app_editable_import_roots(tmp_path / "demo_project")


def _write_app_surface_project(tmp_path: Path) -> Path:
    app = tmp_path / "demo_project"
    surface = app / "src" / "demo" / "app_surface.py"
    surface.parent.mkdir(parents=True)
    (app / "src" / "app_settings.toml").write_text(
        "\n".join(
            [
                "[app_surface]",
                'title = "Demo Surface"',
                'entrypoint = "demo/app_surface.py"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    surface.write_text(
        "\n".join(
            [
                "def render(*, mode, active_app, env=None, container=None, streamlit=None):",
                "    container.append({",
                "        'mode': mode,",
                "        'active_app': active_app.name,",
                "        'env_app': getattr(env, 'app', None),",
                "    })",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return app


def _write_multi_surface_project(tmp_path: Path) -> Path:
    app = tmp_path / "multi_project"
    surface = app / "src" / "demo" / "app_surface.py"
    surface.parent.mkdir(parents=True)
    (app / "src" / "app_settings.toml").write_text(
        "\n".join(
            [
                "[app_surface]",
                'title = "Demo Surface"',
                'entrypoint = "demo/app_surface.py"',
                'default = "streamlit"',
                "",
                "[app_surface.backends.streamlit]",
                'title = "Demo Streamlit"',
                'backend = "streamlit"',
                'entrypoint = "demo/app_surface.py"',
                "default = true",
                'capabilities = ["local", "play-pause"]',
                "",
                "[app_surface.backends.hf]",
                'title = "Demo HF"',
                'backend = "hf"',
                'url = "https://demo.hf.space/?active_app=multi_project"',
                'capabilities = ["hosted-demo"]',
                "",
            ]
        ),
        encoding="utf-8",
    )
    surface.write_text("def render(**_kwargs): pass\n", encoding="utf-8")
    return app


def test_app_surface_resolves_project_local_entrypoint(tmp_path: Path) -> None:
    module = _load_app_surface_module()
    app = _write_app_surface_project(tmp_path)

    assert module.app_surface_config(app) == {
        "title": "Demo Surface",
        "entrypoint": "demo/app_surface.py",
    }
    assert module.configured_app_surface_entrypoint(app) == app / "src" / "demo" / "app_surface.py"


def test_app_surface_specs_support_multiple_backends(tmp_path: Path) -> None:
    module = _load_app_surface_module()
    app = _write_multi_surface_project(tmp_path)

    specs = module.app_surface_specs(app)

    assert sorted(specs) == ["hf", "streamlit"]
    assert specs["streamlit"].as_dict() == {
        "name": "streamlit",
        "backend": "streamlit",
        "title": "Demo Streamlit",
        "default": True,
        "entrypoint": "demo/app_surface.py",
        "capabilities": ["local", "play-pause"],
    }
    assert specs["hf"].as_dict() == {
        "name": "hf",
        "backend": "hf",
        "title": "Demo HF",
        "default": False,
        "url": "https://demo.hf.space/?active_app=multi_project",
        "capabilities": ["hosted-demo"],
    }
    assert module.select_app_surface_spec(app).name == "streamlit"
    assert module.select_app_surface_spec(app, name="hf").url == (
        "https://demo.hf.space/?active_app=multi_project"
    )
    assert module.select_app_surface_spec(app, name="streamlit").entrypoint == (
        "demo/app_surface.py"
    )
    assert module.select_app_surface_spec(app, name="HF").name == "hf"


def test_render_app_surface_only_embeds_streamlit_backend(tmp_path: Path) -> None:
    module = _load_app_surface_module()
    app = _write_multi_surface_project(tmp_path)

    assert module.render_app_surface(app, mode="analysis", surface="hf") is False
    assert module.configured_app_surface_entrypoint(app, surface="hf") is None


def test_render_app_surface_calls_project_render_hook_and_restores_argv(tmp_path: Path) -> None:
    module = _load_app_surface_module()
    app = _write_app_surface_project(tmp_path)
    events: list[dict[str, object]] = []
    before_argv = list(sys.argv)

    rendered = module.render_app_surface(
        app,
        mode="configure",
        env=SimpleNamespace(app="demo_project"),
        container=events,
    )

    assert rendered is True
    assert events == [
        {
            "mode": "configure",
            "active_app": "demo_project",
            "env_app": "demo_project",
        }
    ]
    assert sys.argv == before_argv


def test_app_editable_import_roots_admits_source_without_foreign_site_packages(
    tmp_path: Path,
) -> None:
    module = _load_app_surface_module()
    app = tmp_path / "manager_project"
    app_source = app / "src"
    app_source.mkdir(parents=True)
    site_packages = _manager_site_packages(app)

    plain_project = tmp_path / "plain-project"
    plain_root = plain_project / "src"
    (plain_root / "plain_dep").mkdir(parents=True)
    (plain_root / "plain_dep" / "__init__.py").write_text("", encoding="utf-8")
    _write_editable_owner(
        site_packages,
        distribution="plain_dep",
        project=plain_project,
    )
    (site_packages / "plain-editable.pth").write_text(
        f"{plain_root}\n",
        encoding="utf-8",
    )
    foreign_project = tmp_path / "other-agilab-checkout"
    foreign_framework_root = foreign_project / "src"
    (foreign_framework_root / "agi_web").mkdir(parents=True)
    _write_editable_owner(
        site_packages,
        distribution="foreign_framework",
        project=foreign_project,
    )
    (site_packages / "foreign-framework.pth").write_text(
        f"{foreign_framework_root}\n",
        encoding="utf-8",
    )

    mapped_project = tmp_path / "mapped-project"
    mapped_root = mapped_project / "src"
    mapped_package = mapped_root / "mapped_dep"
    mapped_package.mkdir(parents=True)
    (mapped_package / "__init__.py").write_text("", encoding="utf-8")
    _write_editable_owner(
        site_packages,
        distribution="mapped_dep",
        project=mapped_project,
    )
    finder_name = "__editable___manager_deps_finder"
    (site_packages / f"{finder_name}.py").write_text(
        "from __future__ import annotations\n"
        f"MAPPING = {{'mapped_dep': {str(mapped_package)!r}}}\n"
        "NAMESPACES = {}\n"
        "def install():\n    pass\n",
        encoding="utf-8",
    )
    (site_packages / "mapped-editable.pth").write_text(
        f"import {finder_name}; {finder_name}.install()\n",
        encoding="utf-8",
    )

    unowned_root = tmp_path / "unowned-source"
    unowned_root.mkdir()
    (site_packages / "unowned.pth").write_text(
        f"{unowned_root}\n",
        encoding="utf-8",
    )

    native_project = tmp_path / "native-project"
    native_root = native_project / "src"
    native_root.mkdir(parents=True)
    (native_root / "native_dep.so").write_bytes(b"foreign ABI")
    _write_editable_owner(
        site_packages,
        distribution="native_dep",
        project=native_project,
    )
    (site_packages / "native.pth").write_text(
        f"{native_root}\n",
        encoding="utf-8",
    )

    assert module.app_editable_import_roots(app) == (
        app_source.resolve(strict=False),
        plain_root.resolve(strict=False),
        mapped_root.resolve(strict=False),
    )
    assert site_packages not in module.app_editable_import_roots(app)
    assert foreign_framework_root not in module.app_editable_import_roots(app)
    assert unowned_root not in module.app_editable_import_roots(app)
    assert native_root not in module.app_editable_import_roots(app)


def test_render_app_surface_imports_manager_editable_dependency(
    tmp_path: Path,
) -> None:
    module = _load_app_surface_module()
    app = _write_app_surface_project(tmp_path)
    dependency_project = tmp_path / "dependency-project"
    dependency_root = dependency_project / "src"
    dependency = dependency_root / "surface_dependency"
    dependency.mkdir(parents=True)
    (dependency / "__init__.py").write_text(
        "MARKER = 'surface dependency loaded'\n",
        encoding="utf-8",
    )
    site_packages = _manager_site_packages(app)
    _write_editable_owner(
        site_packages,
        distribution="surface_dependency",
        project=dependency_project,
    )
    (site_packages / "surface-dependency.pth").write_text(
        f"{dependency_root}\n",
        encoding="utf-8",
    )
    entrypoint = app / "src" / "demo" / "app_surface.py"
    entrypoint.write_text(
        "import surface_dependency\n"
        "def render(*, container, **_kwargs):\n"
        "    container.append(surface_dependency.MARKER)\n",
        encoding="utf-8",
    )
    events: list[str] = []

    assert (
        module.render_app_surface(
            app,
            mode="configure",
            container=events,
        )
        is True
    )
    assert events == ["surface dependency loaded"]
    assert "surface_dependency" not in sys.modules


def test_render_app_surface_serializes_and_restores_project_import_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_app_surface_module()
    coordination = ModuleType("agilab_app_surface_test_coordination")
    coordination.lock = threading.Lock()
    coordination.alpha_started = threading.Event()
    coordination.release_alpha = threading.Event()
    coordination.records = []
    coordination.active = 0
    coordination.max_active = 0

    def _enter(value: str, argv: list[str]) -> None:
        with coordination.lock:
            coordination.active += 1
            coordination.max_active = max(
                coordination.max_active,
                coordination.active,
            )
            coordination.records.append((value, list(argv)))
        if value == "alpha":
            coordination.alpha_started.set()
            assert coordination.release_alpha.wait(timeout=5)

    def _exit() -> None:
        with coordination.lock:
            coordination.active -= 1

    coordination.enter = _enter
    coordination.exit = _exit
    monkeypatch.setitem(sys.modules, coordination.__name__, coordination)

    apps: list[tuple[Path, Path]] = []
    for app_name in ("alpha", "beta"):
        active_app = tmp_path / f"{app_name}_project"
        source_root = active_app / "src"
        source_root.mkdir(parents=True)
        (source_root / "helper.py").write_text(
            f'VALUE = "{app_name}"\n',
            encoding="utf-8",
        )
        entrypoint = source_root / "app_surface.py"
        entrypoint.write_text(
            "import sys\n"
            "import helper\n"
            "import agilab_app_surface_test_coordination as coordination\n\n"
            "def render(**_kwargs):\n"
            "    coordination.enter(helper.VALUE, sys.argv)\n"
            "    coordination.exit()\n",
            encoding="utf-8",
        )
        apps.append((entrypoint, active_app))

    original_argv = list(sys.argv)
    original_path = list(sys.path)
    original_helper = sys.modules.get("helper")
    errors: list[BaseException] = []

    def _render(entrypoint: Path, active_app: Path) -> None:
        try:
            assert module.render_app_surface(
                active_app,
                mode="analysis",
                config={"app_surface": {"entrypoint": entrypoint.name}},
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    first = threading.Thread(target=_render, args=apps[0])
    second = threading.Thread(target=_render, args=apps[1])
    first.start()
    assert coordination.alpha_started.wait(timeout=5)
    second.start()
    time.sleep(0.05)
    assert coordination.max_active == 1
    coordination.release_alpha.set()
    first.join(timeout=5)
    second.join(timeout=5)

    assert all(not worker.is_alive() for worker in (first, second))
    assert errors == []
    assert [record[0] for record in coordination.records] == ["alpha", "beta"]
    for (entrypoint, active_app), (_value, argv) in zip(
        apps,
        coordination.records,
    ):
        assert argv == [str(entrypoint), "--active-app", str(active_app)]
    assert coordination.max_active == 1
    assert sys.argv == original_argv
    assert sys.path == original_path
    assert sys.modules.get("helper") is original_helper
    assert not any(
        name.startswith("_agilab_app_surface_") for name in sys.modules
    )


def test_app_surface_config_and_selection_edge_cases(tmp_path: Path) -> None:
    module = _load_app_surface_module()
    bad_app = tmp_path / "bad_project"
    (bad_app / "src").mkdir(parents=True)
    (bad_app / "src" / "app_settings.toml").write_text("[app_surface\n", encoding="utf-8")

    assert module._read_app_settings(bad_app) == {}
    assert module.app_surface_config(None) == {}
    assert module.app_surface_title(None) == "App Surface"
    assert module.app_surface_title({"title": "   "}) == "App Surface"
    assert module._string_tuple(" one ") == ("one",)
    assert module._string_tuple(object()) == ()
    assert module._surface_spec_from_mapping(
        "empty",
        {},
        root={},
        root_default_name="streamlit",
    ) is None

    config = {
        "app_surface": {
            "title": "Backend only",
            "default": "",
            "backends": {
                "": {"entrypoint": "skip.py"},
                "bad": "not-a-mapping",
                "hf": {"backend": "hf", "url": "https://example.invalid"},
            },
        }
    }
    specs = module.app_surface_specs(None, config=config)
    assert specs["hf"].default is True
    assert module.select_app_surface_spec(None, name="missing", config=config) is None
    assert module.select_app_surface_spec(None, backend="missing", config=config) is None
    assert module.select_app_surface_spec(None, backend="hf", config=config).name == "hf"


def test_app_surface_entrypoint_resolution_edges(tmp_path: Path) -> None:
    module = _load_app_surface_module()
    app = _write_app_surface_project(tmp_path)
    outside = tmp_path / "outside.py"
    outside.write_text("def render(**_kwargs): pass\n", encoding="utf-8")

    assert module.resolve_app_surface_entrypoint(None, "demo/app_surface.py") is None
    assert module.resolve_app_surface_entrypoint(app, object()) is None
    assert module.resolve_app_surface_entrypoint(app, outside) is None
    assert module.configured_app_surface_entrypoint(app, surface="missing") is None

    no_render = app / "src" / "demo" / "no_render.py"
    no_render.write_text("VALUE = 1\n", encoding="utf-8")
    assert module.render_app_surface(
        app,
        mode="analysis",
        config={"app_surface": {"entrypoint": "demo/no_render.py"}},
    ) is False

    missing = module.render_app_surface(
        app,
        mode="analysis",
        config={"app_surface": {"entrypoint": "demo/missing.py"}},
    )
    assert missing is False


def test_render_app_surface_forwards_optional_streamlit_argument(tmp_path: Path) -> None:
    module = _load_app_surface_module()
    app = tmp_path / "streamlit_project"
    surface = app / "src" / "demo" / "app_surface.py"
    surface.parent.mkdir(parents=True)
    (app / "src" / "app_settings.toml").write_text(
        "\n".join(
            [
                "[app_surface]",
                'title = "Demo Surface"',
                'entrypoint = "demo/app_surface.py"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    surface.write_text(
        "def render(**kwargs):\n"
        "    kwargs['container'].append(sorted(kwargs))\n",
        encoding="utf-8",
    )
    events: list[list[str]] = []

    assert module.render_app_surface(
        app,
        mode="analysis",
        container=events,
        streamlit=SimpleNamespace(name="fake-st"),
    ) is True
    assert events == [["active_app", "container", "mode", "streamlit"]]
