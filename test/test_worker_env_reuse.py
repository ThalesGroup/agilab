from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "worker_env_reuse.py"


def _load_module():
    sys.path.insert(0, str(ROOT / "tools"))
    spec = importlib.util.spec_from_file_location(
        "worker_env_reuse_test_module", MODULE_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_worker_env_reuse_reports_marker_missing_then_reuse(tmp_path: Path) -> None:
    module = _load_module()
    worker_pyproject = tmp_path / "worker" / "pyproject.toml"
    worker_copy = tmp_path / "wenv" / "demo_worker"
    worker_pyproject.parent.mkdir()
    worker_pyproject.write_text(
        "[project]\nname='demo-worker'\nversion='1'\n", encoding="utf-8"
    )

    missing = module.worker_env_reuse_report(
        worker_pyproject=worker_pyproject,
        worker_copy=worker_copy,
    )
    assert missing["status"] == "rebuild"
    assert missing["reason"] == "marker-missing"

    marker = module.write_marker(missing)
    assert marker.is_file()

    reuse = module.worker_env_reuse_report(
        worker_pyproject=worker_pyproject,
        worker_copy=worker_copy,
    )
    assert reuse["status"] == "reuse"
    assert reuse["reason"] == "manifest-unchanged"


def test_worker_env_reuse_detects_manifest_change_and_json_cli(
    tmp_path: Path, capsys
) -> None:
    module = _load_module()
    worker_pyproject = tmp_path / "worker" / "pyproject.toml"
    worker_copy = tmp_path / "wenv" / "demo_worker"
    worker_pyproject.parent.mkdir()
    worker_pyproject.write_text(
        "[project]\nname='demo-worker'\nversion='1'\n", encoding="utf-8"
    )
    module.write_marker(
        module.worker_env_reuse_report(
            worker_pyproject=worker_pyproject,
            worker_copy=worker_copy,
        )
    )

    worker_pyproject.write_text(
        "[project]\nname='demo-worker'\nversion='2'\n", encoding="utf-8"
    )
    changed = module.worker_env_reuse_report(
        worker_pyproject=worker_pyproject,
        worker_copy=worker_copy,
    )
    assert changed["status"] == "rebuild"
    assert changed["reason"] == "manifest-changed"

    assert (
        module.main(
            [
                "--worker-pyproject",
                str(worker_pyproject),
                "--worker-copy",
                str(worker_copy),
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == module.SCHEMA_VERSION


def _report_fixture(tmp_path: Path):
    module = _load_module()
    project = tmp_path / "worker/pyproject.toml"
    project.parent.mkdir()
    project.write_text('[project]\nname="worker"\nversion="1"\n')
    args = {"worker_pyproject": project, "worker_copy": tmp_path / "generated"}
    return module, project, args


@pytest.mark.parametrize("operation", ["create", "change", "remove"])
def test_implicit_uv_lock_change_invalidates_marker(
    tmp_path: Path, operation: str
) -> None:
    module, project, args = _report_fixture(tmp_path)
    lock = project.with_name("uv.lock")
    if operation != "create":
        lock.write_text("version = 1\nrevision = 1\n")
    original_project = project.read_bytes()
    module.write_marker(module.worker_env_reuse_report(**args))
    if operation == "remove":
        lock.unlink()
    else:
        lock.write_text("version = 1\nrevision = 2\n")
    report = module.worker_env_reuse_report(**args)
    assert report["status"] == "rebuild"
    assert report["reason"] == "manifest-changed"
    assert project.read_bytes() == original_project


def test_same_stat_changed_bytes_are_not_reused(tmp_path: Path) -> None:
    module, project, args = _report_fixture(tmp_path)
    module.write_marker(module.worker_env_reuse_report(**args))
    before = project.stat()
    project.write_text(project.read_text().replace('version="1"', 'version="2"'))
    os.utime(project, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert project.stat().st_size == before.st_size
    assert project.stat().st_mtime_ns == before.st_mtime_ns
    assert project.stat().st_ino == before.st_ino
    assert module.worker_env_reuse_report(**args)["status"] == "rebuild"


@pytest.mark.parametrize(
    "corruption",
    [
        "invalid-json",
        "binary",
        "schema",
        "no-manifest",
        "empty-files",
        "file-hash",
        "digest",
    ],
)
def test_corrupt_marker_never_allows_reuse(tmp_path: Path, corruption: str) -> None:
    module, _project, args = _report_fixture(tmp_path)
    report = module.worker_env_reuse_report(**args)
    marker = module.write_marker(report)
    payload = json.loads(marker.read_text())
    if corruption == "invalid-json":
        marker.write_text("{")
    elif corruption == "binary":
        marker.write_bytes(b"\xff\xfe")
    else:
        if corruption == "schema":
            payload["schema"] = "wrong"
        elif corruption == "no-manifest":
            del payload["manifest"]
        elif corruption == "empty-files":
            payload["manifest"]["files"] = []
        elif corruption == "file-hash":
            payload["manifest"]["files"][0]["sha256"] = "0" * 64
        elif corruption == "digest":
            payload["manifest"]["digest"] = "0" * 64
        marker.write_text(json.dumps(payload))
    actual = module.worker_env_reuse_report(**args)
    assert actual["status"] == "rebuild"
    assert actual["reason"] == "marker-invalid"


def test_missing_required_manifest_refuses_marker_write(tmp_path: Path) -> None:
    module, project, args = _report_fixture(tmp_path)
    extra = project.with_name("required.toml")
    report = module.worker_env_reuse_report(**args, manifest_files=[extra])
    assert report["reason"] == "manifest-missing"
    with pytest.raises(ValueError, match="incomplete"):
        module.write_marker(report)
    assert not args["worker_copy"].exists()


def test_stale_report_cannot_mark_new_file_bytes(tmp_path: Path) -> None:
    module, project, args = _report_fixture(tmp_path)
    report = module.worker_env_reuse_report(**args)
    marker = module.write_marker(report)
    saved = marker.read_bytes()
    project.write_text(project.read_text().replace('version="1"', 'version="2"'))
    with pytest.raises(ValueError, match="changed since report"):
        module.write_marker(report)
    assert marker.read_bytes() == saved
    assert module.worker_env_reuse_report(**args)["status"] == "rebuild"
    module.write_marker(module.worker_env_reuse_report(**args))
    assert module.worker_env_reuse_report(**args)["status"] == "reuse"


def test_atomic_marker_write_failure_preserves_previous_and_retry(
    monkeypatch, tmp_path: Path
) -> None:
    module, _project, args = _report_fixture(tmp_path)
    report = module.worker_env_reuse_report(**args)
    marker = module.write_marker(report)
    before = marker.read_bytes()
    original = Path.replace

    def fail_replace(path, target):
        if target == marker:
            raise OSError("injected marker replacement failure")
        return original(path, target)

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError, match="injected marker replacement"):
        module.write_marker(report)
    assert marker.read_bytes() == before
    assert sorted(marker.parent.iterdir()) == [marker]
    monkeypatch.setattr(Path, "replace", original)
    module.write_marker(report)
    assert module.worker_env_reuse_report(**args)["status"] == "reuse"


def test_report_reads_bytes_without_performance_cache_writes(
    monkeypatch, tmp_path: Path
) -> None:
    module, _project, args = _report_fixture(tmp_path)
    digest = module.manifest_digest
    calls = []

    def checked(*a, **kwargs):
        calls.append(kwargs)
        return digest(*a, **kwargs)

    monkeypatch.setattr(module, "manifest_digest", checked)
    before = {
        p.relative_to(tmp_path): p.read_bytes()
        for p in tmp_path.rglob("*")
        if p.is_file()
    }
    report = module.worker_env_reuse_report(**args)
    after = {
        p.relative_to(tmp_path): p.read_bytes()
        for p in tmp_path.rglob("*")
        if p.is_file()
    }
    assert before == after
    assert calls and all(call["use_cache"] is False for call in calls)
    assert report["scope"] == "manifest-only"


def test_marker_symlink_and_global_name_escape_are_refused(tmp_path: Path) -> None:
    module, _project, args = _report_fixture(tmp_path)
    report = module.worker_env_reuse_report(**args)
    marker = Path(report["marker"])
    marker.parent.mkdir()
    donor = tmp_path / "donor-marker"
    donor.write_bytes(b"preserve donor")
    marker.symlink_to(donor)
    assert module.worker_env_reuse_report(**args)["reason"] == "marker-invalid"
    with pytest.raises(ValueError, match="symlink marker"):
        module.write_marker(report)
    assert marker.is_symlink()
    assert donor.read_bytes() == b"preserve donor"
    for name in (
        "../escaped",
        "/global-marker",
        "nested/marker",
        "nested\\marker",
        "..",
        "",
    ):
        with pytest.raises(ValueError, match="single filename"):
            module.worker_env_reuse_report(**args, marker_name=name)


def test_cli_reports_then_explicitly_records_only_manifest(
    tmp_path: Path, capsys
) -> None:
    module, project, args = _report_fixture(tmp_path)
    argv = [
        "--worker-pyproject",
        str(project),
        "--worker-copy",
        str(args["worker_copy"]),
        "--json",
    ]
    assert module.main(argv) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "rebuild"
    assert not args["worker_copy"].exists()
    assert module.main([*argv, "--write-marker"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "reuse"
    assert report["scope"] == "manifest-only"
    assert sorted(path.name for path in args["worker_copy"].iterdir()) == [
        module.DEFAULT_MARKER_NAME
    ]


def _review_marker_tree(root: Path):
    return {
        str(p.relative_to(root)): (
            p.lstat().st_ino,
            p.lstat().st_mode,
            str(p.readlink())
            if p.is_symlink()
            else p.read_bytes()
            if p.is_file()
            else None,
        )
        for p in [root, *sorted(root.rglob("*"))]
    }


@pytest.mark.parametrize(
    "filename", ["pyproject.toml", "uv.lock", "extra-manifest.txt"]
)
@pytest.mark.parametrize("alias", ["direct", "parent-symlink", "hardlink"])
@pytest.mark.parametrize("entrypoint", ["api", "cli"])
def test_review_marker_input_collision_refuses_before_touch(
    monkeypatch, tmp_path, filename, alias, entrypoint
):
    module = _load_module()
    source = tmp_path / "worker"
    source.mkdir()
    (source / "pyproject.toml").write_text(
        '[project]\nname="owned-worker"\nversion="1"\n'
    )
    (source / "uv.lock").write_text("version = 1\nrevision = 1\n")
    extra = source / "extra-manifest.txt"
    extra.write_text("owned extra input\n")
    copy = source
    marker_name = filename
    if alias == "parent-symlink":
        copy = tmp_path / "owned-source-alias"
        copy.symlink_to(source, target_is_directory=True)
    elif alias == "hardlink":
        copy = tmp_path / "copy"
        copy.mkdir()
        marker_name = "owned-marker.json"
        (copy / marker_name).hardlink_to(source / filename)
    args = dict(
        worker_pyproject=source / "pyproject.toml",
        worker_copy=copy,
        manifest_files=[extra],
        marker_name=marker_name,
    )
    report = module.worker_env_reuse_report(**args)
    before = _review_marker_tree(tmp_path)

    def touch(*args, **kwargs):
        raise AssertionError("Temporary file reached before collision refusal")

    monkeypatch.setattr(module.tempfile, "NamedTemporaryFile", touch)
    with pytest.raises(ValueError, match="input|collision|alias"):
        if entrypoint == "api":
            module.write_marker(report)
        else:
            module.main(
                [
                    "--worker-pyproject",
                    str(args["worker_pyproject"]),
                    "--worker-copy",
                    str(copy),
                    "--manifest-file",
                    str(extra),
                    "--marker-name",
                    marker_name,
                    "--write-marker",
                ]
            )
    assert _review_marker_tree(tmp_path) == before


@pytest.mark.parametrize("destination", ["input", "other-marker", "missing-parent"])
def test_review_marker_destination_substitution_refuses_before_touch(
    monkeypatch, tmp_path, destination
):
    module, _project, args = _report_fixture(tmp_path)
    report = module.worker_env_reuse_report(**args)
    marker = module.write_marker(report)
    other = tmp_path / "other-marker.json"
    other.write_text("preserved existing marker\n")
    substituted = dict(
        report,
        marker=str(
            {
                "input": args["worker_pyproject"],
                "other-marker": other,
                "missing-parent": tmp_path / "absent/marker.json",
            }[destination]
        ),
    )
    before = _review_marker_tree(tmp_path)

    def touch(*args, **kwargs):
        raise AssertionError("Temporary file reached before destination refusal")

    monkeypatch.setattr(module.tempfile, "NamedTemporaryFile", touch)
    with pytest.raises(ValueError, match="destination|input"):
        module.write_marker(substituted)
    assert _review_marker_tree(tmp_path) == before
    assert marker.read_bytes() == Path(report["marker"]).read_bytes()


def test_review_owned_corrupt_marker_explicit_recovery_and_retry(tmp_path):
    module, _project, args = _report_fixture(tmp_path)
    marker = module.write_marker(module.worker_env_reuse_report(**args))
    inputs = {str(p): p.read_bytes() for p in (args["worker_pyproject"],)}
    marker.write_bytes(b"{owned corrupt marker")
    assert module.worker_env_reuse_report(**args)["reason"] == "marker-invalid"
    module.write_marker(module.worker_env_reuse_report(**args))
    assert module.worker_env_reuse_report(**args)["status"] == "reuse"
    module.write_marker(module.worker_env_reuse_report(**args))
    assert all(Path(p).read_bytes() == content for p, content in inputs.items())
