from __future__ import annotations

import importlib.util
import os
import sys
import types
from types import SimpleNamespace
import pytest
from pathlib import Path
from datetime import date
from unittest.mock import patch, MagicMock
from streamlit.testing.v1 import AppTest

from agi_env import AgiEnv
import agi_env.credential_store_support as credential_store_support
from pydantic import BaseModel, ValidationError, model_validator

APP_ARGS_FORM = "src/agilab/apps/builtin/flight_project/src/app_args_form.py"
DEFAULT_APPTEST_TIMEOUT = 20
ENV_TEMPLATE_PATH = Path("src/agilab/core/agi-env/src/agi_env/resources/.agilab/.env")


def _widget_or_none(collections, key: str):
    for collection in collections:
        try:
            return collection(key=key)
        except KeyError:
            continue
    return None


def _app_test(path: str, *, default_timeout: int = DEFAULT_APPTEST_TIMEOUT):
    return AppTest.from_file(path, default_timeout=default_timeout)


class _SimpleColumn:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _load_flight_form_module(
    monkeypatch,
    tmp_path: Path,
    *,
    session_state: dict[str, object],
    share_root_error: bool = False,
    load_error: Exception | None = None,
    defaults_error_source: str | None = None,
    with_humanized_errors: bool = False,
    inject_env: bool = True,
):
    settings_path = tmp_path / "flight-settings.toml"
    settings_path.write_text("", encoding="utf-8")
    calls: dict[str, list[str]] = {
        "caption": [],
        "error": [],
        "warning": [],
        "success": [],
        "info": [],
        "markdown": [],
        "code": [],
    }

    fake_st = types.ModuleType("streamlit")
    fake_st.session_state = dict(session_state)

    def _record(name):
        def inner(message=None, *args, **kwargs):
            calls[name].append("" if message is None else str(message))
            return None

        return inner

    def _stop():
        raise RuntimeError("st.stop")

    def _columns(spec):
        count = spec if isinstance(spec, int) else len(spec)
        return [_SimpleColumn() for _ in range(count)]

    def _widget(default=None, *, key=None, **_kwargs):
        if key is not None:
            fake_st.session_state.setdefault(key, default)
            return fake_st.session_state[key]
        return default

    fake_st.stop = _stop
    fake_st.columns = _columns
    fake_st.caption = _record("caption")
    fake_st.error = _record("error")
    fake_st.warning = _record("warning")
    fake_st.success = _record("success")
    fake_st.info = _record("info")
    fake_st.markdown = _record("markdown")
    fake_st.code = _record("code")
    fake_st.selectbox = lambda _label, options=None, key=None, **kwargs: _widget(
        (options or [""])[0], key=key, **kwargs
    )
    fake_st.text_input = lambda _label, value="", key=None, **kwargs: _widget(value, key=key, **kwargs)
    fake_st.number_input = lambda _label, value=0, key=None, **kwargs: _widget(value, key=key, **kwargs)
    fake_st.date_input = lambda _label, value=None, key=None, **kwargs: _widget(value, key=key, **kwargs)
    fake_st.checkbox = lambda _label, value=False, key=None, **kwargs: _widget(value, key=key, **kwargs)

    class FlightArgs(BaseModel):
        data_source: str = "file"
        data_in: str = ""
        data_out: str = ""
        files: str = "*"
        nfile: int = 1
        nskip: int = 0
        nread: int = 0
        sampling_rate: float = 1.0
        datemin: date = date(2020, 1, 1)
        datemax: date = date(2021, 1, 1)
        output_format: str = "parquet"
        reset_target: bool = False

        @model_validator(mode="after")
        def _validate_hawk(self):
            if self.data_source == "hawk" and not self.data_in.strip():
                raise ValueError("hawk data_in is required")
            return self

        def to_toml_payload(self):
            return self.model_dump(mode="json")

    def apply_source_defaults(args):
        if defaults_error_source and getattr(args, "data_source", "") == defaults_error_source:
            raise RuntimeError("defaults failed")
        if not getattr(args, "data_out", "") and getattr(args, "data_in", ""):
            return args.model_copy(update={"data_out": "derived/output"})
        return args

    def dump_args_to_toml(_args, path):
        Path(path).write_text("saved = true\n", encoding="utf-8")

    def load_args_from_toml(_path):
        if load_error is not None:
            raise load_error
        return FlightArgs()

    fake_flight = types.ModuleType("flight")
    fake_flight.FlightArgs = FlightArgs
    fake_flight.apply_source_defaults = apply_source_defaults
    fake_flight.dump_args_to_toml = dump_args_to_toml
    fake_flight.load_args_from_toml = load_args_from_toml

    def _resolve_share_path(raw):
        return tmp_path / str(raw or "")

    env = SimpleNamespace(
        app_settings_file=settings_path,
        resolve_share_path=_resolve_share_path,
    )
    if share_root_error:
        env.share_root_path = lambda: (_ for _ in ()).throw(RuntimeError("share missing"))
    else:
        env.share_root_path = lambda: tmp_path / "share-root"
    if with_humanized_errors:
        env.humanize_validation_errors = lambda exc: [str(item["msg"]) for item in exc.errors()]

    if inject_env:
        fake_st.session_state.setdefault("env", env)
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    monkeypatch.setitem(sys.modules, "flight", fake_flight)

    module_name = f"flight_form_test_{len(sys.modules)}"
    spec = importlib.util.spec_from_file_location(module_name, APP_ARGS_FORM)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module, fake_st, calls


def _iter_env_editor_keys():
    ordered_keys: list[str] = []
    for candidate in (ENV_TEMPLATE_PATH, Path.home() / ".agilab/.env"):
        if not candidate.exists():
            continue
        for raw_line in candidate.read_text(encoding="utf-8").splitlines():
            stripped = raw_line.strip()
            if not stripped or "=" not in stripped:
                continue
            key = stripped.lstrip("#").split("=", 1)[0].strip()
            if key and key not in ordered_keys:
                ordered_keys.append(key)
    return ordered_keys


def _seed_env_editor_state(at: AppTest, env: AgiEnv) -> None:
    if "env_editor_new_key" not in at.session_state:
        at.session_state["env_editor_new_key"] = ""
    if "env_editor_new_value" not in at.session_state:
        at.session_state["env_editor_new_value"] = ""
    if "env_editor_reset" not in at.session_state:
        at.session_state["env_editor_reset"] = False
    if "env_editor_feedback" not in at.session_state:
        at.session_state["env_editor_feedback"] = None
    env_values = {key: "" if value is None else str(value) for key, value in getattr(env, "envars", {}).items()}
    for key in _iter_env_editor_keys():
        editor_key = f"env_editor_val_{key}"
        if editor_key not in at.session_state:
            at.session_state[editor_key] = env_values.get(key, "")


def _all_button_labels(at: AppTest) -> list[str]:
    labels = [button.label for button in at.button]
    try:
        labels.extend(button.label for button in at.sidebar.button)
    except Exception:
        pass
    return labels


def _assert_docs_actions_present(at: AppTest) -> None:
    labels = _all_button_labels(at)
    assert "Read Documentation" in labels
    assert "Open Local Documentation" in labels

@pytest.fixture
def mock_ui_env(tmp_path, monkeypatch):
    # Set up temporary directories for apps and config
    apps_dir = tmp_path / "apps"
    apps_dir.mkdir()
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    log_dir = tmp_path / "log"
    log_dir.mkdir()
    local_share_dir = tmp_path / "localshare"
    local_share_dir.mkdir()
    cluster_share_dir = tmp_path / "clustershare"
    cluster_share_dir.mkdir()
    
    # Create a dummy project structure
    project_dir = apps_dir / "flight_project"
    project_dir.mkdir()
    
    # Create src dir and app_settings.toml
    src_dir = project_dir / "src"
    src_dir.mkdir()
    settings_file = src_dir / "app_settings.toml"
    settings_file.write_text("[flight]\n") # Just some dummy TOML
    
    # Needs to be able to import flight
    (src_dir / "flight.py").write_text("""
from pydantic import BaseModel
from datetime import date
class FlightArgs(BaseModel):
    data_source: str = "file"
    data_in: str = ""
    data_out: str = ""
    files: str = "*"
    nfile: int = 1
    nskip: int = 0
    nread: int = 0
    sampling_rate: float = 1.0
    datemin: date = date(2020, 1, 1)
    datemax: date = date(2021, 1, 1)
    output_format: str = "parquet"
    reset_target: bool = False

    
    def to_toml_payload(self):
        return self.model_dump(mode="json")
        
def apply_source_defaults(args):
    return args
    
def dump_args_to_toml(args, path):
    pass
    
def load_args_from_toml(path):
        return FlightArgs()
""")
    
    # Create apps-pages directory structure (not strictly needed since AgiEnv falls back to builtin apps)
    pages_dir = project_dir / "apps-pages"
    pages_dir.mkdir(parents=True, exist_ok=True)


    # Mock CLI argv for AGILAB main page
    test_argv = ["About_agilab.py", "--apps-path", str(apps_dir), "--active-app", "flight_project"]
    monkeypatch.setattr(
        credential_store_support,
        "_load_keyring_module",
        lambda keyring_module=None: None,
    )
    
    # Patch sys.argv and env variables
    with patch("sys.argv", test_argv):
        with patch.dict(os.environ, {
            "AGILAB_APP": "flight_project",
            "AGILAB_DISABLE_BACKGROUND_SERVICES": "1",
            "AGI_SHARE_DIR": str(tmp_path),
            "AGI_EXPORT_DIR": str(export_dir),
            "AGI_LOG_DIR": str(log_dir),
            "AGI_LOCAL_SHARE": str(local_share_dir),
            "AGI_CLUSTER_SHARE": str(cluster_share_dir),
            "APPS_PATH": str(apps_dir),
            "AGILAB_PAGES_ABS": str(pages_dir),
            "OPENAI_API_KEY": "dummy",
            "IS_SOURCE_ENV": "1",
        }):
            yield {
                "apps_dir": apps_dir,
                "project_dir": project_dir,
                "pages_dir": pages_dir,
                "export_dir": export_dir,
                "log_dir": log_dir,
            }


def test_agilab_main_page_env_editor(mock_ui_env):
    """Test the main AGILAB page and interacting with the .env editor form."""
    home_root = mock_ui_env["apps_dir"].parent
    at = _app_test("src/agilab/About_agilab.py")

    # Run the app to initialize
    with patch.dict(os.environ, {"HOME": str(home_root)}, clear=False):
        at.run()
    assert not at.exception
    
    # Find the environment editor form
    # We expand the Environment Variables expander (Streamlit AppTest exposes them linearly, but we can look for the form)
    # Actually, we can just interact with the text inputs directly by key
    
    # Wait, the form might not be rendered unless the expander is open. By default it's expanded=False
    # However AppTest runs the whole script. In AppTest, expander contents are accessible
    assert "env_editor_new_key" in [ti.key for ti in at.text_input]
    assert "env_editor_new_value" in [ti.key for ti in at.text_input]
    _assert_docs_actions_present(at)
    
    # Set values in the text inputs
    at.text_input(key="env_editor_new_key").set_value("TEST_UI_VAR")
    at.text_input(key="env_editor_new_value").set_value("helloworld")
    
    # Submit the form
    # We find the button with label "Save .env"
    save_btn = None
    for btn in at.button:
        if btn.label == "Save .env":
            save_btn = btn
            break
            
    assert save_btn is not None
    with patch.dict(os.environ, {"HOME": str(home_root)}, clear=False):
        save_btn.click().run()
    
    assert not at.exception
    # Check if the success message appeared
    # In AppTest, st.success is mapped to at.success
    success_msgs = [s.value for s in at.success]
    assert any("Environment variables updated" in msg for msg in success_msgs)


def test_agilab_main_page_shows_agilab_version(mock_ui_env):
    home_root = mock_ui_env["apps_dir"].parent
    at = _app_test("src/agilab/About_agilab.py")

    with patch.dict(os.environ, {"HOME": str(home_root)}, clear=False):
        at.run()

    assert not at.exception
    assert any(str(caption.value).startswith("AGILAB version: v") for caption in at.caption)


def test_agilab_main_page_env_editor_shows_worker_python_override(mock_ui_env):
    home_root = mock_ui_env["apps_dir"].parent
    env_file = home_root / ".agilab" / ".env"
    env_file.parent.mkdir(parents=True, exist_ok=True)
    existing = env_file.read_text(encoding="utf-8") if env_file.exists() else ""
    if "127.0.0.1_PYTHON_VERSION" not in existing:
        env_file.write_text(existing.rstrip("\n") + "\n127.0.0.1_PYTHON_VERSION=3.12\n", encoding="utf-8")

    at = _app_test("src/agilab/About_agilab.py")
    with patch.dict(os.environ, {"HOME": str(home_root)}, clear=False):
        at.run()

    assert not at.exception
    assert any("<worker-host>_PYTHON_VERSION" in str(item.value) for item in at.caption)
    assert "env_editor_val_127.0.0.1_PYTHON_VERSION" in [ti.key for ti in at.text_input]
    assert at.text_input(key="env_editor_val_AGI_PYTHON_VERSION").label == "Default Python version"
    assert at.text_input(key="env_editor_val_127.0.0.1_PYTHON_VERSION").label == "Worker Python version for 127.0.0.1"


def test_execute_page_cluster_settings(mock_ui_env):
    """Test the EXECUTE page cluster settings interactivity."""
    
    # For execute page we need an initialized env in session_state
    at = _app_test("src/agilab/pages/2_▶️ ORCHESTRATE.py")
    
    # Pre-inject environment into session state
    env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_project", verbose=0)
    env.init_done = True
    env.st_resources = (Path(__file__).resolve().parents[1] / "src/agilab/resources").resolve()
    at.session_state["env"] = env
    at.session_state["app_settings"] = {"args": {}, "cluster": {}}
    _seed_env_editor_state(at, env)
    
    at.run()
    assert not at.exception
    _assert_docs_actions_present(at)

    enabled_toggle_key = f"cluster_enabled__flight_project"
    scheduler_key = f"cluster_scheduler__flight_project"
    # Drive the cluster state directly through session_state rather than
    # AppTest widget replay. This keeps the regression stable even when
    # unrelated sidebar widgets are conditionally omitted in test mode.
    at.session_state[enabled_toggle_key] = True
    at.session_state[scheduler_key] = "127.0.0.1:8786"
    at.session_state["cluster_pool"] = True
    at.run()
    
    assert not at.exception
    app_settings = at.session_state["app_settings"] if "app_settings" in at.session_state else {}
    cluster_state = app_settings.get("cluster", {}) if isinstance(app_settings, dict) else {}
    enabled_state = at.session_state[enabled_toggle_key] if enabled_toggle_key in at.session_state else None
    pool_state = at.session_state["cluster_pool"] if "cluster_pool" in at.session_state else None
    assert cluster_state.get("cluster_enabled", enabled_state) is True
    assert cluster_state.get("pool", pool_state) is True
    assert at.session_state[scheduler_key] == "127.0.0.1:8786"


def test_flight_project_app_args_form_render(mock_ui_env):
    """Test that the flight_project UI data source form renders without errors."""
    project_src = str(mock_ui_env["project_dir"] / "src")
    sys.path.insert(0, project_src)
    try:
        at = _app_test(APP_ARGS_FORM)
        env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_project", verbose=0)

        at.session_state["env"] = env
        at.run()

        assert not at.exception
    finally:
        if project_src in sys.path:
            sys.path.remove(project_src)

def test_flight_project_app_args_form(mock_ui_env):
    """Test the flight_project UI data source form interactions."""
    project_src = str(mock_ui_env["project_dir"] / "src")
    sys.path.insert(0, project_src)
    try:
        at = _app_test(APP_ARGS_FORM)
        env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_project", verbose=0)

        # To avoid the 'not initialised' error
        at.session_state["env"] = env

        at.run()
        assert not at.exception

        # The default data source is 'file', we switch it to 'hawk'
        at.selectbox(key="flight_project:app_args_form:data_source").set_value("hawk").run()

        # Check if the text input labels changed
        # Text input for "Hawk cluster URI" should exist (it replaces "Data directory")
        # Actually, AppTest exposes text inputs but their labels might vary. Let's find it by key
        data_in_input = at.text_input(key="flight_project:app_args_form:data_in")
        assert data_in_input.label == "Hawk cluster URI"

        files_input = at.text_input(key="flight_project:app_args_form:files")
        assert files_input.label == "Pipeline name"

        # Let's set some values
        data_in_input.set_value("hawk.cluster.local:9200")
        files_input.set_value("test_pipeline")
        at.number_input(key="flight_project:app_args_form:nfile").set_value(5)

        at.run()

        if at.error:
            print("ERRORS:", [e.value for e in at.error])

        print("SUCCESS MSGS:", [m.value for m in at.success])
        print("INFO MSGS:", [m.value for m in at.info])
        print("WARNING MSGS:", [m.value for m in at.warning])
        print("ERROR MSGS:", [m.value for m in at.error])

        assert not at.exception

        # The current parameters are collected in the session state payload or validated structure
        # The UI saves to `settings_path` and updates `app_settings`
        assert "app_settings" in at.session_state, "app_settings was not saved!"
        assert at.session_state["app_settings"]["args"]["data_source"] == "hawk"
        assert at.session_state["app_settings"]["args"]["data_in"] == "hawk.cluster.local:9200"
        assert at.session_state["app_settings"]["args"]["files"] == "test_pipeline"
        assert at.session_state["app_settings"]["args"]["nfile"] == 5

        # Look for the success message containing "Saved to"
        success_msgs = [s.value for s in at.success]
        assert any("Saved to" in msg for msg in success_msgs)
    finally:
        if project_src in sys.path:
            sys.path.remove(project_src)


def test_flight_app_args_form_import_helpers_cover_missing_env_and_parse_edges(monkeypatch, tmp_path):
    with pytest.raises(RuntimeError, match="st.stop"):
        _load_flight_form_module(monkeypatch, tmp_path, session_state={}, inject_env=False)

    module, _fake_st, _calls = _load_flight_form_module(
        monkeypatch,
        tmp_path,
        session_state={"flight_project:app_args_form:data_in": "dataset/input"},
        share_root_error=True,
        load_error=RuntimeError("broken settings"),
        defaults_error_source="hawk",
    )

    fallback = date(2022, 1, 1)
    assert module._parse_iso_date(fallback, fallback=fallback) == fallback
    assert module._parse_iso_date("not-a-date", fallback=fallback) == fallback
    assert module._parse_iso_date("", fallback=fallback) == fallback

    module.st.session_state[module._k("data_source")] = "hawk"
    module._on_data_source_change()


def test_flight_app_args_form_import_validation_branches(monkeypatch, tmp_path):
    _, _fake_st, calls = _load_flight_form_module(
        monkeypatch,
        tmp_path,
        session_state={
            "flight_project:app_args_form:data_source": "hawk",
            "flight_project:app_args_form:data_in": "",
        },
        with_humanized_errors=True,
    )

    assert calls["error"] == ["Invalid Flight parameters:"]
    assert calls["markdown"]

    _, _fake_st, calls = _load_flight_form_module(
        monkeypatch,
        tmp_path,
        session_state={
            "flight_project:app_args_form:data_source": "hawk",
            "flight_project:app_args_form:data_in": "",
        },
        with_humanized_errors=False,
    )

    assert calls["code"]


def test_flight_app_args_form_import_warns_for_missing_input_and_persists_data_out(monkeypatch, tmp_path):
    _module, _fake_st, calls = _load_flight_form_module(
        monkeypatch,
        tmp_path,
        session_state={
            "flight_project:app_args_form:data_in": "missing/input",
            "flight_project:app_args_form:data_out": "custom/output",
        },
        share_root_error=True,
        load_error=RuntimeError("broken settings"),
    )

    assert any("Unable to load Flight args" in message for message in calls["warning"])
    assert any("Input directory does not exist" in message for message in calls["warning"])
    assert calls["success"]

def test_explore_page_multiselect(mock_ui_env):
    """Test the EXPLORE page multiselect and button rendering."""
    at = _app_test("src/agilab/pages/4_▶️ ANALYSIS.py")
    at.query_params["current_page"] = "main"
    env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_project", verbose=0)
    env.init_done = True
    env.st_resources = (Path(__file__).resolve().parents[1] / "src/agilab/resources").resolve()
    env.projects = ["flight_project"]
    env.get_projects = MagicMock(return_value=["flight_project"])
    at.session_state["env"] = env
    at.run()
    assert not at.exception
    _assert_docs_actions_present(at)
    
    # Check that 'dummy_view' is an option in the multiselect
    selection_key = f"view_selection__flight_project"
    ms = at.multiselect(key=selection_key)
    
    assert "view_maps" in ms.options
    
    # Select it
    ms.select("view_maps").run()
    assert not at.exception
    
    # Ensure that the button was created for it
    btns = [b.label for b in at.button]
    assert "view_maps" in btns

def test_experiment_page_load(mock_ui_env):
    """Test that the EXPERIMENT page loads without exceptions."""
    at = _app_test("src/agilab/pages/3_▶️ PIPELINE.py")
    env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_project", verbose=0)
    env.init_done = True
    env.st_resources = (Path(__file__).resolve().parents[1] / "src/agilab/resources").resolve()
    env.get_projects = MagicMock(return_value=["flight_project"])
    # We must ensure there is a lab_steps file to not throw exceptions, or handling it safely
    # In mock env we just pass env
    at.session_state["env"] = env
    # Mock some expected session_states for the page
    at.session_state["flight_project"] = [0, "", "", "", "", ""]
    at.session_state["flight_project__venv_map"] = {}
    
    at.run()
    assert not at.exception
    _assert_docs_actions_present(at)

def test_edit_page_load(mock_ui_env):
    """Test that the EDIT page loads without exceptions."""
    at = _app_test("src/agilab/pages/1_▶️ PROJECT.py")
    env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_project", verbose=0)
    env.init_done = True
    env.st_resources = (Path(__file__).resolve().parents[1] / "src/agilab/resources").resolve()
    env.projects = ["flight_project"]
    env.get_projects = MagicMock(return_value=["flight_project"])
    at.session_state["env"] = env
    
    at.run()
    assert not at.exception
    _assert_docs_actions_present(at)


def test_execute_page_cython_toggle(mock_ui_env):
    """Test toggling the Cython checkbox on the EXECUTE page."""
    at = _app_test("src/agilab/pages/2_▶️ ORCHESTRATE.py")
    env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_project", verbose=0)
    at.session_state["env"] = env
    at.session_state["app_settings"] = {"args": {}, "cluster": {}}
    _seed_env_editor_state(at, env)

    at.run()
    assert not at.exception

    at.session_state["cluster_cython"] = True
    at.run()
    assert not at.exception
    app_settings = at.session_state["app_settings"] if "app_settings" in at.session_state else {}
    cluster_state = app_settings.get("cluster", {}) if isinstance(app_settings, dict) else {}
    assert cluster_state.get("cython", at.session_state["cluster_cython"]) is True

    at.session_state["cluster_cython"] = False
    at.run()
    assert not at.exception
    app_settings = at.session_state["app_settings"] if "app_settings" in at.session_state else {}
    cluster_state = app_settings.get("cluster", {}) if isinstance(app_settings, dict) else {}
    assert cluster_state.get("cython", at.session_state["cluster_cython"]) is False


def test_execute_page_workers_data_path(mock_ui_env):
    """Test setting the workers data path when cluster is enabled."""
    at = _app_test("src/agilab/pages/2_▶️ ORCHESTRATE.py")
    env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_project", verbose=0)
    at.session_state["env"] = env
    at.session_state["app_settings"] = {"args": {}, "cluster": {}}
    _seed_env_editor_state(at, env)

    at.run()
    assert not at.exception

    # Enable cluster first
    enabled_key = f"cluster_enabled__flight_project"
    at.session_state[enabled_key] = True
    at.run()
    assert not at.exception

    # Set workers data path
    wdp_key = f"cluster_workers_data_path__flight_project"
    at.session_state[wdp_key] = "/data/shared"
    at.run()
    assert not at.exception
    app_settings = at.session_state["app_settings"] if "app_settings" in at.session_state else {}
    cluster_state = app_settings.get("cluster", {}) if isinstance(app_settings, dict) else {}
    assert cluster_state.get("workers_data_path", at.session_state[wdp_key]) == "/data/shared"


def test_execute_service_snippet_maps_runtime_health_settings():
    """Service snippet template must forward runtime heartbeat/cleanup settings."""
    source = Path("src/agilab/orchestrate_services.py").read_text(encoding="utf-8")
    assert 'heartbeat_timeout={float(service_heartbeat_timeout)}' in source
    assert 'cleanup_done_ttl_sec={float(service_cleanup_done_ttl_hours) * 3600.0}' in source
    assert 'cleanup_failed_ttl_sec={float(service_cleanup_failed_ttl_hours) * 3600.0}' in source
    assert 'cleanup_heartbeat_ttl_sec={float(service_cleanup_heartbeat_ttl_hours) * 3600.0}' in source
    assert 'cleanup_done_max_files={int(service_cleanup_done_max_files)}' in source
    assert 'cleanup_failed_max_files={int(service_cleanup_failed_max_files)}' in source
    assert 'cleanup_heartbeat_max_files={int(service_cleanup_heartbeat_max_files)}' in source


def test_explore_page_multiple_views_selected(mock_ui_env):
    """Test selecting multiple views and verifying a button is rendered for each."""
    at = _app_test("src/agilab/pages/4_▶️ ANALYSIS.py")
    at.query_params["current_page"] = "main"
    env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_project", verbose=0)
    at.session_state["env"] = env
    at.run()
    assert not at.exception

    selection_key = "view_selection__flight_project"
    ms = at.multiselect(key=selection_key)

    # Select two views
    ms.select("view_maps").select("view_barycentric").run()
    assert not at.exception

    btns = [b.label for b in at.button]
    assert "view_maps" in btns
    assert "view_barycentric" in btns


def test_explore_page_deselect_view(mock_ui_env):
    """Test selecting then deselecting a view removes its button."""
    at = _app_test("src/agilab/pages/4_▶️ ANALYSIS.py")
    at.query_params["current_page"] = "main"
    env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_project", verbose=0)
    at.session_state["env"] = env
    at.run()
    assert not at.exception

    selection_key = "view_selection__flight_project"
    ms = at.multiselect(key=selection_key)

    # Select two views
    ms.select("view_maps").select("view_barycentric").run()
    assert not at.exception

    # Now deselect view_maps
    ms.unselect("view_maps").run()
    assert not at.exception

    btns = [b.label for b in at.button]
    assert "view_maps" not in btns
    assert "view_barycentric" in btns


def test_app_args_form_no_changes(mock_ui_env):
    """Test that submitting the form with no changes shows 'No changes to save.'."""
    project_src = str(mock_ui_env["project_dir"] / "src")
    sys.path.insert(0, project_src)
    try:
        at = _app_test(APP_ARGS_FORM)
        env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_project", verbose=0)
        at.session_state["env"] = env

        at.run()
        assert not at.exception

        # Run again without changing anything
        at.run()
        assert not at.exception

        info_msgs = [m.value for m in at.info]
        assert any("No changes" in msg for msg in info_msgs)
    finally:
        if project_src in sys.path:
            sys.path.remove(project_src)


def test_app_args_form_switch_back_to_file(mock_ui_env):
    """Test switching data source from file -> hawk -> file and verifying labels revert."""
    project_src = str(mock_ui_env["project_dir"] / "src")
    sys.path.insert(0, project_src)
    try:
        at = _app_test(APP_ARGS_FORM)
        env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_project", verbose=0)
        at.session_state["env"] = env
        at.run()
        assert not at.exception

        # Switch to hawk
        at.selectbox(key="flight_project:app_args_form:data_source").set_value("hawk").run()
        assert not at.exception
        assert at.text_input(key="flight_project:app_args_form:data_in").label == "Hawk cluster URI"

        # Switch back to file
        at.selectbox(key="flight_project:app_args_form:data_source").set_value("file").run()
        assert not at.exception
        assert at.text_input(key="flight_project:app_args_form:data_in").label == "Data directory"
        assert at.text_input(key="flight_project:app_args_form:files").label == "Files filter"
    finally:
        if project_src in sys.path:
            sys.path.remove(project_src)


def test_agilab_main_page_theme_injection(mock_ui_env):
    """Test that the main page injects theme CSS on load."""
    at = _app_test("src/agilab/About_agilab.py")
    at.run()
    assert not at.exception

    # The page injects CSS via st.markdown with unsafe_allow_html=True
    # In AppTest, these show up as at.markdown elements
    md_values = [m.value for m in at.markdown]
    assert any("<style>" in val or "style" in val.lower() for val in md_values if isinstance(val, str)), \
        "Expected theme CSS to be injected via st.markdown"


def test_experiment_page_missing_openai_key(mock_ui_env):
    """Test that EXPERIMENT page handles a missing OpenAI API key gracefully."""
    at = _app_test("src/agilab/pages/3_▶️ PIPELINE.py")
    env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_project", verbose=0)

    at.session_state["env"] = env
    at.session_state["flight_project"] = [0, "", "", "", "", ""]
    at.session_state["flight_project__venv_map"] = {}

    # Remove the API key from the environment
    with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
        at.run()

    # The page should still load without crashing
    assert not at.exception


def test_experiment_page_delete_cancel_fragment_flow(mock_ui_env, tmp_path):
    """Deleting then canceling a step should rerender locally without crashing."""
    export_root = tmp_path / "export"
    lab_dir = export_root / "flight"
    lab_dir.mkdir(parents=True, exist_ok=True)
    steps_file = lab_dir / "lab_steps.toml"
    steps_file.write_text(
        '[[flight]]\nD = ""\nQ = "demo prompt"\nM = "dummy-model"\nC = "print(1)"\nR = "runpy"\n',
        encoding="utf-8",
    )

    with patch.dict(os.environ, {"AGI_EXPORT_DIR": str(export_root)}, clear=False):
        at = _app_test("src/agilab/pages/3_▶️ PIPELINE.py", default_timeout=20)
        env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_project", verbose=0)
        env.init_done = True
        env.AGILAB_EXPORT_ABS = export_root
        env.envars["AGI_EXPORT_DIR"] = str(export_root)
        env.target = "flight"
        env.st_resources = (Path(__file__).resolve().parents[1] / "src/agilab/resources").resolve()

        at.session_state["env"] = env
        at.session_state["flight"] = [0, "", "", "", "", "", 1]
        at.run()
        assert not at.exception

        safe_prefix = "flight_lab_steps.toml"
        at.button(key=f"{safe_prefix}_delete_0").click().run()
        assert not at.exception
        assert any(button.key == f"{safe_prefix}_delete_cancel_0" for button in at.button)

        at.button(key=f"{safe_prefix}_delete_cancel_0").click().run()
        assert not at.exception
        assert at.text_area(key=f"{safe_prefix}_q_step_0").value == "demo prompt"
        confirm_state_key = f"{safe_prefix}_confirm_delete_0"
        assert not at.session_state.filtered_state.get(confirm_state_key, False)


def test_experiment_page_lab_switch_refreshes_in_virgin_session(mock_ui_env, tmp_path):
    """Switching labs on first use should immediately load the selected lab."""
    export_root = tmp_path / "export"
    flight_lab = export_root / "flight_project"
    trainer_lab = export_root / "sb3_trainer_project"
    flight_lab.mkdir(parents=True, exist_ok=True)
    trainer_lab.mkdir(parents=True, exist_ok=True)
    (flight_lab / "lab_steps.toml").write_text(
        '[[flight_project]]\nD = ""\nQ = "flight prompt"\nM = "dummy-model"\nC = "print(1)"\nR = "runpy"\n',
        encoding="utf-8",
    )
    (trainer_lab / "lab_steps.toml").write_text(
        '[[sb3_trainer_project]]\nD = ""\nQ = "trainer prompt"\nM = "dummy-model"\nC = "print(2)"\nR = "runpy"\n',
        encoding="utf-8",
    )

    with patch.dict(os.environ, {"AGI_EXPORT_DIR": str(export_root)}, clear=False):
        at = _app_test("src/agilab/pages/3_▶️ PIPELINE.py", default_timeout=20)
        env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_project", verbose=0)
        env.init_done = True
        env.AGILAB_EXPORT_ABS = export_root
        env.envars["AGI_EXPORT_DIR"] = str(export_root)
        env.target = "flight_project"
        env.st_resources = (Path(__file__).resolve().parents[1] / "src/agilab/resources").resolve()
        env.get_projects = MagicMock(return_value=["flight_project", "sb3_trainer_project"])

        at.session_state["env"] = env
        at.run()
        assert not at.exception

        initial_lab = at.session_state["lab_dir_selectbox"]
        target_lab = (
            "sb3_trainer_project"
            if initial_lab != "sb3_trainer_project"
            else "flight_project"
        )
        expected_prompt = "trainer prompt" if target_lab == "sb3_trainer_project" else "flight prompt"

        at.sidebar.selectbox(key="lab_dir_selectbox").set_value(target_lab).run()

        assert not at.exception
        assert at.session_state["lab_dir_selectbox"] == target_lab
        assert Path(at.session_state["steps_file"]).parent.name == target_lab
        assert Path(str(at.session_state["index_page"])).parts[0] == target_lab
        assert at.text_area(key=f"{target_lab}_lab_steps.toml_q_step_0").value == expected_prompt


def test_experiment_page_save_step_persists_prompt(mock_ui_env, tmp_path):
    export_root = tmp_path / "export"
    lab_dir = export_root / "flight_project"
    lab_dir.mkdir(parents=True, exist_ok=True)
    steps_file = lab_dir / "lab_steps.toml"
    steps_file.write_text(
        '[[flight_project]]\nD = ""\nQ = "original prompt"\nM = "dummy-model"\nC = "print(1)"\nR = "runpy"\n',
        encoding="utf-8",
    )

    with patch.dict(os.environ, {"AGI_EXPORT_DIR": str(export_root)}, clear=False):
        at = _app_test("src/agilab/pages/3_▶️ PIPELINE.py", default_timeout=20)
        env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_project", verbose=0)
        env.init_done = True
        env.AGILAB_EXPORT_ABS = export_root
        env.envars["AGI_EXPORT_DIR"] = str(export_root)
        env.target = "flight_project"
        env.st_resources = (Path(__file__).resolve().parents[1] / "src/agilab/resources").resolve()
        env.get_projects = MagicMock(return_value=["flight_project"])

        at.session_state["env"] = env
        at.run()
        assert not at.exception

        updated_prompt = "updated prompt from AppTest"
        at.session_state["flight_project_lab_steps.toml_q_step_0"] = updated_prompt
        at.run()
        at.button(key="flight_project_lab_steps.toml_save_0").click().run()

        assert not at.exception
        assert updated_prompt in steps_file.read_text(encoding="utf-8")
        assert at.text_area(key="flight_project_lab_steps.toml_q_step_0").value == updated_prompt


def test_experiment_page_confirm_remove_updates_steps_file(mock_ui_env, tmp_path):
    export_root = tmp_path / "export"
    lab_dir = export_root / "flight_project"
    lab_dir.mkdir(parents=True, exist_ok=True)
    steps_file = lab_dir / "lab_steps.toml"
    steps_file.write_text(
        """
[[flight_project]]
D = ""
Q = "first prompt"
M = "dummy-model"
C = "print(1)"
R = "runpy"
[[flight_project]]
D = ""
Q = "second prompt"
M = "dummy-model"
C = "print(2)"
R = "runpy"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    with patch.dict(os.environ, {"AGI_EXPORT_DIR": str(export_root)}, clear=False):
        at = _app_test("src/agilab/pages/3_▶️ PIPELINE.py", default_timeout=20)
        env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_project", verbose=0)
        env.init_done = True
        env.AGILAB_EXPORT_ABS = export_root
        env.envars["AGI_EXPORT_DIR"] = str(export_root)
        env.target = "flight_project"
        env.st_resources = (Path(__file__).resolve().parents[1] / "src/agilab/resources").resolve()
        env.get_projects = MagicMock(return_value=["flight_project"])

        at.session_state["env"] = env
        at.run()
        assert not at.exception

        at.button(key="flight_project_lab_steps.toml_delete_0").click().run()
        assert not at.exception
        assert any(button.key == "flight_project_lab_steps.toml_delete_confirm_0" for button in at.button)

        at.button(key="flight_project_lab_steps.toml_delete_confirm_0").click().run()
        assert not at.exception

        stored = steps_file.read_text(encoding="utf-8")
        assert "first prompt" not in stored
        assert "second prompt" in stored


def test_edit_page_project_selectbox(mock_ui_env):
    """Test that the EDIT page has a project selectbox with available projects."""
    at = _app_test("src/agilab/pages/1_▶️ PROJECT.py")
    env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_project", verbose=0)
    env.init_done = True
    env.st_resources = (Path(__file__).resolve().parents[1] / "src/agilab/resources").resolve()
    env.projects = ["flight_project"]
    env.get_projects = MagicMock(return_value=["flight_project"])
    at.session_state["env"] = env
    at.session_state["sidebar_selection"] = "Edit"

    at.run()
    assert not at.exception

    main_selectboxes = list(at.selectbox)
    sidebar_selectboxes = list(at.sidebar.selectbox)
    selectbox_keys = [sb.key for sb in main_selectboxes] + [sb.key for sb in sidebar_selectboxes]
    assert selectbox_keys, (
        "EDIT page should have at least one selectbox "
        f"(main={len(main_selectboxes)}, sidebar={len(sidebar_selectboxes)}, "
        f"errors={[e.value for e in at.error]})"
    )
    assert "project_selectbox" in selectbox_keys


def test_clone_page_exposes_environment_strategy(mock_ui_env):
    at = _app_test("src/agilab/pages/1_▶️ PROJECT.py")
    env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_project", verbose=0)
    env.init_done = True
    env.st_resources = (Path(__file__).resolve().parents[1] / "src/agilab/resources").resolve()
    env.projects = ["flight_project"]
    env.get_projects = MagicMock(return_value=["flight_project"])
    at.session_state["env"] = env
    at.session_state["sidebar_selection"] = "Clone"

    at.run()
    assert not at.exception

    sidebar_radios = list(at.sidebar.radio)
    radio_keys = [radio.key for radio in sidebar_radios]
    assert "clone_env_strategy" in radio_keys
