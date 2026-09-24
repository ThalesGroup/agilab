"""Exercise the RTX energy worker protocol with deterministic fake child pipes."""
import importlib.util
from io import BytesIO, StringIO
import itertools
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


@pytest.fixture
def runner(monkeypatch):
    def solver(settings):
        return {"objective": settings["demand"] * 2}
    monkeypatch.setitem(sys.modules, "energy_core", SimpleNamespace(solve_scenario=solver))
    path = Path(__file__).resolve().parents[1] / "src/agilab/demos/resources/milp_energy_demo_rtx/energy_runner.py"
    spec = importlib.util.spec_from_file_location("_energy_rtx_protocol", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    clock = itertools.count()
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: float(next(clock))))
    return module


def _children(runner, monkeypatch, outcome="success"):
    processes = []
    class Input(BytesIO):
        def flush(self):
            payload = json.loads(self.getvalue())
            self.owner.assignment = payload["assignments"]
            rows = [dict(case=case, pid=self.owner.pid, start_monotonic=1.0,
                         end_monotonic=2.0, result={"objective": settings["demand"] * 2})
                    for case, settings in payload["assignments"]]
            self.owner.stdout = BytesIO(b"bad json" if outcome == "bad-json"
                                        else json.dumps({"rows": rows}).encode())
        def close(self):
            pass
    class Child:
        def __init__(self, command, **kwargs):
            self.command, self.options = command, kwargs
            self.pid = 1000 + len(processes)
            self.returncode = 2 if outcome == "exit-error" else 0
            self.assignment, self.killed, self.waits = None, False, []
            self.stdin = Input()
            self.stdin.owner = self
            self.stdout = BytesIO(b"FAIL\n" if outcome == "not-ready" else b"READY\n")
            self.stderr = BytesIO(b"diagnostic\n")
            processes.append(self)
        def kill(self):
            self.killed = True
        def wait(self, timeout):
            self.waits.append(timeout)
            return self.returncode
    class Thread:
        def __init__(self, *, target, daemon):
            assert daemon
            self.target = target
        def start(self):
            self.target()
    monkeypatch.setattr(runner, "subprocess", SimpleNamespace(Popen=Child, PIPE=-1))
    monkeypatch.setattr(runner, "threading", SimpleNamespace(Thread=Thread))
    return processes


@pytest.mark.parametrize("workers", [1, 2, 8])
def test_parallel_assignments_are_partitioned_and_results_reordered(runner, monkeypatch, workers):
    processes = _children(runner, monkeypatch)
    batch = [{"demand": n + 1} for n in range(4)]
    result = runner._solve_parallel(batch, workers)
    assert [row["case"] for row in result["rows"]] == [0, 1, 2, 3]
    assert [row["result"]["objective"] for row in result["rows"]] == [2, 4, 6, 8]
    assignments = [case for proc in processes for case, _ in proc.assignment]
    assert sorted(assignments) == [0, 1, 2, 3]
    assert len(processes) == min(workers, len(batch))
    assert result["engine_seconds"] == 4.0
    for proc in processes:
        assert proc.waits == [900]
        assert not proc.killed
        assert proc.options["env"]["PYTHONPATH"].startswith(proc.options["cwd"])
        assert proc.command[1] == "-c"


@pytest.mark.parametrize("outcome,reason", [
    ("not-ready", "did not signal readiness"),
    ("exit-error", "exited with 2"), ("bad-json", "could not parse output"),
])
def test_child_protocol_failure_cannot_be_reported_as_success(runner, monkeypatch, outcome, reason):
    processes = _children(runner, monkeypatch, outcome)
    with pytest.raises(RuntimeError, match=reason):
        runner._solve_parallel([{"demand": 1}], 1)
    assert len(processes) == 1
    if outcome == "not-ready":
        assert processes[0].killed and processes[0].assignment is None


def test_worker_handshake_precedes_computed_rows(runner, monkeypatch):
    output = StringIO()
    monkeypatch.setattr(runner, "sys", SimpleNamespace(
        stdin=StringIO(json.dumps({"assignments": [[2, {"demand": 3}]]})), stdout=output))
    monkeypatch.setattr(runner, "os", SimpleNamespace(getpid=lambda: 1234))
    assert runner._worker_main() == 0
    ready, payload = output.getvalue().split("\n", 1)
    assert ready == "READY"
    row = json.loads(payload)["rows"][0]
    assert row["case"] == 2 and row["pid"] == 1234
    assert row["result"] == {"objective": 6}
    assert row["end_monotonic"] > row["start_monotonic"]


def test_benchmark_compares_actual_serial_and_parallel_evidence(runner, monkeypatch):
    _children(runner, monkeypatch)
    batch = [{"demand": 1}, {"demand": 2}]
    result = runner.run_benchmark(batch, 2)
    assert result["comparison"]["matches"] is True
    assert result["comparison"]["sequential_wall_seconds"] == result["sequential"]["wall_seconds"]
    assert result["comparison"]["parallel_wall_seconds"] == result["parallel"]["wall_seconds"]
    for corruption in (
        {"rows": []},
        {"rows": [{"case": 9, "result": {"objective": 2}}, {"case": 1, "result": {"objective": 4}}]},
        {"rows": [{"case": 0, "result": {"objective": 99}}, {"case": 1, "result": {"objective": 4}}]},
    ):
        assert runner._results_match(result["sequential"], corruption) is False

@pytest.fixture
def rtx_core():
    path = Path(__file__).resolve().parents[1] / "src/agilab/demos/resources/milp_energy_demo_rtx/energy_core.py"
    spec = importlib.util.spec_from_file_location("_energy_rtx_capacity", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "environment,affinity,quota,logical,expected",
    [
        ({}, 8, "max 100000", 16, 8),
        ({"CPU_LIMIT": "3"}, 8, "max 100000", 16, 3),
        ({"TASKSET_AFFINITY": "2", "OMP_NUM_THREADS": "4"}, 8, "max 100000", 16, 2),
        ({"CPU_LIMIT": "invalid"}, 8, "250000 100000", 16, 2),
        ({}, 8, "50000 100000", 16, 1),
        ({}, 8, "malformed", 16, 8),
        ({}, 8, "100000 0", 16, 8),
        ({}, None, None, 4, 4),
        ({}, None, None, None, 1),
        ({"CPU_LIMIT": "0"}, 8, "max 100000", 16, 1),
    ],
)
def test_rtx_cpu_budget_respects_available_limits(
    rtx_core, monkeypatch, environment, affinity, quota, logical, expected
):
    def affinity_probe(pid):
        assert pid == 0
        if affinity is None:
            raise OSError("affinity unavailable")
        return range(affinity)

    def quota_file(path, **kwargs):
        assert path == "/sys/fs/cgroup/cpu.max"
        assert kwargs == {"encoding": "utf-8"}
        if quota is None:
            raise FileNotFoundError(path)
        return StringIO(quota)

    monkeypatch.setattr(rtx_core, "os", SimpleNamespace(
        environ=environment, process_cpu_affinity=affinity_probe, cpu_count=lambda: logical
    ))
    monkeypatch.setattr(rtx_core, "open", quota_file, raising=False)
    assert rtx_core.cpu_limits() == {"effective_cpus": expected, "logical_cpus": logical or 1}


def test_rtx_cpu_budget_without_optional_affinity_api(rtx_core, monkeypatch):
    monkeypatch.setattr(rtx_core, "os", SimpleNamespace(environ={}, cpu_count=lambda: 6))
    def missing_quota(*args, **kwargs):
        raise FileNotFoundError("no cgroup")
    monkeypatch.setattr(rtx_core, "open", missing_quota, raising=False)
    assert rtx_core.cpu_limits() == {"effective_cpus": 6, "logical_cpus": 6}
