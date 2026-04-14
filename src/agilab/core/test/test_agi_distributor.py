import json
import io
import os
import pickle
import socket
import urllib.request
import getpass
from types import SimpleNamespace
from pathlib import Path, PurePosixPath
from contextlib import asynccontextmanager
import asyncio
import time
from unittest import mock
import pytest
import psutil
from agi_cluster.agi_distributor import AGI
import agi_cluster.agi_distributor.agi_distributor as agi_distributor_module
from agi_env import AgiEnv, normalize_path
from agi_node.agi_dispatcher import BaseWorker

# Set AGI verbosity low to avoid extra prints during test.
AGI.verbose = 0


def test_envar_truthy_handles_common_inputs_and_failures():
    assert agi_distributor_module._envar_truthy({"A": True}, "A") is True
    assert agi_distributor_module._envar_truthy({"A": 1}, "A") is True
    assert agi_distributor_module._envar_truthy({"A": 1.0}, "A") is True
    assert agi_distributor_module._envar_truthy({"A": " yes "}, "A") is True
    assert agi_distributor_module._envar_truthy({"A": "ON"}, "A") is True
    assert agi_distributor_module._envar_truthy({"A": None}, "A") is False
    assert agi_distributor_module._envar_truthy({"A": 2}, "A") is False
    assert agi_distributor_module._envar_truthy({"A": "off"}, "A") is False
    assert agi_distributor_module._envar_truthy({"A": float("nan")}, "A") is False

    class _BrokenEnv:
        def get(self, _key):
            raise RuntimeError("boom")

    assert agi_distributor_module._envar_truthy(_BrokenEnv(), "A") is False


def test_ensure_optional_extras_noop_when_extras_empty(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    agi_distributor_module._ensure_optional_extras(pyproject, set())
    assert pyproject.exists() is False


def test_ensure_optional_extras_creates_and_updates_table(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[project]
name = "demo"
optional-dependencies = []
""".strip(),
        encoding="utf-8",
    )

    agi_distributor_module._ensure_optional_extras(pyproject, {"polars-worker", " ", "dag-worker"})
    content = pyproject.read_text(encoding="utf-8")
    assert "[project.optional-dependencies]" in content
    assert "polars-worker = []" in content
    assert "dag-worker = []" in content


def test_ensure_optional_extras_bootstraps_missing_pyproject(tmp_path):
    pyproject = tmp_path / "pyproject.toml"

    agi_distributor_module._ensure_optional_extras(pyproject, {"agent-worker"})

    content = pyproject.read_text(encoding="utf-8")
    assert "[project.optional-dependencies]" in content
    assert "agent-worker = []" in content


def test_distributor_cli_process_helpers_cover_windows_and_child_scan(monkeypatch):
    cli = agi_distributor_module.distributor_cli

    monkeypatch.setattr(cli.os, "name", "nt", raising=False)
    monkeypatch.setattr(
        cli.subprocess,
        "check_output",
        lambda *_a, **_k: '"dask-worker.exe","1234"\n"python.exe","oops"\n',
    )
    assert cli.get_processes_containing("dask") == {1234}

    monkeypatch.setattr(cli.os, "name", "posix", raising=False)
    monkeypatch.setattr(
        cli.subprocess,
        "check_output",
        lambda *_a, **_k: "10 1\n11 10\nbad line\n",
    )
    assert cli.get_child_pids({10}) == {11}


def test_distributor_cli_kill_handles_pid_files_children_and_exclusions(monkeypatch, tmp_path):
    cli = agi_distributor_module.distributor_cli
    monkeypatch.chdir(tmp_path)

    (tmp_path / "keep.pid").write_text("999\n", encoding="utf-8")
    (tmp_path / "worker.pid").write_text("111\n", encoding="utf-8")
    (tmp_path / "broken.pid").write_text("bad\n", encoding="utf-8")

    kill_calls = []
    monkeypatch.setattr(cli, "get_processes_containing", lambda _name: set())
    monkeypatch.setattr(cli.os, "getpid", lambda: 999)
    monkeypatch.setattr(cli, "get_child_pids", lambda pids: {222} if 111 in pids else set())
    monkeypatch.setattr(cli, "kill_pids", lambda pids, sig: kill_calls.append((set(pids), sig)) or set())
    monkeypatch.setattr(cli, "_poll_until_dead", lambda pids, **_k: set())

    cli.kill()

    assert kill_calls
    assert any(pids == {111, 222} for pids, _sig in kill_calls)
    assert not (tmp_path / "worker.pid").exists()
    assert not (tmp_path / "keep.pid").exists()
    assert not (tmp_path / "broken.pid").exists()


def test_distributor_cli_clean_and_unzip_cover_success_and_failure(monkeypatch, tmp_path):
    cli = agi_distributor_module.distributor_cli
    scratch_root = tmp_path / "tmpdir"
    scratch_root.mkdir()
    scratch = scratch_root / "dask-scratch-space"
    scratch.mkdir()
    wenv = tmp_path / "wenv"
    wenv.mkdir()
    egg = wenv / "demo.egg"
    with cli.zipfile.ZipFile(egg, "w") as zf:
        zf.writestr("pkg/module.py", "print('ok')\n")

    monkeypatch.setattr(cli, "gettempdir", lambda: str(scratch_root))
    cli.unzip(str(wenv))
    assert (wenv / "src" / "pkg" / "module.py").exists()

    monkeypatch.setattr(cli.shutil, "rmtree", lambda *_a, **_k: (_ for _ in ()).throw(OSError("locked")))
    cli.clean(str(wenv))


def test_distributor_cli_signal_helpers_cover_alive_and_permission_paths(monkeypatch):
    cli = agi_distributor_module.distributor_cli
    calls = []

    def _fake_kill(pid, sig):
        calls.append((pid, sig))
        if pid == 2:
            raise ProcessLookupError()
        if pid == 3:
            raise PermissionError()
        if pid == 4:
            raise RuntimeError("boom")

    monkeypatch.setattr(cli.os, "kill", _fake_kill)

    assert cli._is_alive(1) is True
    assert cli._is_alive(2) is False
    assert cli._is_alive(3) is True

    survivors = cli.kill_pids({1, 2, 3, 4}, cli.signal.SIGTERM)
    assert survivors == {3, 4}
    assert calls


def test_rewrite_uv_sources_paths_rewrites_invalid_entries_and_logs(tmp_path, monkeypatch):
    src_dir = tmp_path / "src" / "worker"
    dst_dir = tmp_path / "dst" / "worker"
    src_dir.mkdir(parents=True, exist_ok=True)
    dst_dir.mkdir(parents=True, exist_ok=True)

    src_deps = src_dir.parent / "deps"
    (src_deps / "foo").mkdir(parents=True, exist_ok=True)
    (src_deps / "bar").mkdir(parents=True, exist_ok=True)
    (dst_dir / "keep-bar").mkdir(parents=True, exist_ok=True)

    src_pyproject = src_dir / "pyproject.toml"
    dst_pyproject = dst_dir / "pyproject.toml"

    src_pyproject.write_text(
        """
[tool.uv.sources]
foo = { path = "../deps/foo" }
bar = { path = "../deps/bar" }
missing = { path = "../deps/missing" }
blank = { path = "" }
non_dict = "value"
""".strip(),
        encoding="utf-8",
    )
    dst_pyproject.write_text(
        """
[tool.uv.sources]
foo = { path = "../bad/foo" }
bar = { path = "keep-bar" }
missing = { path = "../bad/missing" }
blank = { path = "../bad/blank" }
non_dict = { path = "../bad/non_dict" }
""".strip(),
        encoding="utf-8",
    )

    logs = []
    monkeypatch.setattr(
        agi_distributor_module.logger,
        "info",
        lambda *args, **kwargs: logs.append(args),
    )

    agi_distributor_module._rewrite_uv_sources_paths_for_copied_pyproject(
        src_pyproject=src_pyproject,
        dest_pyproject=dst_pyproject,
        log_rewrites=True,
    )

    content = dst_pyproject.read_text(encoding="utf-8")
    expected_rel_foo = os.path.relpath((src_deps / "foo").resolve(strict=False), start=dst_dir)
    assert f'foo = {{ path = "{expected_rel_foo}" }}' in content
    assert 'bar = { path = "keep-bar" }' in content
    assert 'missing = { path = "../bad/missing" }' in content
    assert any("Rewrote uv source" in str(entry[0]) for entry in logs if entry)


def test_rewrite_uv_sources_paths_ignores_missing_files(tmp_path):
    src_pyproject = tmp_path / "missing-src.toml"
    dst_pyproject = tmp_path / "missing-dst.toml"
    agi_distributor_module._rewrite_uv_sources_paths_for_copied_pyproject(
        src_pyproject=src_pyproject,
        dest_pyproject=dst_pyproject,
    )
    assert src_pyproject.exists() is False
    assert dst_pyproject.exists() is False


def test_discover_private_ssh_keys_ignores_config_and_public_metadata(tmp_path):
    ssh_dir = tmp_path / ".ssh"
    ssh_dir.mkdir()
    (ssh_dir / "config").write_text("Host remote\n  User agi\n", encoding="utf-8")
    (ssh_dir / "known_hosts").write_text("remote ssh-ed25519 AAAA\n", encoding="utf-8")
    (ssh_dir / "authorized_keys").write_text("ssh-ed25519 AAAA comment\n", encoding="utf-8")
    (ssh_dir / "id_ed25519.pub").write_text("ssh-ed25519 AAAA comment\n", encoding="utf-8")
    (ssh_dir / "id_rsa").write_text(
        "-----BEGIN RSA PRIVATE KEY-----\nmock\n-----END RSA PRIVATE KEY-----\n",
        encoding="utf-8",
    )
    (ssh_dir / "id_ed25519").write_text(
        "-----BEGIN OPENSSH PRIVATE KEY-----\nmock\n-----END OPENSSH PRIVATE KEY-----\n",
        encoding="utf-8",
    )
    (ssh_dir / "id_rsa.old").write_text("stale backup", encoding="utf-8")

    keys = agi_distributor_module._discover_private_ssh_keys(ssh_dir)

    assert keys == [str(ssh_dir / "id_ed25519"), str(ssh_dir / "id_rsa")]


def test_private_key_discovery_handles_missing_dir_and_unreadable_files(tmp_path, monkeypatch):
    assert agi_distributor_module._discover_private_ssh_keys(tmp_path / ".ssh") == []

    unreadable = tmp_path / "id_demo"
    unreadable.write_text("x", encoding="utf-8")
    monkeypatch.setattr(Path, "read_text", lambda self, *args, **kwargs: (_ for _ in ()).throw(OSError("boom")), raising=False)

    assert agi_distributor_module._is_private_ssh_key_file(unreadable) is False


def test_stage_uv_sources_for_copied_pyproject_stages_sources(tmp_path, monkeypatch):
    src_dir = tmp_path / "src" / "worker"
    dst_dir = tmp_path / "dst"
    src_dir.mkdir(parents=True, exist_ok=True)
    dst_dir.mkdir(parents=True, exist_ok=True)

    src_deps = src_dir.parent / "deps"
    (src_deps / "foo").mkdir(parents=True, exist_ok=True)
    (src_deps / "foo" / "pyproject.toml").write_text("[project]\nname='foo'\n", encoding="utf-8")
    (src_deps / "foo" / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    (src_deps / "foo" / ".venv").mkdir(parents=True, exist_ok=True)
    (src_deps / "foo" / ".venv" / "skip.txt").write_text("x", encoding="utf-8")

    src_pyproject = src_dir / "pyproject.toml"
    dst_pyproject = dst_dir / "pyproject.toml"
    src_pyproject.write_text(
        """
[tool.uv.sources]
foo = { path = "../deps/foo" }
""".strip(),
        encoding="utf-8",
    )
    dst_pyproject.write_text(
        """
[tool.uv.sources]
foo = { path = "../bad/foo" }
""".strip(),
        encoding="utf-8",
    )

    logs = []
    monkeypatch.setattr(
        agi_distributor_module.logger,
        "info",
        lambda *args, **kwargs: logs.append(args),
    )

    staged_entries = agi_distributor_module._stage_uv_sources_for_copied_pyproject(
        src_pyproject=src_pyproject,
        dest_pyproject=dst_pyproject,
        stage_root=dst_dir,
        log_rewrites=True,
    )

    staged_root = dst_dir / "_uv_sources"
    staged_dep = staged_root / "foo"
    assert staged_entries == [staged_root]
    assert staged_dep.exists()
    assert (staged_dep / "module.py").exists()
    assert not (staged_dep / ".venv").exists()
    assert 'foo = { path = "_uv_sources/foo" }' in dst_pyproject.read_text(encoding="utf-8")
    assert any("Staged uv source" in str(entry[0]) for entry in logs if entry)


def test_rewrite_uv_sources_paths_for_copied_pyproject_rewrites_invalid_paths_and_keeps_valid_ones(tmp_path, monkeypatch):
    src_dir = tmp_path / "src"
    dest_dir = tmp_path / "dest"
    src_dir.mkdir()
    dest_dir.mkdir()

    rel_dep = src_dir / "deps" / "foo"
    rel_dep.mkdir(parents=True)
    abs_dep = tmp_path / "abs-dep"
    abs_dep.mkdir()
    valid_dest = dest_dir / "vendored" / "baz"
    valid_dest.mkdir(parents=True)

    src_pyproject = src_dir / "pyproject.toml"
    dest_pyproject = dest_dir / "pyproject.toml"
    src_pyproject.write_text(
        f"""
[tool.uv.sources]
foo = {{ path = "deps/foo" }}
bar = {{ path = "{abs_dep}" }}
baz = {{ path = "deps/foo" }}
skip_meta = 3
blank = {{ path = "" }}
missing = {{ path = "deps/missing" }}
""".strip(),
        encoding="utf-8",
    )
    dest_pyproject.write_text(
        f"""
[tool.uv.sources]
foo = {{ path = "../broken/foo" }}
bar = {{ path = "../broken/bar" }}
baz = {{ path = "vendored/baz" }}
skip_meta = {{ path = "../ignored" }}
blank = {{ path = "../ignored-blank" }}
missing = {{ path = "../ignored-missing" }}
""".strip(),
        encoding="utf-8",
    )

    logs = []
    monkeypatch.setattr(agi_distributor_module.logger, "info", lambda *args, **kwargs: logs.append(args))

    agi_distributor_module._rewrite_uv_sources_paths_for_copied_pyproject(
        src_pyproject=src_pyproject,
        dest_pyproject=dest_pyproject,
        log_rewrites=True,
    )

    content = dest_pyproject.read_text(encoding="utf-8")
    assert 'foo = { path = "../src/deps/foo" }' in content
    assert f'bar = {{ path = "{os.path.relpath(abs_dep, start=dest_dir)}" }}' in content
    assert 'baz = { path = "vendored/baz" }' in content
    assert 'blank = { path = "../ignored-blank" }' in content
    assert 'missing = { path = "../ignored-missing" }' in content
    assert any("Rewrote uv source" in str(entry[0]) for entry in logs if entry)


def test_rewrite_uv_sources_paths_for_copied_pyproject_handles_missing_files_and_relpath_failures(tmp_path, monkeypatch):
    src_dir = tmp_path / "src"
    dest_dir = tmp_path / "dest"
    src_dir.mkdir()
    dest_dir.mkdir()
    dep = src_dir / "dep"
    dep.mkdir()

    src_pyproject = src_dir / "pyproject.toml"
    dest_pyproject = dest_dir / "pyproject.toml"
    src_pyproject.write_text('[tool.uv.sources]\nfoo = { path = "dep" }\nnot_a_table = "skip"\n', encoding="utf-8")
    dest_pyproject.write_text('[tool.uv.sources]\nfoo = { path = "../old" }\nnot_a_table = { path = "../unchanged" }\n', encoding="utf-8")

    monkeypatch.setattr(agi_distributor_module.os.path, "relpath", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    agi_distributor_module._rewrite_uv_sources_paths_for_copied_pyproject(
        src_pyproject=src_pyproject,
        dest_pyproject=dest_pyproject,
    )

    assert f'foo = {{ path = "{dep.resolve(strict=False)}" }}' in dest_pyproject.read_text(encoding="utf-8")
    agi_distributor_module._rewrite_uv_sources_paths_for_copied_pyproject(
        src_pyproject=tmp_path / "missing-src.toml",
        dest_pyproject=dest_pyproject,
    )


def test_stage_uv_sources_for_copied_pyproject_falls_back_when_relpath_fails(tmp_path, monkeypatch):
    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst"
    src_dir.mkdir()
    dst_dir.mkdir()
    dep = src_dir / "dep"
    dep.mkdir()
    (dep / "pyproject.toml").write_text("[project]\nname='dep'\n", encoding="utf-8")

    src_pyproject = src_dir / "pyproject.toml"
    dest_pyproject = dst_dir / "pyproject.toml"
    src_pyproject.write_text('[tool.uv.sources]\nfoo = { path = "dep" }\n', encoding="utf-8")
    dest_pyproject.write_text('[tool.uv.sources]\nfoo = { path = "../old" }\n', encoding="utf-8")

    monkeypatch.setattr(agi_distributor_module.os.path, "relpath", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    staged_entries = agi_distributor_module._stage_uv_sources_for_copied_pyproject(
        src_pyproject=src_pyproject,
        dest_pyproject=dest_pyproject,
        stage_root=dst_dir,
    )

    staged_target = dst_dir / "_uv_sources" / "foo"
    assert staged_entries == [dst_dir / "_uv_sources"]
    assert f'foo = {{ path = "{staged_target}" }}' in dest_pyproject.read_text(encoding="utf-8")


def test_copy_uv_source_tree_replaces_existing_file_destination(tmp_path):
    source = tmp_path / "source.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    destination = tmp_path / "staged" / "source.py"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("old\n", encoding="utf-8")

    agi_distributor_module._copy_uv_source_tree(source, destination)

    assert destination.read_text(encoding="utf-8") == "VALUE = 1\n"


def test_missing_uv_source_paths_reports_unresolved_entries(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    (tmp_path / "_uv_sources" / "ok").mkdir(parents=True, exist_ok=True)
    pyproject.write_text(
        """
[tool.uv.sources]
ok = { path = "_uv_sources/ok" }
missing = { path = "_uv_sources/missing" }
""".strip(),
        encoding="utf-8",
    )

    missing = agi_distributor_module._missing_uv_source_paths(pyproject)
    assert missing == [("missing", "_uv_sources/missing")]


def test_missing_uv_source_paths_and_validation_cover_edge_cases(tmp_path):
    assert agi_distributor_module._missing_uv_source_paths(tmp_path / "missing.toml") == []

    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[tool.uv.sources]
a = { path = "_uv_sources/a" }
b = { path = "_uv_sources/b" }
c = { path = "_uv_sources/c" }
d = { path = "_uv_sources/d" }
e = { path = "_uv_sources/e" }
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match=r"\+1 more"):
        agi_distributor_module._validate_worker_uv_sources(pyproject)


def test_validate_worker_uv_sources_raises_actionable_error(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[tool.uv.sources]
ilp_worker = { path = "../../PycharmProjects/thales_agilab/apps/ilp_project/src/ilp_worker" }
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="stale or incomplete"):
        agi_distributor_module._validate_worker_uv_sources(pyproject)


def test_staged_uv_sources_pth_content_relative_for_local_paths(tmp_path):
    site_packages = tmp_path / "wenv" / ".venv" / "lib" / "python3.13" / "site-packages"
    uv_sources = tmp_path / "wenv" / "_uv_sources"
    content = agi_distributor_module._staged_uv_sources_pth_content(site_packages, uv_sources)
    assert content == "../../../../_uv_sources\n"


def test_staged_uv_sources_pth_content_relative_for_remote_posix_paths():
    site_packages = PurePosixPath("wenv/.venv/lib/python3.13/site-packages")
    uv_sources = PurePosixPath("wenv/_uv_sources")
    content = agi_distributor_module._staged_uv_sources_pth_content(site_packages, uv_sources)
    assert content == "../../../../_uv_sources\n"


def test_worker_site_packages_dir_and_pth_writer_branches(tmp_path):
    windows_path = agi_distributor_module._worker_site_packages_dir(Path("worker"), "3.13", windows=True)
    free_threaded = agi_distributor_module._worker_site_packages_dir(Path("worker"), "3.13t")
    assert windows_path == Path("worker/.venv/Lib/site-packages")
    assert free_threaded == Path("worker/.venv/lib/python3.13t/site-packages")

    site_packages = tmp_path / "worker" / ".venv" / "lib" / "python3.13" / "site-packages"
    site_packages.mkdir(parents=True, exist_ok=True)
    pth_path = site_packages / "agilab_uv_sources.pth"
    pth_path.write_text("stale\n", encoding="utf-8")

    assert agi_distributor_module._write_staged_uv_sources_pth(site_packages, tmp_path / "missing") is None
    assert not pth_path.exists()

    uv_sources = tmp_path / "worker" / "_uv_sources"
    uv_sources.mkdir(parents=True, exist_ok=True)
    written = agi_distributor_module._write_staged_uv_sources_pth(site_packages, uv_sources)
    assert written == pth_path
    assert pth_path.read_text(encoding="utf-8").endswith("_uv_sources\n")


def test_background_process_manager_tracks_running_completed_and_dead_jobs(monkeypatch, tmp_path):
    popen_calls: list[dict[str, object]] = []

    class FakeProcess:
        def __init__(self, status):
            self._status = status

        def poll(self):
            return self._status

    processes = [FakeProcess(None), FakeProcess(0), FakeProcess(3)]

    def fake_popen(cmd, shell, cwd, start_new_session):
        popen_calls.append(
            {
                "cmd": cmd,
                "shell": shell,
                "cwd": cwd,
                "start_new_session": start_new_session,
            }
        )
        return processes.pop(0)

    monkeypatch.setattr(agi_distributor_module.subprocess, "Popen", fake_popen)

    manager = agi_distributor_module._BackgroundProcessManager()
    running = manager.new("echo running", cwd=tmp_path)
    completed = manager.new("echo completed", cwd=tmp_path)
    dead = manager.new("echo dead", cwd=tmp_path / "missing")

    assert running.num == 0
    assert completed.num == 1
    assert dead.num == 2
    assert popen_calls[0]["cwd"] == str(tmp_path)
    assert popen_calls[2]["cwd"] is None
    assert manager.result(running.num) is running.process
    assert manager.result(completed.num) is completed.process
    assert manager.result(dead.num) is None
    assert completed in manager.completed
    assert dead in manager.dead

    manager.flush()

    assert completed.num not in manager.all
    assert dead.num not in manager.all
    assert running.num in manager.all
    assert manager.completed == []
    assert manager.dead == []


def test_background_process_manager_normalize_cwd_handles_invalid_values():
    manager = agi_distributor_module._BackgroundProcessManager()

    assert manager._normalize_cwd(None) is None
    assert manager._normalize_cwd("") is None
    assert manager._normalize_cwd(Path("/definitely/missing/path")) is None

    class BrokenPath:
        def __fspath__(self):
            raise RuntimeError("boom")

    assert manager._normalize_cwd(BrokenPath()) is None


def test_agi_singleton_guard_raises_when_already_instantiated(monkeypatch):
    monkeypatch.setattr(AGI, "_instantiated", True, raising=False)
    try:
        with pytest.raises(RuntimeError, match="singleton"):
            AGI("demo")
    finally:
        monkeypatch.setattr(AGI, "_instantiated", False, raising=False)


@pytest.mark.asyncio
async def test_install_sets_sync_run_type_and_install_mode(monkeypatch):
    captured: dict[str, object] = {}

    async def _fake_run(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(AGI, "run", staticmethod(_fake_run))

    env = SimpleNamespace()
    await AGI.install(
        env=env,
        scheduler="127.0.0.1",
        workers={"127.0.0.1": 1},
        workers_data_path="/tmp/workers",
        modes_enabled=AGI.PYTHON_MODE,
        verbose=3,
        force_update=True,
    )

    assert AGI._run_type == "sync"
    assert captured["env"] is env
    assert captured["mode"] == (AGI._INSTALL_MODE | AGI.PYTHON_MODE)
    assert captured["workers_data_path"] == "/tmp/workers"
    assert captured["rapids_enabled"] == (AGI._INSTALL_MODE & AGI.PYTHON_MODE)
    assert captured["force_update"] is True


@pytest.mark.asyncio
async def test_stop_handles_scheduler_info_and_retire_failures(monkeypatch):
    closed = {"count": 0}

    async def _fake_close_all():
        closed["count"] += 1

    class _SchedulerInfoFailsClient:
        shutdown_calls = 0

        async def scheduler_info(self):
            raise RuntimeError("scheduler down")

        async def shutdown(self):
            self.shutdown_calls += 1

    AGI._mode_auto = False
    AGI._dask_client = _SchedulerInfoFailsClient()
    monkeypatch.setattr(AGI, "_close_all_connections", staticmethod(_fake_close_all))
    await AGI._stop()
    assert AGI._dask_client.shutdown_calls == 1
    assert closed["count"] == 1

    closed["count"] = 0

    class _RetireFailsClient:
        shutdown_calls = 0

        async def scheduler_info(self):
            return {"workers": {"tcp://127.0.0.1:8787": {}}}

        async def retire_workers(self, **_kwargs):
            raise RuntimeError("retire failed")

        async def shutdown(self):
            self.shutdown_calls += 1

    AGI._dask_client = _RetireFailsClient()
    monkeypatch.setattr(AGI, "_close_all_connections", staticmethod(_fake_close_all))
    await AGI._stop()
    assert AGI._dask_client.shutdown_calls == 1
    assert closed["count"] == 1


@pytest.mark.asyncio
async def test_calibration_fallback_uses_worker_counts_when_no_worker_keys_exist():
    class _Client:
        def run(self, *_args, **_kwargs):
            return {}

        def gather(self, payload):
            return payload

    AGI._dask_client = _Client()
    AGI._dask_workers = []
    AGI._workers = {"10.0.0.1": 2}
    AGI._capacity_predictor = SimpleNamespace(predict=lambda _x: [1.0])

    await AGI._calibration()

    assert AGI._capacity == {"10.0.0.1:0": 1.0, "10.0.0.1:1": 1.0}
    assert AGI.workers_info == {"10.0.0.1:0": {"label": 1.0}, "10.0.0.1:1": {"label": 1.0}}


@pytest.fixture(autouse=True)
def _reset_agi_service_state(monkeypatch, tmp_path):
    state_file = tmp_path / "service_state.json"
    monkeypatch.setattr(AGI, "_service_state_path", staticmethod(lambda _env: state_file))
    health_file = tmp_path / "service_health.json"

    def _health_path(_env, health_output_path=None):
        if health_output_path is None:
            health_file.parent.mkdir(parents=True, exist_ok=True)
            return health_file
        explicit = Path(str(health_output_path))
        if explicit.is_absolute():
            explicit.parent.mkdir(parents=True, exist_ok=True)
            return explicit
        resolved = (tmp_path / explicit).resolve(strict=False)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        return resolved

    monkeypatch.setattr(AGI, "_service_health_path", staticmethod(_health_path))
    AGI._service_futures = {}
    AGI._service_workers = []
    AGI._dask_client = None
    AGI._jobs = None
    AGI._reset_service_queue_state()
    yield
    AGI._service_futures = {}
    AGI._service_workers = []
    AGI._dask_client = None
    AGI._jobs = None
    AGI._reset_service_queue_state()


def test_normalize_path():
    # Given a relative path "."
    input_path = ""
    normalized = normalize_path(input_path)
    if os.name == "nt":
        assert os.path.isabs(normalized), "On Windows the normalized path should be absolute."
    else:
        # On POSIX, compare with the PurePosixPath version.
        expected = str(PurePosixPath(Path(input_path)))
        assert normalized == expected, f"Expected {expected} but got {normalized}"


def test_mode_constants_exposed():
    assert AGI.PYTHON_MODE == 1
    assert AGI.CYTHON_MODE == 2
    assert AGI.DASK_MODE == 4
    assert AGI.RAPIDS_MODE == 16


def test_is_local():
    # Test that known local IP addresses are detected as local.
    assert AgiEnv.is_local("127.0.0.1"), "127.0.0.1 should be local."
    # Use a public IP that is likely not local.
    assert not AgiEnv.is_local("8.8.8.8"), "8.8.8.8 should not be considered local."


@pytest.mark.asyncio
async def test_agi_run_delegates_to_benchmark_with_sorted_mode_list(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    captured = {}

    async def _fake_benchmark(env_, scheduler, workers, verbose, mode_range, rapids_enabled, **args):
        captured["env"] = env_
        captured["scheduler"] = scheduler
        captured["workers"] = workers
        captured["verbose"] = verbose
        captured["mode_range"] = list(mode_range)
        captured["rapids_enabled"] = rapids_enabled
        captured["args"] = dict(args)
        return {"status": "bench"}

    monkeypatch.setattr(AGI, "_benchmark", staticmethod(_fake_benchmark))

    result = await AGI.run(
        env,
        scheduler="127.0.0.1",
        workers={"127.0.0.1": 1},
        verbose=2,
        mode=[5, 1, 3],
        rapids_enabled=True,
        example_flag=True,
    )

    assert result == {"status": "bench"}
    assert captured["env"] is env
    assert captured["scheduler"] == "127.0.0.1"
    assert captured["workers"] == {"127.0.0.1": 1}
    assert captured["verbose"] == 2
    assert captured["mode_range"] == [1, 3, 5]
    assert captured["rapids_enabled"] is True
    assert captured["args"]["example_flag"] is True


@pytest.mark.asyncio
async def test_benchmark_records_runs_and_writes_output(monkeypatch, tmp_path):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    env.benchmark = tmp_path / "benchmark.json"
    env.benchmark.write_text("stale", encoding="utf-8")

    async def _fake_run(_env, scheduler=None, workers=None, mode=None, **_args):
        return f"mode{mode} {float(mode) + 1.0}"

    async def _fake_bench_dask(_env, _scheduler, _workers, _modes, _mask, runs, **_args):
        runs[4] = {"mode": "mode4", "timing": "4 seconds", "seconds": 4.0}

    monkeypatch.setattr(BaseWorker, "_is_cython_installed", staticmethod(lambda _env: True))
    monkeypatch.setattr(AGI, "run", staticmethod(_fake_run))
    monkeypatch.setattr(AGI, "_benchmark_dask_modes", staticmethod(_fake_bench_dask))

    payload = await AGI._benchmark(
        env,
        scheduler="127.0.0.1",
        workers={"127.0.0.1": 1},
        mode_range=[0, 1, 4],
        rapids_enabled=False,
    )
    data = json.loads(payload)
    assert set(data.keys()) == {"0", "1", "4"}
    assert data["0"]["order"] == 1
    assert data["1"]["order"] == 2
    assert data["4"]["order"] == 3
    assert AGI._best_mode[env.target]["mode"] == data["0"]["mode"]
    assert env.benchmark.exists()
    assert AGI._mode_auto is False


@pytest.mark.asyncio
async def test_benchmark_calls_install_when_cython_missing(monkeypatch, tmp_path):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    env.benchmark = tmp_path / "benchmark.json"
    called = {"install": 0}

    async def _fake_install(*_args, **_kwargs):
        called["install"] += 1
        return None

    async def _fake_run(_env, scheduler=None, workers=None, mode=None, **_args):
        return f"mode{mode} 1.0"

    monkeypatch.setattr(BaseWorker, "_is_cython_installed", staticmethod(lambda _env: False))
    monkeypatch.setattr(AGI, "install", staticmethod(_fake_install))
    monkeypatch.setattr(AGI, "run", staticmethod(_fake_run))
    monkeypatch.setattr(AGI, "_benchmark_dask_modes", staticmethod(lambda *_a, **_k: None))

    payload = await AGI._benchmark(env, mode_range=[0], rapids_enabled=False)
    assert json.loads(payload)["0"]["mode"].startswith("mode")
    assert called["install"] == 1


@pytest.mark.asyncio
async def test_benchmark_raises_on_invalid_run_format(monkeypatch, tmp_path):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    env.benchmark = tmp_path / "benchmark.json"

    async def _bad_run(*_args, **_kwargs):
        return "invalid-format"

    monkeypatch.setattr(BaseWorker, "_is_cython_installed", staticmethod(lambda _env: True))
    monkeypatch.setattr(AGI, "run", staticmethod(_bad_run))
    monkeypatch.setattr(AGI, "_benchmark_dask_modes", staticmethod(lambda *_a, **_k: None))

    with pytest.raises(ValueError, match="Unexpected run format"):
        await AGI._benchmark(env, mode_range=[0], rapids_enabled=False)


@pytest.mark.asyncio
async def test_benchmark_raises_when_no_runs(monkeypatch, tmp_path):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    env.benchmark = tmp_path / "benchmark.json"

    async def _non_str_run(*_args, **_kwargs):
        return {"status": "not-a-string"}

    monkeypatch.setattr(BaseWorker, "_is_cython_installed", staticmethod(lambda _env: True))
    monkeypatch.setattr(AGI, "run", staticmethod(_non_str_run))
    monkeypatch.setattr(AGI, "_benchmark_dask_modes", staticmethod(lambda *_a, **_k: None))

    with pytest.raises(RuntimeError, match="No ordered runs available"):
        await AGI._benchmark(env, mode_range=[0], rapids_enabled=False)


@pytest.mark.asyncio
async def test_benchmark_dask_modes_records_runs_and_stops(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    calls = {"start": 0, "stop": 0, "update": 0}
    runs = {}
    sequence = iter(["m4 2.0", "m5 1.0"])

    async def _start(_scheduler):
        calls["start"] += 1
        return True

    async def _stop():
        calls["stop"] += 1

    async def _distribute():
        return next(sequence)

    monkeypatch.setattr(AGI, "_start", staticmethod(_start))
    monkeypatch.setattr(AGI, "_stop", staticmethod(_stop))
    monkeypatch.setattr(AGI, "_distribute", staticmethod(_distribute))
    monkeypatch.setattr(
        AGI,
        "_update_capacity",
        staticmethod(lambda: calls.__setitem__("update", calls["update"] + 1)),
    )

    await AGI._benchmark_dask_modes(
        env,
        scheduler="127.0.0.1",
        workers={"127.0.0.1": 1},
        mode_range=[4, 5],
        rapids_mode_mask=AGI._RAPIDS_RESET,
        runs=runs,
    )
    assert calls["start"] == 1
    assert calls["stop"] == 1
    assert calls["update"] == 2
    assert runs[4]["seconds"] == 2.0
    assert runs[5]["seconds"] == 1.0


@pytest.mark.asyncio
async def test_benchmark_dask_modes_stops_even_when_run_format_is_invalid(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    calls = {"stop": 0}

    async def _start(_scheduler):
        return True

    async def _stop():
        calls["stop"] += 1

    async def _distribute():
        return "bad-run"

    monkeypatch.setattr(AGI, "_start", staticmethod(_start))
    monkeypatch.setattr(AGI, "_stop", staticmethod(_stop))
    monkeypatch.setattr(AGI, "_distribute", staticmethod(_distribute))
    monkeypatch.setattr(AGI, "_update_capacity", staticmethod(lambda: None))

    with pytest.raises(ValueError, match="Unexpected run format"):
        await AGI._benchmark_dask_modes(
            env,
            scheduler="127.0.0.1",
            workers={"127.0.0.1": 1},
            mode_range=[4],
            rapids_mode_mask=AGI._RAPIDS_RESET,
            runs={},
        )
    assert calls["stop"] == 1


@pytest.mark.asyncio
async def test_agi_run_uses_default_workers_in_benchmark(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=1)
    captured = {}

    async def _fake_benchmark(_env, _scheduler, workers, _verbose, mode_range, _rapids_enabled, **_args):
        captured["workers"] = workers
        captured["modes"] = list(mode_range)
        return {"status": "bench-default-workers"}

    monkeypatch.setattr(AGI, "_benchmark", staticmethod(_fake_benchmark))

    result = await AGI.run(
        env,
        scheduler="127.0.0.1",
        workers=None,
        mode=None,
    )
    assert result == {"status": "bench-default-workers"}
    assert captured["workers"] == agi_distributor_module._workers_default
    assert captured["modes"] == list(range(8))


@pytest.mark.asyncio
async def test_agi_run_rejects_invalid_workers_type():
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    with pytest.raises(ValueError, match=r"workers must be a dict"):
        await AGI.run(
            env,
            workers=["127.0.0.1"],  # type: ignore[arg-type]
            mode=AGI.DASK_MODE,
        )


@pytest.mark.asyncio
async def test_agi_run_rejects_invalid_mode_string():
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    with pytest.raises(ValueError, match=r"parameter <mode> must only contain the letters"):
        await AGI.run(
            env,
            workers={"127.0.0.1": 1},
            mode="dcx",
        )


@pytest.mark.asyncio
async def test_agi_run_rejects_invalid_mode_type():
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    with pytest.raises(ValueError, match=r"parameter <mode> must be an int"):
        await AGI.run(
            env,
            workers={"127.0.0.1": 1},
            mode={"bad": "type"},
        )


@pytest.mark.asyncio
async def test_agi_run_rejects_unsupported_base_worker_class(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    env.base_worker_cls = "UnknownWorker"
    monkeypatch.setattr(AGI, "_train_capacity", staticmethod(lambda *_args, **_kwargs: None))

    with pytest.raises(ValueError, match=r"Unsupported base worker class"):
        await AGI.run(
            env,
            workers={"127.0.0.1": 1},
            mode=AGI.DASK_MODE,
        )


@pytest.mark.asyncio
async def test_agi_run_mode_string_valid_path_calls_mode2int_and_main(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    env.base_worker_cls = "PandasWorker"
    called = {"mode2int": None, "main": None}

    def _mode2int(mode):
        called["mode2int"] = mode
        return 5

    async def _fake_main(scheduler):
        called["main"] = scheduler
        return {"status": "ok"}

    monkeypatch.setattr(env, "mode2int", _mode2int)
    monkeypatch.setattr(AGI, "_main", staticmethod(_fake_main))
    monkeypatch.setattr(AGI, "_train_capacity", staticmethod(lambda *_args, **_kwargs: None))

    result = await AGI.run(
        env,
        scheduler="127.0.0.1",
        workers={"127.0.0.1": 1},
        mode="dc",
    )
    assert result == {"status": "ok"}
    assert called["mode2int"] == "dc"
    assert called["main"] == "127.0.0.1"


@pytest.mark.asyncio
async def test_agi_run_mode_zero_sets_run_type(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    env.base_worker_cls = "PandasWorker"

    async def _fake_main(_scheduler):
        return {"status": "ok"}

    monkeypatch.setattr(AGI, "_main", staticmethod(_fake_main))
    monkeypatch.setattr(AGI, "_train_capacity", staticmethod(lambda *_args, **_kwargs: None))

    result = await AGI.run(
        env,
        scheduler="127.0.0.1",
        workers={"127.0.0.1": 1},
        mode=0,
    )
    assert result == {"status": "ok"}
    assert AGI._run_type == "run --no-sync"


@pytest.mark.asyncio
async def test_agi_run_trains_capacity_when_model_is_missing(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    env.base_worker_cls = "PandasWorker"
    called = {"train": 0}

    async def _fake_main(_scheduler):
        return {"status": "ok"}

    monkeypatch.setattr(Path, "is_file", lambda self: False, raising=False)
    monkeypatch.setattr(AGI, "_main", staticmethod(_fake_main))
    monkeypatch.setattr(
        AGI,
        "_train_capacity",
        staticmethod(lambda *_args, **_kwargs: called.__setitem__("train", called["train"] + 1)),
    )

    result = await AGI.run(
        env,
        scheduler="127.0.0.1",
        workers={"127.0.0.1": 1},
        mode=AGI.DASK_MODE,
    )
    assert result == {"status": "ok"}
    assert called["train"] == 1


@pytest.mark.asyncio
async def test_agi_run_returns_none_on_process_error(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    env.base_worker_cls = "PandasWorker"

    class _FakeProcessError(Exception):
        pass

    async def _fake_main(_scheduler):
        raise _FakeProcessError("process failed")

    monkeypatch.setattr(agi_distributor_module, "ProcessError", _FakeProcessError)
    monkeypatch.setattr(AGI, "_main", staticmethod(_fake_main))
    monkeypatch.setattr(AGI, "_train_capacity", staticmethod(lambda *_args, **_kwargs: None))

    result = await AGI.run(
        env,
        scheduler="127.0.0.1",
        workers={"127.0.0.1": 1},
        mode=AGI.DASK_MODE,
    )
    assert result is None


@pytest.mark.asyncio
async def test_agi_run_returns_connection_error_payload(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    env.base_worker_cls = "PandasWorker"
    monkeypatch.setattr(AGI, "_train_capacity", staticmethod(lambda *_args, **_kwargs: None))

    async def _boom(_scheduler):
        raise ConnectionError("scheduler unavailable")

    monkeypatch.setattr(AGI, "_main", staticmethod(_boom))
    result = await AGI.run(
        env,
        workers={"127.0.0.1": 1},
        mode=AGI.DASK_MODE,
    )
    assert result["status"] == "error"
    assert result["kind"] == "connection"
    assert "scheduler unavailable" in result["message"]


@pytest.mark.asyncio
async def test_agi_run_returns_none_on_module_not_found(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    env.base_worker_cls = "PandasWorker"
    monkeypatch.setattr(AGI, "_train_capacity", staticmethod(lambda *_args, **_kwargs: None))

    async def _missing(_scheduler):
        raise ModuleNotFoundError("missing module")

    monkeypatch.setattr(AGI, "_main", staticmethod(_missing))
    assert await AGI.run(env, workers={"127.0.0.1": 1}, mode=AGI.DASK_MODE) is None


@pytest.mark.asyncio
async def test_agi_run_reraises_unhandled_exception(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    env.base_worker_cls = "PandasWorker"
    monkeypatch.setattr(AGI, "_train_capacity", staticmethod(lambda *_args, **_kwargs: None))

    async def _unexpected(_scheduler):
        raise RuntimeError("unexpected failure")

    monkeypatch.setattr(AGI, "_main", staticmethod(_unexpected))
    with pytest.raises(RuntimeError, match="unexpected failure"):
        await AGI.run(env, workers={"127.0.0.1": 1}, mode=AGI.DASK_MODE)


@pytest.mark.asyncio
async def test_agi_run_logs_debug_traceback_when_debug_enabled(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    env.base_worker_cls = "PandasWorker"
    monkeypatch.setattr(AGI, "_train_capacity", staticmethod(lambda *_args, **_kwargs: None))

    class _FakeLogger:
        def __init__(self):
            self.debug_calls = 0

        def info(self, *args, **kwargs):
            return None

        def error(self, *args, **kwargs):
            return None

        def warning(self, *args, **kwargs):
            return None

        def isEnabledFor(self, _level):
            return True

        def debug(self, *args, **kwargs):
            self.debug_calls += 1

    async def _unexpected(_scheduler):
        raise RuntimeError("boom-debug")

    fake_logger = _FakeLogger()
    monkeypatch.setattr(AGI, "_main", staticmethod(_unexpected))
    monkeypatch.setattr(agi_distributor_module, "logger", fake_logger)

    with pytest.raises(RuntimeError, match="boom-debug"):
        await AGI.run(env, workers={"127.0.0.1": 1}, mode=AGI.DASK_MODE)
    assert fake_logger.debug_calls >= 1


@pytest.mark.asyncio
async def test_agi_run_requires_base_worker_cls():
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    env.base_worker_cls = None
    with pytest.raises(ValueError, match=r"Missing .* definition; expected"):
        await AGI.run(
            env,
            scheduler="127.0.0.1",
            workers={"127.0.0.1": 1},
            verbose=0,
            mode=AGI.DASK_MODE,
        )


def test_exec_bg_raises_when_background_job_fails():
    class _Jobs:
        def __init__(self):
            self.new_calls = []

        def new(self, cmd, cwd=None):
            self.new_calls.append((cmd, cwd))

        def result(self, _index):
            return False

    AGI._jobs = _Jobs()
    with pytest.raises(RuntimeError, match="running echo test"):
        AGI._exec_bg("echo test", "/tmp")


def test_exec_bg_uses_launched_job_id():
    seen = {}

    class _Job:
        def __init__(self, num):
            self.num = num

    class _Jobs:
        def new(self, cmd, cwd=None):
            seen["new"] = (cmd, cwd)
            return _Job(7)

        def result(self, index):
            seen["result"] = index
            return True

    AGI._jobs = _Jobs()
    AGI._exec_bg("echo test", "/tmp")

    assert seen["new"] == ("echo test", "/tmp")
    assert seen["result"] == 7


def test_background_job_manager_uses_subprocess_and_real_directories_only(monkeypatch, tmp_path):
    calls = []

    class _Proc:
        def poll(self):
            return None

    def _fake_popen(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return _Proc()

    monkeypatch.setattr(agi_distributor_module.subprocess, "Popen", _fake_popen)
    jobs = agi_distributor_module.bg.BackgroundJobManager()

    first = jobs.new("echo test", cwd="flight_trajectory_project")
    second = jobs.new("echo test 2", cwd=tmp_path)

    assert first.num == 0
    assert second.num == 1
    assert calls[0][0] == "echo test"
    assert calls[0][1]["shell"] is True
    assert calls[0][1]["cwd"] is None
    assert calls[0][1]["start_new_session"] is True
    assert calls[1][1]["cwd"] == str(tmp_path)
    assert jobs.result(second.num) is second.result


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
        envars={},
        uv_worker="uv",
        is_source_env=False,
        app="demo_app",
        target_worker="demo_worker",
        post_install_rel="demo.post_install",
        verbose=0,
    )
    AGI._rapids_enabled = False
    AGI._workers_data_path = None
    ssh_calls = []
    send_calls = []

    async def _fake_exec_ssh(_ip, cmd):
        ssh_calls.append(cmd)
        return "ok"

    async def _fake_send(_env, ip, files, remote_path, user=None, password=None):
        send_calls.append((ip, [Path(f).name for f in files], str(remote_path)))

    async def _fake_send_file(_env, ip, local_path, remote_path, user=None, password=None):
        send_calls.append((ip, [Path(local_path).name], str(remote_path.parent)))

    monkeypatch.setattr(AGI, "exec_ssh", staticmethod(_fake_exec_ssh))
    monkeypatch.setattr(AGI, "send_files", staticmethod(_fake_send))
    monkeypatch.setattr(AGI, "send_file", staticmethod(_fake_send_file))

    await AGI._deploy_remote_worker("10.0.0.2", env, Path("worker_env"), " --extra pandas-worker")

    assert any("demo_worker-0.0.1.egg" in names for _, names, _ in send_calls)
    assert any("ensurepip" in cmd for cmd in ssh_calls)
    assert any("python -m demo.post_install" in cmd for cmd in ssh_calls)


@pytest.mark.asyncio
async def test_calibration_computes_normalized_capacity(monkeypatch):
    class _Predictor:
        def predict(self, _data):
            return [4.0]

    class _Client:
        def run(self, *_args, **_kwargs):
            return {
                "tcp://127.0.0.1:8787": {
                    "ram_total": [10.0],
                    "ram_available": [5.0],
                    "cpu_count": [4.0],
                    "cpu_frequency": [2.5],
                    "network_speed": [1.0],
                }
            }

        def gather(self, payload):
            return payload

    AGI._dask_client = _Client()
    AGI._dask_workers = ["127.0.0.1:8787"]
    AGI._workers = {"127.0.0.1": 1}
    AGI._capacity_predictor = _Predictor()

    await AGI._calibration()

    assert AGI.workers_info["127.0.0.1:8787"]["label"] == 4.0
    assert AGI._capacity["127.0.0.1:8787"] == 1.0


@pytest.mark.asyncio
async def test_calibration_fallback_when_predictor_has_no_data():
    class _Client:
        def run(self, *_args, **_kwargs):
            return {}

        def gather(self, payload):
            return payload

    AGI._dask_client = _Client()
    AGI._dask_workers = ["127.0.0.1:8787"]
    AGI._workers = {"127.0.0.1": 1}
    AGI._capacity_predictor = SimpleNamespace(predict=lambda _x: [1.0])

    await AGI._calibration()
    assert AGI._capacity["127.0.0.1:8787"] == 1.0


def test_update_capacity_success_and_guard_paths(tmp_path, monkeypatch):
    AGI._workers = {"127.0.0.1": 1}
    AGI.workers_info = {
        "127.0.0.1:8787": {
            "nb_workers": 1,
            "ram_total": 10.0,
            "ram_available": 5.0,
            "cpu_count": 4.0,
            "cpu_frequency": 2.5,
            "network_speed": 1.0,
            "label": 1.0,
        }
    }
    AGI._run_time = ["error-line"]
    AGI._capacity_data_file = str(tmp_path / "capacity.csv")
    AGI.env = SimpleNamespace(home_abs=str(tmp_path))
    train_calls = {"count": 0}
    monkeypatch.setattr(
        AGI,
        "_train_capacity",
        staticmethod(lambda _path: train_calls.__setitem__("count", train_calls["count"] + 1)),
    )

    AGI._update_capacity()
    assert train_calls["count"] == 0

    AGI._run_time = [{"127.0.0.1:8787": 2.0}]
    AGI._update_capacity()
    assert train_calls["count"] == 1
    assert Path(AGI._capacity_data_file).exists()

    AGI.workers_info["127.0.0.1:8787"]["label"] = 0.0
    AGI._run_time = [{"127.0.0.1:8787": 2.0}]
    with pytest.raises(RuntimeError, match="workers BaseWorker.do_works failed"):
        AGI._update_capacity()


def test_train_capacity_missing_and_success(tmp_path):
    AGI._capacity_data_file = "capacity_data.csv"
    AGI._capacity_model_file = "capacity_model.pkl"

    with pytest.raises(FileNotFoundError):
        AGI._train_capacity(tmp_path)

    csv_path = tmp_path / AGI._capacity_data_file
    rows = [
        "nb_workers,ram_total,ram_available,cpu_count,cpu_frequency,network_speed,label",
        "skip,skip,skip,skip,skip,skip,skip",
        "skip,skip,skip,skip,skip,skip,skip",
        "1,32,16,8,2.5,100,1.0",
        "1,32,15,8,2.4,95,0.9",
        "1,32,14,8,2.3,90,0.8",
        "2,64,30,16,2.6,120,1.4",
        "2,64,28,16,2.5,115,1.3",
        "2,64,26,16,2.4,110,1.2",
        "3,96,40,24,2.7,140,1.8",
        "3,96,38,24,2.6,135,1.7",
    ]
    csv_path.write_text("\n".join(rows), encoding="utf-8")

    AGI._train_capacity(tmp_path)

    model_path = tmp_path / AGI._capacity_model_file
    assert model_path.exists()
    assert hasattr(AGI._capacity_predictor, "predict")


@pytest.mark.asyncio
async def test_deploy_remote_worker_source_env_with_rapids(monkeypatch, tmp_path):
    dist_abs = tmp_path / "dist"
    dist_abs.mkdir(parents=True, exist_ok=True)
    (dist_abs / "demo_worker-0.0.1.egg").write_text("egg", encoding="utf-8")
    agi_env = tmp_path / "agi_env"
    agi_node = tmp_path / "agi_node"
    for p, name in ((agi_env, "agi_env"), (agi_node, "agi_node")):
        (p / "dist").mkdir(parents=True, exist_ok=True)
        (p / "dist" / f"{name}-0.0.1-py3-none-any.whl").write_text("whl", encoding="utf-8")

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
        verbose=2,
    )
    AGI._rapids_enabled = True
    AGI._workers_data_path = str(tmp_path / "share")
    sent = []
    ssh = []

    async def _fake_send(_env, ip, files, remote_path, user=None, password=None):
        payload = []
        for file in files:
            p = Path(file)
            entry = {"name": p.name}
            if p.suffix == ".pth":
                entry["content"] = p.read_text(encoding="utf-8")
            payload.append(entry)
        sent.append((ip, payload, str(remote_path)))

    async def _fake_send_file(_env, ip, local_path, remote_path, user=None, password=None):
        p = Path(local_path)
        payload = [{"name": p.name, "content": p.read_text(encoding="utf-8")}]
        sent.append((ip, payload, str(remote_path.parent)))

    async def _fake_exec(ip, cmd):
        ssh.append((ip, cmd))
        if cmd.strip() == "nvidia-smi":
            return "NVIDIA-SMI"
        return "ok"

    monkeypatch.setattr(AGI, "send_files", staticmethod(_fake_send))
    monkeypatch.setattr(AGI, "send_file", staticmethod(_fake_send_file))
    monkeypatch.setattr(AGI, "exec_ssh", staticmethod(_fake_exec))
    monkeypatch.setattr(agi_distributor_module.AgiEnv, "set_env_var", staticmethod(lambda *_a, **_k: None))

    await AGI._deploy_remote_worker("10.0.0.2", env, Path("wenv"), " --extra pandas-worker")

    assert any(".agilab/.env" in cmd for _, cmd in ssh)
    assert any("nvidia-smi" == cmd for _, cmd in ssh)
    assert any(any(item["name"] == "agi_env-0.0.1-py3-none-any.whl" for item in payload) for _, payload, _ in sent)
    assert any(any(item["name"] == "agi_node-0.0.1-py3-none-any.whl" for item in payload) for _, payload, _ in sent)
    assert any("python -m demo.post_install" in cmd for _, cmd in ssh)
