from __future__ import annotations

import importlib.util
import json
import runpy
import subprocess
import sys
from pathlib import Path

import pytest


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


def test_repo_python_paths_deduplicates_extra_paths() -> None:
    module = _load_module()
    src = module.REPO_ROOT / "src"

    paths = module._repo_python_paths([src, src])

    assert paths.count(str(src.resolve())) == 1


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


def test_run_scenario_rejects_invalid_loop_counts() -> None:
    module = _load_module()
    scenario = module.PerfScenario("demo", "demo scenario", ("python", "-V"))

    with pytest.raises(ValueError, match="repeats"):
        module.run_scenario(scenario, repeats=0, warmups=0)
    with pytest.raises(ValueError, match="warmups"):
        module.run_scenario(scenario, repeats=1, warmups=-1)


def test_run_scenario_single_sample_has_zero_stdev() -> None:
    module = _load_module()
    scenario = module.PerfScenario("demo", "demo scenario", ("python", "-V"))
    clock = iter([0.0, 0.4])

    def _fake_time():
        return next(clock)

    def _fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    result = module.run_scenario(
        scenario,
        repeats=1,
        warmups=0,
        runner=_fake_run,
        time_fn=_fake_time,
    )

    assert result.stdev_seconds == 0.0
    assert result.min_seconds == 0.4
    assert result.max_seconds == 0.4


def test_custom_command_and_scenario_resolution_errors() -> None:
    module = _load_module()

    with pytest.raises(ValueError, match="at least one token"):
        module._custom_command_scenario(())
    with pytest.raises(ValueError, match="exactly one"):
        module._resolve_scenarios(type("Args", (), {"command": ["python -V", "python -c pass"], "scenario": None})())

    selected = module._resolve_scenarios(type("Args", (), {"command": None, "scenario": ["base-worker-import"]})())

    assert [scenario.name for scenario in selected] == ["base-worker-import"]


def test_render_human_marks_failed_results() -> None:
    module = _load_module()
    result = module.PerfResult(
        scenario="demo",
        description="demo scenario",
        command=["python", "-V"],
        repeats=1,
        warmups=0,
        samples=[module.PerfSample(iteration=1, wall_seconds=0.5, returncode=3)],
        failures=1,
        median_seconds=0.5,
        mean_seconds=0.5,
        min_seconds=0.5,
        max_seconds=0.5,
        stdev_seconds=0.0,
    )

    rendered = module._render_human([result])

    assert "demo: FAILED" in rendered
    assert "samples: 1:0.5000s(rc=3)" in rendered


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


def test_main_lists_scenarios_and_renders_human(monkeypatch, capsys) -> None:
    module = _load_module()

    assert module.main(["--list-scenarios"]) == 0
    assert "base-worker-import" in capsys.readouterr().out

    fake_result = module.PerfResult(
        scenario="base-worker-import",
        description="Shared base worker dispatcher import startup.",
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

    assert module.main(["--scenario", "base-worker-import", "--repeats", "1", "--warmups", "0"]) == 0
    assert "base-worker-import: OK" in capsys.readouterr().out


def test_main_exits_on_invalid_custom_command(capsys) -> None:
    module = _load_module()

    with pytest.raises(SystemExit) as exc:
        module.main(["--command", "python -V", "--command", "python -c pass"])

    assert exc.value.code == 2
    assert "use exactly one" in capsys.readouterr().err


def test_script_entrypoint_lists_scenarios(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", [str(MODULE_PATH), "--list-scenarios"])

    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(MODULE_PATH), run_name="__main__")

    assert exc.value.code == 0
    assert "base-worker-import" in capsys.readouterr().out
