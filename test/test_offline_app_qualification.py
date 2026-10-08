from __future__ import annotations
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "offline_app_qualification",
    ROOT / "tools/testing/agilab_offline_app_qualification.py",
)
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


def manifest(tmp_path, **updates):
    value = {
        "schema": tool.SCHEMA,
        "sources": [{"root": str(tmp_path), "revision": "a" * 40, "paths": ["app"]}],
        "checks": [
            {
                "id": "real_science",
                "app": "example_project",
                "layer": "science",
                "scope": "one explicit real worker check",
                "argv": [sys.executable, "-c", "print(42)"],
                "cwd": str(tmp_path),
                "control_python": sys.executable,
            }
        ],
    }
    value.update(updates)
    path = tmp_path / "example_app_offline_qualification_manifest.json"
    path.write_text(json.dumps(value))
    return path, value


@pytest.mark.parametrize(
    "changes",
    [
        {"sources": []},
        {"sources": [{"root": "/tmp", "revision": "a" * 40, "paths": ["../escape"]}]},
        {"sources": [{"root": "relative", "revision": "a" * 40, "paths": ["app"]}]},
        {"checks": []},
    ],
)
def test_manifest_rejects_unpinned_or_unsafe_scope(tmp_path, changes):
    path, _ = manifest(tmp_path, **changes)
    with pytest.raises(ValueError):
        tool.read_manifest(path)


def test_manifest_rejects_duplicate_ids(tmp_path):
    path, value = manifest(tmp_path)
    value["checks"].append(dict(value["checks"][0]))
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="duplicate"):
        tool.read_manifest(path)


def test_junit_counts_actual_cases_and_skips(tmp_path):
    path = tmp_path / "example_science_junit.xml"
    path.write_text(
        '<testsuites><testsuite tests="999"><testcase/><testcase><skipped/></testcase><testcase><failure/></testcase></testsuite></testsuites>'
    )
    assert tool.junit_summary(path) == {
        "tests": 3,
        "passed": 1,
        "skipped": 1,
        "failed": 1,
        "errors": 0,
    }


def mock_sandbox_exec_presence(monkeypatch, *, available):
    original_is_file = tool.Path.is_file

    def is_file(path):
        if str(path) == "/usr/bin/sandbox-exec":
            return available
        return original_is_file(path)

    monkeypatch.setattr(tool.Path, "is_file", is_file)


@pytest.mark.parametrize("system", ["Linux", "Windows", "Darwin"])
def test_unsupported_backend_refuses_before_execution(monkeypatch, tmp_path, system):
    path, _ = manifest(tmp_path)
    output = tmp_path / "unsupported_platform_qualification_evidence"
    monkeypatch.setattr(tool.platform, "system", lambda: system)
    mock_sandbox_exec_presence(monkeypatch, available=False)

    def unexpected_call(*args, **kwargs):
        pytest.fail("Unsupported backend must be rejected before execution")

    monkeypatch.setattr(tool, "source_snapshot", unexpected_call)
    monkeypatch.setattr(tool, "execute", unexpected_call)
    with pytest.raises(ValueError, match="macOS sandbox-exec"):
        tool.run(path, output)
    assert not output.exists()


def fake_run(
    monkeypatch,
    tmp_path,
    *,
    junit=None,
    drift=False,
    missing_module=False,
    manifest_drift=False,
    json_evidence=False,
):
    path, value = manifest(tmp_path)
    if junit:
        value["checks"][0]["junit"] = "example_science_junit.xml"
    if missing_module:
        value["checks"][0]["env"] = {"AGI_INTERNET_ON": "1"}
    if json_evidence:
        value["checks"][0]["json_evidence"] = "nested/example_validation.json"
    path.write_text(json.dumps(value))
    calls = []

    def snapshot(sources):
        calls.append(1)
        return [
            {
                "revision": "a" * 40,
                "bytes": "changed" if drift and len(calls) > 1 else "original",
            }
        ]

    monkeypatch.setattr(tool, "source_snapshot", snapshot)
    monkeypatch.setattr(tool.platform, "system", lambda: "Darwin")
    # Unit tests simulate the complete macOS backend, including its executable.
    mock_sandbox_exec_presence(monkeypatch, available=True)

    def probe(argv, **kwargs):
        assert kwargs["env"]["AGI_INTERNET_ON"] == "0"
        return subprocess.CompletedProcess(
            argv,
            0,
            json.dumps(
                {"external_errno": 1, "child_external_errno": 1, "loopback": "denied"}
            ),
            "",
        )

    monkeypatch.setattr(tool.subprocess, "run", probe)

    def execute(argv, *, stdout, stderr, **kwargs):
        stdout.write_text(
            "ModuleNotFoundError: No module named 'noise'\n"
            if missing_module
            else "done\n"
        )
        stderr.write_text("")
        if junit:
            (stdout.parent / "example_science_junit.xml").write_text(junit)
        if manifest_drift:
            path.write_text(json.dumps(dict(value, scope="replaced after execution")))
        if json_evidence:
            evidence = stdout.parent / "nested/example_validation.json"
            evidence.parent.mkdir()
            evidence.write_text(json.dumps({"status": "passed"}))
        return {
            "exit_code": 1 if missing_module else 0,
            "timed_out": False,
            "duration_seconds": 0,
            "stdout": {
                "path": stdout.name,
                "sha256": tool.digest(stdout),
                "size": stdout.stat().st_size,
            },
            "stderr": {"path": stderr.name, "sha256": tool.digest(stderr), "size": 0},
        }

    monkeypatch.setattr(tool, "execute", execute)
    return tool.run(path, tmp_path / "example_offline_qualification_evidence")


def test_all_skipped_is_blocked_and_other_layers_unqualified(monkeypatch, tmp_path):
    result = fake_run(
        monkeypatch,
        tmp_path,
        junit="<testsuite><testcase><skipped/></testcase></testsuite>",
    )
    assert result["status"] == "incomplete"
    assert result["checks"][0]["reason"] == "no_passing_executed_tests"
    assert result["apps"]["example_project"]["layers"] == {
        "notebook": "not_qualified",
        "science": "blocked",
        "web": "not_qualified",
    }


def test_junit_failures_remain_failed_even_with_zero_process_exit(
    monkeypatch, tmp_path
):
    result = fake_run(
        monkeypatch,
        tmp_path,
        junit="<testsuite><testcase><failure/></testcase></testsuite>",
    )
    assert result["checks"][0]["status"] == "failed"


def test_changed_source_invalidates_successful_commands(monkeypatch, tmp_path):
    result = fake_run(monkeypatch, tmp_path, drift=True)
    assert result["status"] == "incomplete"
    assert result["source_integrity"]["status"] == "failed"


def test_missing_module_in_stdout_is_provisional_block(monkeypatch, tmp_path):
    result = fake_run(monkeypatch, tmp_path, missing_module=True)
    assert result["checks"][0]["reason"] == "missing_preinstalled_module"


def test_source_snapshot_refuses_root_escape_symlink(monkeypatch, tmp_path):
    external = tmp_path.parent / (tmp_path.name + "_external.py")
    external.write_text("external")
    (tmp_path / "app.py").symlink_to(external)

    def output(argv, **kwargs):
        return (
            "a" * 40
            if argv[-2:] == ["rev-parse", "HEAD"]
            else b""
            if "--others" in argv
            else b"app.py\\0".replace(b"\\0", b"\0")
        )

    monkeypatch.setattr(tool.subprocess, "check_output", output)
    monkeypatch.setattr(
        tool.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess([], 0)
    )
    with pytest.raises(ValueError, match="regular file"):
        tool.source_snapshot(
            [{"root": str(tmp_path), "revision": "a" * 40, "paths": ["app.py"]}]
        )


@pytest.mark.skipif(
    sys.platform != "darwin", reason="Native process tracking uses macOS libproc"
)
def test_timeout_stops_only_its_owned_process_group(tmp_path):
    child_pid = tmp_path / "example_owned_child_pid.txt"
    code = "import pathlib,subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);pathlib.Path(sys.argv[1]).write_text(str(p.pid));time.sleep(60)"
    result = tool.execute(
        [sys.executable, "-c", code, str(child_pid)],
        cwd=str(tmp_path),
        env=dict(os.environ),
        timeout=1,
        stdout=tmp_path / "example_timeout_stdout.log",
        stderr=tmp_path / "example_timeout_stderr.log",
    )
    assert result["timed_out"]
    assert child_pid.is_file()
    probe = subprocess.run(
        ["ps", "-o", "stat=", "-p", child_pid.read_text()],
        capture_output=True,
        text=True,
    )
    assert probe.returncode != 0 or probe.stdout.strip().startswith("Z")


@pytest.mark.skipif(
    sys.platform != "darwin", reason="Native process tracking uses macOS libproc"
)
def test_successful_launcher_does_not_leave_owned_server(tmp_path):
    child_pid = tmp_path / "example_owned_server_pid.txt"
    code = "import pathlib,subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c','import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(60)']);pathlib.Path(sys.argv[1]).write_text(str(p.pid));time.sleep(.2)"
    result = tool.execute(
        [sys.executable, "-c", code, str(child_pid)],
        cwd=str(tmp_path),
        env=dict(os.environ),
        timeout=3,
        stdout=tmp_path / "example_server_stdout.log",
        stderr=tmp_path / "example_server_stderr.log",
    )
    assert result["exit_code"] == 0
    probe = subprocess.run(
        ["ps", "-o", "stat=", "-p", child_pid.read_text()],
        capture_output=True,
        text=True,
    )
    assert probe.returncode != 0 or probe.stdout.strip().startswith("Z")


def test_stop_permission_error_for_live_owned_member_stays_failed(monkeypatch):
    owner = object.__new__(tool.OwnedProcesses)
    monkeypatch.setattr(owner, "observe", lambda: None)
    monkeypatch.setattr(owner, "live", lambda: [123])

    def denied(*args):
        raise PermissionError("live owned process could not be stopped")

    monkeypatch.setattr(tool.os, "kill", denied)
    with pytest.raises(PermissionError):
        owner.stop()


@pytest.mark.parametrize("status,start", [(5, (1, 2)), (1, (1, 3))])
def test_cleanup_does_not_signal_zombies_or_reused_pids(monkeypatch, status, start):
    owner = object.__new__(tool.OwnedProcesses)
    owner.owned = {123: (1, 2)}
    info = tool.ProcessInfo(
        status=status, start_seconds=start[0], start_microseconds=start[1]
    )
    monkeypatch.setattr(owner, "info", lambda pid: info)
    monkeypatch.setattr(owner, "observe", lambda: None)

    def unexpected_signal(*args):
        raise AssertionError("Must not signal a zombie or a different process identity")

    monkeypatch.setattr(tool.os, "kill", unexpected_signal)
    assert owner.stop()["status"] == "passed"


def test_manifest_drift_records_original_digest_and_invalidates_qualification(
    monkeypatch, tmp_path
):
    path, value = manifest(tmp_path)
    original_digest = hashlib.sha256(json.dumps(value).encode()).hexdigest()
    receipt = fake_run(monkeypatch, tmp_path, manifest_drift=True)
    assert receipt["manifest_sha256"] == original_digest
    assert receipt["manifest_sha256"] != tool.digest(path)
    assert receipt["manifest_integrity"]["status"] == "failed"
    assert receipt["status"] == "incomplete"
    assert not receipt["apps"]["example_project"]["qualified_requested_checks"]


def test_untracked_input_in_pinned_source_scope_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(
        tool.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0),
    )

    def git_output(argv, **kwargs):
        if "--others" in argv:
            return b"app/new_runtime.py\0"
        return "a" * 40 if "rev-parse" in argv else b"app/pinned.py\0"

    monkeypatch.setattr(tool.subprocess, "check_output", git_output)
    with pytest.raises(ValueError, match="Untracked input"):
        tool.source_snapshot(
            [{"root": str(tmp_path), "revision": "a" * 40, "paths": ["app"]}]
        )


@pytest.mark.parametrize(
    "name",
    [
        "app/injected.pyc",
        "app/injected.pyo",
        "app/__pycache__/injected.cpython-313.pyc",
        "app/.pytest_cache/runtime.py",
        "app.egg-info/runtime.py",
    ],
)
def test_cache_names_do_not_exempt_untracked_executable_inputs(
    monkeypatch, tmp_path, name
):
    untracked = tmp_path / name
    untracked.parent.mkdir(parents=True, exist_ok=True)
    untracked.write_bytes(b"untracked executable input")
    monkeypatch.setattr(
        tool.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0),
    )

    def output(argv, **kwargs):
        if "rev-parse" in argv:
            return "a" * 40
        return (name.encode() + b"\0") if "--others" in argv else b"app/pinned.py\0"

    monkeypatch.setattr(tool.subprocess, "check_output", output)
    with pytest.raises(ValueError, match="Untracked input"):
        tool.source_snapshot(
            [{"root": str(tmp_path), "revision": "a" * 40, "paths": ["app"]}]
        )


@pytest.mark.parametrize("pytest_cache", [False, True])
def test_canonical_cache_bytes_are_bound_to_the_source_snapshot(
    monkeypatch, tmp_path, pytest_cache
):
    import py_compile

    source = tmp_path / "app/pinned.py"
    source.parent.mkdir()
    source.write_text("value = 1\n")
    cache = Path(py_compile.compile(str(source), doraise=True))
    if pytest_cache:
        rewritten = cache.with_name("pinned.cpython-313-pytest-9.1.1.pyc")
        cache.rename(rewritten)
        cache = rewritten
    cache_name = cache.relative_to(tmp_path).as_posix()
    monkeypatch.setattr(
        tool.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0),
    )

    def output(argv, **kwargs):
        if "rev-parse" in argv:
            return "a" * 40
        return (
            (cache_name.encode() + b"\0") if "--others" in argv else b"app/pinned.py\0"
        )

    monkeypatch.setattr(tool.subprocess, "check_output", output)
    scope = [{"root": str(tmp_path), "revision": "a" * 40, "paths": ["app"]}]
    before = tool.source_snapshot(scope)
    assert before[0]["generated_bytecode_inputs"][cache_name]["sha256"] == tool.digest(
        cache
    )
    cache.write_bytes(cache.read_bytes() + b"changed executable bytecode")
    assert before != tool.source_snapshot(scope)


@pytest.mark.skipif(
    sys.platform != "darwin", reason="Native process tracking uses macOS libproc"
)
def test_successful_launcher_does_not_leave_detached_owned_child(tmp_path):
    child_pid = tmp_path / "example_detached_owned_child_pid.txt"
    code = "import pathlib,subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c','import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(60)'],start_new_session=True);pathlib.Path(sys.argv[1]).write_text(str(p.pid));time.sleep(.2)"
    result = tool.execute(
        [sys.executable, "-c", code, str(child_pid)],
        cwd=str(tmp_path),
        env=dict(os.environ),
        timeout=3,
        stdout=tmp_path / "example_detached_stdout.log",
        stderr=tmp_path / "example_detached_stderr.log",
    )
    assert result["exit_code"] == 0
    assert result["process_cleanup"]["observed_process_count"] >= 2
    probe = subprocess.run(
        ["ps", "-o", "stat=", "-p", child_pid.read_text()],
        capture_output=True,
        text=True,
    )
    assert probe.returncode != 0 or probe.stdout.strip().startswith("Z")


def test_nested_json_evidence_keeps_its_recoverable_relative_path(
    monkeypatch, tmp_path
):
    receipt = fake_run(monkeypatch, tmp_path, json_evidence=True)
    record = receipt["checks"][0]["json_evidence"]
    assert record["path"] == "nested/example_validation.json"
    artifacts = list(tmp_path.glob("*/" + record["path"]))
    assert len(artifacts) == 1 and tool.digest(artifacts[0]) == record["sha256"]


def test_file_scope_binds_sibling_cache_that_normal_import_executes(
    monkeypatch, tmp_path
):
    import marshal
    import py_compile

    source = tmp_path / "pinned.py"
    source.write_text("VALUE = 1\n")
    cache = Path(py_compile.compile(str(source), doraise=True))
    monkeypatch.setattr(
        tool.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0),
    )

    def output(argv, **kwargs):
        if "rev-parse" in argv:
            return "a" * 40
        return b"" if "--others" in argv else b"pinned.py\0"

    monkeypatch.setattr(tool.subprocess, "check_output", output)
    scope = [{"root": str(tmp_path), "revision": "a" * 40, "paths": ["pinned.py"]}]
    before = tool.source_snapshot(scope)
    cache.write_bytes(
        cache.read_bytes()[:16]
        + marshal.dumps(compile("VALUE = 2\n", str(source), "exec"))
    )
    spec = importlib.util.spec_from_file_location(
        "qualification_cache_import_repro", source
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.VALUE == 2 and source.read_text() == "VALUE = 1\n"
    assert before != tool.source_snapshot(scope)
