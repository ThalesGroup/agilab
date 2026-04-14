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


class _FakeFuture:
    def __init__(self, status: str = "pending"):
        self.status = status


class _FakeClient:
    def __init__(self, workers: list[str]):
        self._workers = workers
        self.status = "running"
        self.submissions: list[dict[str, object]] = []

    def submit(self, *args, **kwargs):
        fn = args[0] if args else None
        fn_name = getattr(fn, "__name__", str(fn))
        self.submissions.append(
            {
                "fn": fn_name,
                "args": args[1:],
                "kwargs": kwargs,
            }
        )
        return _FakeFuture()

    def gather(self, futures, errors="raise"):
        if isinstance(futures, list):
            return [None for _ in futures]
        return []

    def scheduler_info(self):
        return {"workers": {f"tcp://{worker}": {} for worker in self._workers}}


def _real_service_stub_new(**_kwargs):
    return {"status": "ready"}


def _real_service_stub_loop(*, poll_interval=None):
    delay = max(float(poll_interval or 0.05), 0.01)
    time.sleep(delay)
    return {"status": "loop-exited"}


def _real_service_stub_break_loop():
    return True


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


def test_hardware_supports_rapids_true_and_false(monkeypatch):
    monkeypatch.setattr(agi_distributor_module.subprocess, "run", lambda *_a, **_k: None)
    assert AGI._hardware_supports_rapids() is True

    monkeypatch.setattr(
        agi_distributor_module.subprocess,
        "run",
        lambda *_a, **_k: (_ for _ in ()).throw(FileNotFoundError("nvidia-smi missing")),
    )
    assert AGI._hardware_supports_rapids() is False


def test_wrap_worker_chunk_handles_non_list_and_out_of_range_index():
    assert AGI._wrap_worker_chunk("raw-payload", worker_index=0) == "raw-payload"
    wrapped = AGI._wrap_worker_chunk([["a"], ["b"]], worker_index=8)
    assert wrapped["__agi_worker_chunk__"] is True
    assert wrapped["chunk"] == []
    assert wrapped["total_workers"] == 2
    assert wrapped["worker_idx"] == 8


@pytest.mark.asyncio
async def test_service_restart_workers_returns_empty_for_empty_input():
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    restarted = await AGI._service_restart_workers(env, client=_FakeClient([]), workers_to_restart=[])
    assert restarted == []


@pytest.mark.asyncio
async def test_service_restart_workers_restarts_and_tracks_futures(monkeypatch, tmp_path):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    AGI._args = {"sample": 1}
    AGI._mode = AGI.DASK_MODE
    AGI._service_poll_interval = 0.2
    AGI._service_queue_root = None
    AGI._service_workers = []
    AGI._service_futures = {}

    class _RestartClient:
        def __init__(self):
            self.calls = []
            self._gather_calls = 0

        def scheduler_info(self):
            return {"workers": {"tcp://127.0.0.1:8787": {}}}

        def submit(self, fn, *args, **kwargs):
            self.calls.append(getattr(fn, "__name__", str(fn)))
            return _FakeFuture(status="running")

        def gather(self, futures, errors="raise"):
            self._gather_calls += 1
            if self._gather_calls == 1:
                raise RuntimeError("ignore break gather failure")
            return [None for _ in futures]

    client = _RestartClient()

    def _fake_init_queue(_env):
        return AGI._service_apply_queue_root(tmp_path / "queue", create=True)

    monkeypatch.setattr(AGI, "_init_service_queue", staticmethod(_fake_init_queue))

    restarted = await AGI._service_restart_workers(env, client, ["127.0.0.1:8787"])
    assert restarted == ["127.0.0.1:8787"]
    assert AGI._service_futures["127.0.0.1:8787"].status == "running"
    assert {"break_loop", "_new", "loop"}.issubset(set(client.calls))


@pytest.mark.asyncio
async def test_service_auto_restart_unhealthy_returns_empty_without_workers(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    AGI._service_workers = []

    async def _connected(_client):
        return []

    monkeypatch.setattr(AGI, "_service_connected_workers", staticmethod(_connected))
    result = await AGI._service_auto_restart_unhealthy(env, client=object())
    assert result == {"restarted": [], "reasons": {}}


@pytest.mark.asyncio
async def test_service_auto_restart_unhealthy_restarts_and_persists(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    AGI._service_workers = []
    calls = {"write": 0}

    async def _connected(_client):
        return ["w1"]

    async def _restart(_env, _client, _workers):
        return ["w1"]

    monkeypatch.setattr(AGI, "_service_connected_workers", staticmethod(_connected))
    monkeypatch.setattr(AGI, "_service_unhealthy_workers", staticmethod(lambda _workers: {"w1": "missing-heartbeat"}))
    monkeypatch.setattr(AGI, "_service_restart_workers", staticmethod(_restart))
    monkeypatch.setattr(AGI, "_service_state_payload", staticmethod(lambda _env: {"schema": "state"}))
    monkeypatch.setattr(
        AGI,
        "_service_write_state",
        staticmethod(lambda _env, _payload: calls.__setitem__("write", calls["write"] + 1)),
    )

    result = await AGI._service_auto_restart_unhealthy(env, client=object())
    assert result["restarted"] == ["w1"]
    assert result["reasons"]["w1"] == "missing-heartbeat"
    assert calls["write"] == 1


@pytest.mark.asyncio
async def test_service_recover_allow_stale_cleanup_clears_state_on_failure(tmp_path, monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    queue_dir = tmp_path / "service_queue"
    queue_dir.mkdir(parents=True, exist_ok=True)

    AGI._service_write_state(
        env,
        {
            "schema": "agi.service.state.v1",
            "target": env.target,
            "app": env.app,
            "mode": AGI.DASK_MODE,
            "run_type": "run --no-sync",
            "scheduler": "127.0.0.1:8786",
            "workers": {"127.0.0.1": 1},
            "service_workers": ["127.0.0.1:8787"],
            "queue_dir": str(queue_dir),
            "args": {},
        },
    )

    async def _fail_connect(*_args, **_kwargs):
        raise RuntimeError("connect failed")

    monkeypatch.setattr(AGI, "_connect_scheduler_with_retry", staticmethod(_fail_connect))

    recovered = await AGI._service_recover(env, allow_stale_cleanup=True)
    assert recovered is False
    assert AGI._service_read_state(env) is None
    assert AGI._service_queue_root is None
    assert AGI._service_workers == []
    assert AGI._service_futures == {}


@pytest.mark.asyncio
async def test_service_recover_without_stale_cleanup_keeps_state_on_failure(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    state_path = AGI._service_state_path(env)
    AGI._service_write_state(
        env,
        {
            "schema": "agi.service.state.v1",
            "target": env.target,
            "app": env.app,
            "mode": AGI.DASK_MODE,
            "run_type": "run --no-sync",
            "workers": {"127.0.0.1": 1},
            "args": {},
        },
    )

    async def _fail_connect(*_args, **_kwargs):
        raise RuntimeError("connect failed")

    monkeypatch.setattr(AGI, "_connect_scheduler_with_retry", staticmethod(_fail_connect))
    recovered = await AGI._service_recover(env, allow_stale_cleanup=False)
    assert recovered is False
    assert state_path.exists()


@pytest.mark.asyncio
async def test_service_recover_fails_when_no_workers_attached(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    AGI._service_write_state(
        env,
        {
            "schema": "agi.service.state.v1",
            "target": env.target,
            "app": env.app,
            "mode": AGI.DASK_MODE,
            "run_type": "run --no-sync",
            "scheduler": "127.0.0.1:8786",
            "workers": {"127.0.0.1": 1},
            "args": {},
        },
    )

    class _NoWorkerClient:
        status = "running"

        def scheduler_info(self):
            return {"workers": {}}

    async def _connect(*_args, **_kwargs):
        return _NoWorkerClient()

    monkeypatch.setattr(AGI, "_connect_scheduler_with_retry", staticmethod(_connect))
    recovered = await AGI._service_recover(env, allow_stale_cleanup=False)
    assert recovered is False


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


@pytest.mark.asyncio
async def test_agi_serve_status_idle_when_not_started():
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    status = await AGI.serve(env, action="status")
    assert status["status"] == "idle"
    assert status["workers"] == []
    assert status["pending"] == []
    assert status["health"]["schema"] == "agi.service.health.v1"
    assert status["health_path"]
    assert Path(status["health_path"]).exists()


@pytest.mark.asyncio
async def test_agi_serve_rejects_invalid_action():
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    with pytest.raises(ValueError, match=r"action must be"):
        await AGI.serve(env, action="invalid-action")


@pytest.mark.asyncio
async def test_agi_serve_stop_returns_idle_when_nothing_to_stop(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    calls = {"stop": 0, "clean": 0}
    AGI._dask_client = _FakeClient([])
    AGI._jobs = object()
    AGI._service_futures = {}
    AGI._service_workers = []

    async def _recover(_env, allow_stale_cleanup=False):
        return False

    async def _stop():
        calls["stop"] += 1

    monkeypatch.setattr(AGI, "_service_recover", staticmethod(_recover))
    monkeypatch.setattr(AGI, "_stop", staticmethod(_stop))
    monkeypatch.setattr(
        AGI,
        "_clean_job",
        staticmethod(lambda *_a, **_k: calls.__setitem__("clean", calls["clean"] + 1)),
    )

    result = await AGI.serve(env, action="stop", shutdown_on_stop=True)
    assert result["status"] == "idle"
    assert calls["stop"] == 1
    assert calls["clean"] == 1


@pytest.mark.asyncio
async def test_agi_serve_stop_returns_error_when_client_missing(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    AGI._dask_client = None
    AGI._jobs = object()
    AGI._service_futures = {"w1": _FakeFuture("running")}
    AGI._service_workers = ["w1"]
    calls = {"clean": 0}

    monkeypatch.setattr(
        AGI,
        "_clean_job",
        staticmethod(lambda *_a, **_k: calls.__setitem__("clean", calls["clean"] + 1)),
    )

    result = await AGI.serve(env, action="stop", shutdown_on_stop=False)
    assert result["status"] == "error"
    assert "w1" in result["pending"]
    assert calls["clean"] == 1


@pytest.mark.asyncio
async def test_agi_serve_stop_handles_empty_targets_and_shuts_down(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    AGI._dask_client = _FakeClient([])
    AGI._service_futures = {}
    AGI._service_workers = []
    calls = {"stop": 0}

    async def _recover(_env, allow_stale_cleanup=False):
        AGI._dask_client = _FakeClient([])
        return True

    async def _connected(_client):
        return []

    async def _stop():
        calls["stop"] += 1

    monkeypatch.setattr(AGI, "_service_recover", staticmethod(_recover))
    monkeypatch.setattr(AGI, "_service_connected_workers", staticmethod(_connected))
    monkeypatch.setattr(AGI, "_stop", staticmethod(_stop))

    result = await AGI.serve(env, action="stop", shutdown_on_stop=True)
    assert result["status"] == "idle"
    assert calls["stop"] == 1


@pytest.mark.asyncio
async def test_agi_serve_health_action_writes_json(tmp_path):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    health_path = tmp_path / "export" / "health.json"
    payload = await AGI.serve(env, action="health", health_output_path=health_path)
    assert payload["schema"] == "agi.service.health.v1"
    assert payload["status"] == "idle"
    assert payload["path"] == str(health_path)
    assert health_path.exists()
    written = json.loads(health_path.read_text(encoding="utf-8"))
    assert written["schema"] == "agi.service.health.v1"
    assert written["status"] == "idle"


@pytest.mark.asyncio
async def test_agi_serve_start_status_stop_supports_agidataworker(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    env.base_worker_cls = "AgiDataWorker"
    fake_client = _FakeClient(["127.0.0.1:8787"])

    async def _fake_start(_scheduler):
        AGI._dask_client = fake_client

    async def _fake_sync():
        return None

    async def _fake_stop():
        return None

    monkeypatch.setattr(AGI, "_start", staticmethod(_fake_start))
    monkeypatch.setattr(AGI, "_sync", staticmethod(_fake_sync))
    monkeypatch.setattr(AGI, "_stop", staticmethod(_fake_stop))
    monkeypatch.setattr(
        agi_distributor_module,
        "wait",
        lambda futures, **_kwargs: (set(futures), set()),
    )

    started = await AGI.serve(
        env,
        scheduler="127.0.0.1",
        workers={"127.0.0.1": 1},
        mode=AGI.DASK_MODE,
        action="start",
    )
    assert started["status"] == "running"
    assert AGI.install_worker_group == ["pandas-worker"]
    assert started["health"]["schema"] == "agi.service.health.v1"
    assert Path(started["health_path"]).exists()

    status = await AGI.serve(env, action="status")
    assert status["status"] == "running"
    assert status["workers"] == ["127.0.0.1:8787"]
    assert status["health"]["status"] == "running"
    assert Path(status["health_path"]).exists()

    stopped = await AGI.serve(env, action="stop", shutdown_on_stop=False)
    assert stopped["status"] == "stopped"
    assert stopped["health"]["status"] == "stopped"
    assert Path(stopped["health_path"]).exists()


@pytest.mark.asyncio
async def test_agi_serve_start_reuses_recovered_service(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    AGI._service_workers = ["127.0.0.1:8787"]
    AGI._dask_client = _FakeClient(["127.0.0.1:8787"])

    async def _recover(_env, allow_stale_cleanup=False):
        return True

    async def _auto_restart(_env, _client):
        return {"restarted": ["127.0.0.1:8787"], "reasons": {"127.0.0.1:8787": "stale-heartbeat"}}

    monkeypatch.setattr(AGI, "_service_recover", staticmethod(_recover))
    monkeypatch.setattr(AGI, "_service_auto_restart_unhealthy", staticmethod(_auto_restart))
    monkeypatch.setattr(AGI, "_service_cleanup_artifacts", staticmethod(lambda: {"done": 0, "failed": 0, "heartbeats": 0}))
    monkeypatch.setattr(AGI, "_service_worker_health", staticmethod(lambda workers: [{"worker": w, "healthy": True} for w in workers]))
    monkeypatch.setattr(AGI, "_service_queue_counts", staticmethod(lambda: {"pending": 0, "running": 0, "done": 0, "failed": 0}))

    started = await AGI.serve(env, action="start", mode=AGI.DASK_MODE)
    assert started["status"] == "running"
    assert started["recovered"] is True
    assert started["restarted_workers"] == ["127.0.0.1:8787"]


@pytest.mark.asyncio
async def test_agi_serve_start_rejects_invalid_workers_type(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)

    async def _recover(_env, allow_stale_cleanup=False):
        return False

    monkeypatch.setattr(AGI, "_service_recover", staticmethod(_recover))
    with pytest.raises(ValueError, match=r"workers must be a dict"):
        await AGI.serve(env, action="start", workers=["127.0.0.1"], mode=AGI.DASK_MODE)


@pytest.mark.asyncio
async def test_agi_serve_start_rejects_modes_without_dask(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)

    async def _recover(_env, allow_stale_cleanup=False):
        return False

    monkeypatch.setattr(AGI, "_service_recover", staticmethod(_recover))
    with pytest.raises(ValueError, match=r"requires Dask mode"):
        await AGI.serve(env, action="start", workers={"127.0.0.1": 1}, mode=AGI.PYTHON_MODE)


@pytest.mark.asyncio
async def test_agi_serve_start_rejects_invalid_mode_string(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)

    async def _recover(_env, allow_stale_cleanup=False):
        return False

    monkeypatch.setattr(AGI, "_service_recover", staticmethod(_recover))
    with pytest.raises(ValueError, match=r"parameter <mode> must only contain the letters"):
        await AGI.serve(env, action="start", workers={"127.0.0.1": 1}, mode="xyz")


@pytest.mark.asyncio
async def test_agi_serve_start_rejects_invalid_mode_type(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)

    async def _recover(_env, allow_stale_cleanup=False):
        return False

    monkeypatch.setattr(AGI, "_service_recover", staticmethod(_recover))
    with pytest.raises(ValueError, match=r"parameter <mode> must be an int or a string"):
        await AGI.serve(env, action="start", workers={"127.0.0.1": 1}, mode=[AGI.DASK_MODE])  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_agi_serve_start_uses_sync_when_client_already_running(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    env.base_worker_cls = "PandasWorker"
    AGI._dask_client = _FakeClient(["127.0.0.1:8787"])
    calls = {"sync": 0}

    async def _recover(_env, allow_stale_cleanup=False):
        return False

    async def _sync():
        calls["sync"] += 1
        return None

    monkeypatch.setattr(AGI, "_service_recover", staticmethod(_recover))
    monkeypatch.setattr(AGI, "_sync", staticmethod(_sync))

    result = await AGI.serve(
        env,
        action="start",
        workers={"127.0.0.1": 1},
        mode=AGI.DASK_MODE,
        shutdown_on_stop=False,
    )
    assert result["status"] == "running"
    assert calls["sync"] == 1


@pytest.mark.asyncio
async def test_agi_serve_start_raises_when_client_not_obtained(monkeypatch):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    env.base_worker_cls = "PandasWorker"
    AGI._dask_client = None

    async def _recover(_env, allow_stale_cleanup=False):
        return False

    async def _start(_scheduler):
        return True

    monkeypatch.setattr(AGI, "_service_recover", staticmethod(_recover))
    monkeypatch.setattr(AGI, "_start", staticmethod(_start))

    with pytest.raises(RuntimeError, match=r"Failed to obtain Dask client"):
        await AGI.serve(env, action="start", workers={"127.0.0.1": 1}, mode=AGI.DASK_MODE)


@pytest.mark.asyncio
async def test_agi_serve_rejects_unsupported_base_worker():
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    env.base_worker_cls = "UnknownWorker"
    with pytest.raises(ValueError, match=r"Unsupported base worker class"):
        await AGI.serve(
            env,
            workers={"127.0.0.1": 1},
            mode=AGI.DASK_MODE,
            action="start",
        )


@pytest.mark.asyncio
async def test_agi_submit_requires_running_service():
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    with pytest.raises(RuntimeError, match=r"Service is not running"):
        await AGI.submit(env, work_plan=[], work_plan_metadata=[])


@pytest.mark.asyncio
async def test_agi_submit_requires_env_when_not_initialized():
    AGI.env = None
    with pytest.raises(ValueError, match=r"env is required"):
        await AGI.submit(env=None, work_plan=[], work_plan_metadata=[])


@pytest.mark.asyncio
async def test_agi_submit_fails_when_dask_client_is_unavailable():
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    AGI._service_futures = {"w1": _FakeFuture("running")}
    AGI._service_workers = ["w1"]
    AGI._dask_client = None
    with pytest.raises(RuntimeError, match=r"Dask client is unavailable"):
        await AGI.submit(env, work_plan=[["step"]], work_plan_metadata=[[{}]])


@pytest.mark.asyncio
async def test_agi_submit_rejects_invalid_workers_type_when_running(tmp_path):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    AGI._service_futures = {"w1": _FakeFuture("running")}
    AGI._service_workers = ["w1"]
    AGI._dask_client = _FakeClient(["127.0.0.1:8787"])
    AGI._service_apply_queue_root(tmp_path / "queue", create=True)
    with pytest.raises(ValueError, match=r"workers must be a dict"):
        await AGI.submit(
            env,
            workers=["127.0.0.1"],  # type: ignore[arg-type]
            work_plan=[["step"]],
            work_plan_metadata=[[{}]],
        )


@pytest.mark.asyncio
async def test_agi_submit_builds_distribution_when_plan_missing(monkeypatch, tmp_path):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    AGI._service_futures = {"w1": _FakeFuture("running")}
    AGI._service_workers = ["w1"]
    AGI._dask_client = _FakeClient(["127.0.0.1:8787"])
    AGI._workers = {"127.0.0.1": 1}
    AGI._args = {"alpha": 1}
    AGI._service_apply_queue_root(tmp_path / "queue", create=True)

    async def _do_distrib(_env, _workers, _args):
        return {"127.0.0.1": 1}, [["gen-step"]], [[{"auto": True}]]

    monkeypatch.setattr(agi_distributor_module.WorkDispatcher, "_do_distrib", staticmethod(_do_distrib))

    result = await AGI.submit(env, work_plan=None, work_plan_metadata=None, task_name="auto-plan")
    assert result["status"] == "queued"
    assert len(result["queued_files"]) == 1


@pytest.mark.asyncio
async def test_agi_submit_queues_tasks_for_service_workers(monkeypatch, tmp_path):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    env.base_worker_cls = "AgiDataWorker"
    fake_client = _FakeClient(["127.0.0.1:8787"])

    async def _fake_start(_scheduler):
        AGI._dask_client = fake_client

    async def _fake_sync():
        return None

    async def _fake_stop():
        return None

    monkeypatch.setattr(AGI, "_start", staticmethod(_fake_start))
    monkeypatch.setattr(AGI, "_sync", staticmethod(_fake_sync))
    monkeypatch.setattr(AGI, "_stop", staticmethod(_fake_stop))
    monkeypatch.setattr(
        agi_distributor_module,
        "wait",
        lambda futures, **_kwargs: (set(futures), set()),
    )

    await AGI.serve(
        env,
        scheduler="127.0.0.1",
        workers={"127.0.0.1": 1},
        mode=AGI.DASK_MODE,
        action="start",
        service_queue_dir=tmp_path / "service_queue",
    )

    result = await AGI.submit(
        env,
        work_plan=[["mock-step"]],
        work_plan_metadata=[[{"step": 1}]],
        task_name="test-batch",
    )
    assert result["status"] == "queued"
    assert len(result["queued_files"]) == 1

    queued_file = Path(result["queued_files"][0])
    assert queued_file.exists()
    with open(queued_file, "rb") as stream:
        payload = pickle.load(stream)
    assert payload["task_name"] == "test-batch"
    assert payload["worker_idx"] == 0
    assert payload["worker"] == "127.0.0.1:8787"

    stopped = await AGI.serve(env, action="stop", shutdown_on_stop=False)
    assert stopped["status"] == "stopped"


@pytest.mark.asyncio
async def test_agi_serve_status_recovers_persistent_state(monkeypatch, tmp_path):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    queue_dir = tmp_path / "service_queue"
    for name in ("pending", "running", "done", "failed"):
        (queue_dir / name).mkdir(parents=True, exist_ok=True)

    AGI._service_write_state(
        env,
        {
            "schema": "agi.service.state.v1",
            "target": env.target,
            "app": env.app,
            "mode": AGI.DASK_MODE,
            "run_type": "run --no-sync",
            "scheduler": "127.0.0.1:8786",
            "scheduler_ip": "127.0.0.1",
            "scheduler_port": 8786,
            "workers": {"127.0.0.1": 1},
            "service_workers": ["127.0.0.1:8787"],
            "queue_dir": str(queue_dir),
            "args": {},
            "poll_interval": 1.0,
            "stop_timeout": 30.0,
            "shutdown_on_stop": True,
        },
    )

    fake_client = _FakeClient(["127.0.0.1:8787"])

    async def _fake_connect(*_args, **_kwargs):
        return fake_client

    monkeypatch.setattr(AGI, "_connect_scheduler_with_retry", staticmethod(_fake_connect))

    status = await AGI.serve(env, action="status")
    assert status["status"] == "running"
    assert status["workers"] == ["127.0.0.1:8787"]
    assert status["queue_dir"] == str(queue_dir)


@pytest.mark.asyncio
async def test_agi_submit_recovers_persistent_state(monkeypatch, tmp_path):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    queue_dir = tmp_path / "service_queue"
    for name in ("pending", "running", "done", "failed"):
        (queue_dir / name).mkdir(parents=True, exist_ok=True)

    AGI._service_write_state(
        env,
        {
            "schema": "agi.service.state.v1",
            "target": env.target,
            "app": env.app,
            "mode": AGI.DASK_MODE,
            "run_type": "run --no-sync",
            "scheduler": "127.0.0.1:8786",
            "scheduler_ip": "127.0.0.1",
            "scheduler_port": 8786,
            "workers": {"127.0.0.1": 1},
            "service_workers": ["127.0.0.1:8787"],
            "queue_dir": str(queue_dir),
            "args": {},
            "poll_interval": 1.0,
            "stop_timeout": 30.0,
            "shutdown_on_stop": True,
        },
    )

    fake_client = _FakeClient(["127.0.0.1:8787"])

    async def _fake_connect(*_args, **_kwargs):
        return fake_client

    monkeypatch.setattr(AGI, "_connect_scheduler_with_retry", staticmethod(_fake_connect))

    result = await AGI.submit(
        env,
        work_plan=[["recovered-step"]],
        work_plan_metadata=[[{"meta": "ok"}]],
        task_name="recovered-batch",
    )

    assert result["status"] == "queued"
    assert len(result["queued_files"]) == 1
    queued_file = Path(result["queued_files"][0])
    assert queued_file.exists()


@pytest.mark.asyncio
async def test_agi_status_auto_restarts_stale_heartbeat(monkeypatch, tmp_path):
    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    queue_dir = tmp_path / "service_queue"
    for name in ("pending", "running", "done", "failed", "heartbeats"):
        (queue_dir / name).mkdir(parents=True, exist_ok=True)

    AGI._service_write_state(
        env,
        {
            "schema": "agi.service.state.v1",
            "target": env.target,
            "app": env.app,
            "mode": AGI.DASK_MODE,
            "run_type": "run --no-sync",
            "scheduler": "127.0.0.1:8786",
            "scheduler_ip": "127.0.0.1",
            "scheduler_port": 8786,
            "workers": {"127.0.0.1": 1},
            "service_workers": ["127.0.0.1:8787"],
            "queue_dir": str(queue_dir),
            "args": {},
            "poll_interval": 0.1,
            "stop_timeout": 30.0,
            "shutdown_on_stop": True,
            "heartbeat_timeout": 0.5,
            "started_at": time.time() - 30.0,
        },
    )

    stale_hb = queue_dir / "heartbeats" / "000-127.0.0.1-8787.json"
    stale_hb.write_text(
        json.dumps(
            {
                "worker_id": 0,
                "worker": "127.0.0.1:8787",
                "timestamp": time.time() - 20.0,
                "state": "running",
            }
        ),
        encoding="utf-8",
    )

    fake_client = _FakeClient(["127.0.0.1:8787"])

    async def _fake_connect(*_args, **_kwargs):
        return fake_client

    monkeypatch.setattr(AGI, "_connect_scheduler_with_retry", staticmethod(_fake_connect))

    status = await AGI.serve(env, action="status")
    assert status["status"] == "running"
    assert status["restarted_workers"] == ["127.0.0.1:8787"]
    assert status["restart_reasons"]["127.0.0.1:8787"].startswith("stale-heartbeat")

    submitted = [entry["fn"] for entry in fake_client.submissions]
    assert "break_loop" in submitted
    assert "_new" in submitted
    assert "loop" in submitted


@pytest.mark.asyncio
async def test_agi_service_real_dask_e2e_self_heal_submit_stop(monkeypatch, tmp_path):
    distributed = pytest.importorskip("dask.distributed")
    LocalCluster = distributed.LocalCluster
    Client = distributed.Client

    env = AgiEnv(apps_path=Path("src/agilab/apps/builtin"), app="mycode_project", verbose=0)
    env.base_worker_cls = "AgiDataWorker"

    cluster = LocalCluster(
        n_workers=1,
        threads_per_worker=2,
        processes=False,
        host="127.0.0.1",
        protocol="tcp",
        dashboard_address=None,
    )
    client = Client(cluster)

    async def _fake_start(_scheduler):
        AGI._dask_client = client
        AGI._scheduler = "127.0.0.1:8786"
        AGI._scheduler_ip = "127.0.0.1"
        AGI._scheduler_port = 8786

    async def _fake_sync():
        return None

    async def _fake_stop():
        return None

    monkeypatch.setattr(AGI, "_start", staticmethod(_fake_start))
    monkeypatch.setattr(AGI, "_sync", staticmethod(_fake_sync))
    monkeypatch.setattr(AGI, "_stop", staticmethod(_fake_stop))
    monkeypatch.setattr(BaseWorker, "_new", staticmethod(_real_service_stub_new))
    monkeypatch.setattr(BaseWorker, "loop", staticmethod(_real_service_stub_loop))
    monkeypatch.setattr(BaseWorker, "break_loop", staticmethod(_real_service_stub_break_loop))

    try:
        started = await asyncio.wait_for(
            AGI.serve(
                env,
                scheduler="127.0.0.1",
                workers={"127.0.0.1": 1},
                mode=AGI.DASK_MODE,
                action="start",
                service_queue_dir=tmp_path / "service_queue",
                poll_interval=0.05,
                heartbeat_timeout=0.2,
                stop_timeout=3.0,
            ),
            timeout=20.0,
        )
        assert started["status"] == "running"
        assert started["workers"], "expected at least one running service worker"
        worker = started["workers"][0]

        await asyncio.sleep(0.15)

        status = await asyncio.wait_for(
            AGI.serve(
                env,
                action="status",
                heartbeat_timeout=0.2,
            ),
            timeout=20.0,
        )
        assert worker in (status.get("restarted_workers") or [])

        submitted = await asyncio.wait_for(
            AGI.submit(
                env,
                work_plan=[["step"]],
                work_plan_metadata=[[{"meta": 1}]],
                task_name="e2e-batch",
            ),
            timeout=20.0,
        )
        assert submitted["status"] == "queued"
        assert submitted["queued_files"], "submit should enqueue at least one file"

        stopped = await asyncio.wait_for(
            AGI.serve(
                env,
                action="stop",
                shutdown_on_stop=False,
                stop_timeout=3.0,
            ),
            timeout=20.0,
        )
        assert stopped["status"] in {"stopped", "partial"}
    finally:
        try:
            AGI._dask_client = None
            client.close()
        except Exception:
            pass
        try:
            cluster.close()
        except Exception:
            pass


@pytest.mark.asyncio
async def test_start_scheduler_local_switches_port_and_connects(monkeypatch, tmp_path):
    cluster_pck = tmp_path / "cluster"
    (cluster_pck / "agi_distributor").mkdir(parents=True, exist_ok=True)
    (cluster_pck / "agi_distributor" / "cli.py").write_text("print('cli')", encoding="utf-8")
    active_app = tmp_path / "app"
    active_app.mkdir(parents=True, exist_ok=True)
    (active_app / "pyproject.toml").write_text("[project]\nname='app'\n", encoding="utf-8")

    AGI._mode = AGI.DASK_MODE
    AGI._mode_auto = False
    AGI._workers = {"127.0.0.1": 1}
    AGI._worker_init_error = False
    AGI.env = SimpleNamespace(
        wenv_rel=Path("wenv"),
        wenv_abs=tmp_path / "wenv",
        active_app=active_app,
        app="demo_app",
        uv="uv",
        envars={},
        cluster_pck=cluster_pck,
        export_local_bin="",
        is_local=lambda ip: ip == "127.0.0.1",
    )
    AGI.env.wenv_abs.mkdir(parents=True, exist_ok=True)
    calls = {"bg": [], "set_env": []}

    async def _fake_send(*_args, **_kwargs):
        return None

    async def _fake_kill(*_args, **_kwargs):
        return None

    async def _fake_connect(*_args, **_kwargs):
        return "fake-client"

    async def _fake_detect(_ip):
        return "export PATH=\"$HOME/.local/bin:$PATH\"; "

    async def _fake_sleep(_delay):
        return None

    async def _fake_port_release(*_args, **_kwargs):
        return False

    monkeypatch.setattr(
        AGI,
        "_get_scheduler",
        staticmethod(lambda scheduler: ("127.0.0.1", 8786) if scheduler else ("127.0.0.1", 8786)),
    )
    monkeypatch.setattr(AGI, "send_file", staticmethod(_fake_send))
    monkeypatch.setattr(AGI, "_kill", staticmethod(_fake_kill))
    monkeypatch.setattr(AGI, "_wait_for_port_release", staticmethod(_fake_port_release))
    monkeypatch.setattr(AGI, "find_free_port", staticmethod(lambda *_a, **_k: 8899))
    monkeypatch.setattr(AGI, "_detect_export_cmd", staticmethod(_fake_detect))
    monkeypatch.setattr(AGI, "_connect_scheduler_with_retry", staticmethod(_fake_connect))
    monkeypatch.setattr(agi_distributor_module.asyncio, "sleep", _fake_sleep)
    monkeypatch.setattr(
        agi_distributor_module.AgiEnv,
        "set_env_var",
        staticmethod(lambda *args: calls["set_env"].append(args)),
    )
    monkeypatch.setattr(
        AGI,
        "_exec_bg",
        staticmethod(lambda cmd, cwd: calls["bg"].append((cmd, cwd))),
    )

    ok = await AGI._start_scheduler("127.0.0.1")

    assert ok is True
    assert AGI._scheduler_port == 8899
    assert AGI._dask_client == "fake-client"
    assert AGI._install_done is True
    assert calls["bg"]
    assert any(entry[0] == "127.0.0.1_CMD_PREFIX" for entry in calls["set_env"])


@pytest.mark.asyncio
async def test_connect_scheduler_with_retry_succeeds_after_retry(monkeypatch):
    attempts = {"n": 0}

    async def _fake_client(_address, heartbeat_interval=5000, timeout=1.0):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("not ready")
        return {"connected": True, "timeout": timeout, "heartbeat": heartbeat_interval}

    async def _fake_sleep(_delay):
        return None

    monkeypatch.setattr(agi_distributor_module, "Client", _fake_client)
    monkeypatch.setattr(agi_distributor_module.asyncio, "sleep", _fake_sleep)

    client = await AGI._connect_scheduler_with_retry("tcp://127.0.0.1:8786", timeout=2.0)
    assert client["connected"] is True
    assert attempts["n"] == 3


@pytest.mark.asyncio
async def test_connect_scheduler_with_retry_times_out(monkeypatch):
    async def _fake_client(_address, heartbeat_interval=5000, timeout=1.0):
        raise RuntimeError("never ready")

    async def _fake_sleep(_delay):
        return None

    clock = {"t": 0.0}

    def _monotonic():
        clock["t"] += 0.25
        return clock["t"]

    monkeypatch.setattr(agi_distributor_module, "Client", _fake_client)
    monkeypatch.setattr(agi_distributor_module.asyncio, "sleep", _fake_sleep)
    monkeypatch.setattr(agi_distributor_module.time, "monotonic", _monotonic)

    with pytest.raises(RuntimeError, match="Failed to instantiate Dask Client"):
        await AGI._connect_scheduler_with_retry("tcp://127.0.0.1:8786", timeout=0.1)


@pytest.mark.asyncio
async def test_detect_export_cmd_local_and_remote(monkeypatch):
    monkeypatch.setattr(AgiEnv, "is_local", staticmethod(lambda ip: ip == "127.0.0.1"))
    had_attr = hasattr(AgiEnv, "export_local_bin")
    old_export = getattr(AgiEnv, "export_local_bin", None)
    setattr(AgiEnv, "export_local_bin", "LOCAL_PREFIX ")
    assert await AGI._detect_export_cmd("127.0.0.1") == "LOCAL_PREFIX "

    async def _fake_exec(_ip, _cmd):
        return "Linux"

    monkeypatch.setattr(AGI, "exec_ssh", staticmethod(_fake_exec))
    assert await AGI._detect_export_cmd("10.0.0.2") == 'export PATH="$HOME/.local/bin:$PATH";'
    if had_attr:
        setattr(AgiEnv, "export_local_bin", old_export)
    else:
        delattr(AgiEnv, "export_local_bin")


@pytest.mark.asyncio
async def test_detect_export_cmd_returns_empty_for_non_posix(monkeypatch):
    monkeypatch.setattr(AgiEnv, "is_local", staticmethod(lambda _ip: False))

    async def _fake_exec(_ip, _cmd):
        return "Windows_NT"

    monkeypatch.setattr(AGI, "exec_ssh", staticmethod(_fake_exec))
    assert await AGI._detect_export_cmd("10.0.0.3") == ""


def test_dask_env_prefix_and_scale_cluster_trim_workers():
    AGI._dask_log_level = ""
    assert AGI._dask_env_prefix() == ""
    AGI._dask_log_level = "INFO"
    assert "DASK_DISTRIBUTED__LOGGING__distributed=INFO" in AGI._dask_env_prefix()

    AGI._workers = {"10.0.0.1": 1}
    AGI._dask_workers = ["10.0.0.1:1001", "10.0.0.1:1002", "10.0.0.2:1001"]
    AGI._scale_cluster()
    assert AGI._dask_workers == ["10.0.0.1:1001"]


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
async def test_start_launches_workers_and_uploads_eggs(monkeypatch, tmp_path):
    wenv_abs = tmp_path / "worker_env"
    (wenv_abs / "dist").mkdir(parents=True, exist_ok=True)
    (wenv_abs / "dist" / "demo.egg").write_text("x", encoding="utf-8")

    AGI.env = SimpleNamespace(
        is_local=lambda ip: ip == "127.0.0.1",
        envars={},
        uv="uv",
        wenv_abs=wenv_abs,
        wenv_rel=Path("worker_env"),
    )
    AGI._mode = AGI.DASK_MODE
    AGI._mode_auto = False
    AGI._workers = {"127.0.0.1": 1, "10.0.0.2": 1}
    AGI._scheduler = "127.0.0.1:8786"
    AGI._worker_init_error = False
    calls = {"bg": [], "remote": [], "uploaded": []}

    class _Client:
        def upload_file(self, path):
            calls["uploaded"].append(path)

    async def _fake_start_scheduler(_scheduler):
        return True

    async def _fake_detect(_ip):
        return "export PATH=\"$HOME/.local/bin:$PATH\"; "

    async def _fake_sync(timeout=60):
        return None

    async def _fake_build_remote():
        return None

    async def _fake_exec_ssh_async(ip, cmd):
        calls["remote"].append((ip, cmd))
        return ""

    monkeypatch.setattr(AGI, "_dask_client", _Client())
    monkeypatch.setattr(AGI, "_start_scheduler", staticmethod(_fake_start_scheduler))
    monkeypatch.setattr(AGI, "_detect_export_cmd", staticmethod(_fake_detect))
    monkeypatch.setattr(AGI, "_sync", staticmethod(_fake_sync))
    monkeypatch.setattr(AGI, "_build_lib_remote", staticmethod(_fake_build_remote))
    monkeypatch.setattr(AGI, "exec_ssh_async", staticmethod(_fake_exec_ssh_async))
    monkeypatch.setattr(
        agi_distributor_module.AgiEnv,
        "set_env_var",
        staticmethod(lambda *_a, **_k: None),
    )
    monkeypatch.setattr(
        AGI,
        "_exec_bg",
        staticmethod(lambda cmd, cwd: calls["bg"].append((cmd, cwd))),
    )

    await AGI._start("127.0.0.1")
    await asyncio.sleep(0)

    assert calls["bg"]
    assert any(ip == "10.0.0.2" for ip, _ in calls["remote"])
    assert calls["uploaded"]


@pytest.mark.asyncio
async def test_stop_retires_workers_and_shutdown(monkeypatch):
    class _Client:
        def __init__(self):
            self.info_calls = 0
            self.retire_calls = 0
            self.shutdown_calls = 0

        async def scheduler_info(self):
            self.info_calls += 1
            if self.info_calls == 1:
                return {"workers": {"tcp://127.0.0.1:8787": {}}}
            return {"workers": {}}

        async def retire_workers(self, workers, close_workers=True, remove=True):
            self.retire_calls += 1

        async def shutdown(self):
            self.shutdown_calls += 1

    AGI._dask_client = _Client()
    AGI._mode_auto = False
    AGI._mode = AGI.DASK_MODE
    AGI._TIMEOUT = 3
    AGI.env = SimpleNamespace()
    closed = {"count": 0}

    async def _fake_close_all():
        closed["count"] += 1

    async def _fake_sleep(_delay):
        return None

    monkeypatch.setattr(AGI, "_close_all_connections", staticmethod(_fake_close_all))
    monkeypatch.setattr(agi_distributor_module.asyncio, "sleep", _fake_sleep)

    await AGI._stop()

    assert AGI._dask_client.retire_calls >= 1
    assert AGI._dask_client.shutdown_calls == 1
    assert closed["count"] == 1


@pytest.mark.asyncio
async def test_run_raises_when_worker_venv_is_missing(tmp_path, monkeypatch):
    AGI.env = SimpleNamespace(
        envars={},
        wenv_abs=tmp_path / "missing_wenv",
        debug=False,
        verbose=0,
        uv="uv",
        target_worker="demo_worker",
    )
    AGI._mode = AGI.PYTHON_MODE
    AGI._workers = {"127.0.0.1": 1}
    AGI._args = {}
    monkeypatch.chdir(tmp_path)
    with pytest.raises(FileNotFoundError, match="Worker installation"):
        await AGI._run()


@pytest.mark.asyncio
async def test_run_raises_when_worker_uv_sources_are_stale(tmp_path, monkeypatch):
    wenv_abs = tmp_path / "wenv"
    (wenv_abs / ".venv").mkdir(parents=True, exist_ok=True)
    (wenv_abs / "pyproject.toml").write_text(
        """
[tool.uv.sources]
ilp_worker = { path = "../../PycharmProjects/thales_agilab/apps/ilp_project/src/ilp_worker" }
""".strip(),
        encoding="utf-8",
    )
    AGI.env = SimpleNamespace(
        envars={},
        wenv_abs=wenv_abs,
        debug=False,
        verbose=0,
        uv="uv",
        target_worker="demo_worker",
    )
    AGI._mode = AGI.PYTHON_MODE
    AGI._workers = {"127.0.0.1": 1}
    AGI._args = {}
    monkeypatch.chdir(tmp_path)

    with pytest.raises(RuntimeError, match="stale or incomplete"):
        await AGI._run()


@pytest.mark.asyncio
async def test_run_debug_branch_returns_list_result(tmp_path, monkeypatch):
    wenv_abs = tmp_path / "wenv"
    (wenv_abs / ".venv").mkdir(parents=True, exist_ok=True)
    AGI.env = SimpleNamespace(
        envars={},
        wenv_abs=wenv_abs,
        debug=True,
        verbose=1,
        uv="uv",
        target_worker="demo_worker",
    )
    AGI._mode = AGI.DASK_MODE
    AGI._workers = {"127.0.0.1": 1}
    AGI._args = {"alpha": 1}
    monkeypatch.chdir(tmp_path)
    calls = {"new": 0, "run": 0, "kill": 0}

    def _fake_new(*_args, **_kwargs):
        calls["new"] += 1

    async def _fake_run(*_args, **_kwargs):
        calls["run"] += 1
        return ["ok", "done"]

    async def _fake_kill(*_args, **_kwargs):
        calls["kill"] += 1
        return None

    monkeypatch.setattr(BaseWorker, "_new", staticmethod(_fake_new))
    monkeypatch.setattr(BaseWorker, "_run", staticmethod(_fake_run))
    monkeypatch.setattr(AGI, "_kill", staticmethod(_fake_kill))

    result = await AGI._run()
    assert result == ["ok", "done"]
    assert calls["new"] == 1
    assert calls["run"] == 1
    assert calls["kill"] == 1
    assert (tmp_path / "dask_worker_0.pid").exists()


@pytest.mark.asyncio
async def test_run_non_debug_branch_parses_last_line(tmp_path, monkeypatch):
    wenv_abs = tmp_path / "wenv"
    (wenv_abs / ".venv").mkdir(parents=True, exist_ok=True)
    AGI.env = SimpleNamespace(
        envars={},
        wenv_abs=wenv_abs,
        debug=False,
        verbose=0,
        uv="uv",
        target_worker="demo_worker",
    )
    AGI._mode = AGI.PYTHON_MODE
    AGI._workers = {"127.0.0.1": 1}
    AGI._args = {"beta": 2}
    monkeypatch.chdir(tmp_path)

    async def _fake_kill(*_args, **_kwargs):
        return None

    async def _fake_run_async(_cmd, _cwd):
        return "header\nresult-line\n"

    monkeypatch.setattr(AGI, "_kill", staticmethod(_fake_kill))
    monkeypatch.setattr(agi_distributor_module.AgiEnv, "run_async", staticmethod(_fake_run_async))

    result = await AGI._run()
    assert result == "result-line"


@pytest.mark.asyncio
async def test_distribute_executes_new_calibration_and_works(monkeypatch):
    class _Client:
        def __init__(self):
            self._gather_calls = 0
            self.submissions = []

        def scheduler_info(self):
            return {
                "workers": {
                    "tcp://127.0.0.1:8787": {},
                    "tcp://10.0.0.2:8788": {},
                }
            }

        def submit(self, fn, *args, **kwargs):
            self.submissions.append(getattr(fn, "__name__", str(fn)))
            return {"fn": getattr(fn, "__name__", "fn"), "args": args, "kwargs": kwargs}

        def gather(self, futures):
            self._gather_calls += 1
            if self._gather_calls == 1:
                return [None for _ in futures]
            return ["log-a", "log-b"]

    AGI.env = SimpleNamespace(
        debug=False,
        target_worker="demo_worker",
        mode2str=lambda _mode: "dask",
    )
    AGI._dask_client = _Client()
    AGI._workers = {"127.0.0.1": 1, "10.0.0.2": 1}
    AGI._args = {"k": "v"}
    AGI._mode = AGI.DASK_MODE
    AGI.verbose = 0
    AGI.debug = False
    called = {"calibration": 0}

    async def _fake_distrib(_env, workers, _args):
        return workers, [["step-a"], ["step-b"]], [[{"m": 1}], [{"m": 2}]]

    async def _fake_calibration():
        called["calibration"] += 1
        AGI._capacity = {"127.0.0.1:8787": 1.0, "10.0.0.2:8788": 1.0}

    monkeypatch.setattr(agi_distributor_module.WorkDispatcher, "_do_distrib", staticmethod(_fake_distrib))
    monkeypatch.setattr(AGI, "_calibration", staticmethod(_fake_calibration))

    result = await AGI._distribute()
    assert result.startswith("dask ")
    assert called["calibration"] == 1
    assert AGI._work_plan == [["step-a"], ["step-b"]]
    assert AGI._work_plan_metadata == [[{"m": 1}], [{"m": 2}]]
    assert "BaseWorker._new" not in AGI._dask_client.submissions


@pytest.mark.asyncio
async def test_sync_waits_until_expected_workers(monkeypatch):
    class _FakeClient:
        def __init__(self):
            self.calls = 0

        def scheduler_info(self):
            self.calls += 1
            if self.calls == 1:
                return {"workers": None}
            if self.calls == 2:
                return {"workers": {"tcp://127.0.0.1:8787": {}}}
            return {
                "workers": {
                    "tcp://127.0.0.1:8787": {},
                    "tcp://10.0.0.2:8788": {},
                }
            }

    AGI._workers = {"127.0.0.1": 1, "10.0.0.2": 1}
    fake_client = _FakeClient()
    monkeypatch.setattr(agi_distributor_module, "Client", _FakeClient)
    AGI._dask_client = fake_client

    async def _fake_sleep(_delay):
        return None

    monkeypatch.setattr(agi_distributor_module.asyncio, "sleep", _fake_sleep)

    await AGI._sync(timeout=2)
    assert fake_client.calls >= 3


@pytest.mark.asyncio
async def test_sync_raises_timeout_on_repeated_failures(monkeypatch):
    class _FakeClient:
        def scheduler_info(self):
            raise RuntimeError("scheduler down")

    AGI._workers = {"127.0.0.1": 1}
    fake_client = _FakeClient()
    monkeypatch.setattr(agi_distributor_module, "Client", _FakeClient)
    AGI._dask_client = fake_client

    async def _fake_sleep(_delay):
        return None

    clock = {"t": 0.0}

    def _fake_time():
        clock["t"] += 0.3
        return clock["t"]

    monkeypatch.setattr(agi_distributor_module.asyncio, "sleep", _fake_sleep)
    monkeypatch.setattr(agi_distributor_module.time, "time", _fake_time)

    with pytest.raises(TimeoutError, match="Timeout waiting for all workers"):
        await AGI._sync(timeout=0.5)


@pytest.mark.asyncio
async def test_main_branches_simulate_install_dask_and_local(monkeypatch):
    class _Jobs:
        def flush(self):
            return None

    monkeypatch.setattr(agi_distributor_module.bg, "BackgroundJobManager", lambda: _Jobs())
    calls = []

    async def _fake_run():
        calls.append("run")
        return "run-result"

    async def _fake_prepare_local():
        calls.append("prepare_local")
        return None

    async def _fake_prepare_cluster(_scheduler):
        calls.append("prepare_cluster")
        return None

    async def _fake_deploy(_scheduler):
        calls.append("deploy")
        return None

    async def _fake_start(_scheduler):
        calls.append("start")
        return None

    async def _fake_distribute():
        calls.append("distribute")
        return "dist-result"

    async def _fake_stop():
        calls.append("stop")
        return None

    monkeypatch.setattr(AGI, "_run", staticmethod(_fake_run))
    monkeypatch.setattr(AGI, "_prepare_local_env", staticmethod(_fake_prepare_local))
    monkeypatch.setattr(AGI, "_prepare_cluster_env", staticmethod(_fake_prepare_cluster))
    monkeypatch.setattr(AGI, "_deploy_application", staticmethod(_fake_deploy))
    monkeypatch.setattr(AGI, "_start", staticmethod(_fake_start))
    monkeypatch.setattr(AGI, "_distribute", staticmethod(_fake_distribute))
    monkeypatch.setattr(AGI, "_stop", staticmethod(_fake_stop))
    monkeypatch.setattr(AGI, "_update_capacity", staticmethod(lambda: calls.append("update_capacity")))
    monkeypatch.setattr(AGI, "_clean_dirs_local", staticmethod(lambda: calls.append("clean_dirs_local")))
    monkeypatch.setattr(AGI, "_clean_job", staticmethod(lambda cond: calls.append(("clean_job", cond))))

    AGI._mode = AGI._SIMULATE_MODE
    result = await AGI._main("127.0.0.1")
    assert result == "run-result"

    times = iter([10.0, 14.5])
    monkeypatch.setattr(agi_distributor_module.time, "time", lambda: next(times))
    AGI._mode = AGI._INSTALL_MODE | AGI.DASK_MODE
    result = await AGI._main("127.0.0.1")
    assert result == 4.5

    AGI._mode = AGI.DASK_MODE
    result = await AGI._main("127.0.0.1")
    assert result == "dist-result"

    AGI._mode = AGI.PYTHON_MODE
    result = await AGI._main("127.0.0.1")
    assert result == "run-result"

    assert "prepare_local" in calls
    assert "prepare_cluster" in calls
    assert "deploy" in calls
    assert "start" in calls
    assert "distribute" in calls
    assert "stop" in calls


def test_clean_job_respects_cond_and_verbosity(monkeypatch):
    class _Jobs:
        def __init__(self):
            self.flush_calls = 0

        def flush(self):
            self.flush_calls += 1

    jobs = _Jobs()
    AGI._jobs = jobs

    AGI.verbose = 1
    AGI._clean_job(True)
    assert jobs.flush_calls == 1

    AGI.verbose = 0
    AGI._clean_job(True)
    assert jobs.flush_calls == 2

    AGI._clean_job(False)
    assert jobs.flush_calls == 2


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


@pytest.mark.asyncio
async def test_build_lib_local_non_cython_uploads_egg(monkeypatch, tmp_path):
    app_path = tmp_path / "app"
    app_path.mkdir(parents=True, exist_ok=True)
    wenv_abs = tmp_path / "wenv"
    (wenv_abs / "dist").mkdir(parents=True, exist_ok=True)
    egg_path = wenv_abs / "dist" / "demo.egg"
    egg_path.write_text("egg", encoding="utf-8")

    worker_pyproject = tmp_path / "worker_pyproject.toml"
    worker_pyproject.write_text("[project]\nname='worker'\n", encoding="utf-8")
    manager_pyproject = tmp_path / "manager_pyproject.toml"
    manager_pyproject.write_text("[project]\nname='manager'\n", encoding="utf-8")
    uvproject = tmp_path / "uv.toml"
    uvproject.write_text("[tool.uv]\n", encoding="utf-8")

    uploads = []
    commands = []

    class _Client:
        def upload_file(self, path):
            uploads.append(path)

    async def _fake_run(cmd, cwd):
        commands.append((cmd, str(cwd)))
        return ""

    AGI.env = SimpleNamespace(
        wenv_abs=wenv_abs,
        base_worker_cls="PandasWorker",
        active_app=app_path,
        setup_app_module="agi_node.agi_dispatcher.build",
        uv="uv",
        envars={},
        is_free_threading_available=False,
        worker_pyproject=worker_pyproject,
        manager_pyproject=manager_pyproject,
        uvproject=uvproject,
        verbose=0,
        pyvers_worker="3.13",
    )
    AGI._mode = AGI.PYTHON_MODE
    AGI._dask_client = _Client()
    AGI.agi_workers = {"pandas": "pandas-worker"}

    monkeypatch.setattr(agi_distributor_module.AgiEnv, "run", staticmethod(_fake_run))

    await AGI._build_lib_local()

    assert (wenv_abs / worker_pyproject.name).exists()
    assert any("pip install agi-env" in cmd for cmd, _ in commands)
    assert any("pip install agi-node" in cmd for cmd, _ in commands)
    assert any("bdist_egg" in cmd for cmd, _ in commands)
    assert str(egg_path) in uploads


@pytest.mark.asyncio
async def test_build_lib_local_cython_copies_worker_lib(monkeypatch, tmp_path):
    app_path = tmp_path / "app"
    app_path.mkdir(parents=True, exist_ok=True)
    wenv_abs = tmp_path / "wenv"
    dist_dir = wenv_abs / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    worker_lib = dist_dir / "demo_cy.so"
    worker_lib.write_text("binary", encoding="utf-8")

    worker_pyproject = tmp_path / "worker_pyproject.toml"
    worker_pyproject.write_text("[project]\nname='worker'\n", encoding="utf-8")
    manager_pyproject = tmp_path / "manager_pyproject.toml"
    manager_pyproject.write_text("[project]\nname='manager'\n", encoding="utf-8")
    uvproject = tmp_path / "uv.toml"
    uvproject.write_text("[tool.uv]\n", encoding="utf-8")

    commands = []

    async def _fake_run(cmd, cwd):
        commands.append((cmd, str(cwd)))
        if "build_ext" in cmd:
            return "build ok"
        return ""

    AGI.env = SimpleNamespace(
        wenv_abs=wenv_abs,
        base_worker_cls="PandasWorker",
        active_app=app_path,
        setup_app_module="agi_node.agi_dispatcher.build",
        uv="uv",
        envars={},
        is_free_threading_available=False,
        worker_pyproject=worker_pyproject,
        manager_pyproject=manager_pyproject,
        uvproject=uvproject,
        verbose=2,
        pyvers_worker="3.13",
    )
    AGI._mode = AGI.CYTHON_MODE
    AGI._dask_client = None
    AGI.agi_workers = {"pandas": "pandas-worker"}

    monkeypatch.setattr(agi_distributor_module.AgiEnv, "run", staticmethod(_fake_run))

    await AGI._build_lib_local()

    target = wenv_abs / ".venv/lib/python3.13/site-packages/demo_cy.so"
    assert target.exists()
    assert any("build_ext" in cmd for cmd, _ in commands)


@pytest.mark.asyncio
async def test_build_lib_local_selects_fireducks_package(monkeypatch, tmp_path):
    app_path = tmp_path / "app"
    app_path.mkdir(parents=True, exist_ok=True)
    wenv_abs = tmp_path / "wenv"
    dist_dir = wenv_abs / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    egg_path = dist_dir / "demo.egg"
    egg_path.write_text("egg", encoding="utf-8")

    worker_pyproject = tmp_path / "worker_pyproject.toml"
    worker_pyproject.write_text("[project]\nname='worker'\n", encoding="utf-8")
    manager_pyproject = tmp_path / "manager_pyproject.toml"
    manager_pyproject.write_text("[project]\nname='manager'\n", encoding="utf-8")
    uvproject = tmp_path / "uv.toml"
    uvproject.write_text("[tool.uv]\n", encoding="utf-8")

    commands = []

    async def _fake_run(cmd, cwd):
        commands.append((cmd, str(cwd)))
        return ""

    async def _fake_send_file(*_args, **_kwargs):
        return None

    AGI.env = SimpleNamespace(
        wenv_abs=wenv_abs,
        base_worker_cls="FireducksWorker",
        active_app=app_path,
        setup_app_module="agi_node.agi_dispatcher.build",
        uv="uv",
        envars={},
        is_free_threading_available=False,
        worker_pyproject=worker_pyproject,
        manager_pyproject=manager_pyproject,
        uvproject=uvproject,
        verbose=2,
        pyvers_worker="3.13",
    )
    AGI._mode = 0
    AGI._dask_client = SimpleNamespace(upload_file=lambda *_args, **_kwargs: None)
    AGI.agi_workers = {"fireducks": "fireducks-worker"}

    monkeypatch.setattr(agi_distributor_module.AgiEnv, "run", staticmethod(_fake_run))
    monkeypatch.setattr(AGI, "send_file", staticmethod(_fake_send_file))

    await AGI._build_lib_local()

    assert any("fireducks_worker" in cmd for cmd, _ in commands)


@pytest.mark.asyncio
async def test_start_scheduler_wraps_non_runtime_error(monkeypatch, tmp_path):
    app_path = tmp_path / "app"
    app_path.mkdir()
    cluster_pck = tmp_path / "cluster"
    (cluster_pck / "agi_distributor").mkdir(parents=True)
    (cluster_pck / "agi_distributor" / "cli.py").write_text("print('cli')\n", encoding="utf-8")

    env = SimpleNamespace(
        wenv_rel=Path("wenv/demo_worker"),
        wenv_abs=tmp_path / "wenv" / "demo_worker",
        active_app=app_path,
        cluster_pck=cluster_pck,
        envars={},
        uv="uv",
        export_local_bin="",
        app="demo",
        hw_rapids_capable=False,
        is_local=lambda ip: True,
    )
    env.wenv_abs.mkdir(parents=True)
    AGI.env = env
    AGI._mode_auto = True
    AGI._mode = AGI.DASK_MODE
    AGI._workers = {"127.0.0.1": 1}
    AGI._TIMEOUT = 1
    AGI._worker_init_error = False

    async def _fake_send_file(*_args, **_kwargs):
        return None

    async def _fake_kill(*_args, **_kwargs):
        return None

    async def _fake_wait_for_port_release(*_args, **_kwargs):
        return True

    async def _fake_detect_export_cmd(*_args, **_kwargs):
        return ""

    async def _fake_connect_scheduler_with_retry(*_args, **_kwargs):
        raise ValueError("client boom")

    original_sleep = asyncio.sleep
    monkeypatch.setattr(AGI, "send_file", staticmethod(_fake_send_file))
    monkeypatch.setattr(AGI, "_kill", staticmethod(_fake_kill))
    monkeypatch.setattr(AGI, "_wait_for_port_release", staticmethod(_fake_wait_for_port_release))
    monkeypatch.setattr(AGI, "_detect_export_cmd", staticmethod(_fake_detect_export_cmd))
    monkeypatch.setattr(AGI, "_connect_scheduler_with_retry", staticmethod(_fake_connect_scheduler_with_retry))
    monkeypatch.setattr(AGI, "_exec_bg", staticmethod(lambda *_args, **_kwargs: None))
    monkeypatch.setattr(AGI, "_dask_env_prefix", staticmethod(lambda: ""))
    monkeypatch.setattr(AGI, "_get_scheduler", staticmethod(lambda _scheduler: ("127.0.0.1", 8799)))
    monkeypatch.setattr(agi_distributor_module.asyncio, "sleep", lambda *_args, **_kwargs: original_sleep(0))

    with pytest.raises(RuntimeError, match="Failed to instantiate Dask Client"):
        await AGI._start_scheduler("127.0.0.1")
@pytest.mark.asyncio
async def test_build_lib_remote_logs_when_pool_open_zero():
    AGI.verbose = 1
    AGI._dask_client = SimpleNamespace(
        scheduler=SimpleNamespace(pool=SimpleNamespace(open=0)),
        scheduler_info=lambda: {"workers": {"tcp://127.0.0.1:8787": {}}},
    )
    await AGI._build_lib_remote()


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
