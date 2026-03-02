import zipfile
from pathlib import Path

from agi_cluster.agi_distributor import cli as cli_mod


def test_get_processes_containing_parses_unix_ps(monkeypatch):
    output = "\n".join(
        [
            "101 python dask scheduler",
            "202 python other.py",
            "303 python DASK worker",
        ]
    )
    monkeypatch.setattr(cli_mod.os, "name", "posix", raising=False)
    monkeypatch.setattr(cli_mod.subprocess, "check_output", lambda *args, **kwargs: output)
    pids = cli_mod.get_processes_containing("dask")
    assert pids == {101, 303}


def test_get_child_pids_parses_ppid_map(monkeypatch):
    output = "\n".join(["100 1", "200 100", "300 999", "400 200"])
    monkeypatch.setattr(cli_mod.os, "name", "posix", raising=False)
    monkeypatch.setattr(cli_mod.subprocess, "check_output", lambda *args, **kwargs: output)
    children = cli_mod.get_child_pids({100})
    assert children == {200}


def test_poll_until_dead_returns_empty_when_all_dead(monkeypatch):
    monkeypatch.setattr(cli_mod, "_is_alive", lambda _pid: False)
    remaining = cli_mod._poll_until_dead({1, 2}, total=0.05, interval=0.01)
    assert remaining == set()


def test_choose_iters_calibration(monkeypatch):
    monkeypatch.setattr(cli_mod, "_time_busy", lambda _iters: 0.2)
    iters = cli_mod._choose_iters(target_s=0.15)
    assert 149000 <= iters <= 151000

    monkeypatch.setattr(cli_mod, "_time_busy", lambda _iters: 0.0)
    assert cli_mod._choose_iters(target_s=0.15) == 5000000


def test_threaded_runs_requested_number_of_workers(monkeypatch):
    calls = {"count": 0}

    def _fake_busy(_iters):
        calls["count"] += 1
        return 0

    monkeypatch.setattr(cli_mod, "_busy_work", _fake_busy)
    dt = cli_mod.threaded(nthreads=3, iters=1)
    assert dt >= 0.0
    assert calls["count"] == 3


def test_clean_removes_temp_and_wenv(tmp_path, monkeypatch):
    scratch_root = tmp_path / "tmp"
    scratch_dir = scratch_root / "dask-scratch-space"
    wenv_dir = tmp_path / "wenv"
    scratch_dir.mkdir(parents=True, exist_ok=True)
    wenv_dir.mkdir(parents=True, exist_ok=True)
    (scratch_dir / "a.txt").write_text("x", encoding="utf-8")
    (wenv_dir / "b.txt").write_text("y", encoding="utf-8")

    monkeypatch.setattr(cli_mod, "gettempdir", lambda: str(scratch_root))
    cli_mod.clean(str(wenv_dir))
    assert not scratch_dir.exists()
    assert not wenv_dir.exists()


def test_unzip_extracts_egg_contents(tmp_path):
    root = tmp_path / "worker"
    root.mkdir(parents=True, exist_ok=True)
    egg_path = root / "demo.egg"
    with zipfile.ZipFile(egg_path, "w") as zf:
        zf.writestr("demo_pkg/data.txt", "hello")

    cli_mod.unzip(str(root))
    extracted = root / "src" / "demo_pkg" / "data.txt"
    assert extracted.exists()
    assert extracted.read_text(encoding="utf-8") == "hello"


def test_python_version_returns_structured_tag():
    tag = cli_mod.python_version()
    assert "-" in tag
    assert "none" in tag
