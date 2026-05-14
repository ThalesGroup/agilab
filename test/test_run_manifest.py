from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


MODULE_PATH = Path("src/agilab/run_manifest.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("run_manifest_test_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_run_manifest_round_trips_stable_schema(tmp_path: Path) -> None:
    module = _load_module()
    active_app = tmp_path / "flight_telemetry_project"
    active_app.mkdir()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    artifact = tmp_path / "trajectory_summary.json"
    artifact.write_text("{}", encoding="utf-8")

    manifest = module.build_run_manifest(
        path_id="source-checkout-first-proof",
        label="Source checkout first proof",
        status="pass",
        command=module.RunManifestCommand(
            label="newcomer first proof",
            argv=("tools/newcomer_first_proof.py", "--json"),
            cwd=str(repo_root),
            env_overrides={"AGILAB_DISABLE_BACKGROUND_SERVICES": "1"},
        ),
        environment=module.RunManifestEnvironment.from_paths(
            repo_root=repo_root,
            active_app=active_app,
        ),
        timing=module.RunManifestTiming(
            started_at="2026-04-25T00:00:00Z",
            finished_at="2026-04-25T00:00:03Z",
            duration_seconds=3.0,
            target_seconds=600.0,
        ),
        artifacts=[module.RunManifestArtifact.from_path(artifact)],
        validations=[
            module.RunManifestValidation(
                label="proof_steps",
                status="pass",
                summary="all proof steps passed",
            )
        ],
        run_id="first-proof-demo",
        created_at="2026-04-25T00:00:03Z",
    )

    path = module.write_run_manifest(manifest, module.run_manifest_path(tmp_path))
    loaded = module.load_run_manifest(path)

    assert path.name == "run_manifest.json"
    assert loaded.as_dict() == manifest.as_dict()
    assert module.manifest_passed(loaded) is True
    assert module.manifest_summary(loaded) == {
        "run_id": "first-proof-demo",
        "path_id": "source-checkout-first-proof",
        "label": "Source checkout first proof",
        "status": "pass",
        "duration_seconds": 3.0,
        "target_seconds": 600.0,
        "artifact_count": 1,
        "validation_statuses": {"proof_steps": "pass"},
    }


def test_run_manifest_rejects_unsupported_schema() -> None:
    module = _load_module()

    payload = {
        "schema_version": 999,
        "kind": module.MANIFEST_KIND,
        "status": "pass",
    }

    try:
        module.RunManifest.from_dict(payload)
    except ValueError as exc:
        assert "Unsupported run manifest schema" in str(exc)
    else:
        raise AssertionError("unsupported schema should fail")
