from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "src/agilab/apps/builtin/r_runtime_bridge_project"
APP_SRC = APP_ROOT / "src"


def _clear_r_stage_modules() -> None:
    for name in list(sys.modules):
        if (
            name == "r_runtime_bridge"
            or name.startswith("r_runtime_bridge.")
            or name == "r_runtime_bridge_worker"
            or name.startswith("r_runtime_bridge_worker.")
        ):
            sys.modules.pop(name, None)


@pytest.fixture(autouse=True)
def _r_stage_source_path(monkeypatch):
    _clear_r_stage_modules()
    monkeypatch.syspath_prepend(str(APP_SRC))
    yield
    _clear_r_stage_modules()


def test_run_r_stage_writes_json_logs_artifacts_and_manifest(tmp_path):
    from r_runtime_bridge.r_runtime_adapter import run_r_stage

    script = tmp_path / "summarize.R"
    script.write_text("# fake R script\n", encoding="utf-8")

    def fake_runner(cmd, **kwargs):
        input_path = Path(cmd[2])
        output_path = Path(cmd[3])
        artifact_dir = Path(cmd[4])
        payload = json.loads(input_path.read_text(encoding="utf-8"))
        values = [float(value) for value in payload["x"]]
        artifact_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / "summary.txt").write_text("n=5\n", encoding="utf-8")
        output_path.write_text(
            json.dumps(
                {"n": len(values), "mean": sum(values) / len(values), "sd": 1.58113883}
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="note\n")

    result = run_r_stage(
        script,
        {"x": [1, 2, 3, 4, 5]},
        tmp_path / "evidence",
        rscript="Rscript",
        runner=fake_runner,
    )

    assert result.output == {"n": 5, "mean": 3.0, "sd": 1.58113883}
    assert json.loads(result.input_path.read_text(encoding="utf-8")) == {
        "x": [1, 2, 3, 4, 5]
    }
    assert result.stdout_path.read_text(encoding="utf-8") == "ok\n"
    assert result.stderr_path.read_text(encoding="utf-8") == "note\n"
    assert (result.artifact_dir / "summary.txt").is_file()

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["runtime"] == "Rscript + JSON"
    assert manifest["command"][:2] == ["Rscript", str(script.resolve(strict=False))]
    assert manifest["artifacts"]["output"]["path"] == "output.json"
    assert manifest["artifacts"]["artifact:summary.txt"]["sha256"]

    summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
    assert summary["metrics"] == {"n": 5, "mean": 3.0, "sd": 1.58113883}
    assert summary["artifacts"]["summary"]["path"] == "r_stage_summary.json"


def test_run_r_stage_failure_keeps_captured_logs(tmp_path):
    from r_runtime_bridge.r_runtime_adapter import RStageExecutionError, run_r_stage

    script = tmp_path / "summarize.R"
    script.write_text("# fake R script\n", encoding="utf-8")

    def fake_runner(cmd, **_kwargs):
        return subprocess.CompletedProcess(cmd, 7, stdout="partial\n", stderr="boom\n")

    with pytest.raises(RStageExecutionError, match="exit code 7"):
        run_r_stage(script, {"x": [1]}, tmp_path / "evidence", runner=fake_runner)

    assert (tmp_path / "evidence" / "stage_stdout.log").read_text(
        encoding="utf-8"
    ) == "partial\n"
    assert (tmp_path / "evidence" / "stage_stderr.log").read_text(
        encoding="utf-8"
    ) == "boom\n"


def test_run_r_stage_rejects_script_outside_app_root(tmp_path):
    from r_runtime_bridge.r_runtime_adapter import RStageExecutionError, run_r_stage

    app_root = tmp_path / "app"
    app_root.mkdir()
    script = tmp_path / "outside.R"
    script.write_text("# fake R script\n", encoding="utf-8")

    def fake_runner(*_args, **_kwargs):
        raise AssertionError("runner should not be called")

    with pytest.raises(RStageExecutionError, match="inside the app root"):
        run_r_stage(
            script,
            {"x": [1]},
            tmp_path / "evidence",
            runner=fake_runner,
            app_root=app_root,
        )


def test_r_runtime_bridge_ships_default_script_and_conceptual_view() -> None:
    script = APP_ROOT / "scripts" / "summarize.R"
    conceptual_view = APP_ROOT / "pipeline_view.dot"

    assert script.is_file()
    assert "jsonlite" in script.read_text(encoding="utf-8")
    assert conceptual_view.read_text(encoding="utf-8").strip().startswith("digraph ")


def test_run_r_stage_reports_missing_script_before_invoking_runner(tmp_path):
    from r_runtime_bridge.r_runtime_adapter import RStageExecutionError, run_r_stage

    runner_called = False

    def fake_runner(*_args, **_kwargs):
        nonlocal runner_called
        runner_called = True
        raise AssertionError("runner should not be called")

    output_dir = tmp_path / "evidence"
    with pytest.raises(RStageExecutionError, match="R stage script not found"):
        run_r_stage(
            tmp_path / "missing.R",
            {"x": [1]},
            output_dir,
            runner=fake_runner,
        )

    assert runner_called is False
    stderr = (output_dir / "stage_stderr.log").read_text(encoding="utf-8")
    assert "R stage script not found" in stderr
    assert len(stderr) < 512


def test_run_r_stage_redacts_logs_and_manifest_secrets(tmp_path):
    from r_runtime_bridge.r_runtime_adapter import run_r_stage

    app_root = tmp_path / "app"
    script = app_root / "scripts" / "summarize.R"
    script.parent.mkdir(parents=True)
    script.write_text("# fake R script\n", encoding="utf-8")

    def fake_runner(cmd, **_kwargs):
        output_path = Path(cmd[3])
        output_path.write_text(
            json.dumps(
                {
                    "n": 1,
                    "mean": 1,
                    "sd": 0,
                    "api_token": "sk-proj-" + ("a" * 24),
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout="OPENAI_API_KEY=sk-proj-" + ("b" * 24) + "\n",
            stderr="Bearer " + ("c" * 24) + "\n",
        )

    result = run_r_stage(
        script,
        {"x": [1], "service_token": "github_pat_" + ("d" * 24)},
        tmp_path / "evidence",
        runner=fake_runner,
        app_root=app_root,
    )

    assert "sk-proj-" not in result.stdout_path.read_text(encoding="utf-8")
    assert "Bearer c" not in result.stderr_path.read_text(encoding="utf-8")
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
    assert manifest["inputs"]["service_token"] == "<redacted>"
    assert manifest["inputs"]["x"] == [1]
    assert manifest["result"]["api_token"] == "<redacted>"
    assert summary["result"]["api_token"] == "<redacted>"


def test_r_runtime_bridge_manager_round_trips_settings(tmp_path):
    from r_runtime_bridge import RRuntimeBridge

    class FakeEnv(SimpleNamespace):
        _is_managed_pc = False
        verbose = 0
        app = "r_runtime_bridge_project"
        target = "r_runtime_bridge_project"
        active_app = APP_ROOT

        def resolve_share_path(self, value):
            path = Path(value)
            return path if path.is_absolute() else self.share_root / path

    env = FakeEnv(share_root=tmp_path / "share", AGILAB_EXPORT_ABS=tmp_path / "export")
    manager = RRuntimeBridge(env, x=[2.0, 4.0], reset_target=True)

    assert manager.data_out == tmp_path / "share" / "r_runtime_bridge" / "evidence"
    assert (
        manager.analysis_artifact_dir
        == tmp_path / "export" / "r_runtime_bridge_project" / "r_runtime_bridge"
    )
    work_plan, metadata, *_ = manager.build_distribution("3")
    assert work_plan == [[["r_runtime_bridge"]], [], []]
    assert metadata[0] == [{"run": "r_runtime_bridge", "work_items": 1}]

    share_root = tmp_path / "share"
    marker = share_root / "important.txt"
    marker.write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError, match="confinement root"):
        RRuntimeBridge(env, data_out=Path("."), reset_target=True)
    assert marker.read_text(encoding="utf-8") == "keep"

    settings = tmp_path / "settings.toml"
    manager.to_toml(settings)
    reloaded = RRuntimeBridge.from_toml(env, settings, timeout_seconds=30)
    assert reloaded.args.x == [2.0, 4.0]
    assert reloaded.args.timeout_seconds == 30


def test_r_runtime_bridge_reducer_merges_worker_summaries(tmp_path):
    from r_runtime_bridge.reduction import (
        build_reduce_artifact,
        partial_from_r_runtime_bridge_summary,
        write_reduce_artifact,
    )

    summaries = [
        {
            "metrics": {"n": 5, "mean": 3.0, "sd": 1.58113883},
            "artifacts": {"output": {"path": "output.json"}},
        },
        {
            "metrics": {"n": 3, "mean": 2.0, "sd": 1.0},
            "artifacts": {
                "output": {"path": "output.json"},
                "extra": {"path": "artifacts/a.txt"},
            },
        },
    ]
    partials = [
        partial_from_r_runtime_bridge_summary(summary, partial_id=f"run-{index}")
        for index, summary in enumerate(summaries)
    ]

    artifact = build_reduce_artifact(partials)

    assert artifact.payload["run_count"] == 2
    assert artifact.payload["n_sum"] == 8
    assert artifact.payload["mean_mean"] == 2.5
    assert artifact.payload["artifact_paths"] == ["artifacts/a.txt", "output.json"]

    output_path = write_reduce_artifact(summaries, tmp_path, worker_id=9)
    written = json.loads(output_path.read_text(encoding="utf-8"))
    assert output_path.name == "reduce_summary_worker_9.json"
    assert written["payload"]["run_count"] == 2


def test_r_runtime_bridge_worker_exports_reduce_and_analysis_artifacts(
    tmp_path, monkeypatch
):
    import r_runtime_bridge_worker.r_runtime_bridge_worker as worker_mod

    def fake_build(*, output_dir, script_path, x, rscript, timeout_seconds, app_root):
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "output.json").write_text(
            json.dumps({"n": len(x), "mean": 3.0, "sd": 1.58113883}),
            encoding="utf-8",
        )
        (output_dir / "stage_stdout.log").write_text("ok\n", encoding="utf-8")
        (output_dir / "stage_stderr.log").write_text("note\n", encoding="utf-8")
        (output_dir / "run_manifest.json").write_text("{}", encoding="utf-8")
        (output_dir / "artifacts").mkdir(exist_ok=True)
        (output_dir / "artifacts" / "summary.txt").write_text("n=5\n", encoding="utf-8")
        return {
            "app_root": str(app_root),
            "metrics": {"n": len(x), "mean": 3.0, "sd": 1.58113883},
            "artifacts": {
                "output": {"path": "output.json"},
                "stdout": {"path": "stage_stdout.log"},
                "stderr": {"path": "stage_stderr.log"},
                "artifact:summary.txt": {"path": "artifacts/summary.txt"},
            },
        }

    class FakeEnv(SimpleNamespace):
        target = "r_runtime_bridge_project"
        active_app = APP_ROOT

        def resolve_share_path(self, value):
            path = Path(value)
            return path if path.is_absolute() else self.share_root / path

    monkeypatch.setattr(worker_mod, "build_r_runtime_bridge_artifacts", fake_build)
    worker = worker_mod.RRuntimeBridgeWorker()
    worker.env = FakeEnv(
        share_root=tmp_path / "share", AGILAB_EXPORT_ABS=tmp_path / "export"
    )
    worker.args = {
        "data_out": "r_runtime_bridge/evidence",
        "script_path": "scripts/summarize.R",
        "rscript": "Rscript",
        "x": [1, 2, 3, 4, 5],
        "timeout_seconds": 120,
        "reset_target": True,
    }
    worker._worker_id = 4

    worker.start()
    df = worker.work_pool("r_runtime_bridge")

    assert df.to_dict(orient="records")[0]["worker_id"] == 4
    assert (worker.data_out / "output.json").is_file()
    assert (worker.data_out / "reduce_summary_worker_4.json").is_file()
    assert (worker.artifact_dir / "output.json").is_file()
    assert (worker.artifact_dir / "reduce_summary_worker_4.json").is_file()


def test_r_runtime_bridge_worker_rejects_absolute_output_outside_share(tmp_path):
    import r_runtime_bridge_worker.r_runtime_bridge_worker as worker_mod

    share_root = tmp_path / "share"
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = outside / "important.txt"
    marker.write_text("keep", encoding="utf-8")

    class FakeEnv(SimpleNamespace):
        target = "r_runtime_bridge_project"
        active_app = APP_ROOT

        def resolve_share_path(self, value):
            candidate = Path(value)
            return candidate if candidate.is_absolute() else self.share_root / candidate

    worker = worker_mod.RRuntimeBridgeWorker()
    worker.env = FakeEnv(
        share_root=share_root,
        AGILAB_EXPORT_ABS=tmp_path / "export",
    )
    worker.args = {
        "data_out": outside,
        "script_path": "scripts/summarize.R",
        "reset_target": True,
    }

    with pytest.raises(ValueError, match="active share root"):
        worker.start()

    assert marker.read_text(encoding="utf-8") == "keep"


def test_r_runtime_bridge_actual_rscript_contract_when_available(tmp_path):
    rscript = shutil.which("Rscript")
    if not rscript:
        pytest.skip("Rscript is not installed")
    jsonlite = subprocess.run(
        [rscript, "-e", "library(jsonlite)"],
        text=True,
        capture_output=True,
        check=False,
    )
    if jsonlite.returncode != 0:
        pytest.skip("R jsonlite package is not installed")

    from r_runtime_bridge import build_r_runtime_bridge_artifacts

    summary = build_r_runtime_bridge_artifacts(
        output_dir=tmp_path / "evidence",
        script_path=APP_ROOT / "scripts" / "summarize.R",
        x=[1, 2, 3, 4, 5],
        rscript=rscript,
    )

    assert summary["metrics"]["n"] == 5
    assert summary["metrics"]["mean"] == 3.0
    assert round(summary["metrics"]["sd"], 4) == 1.5811
    assert (tmp_path / "evidence" / "artifacts" / "summary.txt").is_file()


@pytest.mark.parametrize("plan,worker_id,expected", [
    ([[["a", "b"], ("c",), "d"]], 0, ["a", "b", "c", "d"]),
    ([[["other"]], [["mine"]]], 1, ["mine"]),
    (None, 0, []), ([], 0, []), (["invalid"], 0, []),
])
@pytest.mark.parametrize("started", [None, 10.0])
def test_r_worker_dispatches_only_assigned_work(monkeypatch, plan, worker_id, expected, started):
    from unittest.mock import Mock
    import r_runtime_bridge_worker.r_runtime_bridge_worker as module
    monkeypatch.setattr(module.BaseWorker, "_t0", started)
    monkeypatch.setattr(module, "time", SimpleNamespace(time=lambda: 20.0))
    worker = module.RRuntimeBridgeWorker()
    worker._worker_id = worker_id
    calls = []
    worker.work_pool = lambda item: calls.append(item) or {"item": item}
    worker.work_done = Mock()
    worker.stop = Mock()
    assert worker.works(plan, None) == (0.0 if started is None else 10.0)
    assert calls == expected
    assert [call.args[0] for call in worker.work_done.call_args_list] == [{"item": x} for x in expected]
    worker.stop.assert_called_once_with()


@pytest.mark.parametrize("active", [False, True])
def test_r_worker_script_resolution_uses_active_app_or_cwd(tmp_path, monkeypatch, active):
    import r_runtime_bridge_worker.r_runtime_bridge_worker as module
    monkeypatch.chdir(tmp_path)
    worker = module.RRuntimeBridgeWorker()
    app = tmp_path / "app"
    worker.env = SimpleNamespace(active_app=app if active else None)
    assert worker._resolve_script_path("scripts/task.R") == (app if active else tmp_path) / "scripts/task.R"
    absolute = tmp_path / "explicit.R"
    assert worker._resolve_script_path(absolute) == absolute
    assert worker._current_app_root() == (app if active else None)


@pytest.mark.parametrize("representation", ["model", "namespace", "object"])
def test_r_worker_accepts_runtime_arg_shapes(representation):
    import r_runtime_bridge_worker.r_runtime_bridge_worker as module
    from r_runtime_bridge import RRuntimeBridgeArgs
    if representation == "model":
        value = RRuntimeBridgeArgs()
    elif representation == "namespace":
        value = SimpleNamespace(timeout_seconds=23, _transport="ignored")
    else:
        class Payload:
            pass
        value = Payload()
        value.__dict__.update(timeout_seconds=23, _transport="ignored")
    result = module._args_with_defaults(value)
    if representation == "model":
        assert result is value
    else:
        assert result.timeout_seconds == 23
    assert not hasattr(result, "_transport")


def test_r_worker_reset_confines_removal_to_own_evidence(tmp_path, monkeypatch):
    import r_runtime_bridge_worker.r_runtime_bridge_worker as module
    monkeypatch.setattr(module, "_runtime", {})
    share, export = tmp_path / "share", tmp_path / "export"
    output = share / "r_runtime_bridge" / "evidence"
    artifact = export / "r_runtime_bridge_project" / "r_runtime_bridge"
    for directory in (output, artifact):
        directory.mkdir(parents=True)
        (directory / "stale.txt").write_text("old")
    (share / "unrelated.txt").write_text("keep")
    worker = module.RRuntimeBridgeWorker()
    worker.env = SimpleNamespace(resolve_share_path=lambda value: share / Path(value),
                                 AGILAB_EXPORT_ABS=export, target="r_runtime_bridge_project",
                                 active_app=tmp_path / "app")
    worker.args = dict(data_out="r_runtime_bridge/evidence", reset_target=True)
    worker.start()
    assert worker.data_out == output
    assert worker.artifact_dir == artifact
    assert not list(output.iterdir())
    assert not list(artifact.iterdir())
    assert (share / "unrelated.txt").read_text() == "keep"
    worker.pool_init(worker.pool_vars)
    assert worker._current_args() is worker.args
    assert worker._current_script_path() == worker.script_path
    module._copy_artifacts(output, output)
