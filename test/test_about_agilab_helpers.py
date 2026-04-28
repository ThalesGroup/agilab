from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "agilab" / "About_agilab.py"
SPEC = importlib.util.spec_from_file_location("agilab_about_helpers", MODULE_PATH)
assert SPEC and SPEC.loader
about_agilab = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(about_agilab)

PAGE_BOOTSTRAP_PATH = Path(__file__).resolve().parents[1] / "src" / "agilab" / "page_bootstrap.py"
PAGE_BOOTSTRAP_SPEC = importlib.util.spec_from_file_location(
    "agilab_page_bootstrap_helpers",
    PAGE_BOOTSTRAP_PATH,
)
assert PAGE_BOOTSTRAP_SPEC and PAGE_BOOTSTRAP_SPEC.loader
page_bootstrap = importlib.util.module_from_spec(PAGE_BOOTSTRAP_SPEC)
PAGE_BOOTSTRAP_SPEC.loader.exec_module(page_bootstrap)


class _BrokenTemplatePath:
    def read_text(self, encoding: str = "utf-8") -> str:  # pragma: no cover - called by test
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")


class _FakeExpander:
    def __init__(self, streamlit, label: str):
        self._streamlit = streamlit
        self._label = label

    def __enter__(self):
        self._streamlit.events.append(("enter_expander", self._label))
        return self

    def __exit__(self, exc_type, exc, tb):
        self._streamlit.events.append(("exit_expander", self._label))
        return False


class _FakeSidebar:
    def __init__(self, streamlit):
        self._streamlit = streamlit

    def caption(self, body: object):
        self._streamlit.events.append(("sidebar.caption", str(body)))

    def markdown(self, body: object, **_kwargs):
        self._streamlit.events.append(("sidebar.markdown", str(body)))


class _FakeStreamlit:
    def __init__(self):
        self.events: list[tuple[str, str]] = []
        self.session_state: dict[str, object] = {}
        self.query_params: dict[str, object] = {}
        self.stopped = False
        self.sidebar = _FakeSidebar(self)

    def expander(self, label: str, expanded: bool = False):
        self.events.append(("expander", f"{label}:{expanded}"))
        return _FakeExpander(self, label)

    def write(self, body: object):
        self.events.append(("write", str(body)))

    def caption(self, body: object):
        self.events.append(("caption", str(body)))

    def info(self, body: object, **_kwargs):
        self.events.append(("info", str(body)))

    def warning(self, body: object, **_kwargs):
        self.events.append(("warning", str(body)))

    def success(self, body: object, **_kwargs):
        self.events.append(("success", str(body)))

    def error(self, body: object, **_kwargs):
        self.events.append(("error", str(body)))

    def markdown(self, body: object, **_kwargs):
        self.events.append(("markdown", str(body)))

    def code(self, body: object, **_kwargs):
        self.events.append(("code", str(body)))

    def divider(self):
        self.events.append(("divider", ""))

    def button(self, label: str, **_kwargs):
        self.events.append(("button", label))
        return False

    def rerun(self):  # pragma: no cover - button is false in these tests
        raise AssertionError("rerun should not be called")

    def stop(self):
        self.stopped = True


def _make_bootstrap_ports(
    agi_env_cls: object,
    *,
    services_enabled: bool = False,
    last_app: object = None,
    environ: dict[str, str] | None = None,
):
    bootstrap = about_agilab._about_bootstrap
    calls = SimpleNamespace(activated=[], stored=[])
    ports = bootstrap.BootstrapPorts(
        agi_env_cls=agi_env_cls,
        activate_mlflow=calls.activated.append,
        background_services_enabled=lambda: services_enabled,
        load_last_active_app=lambda: last_app,
        store_last_active_app=calls.stored.append,
        environ=environ if environ is not None else {},
    )
    return ports, calls


def _event_index(events: list[tuple[str, str]], kind: str, text: str) -> int:
    return next(
        index
        for index, (event_kind, body) in enumerate(events)
        if event_kind == kind and text in body
    )


def test_page_bootstrap_session_env_ready_handles_missing_and_init_flags():
    env = SimpleNamespace()

    assert page_bootstrap.session_env_ready({}) is False
    assert page_bootstrap.session_env_ready({"env": env}) is True
    assert page_bootstrap.session_env_ready({"env": env}, init_done_default=False) is False
    env.init_done = False
    assert page_bootstrap.session_env_ready({"env": env}) is False
    env.init_done = True
    assert page_bootstrap.session_env_ready({"env": env}) is True


def test_page_bootstrap_load_about_page_module_uses_injected_loader(tmp_path):
    current_file = tmp_path / "agilab" / "pages" / "page.py"
    current_file.parent.mkdir(parents=True)
    imported = SimpleNamespace(main=lambda: None)
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def fake_load_module(*args, **kwargs):
        calls.append((args, kwargs))
        return imported

    result = page_bootstrap.load_about_page_module(current_file, load_module=fake_load_module)

    assert result is imported
    assert calls[0][0] == ("agilab.About_agilab",)
    assert calls[0][1]["current_file"] == current_file
    assert calls[0][1]["fallback_path"] == current_file.parents[1] / "About_agilab.py"


def test_page_bootstrap_load_about_page_module_falls_back_to_file(tmp_path, monkeypatch):
    current_file = tmp_path / "agilab" / "pages" / "page.py"
    about_file = tmp_path / "agilab" / "About_agilab.py"
    current_file.parent.mkdir(parents=True)
    about_file.write_text("def main():\n    return 'ok'\n", encoding="utf-8")

    def raise_import(_name):
        raise ModuleNotFoundError("missing")

    monkeypatch.setattr(page_bootstrap.importlib, "import_module", raise_import)

    result = page_bootstrap.load_about_page_module(current_file)

    assert result.main() == "ok"


def test_page_bootstrap_load_about_page_module_returns_imported_module(monkeypatch):
    imported = SimpleNamespace(main=lambda: "ok")

    monkeypatch.setattr(page_bootstrap.importlib, "import_module", lambda _name: imported)

    assert page_bootstrap.load_about_page_module(__file__) is imported


def test_page_bootstrap_load_about_page_module_falls_back_when_import_lacks_main(
    tmp_path,
    monkeypatch,
):
    current_file = tmp_path / "agilab" / "pages" / "page.py"
    about_file = tmp_path / "agilab" / "About_agilab.py"
    current_file.parent.mkdir(parents=True)
    about_file.write_text("def main():\n    return 'fallback'\n", encoding="utf-8")

    monkeypatch.setattr(
        page_bootstrap.importlib,
        "import_module",
        lambda _name: SimpleNamespace(),
    )

    result = page_bootstrap.load_about_page_module(current_file)

    assert result.main() == "fallback"


def test_page_bootstrap_load_about_page_module_reports_missing_fallback_spec(tmp_path, monkeypatch):
    current_file = tmp_path / "agilab" / "pages" / "page.py"
    current_file.parent.mkdir(parents=True)

    monkeypatch.setattr(
        page_bootstrap.importlib,
        "import_module",
        lambda _name: (_ for _ in ()).throw(ModuleNotFoundError("missing")),
    )
    monkeypatch.setattr(page_bootstrap.importlib.util, "spec_from_file_location", lambda *_args: None)

    with pytest.raises(ModuleNotFoundError, match="Unable to load About_agilab"):
        page_bootstrap.load_about_page_module(current_file)


def test_page_bootstrap_load_about_page_module_rejects_fallback_without_main(tmp_path, monkeypatch):
    current_file = tmp_path / "agilab" / "pages" / "page.py"
    about_file = tmp_path / "agilab" / "About_agilab.py"
    current_file.parent.mkdir(parents=True)
    about_file.write_text("VALUE = 1\n", encoding="utf-8")

    monkeypatch.setattr(
        page_bootstrap.importlib,
        "import_module",
        lambda _name: (_ for _ in ()).throw(ImportError("missing")),
    )

    with pytest.raises(ModuleNotFoundError, match="Unable to import About_agilab"):
        page_bootstrap.load_about_page_module(current_file)


def test_page_bootstrap_ensure_page_env_returns_ready_env():
    env = SimpleNamespace(init_done=True)
    fake_st = SimpleNamespace(
        session_state={"env": env},
        rerun=lambda: (_ for _ in ()).throw(AssertionError("rerun should not be called")),
    )

    assert page_bootstrap.ensure_page_env(fake_st, __file__) is env


def test_page_bootstrap_ensure_page_env_delegates_cold_start(tmp_path):
    current_file = tmp_path / "agilab" / "pages" / "page.py"
    current_file.parent.mkdir(parents=True)
    events: list[str] = []
    fake_st = SimpleNamespace(
        session_state={},
        rerun=lambda: events.append("rerun"),
    )

    def fake_load_module(*_args, **_kwargs):
        return SimpleNamespace(main=lambda: events.append("main"))

    result = page_bootstrap.ensure_page_env(
        fake_st,
        current_file,
        load_module=fake_load_module,
    )

    assert result is None
    assert events == ["main", "rerun"]


def test_ensure_env_file_falls_back_to_touch_when_template_read_fails(tmp_path, monkeypatch):
    env_file = tmp_path / ".agilab" / ".env"
    monkeypatch.setattr(about_agilab, "TEMPLATE_ENV_PATH", _BrokenTemplatePath())

    result = about_agilab._ensure_env_file(env_file)

    assert result == env_file
    assert env_file.exists()
    assert env_file.read_text(encoding="utf-8") == ""


def test_refresh_env_from_file_updates_env_map_and_apps_path(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    apps_dir = tmp_path / "apps"
    apps_dir.mkdir()
    env_file.write_text(
        "\n".join(
            [
                "OPENAI_MODEL=gpt-5.4",
                f"APPS_PATH={apps_dir}",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(about_agilab, "ENV_FILE_PATH", env_file)
    about_agilab.st.session_state.pop("env_file_mtime_ns", None)

    env = SimpleNamespace(
        envars={},
        apps_path="old/path",
    )

    about_agilab._refresh_env_from_file(env)

    assert env.envars["OPENAI_MODEL"] == "gpt-5.4"
    assert env.envars["APPS_PATH"] == str(apps_dir)
    assert env.apps_path == apps_dir.resolve()
    assert about_agilab.st.session_state["env_file_mtime_ns"] == env_file.stat().st_mtime_ns


def test_refresh_env_from_file_ignores_bad_envars_mapping(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_MODEL=gpt-5.4\n", encoding="utf-8")
    monkeypatch.setattr(about_agilab, "ENV_FILE_PATH", env_file)
    about_agilab.st.session_state.pop("env_file_mtime_ns", None)

    env = SimpleNamespace(
        envars=object(),
        apps_path="old/path",
    )

    about_agilab._refresh_env_from_file(env)

    assert about_agilab.st.session_state["env_file_mtime_ns"] == env_file.stat().st_mtime_ns


def test_refresh_env_from_file_keeps_runtime_cluster_credentials_when_sentinel(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("CLUSTER_CREDENTIALS=__KEYRING__\n", encoding="utf-8")
    monkeypatch.setattr(about_agilab, "ENV_FILE_PATH", env_file)
    monkeypatch.setenv("CLUSTER_CREDENTIALS", "runtime:user")
    about_agilab.st.session_state.pop("env_file_mtime_ns", None)

    env = SimpleNamespace(
        envars={},
        apps_path="old/path",
    )

    about_agilab._refresh_env_from_file(env)

    assert env.envars["CLUSTER_CREDENTIALS"] == "runtime:user"


def test_bootstrap_resolve_apps_path_prefers_cli_then_env(tmp_path):
    cli_apps = tmp_path / "cli_apps"
    env_apps = tmp_path / "env_apps"
    bootstrap = about_agilab._about_bootstrap

    args = bootstrap.parse_startup_args(["--apps-path", str(cli_apps)])
    assert bootstrap.resolve_apps_path(
        args,
        env_file_path=tmp_path / ".env",
        load_env_file_map=lambda _path: {"APPS_PATH": str(env_apps)},
    ) == cli_apps

    args = bootstrap.parse_startup_args([])
    assert bootstrap.resolve_apps_path(
        args,
        env_file_path=tmp_path / ".env",
        load_env_file_map=lambda _path: {"APPS_PATH": str(env_apps)},
    ) == env_apps


def test_bootstrap_resolve_apps_path_from_agilab_path_file(tmp_path):
    bootstrap = about_agilab._about_bootstrap
    install_root = tmp_path / "agi-space"
    marker = tmp_path / ".agilab-path"
    marker.write_text(str(install_root / ".venv" / "bin" / "python"), encoding="utf-8")

    assert bootstrap.apps_path_from_agilab_path_file(marker) == (install_root / "apps").resolve(
        strict=False
    )


def test_bootstrap_apps_path_from_agilab_path_file_reports_resolve_error(tmp_path, monkeypatch):
    bootstrap = about_agilab._about_bootstrap
    marker = tmp_path / ".agilab-path"
    marker.write_text(str(tmp_path / "agi-space" / ".venv" / "bin" / "python"), encoding="utf-8")

    class BrokenPath:
        def __init__(self, value):
            self.value = value

        def resolve(self, *, strict=False):
            raise OSError(f"cannot resolve {self.value}")

    monkeypatch.setattr(bootstrap, "Path", BrokenPath)

    with pytest.raises(ValueError, match="Cannot resolve apps path"):
        bootstrap.apps_path_from_agilab_path_file(marker)


def test_bootstrap_default_agilab_path_file_uses_platform_locations(tmp_path):
    bootstrap = about_agilab._about_bootstrap

    assert bootstrap.default_agilab_path_file(home_path=tmp_path) == (
        tmp_path / ".local/share/agilab/.agilab-path"
    )
    assert bootstrap.default_agilab_path_file(
        os_name="nt",
        environ={"LOCALAPPDATA": str(tmp_path / "localappdata")},
        home_path=tmp_path,
    ) == tmp_path / "localappdata" / "agilab/.agilab-path"


def test_bootstrap_active_app_helpers_resolve_and_switch_project(tmp_path):
    bootstrap = about_agilab._about_bootstrap
    apps_path = tmp_path / "apps"
    project_path = apps_path / "flight_project"
    project_path.mkdir(parents=True)
    warnings: list[str] = []

    class FakeEnv:
        def __init__(self):
            self.apps_path = apps_path
            self.app = "default"
            self.projects = {"flight_project"}

        def change_app(self, path: Path) -> None:
            assert path == project_path.resolve()
            self.app = path.name

    fake_st = SimpleNamespace(warning=warnings.append)
    env = FakeEnv()

    assert bootstrap.normalize_active_app_input(env, "flight_project") == project_path.resolve()
    assert bootstrap.apply_active_app_request(env, "flight_project", streamlit=fake_st) is True
    assert env.app == "flight_project"
    assert warnings == []


def test_bootstrap_normalize_active_app_input_skips_unresolvable_candidate(
    tmp_path,
    monkeypatch,
):
    bootstrap = about_agilab._about_bootstrap
    broken_path = tmp_path / "broken_project"
    original_resolve = bootstrap.Path.resolve

    def fake_resolve(self, *args, **kwargs):
        if self == broken_path:
            raise OSError("cannot resolve candidate")
        return original_resolve(self, *args, **kwargs)

    env = SimpleNamespace(apps_path=tmp_path / "apps", projects=set())
    monkeypatch.setattr(bootstrap.Path, "resolve", fake_resolve)

    assert bootstrap.normalize_active_app_input(env, str(broken_path)) is None


def test_bootstrap_persist_env_preserves_saved_and_writes_missing(tmp_path):
    calls: list[tuple[str, str]] = []
    stored_credentials: list[str] = []
    bootstrap = about_agilab._about_bootstrap

    class FakeAgiEnv:
        @staticmethod
        def set_env_var(key: str, value: str) -> None:
            calls.append((key, value))

    def fake_store_cluster_credentials(value: str, **_kwargs) -> bool:
        stored_credentials.append(value)
        return True

    env = SimpleNamespace(
        OPENAI_API_KEY="sk-" + "a" * 16,
        CLUSTER_CREDENTIALS="cluster:user",
        is_source_env=True,
        is_worker_env=False,
        envars={},
    )
    environ: dict[str, str] = {}
    apps_path = tmp_path / "apps"

    openai_missing = bootstrap.persist_bootstrap_env(
        env,
        apps_path=apps_path,
        explicit_apps_path=True,
        saved_env={"OPENAI_API_KEY": "existing"},
        agi_env_cls=FakeAgiEnv,
        clean_openai_key=lambda value: value,
        store_cluster_credentials=fake_store_cluster_credentials,
        environ=environ,
    )

    assert openai_missing is False
    assert environ["OPENAI_API_KEY"] == env.OPENAI_API_KEY
    assert environ[bootstrap.CLUSTER_CREDENTIALS_KEY] == "cluster:user"
    assert env.envars[bootstrap.CLUSTER_CREDENTIALS_KEY] == "cluster:user"
    assert stored_credentials == ["cluster:user"]
    assert ("OPENAI_API_KEY", env.OPENAI_API_KEY) not in calls
    assert (bootstrap.CLUSTER_CREDENTIALS_KEY, bootstrap.KEYRING_SENTINEL) in calls
    assert ("IS_SOURCE_ENV", "1") in calls
    assert ("IS_WORKER_ENV", "0") in calls
    assert ("APPS_PATH", str(apps_path)) in calls


def test_bootstrap_persist_env_keeps_saved_cluster_credentials(tmp_path):
    calls: list[tuple[str, str]] = []
    stored_credentials: list[str] = []
    bootstrap = about_agilab._about_bootstrap

    class FakeAgiEnv:
        @staticmethod
        def set_env_var(key: str, value: str) -> None:
            calls.append((key, value))

    env = SimpleNamespace(
        OPENAI_API_KEY="",
        CLUSTER_CREDENTIALS="cluster:user",
        is_source_env=False,
        is_worker_env=True,
        envars={},
    )

    openai_missing = bootstrap.persist_bootstrap_env(
        env,
        apps_path=tmp_path / "apps",
        explicit_apps_path=False,
        saved_env={bootstrap.CLUSTER_CREDENTIALS_KEY: bootstrap.KEYRING_SENTINEL},
        agi_env_cls=FakeAgiEnv,
        clean_openai_key=lambda value: value,
        store_cluster_credentials=lambda value, **_kwargs: stored_credentials.append(value) or True,
        environ={},
    )

    assert openai_missing is True
    assert stored_credentials == []
    assert (bootstrap.CLUSTER_CREDENTIALS_KEY, bootstrap.KEYRING_SENTINEL) not in calls


def test_bootstrap_stop_startup_with_error_renders_and_stops():
    bootstrap = about_agilab._about_bootstrap
    events: list[tuple[str, str]] = []

    fake_st = SimpleNamespace(
        error=lambda message: events.append(("error", message)),
        stop=lambda: events.append(("stop", "")),
    )

    bootstrap.stop_startup_with_error(fake_st, "bad startup")

    assert events == [("error", "bad startup"), ("stop", "")]


def test_bootstrap_stop_startup_with_error_allows_missing_stop():
    bootstrap = about_agilab._about_bootstrap
    events: list[str] = []
    fake_st = SimpleNamespace(error=events.append)

    bootstrap.stop_startup_with_error(fake_st, "bad startup")

    assert events == ["bad startup"]


def test_bootstrap_sync_active_app_from_query_updates_query_and_store(tmp_path):
    bootstrap = about_agilab._about_bootstrap
    apps_path = tmp_path / "apps"
    apps_path.mkdir()
    env = SimpleNamespace(apps_path=apps_path, app="default")
    fake_st = SimpleNamespace(query_params={"active_app": "target"})
    stored_paths: list[Path] = []

    def fake_apply_request(target_env, request_value):
        assert target_env is env
        assert request_value == "target"
        target_env.app = "target"
        return True

    bootstrap.sync_active_app_from_query(
        env,
        streamlit=fake_st,
        store_last_active_app=stored_paths.append,
        apply_request=fake_apply_request,
    )

    assert fake_st.query_params["active_app"] == "target"
    assert stored_paths == [apps_path / "target"]


def test_bootstrap_sync_active_app_from_query_keeps_matching_query(tmp_path):
    bootstrap = about_agilab._about_bootstrap
    env = SimpleNamespace(apps_path=tmp_path / "apps", app="target")
    fake_st = SimpleNamespace(query_params={"active_app": "target"})
    stored_paths: list[Path] = []

    bootstrap.sync_active_app_from_query(
        env,
        streamlit=fake_st,
        store_last_active_app=stored_paths.append,
        apply_request=lambda _env, _request_value: False,
    )

    assert fake_st.query_params == {"active_app": "target"}
    assert stored_paths == []


def test_bootstrap_page_environment_success_path(tmp_path, monkeypatch):
    import agi_env
    import agi_gui.pagelib as pagelib
    import agi_gui.ui_support as ui_support

    bootstrap = about_agilab._about_bootstrap
    apps_path = tmp_path / "apps"
    app_path = apps_path / "flight_project"
    app_path.mkdir(parents=True)
    fake_environ: dict[str, str] = {}
    set_env_calls: list[tuple[str, str]] = []
    remembered_apps: list[Path] = []
    refreshed_envs: list[object] = []

    class FakeAgiEnv:
        @staticmethod
        def set_env_var(key: str, value: str) -> None:
            set_env_calls.append((key, value))

        def __init__(self, *, apps_path: Path, verbose: int):
            self.apps_path = apps_path
            self.verbose = verbose
            self.app = "default"
            self.projects = {"flight_project"}
            self.is_source_env = True
            self.is_worker_env = False
            self.OPENAI_API_KEY = ""
            self.CLUSTER_CREDENTIALS = ""
            self.envars = {}
            self.init_done = False

    def fake_apply_active_app_request(env, request_value):
        assert request_value == str(app_path)
        env.app = "flight_project"
        return True

    fake_st = SimpleNamespace(
        session_state={},
        query_params={},
        warnings=[],
        warning=lambda message: fake_st.warnings.append(message),
        error=lambda _message: None,
    )
    monkeypatch.setattr(bootstrap.os, "environ", fake_environ)
    monkeypatch.setattr(agi_env, "AgiEnv", FakeAgiEnv)
    monkeypatch.setattr(pagelib, "activate_mlflow", lambda _env: None)
    monkeypatch.setattr(pagelib, "background_services_enabled", lambda: False)
    monkeypatch.setattr(ui_support, "load_last_active_app", lambda: app_path)
    monkeypatch.setattr(ui_support, "store_last_active_app", remembered_apps.append)

    result = bootstrap.bootstrap_page_environment(
        streamlit=fake_st,
        env_file_path=tmp_path / ".env",
        load_env_file_map=lambda _path: {"APPS_PATH": str(apps_path)},
        logger=None,
        apply_active_app_request=fake_apply_active_app_request,
        handle_data_root_failure=lambda _exc, **_kwargs: False,
        refresh_env_from_file=refreshed_envs.append,
        clean_openai_key=lambda value: value,
        store_cluster_credentials=lambda *_args, **_kwargs: True,
    )

    assert result.env is fake_st.session_state["env"]
    assert result.should_rerun is False
    assert result.handled_recovery is False
    assert result.env.init_done is True
    assert fake_st.session_state["first_run"] is False
    assert fake_st.query_params["active_app"] == "flight_project"
    assert remembered_apps == [apps_path / "flight_project"]
    assert refreshed_envs == [result.env]
    assert ("APPS_PATH", str(apps_path)) not in set_env_calls
    assert ("IS_SOURCE_ENV", "1") in set_env_calls
    assert "OPENAI_API_KEY not set" in fake_st.warnings[0]


def test_bootstrap_resolve_apps_path_rejects_empty_or_malformed_marker(tmp_path):
    bootstrap = about_agilab._about_bootstrap
    marker = tmp_path / ".agilab-path"
    marker.write_text("", encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        bootstrap.apps_path_from_agilab_path_file(marker)

    marker.write_text(str(tmp_path / "python"), encoding="utf-8")
    with pytest.raises(ValueError, match="missing .venv marker"):
        bootstrap.apps_path_from_agilab_path_file(marker)


def test_bootstrap_resolve_apps_path_uses_marker_when_env_has_placeholder(tmp_path):
    bootstrap = about_agilab._about_bootstrap
    install_root = tmp_path / "install-root"
    marker = tmp_path / ".local/share/agilab/.agilab-path"
    marker.parent.mkdir(parents=True)
    marker.write_text(str(install_root / ".venv" / "bin" / "python"), encoding="utf-8")

    args = bootstrap.parse_startup_args([])
    assert bootstrap.resolve_apps_path(
        args,
        env_file_path=tmp_path / ".env",
        load_env_file_map=lambda _path: {"APPS_PATH": "/path/to/apps"},
        home_path=tmp_path,
    ) == (install_root / "apps").resolve(strict=False)


def test_bootstrap_active_app_helpers_handle_empty_same_and_failed_switch(tmp_path):
    bootstrap = about_agilab._about_bootstrap
    apps_path = tmp_path / "apps"
    project_path = apps_path / "known"
    project_path.mkdir(parents=True)
    warnings: list[str] = []

    class FakeEnv:
        def __init__(self):
            self.apps_path = apps_path
            self.app = "known"
            self.projects = {"known"}

        def change_app(self, _path: Path) -> None:
            raise RuntimeError("should not switch same app")

    assert bootstrap.normalize_active_app_input(FakeEnv(), None) is None
    assert bootstrap.normalize_active_app_input(FakeEnv(), object()) is None
    assert bootstrap.normalize_active_app_input(FakeEnv(), str(project_path)) == project_path.resolve()
    assert bootstrap.normalize_active_app_input(FakeEnv(), "missing") is None
    assert not bootstrap.apply_active_app_request(
        FakeEnv(),
        "missing",
        streamlit=SimpleNamespace(warning=warnings.append),
    )
    assert not bootstrap.apply_active_app_request(
        FakeEnv(),
        "known",
        streamlit=SimpleNamespace(warning=warnings.append),
    )

    class BrokenEnv(FakeEnv):
        def __init__(self):
            super().__init__()
            self.app = "default"

        def change_app(self, _path: Path) -> None:
            raise RuntimeError("cannot switch")

    assert not bootstrap.apply_active_app_request(
        BrokenEnv(),
        "known",
        streamlit=SimpleNamespace(warning=warnings.append),
    )
    assert any("cannot switch" in warning for warning in warnings)


def test_bootstrap_persist_env_handles_plain_and_empty_cluster_credentials(tmp_path):
    bootstrap = about_agilab._about_bootstrap
    calls: list[tuple[str, str]] = []

    class FakeAgiEnv:
        @staticmethod
        def set_env_var(key: str, value: str) -> None:
            calls.append((key, value))

    plain_env = SimpleNamespace(
        OPENAI_API_KEY="",
        CLUSTER_CREDENTIALS="cluster:plain",
        is_source_env=False,
        is_worker_env=True,
        envars=object(),
    )
    environ: dict[str, str] = {}

    openai_missing = bootstrap.persist_bootstrap_env(
        plain_env,
        apps_path=tmp_path / "apps",
        explicit_apps_path=False,
        saved_env={},
        agi_env_cls=FakeAgiEnv,
        clean_openai_key=lambda value: value,
        store_cluster_credentials=lambda *_args, **_kwargs: False,
        environ=environ,
    )

    assert openai_missing is True
    assert environ[bootstrap.CLUSTER_CREDENTIALS_KEY] == "cluster:plain"
    assert (bootstrap.CLUSTER_CREDENTIALS_KEY, "cluster:plain") in calls
    assert ("IS_SOURCE_ENV", "0") in calls
    assert ("IS_WORKER_ENV", "1") in calls

    empty_env = SimpleNamespace(
        OPENAI_API_KEY=None,
        CLUSTER_CREDENTIALS="",
        is_source_env=False,
        is_worker_env=False,
        envars={},
    )
    assert bootstrap.persist_bootstrap_env(
        empty_env,
        apps_path=tmp_path / "apps",
        explicit_apps_path=False,
        saved_env={},
        agi_env_cls=FakeAgiEnv,
        clean_openai_key=lambda value: value,
        store_cluster_credentials=lambda *_args, **_kwargs: True,
        environ={},
    )
    assert (bootstrap.CLUSTER_CREDENTIALS_KEY, "") in calls


def test_bootstrap_sync_active_app_from_query_handles_missing_query_api(tmp_path):
    bootstrap = about_agilab._about_bootstrap

    class BrokenQueryStreamlit:
        @property
        def query_params(self):
            raise RuntimeError("query unavailable")

    stored_paths: list[Path] = []
    env = SimpleNamespace(apps_path=tmp_path, app="default")

    bootstrap.sync_active_app_from_query(
        env,
        streamlit=BrokenQueryStreamlit(),
        store_last_active_app=stored_paths.append,
        apply_request=lambda *_args: True,
    )

    assert stored_paths == []


def test_bootstrap_sync_active_app_from_query_handles_empty_list_and_store_error(tmp_path):
    bootstrap = about_agilab._about_bootstrap
    apps_path = tmp_path / "apps"
    env = SimpleNamespace(apps_path=apps_path, app="default")
    empty_query_st = SimpleNamespace(query_params={"active_app": []})

    bootstrap.sync_active_app_from_query(
        env,
        streamlit=empty_query_st,
        store_last_active_app=lambda _path: None,
        apply_request=lambda *_args: False,
    )

    assert empty_query_st.query_params["active_app"] == "default"

    requested_query_st = SimpleNamespace(query_params={"active_app": ["target"]})

    def apply_request(target_env, requested):
        target_env.app = requested
        return True

    bootstrap.sync_active_app_from_query(
        env,
        streamlit=requested_query_st,
        store_last_active_app=lambda _path: (_ for _ in ()).throw(RuntimeError("store failed")),
        apply_request=apply_request,
    )

    assert requested_query_st.query_params["active_app"] == "target"


def test_bootstrap_remember_active_app_ignores_store_errors(tmp_path):
    bootstrap = about_agilab._about_bootstrap
    env = SimpleNamespace(apps_path=tmp_path, app="demo")
    bootstrap.remember_active_app(env, lambda _path: (_ for _ in ()).throw(OSError("locked")))


def test_bootstrap_page_environment_uses_injected_ports_and_services(tmp_path):
    bootstrap = about_agilab._about_bootstrap
    apps_path = tmp_path / "apps"
    requested_apps: list[str | None] = []
    saved_values: list[tuple[str, str]] = []
    stored_credentials: list[str] = []

    class FakeAgiEnv:
        def __init__(self, *, apps_path: Path, verbose: int):
            self.apps_path = apps_path
            self.verbose = verbose
            self.app = "default"
            self.is_source_env = True
            self.is_worker_env = False
            self.OPENAI_API_KEY = ""
            self.CLUSTER_CREDENTIALS = ""
            self.envars: dict[str, str] = {}
            self.init_done = False

        @staticmethod
        def set_env_var(key: str, value: str) -> None:
            saved_values.append((key, value))

    def apply_request(env, requested):
        requested_apps.append(requested)
        if requested:
            env.app = Path(str(requested)).name
        return bool(requested)

    fake_st = _FakeStreamlit()
    ports, port_calls = _make_bootstrap_ports(
        FakeAgiEnv,
        services_enabled=True,
        last_app=apps_path / "remembered",
        environ={},
    )

    result = bootstrap.bootstrap_page_environment(
        streamlit=fake_st,
        env_file_path=tmp_path / ".env",
        load_env_file_map=lambda _path: {},
        logger=object(),
        apply_active_app_request=apply_request,
        handle_data_root_failure=lambda *_args, **_kwargs: False,
        refresh_env_from_file=lambda _env: (_ for _ in ()).throw(ValueError("stale env")),
        clean_openai_key=lambda value: value,
        store_cluster_credentials=lambda value, **_kwargs: stored_credentials.append(value) or True,
        argv=["--apps-path", str(apps_path)],
        ports=ports,
    )

    assert result.env is fake_st.session_state["env"]
    assert result.should_rerun is True
    assert result.handled_recovery is False
    assert result.env.init_done is True
    assert fake_st.session_state["apps_path"] == str(apps_path)
    assert fake_st.session_state["first_run"] is False
    assert fake_st.query_params["active_app"] == "remembered"
    assert requested_apps == [str(apps_path / "remembered")]
    assert port_calls.activated == [result.env]
    assert port_calls.stored == [apps_path / "remembered"]
    assert ("APPS_PATH", str(apps_path)) in saved_values
    assert any("OPENAI_API_KEY not set" in message for event, message in fake_st.events if event == "warning")


def test_bootstrap_page_environment_cli_active_app_overrides_last_app(tmp_path):
    bootstrap = about_agilab._about_bootstrap
    apps_path = tmp_path / "apps"
    requested_apps: list[str | None] = []

    class FakeAgiEnv:
        def __init__(self, *, apps_path: Path, verbose: int):
            self.apps_path = apps_path
            self.verbose = verbose
            self.app = "default"
            self.is_source_env = False
            self.is_worker_env = False
            self.OPENAI_API_KEY = "sk-" + "b" * 16
            self.CLUSTER_CREDENTIALS = ""
            self.envars = {}

        @staticmethod
        def set_env_var(_key: str, _value: str) -> None:
            return None

    def apply_request(env, requested):
        requested_apps.append(requested)
        env.app = Path(str(requested)).name
        return True

    fake_st = _FakeStreamlit()
    ports, port_calls = _make_bootstrap_ports(FakeAgiEnv, services_enabled=False, last_app="remembered")

    result = bootstrap.bootstrap_page_environment(
        streamlit=fake_st,
        env_file_path=tmp_path / ".env",
        load_env_file_map=lambda _path: {"OPENAI_API_KEY": "already-saved"},
        logger=object(),
        apply_active_app_request=apply_request,
        handle_data_root_failure=lambda *_args, **_kwargs: False,
        refresh_env_from_file=lambda _env: None,
        clean_openai_key=lambda value: value,
        store_cluster_credentials=lambda *_args, **_kwargs: True,
        argv=["--apps-path", str(apps_path), "--active-app", "cli-app"],
        ports=ports,
    )

    assert result.should_rerun is False
    assert requested_apps == ["cli-app"]
    assert fake_st.query_params["active_app"] == "cli-app"
    assert port_calls.activated == []


def test_bootstrap_page_environment_handles_missing_apps_path(monkeypatch, tmp_path):
    bootstrap = about_agilab._about_bootstrap
    fake_st = _FakeStreamlit()

    class FakeAgiEnv:
        pass

    monkeypatch.setattr(bootstrap, "resolve_apps_path", lambda *_args, **_kwargs: None)
    ports, _port_calls = _make_bootstrap_ports(FakeAgiEnv)

    result = bootstrap.bootstrap_page_environment(
        streamlit=fake_st,
        env_file_path=tmp_path / ".env",
        load_env_file_map=lambda _path: {},
        logger=object(),
        apply_active_app_request=lambda *_args: False,
        handle_data_root_failure=lambda *_args, **_kwargs: False,
        refresh_env_from_file=lambda _env: None,
        clean_openai_key=lambda value: value,
        store_cluster_credentials=lambda *_args, **_kwargs: True,
        argv=[],
        ports=ports,
    )

    assert result.handled_recovery is True
    assert fake_st.stopped is True
    assert fake_st.events == [("error", "Error: Missing mandatory parameter: --apps-path")]


def test_bootstrap_page_environment_handles_resolution_and_data_root_recovery(
    monkeypatch,
    tmp_path,
):
    bootstrap = about_agilab._about_bootstrap
    fake_st = _FakeStreamlit()

    class FailingAgiEnv:
        def __init__(self, *_args, **_kwargs):
            raise RuntimeError("bad data root")

    monkeypatch.setattr(
        bootstrap,
        "resolve_apps_path",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("bad marker")),
    )
    ports, _port_calls = _make_bootstrap_ports(FailingAgiEnv)

    result = bootstrap.bootstrap_page_environment(
        streamlit=fake_st,
        env_file_path=tmp_path / ".env",
        load_env_file_map=lambda _path: {},
        logger=object(),
        apply_active_app_request=lambda *_args: False,
        handle_data_root_failure=lambda *_args, **_kwargs: False,
        refresh_env_from_file=lambda _env: None,
        clean_openai_key=lambda value: value,
        store_cluster_credentials=lambda *_args, **_kwargs: True,
        argv=[],
        ports=ports,
    )

    assert result.handled_recovery is True
    assert fake_st.stopped is True
    assert any("bad marker" in message for event, message in fake_st.events if event == "error")

    monkeypatch.setattr(bootstrap, "resolve_apps_path", lambda *_args, **_kwargs: tmp_path / "apps")
    recovered = bootstrap.bootstrap_page_environment(
        streamlit=_FakeStreamlit(),
        env_file_path=tmp_path / ".env",
        load_env_file_map=lambda _path: {},
        logger=object(),
        apply_active_app_request=lambda *_args: False,
        handle_data_root_failure=lambda exc, **_kwargs: "bad data root" in str(exc),
        refresh_env_from_file=lambda _env: None,
        clean_openai_key=lambda value: value,
        store_cluster_credentials=lambda *_args, **_kwargs: True,
        argv=[],
        ports=ports,
    )

    assert recovered.handled_recovery is True


def test_bootstrap_page_environment_reraises_unrecovered_data_root_error(
    monkeypatch,
    tmp_path,
):
    bootstrap = about_agilab._about_bootstrap

    class FailingAgiEnv:
        def __init__(self, *_args, **_kwargs):
            raise RuntimeError("bad data root")

    monkeypatch.setattr(bootstrap, "resolve_apps_path", lambda *_args, **_kwargs: tmp_path / "apps")
    ports, _port_calls = _make_bootstrap_ports(FailingAgiEnv)

    with pytest.raises(RuntimeError, match="bad data root"):
        bootstrap.bootstrap_page_environment(
            streamlit=_FakeStreamlit(),
            env_file_path=tmp_path / ".env",
            load_env_file_map=lambda _path: {},
            logger=object(),
            apply_active_app_request=lambda *_args: False,
            handle_data_root_failure=lambda *_args, **_kwargs: False,
            refresh_env_from_file=lambda _env: None,
            clean_openai_key=lambda value: value,
            store_cluster_credentials=lambda *_args, **_kwargs: True,
            argv=[],
            ports=ports,
        )


def test_bootstrap_page_environment_ignores_query_param_write_errors(tmp_path):
    bootstrap = about_agilab._about_bootstrap

    class FakeAgiEnv:
        def __init__(self, *, apps_path: Path, verbose: int):
            self.apps_path = apps_path
            self.verbose = verbose
            self.app = "default"
            self.is_source_env = True
            self.is_worker_env = False
            self.OPENAI_API_KEY = "sk-" + "c" * 16
            self.CLUSTER_CREDENTIALS = ""
            self.envars = {}

        @staticmethod
        def set_env_var(_key: str, _value: str) -> None:
            return None

    class RaisingQueryParams(dict):
        def __setitem__(self, key, value):
            raise RuntimeError("query write failed")

    fake_st = _FakeStreamlit()
    fake_st.query_params = RaisingQueryParams()
    ports, _port_calls = _make_bootstrap_ports(FakeAgiEnv, environ={})

    result = bootstrap.bootstrap_page_environment(
        streamlit=fake_st,
        env_file_path=tmp_path / ".env",
        load_env_file_map=lambda _path: {"APPS_PATH": str(tmp_path / "apps")},
        logger=object(),
        apply_active_app_request=lambda *_args: False,
        handle_data_root_failure=lambda *_args, **_kwargs: False,
        refresh_env_from_file=lambda _env: None,
        clean_openai_key=lambda value: value,
        store_cluster_credentials=lambda *_args, **_kwargs: True,
        argv=[],
        ports=ports,
    )

    assert result.handled_recovery is False


def test_resolve_share_dir_path_accepts_relative_value(tmp_path):
    resolved = about_agilab._resolve_share_dir_path("shares/data", home_path=tmp_path)
    assert resolved == (tmp_path / "shares" / "data").resolve(strict=False)


def test_resolve_share_dir_path_rejects_invalid_value(tmp_path):
    with pytest.raises(ValueError, match="AGI_SHARE_DIR"):
        about_agilab._resolve_share_dir_path("\0bad-path", home_path=tmp_path)


def test_worker_python_override_key_detection():
    assert about_agilab._is_worker_python_override_key("127.0.0.1_PYTHON_VERSION") is True
    assert about_agilab._is_worker_python_override_key("worker-a_PYTHON_VERSION") is True
    assert about_agilab._is_worker_python_override_key("AGI_PYTHON_VERSION") is False
    assert about_agilab._is_worker_python_override_key("127.0.0.1_CMD_PREFIX") is False


def test_env_editor_field_label_for_python_keys():
    assert about_agilab._env_editor_field_label("AGI_PYTHON_VERSION") == "Default Python version"
    assert about_agilab._env_editor_field_label("AGI_PYTHON_FREE_THREADED") == "Use free-threaded Python"
    assert about_agilab._env_editor_field_label("127.0.0.1_PYTHON_VERSION") == "Worker Python version for 127.0.0.1"
    assert about_agilab._env_editor_field_label("OPENAI_API_KEY") == "OPENAI_API_KEY"


def test_visible_env_editor_keys_keeps_template_order_and_adds_worker_overrides():
    template_keys = ["AGI_PYTHON_VERSION", "AGI_PYTHON_FREE_THREADED", "OPENAI_API_KEY"]
    existing_entries = [
        {"type": "entry", "key": "OPENAI_API_KEY", "value": "dummy"},
        {"type": "entry", "key": "127.0.0.1_PYTHON_VERSION", "value": "3.12"},
        {"type": "entry", "key": "10.0.0.5_CMD_PREFIX", "value": "ssh"},
        {"type": "entry", "key": "worker-a_PYTHON_VERSION", "value": "3.11"},
    ]

    assert about_agilab._visible_env_editor_keys(template_keys, existing_entries) == [
        "AGI_PYTHON_VERSION",
        "AGI_PYTHON_FREE_THREADED",
        "OPENAI_API_KEY",
        "127.0.0.1_PYTHON_VERSION",
        "worker-a_PYTHON_VERSION",
    ]


def test_newcomer_first_proof_content_exposes_single_recommended_path():
    content = about_agilab._newcomer_first_proof_content()

    assert content["title"] == "Start here: run flight_project first"
    assert "built-in flight demo locally" in content["intro"]
    assert content["recommended_path_id"] == "source-checkout-first-proof"
    assert content["actionable_route_ids"] == ["source-checkout-first-proof"]
    assert content["documented_route_ids"] == ["notebook-quickstart", "published-package-route"]
    assert [label for label, _ in content["steps"]] == [
        "PROJECT",
        "ORCHESTRATE",
        "ANALYSIS",
    ]
    assert any("flight_project" in detail for _, detail in content["steps"])
    assert any("generated files" in item for item in content["success_criteria"])
    assert any("cluster, benchmark, and service options off" in detail for _, detail in content["steps"])
    assert content["compatibility_status"] == "validated"
    assert content["compatibility_report_status"] == "pass"
    assert content["proof_command_labels"] == ["preinit smoke", "source ui smoke"]
    assert content["run_manifest_filename"] == "run_manifest.json"
    assert any("run_manifest.json" in item for item in content["success_criteria"])
    assert any("newcomer-guide" in url for _, url in content["links"])
    assert any("compatibility-matrix" in url for _, url in content["links"])


def test_landing_page_sections_use_clear_product_language():
    sections = about_agilab._landing_page_sections()

    assert sections["after_first_demo"] == [
        "try another built-in demo",
        "keep cluster mode for later",
    ]
    assert [card["title"] for card in sections["explore_cards"]] == [
        "Project",
        "Orchestrate",
        "Analysis",
    ]


def test_system_information_lines_include_cpu_gpu_and_npu_core_counts(monkeypatch):
    layout = about_agilab._about_layout

    monkeypatch.setattr(layout.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(layout.platform, "release", lambda: "25.3.0")
    monkeypatch.setattr(layout.platform, "processor", lambda: "arm")
    monkeypatch.setattr(layout.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(layout.os, "cpu_count", lambda: 16)

    def fake_command_output(command: tuple[str, ...]) -> str:
        if command == ("system_profiler", "SPHardwareDataType"):
            return """
Hardware:
    Hardware Overview:
      Chip: Apple M4 Max
      Total Number of Cores: 16 (12 Performance and 4 Efficiency)
"""
        if command == ("system_profiler", "SPDisplaysDataType"):
            return """
Graphics/Displays:
    Apple M4 Max:
      Chipset Model: Apple M4 Max
      Type: GPU
      Total Number of Cores: 40
"""
        return ""

    monkeypatch.setattr(layout, "_command_output", fake_command_output)

    lines = dict(layout.system_information_lines())

    assert lines["OS"] == "Darwin 25.3.0"
    assert lines["CPU"] == "Apple M4 Max; cores: 16 (12 Performance and 4 Efficiency)"
    assert lines["GPU"] == "Apple M4 Max (40 cores)"
    assert lines["NPU"] == "Apple Neural Engine (16 cores)"


def test_system_information_lines_include_nvidia_gpu_summary(monkeypatch):
    layout = about_agilab._about_layout

    monkeypatch.setattr(layout.platform, "system", lambda: "Linux")
    monkeypatch.setattr(layout.platform, "release", lambda: "6.8.0")
    monkeypatch.setattr(layout.platform, "processor", lambda: "")
    monkeypatch.setattr(layout.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(layout.os, "cpu_count", lambda: 12)
    monkeypatch.setattr(layout, "_physical_cpu_count", lambda: 6)

    def fake_command_output(command: tuple[str, ...]) -> str:
        if command and command[0] == "nvidia-smi":
            return "NVIDIA A100, 108\nNVIDIA L4, 58"
        return ""

    monkeypatch.setattr(layout, "_command_output", fake_command_output)

    lines = dict(layout.system_information_lines())

    assert lines["OS"] == "Linux 6.8.0"
    assert lines["CPU"] == "x86_64; cores: 6 physical / 12 logical"
    assert lines["GPU"] == "2 GPUs: NVIDIA A100 (108 SMs); NVIDIA L4 (58 SMs)"
    assert lines["NPU"] == "Not detected"


def test_about_layout_helpers_cover_display_fallbacks(tmp_path, monkeypatch):
    import agi_gui.pagelib as pagelib

    fake_st = _FakeStreamlit()
    monkeypatch.setattr(about_agilab, "st", fake_st)
    monkeypatch.setattr(
        pagelib,
        "get_base64_of_image",
        lambda _path: (_ for _ in ()).throw(OSError("missing logo")),
    )

    about_agilab.quick_logo(tmp_path)
    about_agilab.display_landing_page(tmp_path)
    about_agilab._sync_layout_module()
    monkeypatch.setattr(
        about_agilab._about_layout,
        "system_information_lines",
        lambda: [
            ("OS", "Test OS"),
            ("CPU", "Test CPU"),
            ("GPU", "Test GPU"),
            ("NPU", "Test NPU"),
        ],
    )
    about_agilab._about_layout.render_package_versions()
    about_agilab._about_layout.render_system_information()
    about_agilab._about_layout.render_sidebar_system_information()
    about_agilab._about_layout.render_footer()

    assert about_agilab._clean_openai_key("sk-" + "a" * 16) == "sk-" + "a" * 16
    assert any("Welcome to AGILAB" in body for kind, body in fake_st.events if kind == "info")
    assert any("agilab-next" in body for kind, body in fake_st.events if kind == "markdown")
    assert any("agilab:" in body for kind, body in fake_st.events if kind == "write")
    assert any("agi-gui:" in body for kind, body in fake_st.events if kind == "write")
    assert any("OS:" in body for kind, body in fake_st.events if kind == "write")
    assert any("OS:" in body for kind, body in fake_st.events if kind == "sidebar.caption")
    assert any("CPU:" in body for kind, body in fake_st.events if kind == "sidebar.caption")
    assert any("GPU:" in body for kind, body in fake_st.events if kind == "sidebar.caption")
    assert any("NPU:" in body for kind, body in fake_st.events if kind == "sidebar.caption")
    assert any("2020-" in body for kind, body in fake_st.events if kind == "markdown")


def test_about_page_local_theme_and_sidebar_version_helpers(tmp_path, monkeypatch):
    fake_st = _FakeStreamlit()
    monkeypatch.setattr(about_agilab, "st", fake_st)
    monkeypatch.setattr(
        about_agilab,
        "read_theme_css",
        lambda _base_path, *, module_file: "body { color: #123456; }",
    )

    about_agilab.inject_theme(tmp_path)
    about_agilab.render_sidebar_version("v2026.4.28")
    about_menu = about_agilab.get_about_content()

    markdown = "\n".join(body for kind, body in fake_st.events if kind == "markdown")
    assert "body { color: #123456; }" in markdown
    assert "AGILAB v2026.4.28" in markdown
    assert about_agilab._sidebar_version_label("2026.4.28") == "AGILAB v2026.4.28"
    assert about_agilab._sidebar_version_label("") == ""
    assert "open a GitHub issue" in about_menu["About"]


def test_about_page_moves_system_information_to_sidebar(monkeypatch):
    fake_st = _FakeStreamlit()
    monkeypatch.setattr(about_agilab, "st", fake_st)
    rendered_versions: list[str] = []
    monkeypatch.setattr(about_agilab, "render_sidebar_version", rendered_versions.append)
    monkeypatch.setattr(about_agilab, "detect_agilab_version", lambda _env: "2026.4.28")
    monkeypatch.setattr(about_agilab, "_render_env_editor", lambda _env: None)
    monkeypatch.setattr(about_agilab, "render_page_docs_access", lambda *_args, **_kwargs: None)
    about_agilab._sync_layout_module()
    monkeypatch.setattr(
        about_agilab._about_layout,
        "system_information_lines",
        lambda: [
            ("OS", "Test OS"),
            ("CPU", "Test CPU"),
            ("GPU", "Test GPU"),
            ("NPU", "Test NPU"),
        ],
    )

    env = SimpleNamespace(
        app="flight_project",
        apps_path=Path("/tmp/agilab/apps"),
        agi_share_path_abs=Path("/tmp/agilab/localshare"),
        AGILAB_LOG_ABS=Path("/tmp/agilab/log"),
        TABLE_MAX_ROWS=100,
        GUI_SAMPLING=10,
    )

    about_agilab.page(env)

    env_expander = _event_index(fake_st.events, "expander", "Environment Variables")
    expanders = [body for kind, body in fake_st.events if kind == "expander"]
    assert any("Environment Variables" in label for label in expanders)
    assert "Installed package versions:False" not in expanders
    assert "System information:False" not in expanders
    assert rendered_versions == ["2026.4.28"]
    assert any("OS:" in body for kind, body in fake_st.events if kind == "sidebar.caption")
    assert any("CPU:" in body for kind, body in fake_st.events if kind == "sidebar.caption")
    assert any("GPU:" in body for kind, body in fake_st.events if kind == "sidebar.caption")
    assert any("NPU:" in body for kind, body in fake_st.events if kind == "sidebar.caption")
    assert env_expander >= 0


def test_about_quick_logo_renders_polished_hero(tmp_path, monkeypatch):
    import agi_gui.pagelib as pagelib

    fake_st = _FakeStreamlit()
    monkeypatch.setattr(about_agilab, "st", fake_st)
    monkeypatch.setattr(pagelib, "get_base64_of_image", lambda _path: "encoded-logo")

    about_agilab.quick_logo(tmp_path)

    body = "\n".join(body for kind, body in fake_st.events if kind == "markdown")
    assert "agilab-hero" in body
    assert "Reproducible AI engineering, from project to proof" in body
    assert "Control path" in body
    assert "Data intake" in body
    assert "Decision evidence" in body


def test_newcomer_first_proof_state_prefers_built_in_flight_project(tmp_path):
    apps_path = tmp_path / "apps"
    flight_project = apps_path / "builtin" / "flight_project"
    flight_project.mkdir(parents=True)

    env = SimpleNamespace(
        apps_path=apps_path,
        app="mycode_project",
        AGILAB_LOG_ABS=tmp_path / "log",
    )

    state = about_agilab._newcomer_first_proof_state(env)

    assert state["project_path"] == flight_project.resolve()
    assert state["project_available"] is True
    assert state["current_app_matches"] is False
    assert state["compatibility_slice"] == "Source checkout first proof"
    assert state["compatibility_status"] == "validated"
    assert state["recommended_path_id"] == "source-checkout-first-proof"
    assert state["actionable_route_ids"] == ["source-checkout-first-proof"]
    assert state["run_manifest_path"] == tmp_path / "log" / "execute" / "flight" / "run_manifest.json"
    assert state["run_manifest_loaded"] is False
    assert state["run_manifest_status"] == "missing"
    assert state["remediation_status"] == "missing"
    assert "tools/compatibility_report.py --manifest" in state["evidence_commands"][1]
    assert state["next_step"] == "Go to `PROJECT`. Choose `flight_project`."


def test_first_proof_progress_rows_prioritize_project_selection(tmp_path):
    apps_path = tmp_path / "apps"
    flight_project = apps_path / "builtin" / "flight_project"
    flight_project.mkdir(parents=True)

    env = SimpleNamespace(
        apps_path=apps_path,
        app="mycode_project",
        AGILAB_LOG_ABS=tmp_path / "log",
    )

    rows = about_agilab._first_proof_progress_rows(
        about_agilab._newcomer_first_proof_state(env)
    )
    by_step = {row["step"]: row for row in rows}

    assert by_step["Project selected"]["status"] == "Next"
    assert "mycode_project" in by_step["Project selected"]["detail"]
    assert by_step["Run executed"]["status"] == "Waiting"
    assert by_step["Evidence manifest"]["status"] == "Waiting"


def test_newcomer_first_proof_state_detects_generated_outputs(tmp_path):
    apps_path = tmp_path / "apps"
    flight_project = apps_path / "flight_project"
    flight_project.mkdir(parents=True)
    output_dir = tmp_path / "log" / "execute" / "flight"
    output_dir.mkdir(parents=True)
    (output_dir / "AGI_install_flight.py").write_text("# helper", encoding="utf-8")
    (output_dir / "AGI_run_flight.py").write_text("# helper", encoding="utf-8")
    (output_dir / "forecast_metrics.json").write_text("{}", encoding="utf-8")

    env = SimpleNamespace(
        apps_path=apps_path,
        app="flight_project",
        AGILAB_LOG_ABS=tmp_path / "log",
    )

    state = about_agilab._newcomer_first_proof_state(env)

    assert state["current_app_matches"] is True
    assert state["helper_scripts_present"] is True
    assert state["run_output_detected"] is True
    assert [path.name for path in state["visible_outputs"]] == ["forecast_metrics.json"]
    assert state["remediation_status"] == "missing_manifest_with_outputs"
    assert state["next_step"] == "Generate `run_manifest.json` with the first-proof JSON command."


def test_first_proof_progress_rows_show_incomplete_manifest_attention(tmp_path):
    apps_path = tmp_path / "apps"
    flight_project = apps_path / "flight_project"
    flight_project.mkdir(parents=True)
    output_dir = tmp_path / "log" / "execute" / "flight"
    output_dir.mkdir(parents=True)
    (output_dir / "forecast_metrics.json").write_text("{}", encoding="utf-8")

    env = SimpleNamespace(
        apps_path=apps_path,
        app="flight_project",
        AGILAB_LOG_ABS=tmp_path / "log",
    )

    rows = about_agilab._first_proof_progress_rows(
        about_agilab._newcomer_first_proof_state(env)
    )
    by_step = {row["step"]: row for row in rows}

    assert by_step["Project selected"]["status"] == "Done"
    assert by_step["Run executed"]["status"] == "Done"
    assert by_step["Evidence manifest"]["status"] == "Waiting"
    assert "run_manifest.json" in by_step["Evidence manifest"]["detail"]


def test_first_proof_progress_rows_cover_missing_and_passed_states():
    base_state = {
        "active_app_name": "flight_project",
        "output_dir": "/tmp/out",
        "project_available": True,
        "current_app_matches": True,
        "run_manifest_loaded": False,
        "run_output_detected": False,
        "run_manifest_passed": False,
        "run_manifest_status": "missing",
        "run_manifest_path": "/tmp/out/run_manifest.json",
    }

    missing_rows = about_agilab._first_proof_progress_rows(
        {**base_state, "project_available": False}
    )
    assert missing_rows[0]["status"] == "Blocked"

    passed_rows = about_agilab._first_proof_progress_rows(
        {
            **base_state,
            "run_manifest_loaded": True,
            "run_manifest_passed": True,
        }
    )
    by_step = {row["step"]: row for row in passed_rows}
    assert by_step["Run executed"]["status"] == "Done"
    assert by_step["Evidence manifest"]["status"] == "Done"


def test_first_proof_next_action_branches(monkeypatch):
    fake_st = _FakeStreamlit()
    monkeypatch.setattr(about_agilab, "st", fake_st)
    base_state = {
        "next_step": "next",
        "project_available": True,
        "current_app_matches": True,
        "run_manifest_loaded": False,
        "run_output_detected": False,
        "run_manifest_passed": False,
    }

    about_agilab._render_first_proof_next_action(
        SimpleNamespace(),
        {**base_state, "project_available": False},
    )
    about_agilab._render_first_proof_next_action(
        SimpleNamespace(),
        {**base_state, "run_manifest_passed": True},
    )
    about_agilab._render_first_proof_next_action(
        SimpleNamespace(),
        {**base_state, "run_manifest_loaded": True},
    )
    about_agilab._render_first_proof_next_action(SimpleNamespace(), base_state)

    assert any(kind == "error" for kind, _ in fake_st.events)
    assert any(kind == "success" for kind, _ in fake_st.events)
    assert any(kind == "warning" for kind, _ in fake_st.events)
    assert any(kind == "info" for kind, _ in fake_st.events)


def test_env_editor_refresh_share_dir_success_and_ignored_empty(tmp_path, monkeypatch):
    fake_st = _FakeStreamlit()
    monkeypatch.setattr(about_agilab, "st", fake_st)
    data_root = tmp_path / "share" / "flight"
    env = SimpleNamespace(
        home_abs=tmp_path,
        share_target_name="flight",
        ensure_data_root=lambda: data_root,
    )

    about_agilab._refresh_share_dir(env, "")
    about_agilab._refresh_share_dir(env, "share")

    assert env.agi_share_path == "share"
    assert env.data_root == data_root
    assert env.dataframe_path == tmp_path / "share" / "flight" / "dataframe"


def test_render_newcomer_first_proof_places_next_action_before_diagnostics(
    tmp_path,
    monkeypatch,
):
    apps_path = tmp_path / "apps"
    flight_project = apps_path / "builtin" / "flight_project"
    flight_project.mkdir(parents=True)
    fake_st = _FakeStreamlit()
    env = SimpleNamespace(
        apps_path=apps_path,
        app="mycode_project",
        AGILAB_LOG_ABS=tmp_path / "log",
        st_resources=tmp_path / "resources",
    )

    monkeypatch.setattr(about_agilab, "st", fake_st)
    monkeypatch.setattr(about_agilab, "display_landing_page", lambda _path: None)

    about_agilab.render_newcomer_first_proof(env)

    overview = _event_index(fake_st.events, "markdown", "agilab-proof")
    next_action = _event_index(fake_st.events, "warning", "Next action:")
    do_this_now = _event_index(fake_st.events, "markdown", "**2. Do this now**")
    done_when = _event_index(fake_st.events, "markdown", "**3. Done when**")
    proof_details = _event_index(
        fake_st.events,
        "expander",
        "If it fails / proof details:False",
    )
    progress = _event_index(fake_st.events, "markdown", "**Progress**")
    validated_path = _event_index(fake_st.events, "caption", "Validated path:")

    assert overview < next_action < do_this_now < done_when < proof_details < progress < validated_path


def test_render_newcomer_first_proof_uses_markdown(monkeypatch):
    captured: dict[str, object] = {}

    def fake_markdown(body: str, unsafe_allow_html: bool = False):
        captured["body"] = body
        captured["unsafe_allow_html"] = unsafe_allow_html

    monkeypatch.setattr(about_agilab.st, "markdown", fake_markdown)

    about_agilab.render_newcomer_first_proof()

    assert captured["unsafe_allow_html"] is True
    body = str(captured["body"])
    assert "Start here" in body
    assert "PROJECT" in body
    assert "ORCHESTRATE" in body
    assert "ANALYSIS" in body
    assert "flight_project" in body
    assert "run_manifest.json" in body
    assert "Do this now" in body
    assert "Done when" in body
