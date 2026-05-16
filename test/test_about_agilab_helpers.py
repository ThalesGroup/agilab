from __future__ import annotations

import base64
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "agilab" / "main_page.py"
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

    def caption(self, body: object):
        self._streamlit.events.append(("caption", str(body)))

    def markdown(self, body: object, **_kwargs):
        self._streamlit.events.append(("markdown", str(body)))

    def selectbox(self, label: str, options, **kwargs):
        self._streamlit.events.append(("selectbox", label))
        key = kwargs.get("key")
        if key and key in self._streamlit.session_state:
            return self._streamlit.session_state[key]
        index = int(kwargs.get("index", 0) or 0)
        return list(options)[index]


class _FakeSidebar:
    def __init__(self, streamlit):
        self._streamlit = streamlit

    def button(self, label: str, **_kwargs):
        self._streamlit.events.append(("sidebar.button", label))
        return bool(self._streamlit.sidebar_button_values.get(label, False))

    def caption(self, body: object):
        self._streamlit.events.append(("sidebar.caption", str(body)))

    def markdown(self, body: object, **_kwargs):
        self._streamlit.events.append(("sidebar.markdown", str(body)))


class _FakeColumn:
    def __init__(self, streamlit, index: int):
        self._streamlit = streamlit
        self._index = index

    def __enter__(self):
        self._streamlit.events.append(("enter_column", str(self._index)))
        return self

    def __exit__(self, exc_type, exc, tb):
        self._streamlit.events.append(("exit_column", str(self._index)))
        return False


class _FakeStreamlit:
    def __init__(self, *, button_values=None, file_uploader_values=None, sidebar_button_values=None):
        self.events: list[tuple[str, str]] = []
        self.session_state: dict[str, object] = {}
        self.query_params: dict[str, object] = {}
        self.button_values = button_values or {}
        self.file_uploader_values = file_uploader_values or {}
        self.sidebar_button_values = sidebar_button_values or {}
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
        key = _kwargs.get("key")
        return bool(self.button_values.get(label, self.button_values.get(key, False)))

    def file_uploader(self, label: str, **_kwargs):
        self.events.append(("file_uploader", label))
        key = _kwargs.get("key")
        return self.file_uploader_values.get(label, self.file_uploader_values.get(key))

    def download_button(self, label: str, **_kwargs):
        self.events.append(("download_button", label))
        return False

    def page_link(self, page: object, **kwargs):
        self.events.append(("page_link", f"{kwargs.get('label', page)}:{page}:{kwargs}"))


    def columns(self, spec, **_kwargs):
        count = int(spec) if isinstance(spec, int) else len(spec)
        self.events.append(("columns", str(count)))
        if not isinstance(spec, int):
            self.events.append(("columns_spec", ",".join(str(item) for item in spec)))
        if "width" in _kwargs:
            self.events.append(("columns_width", str(_kwargs["width"])))
        return [_FakeColumn(self, index) for index in range(count)]

    def selectbox(self, label: str, options, **kwargs):
        self.events.append(("selectbox", label))
        key = kwargs.get("key")
        if key and key in self.session_state:
            return self.session_state[key]
        index = int(kwargs.get("index", 0) or 0)
        return list(options)[index]

    def switch_page(self, page: object, **kwargs):
        query_params = kwargs.get("query_params")
        if query_params is not None:
            self.query_params = dict(query_params)
        self.events.append(("switch_page", str(page)))

    def rerun(self):
        self.events.append(("rerun", ""))

    def stop(self):
        self.stopped = True


class _StoppingStreamlit:
    def __init__(self):
        self.events: list[tuple[str, str, object]] = []

    def error(self, body: object, **_kwargs):
        self.events.append(("error", str(body), None))

    def markdown(self, body: object, **_kwargs):
        self.events.append(("markdown", str(body), None))

    def caption(self, body: object, **_kwargs):
        self.events.append(("caption", str(body), None))

    def code(self, body: object, **kwargs):
        self.events.append(("code", str(body), kwargs.get("language")))

    def stop(self):
        raise RuntimeError("st.stop")


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


def _event_body(events: list[tuple[str, str]], kind: str, text: str) -> str:
    return next(
        body
        for event_kind, body in events
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


def test_page_bootstrap_realigns_stale_session_env_to_page_root(tmp_path):
    source_root = tmp_path / "agilab-src" / "src" / "agilab"
    source_apps = source_root / "apps"
    page_file = source_root / "pages" / "2_ORCHESTRATE.py"
    source_project = source_apps / "builtin" / "flight_telemetry_project"
    stale_apps = tmp_path / "agi-space" / "apps" / "builtin"
    page_file.parent.mkdir(parents=True)
    source_project.mkdir(parents=True)
    stale_apps.mkdir(parents=True)

    class FakeEnv:
        def __init__(self, *, apps_path: Path, app: str = "flight_telemetry_project", verbose: int | None = 1):
            self.apps_path = apps_path
            self.app = app
            self.verbose = verbose
            self.active_app = apps_path / "builtin" / app if apps_path.name == "apps" else apps_path / app
            self.init_done = True

    env = FakeEnv(apps_path=stale_apps)
    session_state = {
        "env": env,
        "apps_path": str(source_apps),
    }

    assert page_bootstrap.realign_session_env_with_page_root(session_state, page_file) is True
    assert env.apps_path == source_apps
    assert env.active_app == source_project
    assert session_state["apps_path"] == str(source_apps)
    assert env.init_done is True


def test_page_bootstrap_realigns_stale_agi_space_recorded_root(tmp_path):
    source_root = tmp_path / "agilab-src" / "src" / "agilab"
    source_apps = source_root / "apps"
    page_file = source_root / "pages" / "2_ORCHESTRATE.py"
    source_project = source_apps / "builtin" / "flight_telemetry_project"
    stale_apps = tmp_path / "agi-space" / "apps"
    page_file.parent.mkdir(parents=True)
    source_project.mkdir(parents=True)
    (stale_apps / "builtin" / "flight_telemetry_project").mkdir(parents=True)

    class FakeEnv:
        def __init__(self, *, apps_path: Path, app: str = "flight_telemetry_project", verbose: int | None = 1):
            self.apps_path = apps_path
            self.app = app
            self.verbose = verbose
            self.active_app = apps_path / "builtin" / app
            self.init_done = True

    env = FakeEnv(apps_path=stale_apps)
    session_state = {
        "env": env,
        "apps_path": str(stale_apps),
    }

    assert page_bootstrap.realign_session_env_with_page_root(session_state, page_file) is True
    assert env.apps_path == source_apps
    assert env.active_app == source_project
    assert session_state["apps_path"] == str(source_apps)


def test_page_bootstrap_realigns_stale_agi_space_active_app_with_current_source_root(tmp_path):
    source_root = tmp_path / "agilab-src" / "src" / "agilab"
    source_apps = source_root / "apps"
    page_file = source_root / "pages" / "2_ORCHESTRATE.py"
    source_project = source_apps / "builtin" / "flight_telemetry_project"
    stale_project = tmp_path / "agi-space" / "apps" / "builtin" / "flight_telemetry_project"
    page_file.parent.mkdir(parents=True)
    source_project.mkdir(parents=True)
    stale_project.mkdir(parents=True)

    class FakeEnv:
        def __init__(self, *, apps_path: Path, app: str = "flight_telemetry_project", verbose: int | None = 1):
            self.apps_path = apps_path
            self.app = app
            self.verbose = verbose
            self.active_app = apps_path / "builtin" / app
            self.init_done = True

    env = FakeEnv(apps_path=source_apps)
    env.active_app = stale_project
    session_state = {
        "env": env,
        "apps_path": str(source_apps),
    }

    assert page_bootstrap.realign_session_env_with_page_root(session_state, page_file) is True
    assert env.apps_path == source_apps
    assert env.active_app == source_project
    assert session_state["apps_path"] == str(source_apps)


def test_page_bootstrap_keeps_session_env_when_recorded_root_differs(tmp_path):
    source_root = tmp_path / "agilab-src" / "src" / "agilab"
    source_apps = source_root / "apps"
    other_apps = tmp_path / "other" / "apps"
    page_file = source_root / "pages" / "2_ORCHESTRATE.py"
    page_file.parent.mkdir(parents=True)
    source_apps.mkdir(parents=True)
    other_apps.mkdir(parents=True)
    env = SimpleNamespace(apps_path=other_apps, app="flight_telemetry_project", init_done=True)
    session_state = {
        "env": env,
        "apps_path": str(other_apps),
    }

    assert page_bootstrap.realign_session_env_with_page_root(session_state, page_file) is False
    assert env.apps_path == other_apps


def test_import_guard_error_is_rendered_as_code(monkeypatch):
    fake_st = _StoppingStreamlit()
    monkeypatch.setattr(about_agilab, "st", fake_st)
    message = (
        "Mixed AGILAB Python environment detected.\n\n"
        "How to fix this checkout:\n"
        "macOS/Linux:\n"
        "   cd /tmp/current && AGILAB_PYCHARM_ALLOW_SDK_REBIND=1 "
        "uv --preview-features extra-build-dependencies run python pycharm/setup_pycharm.py\n\n"
        "Windows PowerShell:\n"
        "   Set-Location -LiteralPath 'C:\\current'\n"
        "   $env:AGILAB_PYCHARM_ALLOW_SDK_REBIND = '1'\n"
        "   uv --preview-features extra-build-dependencies run python pycharm/setup_pycharm.py\n"
        "Full details"
    )
    exc = about_agilab._import_guard_module.MixedCheckoutImportError(message)

    with pytest.raises(RuntimeError, match="st.stop"):
        about_agilab._stop_for_import_guard_error(exc)

    assert fake_st.events[0] == (
        "error",
        "AGILAB cannot start because PyCharm/Python is bound to another AGILAB checkout.",
        None,
    )
    assert "What happened" in fake_st.events[1][1]
    assert fake_st.events[2] == ("caption", "Rebind command (macOS/Linux)", None)
    assert fake_st.events[3] == (
        "code",
        "cd /tmp/current && AGILAB_PYCHARM_ALLOW_SDK_REBIND=1 "
        "uv --preview-features extra-build-dependencies run python pycharm/setup_pycharm.py",
        "bash",
    )
    assert fake_st.events[4] == ("caption", "Rebind command (Windows PowerShell)", None)
    assert fake_st.events[5] == (
        "code",
        "Set-Location -LiteralPath 'C:\\current'\n"
        "$env:AGILAB_PYCHARM_ALLOW_SDK_REBIND = '1'\n"
        "uv --preview-features extra-build-dependencies run python pycharm/setup_pycharm.py",
        "powershell",
    )
    assert fake_st.events[6] == ("caption", "Full diagnostic", None)
    assert fake_st.events[7] == ("code", message, "text")


def test_import_guard_single_line_diagnostic_is_wrapped_for_display():
    message = (
        "Mixed AGILAB sys.path detected. "
        "Current file /tmp/current/src/agilab/main_page.py belongs to /tmp/current, "
        "but Python can also resolve AGILAB from /tmp/other via sys.path entry "
        "'/tmp/other/.venv/lib/python3.13/site-packages'. "
        "Remove stale PYTHONPATH/PyCharm content roots and relaunch. "
        "If you intentionally switched checkout, rerun pycharm/setup_pycharm.py from the intended source root."
    )

    rendered = about_agilab._format_import_guard_diagnostic_for_display(message)

    assert "\n" in rendered
    assert "Mixed AGILAB sys.path detected." in rendered
    assert "Current file /tmp/current/src/agilab/main_page.py" in rendered
    assert "but Python can also resolve AGILAB" in rendered
    assert "Remove stale PYTHONPATH/PyCharm content roots" in rendered
    assert "If you intentionally switched checkout" in rendered
    assert " ".join(rendered.split()) == " ".join(message.split())


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
    assert calls[0][0] == ("agilab.main_page",)
    assert calls[0][1]["current_file"] == current_file
    assert calls[0][1]["fallback_path"] == current_file.parents[1] / "main_page.py"


def test_page_bootstrap_load_about_page_module_falls_back_to_file(tmp_path, monkeypatch):
    current_file = tmp_path / "agilab" / "pages" / "page.py"
    about_file = tmp_path / "agilab" / "main_page.py"
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
    about_file = tmp_path / "agilab" / "main_page.py"
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

    with pytest.raises(ModuleNotFoundError, match="Unable to load main_page"):
        page_bootstrap.load_about_page_module(current_file)


def test_page_bootstrap_load_about_page_module_rejects_fallback_without_main(tmp_path, monkeypatch):
    current_file = tmp_path / "agilab" / "pages" / "page.py"
    about_file = tmp_path / "agilab" / "main_page.py"
    current_file.parent.mkdir(parents=True)
    about_file.write_text("VALUE = 1\n", encoding="utf-8")

    monkeypatch.setattr(
        page_bootstrap.importlib,
        "import_module",
        lambda _name: (_ for _ in ()).throw(ImportError("missing")),
    )

    with pytest.raises(ModuleNotFoundError, match="Unable to import main_page"):
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


def test_refresh_env_from_file_keeps_session_apps_path_over_stale_env_path(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    stale_apps = tmp_path / "agi-space" / "apps"
    source_apps = tmp_path / "agilab-src" / "src" / "agilab" / "apps"
    stale_apps.mkdir(parents=True)
    source_apps.mkdir(parents=True)
    env_file.write_text(
        "\n".join(
            [
                "OPENAI_MODEL=gpt-5.4",
                f"APPS_PATH={stale_apps}",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(about_agilab, "ENV_FILE_PATH", env_file)
    about_agilab.st.session_state.pop("env_file_mtime_ns", None)
    previous_apps_path = about_agilab.st.session_state.get("apps_path")
    about_agilab.st.session_state["apps_path"] = str(source_apps)

    env = SimpleNamespace(
        envars={},
        apps_path=stale_apps,
    )

    try:
        about_agilab._refresh_env_from_file(env)
    finally:
        if previous_apps_path is None:
            about_agilab.st.session_state.pop("apps_path", None)
        else:
            about_agilab.st.session_state["apps_path"] = previous_apps_path

    assert env.envars["OPENAI_MODEL"] == "gpt-5.4"
    assert env.envars["APPS_PATH"] == str(stale_apps)
    assert env.apps_path == source_apps.resolve()
    assert about_agilab.st.session_state["env_file_mtime_ns"] == env_file.stat().st_mtime_ns


def test_refresh_env_from_file_ignores_commented_template_defaults(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                '# AGI_EXPORT_DIR="export"',
                'OPENAI_MODEL="gpt-5.4"',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(about_agilab, "ENV_FILE_PATH", env_file)
    monkeypatch.delenv("AGI_EXPORT_DIR", raising=False)
    about_agilab.st.session_state.pop("env_file_mtime_ns", None)

    env = SimpleNamespace(envars={}, apps_path="old/path")

    about_agilab._refresh_env_from_file(env)

    assert "AGI_EXPORT_DIR" not in env.envars
    assert "AGI_EXPORT_DIR" not in os.environ
    assert env.envars["OPENAI_MODEL"] == "gpt-5.4"


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
        home_path=tmp_path,
    ) == cli_apps

    args = bootstrap.parse_startup_args([])
    assert bootstrap.resolve_apps_path(
        args,
        env_file_path=tmp_path / ".env",
        load_env_file_map=lambda _path: {"APPS_PATH": str(env_apps)},
        home_path=tmp_path,
    ) == env_apps


def test_bootstrap_resolve_apps_path_from_agilab_path_file(tmp_path):
    bootstrap = about_agilab._about_bootstrap
    install_root = tmp_path / "agi-space"
    marker = tmp_path / ".agilab-path"
    marker.write_text(str(install_root / ".venv" / "bin" / "python"), encoding="utf-8")

    assert bootstrap.apps_path_from_agilab_path_file(marker) == (install_root / "apps").resolve(
        strict=False
    )


def test_bootstrap_resolve_apps_path_from_source_agilab_path_file(tmp_path):
    bootstrap = about_agilab._about_bootstrap
    source_root = tmp_path / "agilab-src" / "src" / "agilab"
    source_root.mkdir(parents=True)
    marker = tmp_path / ".agilab-path"
    marker.write_text(str(source_root), encoding="utf-8")

    assert bootstrap.apps_path_from_agilab_path_file(marker) == (source_root / "apps").resolve(
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
    project_path = apps_path / "flight_telemetry_project"
    project_path.mkdir(parents=True)
    warnings: list[str] = []

    class FakeEnv:
        def __init__(self):
            self.apps_path = apps_path
            self.app = "default"
            self.projects = {"flight_telemetry_project"}

        def change_app(self, path: Path) -> None:
            assert path == project_path.resolve()
            self.app = path.name

    fake_st = SimpleNamespace(warning=warnings.append)
    env = FakeEnv()

    assert bootstrap.normalize_active_app_input(env, "flight_telemetry_project") == project_path.resolve()
    assert bootstrap.apply_active_app_request(env, "flight_telemetry_project", streamlit=fake_st) is True
    assert env.app == "flight_telemetry_project"
    assert warnings == []


def test_bootstrap_active_app_request_switches_same_name_when_root_changes(tmp_path):
    bootstrap = about_agilab._about_bootstrap
    old_root = tmp_path / "agi-space" / "apps" / "builtin"
    new_root = tmp_path / "agilab-src" / "src" / "agilab" / "apps" / "builtin"
    old_project = old_root / "flight_telemetry_project"
    new_project = new_root / "flight_telemetry_project"
    old_project.mkdir(parents=True)
    new_project.mkdir(parents=True)
    warnings: list[str] = []

    class FakeEnv:
        def __init__(self, *, apps_path: Path = old_root, app: str = "flight_telemetry_project", verbose: int | None = 1):
            self.apps_path = apps_path
            self.app = app
            self.verbose = verbose
            self.active_app = apps_path / app
            self.projects = {"flight_telemetry_project"}
            self.init_done = True

        def change_app(self, _path: Path) -> None:
            raise RuntimeError("same-name path switch must not use name-only change_app")

    fake_st = SimpleNamespace(warning=warnings.append)
    env = FakeEnv()

    assert bootstrap.apply_active_app_request(env, str(new_project), streamlit=fake_st) is True
    assert env.app == "flight_telemetry_project"
    assert env.apps_path == new_root
    assert env.active_app == new_project
    assert env.init_done is True
    assert warnings == []


def test_bootstrap_active_app_store_path_prefers_real_active_app(tmp_path):
    bootstrap = about_agilab._about_bootstrap
    apps_path = tmp_path / "src" / "agilab" / "apps"
    active_app = apps_path / "builtin" / "flight_telemetry_project"
    env = SimpleNamespace(apps_path=apps_path, app="flight_telemetry_project", active_app=active_app)

    assert bootstrap.active_app_store_path(env) == active_app


def test_bootstrap_normalize_active_app_input_finds_builtin_project_name(tmp_path):
    bootstrap = about_agilab._about_bootstrap
    apps_path = tmp_path / "src" / "agilab" / "apps"
    builtin_path = apps_path / "builtin"
    active_app = builtin_path / "flight_telemetry_project"
    active_app.mkdir(parents=True)
    env = SimpleNamespace(
        apps_path=apps_path,
        builtin_apps_path=builtin_path,
        apps_repository_root=None,
        projects={"flight_telemetry_project"},
    )

    assert bootstrap.normalize_active_app_input(env, "flight_telemetry_project") == active_app.resolve()


def test_bootstrap_page_environment_keeps_source_root_when_last_app_is_agi_space(tmp_path):
    bootstrap = about_agilab._about_bootstrap
    source_apps = tmp_path / "agilab-src" / "src" / "agilab" / "apps"
    source_builtin = source_apps / "builtin"
    source_project = source_builtin / "flight_telemetry_project"
    stale_project = tmp_path / "agi-space" / "apps" / "builtin" / "flight_telemetry_project"
    source_project.mkdir(parents=True)
    stale_project.mkdir(parents=True)
    requested_apps: list[str | None] = []

    class FakeAgiEnv:
        def __init__(self, *, apps_path: Path, app: str = "flight_telemetry_project", verbose: int = 1):
            self.apps_path = apps_path
            self.builtin_apps_path = apps_path / "builtin"
            self.apps_repository_root = None
            self.verbose = verbose
            self.app = app
            self.active_app = self.builtin_apps_path / app
            self.projects = {"flight_telemetry_project"}
            self.is_source_env = True
            self.is_worker_env = False
            self.OPENAI_API_KEY = ""
            self.CLUSTER_CREDENTIALS = ""
            self.envars = {}
            self.init_done = False

        @staticmethod
        def set_env_var(_key: str, _value: str) -> None:
            return None

    def apply_request(env, requested):
        requested_apps.append(requested)
        return bootstrap.apply_active_app_request(env, requested, streamlit=fake_st)

    fake_st = _FakeStreamlit()
    ports, port_calls = _make_bootstrap_ports(
        FakeAgiEnv,
        services_enabled=False,
        last_app=stale_project,
        environ={},
    )

    result = bootstrap.bootstrap_page_environment(
        streamlit=fake_st,
        env_file_path=tmp_path / ".env",
        load_env_file_map=lambda _path: {},
        logger=object(),
        apply_active_app_request=apply_request,
        handle_data_root_failure=lambda *_args, **_kwargs: False,
        refresh_env_from_file=lambda _env: None,
        clean_openai_key=lambda value: value,
        store_cluster_credentials=lambda *_args, **_kwargs: True,
        argv=["--apps-path", str(source_apps)],
        ports=ports,
    )

    assert result.env.active_app == source_project
    assert result.env.apps_path == source_apps
    assert requested_apps == ["flight_telemetry_project"]
    assert port_calls.stored == [source_project]
    assert fake_st.query_params["active_app"] == "flight_telemetry_project"


def test_bootstrap_page_environment_repairs_enduser_env_before_source_agi_env_init(tmp_path, monkeypatch):
    bootstrap = about_agilab._about_bootstrap
    source_apps = tmp_path / "agilab-src" / "src" / "agilab" / "apps"
    source_project = source_apps / "builtin" / "flight_telemetry_project"
    stale_apps = tmp_path / "agi-space" / "apps"
    source_project.mkdir(parents=True)
    stale_apps.mkdir(parents=True)
    events: list[tuple[str, str]] = []
    fake_environ: dict[str, str] = {}

    class FakeAgiEnv:
        persisted: dict[str, str] = {
            "APPS_PATH": str(stale_apps),
            "IS_SOURCE_ENV": "0",
            "IS_WORKER_ENV": "0",
        }

        @classmethod
        def set_env_var(cls, key: str, value: str) -> None:
            events.append(("set", f"{key}={value}"))
            cls.persisted[key] = value

        def __init__(self, *, apps_path: Path, verbose: int = 1):
            events.append(("init", f"IS_SOURCE_ENV={self.persisted.get('IS_SOURCE_ENV')}"))
            self.apps_path = apps_path
            self.builtin_apps_path = apps_path / "builtin"
            self.apps_repository_root = None
            self.verbose = verbose
            self.app = "flight_telemetry_project"
            self.active_app = self.builtin_apps_path / self.app
            self.projects = {"flight_telemetry_project"}
            self.is_source_env = self.persisted.get("IS_SOURCE_ENV") == "1"
            self.is_worker_env = self.persisted.get("IS_WORKER_ENV") == "1"
            self.OPENAI_API_KEY = ""
            self.CLUSTER_CREDENTIALS = ""
            self.envars = dict(self.persisted)
            self.init_done = False

    fake_st = _FakeStreamlit()
    ports, _port_calls = _make_bootstrap_ports(
        FakeAgiEnv,
        services_enabled=False,
        last_app=stale_apps / "builtin" / "flight_telemetry_project",
        environ=fake_environ,
    )
    monkeypatch.setattr(bootstrap, "resolve_apps_path", lambda *_args, **_kwargs: source_apps)

    result = bootstrap.bootstrap_page_environment(
        streamlit=fake_st,
        env_file_path=tmp_path / ".env",
        load_env_file_map=lambda _path: {
            "APPS_PATH": str(stale_apps),
            "IS_SOURCE_ENV": "0",
            "IS_WORKER_ENV": "0",
        },
        logger=object(),
        apply_active_app_request=lambda env, requested: bootstrap.apply_active_app_request(
            env,
            requested,
            streamlit=fake_st,
        ),
        handle_data_root_failure=lambda *_args, **_kwargs: False,
        refresh_env_from_file=lambda _env: None,
        clean_openai_key=lambda value: value,
        store_cluster_credentials=lambda *_args, **_kwargs: True,
        argv=[],
        ports=ports,
    )

    assert result.env.is_source_env is True
    assert result.env.active_app == source_project
    assert fake_environ["APPS_PATH"] == str(source_apps.resolve(strict=False))
    assert fake_environ["IS_SOURCE_ENV"] == "1"
    assert ("init", "IS_SOURCE_ENV=1") in events
    assert events.index(("set", "IS_SOURCE_ENV=1")) < events.index(("init", "IS_SOURCE_ENV=1"))


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


def test_bootstrap_page_environment_handles_cluster_share_startup_error(monkeypatch, tmp_path):
    bootstrap = about_agilab._about_bootstrap

    class FailingAgiEnv:
        def __init__(self, *_args, **_kwargs):
            raise RuntimeError(
                "Cluster mode requires AGI_CLUSTER_SHARE to be mounted and writable. "
                "Configured AGI_CLUSTER_SHARE='/missing/share' is not usable; env=/tmp/.env"
            )

    monkeypatch.setattr(bootstrap, "resolve_apps_path", lambda *_args, **_kwargs: tmp_path / "apps")
    ports, _port_calls = _make_bootstrap_ports(FailingAgiEnv)
    fake_st = _FakeStreamlit()
    fake_st.query_params["active_app"] = "flight_telemetry_project"

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
    error_message = _event_body(fake_st.events, "error", "Cluster mode is enabled")
    assert "Disable cluster mode and reload" in [body for kind, body in fake_st.events if kind == "button"]
    assert "AGI_CLUSTER_SHARE" in error_message


def test_bootstrap_cluster_share_startup_error_can_disable_stale_app_setting(tmp_path):
    bootstrap = about_agilab._about_bootstrap
    settings_path = tmp_path / ".agilab/apps/flight_telemetry_project/app_settings.toml"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(
        """
[args]
data_in = "flight/dataset"

[cluster]
cluster_enabled = true
user = "agi"
""",
        encoding="utf-8",
    )
    class ClickStreamlit(_FakeStreamlit):
        def __init__(self):
            super().__init__()
            self.query_params["active_app"] = "flight_telemetry_project"

        def button(self, label: str, **_kwargs):
            self.events.append(("button", label))
            return True

        def rerun(self):
            self.events.append(("rerun", ""))

    fake_st = ClickStreamlit()
    ports, _port_calls = _make_bootstrap_ports(object())
    bootstrap.handle_cluster_share_startup_error(
        streamlit=fake_st,
        exc=RuntimeError(
            "Cluster mode requires AGI_CLUSTER_SHARE to be mounted and writable. "
            "Configured AGI_CLUSTER_SHARE='/missing/share' is not usable; env=/tmp/.env"
        ),
        env_file_path=tmp_path / ".agilab/.env",
        args=bootstrap.parse_startup_args([]),
        ports=ports,
    )

    payload = settings_path.read_text(encoding="utf-8")
    assert "cluster_enabled = false" in payload
    assert ("success", f"Disabled cluster mode in `{settings_path}`.") in fake_st.events
    assert ("rerun", "") in fake_st.events
    assert fake_st.stopped is False


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
    bootstrap = about_agilab._about_bootstrap
    apps_path = tmp_path / "apps"
    app_path = apps_path / "flight_telemetry_project"
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
            self.projects = {"flight_telemetry_project"}
            self.is_source_env = True
            self.is_worker_env = False
            self.OPENAI_API_KEY = ""
            self.CLUSTER_CREDENTIALS = ""
            self.envars = {}
            self.init_done = False

    def fake_apply_active_app_request(env, request_value):
        assert request_value == str(app_path)
        env.app = "flight_telemetry_project"
        return True

    fake_st = SimpleNamespace(
        session_state={},
        query_params={},
        warnings=[],
        warning=lambda message: fake_st.warnings.append(message),
        error=lambda _message: None,
    )
    monkeypatch.setattr(
        bootstrap,
        "default_agilab_path_file",
        lambda **_kwargs: tmp_path / "missing-agilab-path",
    )
    ports, port_calls = _make_bootstrap_ports(
        FakeAgiEnv,
        services_enabled=False,
        last_app=app_path,
        environ=fake_environ,
    )
    ports = bootstrap.BootstrapPorts(
        agi_env_cls=ports.agi_env_cls,
        activate_mlflow=ports.activate_mlflow,
        background_services_enabled=ports.background_services_enabled,
        load_last_active_app=ports.load_last_active_app,
        store_last_active_app=remembered_apps.append,
        environ=ports.environ,
    )

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
        ports=ports,
    )

    assert result.env is fake_st.session_state["env"]
    assert result.should_rerun is False
    assert result.handled_recovery is False
    assert result.env.init_done is True
    assert fake_st.session_state["first_run"] is False
    assert fake_st.query_params["active_app"] == "flight_telemetry_project"
    assert remembered_apps == [apps_path / "flight_telemetry_project"]
    assert port_calls.activated == []
    assert refreshed_envs == [result.env]
    assert ("APPS_PATH", str(apps_path)) not in set_env_calls
    assert ("IS_SOURCE_ENV", "1") in set_env_calls
    assert fake_st.warnings == []


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


def test_bootstrap_resolve_apps_path_prefers_source_marker_over_stale_env(tmp_path):
    bootstrap = about_agilab._about_bootstrap
    source_root = tmp_path / "agilab-src" / "src" / "agilab"
    source_apps = source_root / "apps"
    stale_apps = tmp_path / "agi-space" / "apps"
    source_root.mkdir(parents=True)
    stale_apps.mkdir(parents=True)
    marker = tmp_path / ".local/share/agilab/.agilab-path"
    marker.parent.mkdir(parents=True)
    marker.write_text(str(source_root), encoding="utf-8")

    args = bootstrap.parse_startup_args([])
    assert bootstrap.resolve_apps_path(
        args,
        env_file_path=tmp_path / ".env",
        load_env_file_map=lambda _path: {"APPS_PATH": str(stale_apps)},
        home_path=tmp_path,
    ) == source_apps.resolve(strict=False)


def test_bootstrap_source_launch_env_updates_normalizes_builtin_source_root(tmp_path):
    bootstrap = about_agilab._about_bootstrap
    source_builtin = tmp_path / "agilab-src" / "src" / "agilab" / "apps" / "builtin"

    assert bootstrap.source_launch_env_updates(source_builtin) == {
        "APPS_PATH": str(source_builtin.parent.resolve(strict=False)),
        "IS_SOURCE_ENV": "1",
        "IS_WORKER_ENV": "0",
    }


def test_bootstrap_persisted_active_app_ignores_cross_root_absolute_path(tmp_path):
    bootstrap = about_agilab._about_bootstrap
    source_apps = tmp_path / "agilab-src" / "src" / "agilab" / "apps"
    stale_project = tmp_path / "agi-space" / "apps" / "builtin" / "private_project"
    stale_project.mkdir(parents=True)
    env = SimpleNamespace(
        apps_path=source_apps,
        builtin_apps_path=source_apps / "builtin",
        apps_repository_root=None,
        projects={"flight_telemetry_project"},
    )

    assert bootstrap.persisted_active_app_request(env, stale_project) is None


def test_bootstrap_persisted_active_app_maps_cross_root_absolute_path_to_local_project(tmp_path):
    bootstrap = about_agilab._about_bootstrap
    source_apps = tmp_path / "agilab-src" / "src" / "agilab" / "apps"
    source_project = source_apps / "builtin" / "flight_telemetry_project"
    stale_project = tmp_path / "agi-space" / "apps" / "builtin" / "flight_telemetry_project"
    source_project.mkdir(parents=True)
    stale_project.mkdir(parents=True)
    env = SimpleNamespace(
        apps_path=source_apps,
        builtin_apps_path=source_apps / "builtin",
        apps_repository_root=None,
        projects=set(),
    )

    assert bootstrap.persisted_active_app_request(env, stale_project) == "flight_telemetry_project"


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
    assert not [message for event, message in fake_st.events if event == "warning"]


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
    with pytest.raises(ValueError, match="AGI_CLUSTER_SHARE"):
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

    assert content["title"] == (
        "First proof with flight-telemetry-project: verify AGILAB end-to-end"
    )
    assert "sample data and expected outputs" in content["intro"]
    assert content["recommended_path_id"] == "source-checkout-first-proof"
    assert content["actionable_route_ids"] == ["source-checkout-first-proof"]
    assert content["documented_route_ids"] == ["notebook-quickstart"]
    assert [label for label, _ in content["steps"]] == [
        "DEMO",
        "ORCHESTRATE",
        "ANALYSIS",
    ]
    assert any("flight_telemetry_project" in detail for _, detail in content["steps"])
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


def test_about_layout_rejects_placeholder_openai_keys():
    layout = about_agilab._about_layout

    assert layout.clean_openai_key(None) is None
    assert layout.clean_openai_key("") is None
    assert layout.clean_openai_key(" your-key ") is None
    assert layout.clean_openai_key("sk-XXXX") is None
    assert layout.clean_openai_key("short") is None
    assert layout.clean_openai_key(" sk-" + "a" * 16 + " ") == "sk-" + "a" * 16


def test_about_layout_openai_status_banner_is_silent_without_valid_key(
    tmp_path,
    monkeypatch,
):
    layout = about_agilab._about_layout
    fake_st = _FakeStreamlit()
    monkeypatch.setattr(layout, "st", fake_st)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    layout.openai_status_banner(
        SimpleNamespace(OPENAI_API_KEY="your-key"),
        env_file_path=tmp_path / ".env",
    )

    assert not fake_st.events

    fake_st.events.clear()
    monkeypatch.setenv("OPENAI_API_KEY", "sk-" + "a" * 16)

    layout.openai_status_banner(
        SimpleNamespace(OPENAI_API_KEY="your-key"),
        env_file_path=tmp_path / ".env",
    )

    assert not [body for kind, body in fake_st.events if kind == "warning"]


def test_about_page_openai_status_banner_repairs_cached_layout_without_os(monkeypatch):
    layout = about_agilab._about_layout
    fake_st = _FakeStreamlit()
    monkeypatch.setattr(about_agilab, "st", fake_st)
    monkeypatch.delattr(layout, "os")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    about_agilab.openai_status_banner(SimpleNamespace(OPENAI_API_KEY="your-key"))

    assert layout.os is about_agilab.os
    assert not fake_st.events


def test_system_information_summary_handles_unknown_cpu(monkeypatch):
    layout = about_agilab._about_layout

    monkeypatch.setattr(layout.platform, "system", lambda: "")
    monkeypatch.setattr(layout.platform, "release", lambda: "")
    monkeypatch.setattr(layout.platform, "processor", lambda: "")
    monkeypatch.setattr(layout.platform, "machine", lambda: "")
    monkeypatch.setattr(layout.os, "cpu_count", lambda: None)
    monkeypatch.setattr(layout, "_physical_cpu_count", lambda: None)

    assert layout.system_information_summary() == ("Unknown OS", "Unknown CPU")


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


def test_system_information_summary_uses_machine_when_processor_is_missing(monkeypatch):
    layout = about_agilab._about_layout

    monkeypatch.setattr(layout.platform, "system", lambda: "Linux")
    monkeypatch.setattr(layout.platform, "release", lambda: "6.8.0")
    monkeypatch.setattr(layout.platform, "processor", lambda: "")
    monkeypatch.setattr(layout.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(layout.os, "cpu_count", lambda: None)
    monkeypatch.setattr(layout, "_physical_cpu_count", lambda: None)

    assert layout.system_information_summary() == ("Linux 6.8.0", "x86_64")


def test_about_sidebar_hardware_helpers_parse_cluster_endpoints():
    layout = about_agilab._about_layout

    assert layout._scheduler_host("tcp://scheduler.example:8786") == "scheduler.example"
    assert layout._scheduler_host("192.168.20.111:8786") == "192.168.20.111"
    assert layout._scheduler_host("[2001:db8::1]:8786") == "2001:db8::1"
    assert layout._scheduler_host("agi@192.168.20.130") == "agi@192.168.20.130"
    assert layout._scheduler_display("tcp://scheduler.example:8786", cluster_enabled=True) == "scheduler.example:8786"
    assert layout._scheduler_display("192.168.20.111", cluster_enabled=True) == "192.168.20.111:8786"
    assert layout._scheduler_display("agi@192.168.20.130", cluster_enabled=True) == "192.168.20.130:8786"
    assert layout._parse_hardware_probe_output("CPU=AMD EPYC\nRAM=128 GB\n") == {
        "CPU": "AMD EPYC",
        "RAM": "128 GB",
        "GPU": "Not detected",
        "NPU": "Not detected",
    }
    assert layout._lspci_gpu_summary(
        "65:00.0 VGA compatible controller: NVIDIA Corporation GA102 [GeForce RTX 3080] (rev a1)\n"
        "65:00.1 Audio device: NVIDIA Corporation GA102 High Definition Audio Controller (rev a1)\n"
    ) == "RTX 3080"
    assert "lspci" in layout._remote_hardware_probe_command()


def test_about_layout_helpers_cover_display_fallbacks(tmp_path, monkeypatch):
    import agi_gui.pagelib as pagelib

    fake_st = _FakeStreamlit()
    monkeypatch.setattr(about_agilab, "st", fake_st)
    monkeypatch.setattr(
        about_agilab._about_layout,
        "_node_hardware_summary",
        lambda *_args, **_kwargs: {
            "CPU": "Test CPU; cores: 16",
            "RAM": "64 GB",
            "GPU": "Test GPU",
            "NPU": "Test NPU",
        },
    )
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
        ],
    )
    about_agilab._about_layout.render_package_versions()
    about_agilab._about_layout.render_system_information()
    fake_st.session_state["app_settings"] = {
        "cluster": {
            "cluster_enabled": True,
            "scheduler": "10.0.0.1:8786",
            "workers": {"10.0.0.2": 2},
            "workers_data_path": "/mnt/agilab",
        }
    }
    about_agilab._about_layout.render_execution_context_panel(SimpleNamespace(app="flight_telemetry_project"))
    about_agilab._about_layout.render_footer()

    assert about_agilab._clean_openai_key("sk-" + "a" * 16) == "sk-" + "a" * 16
    assert any("Welcome to AGILAB" in body for kind, body in fake_st.events if kind == "info")
    assert any("agilab-next" in body for kind, body in fake_st.events if kind == "markdown")
    assert any("agilab:" in body for kind, body in fake_st.events if kind == "write")
    assert any("agi-gui:" in body for kind, body in fake_st.events if kind == "write")
    assert any("OS:" in body for kind, body in fake_st.events if kind == "write")
    assert not any("OS:" in body for kind, body in fake_st.events if kind == "sidebar.caption")
    assert not any("agilab-execution-context" in body for kind, body in fake_st.events if kind == "markdown")
    assert not any("Execution environment" in body for kind, body in fake_st.events if kind == "markdown")
    assert not any("ORCHESTRATE context" in body for kind, body in fake_st.events if kind == "markdown")
    assert not any("2020-" in body for kind, body in fake_st.events if kind == "markdown")


def test_landing_page_keeps_about_header_before_first_proof_only(tmp_path, monkeypatch):
    fake_st = _FakeStreamlit()
    rendered: list[tuple[str, str]] = []
    env = SimpleNamespace(app="flight_telemetry_project")

    monkeypatch.setattr(about_agilab, "st", fake_st)
    monkeypatch.setattr(about_agilab, "quick_logo", lambda _path: rendered.append(("logo", "")))
    monkeypatch.setattr(
        about_agilab,
        "render_newcomer_first_proof",
        lambda target_env: rendered.append(("first_proof", target_env.app)),
    )
    monkeypatch.setattr(
        about_agilab,
        "display_landing_page",
        lambda _path: rendered.append(("unexpected_after_first_demo", "AGILAB")),
    )

    about_agilab.show_banner_and_intro(tmp_path, env)

    assert not any(kind == "tabs" for kind, _body in fake_st.events)
    assert rendered == [
        ("logo", ""),
        ("first_proof", "flight_telemetry_project"),
    ]


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
    assert "AGILAB" in about_menu["About"]
    assert "Reproducible AI engineering, from project to proof." in about_menu["About"]
    assert "Support: open a GitHub issue" in about_menu["About"]
    assert "Data Science in Engineering" not in about_menu["About"]
    assert about_menu["Get help"] == "https://thalesgroup.github.io/agilab/agilab-help.html"


def test_main_page_sidebar_keeps_settings_link_without_execution_context(monkeypatch):
    fake_st = _FakeStreamlit()
    monkeypatch.setattr(about_agilab, "st", fake_st)
    monkeypatch.setattr(
        about_agilab._about_layout,
        "_node_hardware_summary",
        lambda *_args, **_kwargs: {
            "CPU": "Synthetic CPU; cores: 32",
            "RAM": "128 GB",
            "GPU": "NVIDIA A100 (108 SMs)",
            "NPU": "Not detected",
        },
    )
    fake_st.session_state["app_settings"] = {
        "cluster": {
            "cluster_enabled": True,
            "pool": True,
            "scheduler": "192.168.20.111:8786",
            "workers": {"192.168.20.130": 1},
            "workers_data_path": "/home/agi/clustershare",
        }
    }
    rendered_versions: list[str] = []
    monkeypatch.setattr(about_agilab, "render_sidebar_version", rendered_versions.append)
    monkeypatch.setattr(about_agilab, "detect_agilab_version", lambda _env: "2026.4.28")
    monkeypatch.setattr(about_agilab, "docs_menu_url", lambda _html_file: "https://docs.example/agilab-help.html")
    monkeypatch.setattr(about_agilab, "_render_env_editor", lambda _env: None)
    env = SimpleNamespace(
        app="flight_telemetry_project",
        apps_path=Path("/tmp/agilab/apps"),
        agi_share_path_abs=Path("/tmp/agilab/localshare"),
        AGILAB_LOG_ABS=Path("/tmp/agilab/log"),
        TABLE_MAX_ROWS=100,
        GUI_SAMPLING=10,
    )

    about_agilab.page(env)

    expanders = [body for kind, body in fake_st.events if kind == "expander"]
    assert not any("Environment Variables" in label for label in expanders)
    assert "Runtime diagnostics:False" not in expanders
    assert "Installed package versions:False" not in expanders
    assert "System information:False" not in expanders
    assert rendered_versions == ["2026.4.28"]
    sidebar_markdowns = [body for kind, body in fake_st.events if kind == "sidebar.markdown"]
    sidebar_markup = "\n".join(sidebar_markdowns)
    assert "[Settings](/SETTINGS)" in sidebar_markdowns
    assert "[Documentation](https://docs.example/agilab-help.html)" in sidebar_markdowns
    assert "[Settings](/SETTINGS)" in sidebar_markup
    assert "[Documentation](https://docs.example/agilab-help.html)" in sidebar_markup
    assert "agilab-sidebar-system" not in sidebar_markup
    assert "Active project" not in sidebar_markup
    assert "Scheduler" not in sidebar_markup
    assert "Worker 192.168.20.130" not in sidebar_markup
    assert not any("OS:" in body for kind, body in fake_st.events if kind == "sidebar.caption")


def test_settings_page_renders_environment_and_runtime_controls(monkeypatch):
    fake_st = _FakeStreamlit()
    monkeypatch.setattr(about_agilab, "st", fake_st)
    monkeypatch.setattr(
        about_agilab,
        "_render_env_editor",
        lambda _env: fake_st.events.append(("env_editor", "rendered")),
    )
    rendered_versions: list[str] = []
    monkeypatch.setattr(about_agilab, "render_sidebar_version", rendered_versions.append)
    monkeypatch.setattr(about_agilab, "detect_agilab_version", lambda _env: "2026.4.28")
    env = SimpleNamespace(
        app="flight_telemetry_project",
        apps_path=Path("/tmp/agilab/apps"),
        agi_share_path_abs=Path("/tmp/agilab/localshare"),
        AGILAB_LOG_ABS=Path("/tmp/agilab/log"),
        TABLE_MAX_ROWS=100,
        GUI_SAMPLING=10,
    )

    about_agilab.settings_page(env)

    assert ("markdown", "## Settings") in fake_st.events
    assert ("markdown", "#### Runtime diagnostics") in fake_st.events
    assert ("selectbox", "Diagnostics level") in fake_st.events
    assert ("env_editor", "rendered") in fake_st.events
    assert rendered_versions == ["2026.4.28"]


def test_navigation_page_file_runner_executes_guarded_page_main(tmp_path, monkeypatch) -> None:
    marker = tmp_path / "page-ran.txt"
    page_file = tmp_path / "sample_page.py"
    page_file.write_text(
        "from pathlib import Path\n"
        "def main():\n"
        f"    Path({str(marker)!r}).write_text('ok', encoding='utf-8')\n"
        "if __name__ == '__main__':\n"
        "    raise RuntimeError('guard should not be executed by import wrapper')\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        about_agilab,
        "_ensure_navigation_environment",
        lambda *_args, **_kwargs: object(),
    )

    runner = about_agilab._page_file_runner(page_file)
    runner()

    assert marker.read_text(encoding="utf-8") == "ok"


def test_active_app_cluster_information_prefers_active_app_settings_file(tmp_path, monkeypatch):
    fake_st = _FakeStreamlit()
    monkeypatch.setattr(about_agilab._about_layout, "st", fake_st)
    monkeypatch.setattr(
        about_agilab._about_layout,
        "_node_hardware_summary",
        lambda *_args, **_kwargs: {
            "CPU": "Fresh CPU; cores: 24",
            "RAM": "96 GB",
            "GPU": "Fresh GPU",
            "NPU": "Fresh NPU",
        },
    )
    fake_st.session_state["app_settings"] = {
        "cluster": {
            "cluster_enabled": True,
            "scheduler": "stale.scheduler:8786",
        }
    }
    settings_file = tmp_path / "app_settings.toml"
    settings_file.write_text(
        """
[cluster]
cluster_enabled = true
cython = true
scheduler = "fresh.scheduler"
workers_data_path = "/fresh/share"

[cluster.workers]
"worker-a" = 2
""",
        encoding="utf-8",
    )

    lines = dict(
        about_agilab._about_layout.active_app_cluster_information_lines(
            SimpleNamespace(app="flight_telemetry_project", app_settings_file=settings_file)
        )
    )

    assert lines["Active project"] == "flight_telemetry_project"
    assert lines["Scheduler"] == "fresh.scheduler:8786"
    assert lines["Mode"] == "enabled (dask, cython)"
    assert lines["Share"] == "/fresh/share"
    assert lines["CPU"] == "48 cores"
    assert lines["RAM"] == "192 GB"
    assert lines["GPU"] == "2 x Fresh GPU"
    assert lines["NPU"] == "2 x Fresh NPU"
    assert not any(label.startswith("Worker ") for label, _value in lines.items())


def test_active_app_cluster_information_hides_cluster_share_when_cluster_disabled(monkeypatch):
    layout = about_agilab._about_layout
    fake_st = _FakeStreamlit()
    fake_st.session_state["app_settings"] = {
        "cluster": {
            "cluster_enabled": False,
            "pool": True,
            "cython": True,
            "rapids": True,
        }
    }
    monkeypatch.setattr(layout, "st", fake_st)
    monkeypatch.setattr(
        layout,
        "_node_hardware_summary",
        lambda *_args, **_kwargs: {
            "CPU": "HF CPU; cores: 8",
            "RAM": "124 GB",
            "GPU": "Not detected",
            "NPU": "Not detected",
        },
    )

    lines = dict(
        layout.active_app_cluster_information_lines(
            SimpleNamespace(
                app="flight_telemetry_project",
                AGI_CLUSTER_SHARE="/home/user/clustershare",
                AGI_LOCAL_SHARE="/home/user/localshare",
            )
        )
    )

    assert lines["Scheduler"] == "local process"
    assert lines["Mode"] == "local (pool, cython, rapids available)"
    assert lines["Share"] == "not used"
    assert lines["CPU"] == "8 cores"
    assert lines["RAM"] == "124 GB"
    assert lines["GPU"] == "Not detected"
    assert lines["NPU"] == "Not detected"


def test_active_app_cluster_information_counts_duplicate_scheduler_once(monkeypatch):
    monkeypatch.setattr(
        about_agilab._about_layout,
        "_node_hardware_summary",
        lambda *_args, **_kwargs: {
            "CPU": "Apple M4 Max; cores: 16",
            "RAM": "48 GB",
            "GPU": "Apple M4 Max",
            "NPU": "Apple Neural Engine (16 cores)",
        },
    )
    fake_st = _FakeStreamlit()
    fake_st.session_state["app_settings"] = {
        "cluster": {
            "cluster_enabled": True,
            "scheduler": "192.168.20.111:8786",
            "workers": {"192.168.20.111": 1},
            "workers_data_path": "/Users/agi/clustershare/agi",
        }
    }
    monkeypatch.setattr(about_agilab._about_layout, "st", fake_st)

    lines = dict(
        about_agilab._about_layout.active_app_cluster_information_lines(
            SimpleNamespace(app="flight_telemetry_project")
        )
    )

    assert lines["CPU"] == "16 cores"
    assert lines["RAM"] == "48 GB"
    assert lines["GPU"] == "Apple M4 Max"
    assert lines["NPU"] == "Apple Neural Engine (16 cores)"


def test_active_app_cluster_information_uses_local_alias_and_cached_remote_gpu(monkeypatch, tmp_path):
    layout = about_agilab._about_layout
    cache_path = tmp_path / ".agilab" / "lan_nodes.json"
    cache_path.parent.mkdir(parents=True)
    cache_path.write_text(
        json.dumps(
            {
                "nodes": [
                    {
                        "host": "192.168.20.15",
                        "status": "ready",
                        "cpu": "Intel Core i9; cores: 36",
                        "ram": "251 GB",
                        "gpu": "RTX 3080",
                        "npu": "Not detected",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    def fake_remote_probe(host: str, _user: str, _ssh_key_path: str) -> str:
        if host != "192.168.20.15":
            raise AssertionError(f"local scheduler should not be probed over SSH: {host}")
        return "CPU=Intel Core i9; cores: 36\nRAM=251 GB\nGPU=\nNPU=\n"

    fake_st = _FakeStreamlit()
    fake_st.session_state["app_settings"] = {
        "cluster": {
            "cluster_enabled": True,
            "scheduler": "192.168.20.111:8786",
            "workers": {"192.168.20.111": 1, "192.168.20.15": 1},
            "workers_data_path": "/Users/agi/clustershare/agi",
        }
    }
    monkeypatch.setattr(layout, "st", fake_st)
    monkeypatch.setattr(layout.Path, "home", classmethod(lambda _cls: tmp_path))
    monkeypatch.setattr(
        layout,
        "_local_node_aliases",
        lambda: frozenset({"", "local", "localhost", "127.0.0.1", "192.168.20.111"}),
    )
    monkeypatch.setattr(
        layout,
        "_local_hardware_summary",
        lambda: {
            "CPU": "Apple M4 Max; cores: 16",
            "RAM": "48 GB",
            "GPU": "Apple M4 Max",
            "NPU": "Apple Neural Engine (16 cores)",
        },
    )
    monkeypatch.setattr(layout, "_remote_hardware_probe", fake_remote_probe)
    layout._lan_discovery_hardware_inventory.cache_clear()

    lines = dict(layout.active_app_cluster_information_lines(SimpleNamespace(app="flight_telemetry_project")))

    assert lines["CPU"] == "52 cores"
    assert lines["RAM"] == "299 GB"
    assert lines["GPU"] == "Apple M4 Max; RTX 3080"
    assert lines["NPU"] == "Apple Neural Engine (16 cores)"


def test_active_app_cluster_information_marks_unreachable_worker_hardware_unknown(monkeypatch):
    def fake_hardware(host, **_kwargs):
        if about_agilab._about_layout._scheduler_host(host) == "192.168.20.130":
            return {
                "CPU": "unreachable",
                "RAM": "unreachable",
                "GPU": "unreachable",
                "NPU": "unreachable",
            }
        return {
            "CPU": "Apple M4 Max; cores: 16",
            "RAM": "48 GB",
            "GPU": "Apple M4 Max",
            "NPU": "Apple Neural Engine (16 cores)",
        }

    monkeypatch.setattr(about_agilab._about_layout, "_node_hardware_summary", fake_hardware)
    fake_st = _FakeStreamlit()
    fake_st.session_state["app_settings"] = {
        "cluster": {
            "cluster_enabled": True,
            "scheduler": "192.168.20.111:8786",
            "workers": {"192.168.20.111": 1, "192.168.20.130": 1},
            "workers_data_path": "/Users/agi/clustershare/agi",
        }
    }
    monkeypatch.setattr(about_agilab._about_layout, "st", fake_st)

    lines = dict(
        about_agilab._about_layout.active_app_cluster_information_lines(
            SimpleNamespace(app="flight_telemetry_project")
        )
    )

    assert lines["CPU"] == "16 cores + 1 worker unreachable"
    assert lines["RAM"] == "48 GB + 1 worker unreachable"
    assert lines["GPU"] == "Apple M4 Max + 1 worker unreachable"
    assert lines["NPU"] == "Apple Neural Engine (16 cores) + 1 worker unreachable"


def test_active_app_cluster_information_reports_worker_ssh_auth_needed(monkeypatch, tmp_path):
    layout = about_agilab._about_layout
    cache_path = tmp_path / ".agilab" / "lan_nodes.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {
                "nodes": [
                    {
                        "host": "192.168.20.15",
                        "ssh_target": "agi@192.168.20.15",
                        "status": "ssh-auth-needed",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    def fake_hardware(host, **_kwargs):
        if layout._node_identity(host) == "192.168.20.15":
            return {
                "CPU": "unreachable",
                "RAM": "unreachable",
                "GPU": "unreachable",
                "NPU": "unreachable",
            }
        return {
            "CPU": "Apple M4 Max; cores: 16",
            "RAM": "48 GB",
            "GPU": "Apple M4 Max",
            "NPU": "Apple Neural Engine (16 cores)",
        }

    fake_st = _FakeStreamlit()
    fake_st.session_state["app_settings"] = {
        "cluster": {
            "cluster_enabled": True,
            "scheduler": "127.0.0.1",
            "workers": {"192.168.20.15": 1},
            "workers_data_path": "/Users/agi/clustershare/agi",
        }
    }
    monkeypatch.setattr(layout, "st", fake_st)
    monkeypatch.setattr(layout.Path, "home", classmethod(lambda _cls: tmp_path))
    monkeypatch.setattr(layout, "_node_hardware_summary", fake_hardware)
    layout._lan_discovery_hardware_inventory.cache_clear()
    layout._remote_hardware_probe.cache_clear()

    lines = dict(layout.active_app_cluster_information_lines(SimpleNamespace(app="flight_telemetry_project")))

    assert lines["CPU"] == "16 cores + 1 worker SSH auth needed"
    assert lines["RAM"] == "48 GB + 1 worker SSH auth needed"
    assert lines["GPU"] == "Apple M4 Max + 1 worker SSH auth needed"
    assert lines["NPU"] == "Apple Neural Engine (16 cores) + 1 worker SSH auth needed"


def test_active_app_cluster_information_does_not_overstate_stale_no_ssh_port_cache(monkeypatch, tmp_path):
    layout = about_agilab._about_layout
    cache_path = tmp_path / ".agilab" / "lan_nodes.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {
                "nodes": [
                    {
                        "host": "192.168.20.15",
                        "status": "no-ssh-port",
                        "tcp_ssh_open": False,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    def fake_hardware(host, **_kwargs):
        if layout._node_identity(host) == "192.168.20.15":
            return {
                "CPU": "unreachable",
                "RAM": "unreachable",
                "GPU": "unreachable",
                "NPU": "unreachable",
            }
        return {
            "CPU": "Apple M4 Max; cores: 16",
            "RAM": "48 GB",
            "GPU": "Apple M4 Max",
            "NPU": "Apple Neural Engine (16 cores)",
        }

    fake_st = _FakeStreamlit()
    fake_st.session_state["app_settings"] = {
        "cluster": {
            "cluster_enabled": True,
            "scheduler": "127.0.0.1",
            "workers": {"192.168.20.15": 1},
            "workers_data_path": "/Users/agi/clustershare/agi",
        }
    }
    monkeypatch.setattr(layout, "st", fake_st)
    monkeypatch.setattr(layout.Path, "home", classmethod(lambda _cls: tmp_path))
    monkeypatch.setattr(layout, "_node_hardware_summary", fake_hardware)
    layout._lan_discovery_hardware_inventory.cache_clear()
    layout._remote_hardware_probe.cache_clear()

    lines = dict(layout.active_app_cluster_information_lines(SimpleNamespace(app="flight_telemetry_project")))

    assert lines["CPU"] == "16 cores + 1 worker unreachable"
    assert lines["RAM"] == "48 GB + 1 worker unreachable"
    assert lines["GPU"] == "Apple M4 Max + 1 worker unreachable"
    assert lines["NPU"] == "Apple Neural Engine (16 cores) + 1 worker unreachable"


def test_active_app_cluster_information_uses_cached_hardware_for_unreachable_worker(monkeypatch, tmp_path):
    def fake_hardware(host, **_kwargs):
        if about_agilab._about_layout._scheduler_host(host) == "192.168.20.130":
            return {
                "CPU": "unreachable",
                "RAM": "unreachable",
                "GPU": "unreachable",
                "NPU": "unreachable",
            }
        return {
            "CPU": "Apple M4 Max; cores: 16",
            "RAM": "48 GB",
            "GPU": "Apple M4 Max",
            "NPU": "Apple Neural Engine (16 cores)",
        }

    cache_path = tmp_path / "lan_nodes.json"
    cache_path.write_text(
        json.dumps(
            {
                "nodes": [
                    {
                        "host": "192.168.20.130",
                        "cpu": "AMD EPYC; cores: 32",
                        "ram": "128 GB",
                        "gpu": "NVIDIA L40S (142 SMs)",
                        "npu": "Not detected",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(about_agilab._about_layout, "_node_hardware_summary", fake_hardware)
    original_inventory = about_agilab._about_layout._lan_discovery_hardware_inventory
    monkeypatch.setattr(
        about_agilab._about_layout,
        "_lan_discovery_hardware_inventory",
        lambda _cache_path="": original_inventory(str(cache_path)),
    )
    fake_st = _FakeStreamlit()
    fake_st.session_state["app_settings"] = {
        "cluster": {
            "cluster_enabled": True,
            "scheduler": "192.168.20.111:8786",
            "workers": {"192.168.20.111": 1, "192.168.20.130": 1},
            "workers_data_path": "/Users/agi/clustershare/agi",
        }
    }
    monkeypatch.setattr(about_agilab._about_layout, "st", fake_st)

    lines = dict(
        about_agilab._about_layout.active_app_cluster_information_lines(
            SimpleNamespace(app="flight_telemetry_project")
        )
    )

    assert lines["CPU"] == "48 cores"
    assert lines["RAM"] == "176 GB"
    assert lines["GPU"] == "Apple M4 Max; NVIDIA L40S (142 SMs)"
    assert lines["NPU"] == "Apple Neural Engine (16 cores)"


def test_active_app_cluster_information_reads_lan_inventory_from_env_home(monkeypatch, tmp_path):
    layout = about_agilab._about_layout
    env_home = tmp_path / "agilab-home"
    wrong_home = tmp_path / "process-home"
    cache_path = env_home / ".agilab" / "lan_nodes.json"
    cache_path.parent.mkdir(parents=True)
    wrong_home.mkdir()
    cache_path.write_text(
        json.dumps(
            {
                "nodes": [
                    {
                        "host": "192.168.60.20",
                        "cpu": "AMD EPYC; cores: 32",
                        "ram": "128 GB",
                        "gpu": "NVIDIA L40S (142 SMs)",
                        "npu": "Not detected",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    def fake_hardware(host, **_kwargs):
        if layout._node_identity(host) == "192.168.60.20":
            return {
                "CPU": "unreachable",
                "RAM": "unreachable",
                "GPU": "unreachable",
                "NPU": "unreachable",
            }
        return {
            "CPU": "Apple M4 Max; cores: 16",
            "RAM": "48 GB",
            "GPU": "Apple M4 Max",
            "NPU": "Apple Neural Engine (16 cores)",
        }

    fake_st = _FakeStreamlit()
    fake_st.session_state["app_settings"] = {
        "cluster": {
            "cluster_enabled": True,
            "scheduler": "127.0.0.1",
            "workers": {"192.168.60.20": 1},
            "workers_data_path": "/Users/agi/clustershare/agi",
        }
    }
    monkeypatch.setattr(layout, "st", fake_st)
    monkeypatch.setattr(layout.Path, "home", classmethod(lambda _cls: wrong_home))
    monkeypatch.setattr(layout, "_node_hardware_summary", fake_hardware)
    layout._lan_discovery_hardware_inventory.cache_clear()
    layout._remote_hardware_probe.cache_clear()

    lines = dict(
        layout.active_app_cluster_information_lines(
            SimpleNamespace(app="flight_telemetry_project", home_abs=env_home)
        )
    )

    assert lines["CPU"] == "48 cores"
    assert lines["RAM"] == "176 GB"
    assert lines["GPU"] == "Apple M4 Max; NVIDIA L40S (142 SMs)"
    assert lines["NPU"] == "Apple Neural Engine (16 cores)"


def test_active_app_cluster_information_refreshes_changed_lan_inventory(monkeypatch, tmp_path):
    layout = about_agilab._about_layout
    cache_path = tmp_path / ".agilab" / "lan_nodes.json"

    def write_lan_cache(*, cpu: str, ram: str, gpu: str, npu: str) -> None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(
                {
                    "nodes": [
                        {
                            "host": "192.168.20.130",
                            "cpu": cpu,
                            "ram": ram,
                            "gpu": gpu,
                            "npu": npu,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

    def fake_hardware(host, **_kwargs):
        if layout._node_identity(host) == "192.168.20.130":
            return {
                "CPU": "unreachable",
                "RAM": "unreachable",
                "GPU": "unreachable",
                "NPU": "unreachable",
            }
        return {
            "CPU": "Apple M4 Max; cores: 16",
            "RAM": "48 GB",
            "GPU": "Apple M4 Max",
            "NPU": "Apple Neural Engine (16 cores)",
        }

    write_lan_cache(
        cpu="AMD EPYC; cores: 32",
        ram="128 GB",
        gpu="NVIDIA L40S (142 SMs)",
        npu="Not detected",
    )
    fake_st = _FakeStreamlit()
    fake_st.session_state["app_settings"] = {
        "cluster": {
            "cluster_enabled": True,
            "scheduler": "127.0.0.1",
            "workers": {"192.168.20.130": 1},
            "workers_data_path": "/Users/agi/clustershare/agi",
        }
    }
    monkeypatch.setattr(layout, "st", fake_st)
    monkeypatch.setattr(layout.Path, "home", classmethod(lambda _cls: tmp_path))
    monkeypatch.setattr(layout, "_node_hardware_summary", fake_hardware)
    layout._lan_discovery_hardware_inventory.cache_clear()
    layout._remote_hardware_probe.cache_clear()

    first_lines = dict(layout.active_app_cluster_information_lines(SimpleNamespace(app="flight_telemetry_project")))

    write_lan_cache(
        cpu="AMD EPYC; cores: 64",
        ram="256 GB",
        gpu="NVIDIA B200 (132 SMs)",
        npu="Not detected",
    )
    second_lines = dict(layout.active_app_cluster_information_lines(SimpleNamespace(app="flight_telemetry_project")))

    assert first_lines["CPU"] == "48 cores"
    assert first_lines["RAM"] == "176 GB"
    assert first_lines["GPU"] == "Apple M4 Max; NVIDIA L40S (142 SMs)"
    assert second_lines["CPU"] == "80 cores"
    assert second_lines["RAM"] == "304 GB"
    assert second_lines["GPU"] == "Apple M4 Max; NVIDIA B200 (132 SMs)"


def test_render_execution_context_panel_is_legacy_noop(monkeypatch):
    layout = about_agilab._about_layout
    fake_st = _FakeStreamlit(button_values={"Refresh cluster info": True})
    cleared: list[bool] = []
    monkeypatch.setattr(layout, "st", fake_st)
    monkeypatch.setattr(layout, "_clear_cluster_probe_caches", lambda: cleared.append(True))
    monkeypatch.setattr(
        layout,
        "active_app_cluster_information_lines",
        lambda _env: [("Active project", "flight_telemetry_project")],
    )

    layout.render_execution_context_panel(SimpleNamespace(app="flight_telemetry_project"))

    assert cleared == []
    assert fake_st.events == []


def test_about_quick_logo_renders_polished_hero(tmp_path, monkeypatch):
    import agi_gui.pagelib as pagelib

    fake_st = _FakeStreamlit()
    monkeypatch.setattr(about_agilab, "st", fake_st)
    monkeypatch.setattr(pagelib, "get_base64_of_image", lambda _path: "encoded-logo")

    about_agilab.quick_logo(tmp_path)

    body = "\n".join(body for kind, body in fake_st.events if kind == "markdown")
    assert "agilab-hero" in body
    assert "width: 100%" in body
    assert "Reproducible AI workflows" in body
    assert "agilab-hero__visual" in body
    assert "agilab-hero__target-img" in body
    assert "data:image/svg+xml;base64," in body
    assert "Digital twin assisted generalization map" in body
    assert "bias variance controls, underfit overfit symptoms, and train test diagnosis" in body
    assert '<g transform="translate(54 111)">' not in body
    assert "<svg viewBox" not in body
    assert "Thales open-source workbench" not in body
    assert "Open-source workbench" in body
    assert "Select a project, run it, and inspect the result" not in body
    assert "agilab-hero__top" in body
    assert "agilab-hero__legal-mark" in body
    assert "BSD 3-Clause</span>" in body
    assert "Thales SIX GTS France" in body
    assert "Licensed under the BSD 3-Clause License" not in body
    assert "margin: 1.55rem 0 0" not in body
    assert "text-align: right" in body
    assert "white-space: nowrap" in body
    assert "Project" in body
    assert "Run" in body
    assert "Analyse" in body
    assert "Control path" not in body
    assert "Data intake" not in body
    assert "Decision evidence" not in body


def test_about_hero_target_svg_data_uri_keeps_svg_encoded():
    prefix = "data:image/svg+xml;base64,"
    data_uri = about_agilab._about_layout._hero_target_svg_data_uri()

    assert data_uri.startswith(prefix)
    decoded = base64.b64decode(data_uri.removeprefix(prefix)).decode("utf-8")
    assert decoded.startswith("<svg ")
    assert '<g transform="translate(54 111)">' not in decoded
    assert '<g transform="translate(306 111)">' not in decoded
    assert 'viewBox="0 0 560 300"' in decoded
    assert '<g transform="translate(116 146)">' in decoded
    assert "Generalization + digital twin map" in decoded
    assert "Digital twin" in decoded
    assert "digital twin simulation symbol" in decoded
    assert "twin-divider" in decoded
    assert "sim-label" in decoded
    assert "stop-opacity" in decoded
    assert "simulate &#8596; reality" in decoded
    assert "Bias &#8596; Variance" in decoded
    assert "Controls" in decoded
    assert "Underfit &#8596; Overfit" in decoded
    assert "Symptoms" in decoded
    assert "Train vs Test" in decoded
    assert "Diagnosis" in decoded
    assert "simulate, run, diagnose, then tune the real workflow" in decoded


def test_newcomer_first_proof_state_prefers_built_in_flight_telemetry_project(tmp_path):
    apps_path = tmp_path / "apps"
    flight_telemetry_project = apps_path / "builtin" / "flight_telemetry_project"
    flight_telemetry_project.mkdir(parents=True)

    env = SimpleNamespace(
        apps_path=apps_path,
        app="mycode_project",
        AGILAB_LOG_ABS=tmp_path / "log",
    )

    state = about_agilab._newcomer_first_proof_state(env)

    assert state["project_path"] == flight_telemetry_project.resolve()
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
    assert (
        state["next_step"]
        == "Select the built-in flight-telemetry demo (`flight_telemetry_project`) from this page."
    )


def test_first_proof_progress_rows_prioritize_project_selection(tmp_path):
    apps_path = tmp_path / "apps"
    flight_telemetry_project = apps_path / "builtin" / "flight_telemetry_project"
    flight_telemetry_project.mkdir(parents=True)

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


def test_first_proof_next_action_model_guides_first_click(tmp_path):
    apps_path = tmp_path / "apps"
    flight_telemetry_project = apps_path / "builtin" / "flight_telemetry_project"
    flight_telemetry_project.mkdir(parents=True)

    select_state = about_agilab._newcomer_first_proof_state(
        SimpleNamespace(
            apps_path=apps_path,
            app="mycode_project",
            AGILAB_LOG_ABS=tmp_path / "log",
        )
    )

    select_action = about_agilab._first_proof_next_action_model(select_state)

    assert select_action["phase"] == "Next action"
    assert select_action["tone"] == "next"
    assert select_action["title"] == "Start with the known demo project"
    assert select_action["cta_label"] == "Select demo"
    assert "mycode_project" in select_action["detail"]
    assert "flight_telemetry_project" in select_action["detail"]

    run_state = about_agilab._newcomer_first_proof_state(
        SimpleNamespace(
            apps_path=apps_path,
            app="flight_telemetry_project",
            AGILAB_LOG_ABS=tmp_path / "log",
        )
    )
    run_action = about_agilab._first_proof_next_action_model(run_state)

    assert run_action["phase"] == "Next action"
    assert run_action["title"] == "Run the demo once"
    assert run_action["cta_label"] == "Open run page"
    assert "ORCHESTRATE" in run_action["detail"]
    assert "run_manifest.json" in run_action["proof_hint"]


def test_newcomer_first_proof_state_detects_generated_outputs(tmp_path):
    apps_path = tmp_path / "apps"
    flight_telemetry_project = apps_path / "flight_telemetry_project"
    flight_telemetry_project.mkdir(parents=True)
    output_dir = tmp_path / "log" / "execute" / "flight"
    output_dir.mkdir(parents=True)
    (output_dir / "AGI_install_flight_telemetry.py").write_text("# helper", encoding="utf-8")
    (output_dir / "AGI_run_flight_telemetry.py").write_text("# helper", encoding="utf-8")
    (output_dir / "forecast_metrics.json").write_text("{}", encoding="utf-8")

    env = SimpleNamespace(
        apps_path=apps_path,
        app="flight_telemetry_project",
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
    flight_telemetry_project = apps_path / "flight_telemetry_project"
    flight_telemetry_project.mkdir(parents=True)
    output_dir = tmp_path / "log" / "execute" / "flight"
    output_dir.mkdir(parents=True)
    (output_dir / "forecast_metrics.json").write_text("{}", encoding="utf-8")

    env = SimpleNamespace(
        apps_path=apps_path,
        app="flight_telemetry_project",
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
        "active_app_name": "flight_telemetry_project",
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


def test_render_newcomer_first_proof_places_wizard_before_diagnostics(
    tmp_path,
    monkeypatch,
):
    apps_path = tmp_path / "apps"
    flight_telemetry_project = apps_path / "builtin" / "flight_telemetry_project"
    flight_telemetry_project.mkdir(parents=True)
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

    wizard = _event_index(
        fake_st.events,
        "markdown",
        "**First proof: choose one path**",
    )
    proof_column = _event_index(fake_st.events, "enter_column", "0")
    separator_column = _event_index(fake_st.events, "enter_column", "1")
    notebook_column = _event_index(fake_st.events, "enter_column", "2")
    install_button = _event_index(fake_st.events, "button", "1. INSTALL demo")
    install_hint = _event_index(fake_st.events, "caption", "ORCHESTRATE `INSTALL`")
    run_button = _event_index(fake_st.events, "button", "2. EXECUTE demo")
    run_hint = _event_index(fake_st.events, "caption", "ORCHESTRATE `EXECUTE`")
    open_analysis = _event_index(fake_st.events, "button", "3. OPEN ANALYSIS")
    analysis_hint = next(
        index
        for index in range(open_analysis + 1, len(fake_st.events))
        if fake_st.events[index][0] == "caption"
        and "`view_maps`: [Open]" in fake_st.events[index][1]
    )
    separator = next(
        index
        for index, (kind, body) in enumerate(fake_st.events)
        if kind == "markdown" and body == "or"
    )
    notebook_start = _event_index(fake_st.events, "button", "Create from built-in notebook")
    notebook_hint = _event_index(
        fake_st.events,
        "caption",
        "No file to find or upload: AGILAB opens PROJECT",
    )
    proof_details = _event_index(
        fake_st.events,
        "expander",
        "If it fails / proof details:False",
    )
    progress = _event_index(fake_st.events, "markdown", "**Progress**")
    validated_path = _event_index(fake_st.events, "caption", "Validated path:")

    assert [body for kind, body in fake_st.events if kind == "expander"] == [
        "If it fails / proof details:False",
    ]
    assert not any(
        "First proof path:" in body
        for kind, body in fake_st.events
        if kind == "caption"
    )
    pre_details = fake_st.events[:proof_details]
    assert [body for kind, body in pre_details if kind == "markdown"] == [
        "**First proof: choose one path**",
        "or",
    ]
    expected_spec, expected_width = about_agilab._about_onboarding._first_proof_action_columns_layout(
        about_agilab._about_onboarding._first_proof_wizard_steps({}),
    )
    assert ("columns", "3") in pre_details
    assert ("columns_spec", ",".join(str(item) for item in expected_spec)) in pre_details
    assert ("columns_width", str(expected_width)) in pre_details
    assert expected_width != 420
    caption_bodies = [body for kind, body in pre_details if kind == "caption"]
    assert len(caption_bodies) == 8
    assert caption_bodies[0] == (
        "Recommended: run the built-in demo. Notebook import is optional: use AGILAB's included "
        "notebook with no file to find."
    )
    assert caption_bodies[1] == "Runs ORCHESTRATE `INSTALL` for `flight_telemetry_project`."
    assert caption_bodies[2] == "Runs ORCHESTRATE `EXECUTE` for the same demo."
    assert caption_bodies[3].startswith("`view_maps`: [Open](/ANALYSIS?")
    assert "active_app=flight_telemetry_project" in caption_bodies[3]
    assert "current_page=" in caption_bodies[3]
    assert caption_bodies[4] == "Notebook import: included sample"
    assert caption_bodies[5] == (
        "No file to find or upload: AGILAB opens PROJECT with its bundled notebook already selected."
    )
    assert caption_bodies[6] == (
        "Then click PROJECT `Create`; it builds `flight_telemetry_from_notebook_project`."
    )
    assert caption_bodies[7] == "After creation, run ORCHESTRATE `INSTALL` and `EXECUTE`."
    assert not [body for kind, body in pre_details if kind == "file_uploader"]
    assert not [body for kind, body in pre_details if kind == "download_button"]
    assert not [body for kind, body in pre_details if kind == "page_link"]
    assert not any(
        "agilab-proof" in body
        for kind, body in fake_st.events
        if kind == "markdown"
    )
    assert ("button", "1. Select demo") not in fake_st.events
    assert wizard < proof_column < install_button < install_hint < run_button < run_hint < open_analysis
    assert open_analysis < analysis_hint < separator_column < separator < notebook_column
    assert notebook_column < notebook_start < notebook_hint < proof_details
    assert proof_details < progress < validated_path


def test_about_first_proof_buttons_keep_compact_width():
    source = Path("src/agilab/about_page/onboarding.py").read_text(encoding="utf-8")

    assert 'width="stretch"' not in source
    assert "width=420" not in source
    assert source.count('width="content"') >= 2


def test_first_proof_action_columns_width_tracks_longest_text():
    onboarding = about_agilab._about_onboarding
    short_spec, short_width = onboarding._first_proof_action_columns_layout(
        [{"button": "Run", "hint": "Then run."}],
        notebook_hint="Upload.",
    )
    long_spec, long_width = onboarding._first_proof_action_columns_layout(
        [{"button": "Run", "hint": "Then press `INSTALL`, then `EXECUTE`."}],
        notebook_hint="Upload.",
    )

    assert long_spec[0] > short_spec[0]
    assert long_width > short_width


def test_first_proof_action_columns_width_uses_visible_link_text():
    onboarding = about_agilab._about_onboarding

    plain_width = onboarding._first_proof_visible_text_length("Open here.")
    linked_width = onboarding._first_proof_visible_text_length(
        "Open [Open](/ANALYSIS?current_page=/very/long/path/to/view_maps.py)."
    )

    assert linked_width == plain_width


def test_first_proof_page_urls_preserve_targeted_query_params():
    onboarding = about_agilab._about_onboarding

    assert onboarding._first_proof_page_url("PROJECT") == "/PROJECT"

    project_url = onboarding._first_proof_page_url(
        "PROJECT",
        {"active_app": "flight telemetry", "start": "notebook-import"},
    )
    parsed_project_url = urlparse(project_url)
    assert parsed_project_url.path == "/PROJECT"
    assert parse_qs(parsed_project_url.query) == {
        "active_app": ["flight telemetry"],
        "start": ["notebook-import"],
    }

    analysis_url = onboarding._first_proof_analysis_view_maps_url()
    parsed_analysis_url = urlparse(analysis_url)
    analysis_params = parse_qs(parsed_analysis_url.query)

    assert parsed_analysis_url.path == "/ANALYSIS"
    assert analysis_params["active_app"] == ["flight_telemetry_project"]
    assert analysis_params["current_page"][0].endswith("view_maps.py")


def test_first_proof_text_column_width_has_stable_floor():
    onboarding = about_agilab._about_onboarding

    assert (
        onboarding._first_proof_text_column_width_px([])
        == onboarding._FIRST_PROOF_ACTION_MIN_COLUMN_WIDTH_PX
    )
    assert (
        onboarding._first_proof_text_column_width_px(["x"])
        == onboarding._FIRST_PROOF_ACTION_MIN_COLUMN_WIDTH_PX
    )


def test_about_first_proof_removes_duplicate_overview_banner():
    source = Path("src/agilab/about_page/onboarding.py").read_text(encoding="utf-8")

    assert "_first_proof_overview_html" not in source
    assert "agilab-proof" not in source
    assert "radial-gradient" not in source
    assert "linear-gradient" not in source
    assert "box-shadow" not in source


def test_first_proof_wizard_omits_redundant_select_demo_step(
    tmp_path,
    monkeypatch,
):
    apps_path = tmp_path / "apps"
    flight_telemetry_project = apps_path / "builtin" / "flight_telemetry_project"
    flight_telemetry_project.mkdir(parents=True)
    fake_st = _FakeStreamlit()
    env = SimpleNamespace(
        apps_path=apps_path,
        app="mycode_project",
        AGILAB_LOG_ABS=tmp_path / "log",
        st_resources=tmp_path / "resources",
    )
    activated: list[Path] = []

    def activate_project(target_env, project_path):
        activated.append(project_path)
        target_env.app = "flight_telemetry_project"
        return True

    monkeypatch.setattr(about_agilab._about_onboarding, "st", fake_st)

    about_agilab._about_onboarding.render_newcomer_first_proof(
        env,
        activate_project=activate_project,
        display_landing_page=lambda _path: None,
    )

    assert activated == []
    assert ("button", "1. Select demo") not in fake_st.events
    assert ("button", "1. INSTALL demo") in fake_st.events
    assert ("button", "2. EXECUTE demo") in fake_st.events
    assert ("button", "3. OPEN ANALYSIS") in fake_st.events
    assert not any(kind == "switch_page" for kind, _body in fake_st.events)


def test_first_proof_wizard_project_action_selects_demo_and_reruns(
    tmp_path,
    monkeypatch,
):
    apps_path = tmp_path / "apps"
    flight_telemetry_project = apps_path / "builtin" / "flight_telemetry_project"
    flight_telemetry_project.mkdir(parents=True)
    fake_st = _FakeStreamlit()
    env = SimpleNamespace(app="mycode_project")
    state = {
        "project_available": True,
        "project_path": flight_telemetry_project.resolve(),
        "current_app_matches": False,
    }
    activated: list[Path] = []

    def activate_project(target_env, project_path):
        activated.append(project_path)
        target_env.app = "flight_telemetry_project"
        return True

    monkeypatch.setattr(about_agilab._about_onboarding, "st", fake_st)

    about_agilab._about_onboarding._handle_first_proof_wizard_action(
        "project",
        env,
        state,
        activate_project,
        page_routes=None,
    )

    assert activated == [flight_telemetry_project.resolve()]
    assert fake_st.session_state["first_proof_feedback"] == (
        "`flight_telemetry_project` selected. Next: open the run page."
    )
    assert ("rerun", "") in fake_st.events
    assert not any(kind == "switch_page" for kind, _body in fake_st.events)


def test_first_proof_wizard_install_missing_project_does_not_queue_action(
    monkeypatch,
):
    fake_st = _FakeStreamlit(button_values={"1. INSTALL demo": True})
    env = SimpleNamespace(app="mycode_project")
    state = {
        "project_available": False,
        "project_path": None,
        "current_app_matches": False,
    }

    monkeypatch.setattr(about_agilab._about_onboarding, "st", fake_st)

    about_agilab._about_onboarding._handle_first_proof_wizard_action(
        "install",
        env,
        state,
        activate_project=lambda _env, _path: pytest.fail("missing project must not activate"),
        page_routes=None,
    )

    assert any(
        kind == "error" and "built-in flight-telemetry project is missing" in body
        for kind, body in fake_st.events
    )
    assert "_orchestrate_pending_install_action" not in fake_st.session_state
    assert not any(kind == "switch_page" for kind, _body in fake_st.events)


def test_first_proof_wizard_install_click_selects_demo_and_queues_install(
    tmp_path,
    monkeypatch,
):
    apps_path = tmp_path / "apps"
    flight_telemetry_project = apps_path / "builtin" / "flight_telemetry_project"
    flight_telemetry_project.mkdir(parents=True)
    fake_st = _FakeStreamlit(button_values={"1. INSTALL demo": True})
    env = SimpleNamespace(
        apps_path=apps_path,
        app="mycode_project",
        AGILAB_LOG_ABS=tmp_path / "log",
        st_resources=tmp_path / "resources",
    )
    activated: list[Path] = []

    def activate_project(target_env, project_path):
        activated.append(project_path)
        target_env.app = "flight_telemetry_project"
        return True

    monkeypatch.setattr(about_agilab._about_onboarding, "st", fake_st)

    about_agilab._about_onboarding.render_newcomer_first_proof(
        env,
        activate_project=activate_project,
        display_landing_page=lambda _path: None,
    )

    assert activated == [flight_telemetry_project.resolve()]
    assert fake_st.session_state["_orchestrate_pending_install_action"] == "install"
    assert fake_st.session_state["show_install"] is True
    assert ("switch_page", "pages/2_ORCHESTRATE.py") in fake_st.events


def test_first_proof_wizard_run_click_selects_demo_and_queues_run(
    tmp_path,
    monkeypatch,
):
    apps_path = tmp_path / "apps"
    flight_telemetry_project = apps_path / "builtin" / "flight_telemetry_project"
    flight_telemetry_project.mkdir(parents=True)
    fake_st = _FakeStreamlit(button_values={"2. EXECUTE demo": True})
    env = SimpleNamespace(
        apps_path=apps_path,
        app="mycode_project",
        AGILAB_LOG_ABS=tmp_path / "log",
        st_resources=tmp_path / "resources",
    )
    activated: list[Path] = []

    def activate_project(target_env, project_path):
        activated.append(project_path)
        target_env.app = "flight_telemetry_project"
        return True

    monkeypatch.setattr(about_agilab._about_onboarding, "st", fake_st)

    about_agilab._about_onboarding.render_newcomer_first_proof(
        env,
        activate_project=activate_project,
        display_landing_page=lambda _path: None,
    )

    assert activated == [flight_telemetry_project.resolve()]
    assert fake_st.session_state["_orchestrate_pending_action"] == "run"
    assert fake_st.session_state["show_run"] is True
    assert ("switch_page", "pages/2_ORCHESTRATE.py") in fake_st.events


def test_first_proof_wizard_uses_registered_navigation_page_object(
    tmp_path,
    monkeypatch,
):
    class PageRoute:
        def __init__(self, name: str):
            self.name = name

        def __str__(self) -> str:
            return self.name

    apps_path = tmp_path / "apps"
    flight_telemetry_project = apps_path / "builtin" / "flight_telemetry_project"
    flight_telemetry_project.mkdir(parents=True)
    fake_st = _FakeStreamlit(button_values={"1. INSTALL demo": True})
    env = SimpleNamespace(
        apps_path=apps_path,
        app="flight_telemetry_project",
        AGILAB_LOG_ABS=tmp_path / "log",
        st_resources=tmp_path / "resources",
    )

    monkeypatch.setattr(about_agilab, "st", fake_st)
    monkeypatch.setattr(about_agilab, "display_landing_page", lambda _path: None)
    monkeypatch.setattr(
        about_agilab,
        "_NAVIGATION_PAGE_ROUTES",
        {
            "project": PageRoute("PROJECT_PAGE_OBJECT"),
            "orchestrate": PageRoute("ORCHESTRATE_PAGE_OBJECT"),
            "analysis": PageRoute("ANALYSIS_PAGE_OBJECT"),
        },
    )

    about_agilab.render_newcomer_first_proof(env)

    assert ("button", "1. Demo selected") not in fake_st.events
    assert ("button", "1. INSTALL demo") in fake_st.events
    assert ("switch_page", "ORCHESTRATE_PAGE_OBJECT") in fake_st.events
    assert ("switch_page", "pages/2_ORCHESTRATE.py") not in fake_st.events
    assert fake_st.query_params["active_app"] == "flight_telemetry_project"


def test_first_proof_wizard_sample_notebook_opens_project_without_forcing_demo(
    tmp_path,
    monkeypatch,
):
    class PageRoute:
        def __str__(self) -> str:
            return "PROJECT_PAGE_OBJECT"

    apps_path = tmp_path / "apps"
    flight_telemetry_project = apps_path / "builtin" / "flight_telemetry_project"
    flight_telemetry_project.mkdir(parents=True)
    fake_st = _FakeStreamlit(button_values={"Create from built-in notebook": True})
    env = SimpleNamespace(
        apps_path=apps_path,
        app="mycode_project",
        AGILAB_LOG_ABS=tmp_path / "log",
        st_resources=tmp_path / "resources",
    )

    monkeypatch.setattr(about_agilab._about_onboarding, "st", fake_st)

    about_agilab._about_onboarding.render_newcomer_first_proof(
        env,
        activate_project=lambda _env, _path: pytest.fail("notebook start should not select demo"),
        display_landing_page=lambda _path: None,
        page_routes={"project": PageRoute()},
    )

    assert fake_st.session_state["sidebar_selection"] == "Create"
    assert fake_st.session_state["create_mode"] == "From notebook"
    assert fake_st.session_state[
        about_agilab._about_onboarding._notebook_import_sample_module.SAMPLE_NOTEBOOK_SESSION_KEY
    ] is True
    assert fake_st.query_params == {
        "start": "notebook-import",
        "active_app": "mycode_project",
    }
    assert ("switch_page", "PROJECT_PAGE_OBJECT") in fake_st.events


def test_first_proof_wizard_does_not_render_direct_notebook_upload(
    tmp_path,
    monkeypatch,
):
    apps_path = tmp_path / "apps"
    flight_telemetry_project = apps_path / "builtin" / "flight_telemetry_project"
    flight_telemetry_project.mkdir(parents=True)
    fake_st = _FakeStreamlit(
        file_uploader_values={"create_notebook_upload": SimpleNamespace(name="demo.ipynb")}
    )
    env = SimpleNamespace(
        apps_path=apps_path,
        app="mycode_project",
        AGILAB_LOG_ABS=tmp_path / "log",
        st_resources=tmp_path / "resources",
    )

    monkeypatch.setattr(about_agilab._about_onboarding, "st", fake_st)

    about_agilab._about_onboarding.render_newcomer_first_proof(
        env,
        activate_project=lambda _env, _path: pytest.fail("notebook upload should not select demo"),
        display_landing_page=lambda _path: None,
        page_routes={"project": object()},
    )

    assert not [body for kind, body in fake_st.events if kind == "file_uploader"]
    assert "sidebar_selection" not in fake_st.session_state
    assert "create_mode" not in fake_st.session_state
    assert not any(kind == "switch_page" for kind, _body in fake_st.events)


def test_first_proof_wizard_analysis_click_opens_analysis_without_run_evidence(
    tmp_path,
    monkeypatch,
):
    apps_path = tmp_path / "apps"
    flight_telemetry_project = apps_path / "builtin" / "flight_telemetry_project"
    flight_telemetry_project.mkdir(parents=True)
    fake_st = _FakeStreamlit(button_values={"3. OPEN ANALYSIS": True})
    env = SimpleNamespace(
        apps_path=apps_path,
        app="flight_telemetry_project",
        AGILAB_LOG_ABS=tmp_path / "log",
        st_resources=tmp_path / "resources",
    )

    monkeypatch.setattr(about_agilab._about_onboarding, "st", fake_st)

    about_agilab._about_onboarding.render_newcomer_first_proof(
        env,
        activate_project=lambda _env, _path: True,
        display_landing_page=lambda _path: None,
    )

    assert fake_st.query_params["active_app"] == "flight_telemetry_project"
    assert ("switch_page", "pages/4_ANALYSIS.py") in fake_st.events
    assert ("switch_page", "pages/2_ORCHESTRATE.py") not in fake_st.events


def test_first_proof_wizard_analysis_click_opens_analysis_after_run_output(
    tmp_path,
    monkeypatch,
):
    apps_path = tmp_path / "apps"
    flight_telemetry_project = apps_path / "builtin" / "flight_telemetry_project"
    flight_telemetry_project.mkdir(parents=True)
    output_dir = tmp_path / "log" / "execute" / "flight"
    output_dir.mkdir(parents=True)
    (output_dir / "forecast_metrics.json").write_text("{}", encoding="utf-8")
    fake_st = _FakeStreamlit(button_values={"3. OPEN ANALYSIS": True})
    env = SimpleNamespace(
        apps_path=apps_path,
        app="flight_telemetry_project",
        AGILAB_LOG_ABS=tmp_path / "log",
        st_resources=tmp_path / "resources",
    )

    monkeypatch.setattr(about_agilab._about_onboarding, "st", fake_st)

    about_agilab._about_onboarding.render_newcomer_first_proof(
        env,
        activate_project=lambda _env, _path: True,
        display_landing_page=lambda _path: None,
    )

    assert fake_st.query_params["active_app"] == "flight_telemetry_project"
    assert ("switch_page", "pages/4_ANALYSIS.py") in fake_st.events
    assert ("switch_page", "pages/2_ORCHESTRATE.py") not in fake_st.events


def test_render_newcomer_first_proof_uses_markdown(monkeypatch):
    captured: dict[str, object] = {}

    def fake_markdown(body: str, unsafe_allow_html: bool = False):
        captured["body"] = body
        captured["unsafe_allow_html"] = unsafe_allow_html

    monkeypatch.setattr(about_agilab.st, "markdown", fake_markdown)

    about_agilab.render_newcomer_first_proof()

    assert captured["unsafe_allow_html"] is False
    body = str(captured["body"])
    assert "First proof with flight-telemetry-project: verify AGILAB end-to-end" in body
    assert "agilab-proof" not in body
    assert "background:" not in body
    assert "Start here" not in body
    assert "DEMO" in body
    assert "ORCHESTRATE" in body
    assert "ANALYSIS" in body
    assert "flight_telemetry_project" in body
    assert "run_manifest.json" in body
    assert "Follow these steps" in body
    assert "Success criteria" in body
