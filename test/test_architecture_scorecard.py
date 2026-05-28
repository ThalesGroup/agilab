from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shlex
import stat
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
ARCHITECTURE_SCORECARD = REPO_ROOT / "tools" / "architecture_scorecard.py"
AGI_CLUSTER_SRC = REPO_ROOT / "src" / "agilab" / "core" / "agi-cluster" / "src"
AGI_ENV_SRC = REPO_ROOT / "src" / "agilab" / "core" / "agi-env" / "src"


def _load_file_module(name: str, path: Path):
    sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_cluster_module(name: str):
    for candidate in (AGI_CLUSTER_SRC, AGI_ENV_SRC):
        value = str(candidate)
        if value not in sys.path:
            sys.path.insert(0, value)
    return _load_file_module(
        f"agilab_architecture_scorecard_{name}",
        AGI_CLUSTER_SRC / "agi_cluster" / "agi_distributor" / f"{name}.py",
    )


def test_architecture_scorecard_passes_current_evidence() -> None:
    module = _load_file_module("architecture_scorecard_test_module", ARCHITECTURE_SCORECARD)

    report = module.build_report(repo_root=REPO_ROOT)
    checks = {check["id"]: check for check in report["checks"]}

    assert report["schema"] == module.SCHEMA
    assert report["status"] == "pass"
    assert report["supported_score"] == "4.6 / 5"
    assert "not external certification" in report["summary"]["score_boundary"]
    assert checks["architecture_remote_execution_hardening"]["status"] == "pass"
    assert checks["architecture_capacity_model_trust_boundary"]["status"] == "pass"
    assert checks["architecture_hardening_gap_register"]["status"] == "pass"
    assert set(checks["architecture_hardening_gap_register"]["details"]["gap_ids"]) >= {
        "tenant-isolation",
        "enterprise-auth-rbac",
        "production-rollback",
        "regulated-serving",
        "capacity-model-signature",
    }


def test_architecture_scorecard_cli_writes_json(tmp_path: Path, capsys) -> None:
    module = _load_file_module("architecture_scorecard_cli_test_module", ARCHITECTURE_SCORECARD)
    output = tmp_path / "architecture-scorecard.json"

    assert module.main(["--compact", "--output", str(output)]) == 0

    stdout_payload = json.loads(capsys.readouterr().out)
    file_payload = json.loads(output.read_text(encoding="utf-8"))
    assert stdout_payload["status"] == "pass"
    assert file_payload["supported_score"] == "4.6 / 5"


def test_remote_dask_worker_command_quotes_dynamic_fragments() -> None:
    module = _load_cluster_module("runtime_distribution_support")

    command = module._remote_dask_worker_command(
        cmd_prefix="env AGILAB_REMOTE=1",
        dask_env="DASK_DISTRIBUTED__LOGGING__distributed=info ",
        uv_cmd="uv --preview-features extra-build-dependencies",
        wenv_rel=Path("worker env/worker's env"),
        scheduler="scheduler.example; touch /tmp/bad",
        pid_file="worker pid.pid",
    )

    tokens = shlex.split(command, posix=True)
    assert tokens[:2] == ["env", "AGILAB_REMOTE=1"]
    assert "worker env/worker's env" in tokens
    assert "tcp://scheduler.example; touch /tmp/bad" in tokens
    assert "worker env/worker pid.pid" in tokens
    assert "; touch /tmp/bad --no-nanny" not in command


def test_capacity_predictor_refuses_untrusted_pickle_path(tmp_path: Path) -> None:
    module = _load_cluster_module("runtime_misc_support")
    trusted_root = tmp_path / "trusted"
    outside_root = tmp_path / "outside"
    trusted_root.mkdir()
    outside_root.mkdir()
    model_path = outside_root / "balancer_model.pkl"
    model_path.write_bytes(b"not-a-trusted-pickle")

    retrained: list[bool] = []

    def _load_should_not_run(_stream):
        raise AssertionError("untrusted capacity model should not be deserialized")

    predictor = module.load_capacity_predictor(
        model_path,
        trusted_root=trusted_root,
        load_fn=_load_should_not_run,
        retrain_fn=lambda: retrained.append(True),
    )

    assert predictor is None
    assert retrained == [True]


def test_capacity_predictor_refuses_world_writable_trusted_model(tmp_path: Path) -> None:
    module = _load_cluster_module("runtime_misc_support")
    model_path = tmp_path / "balancer_model.pkl"
    model_path.write_bytes(b"world-writable-pickle")
    model_path.chmod(model_path.stat().st_mode | stat.S_IWOTH)

    retrained: list[bool] = []

    def _load_should_not_run(_stream):
        raise AssertionError("world-writable capacity model should not be deserialized")

    try:
        predictor = module.load_capacity_predictor(
            model_path,
            trusted_root=tmp_path,
            load_fn=_load_should_not_run,
            retrain_fn=lambda: retrained.append(True),
        )
    finally:
        model_path.chmod(model_path.stat().st_mode & ~stat.S_IWOTH)

    assert predictor is None
    assert retrained == [True]
