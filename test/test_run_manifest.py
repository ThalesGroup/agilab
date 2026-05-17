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


def test_run_manifest_helpers_create_stable_timestamp_and_run_id() -> None:
    module = _load_module()

    timestamp = module.utc_now()
    run_id = module.new_run_id("proof")

    assert timestamp.endswith("Z")
    assert "+00:00" not in timestamp
    assert run_id.startswith("proof-")
    assert len(run_id) == len("proof-") + 12


def test_run_manifest_artifact_from_path_handles_directories_and_missing_files(tmp_path: Path) -> None:
    module = _load_module()
    directory = tmp_path / "outputs"
    directory.mkdir()
    missing = tmp_path / "missing.json"

    directory_artifact = module.RunManifestArtifact.from_path(directory)
    missing_artifact = module.RunManifestArtifact.from_path(
        missing,
        name="planned",
        kind="json",
    )

    assert directory_artifact.exists is True
    assert directory_artifact.kind == "directory"
    assert directory_artifact.size_bytes is None
    assert missing_artifact.exists is False
    assert missing_artifact.name == "planned"
    assert missing_artifact.kind == "json"
    assert missing_artifact.size_bytes is None


def test_run_manifest_rejects_unsupported_kind_and_status(tmp_path: Path) -> None:
    module = _load_module()
    payload = {
        "schema_version": module.SCHEMA_VERSION,
        "kind": module.MANIFEST_KIND,
        "status": "pass",
    }

    try:
        module.RunManifest.from_dict({**payload, "kind": "other"})
    except ValueError as exc:
        assert "Unsupported run manifest kind" in str(exc)
    else:
        raise AssertionError("unsupported kind should fail")

    try:
        module.RunManifest.from_dict({**payload, "status": "skipped"})
    except ValueError as exc:
        assert "Unsupported run manifest status" in str(exc)
    else:
        raise AssertionError("unsupported status should fail")

    try:
        module.build_run_manifest(
            path_id="demo",
            label="Demo",
            status="skipped",
            command=module.RunManifestCommand(label="", argv=(), cwd=str(tmp_path)),
            environment=module.RunManifestEnvironment.from_paths(
                repo_root=tmp_path,
                active_app=tmp_path,
            ),
            timing=module.RunManifestTiming(
                started_at="",
                finished_at="",
                duration_seconds=0.0,
            ),
            artifacts=[],
            validations=[],
        )
    except ValueError as exc:
        assert "Unsupported run manifest status" in str(exc)
    else:
        raise AssertionError("unsupported build status should fail")


def test_try_load_run_manifest_reports_missing_and_parse_errors(tmp_path: Path) -> None:
    module = _load_module()
    missing_path = tmp_path / "missing" / "run_manifest.json"
    malformed_path = tmp_path / "run_manifest.json"
    malformed_path.write_text("{", encoding="utf-8")

    missing_manifest, missing_error = module.try_load_run_manifest(missing_path)
    malformed_manifest, malformed_error = module.try_load_run_manifest(malformed_path)

    assert missing_manifest is None
    assert missing_error == "missing"
    assert malformed_manifest is None
    assert malformed_error is not None
    assert "Expecting property name" in malformed_error
