from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


RUN_MANIFEST_PATH = Path("src/agilab/run_manifest.py").resolve()
PROMOTION_DOSSIER_PATH = Path("src/agilab/promotion_dossier.py").resolve()
LAB_RUN_PATH = Path("src/agilab/lab_run.py").resolve()


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_manifest(tmp_path: Path, *, status: str = "pass") -> Path:
    run_manifest = _load_module(RUN_MANIFEST_PATH, f"run_manifest_for_dossier_{status}")
    active_app = tmp_path / "flight_telemetry_project"
    active_app.mkdir()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    artifact = tmp_path / "trajectory_summary.json"
    artifact.write_text('{"rows": 3}\n', encoding="utf-8")
    manifest = run_manifest.build_run_manifest(
        path_id="source-checkout-first-proof",
        label="Source checkout first proof",
        status=status,
        command=run_manifest.RunManifestCommand(
            label="newcomer first proof",
            argv=(sys.executable, "-c", "print('ok')"),
            cwd=str(repo_root),
            env_overrides={"OPENAI_API_KEY": "<redacted>"},
        ),
        environment=run_manifest.RunManifestEnvironment(
            python_version="3.13.0",
            python_executable=sys.executable,
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
                status=status,
                summary="all proof steps passed" if status == "pass" else "proof failed",
            )
        ],
        run_id=f"dossier-{status}",
        created_at="2026-05-30T00:00:05Z",
    )
    return run_manifest.write_run_manifest(manifest, tmp_path / "run_manifest.json")


def test_promotion_dossier_promotes_passing_manifest(tmp_path: Path) -> None:
    module = _load_module(PROMOTION_DOSSIER_PATH, "promotion_dossier_test_module")
    manifest_path = _write_manifest(tmp_path)

    result = module.build_promotion_dossier(manifest_path, tmp_path / "dossier")

    assert result["schema"] == "agilab.promotion_dossier.v1"
    assert result["decision"] == "promote"
    assert result["status"] == "pass"
    expected_files = {
        "promotion_decision",
        "promotion_dossier",
        "evidence_manifest",
        "policy_results",
        "lineage",
        "mlflow_export",
        "run_story_json",
        "run_story_markdown",
        "replay",
    }
    assert set(result["paths"]) == expected_files
    for path in result["paths"].values():
        assert Path(path).is_file()

    decision = json.loads(Path(result["paths"]["promotion_decision"]).read_text(encoding="utf-8"))
    assert decision["decision"] == "promote"
    assert decision["policy_status"] == "pass"

    evidence_manifest = json.loads(Path(result["paths"]["evidence_manifest"]).read_text(encoding="utf-8"))
    assert evidence_manifest["schema"] == "agilab.promotion_evidence_manifest.v1"
    assert {row["id"] for row in evidence_manifest["dossier_files"]} >= {
        "promotion_decision",
        "policy_results",
        "run_story_json",
    }
    assert evidence_manifest["source_artifacts"][0]["sha256"]
    assert "Decision: `promote`" in Path(result["paths"]["promotion_dossier"]).read_text(encoding="utf-8")


def test_promotion_dossier_blocks_failed_manifest_and_strict_exits(tmp_path: Path) -> None:
    module = _load_module(PROMOTION_DOSSIER_PATH, "promotion_dossier_block_test_module")
    manifest_path = _write_manifest(tmp_path, status="fail")
    output_dir = tmp_path / "dossier"

    result = module.build_promotion_dossier(manifest_path, output_dir)

    assert result["decision"] == "block"
    assert "validations_pass" in result["blockers"]
    assert module.main([str(manifest_path), "--output-dir", str(output_dir)]) == 0
    assert module.main([str(manifest_path), "--output-dir", str(output_dir), "--strict"]) == 1


def test_lab_run_routes_promotion_dossier(monkeypatch) -> None:
    import agilab

    lab_run = _load_module(LAB_RUN_PATH, "lab_run_promotion_dossier_route_test_module")
    captured = {}

    class _PromotionDossier:
        @staticmethod
        def main(argv):
            captured["argv"] = argv
            return 0

    monkeypatch.setitem(sys.modules, "agilab.promotion_dossier", _PromotionDossier)
    monkeypatch.setattr(agilab, "promotion_dossier", _PromotionDossier, raising=False)

    assert lab_run.main(["promotion-dossier", "run_manifest.json", "--json"]) == 0
    assert captured["argv"] == ["run_manifest.json", "--json"]
