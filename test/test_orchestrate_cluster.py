from __future__ import annotations

import importlib
import ipaddress
import json
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

    def button(self, *args, **kwargs):
        return self._st.button(*args, **kwargs)

    def columns(self, spec, **kwargs):
        return self._st.columns(spec, **kwargs)


class _FakeStreamlit:
    def __init__(self, *, widget_values=None, session_state=None, button_values=None):
        self.widget_values = widget_values or {}
        self.button_values = button_values or {}
        self.session_state = _State(session_state or {})
        self.markdowns: list[str] = []
        self.infos: list[str] = []
        self.errors: list[str] = []
        self.buttons: list[str] = []

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

    def button(self, label, *, key=None, **_kwargs):
        self.buttons.append(label)
        if key in self.button_values:
            return self.button_values[key]
        return self.button_values.get(label, False)

    def markdown(self, text):
        self.markdowns.append(text)

    def info(self, text):
        self.infos.append(text)

    def error(self, text):
        self.errors.append(text)


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


def test_home_relative_share_text_strips_host_specific_home_prefix(tmp_path):
    env = SimpleNamespace(home_abs=tmp_path / "home" / "agi")

    assert (
        orchestrate_cluster._home_relative_share_text(env.home_abs / "clustershare" / "agi", env)
        == "clustershare/agi"
    )
    assert (
        orchestrate_cluster._home_relative_share_text(r"C:\Users\agi\clustershare\agi", env)
        == "clustershare/agi"
    )
    assert (
        orchestrate_cluster._home_relative_share_text("/Users/agi/clustershare/agi", env)
        == "clustershare/agi"
    )
    assert orchestrate_cluster._home_relative_share_text("/mnt/agilab/share", env) == "/mnt/agilab/share"


def test_resolve_project_change_args_override_only_preserves_matching_ui_args():
    assert orchestrate_page_support.resolve_project_change_args_override(
        is_args_from_ui=True,
        args_project="flight_telemetry_project",
        previous_project="flight_telemetry_project",
        app_settings_snapshot={"args": {"foo": 1}},
    ) == {"foo": 1}
    assert orchestrate_page_support.resolve_project_change_args_override(
        is_args_from_ui=True,
        args_project="other_project",
        previous_project="flight_telemetry_project",
        app_settings_snapshot={"args": {"foo": 1}},
    ) is None
    assert orchestrate_page_support.resolve_project_change_args_override(
        is_args_from_ui=False,
        args_project="flight_telemetry_project",
        previous_project="flight_telemetry_project",
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


def test_hydrate_cluster_widget_state_preserves_existing_widget_values():
    session_state = _State(
        {
            "cluster_enabled__demo_project": False,
            "cluster_cython__demo_project": False,
            "cluster_pool__demo_project": True,
            "cluster_rapids__demo_project": False,
            "cluster_scheduler__demo_project": "192.168.1.10:8786",
            "cluster_user__demo_project": "local-user",
            "cluster_ssh_key__demo_project": "~/.ssh/local",
            "cluster_workers_data_path__demo_project": "/local/data",
            "cluster_workers__demo_project": '{"192.168.1.11": 1}',
            "cluster_use_key__demo_project": False,
        }
    )

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

    assert session_state["cluster_enabled__demo_project"] is False
    assert session_state["cluster_cython__demo_project"] is False
    assert session_state["cluster_pool__demo_project"] is True
    assert session_state["cluster_rapids__demo_project"] is False
    assert session_state["cluster_scheduler__demo_project"] == "192.168.1.10:8786"
    assert session_state["cluster_user__demo_project"] == "local-user"
    assert session_state["cluster_ssh_key__demo_project"] == "~/.ssh/local"
    assert session_state["cluster_workers_data_path__demo_project"] == "/local/data"
    assert session_state["cluster_workers__demo_project"] == '{"192.168.1.11": 1}'
    assert session_state["cluster_use_key__demo_project"] is False


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


def test_lan_discovery_cluster_defaults_uses_ready_cache_nodes(tmp_path):
    cache_path = tmp_path / "lan_nodes.json"
    cache_path.write_text(
        """
{
  "local_hosts": ["169.254.35.190", "192.168.3.103"],
  "nodes": [
    {"host": "192.168.3.35", "status": "ready"},
    {"host": "192.168.3.36", "status": "sshfs-missing"}
  ]
}
""",
        encoding="utf-8",
    )

    defaults = orchestrate_cluster._lan_discovery_cluster_defaults(cache_path)

    assert defaults == {
        "scheduler": "192.168.3.103:8786",
        "workers": {"192.168.3.103": 1, "192.168.3.35": 1},
    }


def test_lan_discovery_cluster_defaults_accepts_explicit_non_private_lan_cache(tmp_path):
    cache_path = tmp_path / "lan_nodes.json"
    cache_path.write_text(
        """
{
  "local_hosts": ["169.254.35.190", "192.128.20.111"],
  "nodes": [
    {"host": "192.128.20.130", "status": "ready"}
  ]
}
""",
        encoding="utf-8",
    )

    defaults = orchestrate_cluster._lan_discovery_cluster_defaults(cache_path)

    assert defaults == {
        "scheduler": "192.128.20.111:8786",
        "workers": {"192.128.20.111": 1, "192.128.20.130": 1},
    }


def test_lan_discovery_cluster_defaults_uses_only_ready_worker_candidates(tmp_path):
    cache_path = tmp_path / "lan_nodes.json"
    test_net_base = int(ipaddress.IPv4Address(0xC6336400))

    def host(offset: int) -> str:
        return str(ipaddress.IPv4Address(test_net_base + offset))

    scheduler = host(111)
    unconfigured_auth_host = host(2)
    known_hosts_auth_host = host(15)
    ssh_config_host = host(130)
    stale_known_hosts_host = host(84)
    passive_gateway_host = host(1)
    arp_only_host = host(254)
    cache_path.write_text(
        json.dumps(
            {
                "local_hosts": [scheduler],
                "nodes": [
                    {
                        "host": unconfigured_auth_host,
                        "status": "ssh-auth-needed",
                        "sources": ["arp", "tcp-scan"],
                    },
                    {
                        "host": known_hosts_auth_host,
                        "status": "ready",
                        "sources": ["arp", "known-hosts", "tcp-scan"],
                        "tcp_ssh_open": True,
                    },
                    {
                        "host": ssh_config_host,
                        "status": "no-ssh-port",
                        "sources": ["ssh-config"],
                    },
                    {
                        "host": stale_known_hosts_host,
                        "status": "no-ssh-port",
                        "sources": ["known-hosts"],
                        "tcp_ssh_open": False,
                    },
                    {
                        "host": passive_gateway_host,
                        "status": "ssh-auth-needed",
                        "sources": ["arp", "cache", "tcp-scan"],
                        "tcp_ssh_open": True,
                        "errors": ["Host key verification failed."],
                    },
                    {
                        "host": arp_only_host,
                        "status": "no-ssh-port",
                        "sources": ["arp"],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    defaults = orchestrate_cluster._lan_discovery_cluster_defaults(cache_path)

    assert defaults == {
        "scheduler": f"{scheduler}:8786",
        "workers": {scheduler: 1, known_hosts_auth_host: 1},
    }


def test_lan_discovery_cluster_defaults_skips_non_ready_authenticated_known_hosts_worker(tmp_path):
    cache_path = tmp_path / "lan_nodes.json"
    cache_path.write_text(
        json.dumps(
            {
                "local_hosts": ["192.168.20.111"],
                "nodes": [
                    {
                        "host": "192.168.20.15",
                        "status": "uv-missing",
                        "sources": ["arp", "cache", "known-hosts", "tcp-scan"],
                        "tcp_ssh_open": True,
                        "ssh_auth": True,
                    },
                    {
                        "host": "192.168.20.1",
                        "status": "ssh-auth-needed",
                        "sources": ["arp", "cache", "tcp-scan"],
                        "tcp_ssh_open": True,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    defaults = orchestrate_cluster._lan_discovery_cluster_defaults(cache_path)

    assert defaults == {
        "scheduler": "192.168.20.111:8786",
        "workers": {"192.168.20.111": 1},
    }


def test_lan_discovery_invalid_worker_hosts_reports_passive_cache_gateway(tmp_path):
    cache_path = tmp_path / "lan_nodes.json"
    cache_path.write_text(
        json.dumps(
            {
                "local_hosts": ["192.168.20.111"],
                "nodes": [
                    {
                        "host": "192.168.20.1",
                        "status": "ssh-auth-needed",
                        "sources": ["arp", "cache", "tcp-scan"],
                        "tcp_ssh_open": True,
                    },
                    {
                        "host": "192.168.20.15",
                        "status": "uv-missing",
                        "sources": ["arp", "cache", "known-hosts", "tcp-scan"],
                        "tcp_ssh_open": True,
                        "ssh_auth": True,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    assert orchestrate_cluster._lan_discovery_invalid_worker_hosts(cache_path) == {"192.168.20.1", "192.168.20.15"}


def test_lan_discovery_cluster_defaults_reads_cache_from_env_home(tmp_path):
    home = tmp_path / "agilab-home"
    cache_path = home / ".agilab" / "lan_nodes.json"
    cache_path.parent.mkdir(parents=True)
    cache_path.write_text(
        """
{
  "local_hosts": ["192.168.50.10"],
  "nodes": [
    {"host": "192.168.50.20", "status": "ready"}
  ]
}
""",
        encoding="utf-8",
    )

    defaults = orchestrate_cluster._lan_discovery_cluster_defaults(home=home)

    assert defaults == {
        "scheduler": "192.168.50.10:8786",
        "workers": {"192.168.50.10": 1, "192.168.50.20": 1},
    }


def test_clear_lan_discovery_cache_removes_cache_file(tmp_path):
    cache_path = tmp_path / "lan_nodes.json"
    cache_path.write_text("{}", encoding="utf-8")

    assert orchestrate_cluster._clear_lan_discovery_cache(cache_path) == (True, "")
    assert not cache_path.exists()
    assert orchestrate_cluster._clear_lan_discovery_cache(cache_path) == (False, "missing")


def test_refresh_lan_discovery_cache_runs_discovery_with_scheduler_ssh_target(monkeypatch, tmp_path):
    cache_path = tmp_path / ".agilab" / "lan_nodes.json"
    captured = {}

    def fake_discover(options):
        captured["options"] = options
        return SimpleNamespace(
            nodes=[
                SimpleNamespace(status="ready"),
                SimpleNamespace(status="sshfs-missing"),
            ]
        )

    monkeypatch.setattr(orchestrate_cluster, "discover_lan_nodes", fake_discover)

    refreshed, message = orchestrate_cluster._refresh_lan_discovery_cache(
        cache_path,
        remote_user="agi",
        scheduler="192.168.20.111:8786",
        manager_user="manager",
    )

    assert refreshed is True
    assert message == "LAN discovery refreshed: 2 node(s), 1 ready."
    options = captured["options"]
    assert options.remote_user == "agi"
    assert options.scheduler == "192.168.20.111"
    assert options.manager_user == "manager"
    assert options.tcp_timeout == orchestrate_cluster.LAN_UI_TCP_TIMEOUT
    assert options.ssh_timeout == orchestrate_cluster.LAN_UI_SSH_TIMEOUT
    assert options.max_hosts == orchestrate_cluster.LAN_UI_MAX_HOSTS
    assert options.probe_workers == orchestrate_cluster.LAN_UI_PROBE_WORKERS
    assert options.cache_path == cache_path


def _disable_lan_defaults(monkeypatch):
    monkeypatch.setattr(orchestrate_cluster, "_lan_discovery_cluster_defaults", lambda *_, **__: {})
    monkeypatch.setattr(orchestrate_cluster, "_lan_discovery_invalid_worker_hosts", lambda *_, **__: set())


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


def test_render_cluster_settings_ui_can_hide_run_mode_info(monkeypatch, tmp_path):
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

    orchestrate_cluster.render_cluster_settings_ui(env, deps, show_run_mode_info=False)

    assert fake_st.session_state["mode"] == 11
    assert not any(message.startswith("Run mode ") for message in fake_st.infos)
    assert writes["cleared"] is True


def test_render_cluster_settings_ui_populates_empty_cluster_from_lan_discovery(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit(
        widget_values={
            "cluster_enabled__demo_project": True,
            "cluster_cython__demo_project": False,
            "cluster_pool__demo_project": False,
            "cluster_rapids__demo_project": False,
            "cluster_use_key__demo_project": True,
        },
        session_state={
            "app_settings": {"cluster": {"workers": {"127.0.0.1": 1}}},
            "benchmark": False,
        },
    )
    monkeypatch.setattr(orchestrate_cluster, "st", fake_st)
    monkeypatch.setattr(
        orchestrate_cluster,
        "_lan_discovery_cluster_defaults",
        lambda *_, **__: {
            "scheduler": "192.168.3.103:8786",
            "workers": {"192.168.3.35": 1},
        },
    )

    deps = orchestrate_cluster.OrchestrateClusterDeps(
        parse_and_validate_scheduler=lambda raw: raw,
        parse_and_validate_workers=lambda raw: {"192.168.3.35": 1} if "192.168.3.35" in raw else None,
        write_app_settings_toml=lambda _path, settings: settings,
        clear_load_toml_cache=lambda: None,
        set_env_var=lambda _key, _value: None,
        agi_env_envars={},
    )
    share = tmp_path / "share"
    share.mkdir()
    env = SimpleNamespace(
        app="demo_project",
        is_managed_pc=False,
        agi_share_path=Path("clustershare"),
        share_root_path=lambda: share,
        user="agi",
        password=None,
        ssh_key_path=None,
        app_settings_file=tmp_path / "app_settings.toml",
    )

    orchestrate_cluster.render_cluster_settings_ui(env, deps)

    cluster = fake_st.session_state.app_settings["cluster"]
    assert cluster["scheduler"] == "192.168.3.103:8786"
    assert cluster["workers"] == {"192.168.3.35": 1}
    assert cluster["workers_data_path"] == "clustershare"
    assert fake_st.session_state["cluster_scheduler__demo_project"] == "192.168.3.103:8786"
    assert fake_st.session_state["cluster_workers__demo_project"] == '{\n  "192.168.3.35": 1\n}'
    assert fake_st.session_state["cluster_workers_data_path__demo_project"] == "clustershare"


def test_render_cluster_settings_ui_preserves_explicit_cluster_values_over_lan_discovery(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit(
        widget_values={
            "cluster_enabled__demo_project": True,
            "cluster_cython__demo_project": False,
            "cluster_pool__demo_project": False,
            "cluster_rapids__demo_project": False,
            "cluster_scheduler__demo_project": "10.0.0.10:8786",
            "cluster_workers__demo_project": '{"10.0.0.11": 2}',
            "cluster_use_key__demo_project": True,
        },
        session_state={
            "app_settings": {
                "cluster": {
                    "scheduler": "10.0.0.10:8786",
                    "workers": {"10.0.0.11": 2},
                }
            },
            "benchmark": False,
        },
    )
    monkeypatch.setattr(orchestrate_cluster, "st", fake_st)
    monkeypatch.setattr(
        orchestrate_cluster,
        "_lan_discovery_cluster_defaults",
        lambda *_, **__: {
            "scheduler": "192.168.3.103:8786",
            "workers": {"192.168.3.35": 1},
        },
    )

    deps = orchestrate_cluster.OrchestrateClusterDeps(
        parse_and_validate_scheduler=lambda raw: raw,
        parse_and_validate_workers=lambda raw: {"10.0.0.11": 2} if "10.0.0.11" in raw else None,
        write_app_settings_toml=lambda _path, settings: settings,
        clear_load_toml_cache=lambda: None,
        set_env_var=lambda _key, _value: None,
        agi_env_envars={},
    )
    share = tmp_path / "share"
    share.mkdir()
    env = SimpleNamespace(
        app="demo_project",
        is_managed_pc=False,
        agi_share_path=Path("clustershare"),
        share_root_path=lambda: share,
        user="agi",
        password=None,
        ssh_key_path=None,
        app_settings_file=tmp_path / "app_settings.toml",
    )

    orchestrate_cluster.render_cluster_settings_ui(env, deps)

    cluster = fake_st.session_state.app_settings["cluster"]
    assert cluster["scheduler"] == "10.0.0.10:8786"
    assert cluster["workers"] == {"10.0.0.11": 2}


def test_render_cluster_settings_ui_prunes_non_ready_lan_workers(monkeypatch, tmp_path):
    app_name = "demo_project"
    widget_keys = orchestrate_cluster.cluster_widget_keys(app_name)
    home = tmp_path / "agilab-home"
    cache_path = home / ".agilab" / "lan_nodes.json"
    cache_path.parent.mkdir(parents=True)
    cache_path.write_text(
        json.dumps(
            {
                "local_hosts": ["192.168.20.111"],
                "nodes": [
                    {
                        "host": "192.168.20.1",
                        "status": "ssh-auth-needed",
                        "sources": ["arp", "cache", "tcp-scan"],
                        "tcp_ssh_open": True,
                    },
                    {
                        "host": "192.168.20.15",
                        "status": "uv-missing",
                        "sources": ["arp", "cache", "known-hosts", "tcp-scan"],
                        "tcp_ssh_open": True,
                        "ssh_auth": True,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    stale_workers = {
        "192.168.20.1": 1,
        "192.168.20.111": 1,
        "192.168.20.15": 1,
    }
    fake_st = _FakeStreamlit(
        widget_values={
            widget_keys["cluster_enabled"]: True,
            widget_keys["cython"]: False,
            widget_keys["pool"]: False,
            widget_keys["rapids"]: False,
            widget_keys["use_key"]: True,
        },
        session_state={
            "app_settings": {
                "cluster": {
                    "cluster_enabled": True,
                    "scheduler": "192.168.20.111:8786",
                    "workers": stale_workers,
                }
            },
            widget_keys["workers"]: json.dumps(stale_workers, indent=2),
            "benchmark": False,
        },
    )
    monkeypatch.setattr(orchestrate_cluster, "st", fake_st)

    share = tmp_path / "cluster-share"
    share.mkdir()
    deps = orchestrate_cluster.OrchestrateClusterDeps(
        parse_and_validate_scheduler=lambda raw: raw,
        parse_and_validate_workers=lambda raw: json.loads(raw),
        write_app_settings_toml=lambda _path, settings: settings,
        clear_load_toml_cache=lambda: None,
        set_env_var=lambda _key, _value: None,
        agi_env_envars={},
    )
    env = SimpleNamespace(
        app=app_name,
        home_abs=home,
        is_managed_pc=False,
        agi_share_path=Path("clustershare"),
        share_root_path=lambda: share,
        user="agi",
        password=None,
        ssh_key_path=None,
        app_settings_file=tmp_path / "app_settings.toml",
    )

    orchestrate_cluster.render_cluster_settings_ui(env, deps)

    cluster = fake_st.session_state.app_settings["cluster"]
    assert cluster["workers"] == {"192.168.20.111": 1}
    assert json.loads(fake_st.session_state[widget_keys["workers"]]) == {"192.168.20.111": 1}
    assert "192.168.20.1" not in json.loads(fake_st.session_state[widget_keys["workers"]])
    assert "192.168.20.15" not in json.loads(fake_st.session_state[widget_keys["workers"]])


def test_render_cluster_settings_ui_refresh_replaces_stale_lan_discovery_state(monkeypatch, tmp_path):
    app_name = "demo_project"
    widget_keys = orchestrate_cluster.cluster_widget_keys(app_name)
    refresh_calls = []
    fake_st = _FakeStreamlit(
        widget_values={
            widget_keys["cluster_enabled"]: True,
            widget_keys["cython"]: False,
            widget_keys["pool"]: False,
            widget_keys["rapids"]: False,
            widget_keys["use_key"]: True,
        },
        button_values={
            orchestrate_cluster._lan_discovery_refresh_key(app_name): True,
        },
        session_state={
            "app_settings": {
                "cluster": {
                    "cluster_enabled": True,
                    "scheduler": "10.0.0.10:8786",
                    "workers": {"10.0.0.11": 2},
                    "workers_data_path": "/old/share",
                }
            },
            widget_keys["scheduler"]: "10.0.0.10:8786",
            widget_keys["user"]: "agi",
            widget_keys["workers"]: '{"10.0.0.11": 2}',
            widget_keys["workers_data_path"]: "/old/share",
            "benchmark": False,
        },
    )
    monkeypatch.setattr(orchestrate_cluster, "st", fake_st)
    monkeypatch.setattr(
        orchestrate_cluster,
        "_lan_discovery_cluster_defaults",
        lambda *_, **__: {
            "scheduler": "192.168.3.103:8786",
            "workers": {"192.168.3.35": 1},
        },
    )
    monkeypatch.setattr(
        orchestrate_cluster,
        "_refresh_lan_discovery_cache",
        lambda cache_path, **kwargs: refresh_calls.append((cache_path, kwargs))
        or (True, "LAN discovery refreshed: 1 node(s), 1 ready."),
    )

    share = tmp_path / "cluster-share"
    share.mkdir()
    deps = orchestrate_cluster.OrchestrateClusterDeps(
        parse_and_validate_scheduler=lambda raw: raw,
        parse_and_validate_workers=lambda raw: {"192.168.3.35": 1} if "192.168.3.35" in raw else None,
        write_app_settings_toml=lambda _path, settings: settings,
        clear_load_toml_cache=lambda: None,
        set_env_var=lambda _key, _value: None,
        agi_env_envars={},
    )
    env = SimpleNamespace(
        app=app_name,
        home_abs=tmp_path / "agilab-home",
        is_managed_pc=False,
        agi_share_path=Path("clustershare"),
        share_root_path=lambda: share,
        user="agi",
        password=None,
        ssh_key_path=None,
        app_settings_file=tmp_path / "app_settings.toml",
    )

    orchestrate_cluster.render_cluster_settings_ui(env, deps)

    cluster = fake_st.session_state.app_settings["cluster"]
    assert cluster["scheduler"] == "192.168.3.103:8786"
    assert cluster["workers"] == {"192.168.3.35": 1}
    assert cluster["workers_data_path"] == "clustershare"
    assert fake_st.session_state[widget_keys["scheduler"]] == "192.168.3.103:8786"
    assert fake_st.session_state[widget_keys["workers"]] == '{\n  "192.168.3.35": 1\n}'
    assert fake_st.session_state[widget_keys["workers_data_path"]] == "clustershare"
    assert refresh_calls
    assert refresh_calls[0][1]["remote_user"] == "agi"
    assert refresh_calls[0][1]["scheduler"] == "10.0.0.10:8786"
    assert any("LAN discovery refreshed" in info for info in fake_st.infos)


def test_render_cluster_settings_ui_clear_lan_cache_button_deletes_inventory(monkeypatch, tmp_path):
    app_name = "demo_project"
    widget_keys = orchestrate_cluster.cluster_widget_keys(app_name)
    home = tmp_path / "agilab-home"
    cache_path = home / ".agilab" / "lan_nodes.json"
    cache_path.parent.mkdir(parents=True)
    cache_path.write_text(
        json.dumps(
            {
                "local_hosts": ["192.168.3.103"],
                "nodes": [{"host": "192.168.3.35", "status": "ready"}],
            }
        ),
        encoding="utf-8",
    )
    fake_st = _FakeStreamlit(
        widget_values={
            widget_keys["cluster_enabled"]: True,
            widget_keys["cython"]: False,
            widget_keys["pool"]: False,
            widget_keys["rapids"]: False,
            widget_keys["use_key"]: True,
        },
        button_values={
            orchestrate_cluster._lan_discovery_clear_key(app_name): True,
        },
        session_state={"app_settings": {"cluster": {}}, "benchmark": False},
    )
    monkeypatch.setattr(orchestrate_cluster, "st", fake_st)

    share = tmp_path / "cluster-share"
    share.mkdir()
    deps = orchestrate_cluster.OrchestrateClusterDeps(
        parse_and_validate_scheduler=lambda raw: raw,
        parse_and_validate_workers=lambda _raw: None,
        write_app_settings_toml=lambda _path, settings: settings,
        clear_load_toml_cache=lambda: None,
        set_env_var=lambda _key, _value: None,
        agi_env_envars={},
    )
    env = SimpleNamespace(
        app=app_name,
        home_abs=home,
        is_managed_pc=False,
        agi_share_path=Path("clustershare"),
        share_root_path=lambda: share,
        user="agi",
        password=None,
        ssh_key_path=None,
        app_settings_file=tmp_path / "app_settings.toml",
    )

    orchestrate_cluster.render_cluster_settings_ui(env, deps)

    cluster = fake_st.session_state.app_settings["cluster"]
    assert not cache_path.exists()
    assert "scheduler" not in cluster
    assert "workers" not in cluster
    assert any("LAN discovery cache cleared" in info for info in fake_st.infos)


def test_render_cluster_settings_ui_blocks_cluster_when_share_is_unusable(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit(
        widget_values={
            "cluster_enabled__demo_project": True,
            "cluster_cython__demo_project": False,
            "cluster_pool__demo_project": False,
            "cluster_rapids__demo_project": False,
        },
        session_state={"app_settings": {"cluster": {}}, "benchmark": False},
    )
    monkeypatch.setattr(orchestrate_cluster, "st", fake_st)
    deps = orchestrate_cluster.OrchestrateClusterDeps(
        parse_and_validate_scheduler=lambda raw: raw,
        parse_and_validate_workers=lambda raw: {"parsed": raw},
        write_app_settings_toml=lambda _path, settings: settings,
        clear_load_toml_cache=lambda: None,
        set_env_var=lambda _key, _value: None,
        agi_env_envars={},
    )
    unusable_share = tmp_path / "not-a-directory"
    unusable_share.write_text("not a directory", encoding="utf-8")
    env = SimpleNamespace(
        app="demo_project",
        is_managed_pc=False,
        AGI_CLUSTER_SHARE=str(unusable_share),
        agi_share_path=Path("localshare"),
        share_root_path=lambda: tmp_path / "localshare",
        user="agi",
        password=None,
        ssh_key_path=None,
        app_settings_file=tmp_path / "app_settings.toml",
    )

    orchestrate_cluster.render_cluster_settings_ui(env, deps)

    cluster = fake_st.session_state.app_settings["cluster"]
    assert cluster["cluster_enabled"] is False
    assert fake_st.session_state.dask is False
    assert fake_st.session_state["mode"] == 0
    assert fake_st.errors
    assert "AGI_CLUSTER_SHARE" in fake_st.errors[-1]
    assert fake_st.session_state["cluster_enabled__demo_project__reset"] is True


def test_render_cluster_settings_ui_creates_missing_cluster_share(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit(
        widget_values={
            "cluster_enabled__demo_project": True,
            "cluster_cython__demo_project": False,
            "cluster_pool__demo_project": False,
            "cluster_rapids__demo_project": False,
            "cluster_use_key__demo_project": True,
        },
        session_state={"app_settings": {"cluster": {}}, "benchmark": False},
    )
    monkeypatch.setattr(orchestrate_cluster, "st", fake_st)
    _disable_lan_defaults(monkeypatch)
    deps = orchestrate_cluster.OrchestrateClusterDeps(
        parse_and_validate_scheduler=lambda raw: raw,
        parse_and_validate_workers=lambda raw: {"parsed": raw},
        write_app_settings_toml=lambda _path, settings: settings,
        clear_load_toml_cache=lambda: None,
        set_env_var=lambda _key, _value: None,
        agi_env_envars={},
    )
    missing_share = tmp_path / "clustershare" / "agi"
    env = SimpleNamespace(
        app="demo_project",
        is_managed_pc=False,
        AGI_CLUSTER_SHARE=str(missing_share),
        agi_share_path=Path("localshare"),
        share_root_path=lambda: missing_share,
        user="agi",
        password=None,
        ssh_key_path=None,
        app_settings_file=tmp_path / "app_settings.toml",
    )

    orchestrate_cluster.render_cluster_settings_ui(env, deps)

    cluster = fake_st.session_state.app_settings["cluster"]
    assert missing_share.is_dir()
    assert cluster["cluster_enabled"] is True
    assert cluster["workers_data_path"] == str(missing_share)
    assert fake_st.errors == []


def test_render_cluster_settings_ui_replaces_stale_local_workers_data_path(monkeypatch, tmp_path):
    app_name = "demo_project"
    widget_keys = orchestrate_cluster.cluster_widget_keys(app_name)
    local_share = tmp_path / "localshare" / "agi"
    cluster_share = tmp_path / "clustershare" / "agi"
    local_share.mkdir(parents=True)
    cluster_share.mkdir(parents=True)
    fake_st = _FakeStreamlit(
        widget_values={
            widget_keys["cluster_enabled"]: True,
            widget_keys["cython"]: False,
            widget_keys["pool"]: False,
            widget_keys["rapids"]: False,
            widget_keys["use_key"]: True,
        },
        session_state={
            "app_settings": {
                "cluster": {
                    "cluster_enabled": True,
                    "workers_data_path": str(local_share),
                }
            },
            widget_keys["workers_data_path"]: str(local_share),
            "benchmark": False,
        },
    )
    monkeypatch.setattr(orchestrate_cluster, "st", fake_st)
    _disable_lan_defaults(monkeypatch)

    deps = orchestrate_cluster.OrchestrateClusterDeps(
        parse_and_validate_scheduler=lambda _raw: None,
        parse_and_validate_workers=lambda _raw: None,
        write_app_settings_toml=lambda _path, settings: settings,
        clear_load_toml_cache=lambda: None,
        set_env_var=lambda _key, _value: None,
        agi_env_envars={},
    )
    env = SimpleNamespace(
        app=app_name,
        home_abs=tmp_path,
        is_managed_pc=False,
        AGI_LOCAL_SHARE=str(local_share),
        AGI_CLUSTER_SHARE=str(cluster_share),
        agi_share_path=Path("localshare/agi"),
        share_root_path=lambda: local_share,
        user="agi",
        password=None,
        ssh_key_path=None,
        app_settings_file=tmp_path / "app_settings.toml",
    )

    orchestrate_cluster.render_cluster_settings_ui(env, deps)

    cluster = fake_st.session_state.app_settings["cluster"]
    assert cluster["workers_data_path"] == "clustershare/agi"
    assert fake_st.session_state[widget_keys["workers_data_path"]] == "clustershare/agi"


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
    _disable_lan_defaults(monkeypatch)

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
    assert all("agi_share_path" not in text for text in fake_st.markdowns)
    assert all(not ("clustershare" in text and "→" in text) for text in fake_st.markdowns)
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
    _disable_lan_defaults(monkeypatch)

    env_calls: list[tuple[str, str]] = []
    deps = orchestrate_cluster.OrchestrateClusterDeps(
        parse_and_validate_scheduler=lambda _raw: None,
        parse_and_validate_workers=lambda _raw: None,
        write_app_settings_toml=lambda _path, settings: settings,
        clear_load_toml_cache=lambda: (_ for _ in ()).throw(RuntimeError("cache boom")),
        set_env_var=lambda key, value: env_calls.append((key, value)),
        agi_env_envars={"CLUSTER_CREDENTIALS": "old:user", "AGI_SSH_KEY_PATH": "~/.ssh/old"},
    )
    share = tmp_path / "share"
    share.mkdir()
    env = SimpleNamespace(
        app="demo_project",
        is_managed_pc=False,
        agi_share_path=Path("clustershare"),
        share_root_path=lambda: share,
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


def test_render_cluster_settings_ui_persists_cleared_workers_data_path(monkeypatch, tmp_path):
    fake_st = _FakeStreamlit(
        widget_values={
            "cluster_enabled__demo_project": True,
            "cluster_cython__demo_project": False,
            "cluster_pool__demo_project": False,
            "cluster_rapids__demo_project": False,
            "cluster_use_key__demo_project": True,
            "cluster_user__demo_project": "agi",
            "cluster_ssh_key__demo_project": "",
            "cluster_scheduler__demo_project": "",
            "cluster_workers__demo_project": "",
            "cluster_workers_data_path__demo_project": "",
        },
        session_state={
            "app_settings": {
                "cluster": {
                    "cluster_enabled": True,
                    "workers_data_path": "/old/share",
                }
            },
            "benchmark": False,
        },
    )
    monkeypatch.setattr(orchestrate_cluster, "st", fake_st)
    _disable_lan_defaults(monkeypatch)

    deps = orchestrate_cluster.OrchestrateClusterDeps(
        parse_and_validate_scheduler=lambda _raw: None,
        parse_and_validate_workers=lambda _raw: None,
        write_app_settings_toml=lambda _path, settings: settings,
        clear_load_toml_cache=lambda: None,
        set_env_var=lambda _key, _value: None,
        agi_env_envars={},
    )
    share = tmp_path / "share"
    share.mkdir()
    env = SimpleNamespace(
        app="demo_project",
        is_managed_pc=False,
        agi_share_path=Path("clustershare"),
        share_root_path=lambda: share,
        user="agi",
        password=None,
        ssh_key_path=None,
        app_settings_file=tmp_path / "app_settings.toml",
    )

    orchestrate_cluster.render_cluster_settings_ui(env, deps)

    cluster = fake_st.session_state.app_settings["cluster"]
    assert cluster["workers_data_path"] == ""


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
    _disable_lan_defaults(monkeypatch)

    env_calls: list[tuple[str, str]] = []
    deps = orchestrate_cluster.OrchestrateClusterDeps(
        parse_and_validate_scheduler=lambda _raw: None,
        parse_and_validate_workers=lambda _raw: None,
        write_app_settings_toml=lambda _path, settings: settings,
        clear_load_toml_cache=lambda: None,
        set_env_var=lambda key, value: env_calls.append((key, value)),
        agi_env_envars={"CLUSTER_CREDENTIALS": ""},
    )
    share = tmp_path / "share"
    share.mkdir()
    env = SimpleNamespace(
        app="demo_project",
        is_managed_pc=False,
        agi_share_path=Path("clustershare"),
        share_root_path=lambda: share,
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
    _disable_lan_defaults(monkeypatch)

    env_calls: list[tuple[str, str]] = []
    deps = orchestrate_cluster.OrchestrateClusterDeps(
        parse_and_validate_scheduler=lambda _raw: None,
        parse_and_validate_workers=lambda _raw: None,
        write_app_settings_toml=lambda _path, settings: settings,
        clear_load_toml_cache=lambda: None,
        set_env_var=lambda key, value: env_calls.append((key, value)),
        agi_env_envars={"AGI_SSH_KEY_PATH": ""},
    )
    share = tmp_path / "share"
    share.mkdir()
    env = SimpleNamespace(
        app="demo_project",
        is_managed_pc=False,
        agi_share_path=Path("clustershare"),
        share_root_path=lambda: share,
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
