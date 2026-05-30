from __future__ import annotations

from pathlib import Path
from types import ModuleType, SimpleNamespace


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
