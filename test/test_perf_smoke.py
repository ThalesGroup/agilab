from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


MODULE_PATH = Path("tools/perf_smoke.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("perf_smoke_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_scenario_catalog_contains_expected_builtins() -> None:
    module = _load_module()

    scenarios = module.scenario_catalog()

    assert "orchestrate-execute-import" in scenarios
    assert "runtime-distribution-import" in scenarios
    assert "agi-page-network-map-import" in scenarios
    assert scenarios["base-worker-import"].command[0] == sys.executable


def test_run_scenario_uses_only_measured_samples_after_warmup() -> None:
    module = _load_module()
    scenario = module.PerfScenario("demo", "demo scenario", ("python", "-V"))
    clock = iter([0.0, 0.5, 1.0, 1.8, 2.0, 3.0])

    def _fake_time():
        return next(clock)

    def _fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    result = module.run_scenario(
        scenario,
        repeats=2,
        warmups=1,
        runner=_fake_run,
        time_fn=_fake_time,
    )

    assert [sample.wall_seconds for sample in result.samples] == [0.8, 1.0]
    assert result.failures == 0
    assert result.median_seconds == 0.9


def test_run_scenario_counts_failures() -> None:
    module = _load_module()
    scenario = module.PerfScenario("demo", "demo scenario", ("python", "-V"))
    clock = iter([0.0, 0.2, 1.0, 1.3])
    returncodes = iter([0, 7])

    def _fake_time():
        return next(clock)

    def _fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, next(returncodes), stdout="", stderr="")

    result = module.run_scenario(
        scenario,
        repeats=2,
        warmups=0,
        runner=_fake_run,
        time_fn=_fake_time,
    )

    assert result.failures == 1
    assert [sample.returncode for sample in result.samples] == [0, 7]


def test_main_json_for_custom_command(monkeypatch, capsys) -> None:
    module = _load_module()

    fake_result = module.PerfResult(
        scenario="custom-command",
        description="User-supplied command benchmark.",
        command=["python", "-V"],
        repeats=1,
        warmups=0,
        samples=[module.PerfSample(iteration=1, wall_seconds=0.25, returncode=0)],
        failures=0,
        median_seconds=0.25,
        mean_seconds=0.25,
        min_seconds=0.25,
        max_seconds=0.25,
        stdev_seconds=0.0,
    )

    monkeypatch.setattr(module, "run_scenario", lambda *args, **kwargs: fake_result)

    exit_code = module.main(["--command", "python -V", "--repeats", "1", "--warmups", "0", "--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["results"][0]["scenario"] == "custom-command"
    assert payload["results"][0]["median_seconds"] == 0.25
