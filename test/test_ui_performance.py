from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
MODULE_PATH = SRC_ROOT / "agilab" / "ui_performance.py"
spec = importlib.util.spec_from_file_location("agilab_ui_performance_test_module", MODULE_PATH)
assert spec is not None and spec.loader is not None
ui_performance = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = ui_performance
spec.loader.exec_module(ui_performance)


def test_ui_performance_env_flags_are_explicit() -> None:
    assert ui_performance.flag_enabled("1") is True
    assert ui_performance.flag_enabled("debug") is True
    assert ui_performance.flag_enabled("off") is False
    assert ui_performance.flag_enabled(None) is False

    assert ui_performance.ui_discovery_cache_enabled({}) is True
    assert ui_performance.ui_discovery_cache_enabled({"AGILAB_DISABLE_UI_DISCOVERY_CACHE": "yes"}) is False
    assert ui_performance.ui_timing_trace_enabled({}) is False
    assert ui_performance.ui_timing_trace_enabled({"AGILAB_UI_TIMING_TRACE": "on"}) is True


def test_child_path_signatures_cover_expected_registry_inputs(tmp_path: Path) -> None:
    template = tmp_path / "demo_app_template"
    hidden = tmp_path / ".hidden_app_template"
    ignored = tmp_path / "demo_project"
    template.mkdir()
    hidden.mkdir()
    ignored.mkdir()
    (template / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (template / "src").mkdir()
    (template / "src" / "app_settings.toml").write_text("[cluster]\n", encoding="utf-8")

    signatures = ui_performance.child_path_signatures(
        tmp_path,
        child_suffix="_app_template",
        extra_relative_paths=("pyproject.toml", "src", "src/app_settings.toml", "missing.toml"),
    )

    labels = [signature[0] for signature in signatures]
    assert labels == [
        ".",
        "demo_app_template",
        "demo_app_template/pyproject.toml",
        "demo_app_template/src",
        "demo_app_template/src/app_settings.toml",
    ]
    assert ui_performance.path_stat_signature(tmp_path / "missing") is None


def test_child_path_signatures_tolerates_unreadable_root() -> None:
    class BrokenRoot:
        def iterdir(self):
            raise OSError("unreadable")

    assert ui_performance.child_path_signatures(
        BrokenRoot(),  # type: ignore[arg-type]
        child_suffix="_app_template",
        include_root=False,
    ) == ()


def test_child_path_signatures_ignores_unavailable_signatures(tmp_path: Path, monkeypatch) -> None:
    template = tmp_path / "demo_app_template"
    template.mkdir()
    (template / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")

    def fake_signature(path: Path, *, label: str | None = None):
        if label == "." or path == template:
            return None
        return (label or path.name, path.is_dir(), 1, 2)

    monkeypatch.setattr(ui_performance, "path_stat_signature", fake_signature)

    assert ui_performance.child_path_signatures(
        tmp_path,
        child_suffix="_app_template",
        extra_relative_paths=("pyproject.toml",),
    ) == (("demo_app_template/pyproject.toml", False, 1, 2),)


def test_record_ui_timing_span_clamps_and_limits_session_rows() -> None:
    session_state: dict[str, object] = {}

    first = ui_performance.record_ui_timing_span(
        session_state,
        label="ABOUT:bootstrap",
        category="bootstrap",
        started_at=10.0,
        perf_counter=lambda: 10.015,
        limit=2,
    )
    ui_performance.record_ui_timing_span(
        session_state,
        label="ABOUT:render",
        category="render",
        started_at=20.0,
        perf_counter=lambda: 19.0,
        limit=2,
    )
    ui_performance.record_ui_timing_span(
        session_state,
        label="ABOUT:total",
        started_at=30.0,
        perf_counter=lambda: 30.1,
        limit=2,
    )

    assert first.as_row() == {
        "label": "ABOUT:bootstrap",
        "category": "bootstrap",
        "elapsed_ms": "15.0",
    }
    assert session_state[ui_performance.UI_TIMING_SESSION_KEY] == [
        {"label": "ABOUT:render", "category": "render", "elapsed_ms": "0.0"},
        {"label": "ABOUT:total", "category": "page", "elapsed_ms": "100.0"},
    ]

    class BadSession:
        def get(self, *_args, **_kwargs):
            raise RuntimeError("session unavailable")

    span = ui_performance.record_ui_timing_span(
        BadSession(),
        label="bad",
        started_at=1.0,
        perf_counter=lambda: 1.001,
    )
    assert span.as_row()["elapsed_ms"] == "1.0"
