from __future__ import annotations

import json
from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys


PAGE_PATH = (
    "src/agilab/apps-pages/view_data_io_decision/"
    "src/view_data_io_decision/view_data_io_decision.py"
)


def _load_helpers() -> ModuleType:
    source = Path(PAGE_PATH).read_text(encoding="utf-8")
    prefix = source.split("\nconfigure_streamlit_page(st,", 1)[0]
    module = ModuleType("view_data_io_decision_test_module")
    module.__file__ = str(Path(PAGE_PATH).resolve())
    module.__package__ = None
    exec(compile(prefix, str(Path(PAGE_PATH)), "exec"), module.__dict__)
    return module


def test_view_data_io_decision_resets_app_scoped_state_on_active_app_change(tmp_path) -> None:
    module = _load_helpers()
    first_app = tmp_path / "first_app"
    second_app = tmp_path / "second_app"
    first_app.mkdir()
    second_app.mkdir()
    module.st = SimpleNamespace(
        session_state={
            module.APP_SCOPE_KEY: str(first_app.resolve()),
            module.ARTIFACT_ROOT_KEY: "/tmp/old-artifacts",
            module.RUN_SELECTION_KEY: "old-run",
            module.SUMMARY_GLOB_KEY: "*old.json",
        }
    )

    assert module._reset_app_scoped_session_defaults(first_app) is False
    assert module.ARTIFACT_ROOT_KEY in module.st.session_state

    assert module._reset_app_scoped_session_defaults(second_app) is True
    assert module.st.session_state[module.APP_SCOPE_KEY] == str(second_app.resolve())
    for key in module.APP_SCOPED_SESSION_DEFAULT_KEYS:
        assert key not in module.st.session_state


def test_view_data_io_decision_helper_edge_cases(tmp_path) -> None:
    module = _load_helpers()

    assert module._format_delta(2.25) == "+2.2%"
    assert module._format_delta(-1, suffix=" ms") == "-1.0 ms"
    assert module._format_delta("bad") is None

    missing = tmp_path / "missing.csv"
    assert module._read_csv_if_present(missing).empty


def test_view_data_io_decision_full_page_renders_artifact_evidence(monkeypatch, tmp_path) -> None:
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    active_app = tmp_path / "mission_decision_project"
    active_app.mkdir()
    summary_path = artifact_root / "run_summary_metrics.json"
    summary_path.write_text(
        json.dumps(
            {
                "selected_strategy": "replan",
                "latency_ms_selected": 10.5,
                "latency_delta_pct_vs_no_replan": -12.0,
                "cost_selected": 3.2,
                "cost_delta_pct_vs_no_replan": -4.0,
                "reliability_selected": 0.987,
                "reliability_delta_pct_vs_no_replan": 2.5,
            }
        ),
        encoding="utf-8",
    )
    (artifact_root / "run_generated_pipeline.json").write_text(
        json.dumps({"stages": [{"name": "ingest"}, {"name": "decide"}]}),
        encoding="utf-8",
    )
    (artifact_root / "run_mission_decision.json").write_text(
        json.dumps({"applied_events": [{"event": "jammed_link"}]}),
        encoding="utf-8",
    )
    for suffix in (
        "candidate_routes",
        "decision_timeline",
        "sensor_stream",
        "feature_table",
    ):
        (artifact_root / f"run_{suffix}.csv").write_text("name,value\nx,1\n", encoding="utf-8")

    events: list[tuple[str, object]] = []

    class _Box:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def metric(self, label, value, *args, **kwargs):
            events.append(("metric", (label, value, args, kwargs)))

        def subheader(self, label):
            events.append(("subheader", label))

        def dataframe(self, frame, **kwargs):
            events.append(("dataframe", (len(frame), kwargs)))

        def info(self, message):
            events.append(("info", message))

        def markdown(self, message):
            events.append(("markdown", message))

        def json(self, payload):
            events.append(("json", payload))

    class _FakeStreamlit(_Box):
        def __init__(self):
            self.session_state: dict[str, object] = {}
            self.sidebar = self

        def set_page_config(self, **kwargs):
            events.append(("page_config", kwargs))

        def title(self, label):
            events.append(("title", label))

        def caption(self, message):
            events.append(("caption", message))

        def text_input(self, _label, *, key):
            return self.session_state[key]

        def selectbox(self, _label, *, options, key):
            self.session_state[key] = options[-1]
            return options[-1]

        def columns(self, spec):
            count = spec if isinstance(spec, int) else len(spec)
            return [_Box() for _ in range(count)]

        def expander(self, label, *, expanded=False):
            events.append(("expander", (label, expanded)))
            return _Box()

        def warning(self, message):
            raise AssertionError(message)

        def error(self, message):
            raise AssertionError(message)

        def stop(self):
            raise AssertionError("st.stop should not be reached")

    fake_st = _FakeStreamlit()
    fake_runtime = ModuleType("agi_pages.runtime")
    fake_runtime.artifact_root = lambda _env, _leaf: artifact_root
    fake_runtime.configure_streamlit_page = (
        lambda st_module, *, title: st_module.set_page_config(page_title=title)
    )
    fake_runtime.discover_files = lambda base, pattern: sorted(Path(base).glob(pattern))
    fake_runtime.ensure_repo_on_path = lambda _file: None
    fake_runtime.relative_label = lambda path, root: Path(path).relative_to(root).as_posix()
    fake_runtime.render_streamlit_page_header = (
        lambda st_module, *, title, logo_title, caption: (
            events.append(("logo", logo_title)),
            st_module.title(title),
            st_module.caption(caption),
        )
    )
    fake_runtime.resolve_active_app_path = lambda **_kwargs: active_app
    fake_runtime.reset_scoped_session_state = lambda *_args, **_kwargs: False

    fake_agi_env = ModuleType("agi_env")

    class _FakeAgiEnv:
        for_app = None

        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    _FakeAgiEnv.for_app = _FakeAgiEnv
    fake_agi_env.AgiEnv = _FakeAgiEnv

    fake_pagelib = ModuleType("agi_gui.pagelib")
    fake_pagelib.render_logo = lambda label: events.append(("logo", label))

    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    monkeypatch.setitem(sys.modules, "agi_pages.runtime", fake_runtime)
    monkeypatch.setitem(sys.modules, "agi_env", fake_agi_env)
    monkeypatch.setitem(sys.modules, "agi_gui.pagelib", fake_pagelib)

    module = ModuleType("view_data_io_decision_full_page_test_module")
    module.__file__ = str(Path(PAGE_PATH).resolve())
    module.__package__ = None
    source = Path(PAGE_PATH).read_text(encoding="utf-8")
    exec(compile(source, str(Path(PAGE_PATH)), "exec"), module.__dict__)

    metric_labels = [payload[0] for kind, payload in events if kind == "metric"]
    assert metric_labels == [
        "Selected strategy",
        "Latency selected",
        "Cost selected",
        "Reliability selected",
    ]
    assert ("logo", "Decision Evidence") in events
    assert any(kind == "dataframe" and payload[0] == 2 for kind, payload in events)
    assert any(kind == "dataframe" and payload[0] == 1 for kind, payload in events)
