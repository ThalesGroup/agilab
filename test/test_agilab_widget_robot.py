from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


MODULE_PATH = Path("tools/agilab_widget_robot.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("agilab_widget_robot_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_public_builtin_apps_are_sorted_project_directories() -> None:
    module = _load_module()

    apps = module.public_builtin_apps()

    assert apps == sorted(apps)
    assert any(path.name == "flight_project" for path in apps)
    assert all(path.name.endswith("_project") for path in apps)


def test_resolve_apps_accepts_all_names_and_paths(tmp_path) -> None:
    module = _load_module()
    custom = tmp_path / "custom_project"
    custom.mkdir()

    all_apps = module.resolve_apps("all")
    selected = module.resolve_apps(f"flight_project,{custom}")

    assert len(all_apps) >= 2
    assert any(Path(app).name == "flight_project" for app in selected)
    assert custom.resolve() in selected


def test_resolve_pages_accepts_all_or_csv() -> None:
    module = _load_module()

    assert module.resolve_pages("all") == list(module.DEFAULT_PAGES)
    assert module.resolve_pages("PROJECT, ANALYSIS") == ["PROJECT", "ANALYSIS"]
    assert module.resolve_pages("HOME,PROJECT") == ["", "PROJECT"]
    assert module.page_label("") == "HOME"
    assert "ORCHESTRATE" in module.PAGE_EXPECTED_TEXT
    assert module.DEFAULT_INTERACTION_MODE == "full"
    assert module.DEFAULT_ACTION_BUTTON_POLICY == "trial"
    assert module.DEFAULT_WIDGET_TIMEOUT_SECONDS < module.DEFAULT_TIMEOUT_SECONDS


def test_active_app_aliases_accept_project_suffix_alias() -> None:
    module = _load_module()

    assert module.active_app_aliases("/tmp/flight_project") == {"flight_project", "flight"}


def test_wait_for_page_ready_returns_after_initialization_clears() -> None:
    module = _load_module()
    texts = iter(["Initializing environment...", "Ready"])
    waits: list[int] = []

    class _Body:
        def inner_text(self, timeout):
            return next(texts)

    class _Spinner:
        def count(self):
            return 0

    class _Page:
        def locator(self, selector):
            return _Body() if selector == "body" else _Spinner()

        def wait_for_timeout(self, ms):
            waits.append(ms)

    module.wait_for_page_ready(_Page(), timeout_ms=1000)

    assert waits


def test_summarize_counts_widgets_and_failures() -> None:
    module = _load_module()
    failure = module.WidgetProbe(
        app="flight_project",
        page="PROJECT",
        kind="button",
        label="Run",
        status="failed",
        detail="blocked",
        url="http://demo",
    )
    pages = [
        module.PageSweep(
            app="flight_project",
            page="PROJECT",
            success=False,
            duration_seconds=1.0,
            widget_count=3,
            interacted_count=1,
            probed_count=2,
            skipped_count=0,
            failed_count=1,
            url="http://demo",
            failures=[failure],
            skips=[],
        )
    ]

    summary = module.summarize(pages, app_count=1, target_seconds=10.0)

    assert summary.success is False
    assert summary.widget_count == 3
    assert summary.interacted_count == 1
    assert summary.probed_count == 2
    assert summary.failed_count == 1
    assert summary.within_target is False


def test_full_mode_uses_trial_for_action_buttons_by_default(tmp_path) -> None:
    module = _load_module()
    clicks: list[dict] = []

    class _Locator:
        @property
        def first(self):
            return self

        def count(self):
            return 1

        def scroll_into_view_if_needed(self, timeout):
            pass

        def is_visible(self, timeout):
            return True

        def is_enabled(self, timeout):
            return True

        def bounding_box(self, timeout):
            return {"width": 10, "height": 10}

        def click(self, **kwargs):
            clicks.append(kwargs)

    class _Page:
        def locator(self, selector):
            return _Locator()

    status, detail = module._probe_widget(
        _Page(),
        {"id": "w1", "kind": "button", "label": "EXECUTE"},
        timeout_ms=100,
        interaction_mode="full",
        action_button_policy="trial",
        upload_file=tmp_path / "fixture.txt",
    )

    assert status == "probed"
    assert "callback not fired" in detail
    assert clicks == [{"timeout": 100, "trial": True}]


def test_full_mode_fills_and_restores_text_inputs(tmp_path) -> None:
    module = _load_module()
    fills: list[str] = []

    class _Locator:
        @property
        def first(self):
            return self

        def count(self):
            return 1

        def scroll_into_view_if_needed(self, timeout):
            pass

        def is_visible(self, timeout):
            return True

        def is_enabled(self, timeout):
            return True

        def bounding_box(self, timeout):
            return {"width": 10, "height": 10}

        def input_value(self, timeout):
            return "original"

        def fill(self, value, timeout):
            fills.append(value)

    class _Page:
        def locator(self, selector):
            return _Locator()

    status, detail = module._probe_widget(
        _Page(),
        {"id": "w1", "kind": "text_input", "label": "Name"},
        timeout_ms=100,
        interaction_mode="full",
        action_button_policy="trial",
        upload_file=tmp_path / "fixture.txt",
    )

    assert status == "interacted"
    assert "restored" in detail
    assert fills == ["original robot", "original"]
