from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src" / "agilab" / "env_footprint.py"
SPEC = importlib.util.spec_from_file_location("agilab.env_footprint", MODULE_PATH)
assert SPEC and SPEC.loader
env_footprint = importlib.util.module_from_spec(SPEC)
sys.modules.setdefault("agilab.env_footprint", env_footprint)
SPEC.loader.exec_module(env_footprint)


def _write_file(path: Path, payload: bytes = b"x" * 4096) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _make_sample_install(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    home = tmp_path / "home"
    _write_file(repo / "pyproject.toml", b"[project]\nname = 'agilab'\n")
    _write_file(repo / "src" / "agilab" / "__init__.py", b"")
    _write_file(repo / "src" / "agilab" / "module.py")
    _write_file(repo / ".venv" / "lib" / "python3.13" / "site-packages" / "root_pkg.py")
    _write_file(repo / "src" / "agilab" / "apps" / "demo" / ".venv" / "lib" / "site-packages" / "app_pkg.py")
    _write_file(home / "agi-space" / ".venv" / "lib" / "site-packages" / "agilab_pkg.py")
    _write_file(home / "wenv" / "demo_worker" / ".venv" / "lib" / "site-packages" / "worker_pkg.py")
    _write_file(home / ".local" / "share" / "uv" / "python" / "cpython-3.13" / "python")
    _write_file(home / ".local" / "share" / "agilab" / "state.toml")
    _write_file(home / ".agilab" / "app_settings.toml")
    _write_file(repo / "src" / "agilab" / "pkg" / "build" / "artifact.o")

    cache_file = home / ".cache" / "uv" / "archive" / "shared.py"
    venv_file = repo / ".venv" / "lib" / "python3.13" / "site-packages" / "shared.py"
    _write_file(cache_file, b"shared" * 2048)
    venv_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(cache_file, venv_file)
    except OSError:
        venv_file.write_bytes(cache_file.read_bytes())

    return repo, home


def test_build_footprint_reports_expected_install_categories(tmp_path: Path, monkeypatch) -> None:
    repo, home = _make_sample_install(tmp_path)
    monkeypatch.setenv("UV_LINK_MODE", "hardlink")

    report = env_footprint.build_footprint(repo_root=repo, home=home, top=5)

    assert report["schema"] == env_footprint.SCHEMA
    assert report["uv_link_mode"] == "hardlink"
    assert report["summary"]["raw_allocated_bytes"] >= report["summary"]["unique_allocated_bytes"]
    assert report["summary"]["hardlink_savings_bytes"] >= 0

    categories = {category["name"]: category for category in report["categories"]}
    assert set(categories) == {
        "source_tree",
        "root_venv",
        "project_venvs",
        "agi_space_venvs",
        "worker_venvs",
        "uv_cache",
        "uv_python_store",
        "agilab_state",
        "build_outputs",
    }
    assert categories["source_tree"]["allocated_bytes"] > 0
    assert categories["root_venv"]["allocated_bytes"] > 0
    assert categories["project_venvs"]["allocated_bytes"] > 0
    assert categories["agi_space_venvs"]["allocated_bytes"] > 0
    assert categories["worker_venvs"]["allocated_bytes"] > 0
    assert categories["uv_cache"]["allocated_bytes"] > 0
    assert categories["uv_python_store"]["allocated_bytes"] > 0
    assert categories["build_outputs"]["allocated_bytes"] > 0
    assert len(report["top_entries"]) <= 5


def test_footprint_helpers_cover_symlink_missing_and_duplicate_paths(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "target.txt"
    _write_file(target, b"target")
    symlink = tmp_path / "target-link.txt"
    try:
        symlink.symlink_to(target)
    except OSError:
        symlink = target

    missing = tmp_path / "missing"

    assert env_footprint._format_bytes(0) == "0 B"
    assert env_footprint._format_bytes(1536) == "1.5 KiB"
    assert env_footprint._scan_path(missing) == (0, 0)

    entry = env_footprint._entry_for(symlink)
    assert entry["exists"] is True
    if symlink.is_symlink():
        assert entry["symlink_target"] == str(target)

    assert env_footprint._existing([missing, target, target]) == [target]

    monkeypatch.chdir(tmp_path)
    assert env_footprint._repo_root_from_here() == tmp_path


def test_footprint_iterators_skip_missing_and_reserved_dirs(tmp_path: Path) -> None:
    assert list(env_footprint._iter_venvs(tmp_path / "missing")) == []
    assert list(env_footprint._iter_build_outputs(tmp_path / "missing")) == []

    _write_file(tmp_path / "project" / ".venv" / "pyvenv.cfg", b"")
    _write_file(tmp_path / "node_modules" / "pkg" / ".venv" / "pyvenv.cfg", b"")
    _write_file(tmp_path / ".git" / "hooks" / ".venv" / "pyvenv.cfg", b"")
    _write_file(tmp_path / "package" / "dist" / "artifact.whl", b"wheel")
    _write_file(tmp_path / "node_modules" / "pkg" / "dist" / "artifact.whl", b"wheel")

    assert list(env_footprint._iter_venvs(tmp_path)) == [tmp_path / "project" / ".venv"]
    assert list(env_footprint._iter_build_outputs(tmp_path)) == [tmp_path / "package" / "dist"]


def test_footprint_cli_emits_json_and_text(tmp_path: Path, monkeypatch, capsys) -> None:
    repo, home = _make_sample_install(tmp_path)
    monkeypatch.setenv("UV_LINK_MODE", "hardlink")

    assert env_footprint.main(["--repo-root", str(repo), "--home", str(home), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == env_footprint.SCHEMA
    assert payload["home"] == str(home.resolve())

    assert env_footprint.main(["--repo-root", str(repo), "--home", str(home), "--top", "1"]) == 0
    output = capsys.readouterr().out
    assert "AGILAB environment footprint" in output
    assert "uv_link_mode: hardlink" in output
    assert "- source_tree:" in output
