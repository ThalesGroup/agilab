import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from agi_env.cython_build_config import CYTHON_BUILD_REQUIREMENT
from agi_cluster.agi_distributor import deployment_remote_support, uv_source_support


@pytest.mark.parametrize(
    ("system", "machine", "product_version", "expected"),
    [
        ("Darwin", "x86_64", "10.15.8", True),
        ("Darwin", "x86_64", "10.14.6", True),
        ("Darwin", "x86_64", "11.7.10", False),
        ("Darwin", "arm64", "10.15.8", False),
        ("Linux", "x86_64", "10.15.8", False),
        ("Darwin", "x86_64", "", False),
    ],
)
def test_is_legacy_intel_macos_scope(system, machine, product_version, expected):
    assert (
        deployment_remote_support._is_legacy_intel_macos(
            system, machine, product_version
        )
        is expected
    )


def _rapids_probe_output(capable: bool) -> str:
    return json.dumps(
        {
            "rapids_capable": capable,
            "probe": "nvidia-smi",
            "gpus": ["NVIDIA A100"] if capable else [],
        }
    )


def test_parse_remote_rapids_probe_accepts_log_wrapped_json():
    output = "banner\nagilab.cli.rapids_probe " + _rapids_probe_output(True) + "\n"

    assert deployment_remote_support._parse_remote_rapids_probe(output) is True


def test_parse_remote_rapids_probe_rejects_missing_json():
    with pytest.raises(ValueError, match="Remote RAPIDS probe did not return JSON"):
        deployment_remote_support._parse_remote_rapids_probe("no json here")


def test_remote_deployment_path_and_probe_helpers(tmp_path):
    env = SimpleNamespace(home_abs=tmp_path / "home")
    assert deployment_remote_support._resolve_local_share_path("share", env) == (
        tmp_path / "home" / "share"
    ).resolve(strict=False)
    assert (
        deployment_remote_support._remote_share_assignment("~/clustershare")
        == '"$HOME"/clustershare'
    )
    assert deployment_remote_support._remote_share_assignment("~") == '"$HOME"'
    assert (
        deployment_remote_support._remote_share_assignment("/mnt/share") == "/mnt/share"
    )
    assert (
        deployment_remote_support._home_relative_share_setting(
            str(tmp_path / "home" / "clustershare"), env
        )
        == "clustershare"
    )
    assert (
        deployment_remote_support._home_relative_share_setting(
            "/Users/demo/clustershare", SimpleNamespace()
        )
        == "clustershare"
    )

    assert (
        deployment_remote_support._scheduler_host_from_state(
            SimpleNamespace(_scheduler_ip="tcp://user@[fe80::1]:8786")
        )
        == "fe80::1"
    )
    assert (
        deployment_remote_support._scheduler_host_from_state(
            SimpleNamespace(_scheduler_ip="tcp://user@10.0.0.1:8786")
        )
        == "10.0.0.1"
    )
    assert (
        deployment_remote_support._scheduler_ssh_target(
            SimpleNamespace(_scheduler_ip="10.0.0.1"), SimpleNamespace(user="agi")
        )
        == "agi@10.0.0.1"
    )
    assert (
        deployment_remote_support._scheduler_ssh_target(
            SimpleNamespace(_scheduler_ip=""), SimpleNamespace(user="agi")
        )
        == ""
    )
    local_share = tmp_path / "home" / "clustershare" / "agi"
    assert deployment_remote_support._remote_cluster_share_root_setting(
        "clustershare/agi/workflows/session-123",
        local_share_setting=str(local_share),
        env=env,
    ) == "clustershare/agi"
    with pytest.raises(ValueError, match=r"must not contain '\.\.' traversal"):
        deployment_remote_support._remote_cluster_share_root_setting(
            "clustershare/agi/../outside",
            local_share_setting=str(local_share),
            env=env,
        )

    assert deployment_remote_support._parse_version_prefix("10.15.7-extra") == (
        10,
        15,
        7,
    )
    assert deployment_remote_support._parse_version_prefix("beta") == ()
    assert (
        deployment_remote_support._parse_remote_rapids_probe(
            '{"rapids_capable": false}\n[]\n{bad json}\n'
        )
        is False
    )


def test_remote_cluster_share_root_setting_strips_default_user_workflow_suffix(tmp_path):
    env = SimpleNamespace(home_abs=tmp_path, user="agi")

    assert deployment_remote_support._remote_cluster_share_root_setting(
        "clustershare/agi/workflow-123/session-456",
        local_share_setting=str(tmp_path / "scheduler-share"),
        env=env,
    ) == "clustershare/agi"


@pytest.mark.parametrize(
    "remote_share",
    (
        "/mnt/agilab",
        "/mnt/agilab/agi/workflows/session-123",
    ),
)
def test_remote_cluster_share_root_setting_preserves_absolute_physical_root(
    remote_share,
):
    env = SimpleNamespace(home_abs=Path("/home/agi"), user="agi")

    assert deployment_remote_support._remote_cluster_share_root_setting(
        remote_share,
        local_share_setting="/mnt/agilab",
        env=env,
    ) == "/mnt/agilab"


def test_remote_command_helpers_quote_dynamic_arguments():
    command = deployment_remote_support._remote_command(
        "uv",
        "--project",
        "worker env/$bad;name",
        "run",
        "-p",
        "3.13; echo bad",
        "python",
        "-c",
        "import pip",
    )

    assert command == (
        "uv --project 'worker env/$bad;name' run -p '3.13; echo bad' "
        "python -c 'import pip'"
    )
    assert (
        deployment_remote_support._remote_tool("source ~/.profile &&", "uv tool")
        == "source ~/.profile && uv tool"
    )
    assert deployment_remote_support._remote_tool("", "uv --quiet") == "uv --quiet"


def test_sshfs_source_host_parses_common_sources():
    assert (
        deployment_remote_support._sshfs_source_host(
            "agi@192.168.20.15:/home/agi/clustershare"
        )
        == "192.168.20.15"
    )
    assert (
        deployment_remote_support._sshfs_source_host(
            "sshfs#agi@worker.local:/home/agi/clustershare"
        )
        == "worker.local"
    )
    assert (
        deployment_remote_support._sshfs_source_host(
            "agi@[2001:db8::1]:/home/agi/clustershare"
        )
        == "2001:db8::1"
    )


def test_remote_environment_and_scheduler_port_edge_helpers(monkeypatch):
    assert deployment_remote_support._env_lookup(SimpleNamespace(FIRST="attr"), "FIRST") == "attr"
    assert (
        deployment_remote_support._env_lookup(
            SimpleNamespace(envars={"SECOND": "from-env-map"}),
            "FIRST",
            "SECOND",
        )
        == "from-env-map"
    )
    monkeypatch.setenv("FALLBACK_PORT", "2222")
    assert deployment_remote_support._env_lookup(SimpleNamespace(envars={}), "FALLBACK_PORT") == "2222"
    assert deployment_remote_support._shell_words("") == ""
    assert deployment_remote_support._scheduler_ssh_port(SimpleNamespace(envars={})) == 22

    with pytest.raises(ValueError, match="Invalid scheduler SSH port"):
        deployment_remote_support._scheduler_ssh_port(
            SimpleNamespace(envars={"AGILAB_SCHEDULER_SSH_PORT": "abc"})
        )
    with pytest.raises(ValueError, match="Invalid scheduler SSH port"):
        deployment_remote_support._scheduler_ssh_port(
            SimpleNamespace(envars={"AGILAB_SCHEDULER_SSH_PORT": "70000"})
        )


@pytest.mark.asyncio
async def test_remote_deployment_mount_and_platform_error_edges(tmp_path):
    no_scheduler_calls: list[str] = []

    class _AgiNoScheduler:
        _scheduler_ip = ""

        async def exec_ssh(self, _ip, cmd):
            no_scheduler_calls.append(cmd)
            return "ok"

    env = SimpleNamespace(
        AGI_CLUSTER_SHARE="share", envars={}, home_abs=tmp_path, user="", verbose=0
    )
    with pytest.raises(RuntimeError, match="scheduler host is unknown"):
        await deployment_remote_support._prepare_remote_cluster_share(
            _AgiNoScheduler(), "10.0.0.2", env, "clustershare"
        )
    assert no_scheduler_calls == []

    calls: list[str] = []

    class _Agi:
        async def exec_ssh(self, _ip, cmd):
            calls.append(cmd)
            if cmd == deployment_remote_support._remote_platform_probe_command():
                raise RuntimeError("probe failed")
            return "ok"

    assert (
        await deployment_remote_support._legacy_intel_macos_dependency_specs(
            _Agi(), "10.0.0.2"
        )
        == ()
    )
    assert calls == [deployment_remote_support._remote_platform_probe_command()]


@pytest.mark.asyncio
async def test_legacy_intel_macos_specs_reuse_cached_probe_result():
    # Regression (#31): when prepare_cluster_env already probed the worker
    # platform and recorded the legacy Intel macOS IPs, deploy_remote_worker
    # must reuse that result instead of re-running the SSH probe per worker.
    probe_calls: list[str] = []

    class _Agi:
        _legacy_intel_macos_ips = {"10.0.0.9"}

        async def exec_ssh(self, _ip, cmd):
            probe_calls.append(cmd)
            return "Darwin\nx86_64\n10.15.7\n"

    agi = _Agi()

    # Cached legacy IP: specs returned without any SSH probe.
    specs = await deployment_remote_support._legacy_intel_macos_dependency_specs(
        agi, "10.0.0.9"
    )
    assert specs == deployment_remote_support._LEGACY_INTEL_MACOS_DEPENDENCY_SPECS

    # IP not in the cached set: not legacy, still no SSH probe.
    assert (
        await deployment_remote_support._legacy_intel_macos_dependency_specs(
            agi, "10.0.0.10"
        )
        == ()
    )
    assert probe_calls == []


def test_env_lookup_warns_on_conflicting_aliases(monkeypatch):
    # Regression (#17): first-match precedence is preserved, but conflicting
    # alias values for the same setting emit a one-time warning naming the
    # effective source.
    deployment_remote_support._ALIAS_CONFLICT_WARNED.clear()
    warnings: list[str] = []
    monkeypatch.setattr(
        deployment_remote_support.logger,
        "warning",
        lambda message, *args: warnings.append(message % args if args else message),
    )

    env = SimpleNamespace(envars={"PRIMARY": "8022", "SECONDARY": "9022"})
    resolved = deployment_remote_support._env_lookup(env, "PRIMARY", "SECONDARY")

    # First-match precedence unchanged.
    assert resolved == "8022"
    assert len(warnings) == 1
    assert "PRIMARY" in warnings[0]
    assert "8022" in warnings[0]
    assert "9022" in warnings[0]

    # Repeated lookups with the same conflict do not re-warn.
    deployment_remote_support._env_lookup(env, "PRIMARY", "SECONDARY")
    assert len(warnings) == 1


def test_env_lookup_no_warning_when_aliases_agree(monkeypatch):
    deployment_remote_support._ALIAS_CONFLICT_WARNED.clear()
    warnings: list[str] = []
    monkeypatch.setattr(
        deployment_remote_support.logger,
        "warning",
        lambda message, *args: warnings.append(message % args if args else message),
    )

    env = SimpleNamespace(envars={"PRIMARY": "8022", "SECONDARY": "8022"})
    assert deployment_remote_support._env_lookup(env, "PRIMARY", "SECONDARY") == "8022"
    assert warnings == []


@pytest.mark.asyncio
async def test_prepare_remote_cluster_share_logs_premounted_verbose_path(tmp_path):
    env = SimpleNamespace(
        AGI_CLUSTER_SHARE=str(tmp_path / "scheduler-share"),
        envars={"AGILAB_REMOTE_CLUSTER_SHARE_PREMOUNTED": "1"},
        home_abs=tmp_path,
        user="agi",
        verbose=1,
    )
    ssh_calls: list[str] = []
    log = mock.Mock()

    class _AgiNoScheduler:
        _scheduler_ip = ""

        async def exec_ssh(self, _ip, cmd):
            ssh_calls.append(cmd)
            return "ok"

    await deployment_remote_support._prepare_remote_cluster_share(
        _AgiNoScheduler(), "192.168.20.15", env, "clustershare", log=log
    )

    log.info.assert_called_once()
    assert len(ssh_calls) == 2
    assert "Pre-mounted AGILAB cluster share" in ssh_calls[0]
    assert "AGI_CLUSTER_ENABLED=" in ssh_calls[1]


@pytest.mark.asyncio
async def test_prepare_remote_cluster_share_does_not_persist_env_when_premounted_check_fails(
    tmp_path,
):
    env = SimpleNamespace(
        AGI_CLUSTER_SHARE=str(tmp_path / "scheduler-share"),
        envars={"AGILAB_REMOTE_CLUSTER_SHARE_PREMOUNTED": "1"},
        home_abs=tmp_path,
        user="agi",
        verbose=0,
    )
    ssh_calls: list[str] = []

    class _AgiNoScheduler:
        _scheduler_ip = ""

        async def exec_ssh(self, _ip, cmd):
            ssh_calls.append(cmd)
            raise RuntimeError("pre-mounted share unavailable")

    with pytest.raises(RuntimeError, match="pre-mounted share unavailable"):
        await deployment_remote_support._prepare_remote_cluster_share(
            _AgiNoScheduler(), "192.168.20.15", env, "clustershare"
        )

    assert len(ssh_calls) == 1
    assert "Pre-mounted AGILAB cluster share" in ssh_calls[0]
    assert not any("AGI_CLUSTER_ENABLED=" in cmd for cmd in ssh_calls)


@pytest.mark.asyncio
async def test_prepare_remote_cluster_share_does_not_persist_env_when_mount_fails(
    tmp_path,
):
    env = SimpleNamespace(
        AGI_CLUSTER_SHARE=str(tmp_path / "scheduler-share"),
        envars={},
        home_abs=tmp_path,
        user="agi",
        verbose=0,
    )
    ssh_calls: list[str] = []

    class _Agi:
        _scheduler_ip = "192.168.20.111"

        async def exec_ssh(self, _ip, cmd):
            ssh_calls.append(cmd)
            raise RuntimeError("sshfs mount failed")

    with pytest.raises(RuntimeError, match="sshfs mount failed"):
        await deployment_remote_support._prepare_remote_cluster_share(
            _Agi(), "192.168.20.15", env, "clustershare"
        )

    assert len(ssh_calls) == 1
    assert "SCHEDULER_CLUSTER_SHARE" in ssh_calls[0]
    assert not any("AGI_CLUSTER_ENABLED=" in cmd for cmd in ssh_calls)


@pytest.mark.parametrize(
    "remote_share",
    [
        "../victim",
        "clustershare/../victim",
        r"clustershare\..\victim",
        "clustershare/evil\x00target",
        r"C:relative\share",
        r"C:\absolute\share",
        r"\\server\share",
        "",
        ".",
        "./",
        "./.",
        "~",
        "~/",
        "/",
        "//",
        "/./",
        "/home/agi",
        "/home/agi/.",
        "//home/agi/.",
        "/Users/agi",
        "/Users/agi/.",
        "/root",
        "/root/.",
        "/var/root",
        "/var/root/.",
        "/etc",
        "/etc/.",
        "/mnt",
        "/mnt/.",
    ],
)
@pytest.mark.asyncio
async def test_prepare_remote_cluster_share_rejects_unsafe_worker_target_before_ssh(
    tmp_path,
    remote_share,
):
    env = SimpleNamespace(
        AGI_CLUSTER_SHARE=str(tmp_path / "scheduler-share"),
        envars={},
        home_abs=tmp_path,
        user="agi",
        verbose=0,
    )
    ssh_calls: list[str] = []

    class _Agi:
        _scheduler_ip = "192.168.20.111"

        async def exec_ssh(self, _ip, cmd):
            ssh_calls.append(cmd)
            return "ok"

    with pytest.raises(ValueError, match="Workers Data Path"):
        await deployment_remote_support._prepare_remote_cluster_share(
            _Agi(), "192.168.20.15", env, remote_share
        )

    assert ssh_calls == []
    assert not (tmp_path / "scheduler-share").exists()


@pytest.mark.parametrize(
    "local_share",
    ["/", "/etc", "/mnt", "/home/agi", "/Users/agi", "/var/root"],
)
@pytest.mark.asyncio
async def test_prepare_remote_cluster_share_rejects_unsafe_scheduler_source_before_ssh(
    tmp_path,
    local_share,
):
    env = SimpleNamespace(
        AGI_CLUSTER_SHARE=local_share,
        envars={},
        home_abs=tmp_path,
        user="agi",
        verbose=0,
    )
    ssh_calls: list[str] = []
    agi_cls = SimpleNamespace(
        _scheduler_ip="127.0.0.1",
        exec_ssh=lambda ip, command: ssh_calls.append(command),
    )

    with pytest.raises(ValueError, match="AGI_CLUSTER_SHARE"):
        await deployment_remote_support._prepare_remote_cluster_share(
            agi_cls,
            "192.0.2.10",
            env,
            "clustershare/agi",
        )

    assert ssh_calls == []


@pytest.mark.parametrize(
    "remote_share",
    [
        "clustershare",
        "~/clustershare",
        "/mnt/agilab",
        "/var/lib/agilab",
        "/tmp/agilab",
    ],
)
def test_validate_remote_share_target_accepts_dedicated_roots(remote_share):
    assert deployment_remote_support._validate_remote_share_target(remote_share) == remote_share


@pytest.mark.asyncio
async def test_prepare_remote_cluster_share_preserves_absolute_worker_mount_target(
    tmp_path,
):
    scheduler_share = tmp_path / "scheduler-share"
    env = SimpleNamespace(
        AGI_CLUSTER_SHARE=str(scheduler_share),
        envars={},
        home_abs=tmp_path,
        user="agi",
        verbose=0,
    )
    ssh_calls: list[str] = []

    class _Agi:
        _scheduler_ip = "192.168.20.111"

        async def exec_ssh(self, _ip, cmd):
            ssh_calls.append(cmd)
            return "ok"

    await deployment_remote_support._prepare_remote_cluster_share(
        _Agi(), "192.168.20.15", env, "/mnt/agilab"
    )

    assert scheduler_share.is_dir()
    remote_env_cmd = next(cmd for cmd in ssh_calls if "AGI_CLUSTER_SHARE=" in cmd)
    mount_cmd = next(cmd for cmd in ssh_calls if "SCHEDULER_CLUSTER_SHARE" in cmd)
    assert "/mnt/agilab" in remote_env_cmd
    assert "REMOTE_CLUSTER_SHARE=/mnt/agilab" in mount_cmd
    assert scheduler_share.as_posix() in mount_cmd
    assert ssh_calls.index(mount_cmd) < ssh_calls.index(remote_env_cmd)


@pytest.mark.asyncio
async def test_remote_probe_connection_errors_are_not_downgraded():
    class _Agi:
        async def exec_ssh(self, *_args):
            raise ConnectionError("network down")

    with pytest.raises(ConnectionError, match="network down"):
        await deployment_remote_support._legacy_intel_macos_dependency_specs(_Agi(), "10.0.0.2")
    with pytest.raises(ConnectionError, match="network down"):
        await deployment_remote_support._remote_project_has_pip(
            _Agi(),
            "10.0.0.2",
            uv="uv",
            wenv_rel=Path("worker_env"),
            pyvers="3.13",
        )


async def _call_deploy_remote_worker(
    agi_cls,
    ip: str,
    env,
    wenv_rel: Path,
    option: str,
    *,
    set_env_var_fn,
    log,
) -> None:
    # wenv_rel/option are accepted for call-site compatibility but the
    # production signature dropped them: deploy_remote_worker reads
    # env.wenv_rel and never used option.
    del wenv_rel, option
    await deployment_remote_support.deploy_remote_worker(
        agi_cls,
        ip,
        env,
        worker_site_packages_dir_fn=uv_source_support.worker_site_packages_dir,
        staged_uv_sources_pth_content_fn=uv_source_support.staged_uv_sources_pth_content,
        set_env_var_fn=set_env_var_fn,
        log=log,
    )


@pytest.mark.asyncio
async def test_deploy_remote_worker_non_source_flow(monkeypatch, tmp_path):
    dist_abs = tmp_path / "dist"
    dist_abs.mkdir(parents=True, exist_ok=True)
    (dist_abs / "demo_worker-0.0.1.egg").write_text("x", encoding="utf-8")

    env = SimpleNamespace(
        wenv_abs=tmp_path / "worker_env",
        wenv_rel=Path("worker_env"),
        dist_rel=Path("worker_env/dist"),
        dist_abs=dist_abs,
        pyvers_worker="3.13",
        pyvers_worker_uv_spec="3.14.6+gil",
        envars={},
        uv_worker="uv --quiet",
        is_source_env=False,
        app="demo_app",
        target_worker="demo_worker",
        post_install_rel="demo.post_install",
        verbose=0,
    )
    ssh_calls = []
    send_calls = []

    async def _fake_exec_ssh(_ip, cmd):
        ssh_calls.append(cmd)
        return "ok"

    async def _fake_send(_env, ip, files, remote_path, user=None, password=None):
        del user, password
        send_calls.append((ip, [Path(f).name for f in files], str(remote_path)))

    async def _fake_send_file(
        _env, ip, local_path, remote_path, user=None, password=None
    ):
        del user, password
        send_calls.append((ip, [Path(local_path).name], str(remote_path.parent)))

    agi_cls = SimpleNamespace(
        # Cython bit set: remote build_ext emission is gated on _mode & 2.
        _mode=2,
        CYTHON_MODE=2,
        DASK_MODE=4,
        _rapids_enabled=False,
        _workers_data_path=None,
        exec_ssh=_fake_exec_ssh,
        send_files=_fake_send,
        send_file=_fake_send_file,
    )

    await _call_deploy_remote_worker(
        agi_cls,
        "10.0.0.2",
        env,
        Path("worker_env"),
        " --extra pandas-worker",
        set_env_var_fn=lambda *_a, **_k: None,
        log=deployment_remote_support.logger,
    )

    assert any("demo_worker-0.0.1.egg" in names for _, names, _ in send_calls)
    assert any("python -c 'import pip'" in cmd for cmd in ssh_calls)
    assert any("uv --quiet run -p 3.14.6+gil" in cmd for cmd in ssh_calls)
    assert not any("'uv --quiet'" in cmd for cmd in ssh_calls)
    assert not any("ensurepip" in cmd for cmd in ssh_calls)
    assert not any("dask[distributed]" in cmd for cmd in ssh_calls)
    assert not any("numba==0.62.1" in cmd for cmd in ssh_calls)
    assert any("--upgrade agi-env agi-node" in cmd for cmd in ssh_calls)
    assert any("python -m demo.post_install" in cmd for cmd in ssh_calls)
    assert any(
        "python cli.py threaded"
        in cmd.replace('"', "").replace("'", "")
        for cmd in ssh_calls
    )
    assert any(
        "agi_node.agi_dispatcher.build" in cmd
        and "--with setuptools" in cmd
        and f"--with {CYTHON_BUILD_REQUIREMENT}" in cmd
        for cmd in ssh_calls
    )


@pytest.mark.asyncio
async def test_deploy_remote_worker_fails_when_threaded_smoke_probe_fails(tmp_path):
    dist_abs = tmp_path / "dist"
    dist_abs.mkdir(parents=True, exist_ok=True)
    (dist_abs / "demo_worker-0.0.1.egg").write_text("x", encoding="utf-8")

    env = SimpleNamespace(
        wenv_abs=tmp_path / "worker_env",
        wenv_rel=Path("worker_env"),
        dist_rel=Path("worker_env/dist"),
        dist_abs=dist_abs,
        pyvers_worker="3.13",
        envars={},
        uv_worker="uv --quiet",
        is_source_env=False,
        app="demo_app",
        target_worker="demo_worker",
        post_install_rel="demo.post_install",
        verbose=0,
    )
    ssh_calls = []

    async def _fake_exec_ssh(_ip, cmd):
        ssh_calls.append(cmd)
        if "threaded" in cmd:
            raise RuntimeError("worker is down")
        return "ok"

    async def _fake_send(_env, ip, files, remote_path, user=None, password=None):
        del _env, ip, files, remote_path, user, password

    async def _fake_send_file(
        _env, ip, local_path, remote_path, user=None, password=None
    ):
        del _env, ip, local_path, remote_path, user, password

    agi_cls = SimpleNamespace(
        _mode=0,
        DASK_MODE=4,
        _rapids_enabled=False,
        _workers_data_path=None,
        exec_ssh=_fake_exec_ssh,
        send_files=_fake_send,
        send_file=_fake_send_file,
    )

    with pytest.raises(RuntimeError, match="worker is down"):
        await _call_deploy_remote_worker(
            agi_cls,
            "10.0.0.2",
            env,
            Path("worker_env"),
            " --extra pandas-worker",
            set_env_var_fn=lambda *_a, **_k: None,
            log=deployment_remote_support.logger,
        )

    assert any("threaded" in cmd for cmd in ssh_calls)


@pytest.mark.asyncio
async def test_deploy_remote_worker_verbose_build_keeps_overlay_without_quiet_flag(
    monkeypatch,
    tmp_path,
):
    dist_abs = tmp_path / "dist"
    dist_abs.mkdir(parents=True, exist_ok=True)
    (dist_abs / "demo_worker-0.0.1.egg").write_text("x", encoding="utf-8")

    env = SimpleNamespace(
        wenv_abs=tmp_path / "worker_env",
        wenv_rel=Path("worker_env"),
        dist_rel=Path("worker_env/dist"),
        dist_abs=dist_abs,
        pyvers_worker="3.13",
        envars={},
        uv_worker="uv",
        is_source_env=False,
        app="demo_app",
        target_worker="demo_worker",
        post_install_rel="demo.post_install",
        verbose=2,
    )
    ssh_calls: list[str] = []

    async def _fake_exec_ssh(_ip, cmd):
        ssh_calls.append(cmd)
        return "ok"

    async def _fake_send(_env, _ip, _files, _remote_path, user=None, password=None):
        del user, password

    async def _fake_send_file(
        _env, _ip, _local_path, _remote_path, user=None, password=None
    ):
        del user, password

    agi_cls = SimpleNamespace(
        # Cython bit set: remote build_ext emission is gated on _mode & 2.
        _mode=2,
        CYTHON_MODE=2,
        DASK_MODE=4,
        _rapids_enabled=False,
        _workers_data_path=None,
        exec_ssh=_fake_exec_ssh,
        send_files=_fake_send,
        send_file=_fake_send_file,
    )

    await _call_deploy_remote_worker(
        agi_cls,
        "10.0.0.2",
        env,
        Path("worker_env"),
        " --extra pandas-worker",
        set_env_var_fn=lambda *_a, **_k: None,
        log=deployment_remote_support.logger,
    )

    build_commands = [
        cmd
        for cmd in ssh_calls
        if "agi_node.agi_dispatcher.build" in cmd and "build_ext" in cmd
    ]
    assert len(build_commands) == 1
    build_cmd = build_commands[0]
    assert "--with setuptools" in build_cmd
    assert f"--with {CYTHON_BUILD_REQUIREMENT}" in build_cmd
    assert " -q " not in f" {build_cmd} "


@pytest.mark.asyncio
async def test_remote_project_has_pip_reports_missing_when_probe_fails():
    calls: list[str] = []

    async def _fake_exec_ssh(_ip, cmd):
        calls.append(cmd)
        raise RuntimeError("pip is missing")

    agi_cls = SimpleNamespace(exec_ssh=_fake_exec_ssh)

    assert (
        await deployment_remote_support._remote_project_has_pip(
            agi_cls,
            "10.0.0.2",
            uv="uv",
            wenv_rel=Path("worker_env"),
            pyvers="3.13",
        )
        is False
    )
    assert calls == ["uv --project worker_env run -p 3.13 python -c 'import pip'"]


@pytest.mark.asyncio
async def test_remote_project_has_pip_propagates_unexpected_probe_bug():
    async def _fake_exec_ssh(_ip, _cmd):
        raise ValueError("broken probe wiring")

    agi_cls = SimpleNamespace(exec_ssh=_fake_exec_ssh)

    with pytest.raises(ValueError, match="broken probe wiring"):
        await deployment_remote_support._remote_project_has_pip(
            agi_cls,
            "10.0.0.2",
            uv="uv",
            wenv_rel=Path("worker_env"),
            pyvers="3.13",
        )


@pytest.mark.asyncio
async def test_deploy_remote_worker_installs_dask_runtime_when_dask_mode_enabled(
    tmp_path,
):
    dist_abs = tmp_path / "dist"
    dist_abs.mkdir(parents=True, exist_ok=True)
    (dist_abs / "demo_worker-0.0.1.egg").write_text("x", encoding="utf-8")

    env = SimpleNamespace(
        wenv_abs=tmp_path / "worker_env",
        wenv_rel=Path("worker_env"),
        dist_rel=Path("worker_env/dist"),
        dist_abs=dist_abs,
        pyvers_worker="3.13",
        envars={},
        uv_worker="uv",
        is_source_env=False,
        app="demo_app",
        target_worker="demo_worker",
        post_install_rel="demo.post_install",
        verbose=0,
    )
    ssh_calls = []

    async def _fake_exec_ssh(_ip, cmd):
        ssh_calls.append(cmd)
        return "ok"

    async def _fake_send(_env, _ip, _files, _remote_path, user=None, password=None):
        del user, password

    async def _fake_send_file(
        _env, _ip, _local_path, _remote_path, user=None, password=None
    ):
        del user, password

    agi_cls = SimpleNamespace(
        _mode=4,
        DASK_MODE=4,
        _rapids_enabled=False,
        _workers_data_path=None,
        exec_ssh=_fake_exec_ssh,
        send_files=_fake_send,
        send_file=_fake_send_file,
    )

    await _call_deploy_remote_worker(
        agi_cls,
        "10.0.0.2",
        env,
        Path("worker_env"),
        "",
        set_env_var_fn=lambda *_a, **_k: None,
        log=deployment_remote_support.logger,
    )

    core_index = next(
        i for i, cmd in enumerate(ssh_calls) if "--upgrade agi-env agi-node" in cmd
    )
    dask_index = next(
        i for i, cmd in enumerate(ssh_calls) if "dask[distributed]" in cmd
    )

    assert (
        "uv --project worker_env add -p 3.13 'dask[distributed]'"
        in ssh_calls[dask_index]
    )
    assert core_index < dask_index


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="sshfs/POSIX shell mount commands are not portable to Windows.",
)
@pytest.mark.asyncio
async def test_deploy_remote_worker_mounts_scheduler_cluster_share_with_sshfs(tmp_path):
    dist_abs = tmp_path / "dist"
    dist_abs.mkdir(parents=True, exist_ok=True)
    (dist_abs / "demo_worker-0.0.1.egg").write_text("x", encoding="utf-8")

    scheduler_share = tmp_path / "scheduler-share"
    remote_share = "/home/agilab/clustershare/agi"
    env = SimpleNamespace(
        wenv_abs=tmp_path / "worker_env",
        wenv_rel=Path("worker_env"),
        dist_rel=Path("worker_env/dist"),
        dist_abs=dist_abs,
        pyvers_worker="3.13",
        envars={"AGI_CLUSTER_SHARE": str(scheduler_share)},
        uv_worker="uv",
        is_source_env=False,
        app="demo_app",
        target_worker="demo_worker",
        post_install_rel="demo.post_install",
        verbose=1,
        user="agi",
        home_abs=Path("/home/agilab"),
    )
    ssh_calls: list[str] = []

    async def _fake_exec_ssh(_ip, cmd):
        ssh_calls.append(cmd)
        return "ok"

    async def _fake_send(_env, _ip, _files, _remote_path, user=None, password=None):
        del user, password

    async def _fake_send_file(
        _env, _ip, _local_path, _remote_path, user=None, password=None
    ):
        del user, password

    agi_cls = SimpleNamespace(
        _mode=0,
        DASK_MODE=4,
        _rapids_enabled=False,
        _workers_data_path=remote_share,
        _scheduler_ip="192.168.20.111",
        exec_ssh=_fake_exec_ssh,
        send_files=_fake_send,
        send_file=_fake_send_file,
    )

    await _call_deploy_remote_worker(
        agi_cls,
        "192.168.20.15",
        env,
        Path("worker_env"),
        " --extra pandas-worker",
        set_env_var_fn=lambda *_a, **_k: None,
        log=deployment_remote_support.logger,
    )

    assert scheduler_share.is_dir()
    remote_env_cmd = next(cmd for cmd in ssh_calls if "AGI_CLUSTER_SHARE=" in cmd)
    assert "clustershare/agi" in remote_env_cmd
    assert "/home/agilab/clustershare/agi" not in remote_env_cmd
    assert not any(
        "/home/agilab/clustershare/agi" in cmd and "REMOTE_CLUSTER_SHARE" in cmd
        for cmd in ssh_calls
    )
    assert any("command -v sshfs" in cmd for cmd in ssh_calls)
    mount_cmd = next(cmd for cmd in ssh_calls if "SCHEDULER_CLUSTER_SHARE" in cmd)
    assert mount_cmd.startswith(
        'export PATH="$HOME/.local/bin:$HOME/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"; '
    )
    assert 'ssh -p "$SCHEDULER_SSH_PORT" -o BatchMode=yes -o ConnectTimeout=5 "$SCHEDULER_SSH_TARGET" true' in mount_cmd
    assert "Scheduler SSH is not reachable from the worker" in mount_cmd
    assert any(
        'sshfs -p "$SCHEDULER_SSH_PORT" "$SCHEDULER_CLUSTER_SHARE" "$REMOTE_CLUSTER_SHARE"' in cmd
        for cmd in ssh_calls
    )
    mount_cmd = next(
        cmd for cmd in ssh_calls if 'sshfs -p "$SCHEDULER_SSH_PORT"' in cmd
    )
    assert (
        'export PATH="$HOME/.local/bin:$HOME/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"; set -e;'
        in mount_cmd
    )
    assert "-o reconnect" in mount_cmd
    assert "-o ServerAliveInterval=15" in mount_cmd
    assert "-o ServerAliveCountMax=3" in mount_cmd
    assert "-o BatchMode=yes" in mount_cmd
    assert "-o StrictHostKeyChecking=yes" in mount_cmd
    assert "-o noexec" in mount_cmd
    assert "MOUNT_LINE=$(mount | grep -F" in mount_cmd
    assert "stale, unexpected, or unwritable SSHFS mount" in mount_cmd
    assert "fusermount3 -u" in mount_cmd
    assert "sudo apt-get install -y sshfs" in mount_cmd
    assert any(
        "agi@192.168.20.111:" in cmd and str(scheduler_share) in cmd
        for cmd in ssh_calls
    )


@pytest.mark.asyncio
async def test_prepare_remote_cluster_share_honors_custom_scheduler_ssh_port(tmp_path):
    scheduler_share = tmp_path / "scheduler-share"
    env = SimpleNamespace(
        AGI_CLUSTER_SHARE=str(scheduler_share),
        envars={"AGILAB_SCHEDULER_SSH_PORT": "2222"},
        home_abs=tmp_path,
        user="agi",
        verbose=0,
    )
    ssh_calls: list[str] = []

    class _Agi:
        _scheduler_ip = "192.168.20.111"

        async def exec_ssh(self, _ip, cmd):
            ssh_calls.append(cmd)
            return "ok"

    await deployment_remote_support._prepare_remote_cluster_share(
        _Agi(), "192.168.20.15", env, "clustershare"
    )

    mount_cmd = next(cmd for cmd in ssh_calls if "SCHEDULER_CLUSTER_SHARE" in cmd)
    assert "SCHEDULER_SSH_PORT=2222" in mount_cmd
    assert 'ssh -p "$SCHEDULER_SSH_PORT"' in mount_cmd
    assert 'sshfs -p "$SCHEDULER_SSH_PORT"' in mount_cmd


@pytest.mark.asyncio
async def test_prepare_remote_cluster_share_mounts_cluster_share_root_for_workflow_session(tmp_path):
    scheduler_share = tmp_path / "clustershare" / "agi"
    workflow_share = "clustershare/agi/workflows/session-123"
    env = SimpleNamespace(
        AGI_CLUSTER_SHARE=str(scheduler_share),
        envars={},
        home_abs=tmp_path,
        user="agi",
        verbose=0,
    )
    ssh_calls: list[str] = []

    class _Agi:
        _scheduler_ip = "192.168.20.111"

        async def exec_ssh(self, _ip, cmd):
            ssh_calls.append(cmd)
            return "ok"

    await deployment_remote_support._prepare_remote_cluster_share(
        _Agi(), "192.168.20.15", env, workflow_share
    )

    mount_cmd = next(cmd for cmd in ssh_calls if "SCHEDULER_CLUSTER_SHARE" in cmd)
    scheduler_session = scheduler_share / "workflows" / "session-123"
    remote_env_cmd = next(cmd for cmd in ssh_calls if "AGI_CLUSTER_SHARE=" in cmd)
    assert scheduler_share.is_dir()
    assert not scheduler_session.exists()
    assert "clustershare/agi" in remote_env_cmd
    assert "AGILAB_WORKFLOW_DATA_ROOT=" in remote_env_cmd
    assert "workflows/session-123" in remote_env_cmd
    assert f"agi@192.168.20.111:{scheduler_share.as_posix()}" in mount_cmd
    assert '"$HOME"/clustershare/agi' in mount_cmd
    assert "workflows/session-123" not in mount_cmd


@pytest.mark.asyncio
async def test_prepare_remote_cluster_share_rejects_reverse_sshfs_loop_on_share_root(
    tmp_path, monkeypatch
):
    scheduler_share = tmp_path / "clustershare" / "agi"
    workflow_share = "clustershare/agi/workflows/session-123"
    scheduler_root = scheduler_share.resolve(strict=False)
    env = SimpleNamespace(
        AGI_CLUSTER_SHARE=str(scheduler_share),
        envars={},
        home_abs=tmp_path,
        user="agi",
        verbose=0,
    )
    ssh_calls: list[str] = []

    class _Agi:
        _scheduler_ip = "192.168.20.141"

        async def exec_ssh(self, _ip, cmd):
            ssh_calls.append(cmd)
            return "ok"

    def _mount_record(path):
        if Path(path) != scheduler_root:
            return None
        return {
            "TARGET": scheduler_root.as_posix(),
            "SOURCE": "agi@192.168.20.15:/home/agi/clustershare/agi",
            "FSTYPE": "fuse.sshfs",
        }

    monkeypatch.setattr(
        deployment_remote_support,
        "_local_mount_record_for_path",
        _mount_record,
    )

    with pytest.raises(RuntimeError, match="SSHFS loop"):
        await deployment_remote_support._prepare_remote_cluster_share(
            _Agi(), "192.168.20.15", env, workflow_share
        )

    assert ssh_calls == []
    assert not scheduler_share.exists()


@pytest.mark.asyncio
async def test_prepare_remote_cluster_share_rejects_reverse_sshfs_loop(tmp_path, monkeypatch):
    scheduler_share = tmp_path / "clustershare" / "agi"
    env = SimpleNamespace(
        AGI_CLUSTER_SHARE=str(scheduler_share),
        envars={},
        home_abs=tmp_path,
        user="agi",
        verbose=0,
    )
    ssh_calls: list[str] = []

    class _Agi:
        _scheduler_ip = "192.168.20.141"

        async def exec_ssh(self, _ip, cmd):
            ssh_calls.append(cmd)
            return "ok"

    monkeypatch.setattr(
        deployment_remote_support,
        "_local_mount_record_for_path",
        lambda _path: {
            "TARGET": str(tmp_path / "clustershare"),
            "SOURCE": "agi@192.168.20.15:/home/agi/clustershare",
            "FSTYPE": "fuse.sshfs",
        },
    )

    with pytest.raises(RuntimeError, match="SSHFS loop"):
        await deployment_remote_support._prepare_remote_cluster_share(
            _Agi(), "192.168.20.15", env, "clustershare/agi"
        )

    assert ssh_calls == []
    assert not scheduler_share.exists()


@pytest.mark.asyncio
async def test_prepare_remote_cluster_share_allows_unrelated_sshfs_mount(tmp_path, monkeypatch):
    scheduler_share = tmp_path / "clustershare" / "agi"
    env = SimpleNamespace(
        AGI_CLUSTER_SHARE=str(scheduler_share),
        envars={},
        home_abs=tmp_path,
        user="agi",
        verbose=0,
    )
    ssh_calls: list[str] = []

    class _Agi:
        _scheduler_ip = "192.168.20.141"

        async def exec_ssh(self, _ip, cmd):
            ssh_calls.append(cmd)
            return "ok"

    monkeypatch.setattr(
        deployment_remote_support,
        "_local_mount_record_for_path",
        lambda _path: {
            "TARGET": str(tmp_path / "clustershare"),
            "SOURCE": "agi@192.168.20.99:/home/agi/clustershare",
            "FSTYPE": "fuse.sshfs",
        },
    )

    await deployment_remote_support._prepare_remote_cluster_share(
        _Agi(), "192.168.20.15", env, "clustershare/agi"
    )

    assert scheduler_share.is_dir()
    assert any("SCHEDULER_CLUSTER_SHARE" in cmd for cmd in ssh_calls)


@pytest.mark.asyncio
async def test_prepare_remote_cluster_share_accepts_premounted_remote_share_without_scheduler(tmp_path):
    env = SimpleNamespace(
        AGI_CLUSTER_SHARE=str(tmp_path / "scheduler-share"),
        envars={"AGILAB_REMOTE_CLUSTER_SHARE_PREMOUNTED": "1"},
        home_abs=tmp_path,
        user="agi",
        verbose=0,
    )
    ssh_calls: list[str] = []

    class _AgiNoScheduler:
        _scheduler_ip = ""

        async def exec_ssh(self, _ip, cmd):
            ssh_calls.append(cmd)
            return "ok"

    await deployment_remote_support._prepare_remote_cluster_share(
        _AgiNoScheduler(), "192.168.20.15", env, "clustershare"
    )

    assert len(ssh_calls) == 2
    assert "Pre-mounted AGILAB cluster share" in ssh_calls[0]
    assert "AGI_CLUSTER_SHARE=" in ssh_calls[1]
    assert "clustershare" in ssh_calls[1]
    assert "SCHEDULER_SSH_TARGET" not in "\n".join(ssh_calls)
    assert "sshfs" not in "\n".join(ssh_calls)


@pytest.mark.asyncio
async def test_prepare_remote_cluster_share_treats_nfs_and_ntfs_backends_as_premounted(
    tmp_path,
    monkeypatch,
):
    for backend in ("nfs", "ntfs"):
        env = SimpleNamespace(
            AGI_CLUSTER_SHARE=str(tmp_path / f"scheduler-share-{backend}"),
            envars={"AGILAB_CLUSTER_SHARE_BACKEND": backend},
            home_abs=tmp_path,
            user="agi",
            verbose=0,
        )
        ssh_calls: list[str] = []

        class _AgiNoScheduler:
            _scheduler_ip = ""

            async def exec_ssh(self, _ip, cmd):
                ssh_calls.append(cmd)
                return "ok"

        monkeypatch.setattr(
            deployment_remote_support,
            "_reverse_sshfs_mount_problem",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("no reverse guard")),
        )

        await deployment_remote_support._prepare_remote_cluster_share(
            _AgiNoScheduler(), "192.168.20.15", env, "clustershare"
        )

        assert len(ssh_calls) == 2
        assert "Pre-mounted AGILAB cluster share" in ssh_calls[0]
        assert "AGI_CLUSTER_ENABLED=" in ssh_calls[1]
        assert "SCHEDULER_SSH_TARGET" not in "\n".join(ssh_calls)
        assert "sshfs" not in "\n".join(ssh_calls).lower()


def test_cluster_share_backend_rejects_unknown_backend():
    env = SimpleNamespace(envars={"AGILAB_CLUSTER_SHARE_BACKEND": "smb"})

    with pytest.raises(ValueError, match="Unsupported AGILAB cluster-share backend"):
        deployment_remote_support._remote_cluster_share_premounted(env)


@pytest.mark.asyncio
async def test_deploy_remote_worker_prepins_dependencies_for_legacy_intel_macos(
    tmp_path,
):
    dist_abs = tmp_path / "dist"
    dist_abs.mkdir(parents=True, exist_ok=True)
    (dist_abs / "demo_worker-0.0.1.egg").write_text("x", encoding="utf-8")

    env = SimpleNamespace(
        wenv_abs=tmp_path / "worker_env",
        wenv_rel=Path("worker_env"),
        dist_rel=Path("worker_env/dist"),
        dist_abs=dist_abs,
        pyvers_worker="3.12",
        envars={},
        uv_worker="uv",
        is_source_env=False,
        app="demo_app",
        target_worker="demo_worker",
        post_install_rel="demo.post_install",
        verbose=0,
    )
    ssh_calls = []
    send_calls = []

    async def _fake_exec_ssh(_ip, cmd):
        ssh_calls.append(cmd)
        if cmd == deployment_remote_support._remote_platform_probe_command():
            return "Darwin\nx86_64\n10.15.8"
        return "ok"

    async def _fake_send(_env, ip, files, remote_path, user=None, password=None):
        del user, password
        send_calls.append((ip, [Path(f).name for f in files], str(remote_path)))

    async def _fake_send_file(
        _env, ip, local_path, remote_path, user=None, password=None
    ):
        del user, password
        send_calls.append((ip, [Path(local_path).name], str(remote_path.parent)))

    agi_cls = SimpleNamespace(
        _rapids_enabled=False,
        _workers_data_path=None,
        exec_ssh=_fake_exec_ssh,
        send_files=_fake_send,
        send_file=_fake_send_file,
    )

    await _call_deploy_remote_worker(
        agi_cls,
        "10.0.0.2",
        env,
        Path("worker_env"),
        "",
        set_env_var_fn=lambda *_a, **_k: None,
        log=deployment_remote_support.logger,
    )

    pin_index = next(i for i, cmd in enumerate(ssh_calls) if "numba==0.62.1" in cmd)
    core_index = next(
        i for i, cmd in enumerate(ssh_calls) if "--upgrade agi-env agi-node" in cmd
    )

    assert "pyarrow==17.0.0" in ssh_calls[pin_index]
    assert "add -p 3.12" in ssh_calls[pin_index]
    assert pin_index < core_index


@pytest.mark.asyncio
async def test_deploy_remote_worker_source_env_with_rapids(monkeypatch, tmp_path):
    dist_abs = tmp_path / "dist"
    dist_abs.mkdir(parents=True, exist_ok=True)
    (dist_abs / "demo_worker-0.0.1.egg").write_text("egg", encoding="utf-8")
    scheduler_share = tmp_path / "share"
    agi_env = tmp_path / "agi_env"
    agi_node = tmp_path / "agi_node"
    for p, name in ((agi_env, "agi_env"), (agi_node, "agi_node")):
        (p / "dist").mkdir(parents=True, exist_ok=True)
        (p / "dist" / f"{name}-0.0.1-py3-none-any.whl").write_text(
            "whl", encoding="utf-8"
        )

    env = SimpleNamespace(
        wenv_abs=tmp_path / "wenv",
        wenv_rel=Path("wenv"),
        dist_rel=Path("wenv/dist"),
        dist_abs=dist_abs,
        pyvers_worker="3.13",
        envars={},
        AGI_CLUSTER_SHARE=str(scheduler_share),
        uv_worker="uv",
        is_source_env=True,
        app="demo_app",
        target_worker="demo_worker",
        agi_env=agi_env,
        agi_node=agi_node,
        post_install_rel="demo.post_install",
        verbose=2,
    )
    sent = []
    ssh = []
    env_vars = []

    async def _fake_send(_env, ip, files, remote_path, user=None, password=None):
        del user, password
        payload = []
        for file in files:
            p = Path(file)
            entry = {"name": p.name}
            if p.suffix == ".pth":
                entry["content"] = p.read_text(encoding="utf-8")
            payload.append(entry)
        sent.append((ip, payload, str(remote_path)))

    async def _fake_send_file(
        _env, ip, local_path, remote_path, user=None, password=None
    ):
        del user, password
        p = Path(local_path)
        payload = [{"name": p.name, "content": p.read_text(encoding="utf-8")}]
        sent.append((ip, payload, str(remote_path.parent)))

    async def _fake_exec(ip, cmd):
        ssh.append((ip, cmd))
        if "rapids-probe" in cmd:
            return _rapids_probe_output(True)
        return "ok"

    agi_cls = SimpleNamespace(
        _rapids_enabled=True,
        _workers_data_path="/mnt/agilab",
        _scheduler_ip="10.0.0.1",
        exec_ssh=_fake_exec,
        send_files=_fake_send,
        send_file=_fake_send_file,
    )

    await _call_deploy_remote_worker(
        agi_cls,
        "10.0.0.2",
        env,
        Path("wenv"),
        " --extra pandas-worker",
        set_env_var_fn=lambda *args: env_vars.append(args),
        log=deployment_remote_support.logger,
    )

    assert any(".agilab/.env" in cmd for _, cmd in ssh)
    assert any("rapids-probe" in cmd for _, cmd in ssh)
    assert not any("nvidia-smi" == cmd.strip() for _, cmd in ssh)
    assert ("10.0.0.2", "hw_rapids_capable") in env_vars
    assert any(
        any(item["name"] == "agi_env-0.0.1-py3-none-any.whl" for item in payload)
        for _, payload, _ in sent
    )
    assert any(
        any(item["name"] == "agi_node-0.0.1-py3-none-any.whl" for item in payload)
        for _, payload, _ in sent
    )
    assert any("python -m demo.post_install" in cmd for _, cmd in ssh)
    mount_cmd = next(cmd for _, cmd in ssh if "SCHEDULER_CLUSTER_SHARE" in cmd)
    assert scheduler_share.is_dir()
    assert scheduler_share.as_posix() in mount_cmd
    assert "REMOTE_CLUSTER_SHARE=/mnt/agilab" in mount_cmd


@pytest.mark.asyncio
async def test_deploy_remote_worker_source_env_prefers_latest_artifacts(tmp_path):
    dist_abs = tmp_path / "dist"
    dist_abs.mkdir(parents=True, exist_ok=True)
    old_egg = dist_abs / "demo_worker-0.0.1.egg"
    new_egg = dist_abs / "demo_worker-0.0.2.egg"
    old_egg.write_text("old-egg", encoding="utf-8")
    new_egg.write_text("new-egg", encoding="utf-8")
    os.utime(old_egg, (1, 1))
    os.utime(new_egg, (2, 2))

    agi_env = tmp_path / "agi_env"
    agi_node = tmp_path / "agi_node"
    for root, older_name, newer_name in (
        (
            agi_env,
            "agi_env-0.0.1-py3-none-any.whl",
            "agi_env-0.0.2-py3-none-any.whl",
        ),
        (
            agi_node,
            "agi_node-0.0.1-py3-none-any.whl",
            "agi_node-0.0.2-py3-none-any.whl",
        ),
    ):
        dist_dir = root / "dist"
        dist_dir.mkdir(parents=True, exist_ok=True)
        older = dist_dir / older_name
        newer = dist_dir / newer_name
        older.write_text("old", encoding="utf-8")
        newer.write_text("new", encoding="utf-8")
        os.utime(older, (1, 1))
        os.utime(newer, (2, 2))

    env = SimpleNamespace(
        wenv_abs=tmp_path / "wenv",
        wenv_rel=Path("wenv"),
        dist_rel=Path("wenv/dist"),
        dist_abs=dist_abs,
        pyvers_worker="3.13",
        envars={},
        uv_worker="uv",
        is_source_env=True,
        app="demo_app",
        target_worker="demo_worker",
        agi_env=agi_env,
        agi_node=agi_node,
        post_install_rel="demo.post_install",
        verbose=0,
    )
    sent: list[tuple[str, list[str], str]] = []

    async def _fake_send(_env, ip, files, remote_path, user=None, password=None):
        del user, password
        sent.append((ip, [Path(f).name for f in files], str(remote_path)))

    async def _fake_send_file(
        _env, ip, local_path, remote_path, user=None, password=None
    ):
        del _env, ip, user, password
        sent.append(("10.0.0.2", [Path(local_path).name], str(remote_path.parent)))

    async def _fake_exec(_ip, _cmd):
        return "ok"

    agi_cls = SimpleNamespace(
        _rapids_enabled=False,
        _workers_data_path=None,
        exec_ssh=_fake_exec,
        send_files=_fake_send,
        send_file=_fake_send_file,
    )

    await _call_deploy_remote_worker(
        agi_cls,
        "10.0.0.2",
        env,
        Path("wenv"),
        "",
        set_env_var_fn=lambda *_a, **_k: None,
        log=deployment_remote_support.logger,
    )

    assert any(names == ["demo_worker-0.0.2.egg"] for _, names, _ in sent)
    assert any("agi_env-0.0.2-py3-none-any.whl" in names for _, names, _ in sent)
    assert any("agi_node-0.0.2-py3-none-any.whl" in names for _, names, _ in sent)


@pytest.mark.asyncio
async def test_deploy_remote_worker_rapids_probe_propagates_unexpected_value_error(
    tmp_path,
):
    dist_abs = tmp_path / "dist"
    dist_abs.mkdir(parents=True, exist_ok=True)
    (dist_abs / "demo_worker-0.0.1.egg").write_text("egg", encoding="utf-8")
    agi_env = tmp_path / "agi_env"
    agi_node = tmp_path / "agi_node"
    for p, name in ((agi_env, "agi_env"), (agi_node, "agi_node")):
        (p / "dist").mkdir(parents=True, exist_ok=True)
        (p / "dist" / f"{name}-0.0.1-py3-none-any.whl").write_text(
            "whl", encoding="utf-8"
        )

    env = SimpleNamespace(
        wenv_abs=tmp_path / "wenv",
        wenv_rel=Path("wenv"),
        dist_rel=Path("wenv/dist"),
        dist_abs=dist_abs,
        pyvers_worker="3.13",
        envars={},
        uv_worker="uv",
        is_source_env=True,
        app="demo_app",
        target_worker="demo_worker",
        agi_env=agi_env,
        agi_node=agi_node,
        post_install_rel="demo.post_install",
        verbose=0,
    )

    async def _fake_exec(ip, cmd):
        if "rapids-probe" in cmd:
            raise ValueError("unexpected rapids probe bug")
        return "ok"

    async def _fake_send(_env, ip, files, remote_path, user=None, password=None):
        del _env, ip, files, remote_path, user, password

    async def _fake_send_file(
        _env, ip, local_path, remote_path, user=None, password=None
    ):
        del _env, ip, local_path, remote_path, user, password

    agi_cls = SimpleNamespace(
        _rapids_enabled=True,
        _workers_data_path=None,
        exec_ssh=_fake_exec,
        send_files=_fake_send,
        send_file=_fake_send_file,
    )

    with pytest.raises(ValueError, match="unexpected rapids probe bug"):
        await _call_deploy_remote_worker(
            agi_cls,
            "10.0.0.2",
            env,
            Path("wenv"),
            " --extra pandas-worker",
            set_env_var_fn=lambda *_a, **_k: None,
            log=deployment_remote_support.logger,
        )


@pytest.mark.asyncio
async def test_deploy_remote_worker_source_env_missing_egg_logs_and_raises(tmp_path):
    dist_abs = tmp_path / "dist"
    dist_abs.mkdir(parents=True, exist_ok=True)
    agi_env = tmp_path / "agi_env"
    agi_node = tmp_path / "agi_node"
    for p, name in ((agi_env, "agi_env"), (agi_node, "agi_node")):
        (p / "dist").mkdir(parents=True, exist_ok=True)
        (p / "dist" / f"{name}-0.0.1-py3-none-any.whl").write_text(
            "whl", encoding="utf-8"
        )

    env = SimpleNamespace(
        wenv_abs=tmp_path / "wenv",
        wenv_rel=Path("wenv"),
        dist_rel=Path("wenv/dist"),
        dist_abs=dist_abs,
        pyvers_worker="3.13",
        envars={},
        uv_worker="uv",
        is_source_env=True,
        app="demo_app",
        target_worker="demo_worker",
        agi_env=agi_env,
        agi_node=agi_node,
        post_install_rel="demo.post_install",
        verbose=0,
    )
    agi_cls = SimpleNamespace(
        _rapids_enabled=False,
        _workers_data_path=None,
        exec_ssh=lambda *_a, **_k: None,
        send_files=lambda *_a, **_k: None,
        send_file=lambda *_a, **_k: None,
    )
    log = mock.Mock()

    with pytest.raises(FileNotFoundError, match="no existing egg file"):
        await _call_deploy_remote_worker(
            agi_cls,
            "10.0.0.2",
            env,
            Path("wenv"),
            "",
            set_env_var_fn=lambda *_a, **_k: None,
            log=log,
        )

    log.error.assert_called_once()


@pytest.mark.asyncio
async def test_deploy_remote_worker_source_env_missing_wheels_raise(tmp_path):
    dist_abs = tmp_path / "dist"
    dist_abs.mkdir(parents=True, exist_ok=True)
    (dist_abs / "demo_worker-0.0.1.egg").write_text("egg", encoding="utf-8")
    agi_env = tmp_path / "agi_env"
    agi_node = tmp_path / "agi_node"
    (agi_env / "dist").mkdir(parents=True, exist_ok=True)
    (agi_node / "dist").mkdir(parents=True, exist_ok=True)
    (agi_node / "dist" / "agi_node-0.0.1-py3-none-any.whl").write_text(
        "whl", encoding="utf-8"
    )

    env = SimpleNamespace(
        wenv_abs=tmp_path / "wenv",
        wenv_rel=Path("wenv"),
        dist_rel=Path("wenv/dist"),
        dist_abs=dist_abs,
        pyvers_worker="3.13",
        envars={},
        uv_worker="uv",
        is_source_env=True,
        app="demo_app",
        target_worker="demo_worker",
        agi_env=agi_env,
        agi_node=agi_node,
        post_install_rel="demo.post_install",
        verbose=0,
    )

    async def _fake_send(*_args, **_kwargs):
        return None

    agi_cls = SimpleNamespace(
        _rapids_enabled=False,
        _workers_data_path=None,
        exec_ssh=_fake_send,
        send_files=_fake_send,
        send_file=_fake_send,
    )

    with pytest.raises(FileNotFoundError, match="agi_env"):
        await _call_deploy_remote_worker(
            agi_cls,
            "10.0.0.2",
            env,
            Path("wenv"),
            "",
            set_env_var_fn=lambda *_a, **_k: None,
            log=mock.Mock(),
        )

    (agi_env / "dist" / "agi_env-0.0.1-py3-none-any.whl").write_text(
        "whl", encoding="utf-8"
    )
    (agi_node / "dist" / "agi_node-0.0.1-py3-none-any.whl").unlink()
    with pytest.raises(FileNotFoundError, match="agi_node"):
        await _call_deploy_remote_worker(
            agi_cls,
            "10.0.0.2",
            env,
            Path("wenv"),
            "",
            set_env_var_fn=lambda *_a, **_k: None,
            log=mock.Mock(),
        )


@pytest.mark.asyncio
async def test_deploy_remote_worker_non_source_missing_egg_raises(tmp_path):
    dist_abs = tmp_path / "dist"
    dist_abs.mkdir(parents=True, exist_ok=True)
    env = SimpleNamespace(
        wenv_abs=tmp_path / "worker_env",
        wenv_rel=Path("worker_env"),
        dist_rel=Path("worker_env/dist"),
        dist_abs=dist_abs,
        pyvers_worker="3.13",
        envars={},
        uv_worker="uv",
        is_source_env=False,
        app="demo_app",
        target_worker="demo_worker",
        post_install_rel="demo.post_install",
        verbose=0,
    )
    agi_cls = SimpleNamespace(
        _rapids_enabled=False,
        _workers_data_path=None,
        exec_ssh=lambda *_a, **_k: None,
        send_files=lambda *_a, **_k: None,
        send_file=lambda *_a, **_k: None,
    )
    log = mock.Mock()

    with pytest.raises(FileNotFoundError, match="no existing egg file"):
        await _call_deploy_remote_worker(
            agi_cls,
            "10.0.0.2",
            env,
            Path("worker_env"),
            "",
            set_env_var_fn=lambda *_a, **_k: None,
            log=log,
        )

    log.error.assert_called_once()


@pytest.mark.asyncio
async def test_deploy_remote_worker_rapids_false_and_temp_pth_cleanup_missing(
    monkeypatch, tmp_path
):
    dist_abs = tmp_path / "dist"
    dist_abs.mkdir(parents=True, exist_ok=True)
    (dist_abs / "demo_worker-0.0.1.egg").write_text("egg", encoding="utf-8")

    env = SimpleNamespace(
        wenv_abs=tmp_path / "worker_env",
        wenv_rel=Path("worker_env"),
        dist_rel=Path("worker_env/dist"),
        dist_abs=dist_abs,
        pyvers_worker="3.13",
        envars={},
        uv_worker="uv",
        is_source_env=False,
        app="demo_app",
        target_worker="demo_worker",
        post_install_rel="demo.post_install",
        verbose=0,
        hw_rapids_capable=None,
    )
    ssh_calls = []
    env_vars = []

    async def _fake_exec(ip, cmd):
        ssh_calls.append((ip, cmd))
        if "rapids-probe" in cmd:
            return _rapids_probe_output(False)
        return "ok"

    async def _fake_send(_env, ip, files, remote_path, user=None, password=None):
        del _env, ip, files, remote_path, user, password

    original_unlink = Path.unlink

    def _patched_unlink(self, *args, **kwargs):
        if self.name.startswith("agilab_uv_sources_"):
            raise FileNotFoundError(self)
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", _patched_unlink)

    agi_cls = SimpleNamespace(
        _rapids_enabled=True,
        _workers_data_path=None,
        exec_ssh=_fake_exec,
        send_files=_fake_send,
        send_file=_fake_send,
    )

    await _call_deploy_remote_worker(
        agi_cls,
        "10.0.0.2",
        env,
        Path("worker_env"),
        "",
        set_env_var_fn=lambda *args: env_vars.append(args),
        log=mock.Mock(),
    )

    assert any("rapids-probe" in cmd for _ip, cmd in ssh_calls)
    assert env.hw_rapids_capable is False
    assert env_vars == [("10.0.0.2", "no_rapids_hw")]


@pytest.mark.asyncio
async def test_deploy_remote_worker_rapids_runtime_error_is_logged(tmp_path):
    dist_abs = tmp_path / "dist"
    dist_abs.mkdir(parents=True, exist_ok=True)
    (dist_abs / "demo_worker-0.0.1.egg").write_text("egg", encoding="utf-8")

    env = SimpleNamespace(
        wenv_abs=tmp_path / "worker_env",
        wenv_rel=Path("worker_env"),
        dist_rel=Path("worker_env/dist"),
        dist_abs=dist_abs,
        pyvers_worker="3.13",
        envars={},
        uv_worker="uv",
        is_source_env=False,
        app="demo_app",
        target_worker="demo_worker",
        post_install_rel="demo.post_install",
        verbose=0,
    )

    async def _fake_exec(_ip, cmd):
        if "rapids-probe" in cmd:
            raise RuntimeError("rapids probe unavailable")
        return "ok"

    async def _fake_send(*_args, **_kwargs):
        return None

    agi_cls = SimpleNamespace(
        _rapids_enabled=True,
        _workers_data_path=None,
        exec_ssh=_fake_exec,
        send_files=_fake_send,
        send_file=_fake_send,
    )
    log = mock.Mock()

    with pytest.raises(RuntimeError, match="rapids probe unavailable"):
        await _call_deploy_remote_worker(
            agi_cls,
            "10.0.0.2",
            env,
            Path("worker_env"),
            "",
            set_env_var_fn=lambda *_a, **_k: None,
            log=log,
        )

    log.error.assert_called_once()


def test_remote_env_update_command_preserves_other_env_keys():
    # Regression: concurrent remote deploys previously shared one .env.tmp and
    # treated a failed read as empty, which could erase operator settings.
    cmd = deployment_remote_support._remote_env_update_command(
        "clustershare/agi",
        "clustershare/agi/workflows/session-123",
    )

    assert 'env_path.name + ".lock"' in cmd
    assert "tempfile.mkstemp" in cmd
    assert "os.replace" in cmd
    assert "IS_SOURCE_ENV" in cmd
    assert "IS_WORKER_ENV" in cmd
    assert "AGI_CLUSTER_ENABLED" in cmd
    assert "AGI_CLUSTER_SHARE" in cmd
    assert "AGILAB_WORKFLOW_DATA_ROOT" in cmd
    assert "clustershare/agi/workflows/session-123" in cmd
    assert "AGI_LOCAL_SHARE" not in cmd
    assert "grep -Ev" not in cmd
    assert '"$HOME/.agilab/.env.tmp"' not in cmd


@pytest.mark.skipif(os.name == "nt", reason="BSD/macOS mount output uses POSIX paths")
def test_local_mount_record_for_path_falls_back_to_mount_on_missing_findmnt(
    monkeypatch, tmp_path
):
    # Regression: findmnt does not exist on macOS, which silently disabled the
    # reverse-SSHFS loop guard; the probe must fall back to ``mount`` output.
    share = tmp_path / "clustershare" / "agi"
    share.mkdir(parents=True, exist_ok=True)
    mount_output = (
        "/dev/disk3s1 on / (apfs, sealed, local, read-only, journaled)\n"
        f"agi@192.168.20.15:/home/agi/clustershare on {tmp_path / 'clustershare'} "
        "(macfuse, nodev, nosuid, synchronous, mounted by agi)\n"
    )

    def _fake_run(argv, **_kwargs):
        if argv[0] == "findmnt":
            raise FileNotFoundError("findmnt")
        assert argv == ["mount"]
        return SimpleNamespace(returncode=0, stdout=mount_output)

    monkeypatch.setattr(deployment_remote_support.subprocess, "run", _fake_run)

    record = deployment_remote_support._local_mount_record_for_path(share)

    assert record == {
        "TARGET": str(tmp_path / "clustershare"),
        "SOURCE": "agi@192.168.20.15:/home/agi/clustershare",
        "FSTYPE": "macfuse",
    }

    problem = deployment_remote_support._reverse_sshfs_mount_problem(
        share, "192.168.20.15"
    )
    assert problem is not None and "SSHFS loop" in problem


def test_reverse_sshfs_mount_problem_matches_macfuse_and_nfs_fstypes(monkeypatch):
    # macFUSE/FUSE-T SSHFS mounts surface as "macfuse"/"nfs" rather than the
    # Linux "fuse.sshfs" fstype.
    for fstype in ("macfuse", "nfs", "fuse.sshfs"):
        monkeypatch.setattr(
            deployment_remote_support,
            "_local_mount_record_for_path",
            lambda _path, _fstype=fstype: {
                "TARGET": "/Users/agi/clustershare",
                "SOURCE": "agi@192.168.20.15:/home/agi/clustershare",
                "FSTYPE": _fstype,
            },
        )
        problem = deployment_remote_support._reverse_sshfs_mount_problem(
            Path("/Users/agi/clustershare"), "192.168.20.15"
        )
        assert problem is not None, fstype


def test_resolve_worker_egg_falls_back_and_raises(tmp_path):
    env = SimpleNamespace(target_worker="demo_worker", app="demo_app")
    log = mock.Mock()

    with pytest.raises(FileNotFoundError, match="no existing egg file"):
        deployment_remote_support._resolve_worker_egg(env, tmp_path, log)
    log.error.assert_called_once()

    fallback_egg = tmp_path / "demo_app-0.0.1.egg"
    fallback_egg.write_text("egg", encoding="utf-8")
    assert (
        deployment_remote_support._resolve_worker_egg(env, tmp_path, log)
        == fallback_egg
    )
