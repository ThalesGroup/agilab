from __future__ import annotations

import importlib.util
import json
import runpy
import sys
from pathlib import Path
import types


MODULE_PATH = Path("tools/first_launch_robot.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "first_launch_robot_test_module",
        MODULE_PATH,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_first_launch_robot_passes_static_first_surface(tmp_path: Path) -> None:
    module = _load_module()

    report = module.build_report(target_seconds=90.0, timeout=90.0)

    assert report["schema"] == "agilab.first_launch_robot.v1"
    assert report["status"] == "pass", json.dumps(report, indent=2, sort_keys=True)
    assert report["success"] is True
    assert report["within_target"] is True
    assert report["summary"]["check_count"] == 8
    checks = {check["id"]: check for check in report["checks"]}
    assert checks["first_launch_no_exceptions"]["status"] == "pass"
    assert checks["first_launch_env_initialized"]["status"] == "pass"
    assert checks["first_launch_first_proof_signal"]["status"] == "pass"
    docs_menu = checks["first_launch_docs_action"]["details"]["menu_items"]
    assert (
        docs_menu["Get help"] == "https://thalesgroup.github.io/agilab/agilab-help.html"
    )

    output = tmp_path / "first-launch-robot.json"
    assert (
        module.main(
            [
                "--target-seconds",
                "90",
                "--timeout",
                "90",
                "--output",
                str(output),
                "--json",
            ]
        )
        == 0
    )
    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted["status"] == "pass", json.dumps(
        persisted, indent=2, sort_keys=True
    )


def test_first_launch_robot_helpers_cover_empty_values_and_docs_import_failure(
    monkeypatch,
) -> None:
    module = _load_module()

    class Widget:
        def __init__(self, value):
            self.value = value

    assert module._widget_values([Widget("kept"), Widget(None)], "value") == ["kept"]
    assert module._contains_any(["one", "two"], ["missing"]) is False
    readme_path = module.DEFAULT_ACTIVE_APP / "README.md"
    readme_route = module._readme_route(readme_path.parent.name)
    has_readme_link, readme_details = module._readme_link_details(
        [f'<a href="{readme_route}" target="_self">README</a>'],
        [],
        module.DEFAULT_ACTIVE_APP,
        module.DEFAULT_APPS_PATH,
    )
    assert has_readme_link is True
    assert readme_details["expected_path"] == str(readme_path)
    assert readme_details["expected_route"] == readme_route
    has_readme_link, _ = module._readme_link_details(
        ["README without the file link"],
        [],
        module.DEFAULT_ACTIVE_APP,
        module.DEFAULT_APPS_PATH,
    )
    assert has_readme_link is False
    has_readme_link, _ = module._readme_link_details(
        [],
        ["README"],
        module.DEFAULT_ACTIVE_APP,
        module.DEFAULT_APPS_PATH,
    )
    assert has_readme_link is True
    src_root = str(module.REPO_ROOT / "src")
    monkeypatch.setattr(
        module.sys, "path", [path for path in module.sys.path if path != src_root]
    )
    monkeypatch.setattr(
        module.importlib.util, "spec_from_file_location", lambda *_args, **_kwargs: None
    )

    docs_menu = module._docs_menu_items()

    assert "cannot load page docs module" in docs_menu["_error"]
    assert module.sys.path[0] == src_root


def test_first_launch_robot_marks_env_missing_when_session_state_probe_fails(
    monkeypatch,
) -> None:
    module = _load_module()

    class BrokenSessionState:
        def __contains__(self, _key):
            raise RuntimeError("session unavailable")

    class FakeApp:
        exception: list[object] = []
        markdown: list[object] = []
        caption: list[object] = []
        button: list[object] = []
        session_state = BrokenSessionState()

        def run(self, *, timeout):
            return self

    class FakeAppTest:
        @staticmethod
        def from_file(_path, *, default_timeout):
            return FakeApp()

    streamlit = types.ModuleType("streamlit")
    testing = types.ModuleType("streamlit.testing")
    v1 = types.ModuleType("streamlit.testing.v1")
    v1.AppTest = FakeAppTest
    monkeypatch.setitem(sys.modules, "streamlit", streamlit)
    monkeypatch.setitem(sys.modules, "streamlit.testing", testing)
    monkeypatch.setitem(sys.modules, "streamlit.testing.v1", v1)
    monkeypatch.setattr(module, "_docs_menu_items", lambda: {})

    report = module.build_report(timeout=1.0, target_seconds=999.0)

    checks = {check["id"]: check for check in report["checks"]}
    assert checks["first_launch_no_exceptions"]["status"] == "pass"
    assert checks["first_launch_env_initialized"]["status"] == "fail"


def test_first_launch_robot_main_reports_human_failure(capsys, monkeypatch) -> None:
    module = _load_module()

    monkeypatch.setattr(
        module,
        "build_report",
        lambda **_kwargs: {
            "status": "fail",
            "checks": [
                {
                    "label": "First launch renders without exceptions",
                    "status": "fail",
                    "summary": "synthetic failure",
                }
            ],
        },
    )

    assert module.main(["--target-seconds", "1", "--timeout", "1"]) == 1
    output = capsys.readouterr().out
    assert "AGILAB first-launch robot: FAIL" in output
    assert "synthetic failure" in output


def test_first_launch_robot_rejects_non_positive_timeouts() -> None:
    module = _load_module()

    for option in ("--timeout", "--target-seconds"):
        try:
            module.main([option, "0"])
        except SystemExit as exc:
            assert exc.code == 2
        else:  # pragma: no cover - assertion guard
            raise AssertionError(f"expected parser error for {option}")


def test_first_launch_robot_entrypoint_runs_with_fake_apptest(
    monkeypatch, capsys
) -> None:
    readme_route = "/PROJECT?active_app=flight_telemetry_project&sidebar_selection=Edit&project_section=readme"
    readme_path = (
        MODULE_PATH.parents[1]
        / "src"
        / "agilab"
        / "apps"
        / "builtin"
        / "flight_telemetry_project"
        / "README.md"
    )
    assert readme_path.is_file()

    class Widget:
        def __init__(self, value: str = "", label: str = ""):
            self.value = value
            self.label = label

    class FakeApp:
        exception: list[object] = []
        markdown = [
            Widget(
                "AGILAB logo AI/ML reproducibility workbench "
                f'DEMO / ORCHESTRATE / ANALYSIS <a href="{readme_route}">README</a>'
            )
        ]
        caption: list[object] = []
        button = [Widget(label="First proof")]
        session_state = {"env": object()}

        def run(self, *, timeout):
            assert timeout == 1.0
            return self

    class FakeAppTest:
        @staticmethod
        def from_file(_path, *, default_timeout):
            assert default_timeout == 1.0
            return FakeApp()

    streamlit = types.ModuleType("streamlit")
    testing = types.ModuleType("streamlit.testing")
    v1 = types.ModuleType("streamlit.testing.v1")
    v1.AppTest = FakeAppTest
    monkeypatch.setitem(sys.modules, "streamlit", streamlit)
    monkeypatch.setitem(sys.modules, "streamlit.testing", testing)
    monkeypatch.setitem(sys.modules, "streamlit.testing.v1", v1)
    monkeypatch.setattr(
        sys,
        "argv",
        [str(MODULE_PATH), "--json", "--timeout", "1", "--target-seconds", "999"],
    )

    try:
        runpy.run_path(str(MODULE_PATH), run_name="__main__")
    except SystemExit as exc:
        assert exc.code == 0
    else:  # pragma: no cover - assertion guard
        raise AssertionError("expected entrypoint to raise SystemExit")

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "pass"
    assert payload["summary"]["check_count"] == 8
