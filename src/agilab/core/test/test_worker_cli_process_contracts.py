"""Process-incarnation and cleanup contracts; no real process is signalled."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agi_node.agi_dispatcher import cli


class MissingProcess(Exception):
    pass


class DeniedProcess(Exception):
    pass


@pytest.fixture
def processes(monkeypatch):
    registry = {}

    def process(pid):
        value = registry[pid]
        if isinstance(value, Exception):
            raise value
        return value

    api = SimpleNamespace(
        Process=process,
        NoSuchProcess=MissingProcess,
        AccessDenied=DeniedProcess,
        STATUS_ZOMBIE="zombie",
        process_iter=lambda attrs: list(registry.values()),
    )
    monkeypatch.setattr(cli, "psutil", api)
    return registry


def fake_process(
    pid=41, start=10.0, command=None, cwd="/tmp", status="running", running=True
):
    return SimpleNamespace(
        pid=pid,
        create_time=lambda: start,
        cmdline=lambda: command or ["dask-worker"],
        cwd=lambda: cwd,
        status=lambda: status,
        is_running=lambda: running,
        children=lambda recursive=False: [],
        ppid=lambda: 0,
        info={"pid": pid, "cmdline": command or ["dask-worker"], "create_time": start},
    )


def fail(error):
    def call(*args, **kwargs):
        raise error

    return call


@pytest.mark.parametrize(
    "error,expected",
    [
        (MissingProcess(), None),
        (DeniedProcess(), "error"),
        (OSError(), "error"),
        (ValueError(), "error"),
    ],
)
def test_identity_requires_observable_process(processes, error, expected):
    processes[41] = error
    if expected == "error":
        with pytest.raises(
            RuntimeError, match="Cannot prove process ownership for PID 41"
        ):
            cli._process_identity(41)
    else:
        assert cli._process_identity(41) is None


@pytest.mark.parametrize(
    "cwd_error", [None, DeniedProcess(), MissingProcess(), OSError()]
)
def test_identity_preserves_start_and_command_when_cwd_unavailable(
    processes, cwd_error
):
    process = fake_process(command=["dask", "worker", "--project", "/tmp/runtime"])
    if cwd_error:
        process.cwd = fail(cwd_error)
    processes[41] = process
    assert cli._process_identity(41) == (
        process,
        10.0,
        ["dask", "worker", "--project", "/tmp/runtime"],
        None if cwd_error else Path("/tmp"),
    )


@pytest.mark.parametrize(
    "case,expected",
    [
        ("live", True),
        ("reused", False),
        ("stopped", False),
        ("zombie", False),
        ("missing", False),
        ("denied", None),
        ("io", None),
        ("invalid", None),
    ],
)
def test_incarnation_state_does_not_confuse_unknown_and_dead(processes, case, expected):
    value = fake_process(
        start=20.0 if case == "reused" else 10.0,
        running=case != "stopped",
        status="zombie" if case == "zombie" else "running",
    )
    if case in {"missing", "denied", "io", "invalid"}:
        value = {
            "missing": MissingProcess(),
            "denied": DeniedProcess(),
            "io": OSError(),
            "invalid": ValueError(),
        }[case]
    processes[41] = value
    assert cli._process_incarnation_state(41, 10.0) is expected
    assert cli._same_process_incarnation(41, 10.0) is (expected is True)


@pytest.mark.parametrize(
    "command,expected",
    [
        (None, False),
        ([], False),
        ('"unterminated', False),
        (["dask-worker", "--pid-file", "runtime/dask.pid"], False),
        (["https://example.invalid/runtime/bin/dask-worker"], False),
        (["dask", "--project="], False),
        (["dask", "--project=runtime"], True),
        (["runtime/bin/dask-worker"], True),
        (["runtime-sibling/bin/dask-worker"], False),
        (["dask", "--project", "runtime"], True),
    ],
)
def test_command_ownership_requires_exact_runtime_path(tmp_path, command, expected):
    assert (
        cli._command_belongs_to_target(
            command, tmp_path / "runtime", process_cwd=tmp_path
        )
        is expected
    )


@pytest.mark.parametrize(
    "payload,expected",
    [
        ("42", (42, None, None)),
        ('{"pid":42,"process_start_time":"","target":""}', (42, None, None)),
        (
            '{"pid":"42","process_start_time":"1.5","target":"/tmp/x"}',
            (42, 1.5, "/tmp/x"),
        ),
    ],
)
def test_pid_record_supported_formats(tmp_path, payload, expected):
    record = tmp_path / "worker.pid"
    record.write_text(payload)
    assert cli._read_pid_record(record) == expected


@pytest.mark.parametrize("payload", ["[]", "null", '"42"', '{"pid":"bad"}', "{}"])
def test_pid_record_invalid_formats_are_rejected(tmp_path, payload):
    record = tmp_path / "worker.pid"
    record.write_text(payload)
    with pytest.raises((ValueError, KeyError, TypeError)):
        cli._read_pid_record(record)


def test_poll_retains_unknown_identity_until_timeout(monkeypatch):
    ticks = iter([0, 0, 1, 3])
    monkeypatch.setattr(
        cli,
        "time",
        SimpleNamespace(monotonic=lambda: next(ticks), sleep=lambda _: None),
    )
    monkeypatch.setattr(
        cli,
        "_process_incarnation_state",
        lambda pid, start: False if pid == 1 else None,
    )
    assert cli._poll_process_incarnations_until_dead({1: 1.0, 2: 2.0}, total=2) == {2}


def test_poll_stops_when_all_incarnations_disappear(monkeypatch):
    monkeypatch.setattr(
        cli,
        "time",
        SimpleNamespace(
            monotonic=lambda: 0, sleep=lambda _: pytest.fail("unexpected sleep")
        ),
    )
    monkeypatch.setattr(cli, "_process_incarnation_state", lambda pid, start: False)
    assert cli._poll_process_incarnations_until_dead({1: 1.0}) == set()


@pytest.mark.parametrize("parent_state", [False, None])
def test_descendant_snapshot_rejects_uncertain_parent(
    monkeypatch, processes, parent_state
):
    monkeypatch.setattr(cli, "_process_incarnation_state", lambda *args: parent_state)
    starts = {41: 10.0}
    assert cli._add_child_incarnations(starts) is (parent_state is False)
    assert starts == {41: 10.0}


@pytest.mark.parametrize(
    "error,expected",
    [(MissingProcess(), True), (DeniedProcess(), False), (OSError(), False)],
)
def test_descendant_snapshot_handles_disappearing_or_inaccessible_parent(
    monkeypatch, processes, error, expected
):
    monkeypatch.setattr(cli, "_process_incarnation_state", lambda *args: True)
    processes[41] = error
    assert cli._add_child_incarnations({41: 10.0}) is expected


@pytest.mark.parametrize(
    "error,expected",
    [(MissingProcess(), True), (DeniedProcess(), False), (ValueError(), False)],
)
def test_descendant_snapshot_requires_readable_child_generation(
    monkeypatch, processes, error, expected
):
    monkeypatch.setattr(cli, "_process_incarnation_state", lambda *args: True)
    parent = fake_process()
    child = fake_process(pid=42)
    child.create_time = fail(error)
    parent.children = lambda recursive=False: [child]
    processes[41] = parent
    starts = {41: 10.0}
    assert cli._add_child_incarnations(starts) is expected
    assert starts == {41: 10.0}


def test_descendant_snapshot_ignores_reparented_pid_and_traverses_grandchild(
    monkeypatch, processes
):
    monkeypatch.setattr(cli, "_process_incarnation_state", lambda *args: True)
    parent, child, grandchild, recycled = [
        fake_process(pid=n, start=float(n)) for n in (41, 42, 43, 44)
    ]
    child.ppid = lambda: 41
    grandchild.ppid = lambda: 42
    recycled.ppid = lambda: 999
    parent.children = lambda recursive=False: [child, recycled, child]
    child.children = lambda recursive=False: [grandchild]
    processes.update({41: parent, 42: child, 43: grandchild})
    starts = {41: 41.0}
    assert cli._add_child_incarnations(starts) is True
    assert starts == {41: 41.0, 42: 42.0, 43: 43.0}


def test_target_scan_filters_siblings_and_survives_inaccessible_cwd(
    tmp_path, processes
):
    target = tmp_path / "runtime"
    own = fake_process(command=[str(target / "bin/dask-worker")])
    own.cwd = fail(DeniedProcess())
    sibling = fake_process(
        pid=42, command=[str(tmp_path / "runtime-other/bin/dask-worker")]
    )
    editor = fake_process(pid=43, command=["editor", "dask.md"])
    malformed = fake_process(pid=44, command=[str(target / "bin/dask-worker")])
    malformed.info["create_time"] = "invalid"
    processes.update({41: own, 42: sibling, 43: editor, 44: malformed})
    assert cli._target_dask_processes(target) == {41: 10.0}


def test_signal_requires_authorized_incarnation(monkeypatch):
    sent = []
    monkeypatch.setattr(
        cli, "os", SimpleNamespace(kill=lambda *args: sent.append(args))
    )
    monkeypatch.setattr(cli, "_same_process_incarnation", lambda pid, start: pid == 41)
    assert cli.kill_pids({41, 42, 43}, 15, process_starts={41: 1.0, 42: 2.0}) == set()
    assert sent == [(41, 15)]


def test_unlink_pid_records_reports_partial_failure(tmp_path, monkeypatch):
    missing, denied, normal = [
        tmp_path / name for name in ("missing.pid", "denied.pid", "normal.pid")
    ]
    denied.write_text("1")
    normal.write_text("2")
    original = Path.unlink

    def unlink(path, *args, **kwargs):
        if path == denied:
            raise PermissionError("read-only record")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", unlink)
    assert cli._unlink_pid_files({missing, denied, normal}) is False
    assert denied.exists() and not normal.exists()


@pytest.mark.parametrize(
    "mode", ["active", "rmtree-failed", "rmtree-noop", "absent", "success"]
)
def test_clean_requires_runtime_to_be_absent_after_removal(tmp_path, monkeypatch, mode):
    home = tmp_path / "home"
    target = home / "wenv" / "worker"
    target.mkdir(parents=True)
    (target / "data").write_text("retain until safe")
    if mode == "absent":
        (target / "data").unlink()
        target.rmdir()
    monkeypatch.setattr(
        cli, "_target_dask_processes", lambda _: {41: 10.0} if mode == "active" else {}
    )
    if mode == "rmtree-failed":
        monkeypatch.setattr(
            cli, "shutil", SimpleNamespace(rmtree=fail(PermissionError("locked")))
        )
    elif mode == "rmtree-noop":
        monkeypatch.setattr(
            cli, "shutil", SimpleNamespace(rmtree=lambda *args, **kwargs: None)
        )
    assert cli.clean("wenv/worker", home_path=home, cwd_path=home) is (
        mode in {"absent", "success"}
    )
    assert target.exists() is (mode not in {"absent", "success"})


@pytest.mark.parametrize(
    "case,expected,retained",
    [
        ("valid", True, False),
        ("legacy", True, False),
        ("missing", True, False),
        ("reused", True, False),
        ("legacy-reused", True, False),
        ("wrong-command", False, True),
        ("malformed", False, True),
        ("other-target", True, True),
        ("excluded", True, True),
        ("identity-denied", False, True),
        ("upgrade-failed", True, False),
        ("unauthorized", False, True),
        ("excluded-active", False, True),
        ("children-uncertain", False, True),
        ("survivor", False, True),
        ("residual", False, True),
    ],
)
def test_scoped_stop_preserves_evidence_until_ownership_and_death_proven(
    tmp_path, monkeypatch, case, expected, retained
):
    target = tmp_path / "runtime"
    target.mkdir()
    record = target / "dask_worker.pid"
    payload = {"pid": 41, "process_start_time": 10.0, "target": str(target)}
    if case == "other-target":
        payload["target"] = str(tmp_path / "other")
    record.write_text(
        "41"
        if case.startswith("legacy")
        else "broken"
        if case == "malformed"
        else json.dumps(payload)
    )
    command = [str(target / "bin/dask-worker")]
    if case == "wrong-command":
        command = ["editor", "dask.md"]
    start = 20.0 if case == "reused" else 10.0
    if case == "legacy-reused":
        start = record.stat().st_mtime + 100
    identity = (object(), start, command, target)
    monkeypatch.setattr(
        cli,
        "_process_identity",
        fail(RuntimeError("ownership unavailable"))
        if case == "identity-denied"
        else lambda pid: None if case == "missing" else identity,
    )
    if case == "upgrade-failed":
        monkeypatch.setattr(
            cli, "_write_pid_record", fail(PermissionError("read-only"))
        )
    states = [
        {99: 1.0}
        if case == "unauthorized"
        else {41: 10.0}
        if case == "excluded-active"
        else {},
        {99: 1.0} if case == "residual" else {},
    ]
    monkeypatch.setattr(cli, "_target_dask_processes", lambda _: states.pop(0))
    monkeypatch.setattr(
        cli, "_add_child_incarnations", lambda _: case != "children-uncertain"
    )
    signals = []
    monkeypatch.setattr(
        cli,
        "kill_pids",
        lambda pids, sig, **kwargs: signals.append(
            (set(pids), sig, dict(kwargs["process_starts"]))
        )
        or set(),
    )
    monkeypatch.setattr(
        cli,
        "_poll_process_incarnations_until_dead",
        lambda starts: {41} if case == "survivor" else set(),
    )
    assert (
        cli._scoped_kill(
            target, {41} if case in {"excluded", "excluded-active"} else set()
        )
        is expected
    )
    assert record.exists() is retained
    if case in {
        "wrong-command",
        "malformed",
        "other-target",
        "excluded",
        "identity-denied",
        "missing",
        "reused",
        "legacy-reused",
        "excluded-active",
    }:
        assert signals == []
    else:
        assert signals[0] == ({41}, cli.signal.SIGTERM, {41: 10.0})
    if case == "survivor" and hasattr(cli.signal, "SIGKILL"):
        assert signals[-1][1] == cli.signal.SIGKILL


@pytest.mark.parametrize(
    "value", [None, 42, b"worker", "", " ", "\x00", ".", "..", "C:worker", "/"]
)
def test_destructive_path_rejects_malformed_or_root_targets(tmp_path, value):
    with pytest.raises(ValueError):
        cli.safe_destructive_path(value, roots=[tmp_path])


def test_destructive_path_confines_symlinks_and_protected_paths(tmp_path):
    root = tmp_path / "trusted"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "escape").symlink_to(outside, target_is_directory=True)
    for target, roots, protected in [
        (root / "escape" / "data", [root], []),
        (root, [root], []),
        (root / "data", [], []),
        (root / "data", [root], [root / "data"]),
    ]:
        with pytest.raises(ValueError):
            cli.safe_destructive_path(target, roots=roots, protected_paths=protected)
    assert cli.safe_destructive_path(root / "data", roots=[root]) == root / "data"


@pytest.mark.parametrize(
    "member", ["/absolute", "../escape", "C:relative", "C:\\absolute", "..\\escape"]
)
@pytest.mark.parametrize("method", ["getnames", "namelist"])
def test_archive_confinement_rejects_both_platform_traversals(tmp_path, member, method):
    archive = SimpleNamespace(**{method: lambda: ["safe/data", member]})
    with pytest.raises(RuntimeError, match="Unsafe archive"):
        cli.validate_archive_members_stay_within_dest(archive, tmp_path)


def test_archive_without_inventory_is_noop(tmp_path):
    cli.validate_archive_members_stay_within_dest(object(), tmp_path)


def test_lazy_process_dependency_reports_missing_package(monkeypatch):
    lazy = cli._LazyPsutil()
    monkeypatch.setattr(
        cli,
        "importlib",
        SimpleNamespace(import_module=fail(ImportError("not installed"))),
    )
    with pytest.raises(RuntimeError, match="psutil is required"):
        lazy.Process


def test_lazy_process_dependency_supports_patch_restore_without_reimports(monkeypatch):
    module = SimpleNamespace(Process="original")
    imports = []
    monkeypatch.setattr(
        cli,
        "importlib",
        SimpleNamespace(import_module=lambda name: imports.append(name) or module),
    )
    lazy = cli._LazyPsutil()
    lazy.Process = "replacement"
    assert lazy.Process == "replacement"
    del lazy.Process
    assert not hasattr(module, "Process")
    lazy._module = SimpleNamespace(Process="restored")
    assert lazy.Process == "restored"
    assert imports == ["psutil"]
