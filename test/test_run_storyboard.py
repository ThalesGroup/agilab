from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


RUN_MANIFEST_PATH = Path("src/agilab/run_manifest.py").resolve()
STORYBOARD_PATH = Path("src/agilab/run_storyboard.py").resolve()
LAB_RUN_PATH = Path("src/agilab/lab_run.py").resolve()


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_manifest(
    tmp_path: Path,
    *,
    status: str = "pass",
    artifact_exists: bool = True,
    validation_status: str | None = None,
) -> Path:
    run_manifest = _load_module(RUN_MANIFEST_PATH, "run_manifest_for_storyboard_test")
    tmp_path.mkdir(parents=True, exist_ok=True)
    active_app = tmp_path / "flight_telemetry_project"
    active_app.mkdir(parents=True)
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True)
    artifact = tmp_path / "trajectory_summary.json"
    if artifact_exists:
        artifact.write_text('{"rows": 3}\n', encoding="utf-8")
    manifest = run_manifest.build_run_manifest(
        path_id="source-checkout-first-proof",
        label="Source checkout first proof",
        status=status,
        command=run_manifest.RunManifestCommand(
            label="newcomer first proof",
            argv=("agilab", "first-proof", "--json"),
            cwd=str(repo_root),
            env_overrides={"OPENAI_API_KEY": "redacted-by-caller"},
        ),
        environment=run_manifest.RunManifestEnvironment(
            python_version="3.13.0",
            python_executable="/venv/bin/python",
            platform="test-platform",
            repo_root=str(repo_root),
            active_app=str(active_app),
            app_name=active_app.name,
        ),
        timing=run_manifest.RunManifestTiming(
            started_at="2026-05-30T00:00:00Z",
            finished_at="2026-05-30T00:00:05Z",
            duration_seconds=5.0,
            target_seconds=600.0,
        ),
        artifacts=[run_manifest.RunManifestArtifact.from_path(artifact)],
        validations=[
            run_manifest.RunManifestValidation(
                label="proof_steps",
                status=validation_status or status,
                summary=(
                    "all proof steps passed"
                    if (validation_status or status) == "pass"
                    else "proof failed"
                ),
            )
        ],
        run_id="story-demo",
        created_at="2026-05-30T00:00:05Z",
    )
    return run_manifest.write_run_manifest(manifest, tmp_path / "run_manifest.json")


def test_run_storyboard_builds_shareable_story(tmp_path: Path) -> None:
    module = _load_module(STORYBOARD_PATH, "run_storyboard_test_module")
    manifest_path = _write_manifest(tmp_path)

    story = module.build_run_story(manifest_path)

    assert story["schema"] == "agilab.run_storyboard.v1"
    assert story["status"] == "pass"
    assert story["story"]["headline"] == (
        "Source checkout first proof passed for flight_telemetry_project."
    )
    assert story["command"]["text"] == "agilab first-proof --json"
    assert story["command"]["env_override_keys"] == ["OPENAI_API_KEY"]
    assert story["artifacts"][0]["exists"] is True
    assert len(story["artifacts"][0]["sha256"]) == 64
    assert story["provenance"] == {
        "source": "run_manifest",
        "source_schema": "agilab.run_manifest",
        "source_schema_version": 1,
        "executes_commands": False,
        "executes_network_probe": False,
        "safe_for_public_evidence": True,
    }


def test_run_storyboard_writes_json_and_markdown(tmp_path: Path) -> None:
    module = _load_module(STORYBOARD_PATH, "run_storyboard_write_test_module")
    manifest_path = _write_manifest(tmp_path)
    output_dir = tmp_path / "story"

    result = module.write_run_storyboard(manifest_path, output_dir)

    markdown_path = Path(result["paths"]["markdown"])
    json_path = Path(result["paths"]["json"])
    assert markdown_path.read_text(encoding="utf-8").startswith(
        "# Source checkout first proof passed"
    )
    assert json.loads(json_path.read_text(encoding="utf-8"))["schema"] == (
        "agilab.run_storyboard.v1"
    )


def test_run_storyboard_strict_fails_on_failed_manifest(tmp_path: Path) -> None:
    module = _load_module(STORYBOARD_PATH, "run_storyboard_cli_test_module")
    manifest_path = _write_manifest(tmp_path, status="fail")

    assert module.main([str(manifest_path), "--output-dir", str(tmp_path / "story")]) == 0
    assert module.main([str(manifest_path), "--output-dir", str(tmp_path / "story"), "--strict"]) == 1


def test_run_storyboard_next_actions_cover_missing_and_unknown_cases(tmp_path: Path) -> None:
    module = _load_module(STORYBOARD_PATH, "run_storyboard_next_actions_test_module")

    missing_artifact = module.build_run_story(
        _write_manifest(tmp_path / "missing-artifact", artifact_exists=False)
    )
    assert missing_artifact["story"]["headline"].endswith("passed for flight_telemetry_project.")
    assert missing_artifact["next_actions"][0] == "Regenerate missing artifacts before sharing the run."
    assert "trajectory_summary.json" in missing_artifact["next_actions"][1]

    failed_validation = module.build_run_story(
        _write_manifest(tmp_path / "failed-validation", validation_status="fail")
    )
    assert failed_validation["story"]["headline"].endswith(
        "finished with unknown status for flight_telemetry_project."
    )
    assert failed_validation["next_actions"][0].startswith("Fix or rerun the failing validation")

    unknown = module.build_run_story(
        _write_manifest(tmp_path / "unknown", status="unknown", validation_status="pass")
    )
    assert unknown["next_actions"] == [
        "Rerun the manifest-producing command until the status is pass or fail."
    ]


def test_lab_run_routes_storyboard(monkeypatch) -> None:
    import agilab

    lab_run = _load_module(LAB_RUN_PATH, "lab_run_storyboard_route_test_module")
    captured = {}

    class _Storyboard:
        @staticmethod
        def main(argv):
            captured["argv"] = argv
            return 0

    monkeypatch.setitem(sys.modules, "agilab.run_storyboard", _Storyboard)
    monkeypatch.setattr(agilab, "run_storyboard", _Storyboard, raising=False)

    assert lab_run.main(["story", "run_manifest.json", "--json"]) == 0
    assert captured["argv"] == ["run_manifest.json", "--json"]
