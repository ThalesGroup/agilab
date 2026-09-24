"""Public solver isolation and container ancestry limits for the Astra energy demo."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


@pytest.fixture
def core():
    path = Path(__file__).resolve().parents[1] / "src/agilab/demos/resources/milp_energy_demo_astra/energy_core.py"
    spec = importlib.util.spec_from_file_location("_astra_energy_limits", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_public_solver_validates_before_crossing_process_boundary(core, monkeypatch):
    calls = []
    def run(settings):
        calls.append(settings)
        return {"status": "isolated-result"}
    monkeypatch.setitem(sys.modules, "energy_runner", SimpleNamespace(run_scenario=run))
    settings = core.default_settings()
    assert core.solve_scenario(settings) == {"status": "isolated-result"}
    assert calls == [core.validate_settings(settings)]
    with pytest.raises(ValueError):
        core.solve_scenario({**settings, "hours": -1})
    assert len(calls) == 1


@pytest.mark.parametrize("batch", [None, (), [], [{}], [{}] * 5])
def test_public_batch_rejects_invalid_shape_before_resource_observation(core, monkeypatch, batch):
    def forbidden():
        pytest.fail("invalid batch reached CPU probing")
    monkeypatch.setattr(core, "cpu_limits", forbidden)
    with pytest.raises(ValueError, match="Batch must contain"):
        core.validate_batch(batch, 1)


@pytest.mark.parametrize("controller", ["cpu,cpuacct", ""])
@pytest.mark.parametrize("quota", ["200000", "-1"])
def test_visible_parent_cgroup_quota_caps_child_allowance(core, monkeypatch, tmp_path, controller, quota):
    root = tmp_path / "cgroup"
    child = root / "team" / "job"
    child.mkdir(parents=True)
    (root / "team" / "cpu.cfs_quota_us").write_text(quota)
    (root / "team" / "cpu.cfs_period_us").write_text("100000")
    (child / "cpu.max").write_text("400000 100000")
    membership = tmp_path / "membership"
    membership.write_text(f"0:{controller}:/team/job\n")
    def rooted_path(value):
        if value == "/proc/self/cgroup":
            return membership
        return root / value.removeprefix("/sys/fs/cgroup").lstrip("/")
    monkeypatch.setattr(core, "Path", rooted_path)
    monkeypatch.setattr(core, "os", SimpleNamespace(
        cpu_count=lambda: 16, process_cpu_count=lambda: 8, environ={}))
    result = core.cpu_limits()
    assert result["effective_cpus"] == (2 if quota == "200000" else 4)
    assert result["limits"]["os.process_cpu_count"] == 8
    assert result["limits"]["cgroup quota"] == (2 if quota == "200000" else 4)
