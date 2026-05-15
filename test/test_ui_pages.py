from __future__ import annotations

import importlib.util
import importlib
import os
import shutil
import sys
import tomllib
import types
from types import SimpleNamespace
import pytest
from pathlib import Path
from datetime import date
from unittest.mock import patch, MagicMock
from streamlit.testing.v1 import AppTest

from agi_env import AgiEnv
import agi_env.credential_store_support as credential_store_support
from pydantic import BaseModel, model_validator

APP_ARGS_FORM = "src/agilab/apps/builtin/flight_telemetry_project/src/app_args_form.py"
DEFAULT_APPTEST_TIMEOUT = 20
ENV_TEMPLATE_PATH = Path("src/agilab/core/agi-env/src/agi_env/resources/.agilab/.env")


def _import_agilab_module(module_name: str):
    src_root = Path(__file__).resolve().parents[1] / "src"
    package_root = str(src_root / "agilab")
    src_root_str = str(src_root)
    if src_root_str not in sys.path:
        sys.path.insert(0, src_root_str)
    pkg = sys.modules.get("agilab")
    if pkg is None or not hasattr(pkg, "__path__"):
        pkg = types.ModuleType("agilab")
        pkg.__path__ = [package_root]
        sys.modules["agilab"] = pkg
    else:
        package_path = list(pkg.__path__)
        if package_root not in package_path:
            pkg.__path__ = [package_root, *package_path]
    if getattr(pkg, "__spec__", None) is None:
        pkg.__spec__ = importlib.util.spec_from_file_location(
            "agilab",
            src_root / "agilab" / "__init__.py",
            submodule_search_locations=[package_root],
        )
        pkg.__file__ = str(src_root / "agilab" / "__init__.py")
        pkg.__package__ = "agilab"
    importlib.invalidate_caches()
    return importlib.import_module(module_name)


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
        def _validate_public_file_source(self):
            if self.data_source != "file":
                raise ValueError("flight_telemetry_project public demo supports only file-based input")
            if self.files == "[":
                raise ValueError("invalid files filter")
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
    fake_flight.SUPPORTED_DATA_SOURCES = ("file",)
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
    missing = object()
    previous_flight = sys.modules.get("flight", missing)
    sys.modules["flight"] = fake_flight

    module_name = f"flight_form_test_{len(sys.modules)}"
    spec = importlib.util.spec_from_file_location(module_name, APP_ARGS_FORM)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        if previous_flight is missing:
            sys.modules.pop("flight", None)
        else:
            sys.modules["flight"] = previous_flight
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


def _seed_probeable_venv(venv: Path) -> None:
    python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    python.parent.mkdir(parents=True, exist_ok=True)
    if python.exists() or python.is_symlink():
        python.unlink()
    try:
        python.symlink_to(Path(sys.executable), target_is_directory=False)
    except OSError:
        shutil.copy2(sys.executable, python)
    if os.name == "nt":
        site_packages = venv / "Lib" / "site-packages"
    else:
        site_packages = venv / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    site_packages.mkdir(parents=True, exist_ok=True)
    for module_name in ("agi_env", "agi_node", "agi_cluster"):
        package_dir = site_packages / module_name
        package_dir.mkdir(parents=True, exist_ok=True)
        (package_dir / "__init__.py").write_text("", encoding="utf-8")
        if module_name == "agi_cluster":
            distributor_dir = package_dir / "agi_distributor"
            distributor_dir.mkdir(parents=True, exist_ok=True)
            (distributor_dir / "__init__.py").write_text("class StageRequest: ...\n", encoding="utf-8")


def _current_app_state_name(at: AppTest) -> str:
    try:
        env = at.session_state["env"]
    except Exception:
        return ""
    app_value = getattr(env, "app", "")
    return Path(str(app_value)).name if app_value else ""


def _all_button_labels(at: AppTest) -> list[str]:
    labels = [button.label for button in at.button]
    try:
        labels.extend(button.label for button in at.sidebar.button)
    except Exception:
        pass
    return labels


def _page_text(at: AppTest) -> str:
    elements = [
        *at.markdown,
        *at.caption,
        *at.info,
        *at.warning,
        *at.error,
    ]
    return "\n".join(str(item.value) for item in elements)


def _element_labels(container) -> list[str]:
    return [
        str(label)
        for item in container
        if (label := getattr(item, "label", None)) is not None
    ]


def _assert_docs_actions_absent(at: AppTest) -> None:
    labels = _all_button_labels(at)
    assert "Read Documentation" not in labels
    assert "Open Local Documentation" not in labels


def _write_minimal_run_manifest(manifest_path: Path, *, app_name: str = "flight_telemetry_project") -> None:
    run_manifest = _import_agilab_module("agilab.run_manifest")
    manifest = run_manifest.build_run_manifest(
        path_id=f"{app_name}-apptest",
        label="WORKFLOW AppTest run",
        status="pass",
        command=run_manifest.RunManifestCommand(
            label="workflow apptest",
            argv=("agilab", "workflow"),
            cwd=str(Path.cwd()),
            env_overrides={},
        ),
        environment=run_manifest.RunManifestEnvironment(
            python_version="3.13.13",
            python_executable=sys.executable,
            platform="test",
            repo_root=str(Path.cwd()),
            active_app=str(Path.cwd() / "src/agilab/apps/builtin" / app_name),
            app_name=app_name,
        ),
        timing=run_manifest.RunManifestTiming(
            started_at="2026-05-12T10:00:00Z",
            finished_at="2026-05-12T10:00:03Z",
            duration_seconds=3.25,
            target_seconds=60.0,
        ),
        artifacts=[],
        validations=[
            run_manifest.RunManifestValidation(
                label="workflow_page",
                status="pass",
                summary="WORKFLOW page rendered",
            )
        ],
        run_id="run-workflow-apptest",
        created_at="2026-05-12T10:00:03Z",
    )
    run_manifest.write_run_manifest(manifest, manifest_path)


def test_first_party_pages_configure_docs_menu_items() -> None:
    expected = {
        "src/agilab/main_page.py": "get_about_content()",
        "src/agilab/pages/1_PROJECT.py": 'get_docs_menu_items(html_file="edit-help.html")',
        "src/agilab/pages/2_ORCHESTRATE.py": 'get_docs_menu_items(html_file="execute-help.html")',
        "src/agilab/pages/3_WORKFLOW.py": 'get_docs_menu_items(html_file="experiment-help.html")',
        "src/agilab/pages/4_ANALYSIS.py": 'get_docs_menu_items(html_file="explore-help.html")',
    }

    for page_path, marker in expected.items():
        assert marker in Path(page_path).read_text(encoding="utf-8")

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
    project_dir = apps_dir / "flight_telemetry_project"
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
    env_file = tmp_path / ".agilab" / ".env"
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text("CLUSTER_CREDENTIALS=\n", encoding="utf-8")
    about_env_editor = _import_agilab_module("agilab.about_page.env_editor")
    monkeypatch.setattr(about_env_editor, "ENV_FILE_PATH", env_file, raising=False)


    # Mock CLI argv for AGILAB main page
    test_argv = ["main_page.py", "--apps-path", str(apps_dir), "--active-app", "flight_telemetry_project"]
    monkeypatch.setattr(
        credential_store_support,
        "_load_keyring_module",
        lambda keyring_module=None: None,
    )
    
    # Patch sys.argv and env variables
    with patch("sys.argv", test_argv):
        with patch.dict(os.environ, {
            "APP_DEFAULT": "flight_telemetry_project",
            "AGILAB_DISABLE_BACKGROUND_SERVICES": "1",
            "AGI_CLUSTER_SHARE": str(tmp_path),
            "AGI_EXPORT_DIR": str(export_dir),
            "AGI_LOG_DIR": str(log_dir),
            "AGI_LOCAL_SHARE": str(local_share_dir),
            "AGI_CLUSTER_SHARE": str(cluster_share_dir),
            "APPS_PATH": str(apps_dir),
            "AGILAB_PAGES_ABS": str(pages_dir),
            "OPENAI_API_KEY": "dummy",
            # Prevent developer-shell secrets from leaking into AppTest runs and
            # triggering keychain storage paths during first-run initialization.
            "CLUSTER_CREDENTIALS": "",
            "AGILAB_RUNTIME_DIAGNOSTICS_VERBOSE": "1",
            "IS_SOURCE_ENV": "1",
            # Keep Streamlit AppTest runs off the macOS keychain so they never
            # block on an interactive credential prompt during local/CI preflight.
            "PYTHON_KEYRING_BACKEND": "keyring.backends.fail.Keyring",
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
    at = _app_test("src/agilab/main_page.py")

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
    assert at.text_input(key="env_editor_val_CLUSTER_CREDENTIALS").value == ""
    assert "Runtime diagnostics" in _element_labels(at)
    assert "Diagnostics level" in _element_labels(at)
    assert "Runtime diagnostics" not in _element_labels(at.sidebar)
    assert "Diagnostics level" not in _element_labels(at.sidebar)
    _assert_docs_actions_absent(at)
    
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


def test_agilab_main_page_refuses_unprotected_public_bind(mock_ui_env):
    home_root = mock_ui_env["apps_dir"].parent
    at = _app_test("src/agilab/main_page.py")

    with patch.dict(
        os.environ,
        {
            "HOME": str(home_root),
            "STREAMLIT_SERVER_ADDRESS": "0.0.0.0",
            "AGILAB_PUBLIC_BIND_OK": "",
            "AGILAB_TLS_TERMINATED": "",
        },
        clear=False,
    ):
        at.run()

    assert not list(at.exception)
    assert any("refuses to bind the Streamlit UI publicly" in item.value for item in at.error)


def test_env_editor_redacts_sensitive_values_in_widgets_and_preview(mock_ui_env):
    module = _import_agilab_module("agilab.about_page.env_editor")

    assert module._is_sensitive_env_key("OPENAI_API_KEY")
    assert module._is_sensitive_env_key("MISTRAL_TOKEN")
    assert not module._is_sensitive_env_key("AGI_CLUSTER_SHARE")
    assert module._env_editor_input_value("OPENAI_API_KEY", "sk-real-secret") == ""
    assert module._env_preview_value("OPENAI_API_KEY", "sk-real-secret") == module.REDACTED_ENV_VALUE
    assert module._env_preview_value("CLUSTER_CREDENTIALS", module.KEYRING_SENTINEL) == "<stored in keyring>"


def test_agilab_main_page_env_editor_does_not_render_secret_values(mock_ui_env):
    home_root = mock_ui_env["apps_dir"].parent
    env_file = home_root / ".agilab" / ".env"
    env_file.write_text(
        "\n".join(
            [
                "OPENAI_API_KEY=sk-real-secret-should-not-render",
                "MISTRAL_API_TOKEN=mistral-secret-should-not-render",
                "AGI_CLUSTER_SHARE=clustershare/user",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    at = _app_test("src/agilab/main_page.py")
    with patch.dict(os.environ, {"HOME": str(home_root)}, clear=False):
        at.run()

    assert not at.exception
    rendered = "\n".join(str(item.value) for item in list(at.code) + list(at.markdown) + list(at.caption))
    assert "sk-real-secret-should-not-render" not in rendered
    assert "mistral-secret-should-not-render" not in rendered
    assert "OPENAI_API_KEY=<redacted>" in rendered
    assert at.text_input(key="env_editor_val_OPENAI_API_KEY").value == ""


def test_agilab_main_page_shows_agilab_version(mock_ui_env):
    home_root = mock_ui_env["apps_dir"].parent
    at = _app_test("src/agilab/main_page.py")

    with patch.dict(os.environ, {"HOME": str(home_root)}, clear=False):
        at.run()

    assert not at.exception
    assert not any(str(caption.value).startswith("AGILAB version: v") for caption in at.sidebar.caption)
    sidebar_markdown = "\n".join(str(item.value) for item in at.sidebar.markdown)
    assert "Documentation" in sidebar_markdown
    assert "agilab-help.html" in sidebar_markdown


def test_agilab_navigation_keeps_about_hidden_from_visible_page_list():
    source = Path("src/agilab/main_page.py").read_text(encoding="utf-8")
    selector_source = Path("src/agilab/page_project_selector.py").read_text(encoding="utf-8")
    pipeline_source = Path("src/agilab/pages/3_WORKFLOW.py").read_text(encoding="utf-8")

    assert "st.navigation(_navigation_pages()).run()" in source
    assert 'title="Main Page"' in source
    assert 'visibility="hidden"' in source
    assert 'page_label="ABOUT"' not in source
    assert 'page_label="MAIN_PAGE"' in source
    assert 'title="PROJECT"' in source
    assert 'url_path="PROJECT"' in source
    assert 'visibility="hidden"' in source
    assert 'title="ORCHESTRATE"' in source
    assert 'title="WORKFLOW"' in source
    assert 'title="ANALYSIS"' in source
    assert "streamlit.sidebar.columns([0.76, 0.24], vertical_alignment=\"bottom\")" in selector_source
    assert 'streamlit.switch_page(Path("pages/1_PROJECT.py"))' in selector_source
    assert 'st.switch_page(Path("pages/1_PROJECT.py"))' in pipeline_source
    assert 'st.sidebar.markdown(f"### [MLflow]({mlflow_url})")' in pipeline_source
    assert 'st.sidebar.columns([0.64, 0.36], vertical_alignment="center")' not in pipeline_source
    assert "stLinkButton" not in pipeline_source
    assert '"Open UI"' not in pipeline_source
    assert '"Open"' not in pipeline_source


def test_agilab_main_page_env_editor_shows_worker_python_override(mock_ui_env):
    home_root = mock_ui_env["apps_dir"].parent
    env_file = home_root / ".agilab" / ".env"
    env_file.parent.mkdir(parents=True, exist_ok=True)
    existing = env_file.read_text(encoding="utf-8") if env_file.exists() else ""
    if "127.0.0.1_PYTHON_VERSION" not in existing:
        env_file.write_text(existing.rstrip("\n") + "\n127.0.0.1_PYTHON_VERSION=3.12\n", encoding="utf-8")

    at = _app_test("src/agilab/main_page.py")
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
    at = _app_test("src/agilab/pages/2_ORCHESTRATE.py")
    
    # Pre-inject environment into session state
    env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_telemetry_project", verbose=0)
    env.init_done = True
    env.st_resources = (Path(__file__).resolve().parents[1] / "src/agilab/resources").resolve()
    data_share = Path(env.app_data_rel)
    if data_share.exists():
        shutil.rmtree(data_share)
    data_share.mkdir(parents=True, exist_ok=True)
    (data_share / "sample.bin").write_bytes(b"x" * 1536)
    runenv = Path(env.runenv)
    runenv.mkdir(parents=True, exist_ok=True)
    (runenv / "run_20260506_010203.log").write_text("first run\n", encoding="utf-8")
    (runenv / "run_20260506_020304.log").write_text("second run\n", encoding="utf-8")
    at.session_state["env"] = env
    at.session_state["app_settings"] = {"args": {}, "cluster": {}}
    _seed_env_editor_state(at, env)
    
    at.run()
    assert not at.exception
    _assert_docs_actions_absent(at)
    markdown_text = "\n".join(str(item.value) for item in at.markdown)
    assert "Run readiness" not in markdown_text
    assert all("Check what will run" not in str(item.value) for item in at.caption)
    assert "Runtime module" in markdown_text
    assert "Manager env" in markdown_text
    assert "Worker env" in markdown_text
    assert "Runs" in markdown_text
    assert "Data share content (size)" in markdown_text
    assert "Data/share" not in markdown_text
    assert "1.5 KB" in markdown_text
    assert "Resource summary" in markdown_text
    assert "Share" in markdown_text
    assert "CPU" in markdown_text
    assert "RAM" in markdown_text
    assert "GPU" in markdown_text
    assert "NPU" in markdown_text
    assert "Execution environment" not in markdown_text
    assert "ORCHESTRATE context" not in markdown_text
    assert "agilab-execution-context" not in markdown_text
    assert "Active project" not in markdown_text
    assert "Scheduler" not in markdown_text
    assert "Mode" not in markdown_text
    assert all("Run mode " not in str(item.value) for item in at.info)
    assert "agilab-header-value agilab-header-value--ready'>2</div>" in markdown_text
    assert "Settings</div>" not in markdown_text

    assert "Next action" not in markdown_text
    assert all("Active project" not in str(item.value) for item in at.sidebar.markdown)
    assert all("Flow:" not in str(item.value) for item in at.caption)
    assert all("runtime resources -> arguments -> distribution preview" not in str(item.value) for item in at.caption)
    assert all("active project and runtime resources" not in str(item.value) for item in at.caption)
    assert all(text_input.key != "project_filter" for text_input in at.sidebar.text_input)
    assert "Runtime diagnostics" not in _element_labels(at.sidebar)
    assert "Diagnostics level" not in _element_labels(at.sidebar)

    app_state_name = _current_app_state_name(at)
    enabled_toggle_key = f"cluster_enabled__{app_state_name}"
    scheduler_key = f"cluster_scheduler__{app_state_name}"
    pool_key = f"cluster_pool__{app_state_name}"
    at.toggle(key=enabled_toggle_key).set_value(True).run()
    assert not at.exception

    at.session_state[scheduler_key] = "127.0.0.1:8786"
    at.session_state[pool_key] = True
    at.run()
    
    assert not at.exception
    markdown_text = "\n".join(str(item.value) for item in at.markdown)
    assert "agi_share_path" not in markdown_text
    app_settings = at.session_state["app_settings"] if "app_settings" in at.session_state else {}
    cluster_state = app_settings.get("cluster", {}) if isinstance(app_settings, dict) else {}
    enabled_state = at.session_state[enabled_toggle_key] if enabled_toggle_key in at.session_state else None
    pool_state = at.session_state[pool_key] if pool_key in at.session_state else None
    assert cluster_state.get("cluster_enabled", enabled_state) is True
    assert cluster_state.get("pool", pool_state) is True
    assert at.session_state[scheduler_key] == "127.0.0.1:8786"


def test_orchestrate_page_does_not_import_dag_helper_from_execute_module():
    source = Path("src/agilab/pages/2_ORCHESTRATE.py").read_text(encoding="utf-8")
    workflow_import = source.split('"agilab.workflow_ui"', 1)[1].split(")", 1)[0]
    execute_import = source.split('"agilab.orchestrate_execute"', 1)[1].split(")", 1)[0]

    assert '"is_dag_worker_base": "is_dag_worker_base"' in workflow_import
    assert '"is_dag_worker_base": "is_dag_worker_base"' not in execute_import


def test_orchestrate_resource_summary_uses_updated_cluster_widget_state():
    source = Path("src/agilab/pages/2_ORCHESTRATE.py").read_text(encoding="utf-8")
    panel_source = source.split("async def _render_deployment_panel", 1)[1]

    placeholder_index = panel_source.index("resource_summary_slot = st.empty()")
    cluster_widget_index = panel_source.index("render_cluster_settings_ui(")
    summary_index = panel_source.index("_render_orchestrate_resource_summary(env, target=resource_summary_slot)")

    assert placeholder_index < cluster_widget_index < summary_index


def test_execute_page_realigns_stale_agi_space_session_env(mock_ui_env, tmp_path):
    """Source ORCHESTRATE must not keep an old installed agi-space active app."""
    at = _app_test("src/agilab/pages/2_ORCHESTRATE.py")
    source_apps = (Path(__file__).resolve().parents[1] / "src/agilab/apps").resolve()
    source_project = source_apps / "builtin" / "flight_telemetry_project"
    stale_apps = tmp_path / "agi-space" / "apps"
    stale_project = stale_apps / "builtin" / "flight_telemetry_project"
    stale_project.mkdir(parents=True)

    env = AgiEnv(apps_path=source_apps, app="flight_telemetry_project", verbose=0)
    env.apps_path = stale_apps
    env.active_app = stale_project
    env.init_done = True
    env.st_resources = (Path(__file__).resolve().parents[1] / "src/agilab/resources").resolve()
    at.session_state["env"] = env
    at.session_state["apps_path"] = str(stale_apps)
    at.session_state["app_settings"] = {"args": {}, "cluster": {}}
    _seed_env_editor_state(at, env)

    at.run()

    assert not at.exception
    assert Path(at.session_state["env"].apps_path) == source_apps
    assert Path(at.session_state["env"].active_app) == source_project
    markdown_text = "\n".join(str(item.value) for item in at.markdown)
    assert "agi-space" not in markdown_text


def test_execute_page_realigns_stale_active_app_only_for_source_root(mock_ui_env, tmp_path):
    """ORCHESTRATE header must not use an old agi-space active app when apps_path is already source."""
    at = _app_test("src/agilab/pages/2_ORCHESTRATE.py")
    source_apps = (Path(__file__).resolve().parents[1] / "src/agilab/apps").resolve()
    source_project = source_apps / "builtin" / "flight_telemetry_project"
    stale_project = tmp_path / "agi-space" / "apps" / "builtin" / "flight_telemetry_project"
    stale_project.mkdir(parents=True)

    env = AgiEnv(apps_path=source_apps, app="flight_telemetry_project", verbose=0)
    env.active_app = stale_project
    env.init_done = True
    env.st_resources = (Path(__file__).resolve().parents[1] / "src/agilab/resources").resolve()
    at.session_state["env"] = env
    at.session_state["apps_path"] = str(source_apps)
    at.session_state["app_settings"] = {"args": {}, "cluster": {}}
    _seed_env_editor_state(at, env)

    at.run()

    assert not at.exception
    assert Path(at.session_state["env"].apps_path) == source_apps
    assert Path(at.session_state["env"].active_app) == source_project
    markdown_text = "\n".join(str(item.value) for item in at.markdown)
    assert "agi-space" not in markdown_text
    assert str(source_project / ".venv") in markdown_text


def test_execute_page_install_robot_allows_benign_uv_self_update_warning(mock_ui_env):
    """Robot-style INSTALL regression for handled remote uv self-update warnings."""

    at = _app_test("src/agilab/pages/2_ORCHESTRATE.py", default_timeout=30)
    env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_telemetry_project", verbose=0)
    env.init_done = True
    env.st_resources = (Path(__file__).resolve().parents[1] / "src/agilab/resources").resolve()
    cluster_share = mock_ui_env["apps_dir"].parent / "clustershare"
    cluster_share.mkdir(parents=True, exist_ok=True)
    env.AGI_CLUSTER_SHARE = str(cluster_share)
    env.envars = dict(getattr(env, "envars", {}) or {})
    env.envars["AGI_CLUSTER_SHARE"] = str(cluster_share)
    at.session_state["env"] = env
    at.session_state["app_settings"] = {
        "args": {},
        "cluster": {
            "cluster_enabled": True,
            "cython": True,
            "pool": True,
            "scheduler": "192.168.20.111:8786",
            "workers": {"192.168.20.111": 1, "192.168.20.15": 1},
            "workers_data_path": str(cluster_share),
        },
    }
    _seed_env_editor_state(at, env)
    calls: list[dict[str, object]] = []

    async def _fake_run_agi(self, code, log_callback=None, venv=None, type=None):
        calls.append({"code": code, "venv": venv, "type": type})
        if "AGI.install" in code:
            assert venv is None
            _seed_probeable_venv(self.active_app / ".venv")
            _seed_probeable_venv(self.wenv_abs / ".venv")
            if log_callback is not None:
                log_callback("Remote command stderr: error: Permission denied (os error 13)")
                log_callback(
                    "Failed to update uv on 192.168.20.15 (skipping self update): "
                    "Process exited with non-zero exit status 2"
                )
            return "None\nProcess finished", ""
        assert "AGI.run" in code
        assert venv is not None
        if log_callback is not None:
            log_callback("run completed")
        return "{'ok': True}", ""

    with patch.object(AgiEnv, "run_agi", _fake_run_agi):
        at.run()
        assert not at.exception
        at.button(key="install_btn").click().run()
        assert not at.exception
        install_success_rendered = any("Cluster installation completed." in str(item.value) for item in at.success)
        install_failure_rendered = any("Cluster installation failed." in str(item.value) for item in at.error)
        install_log_rendered = any("✅ Install complete." in str(item.value) for item in at.code)
        benign_warning_rendered = any(
            "Process exited with non-zero exit status 2" in str(item.value) for item in at.code
        )
        at.run()
        assert not at.exception
        at.button(key="run_btn").click().run()

    assert not at.exception
    assert len(calls) == 2
    assert "AGI.install" in str(calls[0]["code"])
    assert "AGI.run" in str(calls[1]["code"])
    assert install_success_rendered is True
    assert install_failure_rendered is False
    assert install_log_rendered is True
    assert benign_warning_rendered is True
    assert any("run completed" in str(item.value) for item in at.code)


def test_execute_page_cluster_toggle_off_persists_false_to_workspace(mock_ui_env):
    at = _app_test("src/agilab/pages/2_ORCHESTRATE.py")

    env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_telemetry_project", verbose=0)
    env.init_done = True
    env.st_resources = (Path(__file__).resolve().parents[1] / "src/agilab/resources").resolve()
    at.session_state["env"] = env
    at.session_state["app_settings"] = {"args": {}, "cluster": {}}
    _seed_env_editor_state(at, env)

    at.run()
    assert not at.exception

    app_state_name = _current_app_state_name(at)
    enabled_key = f"cluster_enabled__{app_state_name}"
    at.toggle(key=enabled_key).set_value(True).run()
    assert not at.exception
    assert at.session_state["app_settings"]["cluster"]["cluster_enabled"] is True

    at.toggle(key=enabled_key).set_value(False).run()
    assert not at.exception

    cluster_state = at.session_state["app_settings"]["cluster"]
    assert cluster_state["cluster_enabled"] is False

    payload = tomllib.loads(Path(env.app_settings_file).read_text(encoding="utf-8"))
    assert payload["cluster"]["cluster_enabled"] is False


def test_flight_telemetry_project_app_args_form_render(mock_ui_env):
    """Test that the flight_telemetry_project UI data source form renders without errors."""
    project_src = str(mock_ui_env["project_dir"] / "src")
    sys.path.insert(0, project_src)
    try:
        at = _app_test(APP_ARGS_FORM)
        env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_telemetry_project", verbose=0)

        at.session_state["env"] = env
        at.run()

        assert not at.exception
    finally:
        if project_src in sys.path:
            sys.path.remove(project_src)

def test_flight_telemetry_project_app_args_form(mock_ui_env):
    """Test the flight_telemetry_project file-based public UI data source form interactions."""
    project_src = str(mock_ui_env["project_dir"] / "src")
    sys.path.insert(0, project_src)
    try:
        at = _app_test(APP_ARGS_FORM)
        env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_telemetry_project", verbose=0)

        # To avoid the 'not initialised' error
        at.session_state["env"] = env

        at.run()
        assert not at.exception

        source_select = at.selectbox(key="flight_telemetry_project:app_args_form:data_source")
        assert source_select.options == ["file"]

        data_in_input = at.text_input(key="flight_telemetry_project:app_args_form:data_in")
        assert data_in_input.label == "Data directory"

        files_input = at.text_input(key="flight_telemetry_project:app_args_form:files")
        assert files_input.label == "Files filter"

        data_in_input.set_value("flight/custom_dataset")
        files_input.set_value("*.csv")
        at.number_input(key="flight_telemetry_project:app_args_form:nfile").set_value(5)

        at.run()

        if at.error:
            print("ERRORS:", [e.value for e in at.error])

        print("SUCCESS MSGS:", [m.value for m in at.success])
        print("INFO MSGS:", [m.value for m in at.info])
        print("WARNING MSGS:", [m.value for m in at.warning])
        print("ERROR MSGS:", [m.value for m in at.error])

        assert not at.exception

        assert "app_settings" in at.session_state, "app_settings was not saved!"
        assert at.session_state["app_settings"]["args"]["data_source"] == "file"
        assert at.session_state["app_settings"]["args"]["data_in"] == "flight/custom_dataset"
        assert at.session_state["app_settings"]["args"]["files"] == "*.csv"
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
        session_state={"flight_telemetry_project:app_args_form:data_in": "dataset/input"},
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
            "flight_telemetry_project:app_args_form:data_source": "file",
            "flight_telemetry_project:app_args_form:files": "[",
        },
        with_humanized_errors=True,
    )

    assert calls["error"] == ["Invalid Flight parameters:"]
    assert calls["markdown"]

    _, _fake_st, calls = _load_flight_form_module(
        monkeypatch,
        tmp_path,
        session_state={
            "flight_telemetry_project:app_args_form:data_source": "file",
            "flight_telemetry_project:app_args_form:files": "[",
        },
        with_humanized_errors=False,
    )

    assert calls["code"]


def test_flight_app_args_form_import_warns_for_missing_input_and_persists_data_out(monkeypatch, tmp_path):
    monkeypatch.delenv("SPACE_ID", raising=False)
    monkeypatch.delenv("SPACE_HOST", raising=False)

    _module, _fake_st, calls = _load_flight_form_module(
        monkeypatch,
        tmp_path,
        session_state={
            "flight_telemetry_project:app_args_form:data_in": "missing/input",
            "flight_telemetry_project:app_args_form:data_out": "custom/output",
        },
        share_root_error=True,
        load_error=RuntimeError("broken settings"),
    )

    assert any("Unable to load Flight args" in message for message in calls["warning"])
    assert any("Input directory does not exist" in message for message in calls["warning"])
    assert calls["success"]


def test_flight_app_args_form_hf_seed_dataset_missing_is_informational(monkeypatch, tmp_path):
    monkeypatch.setenv("SPACE_ID", "jpmorard/agilab")

    _module, _fake_st, calls = _load_flight_form_module(
        monkeypatch,
        tmp_path,
        session_state={
            "flight_telemetry_project:app_args_form:data_in": "flight/dataset",
            "flight_telemetry_project:app_args_form:data_out": "flight/dataframe",
        },
        share_root_error=True,
        load_error=RuntimeError("broken settings"),
    )

    assert not any("Input directory does not exist" in message for message in calls["warning"])
    assert any("public Hugging Face Space" in message for message in calls["info"])


def test_explore_page_multiselect(mock_ui_env):
    """Test the EXPLORE page multiselect and button rendering."""
    notebooks_dir = mock_ui_env["project_dir"] / "notebooks"
    notebooks_dir.mkdir()
    (notebooks_dir / "lab_stages.ipynb").write_text("{}", encoding="utf-8")

    at = _app_test("src/agilab/pages/4_ANALYSIS.py")
    at.query_params["current_page"] = "main"
    env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_telemetry_project", verbose=0)
    env.init_done = True
    env.st_resources = (Path(__file__).resolve().parents[1] / "src/agilab/resources").resolve()
    env.projects = ["flight_telemetry_project"]
    env.get_projects = MagicMock(return_value=["flight_telemetry_project"])
    at.session_state["env"] = env
    at.run()
    assert not at.exception
    _assert_docs_actions_absent(at)
    markdown_values = [item.value for item in at.markdown]
    assert all("Analysis workspace" not in value for value in markdown_values)
    assert any("Analysis views" in value for value in markdown_values)
    caption_values = [str(item.value) for item in at.caption]
    assert all("Project evidence, available outputs" not in value for value in caption_values)
    assert all("Choose the project whose analysis artifacts" not in value for value in caption_values)
    assert all("Open the view" not in value for value in caption_values)
    assert all("Output root" not in value for value in caption_values)
    assert all("Examples:" not in value for value in caption_values)
    assert all("Entrypoint" not in value for value in caption_values)
    markdown_text = "\n".join(markdown_values)
    assert "Output files" in markdown_text
    assert "Latest output" in markdown_text
    assert "Views selected" in markdown_text
    assert "Notebooks selected" in markdown_text
    assert "Choose the analysis surface" in markdown_text
    assert "AGI page" in markdown_text
    assert "Notebook / AGI snippets" in markdown_text
    assert "Use both" in markdown_text
    assert "app contract" in markdown_text
    assert "agi-page-*" in markdown_text
    assert "code-centric" in markdown_text
    assert "snippet/notebook contract" in markdown_text
    assert "ANALYSIS Jupyter sidecar" in markdown_text
    assert "Available views" not in markdown_text
    assert "selected / available" not in markdown_text
    assert "agilab-header-value--incomplete" in markdown_text
    assert "Recommended" not in markdown_text
    assert "Project</div>" not in markdown_text
    assert "Artifacts" not in markdown_text
    sidebar_markdown = "\n".join(str(item.value) for item in at.sidebar.markdown)
    assert "### Active project" not in sidebar_markdown
    assert all(text_input.key != "project_filter" for text_input in at.sidebar.text_input)
    assert "### Analysis views" in sidebar_markdown
    assert "agilab-analysis-view-links" in sidebar_markdown
    assert "current_page=" in sidebar_markdown
    assert "view_maps" in sidebar_markdown
    assert "### Notebooks" in sidebar_markdown
    assert "agilab-analysis-notebook-links" in sidebar_markdown
    assert "current_notebook=" in sidebar_markdown
    assert "lab_stages.ipynb" in sidebar_markdown
    sidebar_buttons = [button.label for button in at.sidebar.button]
    assert "view_maps" not in sidebar_buttons
    assert not [selectbox for selectbox in at.sidebar.selectbox if selectbox.key == "analysis_sidebar_view__flight_telemetry_project"]
    
    # Check that 'dummy_view' is an option in the multiselect
    selection_key = f"view_selection__flight_telemetry_project"
    ms = at.multiselect(key=selection_key)
    
    assert "view_maps" in ms.options
    notebook_ms = at.multiselect(key="notebook_selection__flight_telemetry_project")
    assert "lab_stages.ipynb" in notebook_ms.options
    
    # Select it
    ms.select("view_maps").run()
    assert not at.exception
    
    # Launching is handled by the sidebar links, not by duplicate in-page sidecar buttons.
    btns = [b.label for b in at.button]
    assert "Open view_maps" not in btns
    assert "Open" not in btns


def test_explore_page_default_view_does_not_mutate_widget_state_after_render(mock_ui_env):
    """Default analysis views hydrate sidebar links without auto-opening a view."""
    page_path = mock_ui_env["pages_dir"] / "view_default.py"
    page_path.write_text(
        "import streamlit as st\n\n"
        "def main():\n"
        "    st.write('default view rendered')\n",
        encoding="utf-8",
    )
    settings_payload = (
        "[pages]\n"
        "default_view = 'view_default'\n"
        "view_module = []\n"
    )
    settings_file = mock_ui_env["project_dir"] / "src" / "app_settings.toml"
    settings_file.write_text(
        settings_payload,
        encoding="utf-8",
    )

    at = _app_test("src/agilab/pages/4_ANALYSIS.py")
    home_root = mock_ui_env["apps_dir"].parent
    with patch.dict(os.environ, {"HOME": str(home_root), "SPACE_ID": "test/agilab"}, clear=False):
        env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_telemetry_project", verbose=0)
    env.init_done = True
    env.st_resources = (Path(__file__).resolve().parents[1] / "src/agilab/resources").resolve()
    env.AGILAB_PAGES_ABS = str(mock_ui_env["pages_dir"])
    env.projects = ["flight_telemetry_project"]
    env.get_projects = MagicMock(return_value=["flight_telemetry_project"])
    env.envars["SPACE_ID"] = "test/agilab"
    env.resolve_user_app_settings_file("flight_telemetry_project").write_text(
        settings_payload,
        encoding="utf-8",
    )
    at.session_state["env"] = env

    at.run()

    assert not at.exception
    assert at.session_state["view_selection__flight_telemetry_project"] == ["view_default"]
    assert at.query_params.get("current_page") in (None, "", "main")
    markdown_text = "\n".join(str(item.value) for item in at.markdown)
    assert "Views selected" in markdown_text
    assert "default view rendered" not in markdown_text
    sidebar_markdown = "\n".join(str(item.value) for item in at.sidebar.markdown)
    assert "view_default" in sidebar_markdown
    assert "current_page=" in sidebar_markdown
    assert not [selectbox for selectbox in at.sidebar.selectbox if selectbox.key == "analysis_sidebar_view__flight_telemetry_project"]


def test_explore_page_sidebar_view_selection_persists(mock_ui_env):
    """ANALYSIS persists the selected sidebar view launcher links."""
    at = _app_test("src/agilab/pages/4_ANALYSIS.py")
    at.query_params["current_page"] = "main"
    env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_telemetry_project", verbose=0)
    env.resolve_user_app_settings_file("flight_telemetry_project").write_text(
        "[pages]\nview_module = []\n",
        encoding="utf-8",
    )
    at.session_state["env"] = env

    at.run()

    assert not at.exception
    selection_key = "view_selection__flight_telemetry_project"
    at.multiselect(key=selection_key).select("view_maps").select("view_barycentric").run()

    assert not at.exception
    settings_file = env.resolve_user_app_settings_file("flight_telemetry_project")
    with settings_file.open("rb") as f:
        settings_payload = tomllib.load(f)
    pages_payload = settings_payload["pages"]
    assert pages_payload["view_module"] == ["view_maps", "view_barycentric"]
    assert "default_views" not in pages_payload
    assert "default_view" not in pages_payload
    markdown_text = "\n".join(str(item.value) for item in at.markdown)
    assert "Views selected" in markdown_text
    assert "2 linked to flight_telemetry_project" in markdown_text
    assert "agilab-header-value agilab-header-value--ready'>2/" in markdown_text
    assert "Available views" not in markdown_text
    assert "selected / available" not in markdown_text
    sidebar_markdown = "\n".join(str(item.value) for item in at.sidebar.markdown)
    assert "view_maps" in sidebar_markdown
    assert "view_barycentric" in sidebar_markdown
    assert "current_page=" in sidebar_markdown

    at.multiselect(key=selection_key).unselect("view_maps").run()

    assert not at.exception
    with settings_file.open("rb") as f:
        settings_payload = tomllib.load(f)
    pages_payload = settings_payload["pages"]
    assert pages_payload["view_module"] == ["view_barycentric"]
    assert "default_views" not in pages_payload
    assert "default_view" not in pages_payload

    reloaded = _app_test("src/agilab/pages/4_ANALYSIS.py")
    reloaded.query_params["current_page"] = "main"
    reloaded.session_state["env"] = env
    reloaded.run()

    assert not reloaded.exception
    assert reloaded.session_state["view_selection__flight_telemetry_project"] == ["view_barycentric"]
    reloaded_markdown = "\n".join(str(item.value) for item in reloaded.markdown)
    assert "Views selected" in reloaded_markdown
    assert "1 linked to flight_telemetry_project" in reloaded_markdown
    assert "agilab-header-value agilab-header-value--ready'>1/" in reloaded_markdown
    assert "Available views" not in reloaded_markdown
    reloaded_sidebar_markdown = "\n".join(str(item.value) for item in reloaded.sidebar.markdown)
    assert "view_maps" not in reloaded_sidebar_markdown
    assert "view_barycentric" in reloaded_sidebar_markdown
    assert "current_page=" in reloaded_sidebar_markdown


def test_explore_page_sidebar_notebook_selection_persists(mock_ui_env):
    """ANALYSIS persists selected project notebook launcher links."""
    notebooks_dir = mock_ui_env["project_dir"] / "notebooks"
    (notebooks_dir / "extra").mkdir(parents=True)
    (notebooks_dir / "lab_stages.ipynb").write_text("{}", encoding="utf-8")
    (notebooks_dir / "extra" / "demo.ipynb").write_text("{}", encoding="utf-8")

    at = _app_test("src/agilab/pages/4_ANALYSIS.py")
    at.query_params["current_page"] = "main"
    env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_telemetry_project", verbose=0)
    settings_file = env.resolve_user_app_settings_file("flight_telemetry_project")
    settings_file.write_text(
        "[pages]\nview_module = []\n[notebooks]\nselected = []\n",
        encoding="utf-8",
    )
    at.session_state["env"] = env

    at.run()

    assert not at.exception
    selection_key = "notebook_selection__flight_telemetry_project"
    at.multiselect(key=selection_key).select("extra/demo.ipynb").run()

    assert not at.exception
    with settings_file.open("rb") as f:
        settings_payload = tomllib.load(f)
    assert settings_payload["notebooks"]["selected"] == ["extra/demo.ipynb"]
    markdown_text = "\n".join(str(item.value) for item in at.markdown)
    assert "Notebooks selected" in markdown_text
    assert "1 linked to flight_telemetry_project" in markdown_text
    assert "agilab-header-value agilab-header-value--ready'>1/2</div>" in markdown_text
    sidebar_markdown = "\n".join(str(item.value) for item in at.sidebar.markdown)
    assert "### Notebooks" in sidebar_markdown
    assert "extra/demo.ipynb" in sidebar_markdown
    assert "lab_stages.ipynb" not in sidebar_markdown
    assert "current_notebook=" in sidebar_markdown

    reloaded = _app_test("src/agilab/pages/4_ANALYSIS.py")
    reloaded.query_params["current_page"] = "main"
    reloaded.session_state["env"] = env
    reloaded.run()

    assert not reloaded.exception
    assert reloaded.session_state[selection_key] == ["extra/demo.ipynb"]
    reloaded_markdown = "\n".join(str(item.value) for item in reloaded.markdown)
    assert "Notebooks selected" in reloaded_markdown
    assert "1 linked to flight_telemetry_project" in reloaded_markdown
    assert "agilab-header-value agilab-header-value--ready'>1/2</div>" in reloaded_markdown
    reloaded_sidebar_markdown = "\n".join(str(item.value) for item in reloaded.sidebar.markdown)
    assert "extra/demo.ipynb" in reloaded_sidebar_markdown
    assert "lab_stages.ipynb" not in reloaded_sidebar_markdown
    assert "current_notebook=" in reloaded_sidebar_markdown


def test_explore_page_sidebar_links_initialize_from_view_module(mock_ui_env):
    """Selected analysis views render in the sidebar even when another view was previously default."""
    at = _app_test("src/agilab/pages/4_ANALYSIS.py")
    at.query_params["current_page"] = "main"
    env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_telemetry_project", verbose=0)
    settings_file = env.resolve_user_app_settings_file("flight_telemetry_project")
    settings_file.write_text(
        (
            "[pages]\n"
            "view_module = ['view_maps', 'view_maps_3d']\n"
            "default_view = 'view_maps_3d'\n"
            "default_views = ['view_maps_3d']\n"
        ),
        encoding="utf-8",
    )
    at.session_state["env"] = env

    at.run()

    assert not at.exception
    sidebar_markdown = "\n".join(str(item.value) for item in at.sidebar.markdown)
    assert "view_maps" in sidebar_markdown
    assert "view_maps_3d" in sidebar_markdown
    assert "current_page=" in sidebar_markdown
    with settings_file.open("rb") as f:
        settings_payload = tomllib.load(f)
    pages_payload = settings_payload["pages"]
    assert pages_payload["view_module"] == ["view_maps", "view_maps_3d"]
    assert "default_views" not in pages_payload
    assert "default_view" not in pages_payload


def test_experiment_page_load(mock_ui_env):
    """Test that the EXPERIMENT page loads without exceptions."""
    at = _app_test("src/agilab/pages/3_WORKFLOW.py")
    env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_telemetry_project", verbose=0)
    env.init_done = True
    env.st_resources = (Path(__file__).resolve().parents[1] / "src/agilab/resources").resolve()
    env.get_projects = MagicMock(return_value=["flight_telemetry_project"])
    # We must ensure there is a lab_stages file to not throw exceptions, or handling it safely
    # In mock env we just pass env
    at.session_state["env"] = env
    # Mock some expected session_states for the page
    at.session_state["flight_telemetry_project"] = [0, "", "", "", "", ""]
    at.session_state["flight_telemetry_project__venv_map"] = {}
    
    at.run()
    assert not at.exception
    _assert_docs_actions_absent(at)
    markdown_text = "\n".join(str(item.value) for item in at.markdown)
    assert "Workflow stages" in markdown_text
    assert "Runnable" in markdown_text
    assert "Output files" in markdown_text
    assert "Dataframes" in markdown_text
    assert "Workflow graph" in markdown_text
    assert "Updated" in markdown_text
    sidebar_text = "\n".join(str(item.value) for item in [*at.sidebar.markdown, *at.sidebar.caption])
    assert "Inspect experiment runs separately from pipeline execution." not in sidebar_text
    assert "Start it from Edit." not in sidebar_text
    assert "MLflow" not in sidebar_text


def test_workflow_page_surfaces_existing_run_log_contract(mock_ui_env):
    """WORKFLOW should reference the existing log/execute run evidence, not a parallel history."""
    at = _app_test("src/agilab/pages/3_WORKFLOW.py")
    env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_telemetry_project", verbose=0)
    env.init_done = True
    env.st_resources = (Path(__file__).resolve().parents[1] / "src/agilab/resources").resolve()
    env.get_projects = MagicMock(return_value=["flight_telemetry_project"])
    runenv = Path(env.runenv)
    runenv.mkdir(parents=True, exist_ok=True)
    latest_log = runenv / "run_20260512_100000.log"
    latest_log.write_text("workflow run finished\n", encoding="utf-8")
    _write_minimal_run_manifest(runenv / "run_manifest.json", app_name="flight_telemetry_project")

    at.session_state["env"] = env
    at.session_state["flight_telemetry_project"] = [0, "", "", "", "", ""]
    at.session_state["flight_telemetry_project__venv_map"] = {}

    at.run()

    assert not at.exception
    page_text = _page_text(at)
    assert "Execution log" in page_text
    assert "Plan evidence" in page_text
    assert str(latest_log) in page_text
    assert str(runenv / "run_manifest.json") in page_text
    assert "Latest execution" in "".join(str(item.label) for item in at.expander)


def test_workflow_dag_project_keeps_dataframe_load_export_controls_hidden(tmp_path):
    """DAG-only projects should expose workflow execution, not dataframe load/export actions."""
    export_root = tmp_path / "export"
    log_root = tmp_path / "log"
    home_root = tmp_path / "home"
    export_root.mkdir()
    log_root.mkdir()
    home_root.mkdir()
    apps_dir = Path("src/agilab/apps/builtin").resolve()
    with patch.dict(
        os.environ,
        {
            "HOME": str(home_root),
            "AGI_EXPORT_DIR": str(export_root),
            "AGI_LOG_DIR": str(log_root),
            "AGILAB_DISABLE_BACKGROUND_SERVICES": "1",
            "OPENAI_API_KEY": "dummy",
            "IS_SOURCE_ENV": "1",
        },
        clear=False,
    ):
        env = AgiEnv(apps_path=apps_dir, app="global_dag_project", verbose=0)
        env.init_done = True
        env.st_resources = (Path(__file__).resolve().parents[1] / "src/agilab/resources").resolve()
        env.get_projects = MagicMock(return_value=["global_dag_project"])
        at = _app_test("src/agilab/pages/3_WORKFLOW.py", default_timeout=30)
        at.session_state["env"] = env
        at.session_state["global_dag_project"] = [0, "", "", "", "", ""]
        at.session_state["global_dag"] = [0, "", "", "", "", ""]
        at.session_state["global_dag_project__venv_map"] = {}

        at.run()

    assert not at.exception
    page_text = _page_text(at)
    assert "Execution log" in page_text
    assert "Plan evidence" in page_text
    labels = _all_button_labels(at)
    assert "Run workflow" in labels
    assert "Load output" not in labels
    assert "Export" not in labels
    assert "Delete output" not in labels
    assert "No dataframe export found yet" not in page_text


def test_workflow_notebook_manifest_dir_prefers_selected_project(tmp_path):
    workflow_page = _import_agilab_module("agilab.pages.3_WORKFLOW")
    apps_root = tmp_path / "apps"
    active_project = apps_root / "alpha_project"
    selected_project = apps_root / "beta_project"
    active_project.mkdir(parents=True)
    selected_project.mkdir()
    env = SimpleNamespace(
        apps_path=apps_root,
        builtin_apps_path=apps_root / "builtin",
        active_app=active_project,
        app="alpha_project",
        target="alpha_project",
    )

    resolved = workflow_page._resolve_active_app_project_dir(env, "beta_project")

    assert resolved == selected_project.resolve()


def test_pipeline_page_restores_missing_export_stages_from_project_source(mock_ui_env):
    source_stages = mock_ui_env["project_dir"] / "lab_stages.toml"
    source_stages.write_text(
        'flight_telemetry_project = [{ Q = "Recover pipeline", C = "print(1)" }]\n',
        encoding="utf-8",
    )
    target_stages = mock_ui_env["export_dir"] / "flight" / "lab_stages.toml"
    assert not target_stages.exists()

    at = _app_test("src/agilab/pages/3_WORKFLOW.py")
    env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_telemetry_project", verbose=0)
    env.init_done = True
    env.st_resources = (Path(__file__).resolve().parents[1] / "src/agilab/resources").resolve()
    env.get_projects = MagicMock(return_value=["flight_telemetry_project"])
    at.session_state["env"] = env

    at.run()

    assert not at.exception
    data = tomllib.loads(target_stages.read_text(encoding="utf-8"))
    assert data["flight"][0]["Q"] == "Recover pipeline"
    assert "flight_telemetry_project" not in data


def test_edit_page_load(mock_ui_env):
    """Test that the EDIT page loads without exceptions."""
    at = _app_test("src/agilab/pages/1_PROJECT.py")
    env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_telemetry_project", verbose=0)
    env.init_done = True
    env.st_resources = (Path(__file__).resolve().parents[1] / "src/agilab/resources").resolve()
    env.projects = ["flight_telemetry_project"]
    env.get_projects = MagicMock(return_value=["flight_telemetry_project"])
    at.session_state["env"] = env
    
    at.run()
    assert not at.exception
    markdown_values = [item.value for item in at.markdown]
    assert all("Project workspace" not in value for value in markdown_values)
    assert all("Identity, editable files" not in str(item.value) for item in at.caption)
    assert any("Edit project files" in value for value in markdown_values)
    assert any(button.label == "Export" for button in at.sidebar.button)
    assert all(button.label != "Edit" for button in at.sidebar.button)
    assert all(button.label != "Export project" for button in at.sidebar.button)
    markdown_text = "\n".join(markdown_values)
    assert "Worker class" in markdown_text
    assert "Source files" not in markdown_text
    assert "Source LOC" in markdown_text
    assert "Functions" in markdown_text
    assert "Classes" in markdown_text
    assert "Docs/config" in markdown_text
    assert "Runtime module" not in markdown_text
    assert "Manager env" not in markdown_text
    assert "Worker env" not in markdown_text
    assert "Project</div>" not in markdown_text
    assert "Project workspace" not in markdown_text
    assert "README" not in markdown_text
    assert all("Open only the file group you need" not in str(item.value) for item in at.caption)
    sidebar_markdown = "\n".join(str(item.value) for item in at.sidebar.markdown)
    assert "### Active project" not in sidebar_markdown
    assert "Project</div>" not in sidebar_markdown
    assert "workspace ready" not in sidebar_markdown
    assert all(text_input.key != "project_filter" for text_input in at.sidebar.text_input)
    assert "Runtime diagnostics" not in _element_labels(at)
    assert "Diagnostics level" not in _element_labels(at)
    assert "Runtime diagnostics" not in _element_labels(at.sidebar)
    assert "Diagnostics level" not in _element_labels(at.sidebar)
    _assert_docs_actions_absent(at)


def test_project_sidebar_orders_active_project_before_actions():
    """The sidebar should start with selection controls before project actions."""
    source = Path("src/agilab/pages/1_PROJECT.py").read_text(encoding="utf-8")
    page_body = source[source.index("def page():"):]

    active_project_index = page_body.index("_render_active_project_sidebar(env)")
    export_index = page_body.index("_render_sidebar_export_action(env)")
    action_index = page_body.index('"Project action"')

    assert active_project_index < export_index < action_index
    assert "Project workflow" not in source
    assert "### Active project" not in source
    assert "_render_sidebar_project_metric" not in source
    assert "workspace ready" not in source
    assert "_render_project_software_metrics(env)" in source
    assert "_render_edit_project_metric" not in source
    assert "Choose what to do with the active project" not in source
    assert "Actions below apply to this selected project" not in source
    assert "Export creates a portable archive" not in source
    assert "Project workspace" not in source
    assert "Identity, editable files" not in source
    assert 'page_title="AGILab PROJECT"' in source
    assert 'layout="wide"' in source
    assert '["Edit", "Create", "Import", "Rename", "Delete"]' in source
    assert '["Edit", "Clone", "Import", "Rename", "Delete"]' not in source
    assert "_render_project_workspace_overview" not in source
    assert "Python package used by RUN/ORCHESTRATE" not in source
    assert "Source LOC" in source
    assert "Project Name (no suffix)" not in source
    assert "New Project Name (no suffix)" not in source


def test_execute_page_cython_setting_hydrates_from_app_settings(mock_ui_env):
    """Test that the EXECUTE page hydrates the Cython checkbox from app settings."""
    at = _app_test("src/agilab/pages/2_ORCHESTRATE.py")
    env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_telemetry_project", verbose=0)
    env.init_done = True
    env.st_resources = (Path(__file__).resolve().parents[1] / "src/agilab/resources").resolve()
    Path(env.app_settings_file).write_text("[cluster]\ncython = true\n", encoding="utf-8")
    at.session_state["env"] = env
    _seed_env_editor_state(at, env)

    at.run()
    assert not at.exception

    app_state_name = _current_app_state_name(at)
    cython_key = f"cluster_cython__{app_state_name}"
    app_settings = at.session_state["app_settings"] if "app_settings" in at.session_state else {}
    cluster_state = app_settings.get("cluster", {}) if isinstance(app_settings, dict) else {}
    assert cluster_state.get("cython", at.session_state[cython_key]) is True
    assert at.session_state[cython_key] is True


def test_execute_page_workers_data_path(mock_ui_env):
    """Test setting the workers data path when cluster is enabled."""
    at = _app_test("src/agilab/pages/2_ORCHESTRATE.py")
    env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_telemetry_project", verbose=0)
    env.init_done = True
    env.st_resources = (Path(__file__).resolve().parents[1] / "src/agilab/resources").resolve()
    at.session_state["env"] = env
    at.session_state["app_settings"] = {"args": {}, "cluster": {}}
    _seed_env_editor_state(at, env)

    at.run()
    assert not at.exception

    # Enable cluster first
    app_state_name = _current_app_state_name(at)
    enabled_key = f"cluster_enabled__{app_state_name}"
    at.toggle(key=enabled_key).set_value(True).run()
    assert not at.exception

    # Set workers data path
    wdp_key = f"cluster_workers_data_path__{app_state_name}"
    at.text_input(key=wdp_key).set_value("/data/shared").run()
    assert not at.exception
    app_settings = at.session_state["app_settings"] if "app_settings" in at.session_state else {}
    cluster_state = app_settings.get("cluster", {}) if isinstance(app_settings, dict) else {}
    assert cluster_state.get("workers_data_path", at.session_state[wdp_key]) == "/data/shared"
    with open(env.app_settings_file, "rb") as file:
        persisted_settings = tomllib.load(file)
    assert persisted_settings["cluster"]["workers_data_path"] == "/data/shared"

    at.text_input(key=wdp_key).set_value("").run()
    assert not at.exception
    app_settings = at.session_state["app_settings"] if "app_settings" in at.session_state else {}
    cluster_state = app_settings.get("cluster", {}) if isinstance(app_settings, dict) else {}
    assert cluster_state.get("workers_data_path") == ""
    with open(env.app_settings_file, "rb") as file:
        persisted_settings = tomllib.load(file)
    assert persisted_settings["cluster"]["workers_data_path"] == ""


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
    """Selecting multiple views renders sidebar launch links without duplicate card buttons."""
    at = _app_test("src/agilab/pages/4_ANALYSIS.py")
    at.query_params["current_page"] = "main"
    env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_telemetry_project", verbose=0)
    at.session_state["env"] = env
    at.run()
    assert not at.exception

    selection_key = "view_selection__flight_telemetry_project"
    ms = at.multiselect(key=selection_key)

    # Select two views
    ms.select("view_maps").select("view_barycentric").run()
    assert not at.exception

    btns = [b.label for b in at.button]
    assert "Open view_maps" not in btns
    assert "Open view_barycentric" not in btns
    assert "Open" not in btns
    sidebar_markdown = "\n".join(str(item.value) for item in at.sidebar.markdown)
    assert "view_maps" in sidebar_markdown
    assert "view_barycentric" in sidebar_markdown
    assert "current_page=" in sidebar_markdown


def test_explore_page_deselect_view(mock_ui_env):
    """Selecting then deselecting a view removes it from sidebar launch links."""
    at = _app_test("src/agilab/pages/4_ANALYSIS.py")
    at.query_params["current_page"] = "main"
    env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_telemetry_project", verbose=0)
    env.resolve_user_app_settings_file("flight_telemetry_project").write_text(
        "[pages]\nview_module = []\n",
        encoding="utf-8",
    )
    at.session_state["env"] = env
    at.run()
    assert not at.exception

    selection_key = "view_selection__flight_telemetry_project"
    ms = at.multiselect(key=selection_key)

    # Select two views
    ms.select("view_maps").select("view_barycentric").run()
    assert not at.exception

    # Now deselect view_maps
    ms.unselect("view_maps").run()
    assert not at.exception

    btns = [b.label for b in at.button]
    card_open_buttons = [
        b for b in at.button if str(getattr(b, "key", "")).startswith("analysis_open_view__")
    ]
    assert "Open view_maps" not in btns
    assert "Open view_barycentric" not in btns
    assert not card_open_buttons
    sidebar_markdown = "\n".join(str(item.value) for item in at.sidebar.markdown)
    assert "view_maps" not in sidebar_markdown
    assert "view_barycentric" in sidebar_markdown


def test_app_args_form_no_changes(mock_ui_env):
    """Test that submitting the form with no changes shows 'No changes to save.'."""
    project_src = str(mock_ui_env["project_dir"] / "src")
    sys.path.insert(0, project_src)
    try:
        at = _app_test(APP_ARGS_FORM)
        env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_telemetry_project", verbose=0)
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


def test_app_args_form_exposes_only_file_source(mock_ui_env):
    """Test the public built-in form exposes only the implemented file source."""
    project_src = str(mock_ui_env["project_dir"] / "src")
    sys.path.insert(0, project_src)
    try:
        at = _app_test(APP_ARGS_FORM)
        env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_telemetry_project", verbose=0)
        at.session_state["env"] = env
        at.run()
        assert not at.exception

        source_select = at.selectbox(key="flight_telemetry_project:app_args_form:data_source")
        assert source_select.options == ["file"]
        assert at.text_input(key="flight_telemetry_project:app_args_form:data_in").label == "Data directory"
        assert at.text_input(key="flight_telemetry_project:app_args_form:files").label == "Files filter"
    finally:
        if project_src in sys.path:
            sys.path.remove(project_src)


def test_agilab_main_page_theme_injection(mock_ui_env):
    """Test that the main page injects theme CSS on load."""
    at = _app_test("src/agilab/main_page.py")
    at.run()
    assert not at.exception

    # The page injects CSS via st.markdown with unsafe_allow_html=True
    # In AppTest, these show up as at.markdown elements
    md_values = [m.value for m in at.markdown]
    assert any("<style>" in val or "style" in val.lower() for val in md_values if isinstance(val, str)), \
        "Expected theme CSS to be injected via st.markdown"


def test_agilab_main_page_missing_openai_key_stays_silent_on_first_launch(mock_ui_env):
    at = _app_test("src/agilab/main_page.py")

    with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
        at.run()

    assert not at.exception
    warning_messages = [str(item.value) for item in at.warning]
    info_messages = [str(item.value) for item in at.info]
    assert not any("OPENAI_API_KEY" in message for message in warning_messages)
    assert not any("OPENAI_API_KEY" in message for message in info_messages)


def test_experiment_page_missing_openai_key(mock_ui_env):
    """Test that EXPERIMENT page handles a missing OpenAI API key gracefully."""
    at = _app_test("src/agilab/pages/3_WORKFLOW.py")
    env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_telemetry_project", verbose=0)

    at.session_state["env"] = env
    at.session_state["flight_telemetry_project"] = [0, "", "", "", "", ""]
    at.session_state["flight_telemetry_project__venv_map"] = {}

    # Remove the API key from the environment
    with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
        at.run()

    # The page should still load without crashing
    assert not at.exception


def test_experiment_page_delete_cancel_fragment_flow(mock_ui_env, tmp_path):
    """Deleting then canceling a stage should rerender locally without crashing."""
    export_root = tmp_path / "export"
    flight_lab_dir = export_root / "flight"
    flight_lab_dir.mkdir(parents=True, exist_ok=True)
    (flight_lab_dir / "lab_stages.toml").write_text(
        '[[flight]]\nD = ""\nQ = "demo prompt"\nM = "dummy-model"\nC = "print(1)"\nR = "runpy"\n',
        encoding="utf-8",
    )
    flight_telemetry_project_lab_dir = export_root / "flight_telemetry_project"
    flight_telemetry_project_lab_dir.mkdir(parents=True, exist_ok=True)
    (flight_telemetry_project_lab_dir / "lab_stages.toml").write_text(
        '[[flight_telemetry_project]]\nD = ""\nQ = "demo prompt"\nM = "dummy-model"\nC = "print(1)"\nR = "runpy"\n',
        encoding="utf-8",
    )

    with patch.dict(os.environ, {"AGI_EXPORT_DIR": str(export_root)}, clear=False):
        at = _app_test("src/agilab/pages/3_WORKFLOW.py", default_timeout=20)
        env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_telemetry_project", verbose=0)
        env.init_done = True
        env.AGILAB_EXPORT_ABS = export_root
        env.envars["AGI_EXPORT_DIR"] = str(export_root)
        env.target = "flight_telemetry_project"
        env.st_resources = (Path(__file__).resolve().parents[1] / "src/agilab/resources").resolve()

        at.query_params["lab_dir_selectbox"] = "flight_telemetry_project"
        at.session_state["env"] = env
        at.session_state["flight"] = [0, "", "", "", "", "", 1]
        at.session_state["flight_telemetry_project"] = [0, "", "", "", "", "", 1]
        at.session_state["flight_telemetry_project__venv_map"] = {}
        at.session_state["_requested_lab_dir"] = "flight_telemetry_project"
        at.session_state["lab_dir_selectbox"] = "flight_telemetry_project"
        at.session_state["lab_dir"] = "flight_telemetry_project"
        at.run()
        assert not at.exception

        delete_keys = [
            button.key
            for button in at.button
            if isinstance(button.key, str) and button.key.endswith("_delete_0")
        ]
        assert delete_keys
        safe_prefix = delete_keys[0].removesuffix("_delete_0")
        at.button(key=f"{safe_prefix}_delete_0").click().run()
        assert not at.exception
        assert any(button.key == f"{safe_prefix}_delete_cancel_0" for button in at.button)

        at.button(key=f"{safe_prefix}_delete_cancel_0").click().run()
        assert not at.exception
        assert at.text_area(key=f"{safe_prefix}_q_stage_0").value == "demo prompt"
        confirm_state_key = f"{safe_prefix}_confirm_delete_0"
        assert not at.session_state.filtered_state.get(confirm_state_key, False)


def test_experiment_page_lab_switch_refreshes_in_virgin_session(mock_ui_env, tmp_path):
    """Switching labs on first use should immediately load the selected lab."""
    export_root = tmp_path / "export"
    flight_lab = export_root / "flight_telemetry_project"
    trainer_lab = export_root / "sb3_trainer_project"
    flight_lab.mkdir(parents=True, exist_ok=True)
    trainer_lab.mkdir(parents=True, exist_ok=True)
    (flight_lab / "lab_stages.toml").write_text(
        '[[flight_telemetry_project]]\nD = ""\nQ = "flight prompt"\nM = "dummy-model"\nC = "print(1)"\nR = "runpy"\n',
        encoding="utf-8",
    )
    (trainer_lab / "lab_stages.toml").write_text(
        '[[sb3_trainer_project]]\nD = ""\nQ = "trainer prompt"\nM = "dummy-model"\nC = "print(2)"\nR = "runpy"\n',
        encoding="utf-8",
    )

    with patch.dict(os.environ, {"AGI_EXPORT_DIR": str(export_root)}, clear=False):
        at = _app_test("src/agilab/pages/3_WORKFLOW.py", default_timeout=20)
        env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_telemetry_project", verbose=0)
        env.init_done = True
        env.AGILAB_EXPORT_ABS = export_root
        env.envars["AGI_EXPORT_DIR"] = str(export_root)
        env.target = "flight_telemetry_project"
        env.st_resources = (Path(__file__).resolve().parents[1] / "src/agilab/resources").resolve()
        env.get_projects = MagicMock(return_value=["flight_telemetry_project", "sb3_trainer_project"])

        at.session_state["env"] = env
        at.run()
        assert not at.exception
        assert all(text_input.key != "project_filter" for text_input in at.sidebar.text_input)
        assert [selectbox.label for selectbox in at.sidebar.selectbox][0] == "Project"
        assert "Runtime diagnostics" not in _element_labels(at.sidebar)
        assert "Diagnostics level" not in _element_labels(at.sidebar)
        project_select = at.sidebar.selectbox(key="project_selectbox")
        assert project_select.label == "Project"
        assert "Type in the dropdown to search." in str(project_select.help)
        sidebar_markdown = "\n".join(str(item.value) for item in at.sidebar.markdown)
        sidebar_caption = "\n".join(str(item.value) for item in at.sidebar.caption)
        assert "### Active project" not in sidebar_markdown
        assert "Choose the project workspace whose workflow stages and artifacts are shown below." not in sidebar_caption
        assert "Inspect experiment runs separately from workflow execution." not in sidebar_caption
        assert "Start it from Edit." not in sidebar_caption
        assert "MLflow" not in sidebar_markdown
        assert list(project_select.options) == ["flight_telemetry_project", "sb3_trainer_project"]
        assert at.session_state["lab_dir_selectbox"] == project_select.value
        markdown_text = "\n".join(str(item.value) for item in at.markdown)
        assert "Workflow stages" in markdown_text
        assert "agilab-header-value agilab-header-value--ready'>1/1</div>" in markdown_text
        assert "Workflow graph" in markdown_text
        assert "stages / dependencies" in markdown_text

        initial_lab = at.session_state["lab_dir_selectbox"]
        target_lab = (
            "sb3_trainer_project"
            if initial_lab != "sb3_trainer_project"
            else "flight_telemetry_project"
        )
        expected_prompt = "trainer prompt" if target_lab == "sb3_trainer_project" else "flight prompt"

        at.sidebar.selectbox(key="project_selectbox").set_value(target_lab).run()

        assert not at.exception
        assert at.session_state["project_selectbox"] == target_lab
        assert at.session_state["lab_dir_selectbox"] == target_lab
        assert Path(at.session_state["stages_file"]).parent.name == target_lab
        assert Path(str(at.session_state["index_page"])).parts[0] == target_lab
        assert at.text_area(key=f"{target_lab}_lab_stages.toml_q_stage_0").value == expected_prompt


def test_pipeline_page_project_selectbox_replaces_filter_and_switches_projects(mock_ui_env, tmp_path):
    export_root = tmp_path / "export"
    flight_lab = export_root / "flight_telemetry_project"
    trainer_lab = export_root / "sb3_trainer_project"
    flight_lab.mkdir(parents=True, exist_ok=True)
    trainer_lab.mkdir(parents=True, exist_ok=True)
    (flight_lab / "lab_stages.toml").write_text(
        '[[flight_telemetry_project]]\nD = ""\nQ = "flight prompt"\nM = "dummy-model"\nC = "print(1)"\nR = "runpy"\n',
        encoding="utf-8",
    )
    (trainer_lab / "lab_stages.toml").write_text(
        '[[sb3_trainer_project]]\nD = ""\nQ = "trainer prompt"\nM = "dummy-model"\nC = "print(2)"\nR = "runpy"\n',
        encoding="utf-8",
    )

    with patch.dict(os.environ, {"AGI_EXPORT_DIR": str(export_root)}, clear=False):
        at = _app_test("src/agilab/pages/3_WORKFLOW.py", default_timeout=20)
        env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_telemetry_project", verbose=0)
        env.init_done = True
        env.AGILAB_EXPORT_ABS = export_root
        env.envars["AGI_EXPORT_DIR"] = str(export_root)
        env.target = "flight_telemetry_project"
        env.st_resources = (Path(__file__).resolve().parents[1] / "src/agilab/resources").resolve()
        env.get_projects = MagicMock(return_value=["flight_telemetry_project", "sb3_trainer_project"])

        at.session_state["env"] = env
        at.run()
        assert not at.exception

        assert all(text_input.key != "project_filter" for text_input in at.sidebar.text_input)
        project_select = at.sidebar.selectbox(key="project_selectbox")
        assert project_select.label == "Project"
        assert list(project_select.options) == ["flight_telemetry_project", "sb3_trainer_project"]

        project_select.set_value("sb3_trainer_project").run()

        assert not at.exception
        assert at.session_state["project_selectbox"] == "sb3_trainer_project"
        assert at.session_state["lab_dir_selectbox"] == "sb3_trainer_project"
        assert Path(at.session_state["stages_file"]).parent.name == "sb3_trainer_project"


def test_pipeline_page_project_selectbox_uses_canonical_project_names(mock_ui_env, tmp_path):
    export_root = tmp_path / "export"
    flight_lab = export_root / "flight_telemetry_project"
    trainer_lab = export_root / "sb3_trainer_project"
    flight_lab.mkdir(parents=True, exist_ok=True)
    trainer_lab.mkdir(parents=True, exist_ok=True)
    (flight_lab / "lab_stages.toml").write_text(
        '[[flight_telemetry_project]]\nD = ""\nQ = "flight prompt"\nM = "dummy-model"\nC = "print(1)"\nR = "runpy"\n',
        encoding="utf-8",
    )
    (trainer_lab / "lab_stages.toml").write_text(
        '[[sb3_trainer_project]]\nD = ""\nQ = "trainer prompt"\nM = "dummy-model"\nC = "print(2)"\nR = "runpy"\n',
        encoding="utf-8",
    )

    with patch.dict(os.environ, {"AGI_EXPORT_DIR": str(export_root)}, clear=False):
        at = _app_test("src/agilab/pages/3_WORKFLOW.py", default_timeout=20)
        env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_telemetry_project", verbose=0)
        env.init_done = True
        env.AGILAB_EXPORT_ABS = export_root
        env.envars["AGI_EXPORT_DIR"] = str(export_root)
        env.target = "flight"
        env.st_resources = (Path(__file__).resolve().parents[1] / "src/agilab/resources").resolve()
        env.get_projects = MagicMock(return_value=["flight_telemetry_project", "sb3_trainer_project"])

        at.session_state["env"] = env
        at.run()
        assert not at.exception

        project_select = at.sidebar.selectbox(key="project_selectbox")
        assert list(project_select.options) == ["flight_telemetry_project", "sb3_trainer_project"]
        assert "flight" not in project_select.options
        assert at.session_state["lab_dir_selectbox"] == "flight_telemetry_project"
        assert Path(at.session_state["stages_file"]).parent.name == "flight_telemetry_project"


def test_pipeline_page_reuses_cross_page_project_selectbox_state(mock_ui_env, tmp_path):
    export_root = tmp_path / "export"
    flight_lab = export_root / "flight_telemetry_project"
    trainer_lab = export_root / "sb3_trainer_project"
    flight_lab.mkdir(parents=True, exist_ok=True)
    trainer_lab.mkdir(parents=True, exist_ok=True)
    (flight_lab / "lab_stages.toml").write_text(
        '[[flight_telemetry_project]]\nD = ""\nQ = "flight prompt"\nM = "dummy-model"\nC = "print(1)"\nR = "runpy"\n',
        encoding="utf-8",
    )
    (trainer_lab / "lab_stages.toml").write_text(
        '[[sb3_trainer_project]]\nD = ""\nQ = "trainer prompt"\nM = "dummy-model"\nC = "print(2)"\nR = "runpy"\n',
        encoding="utf-8",
    )

    with patch.dict(os.environ, {"AGI_EXPORT_DIR": str(export_root)}, clear=False):
        at = _app_test("src/agilab/pages/3_WORKFLOW.py", default_timeout=20)
        env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_telemetry_project", verbose=0)
        env.init_done = True
        env.AGILAB_EXPORT_ABS = export_root
        env.envars["AGI_EXPORT_DIR"] = str(export_root)
        env.target = "flight_telemetry_project"
        env.st_resources = (Path(__file__).resolve().parents[1] / "src/agilab/resources").resolve()
        env.get_projects = MagicMock(return_value=["flight_telemetry_project", "sb3_trainer_project"])

        at.session_state["env"] = env
        at.session_state["project_selectbox"] = "sb3_trainer_project"
        at.run()
        assert not at.exception

        project_select = at.sidebar.selectbox(key="project_selectbox")
        assert project_select.value == "sb3_trainer_project"
        assert at.session_state["lab_dir_selectbox"] == "sb3_trainer_project"
        assert Path(at.session_state["stages_file"]).parent.name == "sb3_trainer_project"


def test_experiment_page_save_stage_persists_prompt(mock_ui_env, tmp_path):
    export_root = tmp_path / "export"
    lab_dir = export_root / "flight_telemetry_project"
    lab_dir.mkdir(parents=True, exist_ok=True)
    stages_file = lab_dir / "lab_stages.toml"
    stages_file.write_text(
        '[[flight_telemetry_project]]\nD = ""\nQ = "original prompt"\nM = "dummy-model"\nC = "print(1)"\nR = "runpy"\n',
        encoding="utf-8",
    )

    with patch.dict(os.environ, {"AGI_EXPORT_DIR": str(export_root)}, clear=False):
        at = _app_test("src/agilab/pages/3_WORKFLOW.py", default_timeout=20)
        env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_telemetry_project", verbose=0)
        env.init_done = True
        env.AGILAB_EXPORT_ABS = export_root
        env.envars["AGI_EXPORT_DIR"] = str(export_root)
        env.target = "flight_telemetry_project"
        env.st_resources = (Path(__file__).resolve().parents[1] / "src/agilab/resources").resolve()
        env.get_projects = MagicMock(return_value=["flight_telemetry_project"])

        at.session_state["env"] = env
        at.run()
        assert not at.exception

        updated_prompt = "updated prompt from AppTest"
        at.session_state["flight_telemetry_project_lab_stages.toml_q_stage_0"] = updated_prompt
        at.run()
        at.button(key="flight_telemetry_project_lab_stages.toml_save_0").click().run()

        assert not at.exception
        assert updated_prompt in stages_file.read_text(encoding="utf-8")
        assert at.text_area(key="flight_telemetry_project_lab_stages.toml_q_stage_0").value == updated_prompt


def test_experiment_page_confirm_remove_updates_stages_file(mock_ui_env, tmp_path):
    export_root = tmp_path / "export"
    lab_dir = export_root / "flight_telemetry_project"
    lab_dir.mkdir(parents=True, exist_ok=True)
    stages_file = lab_dir / "lab_stages.toml"
    stages_file.write_text(
        """
[[flight_telemetry_project]]
D = ""
Q = "first prompt"
M = "dummy-model"
C = "print(1)"
R = "runpy"
[[flight_telemetry_project]]
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
        at = _app_test("src/agilab/pages/3_WORKFLOW.py", default_timeout=20)
        env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_telemetry_project", verbose=0)
        env.init_done = True
        env.AGILAB_EXPORT_ABS = export_root
        env.envars["AGI_EXPORT_DIR"] = str(export_root)
        env.target = "flight_telemetry_project"
        env.st_resources = (Path(__file__).resolve().parents[1] / "src/agilab/resources").resolve()
        env.get_projects = MagicMock(return_value=["flight_telemetry_project"])

        at.session_state["env"] = env
        at.run()
        assert not at.exception

        at.button(key="flight_telemetry_project_lab_stages.toml_delete_0").click().run()
        assert not at.exception
        assert any(button.key == "flight_telemetry_project_lab_stages.toml_delete_confirm_0" for button in at.button)

        at.button(key="flight_telemetry_project_lab_stages.toml_delete_confirm_0").click().run()
        assert not at.exception

        stored = stages_file.read_text(encoding="utf-8")
        assert "first prompt" not in stored
        assert "second prompt" in stored


def test_edit_page_project_selectbox(mock_ui_env):
    """Test that the EDIT page has a project selectbox with available projects."""
    at = _app_test("src/agilab/pages/1_PROJECT.py")
    env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_telemetry_project", verbose=0)
    env.init_done = True
    env.st_resources = (Path(__file__).resolve().parents[1] / "src/agilab/resources").resolve()
    env.projects = ["flight_telemetry_project"]
    env.get_projects = MagicMock(return_value=["flight_telemetry_project"])
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
    assert "project_selectbox__edit" not in [button.key for button in at.sidebar.button]
    assert "project_filter" not in [ti.key for ti in at.sidebar.text_input]


def test_create_page_exposes_environment_strategy(mock_ui_env):
    at = _app_test("src/agilab/pages/1_PROJECT.py")
    env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_telemetry_project", verbose=0)
    env.init_done = True
    env.st_resources = (Path(__file__).resolve().parents[1] / "src/agilab/resources").resolve()
    env.projects = ["flight_telemetry_project"]
    env.get_projects = MagicMock(return_value=["flight_telemetry_project"])
    at.session_state["env"] = env
    at.session_state["sidebar_selection"] = "Create"

    at.run()
    assert not at.exception

    assert "clone_env_strategy" in at.session_state
    assert at.session_state["clone_env_strategy"] in {"share_source_venv", "detach_venv"}
    sidebar_captions = "\n".join(str(item.value) for item in at.sidebar.caption)
    assert "Fast and lightweight." not in sidebar_captions
    assert "Safer for real development." not in sidebar_captions


def test_project_page_maps_legacy_clone_action_to_create(mock_ui_env):
    at = _app_test("src/agilab/pages/1_PROJECT.py")
    env = AgiEnv(apps_path=mock_ui_env["apps_dir"], app="flight_telemetry_project", verbose=0)
    env.init_done = True
    env.st_resources = (Path(__file__).resolve().parents[1] / "src/agilab/resources").resolve()
    env.projects = ["flight_telemetry_project"]
    env.get_projects = MagicMock(return_value=["flight_telemetry_project"])
    at.session_state["env"] = env
    at.session_state["sidebar_selection"] = "Clone"

    at.run()
    assert not at.exception

    assert at.session_state["sidebar_selection"] == "Create"
    assert "clone_env_strategy" in at.session_state
