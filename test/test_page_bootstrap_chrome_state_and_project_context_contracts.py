"""Page chrome must tolerate host state boundaries and show explicit context."""

import builtins
from collections import UserDict
from types import ModuleType, SimpleNamespace
import sys

import pytest

from agilab.ui import page_bootstrap as bootstrap


@pytest.mark.parametrize(
    ("env", "label"),
    [
        (None, ""),
        (SimpleNamespace(app="", target="  ", active_app=None), ""),
        (SimpleNamespace(app="pytorch_playground_project"), "PyTorch Playground"),
        (SimpleNamespace(app="traffic_analysis"), "Traffic Analysis"),
        (
            SimpleNamespace(app=None, target="/apps/flight_analysis_project"),
            "Flight Analysis",
        ),
        (
            SimpleNamespace(app=" ", target="", active_app="/apps/weather_project"),
            "Weather",
        ),
    ],
)
def test_explicit_project_chip_labels_and_host_capabilities(env, label):
    rendered = []
    host = SimpleNamespace(sidebar=SimpleNamespace(markdown=rendered.append))

    assert bootstrap.render_active_project_chip(host, env=env) is bool(label)
    assert rendered == ([f"**{label}**"] if label else [])


@pytest.mark.parametrize(
    "host", [SimpleNamespace(), SimpleNamespace(sidebar=SimpleNamespace(markdown=None))]
)
def test_project_chip_skips_hosts_without_a_markdown_sidebar(host):
    assert bootstrap.render_active_project_chip(
        host, env=SimpleNamespace(app="weather_project")
    ) is False


def test_page_configuration_tolerates_attribute_only_session_storage():
    class AttributeOnlyState:
        def get(self, _key):
            raise RuntimeError("host state is temporarily unavailable")

        def __setitem__(self, _key, _value):
            raise TypeError("host exposes attributes instead of mapping writes")

    state = AttributeOnlyState()
    configured = []
    host = SimpleNamespace(session_state=state, set_page_config=lambda **kw: configured.append(kw))

    assert bootstrap.configure_page_config(host, page_title="Weather") is True
    assert bootstrap.configure_page_config(host, page_title="Weather") is False
    assert configured == [{"page_title": "Weather", "layout": "wide"}]
    assert getattr(state, bootstrap.PAGE_CONFIGURED_STATE_KEY) is True


def test_page_configuration_reuses_attribute_flag_when_mapping_has_no_value():
    class ReadOnlyMapping(UserDict):
        def __setitem__(self, _key, _value):
            raise TypeError("mapping writes are unavailable")

    state = ReadOnlyMapping()
    configured = []
    host = SimpleNamespace(
        session_state=state, set_page_config=lambda **kw: configured.append(kw)
    )

    assert bootstrap.configure_page_config(host, page_title="Weather") is True
    assert state.get(bootstrap.PAGE_CONFIGURED_STATE_KEY) is None
    assert getattr(state, bootstrap.PAGE_CONFIGURED_STATE_KEY) is True
    assert bootstrap.configure_page_config(host, page_title="Weather") is False
    assert configured == [{"page_title": "Weather", "layout": "wide"}]


def test_explicit_mapping_false_takes_priority_over_attribute_flag():
    state = UserDict({bootstrap.PAGE_CONFIGURED_STATE_KEY: False})
    setattr(state, bootstrap.PAGE_CONFIGURED_STATE_KEY, True)
    configured = []
    host = SimpleNamespace(
        session_state=state, set_page_config=lambda **kw: configured.append(kw)
    )

    assert bootstrap.configure_page_config(host, page_title="Weather") is True
    assert configured == [{"page_title": "Weather", "layout": "wide"}]
    assert state[bootstrap.PAGE_CONFIGURED_STATE_KEY] is True


def test_page_configuration_survives_read_only_session_storage():
    class ReadOnlyState:
        def get(self, _key):
            return None

        def __setitem__(self, _key, _value):
            raise KeyError("session storage is read only")

        def __setattr__(self, _key, _value):
            raise ValueError("attribute storage is also read only")

    configured = []
    host = SimpleNamespace(
        session_state=ReadOnlyState(), set_page_config=lambda **kw: configured.append(kw)
    )

    assert bootstrap.configure_page_config(host, page_title="Weather") is True
    assert configured == [{"page_title": "Weather", "layout": "wide"}]


def test_page_configuration_without_session_storage_tolerates_immutable_host():
    class ImmutableHost:
        __slots__ = ("configured",)

        def __init__(self):
            self.configured = []

        def set_page_config(self, **kwargs):
            self.configured.append(kwargs)

    host = ImmutableHost()

    assert bootstrap.configure_page_config(host, page_title="Weather") is True
    assert host.configured == [{"page_title": "Weather", "layout": "wide"}]


def test_page_configuration_survives_unavailable_mapping_and_attribute_reads():
    class UnavailableState:
        __slots__ = ()

        def __getattr__(self, _key):
            raise RuntimeError("host state cannot currently be read")

        def __setitem__(self, _key, _value):
            raise RuntimeError("host state cannot currently be written")

    configured = []
    host = SimpleNamespace(
        session_state=UnavailableState(),
        set_page_config=lambda **kwargs: configured.append(kwargs),
    )

    assert bootstrap.configure_page_config(host, page_title="Weather") is True
    assert configured == [{"page_title": "Weather", "layout": "wide"}]


def test_page_chrome_uses_default_title_for_an_empty_page_label():
    configured = []
    host = SimpleNamespace(
        session_state={}, set_page_config=lambda **kw: configured.append(kw)
    )
    bootstrap.configure_page_chrome(
        host,
        page_label=" ",
        docs_html_file="index.html",
        get_docs_menu_items=lambda **_kwargs: {},
        inject_theme=lambda _resources: pytest.fail("no theme resources were supplied"),
    )

    assert configured == [{"page_title": "AGILab", "layout": "wide", "menu_items": {}}]


def test_page_header_lazily_loads_context_and_does_not_add_a_global_project_chip(monkeypatch):
    events = []
    env = SimpleNamespace(app="weather_project")
    host = SimpleNamespace(
        sidebar=SimpleNamespace(markdown=lambda _text: pytest.fail("global project chip"))
    )
    pagelib = ModuleType("agi_gui.pagelib")
    pagelib.render_logo = lambda: events.append(("logo",))
    pinned = ModuleType("agilab.ui.pinned_expander")
    pinned.render_pinned_expanders = lambda target: events.append(("expanders", target))
    context = ModuleType("agilab.workflow.workflow_ui")
    context.render_page_context = lambda target, **kwargs: events.append(
        ("context", target, kwargs)
    )
    monkeypatch.setitem(sys.modules, "agi_gui.pagelib", pagelib)
    monkeypatch.setitem(sys.modules, "agilab.ui.pinned_expander", pinned)
    monkeypatch.setitem(sys.modules, "agilab.workflow.workflow_ui", context)
    imports = []
    original_import = builtins.__import__

    def observe_import(name, *args, **kwargs):
        if name == "agilab.workflow.workflow_ui":
            imports.append(name)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", observe_import)

    bootstrap.render_page_header(host, page_label="Analyse", env=env)
    assert imports == []
    assert events == [("logo",), ("expanders", host)]

    events.clear()
    bootstrap.render_page_header(
        host, page_label="Analyse", env=env, show_project_context=True
    )
    assert imports == ["agilab.workflow.workflow_ui"]
    assert events == [
        ("logo",),
        ("expanders", host),
        ("context", host, {"page_label": "Analyse", "env": env}),
    ]


@pytest.mark.parametrize("resources", [None, "/explicit/theme"])
def test_page_chrome_uses_project_theme_unless_the_page_overrides_it(resources):
    configured = []
    themed = []
    rendered = []
    host = SimpleNamespace(
        session_state={}, set_page_config=lambda **kwargs: configured.append(kwargs)
    )
    bootstrap.render_page_chrome(
        host,
        env=SimpleNamespace(st_resources="/project/theme"),
        page_label="Analyse",
        docs_html_file="analysis.html",
        resources_path=resources,
        get_docs_menu_items=lambda **kwargs: {"Help": kwargs["html_file"]},
        inject_theme=themed.append,
        render_logo=lambda: rendered.append("logo"),
        render_pinned_expanders=lambda target: rendered.append(target),
    )

    assert configured == [
        {"page_title": "AGILab Analyse", "layout": "wide", "menu_items": {"Help": "analysis.html"}}
    ]
    assert themed == [resources or "/project/theme"]
    assert rendered == ["logo", host]


@pytest.mark.parametrize("init_done", [None, False])
def test_realign_legacy_environment_preserves_known_initialization_or_absence(tmp_path, init_done):
    class LegacyEnvironment:
        def __init__(self, *, apps_path, app, verbose=None, _agilab_reinitialize=False):
            self.apps_path = apps_path
            self.app = app
            self.active_app = apps_path / app
            self.verbose = verbose
            if _agilab_reinitialize and hasattr(self, "init_done"):
                self.init_done = True

    page_file = tmp_path / "workspace" / "pages" / "analyse.py"
    page_file.parent.mkdir(parents=True)
    page_file.touch()
    apps = tmp_path / "workspace" / "apps"
    (apps / "weather_project").mkdir(parents=True)
    env = LegacyEnvironment(apps_path=tmp_path / "agi-space" / "apps", app="weather_project")
    if init_done is not None:
        env.init_done = init_done
    session = {"env": env}

    assert bootstrap.realign_session_env_with_page_root(session, page_file) is True
    assert session["env"] is env
    assert env.apps_path == apps
    assert env.active_app == apps / "weather_project"
    assert session["apps_path"] == str(apps)
    if init_done is None:
        assert not hasattr(env, "init_done")
    else:
        assert env.init_done is init_done
