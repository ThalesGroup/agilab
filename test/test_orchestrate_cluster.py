from __future__ import annotations

import importlib
from pathlib import Path
import sys
import types
from types import SimpleNamespace


def _import_agilab_module(module_name: str):
    src_root = Path(__file__).resolve().parents[1] / "src"
    package_root = src_root / "agilab"
    src_root_str = str(src_root)
    package_root_str = str(package_root)
    if src_root_str not in sys.path:
        sys.path.insert(0, src_root_str)
    pkg = sys.modules.get("agilab")
    if pkg is None or not hasattr(pkg, "__path__"):
        pkg = types.ModuleType("agilab")
        pkg.__path__ = [package_root_str]
        sys.modules["agilab"] = pkg
    else:
        package_path = list(pkg.__path__)
        if package_root_str not in package_path:
            pkg.__path__ = [package_root_str, *package_path]
    importlib.invalidate_caches()
    return importlib.import_module(module_name)


orchestrate_cluster = _import_agilab_module("agilab.orchestrate_cluster")
orchestrate_page_support = _import_agilab_module("agilab.orchestrate_page_support")


class _State(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


class _Context:
    def __init__(self, st):
        self._st = st

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def checkbox(self, *args, **kwargs):
        return self._st.checkbox(*args, **kwargs)

    def columns(self, spec, **kwargs):
        return self._st.columns(spec, **kwargs)


class _FakeStreamlit:
    def __init__(self, *, widget_values=None, session_state=None):
        self.widget_values = widget_values or {}
        self.session_state = _State(session_state or {})
        self.markdowns: list[str] = []
        self.infos: list[str] = []

    def _value(self, key, default=""):
        if key in self.widget_values:
            return self.widget_values[key]
        return self.session_state.get(key, default)

    def columns(self, spec, **_kwargs):
        count = spec if isinstance(spec, int) else len(spec)
        return [_Context(self) for _ in range(count)]

    def container(self):
        return _Context(self)

    def checkbox(self, _label, value=False, *, key=None, **_kwargs):
        result = self._value(key, value)
        if key is not None:
            self.session_state[key] = result
        return result

    def toggle(self, _label, *, key=None, value=False, **_kwargs):
        result = self._value(key, value)
        if key is not None:
            self.session_state[key] = result
        return result

    def text_input(self, _label, *, key=None, value="", **_kwargs):
        result = self._value(key, value)
        if key is not None:
            self.session_state[key] = result
        return result

    def text_area(self, _label, *, key=None, value="", **_kwargs):
        result = self._value(key, value)
        if key is not None:
            self.session_state[key] = result
        return result

    def markdown(self, text):
        self.markdowns.append(text)

    def info(self, text):
        self.infos.append(text)


def test_compute_cluster_mode_uses_expected_bitmask():
    result = orchestrate_cluster.compute_cluster_mode(
        {"pool": True, "cython": True, "rapids": True},
        cluster_enabled=True,
    )

    assert result == 15


def test_compute_benchmark_run_mode_lists_enabled_capability_combinations():
    assert orchestrate_page_support.compute_benchmark_run_mode(
        {"pool": True, "cython": True, "rapids": False},
        cluster_enabled=False,
    ) == [0, 1, 2, 3]
    assert orchestrate_page_support.compute_benchmark_run_mode(
        {"pool": True, "cython": True, "rapids": True},
        cluster_enabled=False,
    ) == [0, 1, 2, 3, 8, 9, 10, 11]
    assert orchestrate_page_support.compute_benchmark_run_mode(
        {"pool": True, "cython": True, "rapids": True},
        cluster_enabled=True,
    ) == list(range(16))


def test_resolve_project_change_args_override_only_preserves_matching_ui_args():
    assert orchestrate_page_support.resolve_project_change_args_override(
        is_args_from_ui=True,
        args_project="flight_project",
        previous_project="flight_project",
        app_settings_snapshot={"args": {"foo": 1}},
    ) == {"foo": 1}
    assert orchestrate_page_support.resolve_project_change_args_override(
        is_args_from_ui=True,
        args_project="other_project",
        previous_project="flight_project",
        app_settings_snapshot={"args": {"foo": 1}},
    ) is None
    assert orchestrate_page_support.resolve_project_change_args_override(
        is_args_from_ui=False,
        args_project="flight_project",
        previous_project="flight_project",
        app_settings_snapshot={"args": {"foo": 1}},
    ) is None


def test_hydrate_and_clear_cluster_widget_state_are_project_scoped():
    session_state = _State()

    orchestrate_cluster.hydrate_cluster_widget_state(
        session_state,
        "demo_project",
        {
            "cluster_enabled": True,
            "cython": True,
            "pool": False,
            "rapids": True,
            "scheduler": "127.0.0.1:8786",
            "user": "agi",
            "auth_method": "ssh_key",
            "ssh_key_path": "~/.ssh/id_demo",
            "workers_data_path": "/cluster/data",
            "workers": {"127.0.0.1": 2},
        },
        is_managed_pc=False,
    )

    assert session_state["cluster_enabled__demo_project"] is True
    assert session_state["cluster_cython__demo_project"] is True
    assert session_state["cluster_pool__demo_project"] is False
    assert session_state["cluster_rapids__demo_project"] is True
    assert session_state["cluster_scheduler__demo_project"] == "127.0.0.1:8786"
    assert session_state["cluster_workers__demo_project"] == '{\n  "127.0.0.1": 2\n}'
    assert session_state["cluster_use_key__demo_project"] is True

    orchestrate_cluster.clear_cluster_widget_state(session_state, "demo_project")

    assert "cluster_enabled__demo_project" not in session_state
    assert "cluster_cython__demo_project" not in session_state
    assert "cluster_pool__demo_project" not in session_state
    assert "cluster_rapids__demo_project" not in session_state
    assert "cluster_scheduler__demo_project" not in session_state
    assert "cluster_workers__demo_project" not in session_state


def test_persist_env_var_if_changed_ignores_same_value():
    calls: list[tuple[str, str]] = []

    orchestrate_cluster.persist_env_var_if_changed(
        key="CLUSTER_CREDENTIALS",
        value="user",
        set_env_var=lambda key, value: calls.append((key, value)),
        agi_env_envars={"CLUSTER_CREDENTIALS": "user"},
    )

    assert calls == []


def test_persist_env_var_if_changed_updates_changed_value():
    calls: list[tuple[str, str]] = []

    orchestrate_cluster.persist_env_var_if_changed(
        key="AGI_SSH_KEY_PATH",
        value="~/.ssh/id_rsa",
        set_env_var=lambda key, value: calls.append((key, value)),
        agi_env_envars={"AGI_SSH_KEY_PATH": ""},
    )

    assert calls == [("AGI_SSH_KEY_PATH", "~/.ssh/id_rsa")]


def test_describe_share_path_handles_missing_and_resolved_paths(tmp_path):
    share_real = tmp_path / "share_real"
    share_real.mkdir()
    share_link = tmp_path / "share_link"
    share_link.symlink_to(share_real, target_is_directory=True)

    env_missing = SimpleNamespace(agi_share_path=None, share_root_path=lambda: share_link)
    assert orchestrate_cluster._describe_share_path(env_missing).startswith("not set.")

    env_resolved = SimpleNamespace(agi_share_path=Path("clustershare"), share_root_path=lambda: share_link)
    assert orchestrate_cluster._describe_share_path(env_resolved).startswith("clustershare → ")


def test_describe_share_path_handles_share_root_errors_and_unresolved_same_path():
    env_error = SimpleNamespace(
        agi_share_path=Path("clustershare"),
        share_root_path=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    assert orchestrate_cluster._describe_share_path(env_error) == "clustershare"

    class _BrokenResolvePath:
        def __str__(self):
            return "clustershare"

        def resolve(self, strict=False):
            raise OSError("bad resolve")

    env_broken_resolve = SimpleNamespace(
        agi_share_path=Path("clustershare"),
        share_root_path=lambda: _BrokenResolvePath(),
    )
    assert orchestrate_cluster._describe_share_path(env_broken_resolve) == "clustershare"


def test_cluster_credentials_value_formats_password_and_key_modes():
    assert orchestrate_cluster._cluster_credentials_value(" agi ", use_ssh_key=True) == "agi"
    assert (
        orchestrate_cluster._cluster_credentials_value(" agi ", password="secret", use_ssh_key=False)
        == "agi:secret"
    )
    assert orchestrate_cluster._cluster_credentials_value("", password="secret", use_ssh_key=False) == ""


def test_render_cluster_settings_ui_initializes_state_and_persists_cluster_mode(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit(
        widget_values={
            "cluster_cython__demo_project": True,
            "cluster_pool__demo_project": True,
            "cluster_rapids__demo_project": True,
            "cluster_enabled__demo_project": False,
        },
        session_state={"benchmark": False},
    )
    monkeypatch.setattr(orchestrate_cluster, "st", fake_st)

    writes: dict[str, object] = {}
    deps = orchestrate_cluster.OrchestrateClusterDeps(
        parse_and_validate_scheduler=lambda raw: raw,
        parse_and_validate_workers=lambda raw: {"parsed": raw},
        write_app_settings_toml=lambda path, settings: writes.setdefault("write", (path, settings)) and settings,
        clear_load_toml_cache=lambda: writes.setdefault("cleared", True),
        set_env_var=lambda key, value: writes.setdefault("env_calls", []).append((key, value)),
        agi_env_envars={},
    )
    env = SimpleNamespace(
        app="demo_project",
        is_managed_pc=False,
        agi_share_path=None,
        share_root_path=lambda: tmp_path / "share",
        user="",
        password=None,
        ssh_key_path=None,
        app_settings_file=tmp_path / "app_settings.toml",
    )

    orchestrate_cluster.render_cluster_settings_ui(env, deps)

    cluster = fake_st.session_state.app_settings["cluster"]
    assert cluster["cython"] is True
    assert cluster["pool"] is True
    assert cluster["rapids"] is True
    assert cluster["cluster_enabled"] is False
    assert fake_st.session_state.dask is False
    assert fake_st.session_state["mode"] == 11
    assert fake_st.infos[-1] == "Run mode 11: rapids and pool and cython"
    assert writes["cleared"] is True
    assert writes["write"][0] == env.app_settings_file


def test_render_cluster_settings_ui_uses_ssh_key_auth_and_resolved_share(monkeypatch, tmp_path):
    share_real = tmp_path / "share_real"
    share_real.mkdir()
    share_link = tmp_path / "share_link"
    share_link.symlink_to(share_real, target_is_directory=True)

    fake_st = _FakeStreamlit(
        widget_values={
            "cluster_enabled__demo_project": True,
            "cluster_cython__demo_project": True,
            "cluster_pool__demo_project": False,
            "cluster_scheduler__demo_project": "192.168.1.10",
            "cluster_workers_data_path__demo_project": "/cluster/data",
            "cluster_workers__demo_project": '{"192.168.1.11": 2}',
            "cluster_use_key__demo_project": True,
        },
        session_state={
            "app_settings": {"cluster": {"cluster_enabled": True, "ssh_key_path": "~/.ssh/id_demo"}},
            "benchmark": False,
        },
    )
    monkeypatch.setattr(orchestrate_cluster, "st", fake_st)

    env_calls: list[tuple[str, str]] = []
    writes: dict[str, object] = {}
    deps = orchestrate_cluster.OrchestrateClusterDeps(
        parse_and_validate_scheduler=lambda raw: f"{raw}:8786",
        parse_and_validate_workers=lambda raw: {"192.168.1.11": 2} if "192.168.1.11" in raw else None,
        write_app_settings_toml=lambda path, settings: writes.setdefault("write", (path, settings)) and settings,
        clear_load_toml_cache=lambda: writes.setdefault("cleared", True),
        set_env_var=lambda key, value: env_calls.append((key, value)),
        agi_env_envars={},
    )
    env = SimpleNamespace(
        app="demo_project",
        is_managed_pc=True,
        agi_share_path=Path("clustershare"),
        share_root_path=lambda: share_link,
        user="agi",
        password="stale",
        ssh_key_path=None,
        app_settings_file=tmp_path / "app_settings.toml",
    )

    orchestrate_cluster.render_cluster_settings_ui(env, deps)

    cluster = fake_st.session_state.app_settings["cluster"]
    assert cluster["cluster_enabled"] is True
    assert cluster["auth_method"] == "ssh_key"
    assert cluster["ssh_key_path"] == "~/.ssh/id_demo"
    assert cluster["scheduler"] == "192.168.1.10:8786"
    assert cluster["workers"] == {"192.168.1.11": 2}
    assert cluster["workers_data_path"] == "/cluster/data"
    assert cluster["rapids"] is False
    assert env.user == "agi"
    assert env.password is None
    assert env.ssh_key_path == "~/.ssh/id_demo"
    assert ("CLUSTER_CREDENTIALS", "agi") in env_calls
    assert ("AGI_SSH_KEY_PATH", "~/.ssh/id_demo") in env_calls
    assert any("clustershare" in text and "→" in text for text in fake_st.markdowns)
    assert fake_st.session_state["mode"] == 6
    assert fake_st.infos[-1] == "Run mode 6: dask and cython"


def test_render_cluster_settings_ui_password_auth_clears_credentials_and_ignores_cache_errors(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit(
        widget_values={
            "cluster_enabled__demo_project": True,
            "cluster_cython__demo_project": False,
            "cluster_pool__demo_project": False,
            "cluster_rapids__demo_project": False,
            "cluster_use_key__demo_project": False,
            "cluster_user__demo_project": "",
            "cluster_password__demo_project": "secret",
            "cluster_scheduler__demo_project": "invalid",
            "cluster_workers__demo_project": "{broken}",
            "cluster_workers_data_path__demo_project": "/tmp/data",
        },
        session_state={
            "app_settings": {"cluster": {}},
            "benchmark": True,
        },
    )
    monkeypatch.setattr(orchestrate_cluster, "st", fake_st)

    env_calls: list[tuple[str, str]] = []
    deps = orchestrate_cluster.OrchestrateClusterDeps(
        parse_and_validate_scheduler=lambda _raw: None,
        parse_and_validate_workers=lambda _raw: None,
        write_app_settings_toml=lambda _path, settings: settings,
        clear_load_toml_cache=lambda: (_ for _ in ()).throw(RuntimeError("cache boom")),
        set_env_var=lambda key, value: env_calls.append((key, value)),
        agi_env_envars={"CLUSTER_CREDENTIALS": "old:user", "AGI_SSH_KEY_PATH": "~/.ssh/old"},
    )
    env = SimpleNamespace(
        app="demo_project",
        is_managed_pc=False,
        agi_share_path=Path("clustershare"),
        share_root_path=lambda: tmp_path / "share",
        user="",
        password=None,
        ssh_key_path="~/.ssh/old",
        app_settings_file=tmp_path / "app_settings.toml",
    )

    orchestrate_cluster.render_cluster_settings_ui(env, deps)

    cluster = fake_st.session_state.app_settings["cluster"]
    assert cluster["auth_method"] == "password"
    assert cluster["workers_data_path"] == "/tmp/data"
    assert "scheduler" not in cluster
    assert "workers" not in cluster
    assert env.password == "secret"
    assert env.ssh_key_path is None
    assert ("CLUSTER_CREDENTIALS", "") in env_calls
    assert ("AGI_SSH_KEY_PATH", "") in env_calls
    assert fake_st.session_state["mode"] == 4
    assert fake_st.infos[-1] == "Run mode 4: dask"


def test_render_cluster_settings_ui_password_auth_uses_stored_user_for_credentials(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit(
        widget_values={
            "cluster_enabled__demo_project": True,
            "cluster_cython__demo_project": False,
            "cluster_pool__demo_project": False,
            "cluster_rapids__demo_project": False,
            "cluster_use_key__demo_project": False,
            "cluster_user__demo_project": "   ",
            "cluster_password__demo_project": "secret",
        },
        session_state={
            "app_settings": {"cluster": {"user": " agi "}},
            "benchmark": False,
        },
    )
    monkeypatch.setattr(orchestrate_cluster, "st", fake_st)

    env_calls: list[tuple[str, str]] = []
    deps = orchestrate_cluster.OrchestrateClusterDeps(
        parse_and_validate_scheduler=lambda _raw: None,
        parse_and_validate_workers=lambda _raw: None,
        write_app_settings_toml=lambda _path, settings: settings,
        clear_load_toml_cache=lambda: None,
        set_env_var=lambda key, value: env_calls.append((key, value)),
        agi_env_envars={"CLUSTER_CREDENTIALS": ""},
    )
    env = SimpleNamespace(
        app="demo_project",
        is_managed_pc=False,
        agi_share_path=Path("clustershare"),
        share_root_path=lambda: tmp_path / "share",
        user="",
        password=None,
        ssh_key_path=None,
        app_settings_file=tmp_path / "app_settings.toml",
    )

    orchestrate_cluster.render_cluster_settings_ui(env, deps)

    cluster = fake_st.session_state.app_settings["cluster"]
    assert cluster["user"] == "agi"
    assert env.user == "agi"
    assert env.password == "secret"
    assert ("CLUSTER_CREDENTIALS", "agi:secret") in env_calls


def test_render_cluster_settings_ui_ssh_key_mode_uses_env_default_key_when_input_blank(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit(
        widget_values={
            "cluster_enabled__demo_project": True,
            "cluster_cython__demo_project": False,
            "cluster_pool__demo_project": False,
            "cluster_rapids__demo_project": False,
            "cluster_use_key__demo_project": True,
            "cluster_ssh_key__demo_project": "   ",
        },
        session_state={
            "app_settings": {"cluster": {"cluster_enabled": True}},
            "benchmark": False,
        },
    )
    monkeypatch.setattr(orchestrate_cluster, "st", fake_st)

    env_calls: list[tuple[str, str]] = []
    deps = orchestrate_cluster.OrchestrateClusterDeps(
        parse_and_validate_scheduler=lambda _raw: None,
        parse_and_validate_workers=lambda _raw: None,
        write_app_settings_toml=lambda _path, settings: settings,
        clear_load_toml_cache=lambda: None,
        set_env_var=lambda key, value: env_calls.append((key, value)),
        agi_env_envars={"AGI_SSH_KEY_PATH": ""},
    )
    env = SimpleNamespace(
        app="demo_project",
        is_managed_pc=False,
        agi_share_path=Path("clustershare"),
        share_root_path=lambda: tmp_path / "share",
        user="agi",
        password="stale",
        ssh_key_path=" ~/.ssh/id_demo ",
        app_settings_file=tmp_path / "app_settings.toml",
    )

    orchestrate_cluster.render_cluster_settings_ui(env, deps)

    cluster = fake_st.session_state.app_settings["cluster"]
    assert cluster["ssh_key_path"] == "~/.ssh/id_demo"
    assert env.password is None
    assert env.ssh_key_path == "~/.ssh/id_demo"
    assert ("AGI_SSH_KEY_PATH", "~/.ssh/id_demo") in env_calls
