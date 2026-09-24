"""Packaged benchmark CPU budgets and launch boundaries without child execution."""
import contextlib
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def astra(monkeypatch):
    root = Path(__file__).resolve().parents[1] / "src/agilab/demos/resources/free_threading_demo_astra"
    loaded = []
    for name in ("agilab_pool", "free_threading_core", "benchmark"):
        spec = importlib.util.spec_from_file_location(name, root / (name + ".py"))
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        loaded.append(module)
    return loaded[-1]


@pytest.mark.parametrize("version", [1, 2])
def test_cgroup_quota_reads_child_and_parent_limits(astra, monkeypatch, version):
    base = "/fixture/cgroup"
    if version == 2:
        files = {"/proc/self/cgroup": "0::/child", "/proc/self/mountinfo": f"1 0 0:1 / {base} rw - cgroup2 cgroup rw",
                 base + "/child/cpu.max": "250000 100000", base + "/cpu.max": "150000 100000"}
    else:
        files = {"/proc/self/cgroup": "3:cpu,cpuacct:/child", "/proc/self/mountinfo": f"1 0 0:1 / {base} rw - cgroup cgroup rw,cpu",
                 base + "/child/cpu.cfs_quota_us": "250000", base + "/child/cpu.cfs_period_us": "100000",
                 base + "/cpu.cfs_quota_us": "150000", base + "/cpu.cfs_period_us": "100000"}
    monkeypatch.setattr(astra, "_read", lambda path: files.get(str(path), ""))
    assert astra._cgroup_limits() == [2.5, 1.5]


@pytest.mark.parametrize("quota", ["max 100000", "-1 100000", "1000 0", "bad"])
def test_cgroup_unbounded_or_invalid_quota_does_not_invent_cpu_limit(astra, monkeypatch, quota):
    files = {"/proc/self/cgroup": "malformed\n0::/", "/proc/self/mountinfo":
             "malformed\n1 0 0:1 / /sys rw - tmpfs tmpfs rw\n2 0 0:2 / /fixture rw - cgroup2 cgroup rw",
             "/fixture/cpu.max": quota}
    monkeypatch.setattr(astra, "_read", lambda path: files.get(str(path), ""))
    assert astra._cgroup_limits() == []


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "invalid"])
@pytest.mark.parametrize("key", ["CPU_CORES", "SPACE_CPU_CORES"])
def test_invalid_cpu_allowance_blocks_benchmark(astra, monkeypatch, key, value):
    monkeypatch.setattr(astra, "os", SimpleNamespace(cpu_count=lambda: 8, environ={key: value}))
    with pytest.raises(ValueError, match="positive finite CPU allowance"):
        astra.effective_cpus()


def test_effective_cpu_count_uses_tightest_constraint_and_tolerates_affinity_denial(astra, monkeypatch):
    monkeypatch.setattr(astra, "os", SimpleNamespace(cpu_count=lambda: 8, process_cpu_count=lambda: 6,
        sched_getaffinity=Mock(side_effect=OSError("unsupported")), environ={"SPACE_CPU_CORES": "3.5"}))
    monkeypatch.setattr(astra, "_cgroup_limits", lambda: [2.5, 4])
    hardware = astra.effective_cpus()
    assert hardware["effective_cpus"] == 2


@pytest.mark.parametrize("after_launch", [False, True])
def test_total_budget_exhaustion_prevents_further_child_launch(astra, monkeypatch, after_launch):
    monkeypatch.setattr(astra, "effective_cpus", lambda: {"effective_cpus": 2})
    monkeypatch.setattr(astra, "benchmark_lock", contextlib.nullcontext)
    clock = Mock(side_effect=[0, 0, 51] if after_launch else [0, 51])
    monkeypatch.setattr(astra, "time", SimpleNamespace(monotonic=clock))
    launch = Mock(return_value={})
    monkeypatch.setattr(astra, "run_case", launch)
    with pytest.raises(TimeoutError, match="Total analysis time budget"):
        astra.run_benchmark(width=2, height=2, iterations=2, workers=1, repeats=1)
    assert launch.call_count == int(after_launch)


@pytest.mark.parametrize("difference", ["digest", "version"])
def test_same_work_guard_rejects_cross_case_image_or_runtime_change(astra, monkeypatch, difference):
    monkeypatch.setattr(astra, "effective_cpus", lambda: {"effective_cpus": 2})
    monkeypatch.setattr(astra, "benchmark_lock", contextlib.nullcontext)
    monkeypatch.setattr(astra, "time", SimpleNamespace(monotonic=lambda: 0))
    first = {"digest": "same-image", "before": {"version": "same-runtime"}}
    second = {"digest": "other-image" if difference == "digest" else "same-image",
              "before": {"version": "other-runtime" if difference == "version" else "same-runtime"}}
    launch = Mock(side_effect=[first, second])
    monkeypatch.setattr(astra, "run_case", launch)
    with pytest.raises(ValueError, match="Same-work verification"):
        astra.run_benchmark(width=2, height=2, iterations=2, workers=1, repeats=1)
    assert launch.call_count == 2


def test_excess_workers_rejected_before_lock_or_child_launch(astra, monkeypatch):
    monkeypatch.setattr(astra, "effective_cpus", lambda: {"effective_cpus": 1})
    lock = Mock(side_effect=AssertionError("must not acquire"))
    monkeypatch.setattr(astra, "benchmark_lock", lock)
    with pytest.raises(ValueError, match="CPU allowance"):
        astra.run_benchmark(workers=2)
    lock.assert_not_called()
