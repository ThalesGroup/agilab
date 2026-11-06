from __future__ import annotations

import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from tools import setup_locked_python_tools as installer


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / "repo"
    requirements = root / ".github/requirements/ci-example.txt"
    requirements.parent.mkdir(parents=True)
    requirements.write_text("example==1 --hash=sha256:" + "a" * 64 + "\n")
    return root


@pytest.mark.parametrize(
    "requirements",
    [
        "/tmp/ci-example.txt", ".github/requirements/../ci-example.txt",
        ".github/requirements/ci-example.in", ".github/requirements/ci-Example.txt",
        ".github/requirements/ci-missing.txt", ".github/requirements/ci-example.txt\n",
        ".github/requirements/ci-example.txt; echo unsafe",
        "xgithub/requirements/ci-example.txt", ".github/requirements/ci-exampleXtxt",
    ],
)
def test_invalid_requirements_refuse_before_any_subprocess(repository, monkeypatch, requirements):
    calls = []
    monkeypatch.setattr(installer.subprocess, "run", lambda *a, **k: calls.append(a))
    with pytest.raises(installer.LockedToolsError):
        installer.install_tools(requirements, root=repository)
    assert calls == []


def test_redirected_lock_refuses_before_any_subprocess(repository, tmp_path, monkeypatch):
    lock = repository / ".github/requirements/ci-example.txt"
    outside = tmp_path / "outside.txt"
    outside.write_text(lock.read_text())
    lock.unlink()
    lock.symlink_to(outside)
    calls = []
    monkeypatch.setattr(installer.subprocess, "run", lambda *a, **k: calls.append(a))
    with pytest.raises(installer.LockedToolsError, match="redirected"):
        installer.install_tools(".github/requirements/ci-example.txt", root=repository)
    assert calls == []


def fake_uv(monkeypatch, tmp_path, *, version="0.10.7", fail_install=False):
    calls = []
    original_mkdtemp = installer.tempfile.mkdtemp
    monkeypatch.setattr(
        installer.tempfile, "mkdtemp",
        lambda **kwargs: original_mkdtemp(dir=tmp_path, **kwargs),
    )
    def execute(argv, **kwargs):
        calls.append((argv, kwargs))
        if argv == ["uv", "--version"]:
            return SimpleNamespace(stdout=f"uv {version} (test build)\n", returncode=0)
        if fail_install and argv[:3] == ["uv", "pip", "install"]:
            raise subprocess.CalledProcessError(1, argv)
        return SimpleNamespace(returncode=7 if argv[0] == "locked-command" else 0)
    monkeypatch.setattr(installer.subprocess, "run", execute)
    return calls


def test_isolated_install_preserves_exact_interpreter_and_hash_flags(repository, tmp_path, monkeypatch):
    for key in ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "UV_PROJECT", "PYTHONPATH",
                "UV_ENV_FILE", "UV_PYTHON", "AGILAB_DEV_UV_PROJECT_ENVIRONMENT"):
        monkeypatch.setenv(key, "/polluted/developer/environment")
    calls = fake_uv(monkeypatch, tmp_path)
    target = installer.install_tools(".github/requirements/ci-example.txt", root=repository)
    assert target.parent == tmp_path
    assert target.name.startswith("agilab-ci-example-")
    assert calls[1][0] == ["uv", "venv", "--python", installer.sys.executable, str(target)]
    python = target / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    assert calls[2][0] == [
        "uv", "pip", "install", "--python", str(python),
        "--require-hashes", "--no-build", "--no-cache", "--requirements",
        str(repository / ".github/requirements/ci-example.txt"),
    ]
    for _, kwargs in calls:
        assert kwargs["check"] is True
        assert kwargs.get("shell", False) is False
        assert "VIRTUAL_ENV" not in kwargs["env"]
        assert "UV_PROJECT_ENVIRONMENT" not in kwargs["env"]
        assert "PYTHONPATH" not in kwargs["env"]
        assert kwargs["env"]["UV_NO_CONFIG"] == "1"
        assert kwargs["env"]["UV_NO_CACHE"] == "1"


def test_unpinned_uv_refuses_before_environment_or_install(repository, tmp_path, monkeypatch):
    calls = fake_uv(monkeypatch, tmp_path, version="0.11.26")
    with pytest.raises(installer.LockedToolsError, match="Expected uv 0.10.7"):
        installer.install_tools(".github/requirements/ci-example.txt", root=repository)
    assert len(calls) == 1
    assert not list(tmp_path.glob("agilab-ci-*"))


@pytest.mark.parametrize("fail_install", [False, True])
def test_workflow_exports_only_after_successful_install(repository, tmp_path, monkeypatch, fail_install):
    export_path = tmp_path / "github-path"
    export_env = tmp_path / "github-env"
    export_path.write_text("")
    export_env.write_text("")
    monkeypatch.setenv("GITHUB_PATH", str(export_path))
    monkeypatch.setenv("GITHUB_ENV", str(export_env))
    calls = fake_uv(monkeypatch, tmp_path, fail_install=fail_install)
    fake = installer.subprocess.run
    def execute(argv, **kwargs):
        assert export_path.read_text() == ""
        assert export_env.read_text() == ""
        return fake(argv, **kwargs)
    monkeypatch.setattr(installer.subprocess, "run", execute)
    if fail_install:
        with pytest.raises(subprocess.CalledProcessError):
            installer.install_tools(
                ".github/requirements/ci-example.txt", root=repository, github_env=True,
            )
        assert export_path.read_text() == export_env.read_text() == ""
        assert not list(tmp_path.glob("agilab-ci-*"))
    else:
        target = installer.install_tools(
            ".github/requirements/ci-example.txt", root=repository, github_env=True,
        )
        bin_dir = target / ("Scripts" if os.name == "nt" else "bin")
        assert export_path.read_text() == str(bin_dir) + "\n"
        assert export_env.read_text() == f"AGILAB_DEV_UV_PROJECT_ENVIRONMENT={target}\n"
    assert len(calls) == 3


def test_invalid_workflow_exports_refuse_before_subprocess(repository, monkeypatch):
    monkeypatch.delenv("GITHUB_PATH", raising=False)
    calls = []
    monkeypatch.setattr(installer.subprocess, "run", lambda *a, **k: calls.append(a))
    with pytest.raises(installer.LockedToolsError, match="GITHUB_PATH"):
        installer.install_tools(
            ".github/requirements/ci-example.txt", root=repository, github_env=True,
        )
    assert calls == []


def test_run_uses_locked_path_propagates_failure_and_cleans_environment(tmp_path, monkeypatch):
    target = tmp_path / "locked-env"
    target.mkdir()
    monkeypatch.setattr(installer, "install_tools", lambda *a, **k: target)
    calls = []
    def execute(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=7)
    monkeypatch.setattr(installer.subprocess, "run", execute)
    assert installer.main([
        "--requirements", ".github/requirements/ci-example.txt",
        "--run", "locked-command", "--check",
    ]) == 7
    argv, kwargs = calls[0]
    assert argv == ["locked-command", "--check"]
    bin_dir = target / ("Scripts" if os.name == "nt" else "bin")
    assert kwargs["env"]["PATH"].split(os.pathsep)[0] == str(bin_dir)
    assert kwargs["env"]["VIRTUAL_ENV"] == str(target)
    assert not target.exists()


@pytest.mark.parametrize("arguments", [
    ["--requirements", ".github/requirements/ci-example.txt", "--run"],
    ["--requirements", ".github/requirements/ci-example.txt", "--github-env", "--run", "anything"],
])
def test_invalid_run_options_refuse_before_install(monkeypatch, arguments):
    calls = []
    monkeypatch.setattr(installer, "install_tools", lambda *a, **k: calls.append(a))
    with pytest.raises(SystemExit) as error:
        installer.main(arguments)
    assert error.value.code == 2
    assert calls == []


def test_removed_github_entrypoints_remain_absent():
    assert not Path(".github/actions/setup-locked-python-tools/action.yml").exists()
    assert not Path(".github/scripts/agilab_polars_2_runtime_qualification.py").exists()
