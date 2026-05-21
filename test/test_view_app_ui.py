from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


MODULE_PATH = Path("src/agilab/apps-pages/view_app_ui/src/view_app_ui/view_app_ui.py")


def _load_module():
    spec = importlib.util.spec_from_file_location("view_app_ui_test_module", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_view_app_ui_resolves_project_scoped_entrypoint(tmp_path: Path) -> None:
    module = _load_module()
    app = tmp_path / "demo_project"
    ui = app / "src" / "demo" / "ui.py"
    outside = tmp_path / "outside.py"
    ui.parent.mkdir(parents=True)
    ui.write_text("def main(): pass\n", encoding="utf-8")
    outside.write_text("def main(): pass\n", encoding="utf-8")

    assert module._resolve_active_app(["--active-app", str(app)]) == app.resolve()
    assert module._resolve_entrypoint(app, "demo/ui.py") == ui.resolve()
    assert module._resolve_entrypoint(app, "../outside.py") is None
    assert module._resolve_entrypoint(app, str(outside)) is None
    assert module._resolve_entrypoint(app, "") is None
    with pytest.raises(FileNotFoundError, match="Provided --active-app path not found"):
        module._resolve_active_app(["--active-app", str(tmp_path / "missing_project")])


def test_view_app_ui_reads_missing_or_invalid_settings_as_empty(tmp_path: Path) -> None:
    module = _load_module()
    app = tmp_path / "demo_project"
    settings = app / "src" / "app_settings.toml"

    assert module._read_toml(settings) == {}
    assert module._configured_app_ui(app) == {}

    settings.parent.mkdir(parents=True)
    settings.write_text("[pages\n", encoding="utf-8")

    assert module._read_toml(settings) == {}
    assert module._configured_app_ui(app) == {}

    settings.write_text("[pages]\nview_app_ui = 'bad'\n", encoding="utf-8")
    assert module._configured_app_ui(app) == {}


def test_view_app_ui_loads_declared_entrypoint_from_settings(tmp_path: Path) -> None:
    module = _load_module()
    app = tmp_path / "demo_project"
    settings = app / "src" / "app_settings.toml"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        "\n".join(
            [
                "[pages]",
                'view_module = ["view_app_ui"]',
                "",
                "[pages.view_app_ui]",
                'title = "Demo UI"',
                'entrypoint = "demo/ui.py"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    assert module._configured_app_ui(app) == {"title": "Demo UI", "entrypoint": "demo/ui.py"}


def test_view_app_ui_runs_app_main_with_active_app_argument(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_module()
    app = tmp_path / "demo_project"
    ui = app / "src" / "demo" / "ui.py"
    marker = tmp_path / "argv.txt"
    ui.parent.mkdir(parents=True)
    ui.write_text(
        "\n".join(
            [
                "from pathlib import Path",
                "import sys",
                "def main():",
                f"    Path({str(marker)!r}).write_text('|'.join(sys.argv), encoding='utf-8')",
                "",
            ]
        ),
        encoding="utf-8",
    )

    previous_argv = list(sys.argv)
    module._run_app_ui(ui, app)

    assert sys.argv == previous_argv
    assert marker.read_text(encoding="utf-8") == f"{ui}|--active-app|{app}"


def test_view_app_ui_runs_app_main_with_script_local_imports(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    app = tmp_path / "demo_project"
    ui = app / "src" / "demo" / "ui.py"
    marker = tmp_path / "local_import.txt"
    ui.parent.mkdir(parents=True)
    (ui.parent / "core.py").write_text("VALUE = 'script-local-core'\n", encoding="utf-8")
    ui.write_text(
        "\n".join(
            [
                "from pathlib import Path",
                "import core",
                "def main():",
                f"    Path({str(marker)!r}).write_text(core.VALUE, encoding='utf-8')",
                "",
            ]
        ),
        encoding="utf-8",
    )

    module._run_app_ui(ui, app)

    assert marker.read_text(encoding="utf-8") == "script-local-core"
    assert sys.path[:2] == [str((app / "src").resolve()), str(ui.parent.resolve())]


def test_view_app_ui_reorders_path_and_rejects_entrypoint_without_main(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    app = tmp_path / "demo_project"
    ui = app / "src" / "demo" / "ui.py"
    ui.parent.mkdir(parents=True)
    ui.write_text("VALUE = 1\n", encoding="utf-8")
    monkeypatch.setattr(sys, "path", [str(app / "src"), "existing"])
    previous_argv = list(sys.argv)

    with pytest.raises(AttributeError, match="does not expose main"):
        module._run_app_ui(ui, app)

    assert sys.argv == previous_argv
    assert sys.path[:3] == [str(app / "src"), str(ui.parent), "existing"]


def test_view_app_ui_load_module_reports_missing_spec_and_cleans_failed_import(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    bad_ui = tmp_path / "bad_ui.py"
    bad_ui.write_text("raise RuntimeError('boom')\n", encoding="utf-8")

    monkeypatch.setattr(module.importlib.util, "spec_from_file_location", lambda *_args, **_kwargs: None)
    with pytest.raises(ModuleNotFoundError, match="Unable to load app UI"):
        module._load_module(bad_ui)

    monkeypatch.undo()
    before = {name for name in sys.modules if name.startswith("_agilab_view_app_ui_")}
    with pytest.raises(RuntimeError, match="boom"):
        module._load_module(bad_ui)
    after = {name for name in sys.modules if name.startswith("_agilab_view_app_ui_")}

    assert after == before


def test_view_app_ui_main_reports_missing_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_module()
    app = tmp_path / "demo_project"
    (app / "src").mkdir(parents=True)
    monkeypatch.setattr(sys, "argv", ["view_app_ui.py", "--active-app", str(app)])

    fake_st = SimpleNamespace(
        messages=[],
        set_page_config=lambda **kwargs: fake_st.messages.append(("config", kwargs)),
        info=lambda message: fake_st.messages.append(("info", message)),
        caption=lambda message: fake_st.messages.append(("caption", message)),
        error=lambda message: fake_st.messages.append(("error", message)),
    )
    monkeypatch.setattr(module, "st", fake_st)

    module.main()

    assert ("info", "This project does not declare an app UI entrypoint for ANALYSIS.") in fake_st.messages


def test_view_app_ui_main_runs_configured_entrypoint_and_reports_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    app = tmp_path / "demo_project"
    ui = app / "src" / "demo" / "ui.py"
    settings = app / "src" / "app_settings.toml"
    ui.parent.mkdir(parents=True)
    ui.write_text("def main(): pass\n", encoding="utf-8")
    settings.write_text(
        "\n".join(
            [
                "[pages.view_app_ui]",
                'entrypoint = "demo/ui.py"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "argv", ["view_app_ui.py", "--active-app", str(app)])
    calls: list[tuple[Path, Path]] = []
    fake_st = SimpleNamespace(
        messages=[],
        set_page_config=lambda **kwargs: fake_st.messages.append(("config", kwargs)),
        info=lambda message: fake_st.messages.append(("info", message)),
        caption=lambda message: fake_st.messages.append(("caption", message)),
        error=lambda message: fake_st.messages.append(("error", message)),
    )
    monkeypatch.setattr(module, "st", fake_st)
    monkeypatch.setattr(module, "_run_app_ui", lambda entrypoint, active_app: calls.append((entrypoint, active_app)))

    module.main()

    assert calls == [(ui.resolve(), app.resolve())]
    assert fake_st.messages == []

    def failing_run_app_ui(_entrypoint, _active_app):
        raise RuntimeError("render boom")

    monkeypatch.setattr(module, "_run_app_ui", failing_run_app_ui)
    module.main()

    assert ("error", "Failed to render app UI: render boom") in fake_st.messages


def test_view_app_ui_safe_page_config_suppresses_streamlit_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    fake_st = SimpleNamespace(set_page_config=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("late config")))
    monkeypatch.setattr(module, "st", fake_st)

    module._safe_page_config()
