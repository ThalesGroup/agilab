from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace


APP_ROOT = Path("src/agilab/apps/builtin/tescia_diagnostic_project").resolve()
APP_SRC = APP_ROOT / "src"
SAMPLE_CASES = APP_SRC / "tescia_diagnostic" / "sample_data" / "tescia_diagnostic_cases.json"


class _FakeEnv:
    def __init__(self, tmp_path: Path) -> None:
        self._is_managed_pc = False
        self.verbose = 0
        self.target = "tescia_diagnostic"
        self.home_abs = str(tmp_path)
        self.AGI_LOCAL_SHARE = str(tmp_path / "localshare")
        self.AGILAB_EXPORT_ABS = tmp_path / "export"
        self.agi_share_path = tmp_path / "share"
        self.agi_share_path_abs = tmp_path / "share"
        self.agi_share_path.mkdir(parents=True, exist_ok=True)

    def share_root_path(self) -> Path:
        return Path(self.agi_share_path)

    def resolve_share_path(self, value) -> Path:
        path = Path(value).expanduser()
        if path.is_absolute():
            return path
        return self.share_root_path() / path


def _load_cases() -> list[dict]:
    payload = json.loads(SAMPLE_CASES.read_text(encoding="utf-8"))
    return payload["cases"]


def test_tescia_diagnostic_selects_evidence_backed_fix(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(APP_SRC))

    from tescia_diagnostic import diagnose_case

    report = diagnose_case(_load_cases()[0])

    assert report["status"] == "actionable"
    assert report["case_id"] == "cluster_share_sshfs"
    assert report["selected_fix"]["id"] == "mount_scheduler_share_with_sshfs"
    assert report["evidence_quality"] >= 0.85
    assert report["regression_coverage"] >= 0.75
    assert "SSH login success proves the shared data path is usable." in report["weak_assumptions"]


def test_tescia_reduce_contract_merges_case_summaries(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(APP_SRC))

    from tescia_diagnostic import (
        build_reduce_artifact,
        diagnose_case,
        partial_from_diagnostic_summary,
        summarize_report,
    )

    summaries = [
        summarize_report(diagnose_case(case), worker_id=0, source_file="cases.json")
        for case in _load_cases()
    ]
    artifact = build_reduce_artifact(
        tuple(
            partial_from_diagnostic_summary(summary, partial_id=summary["case_id"])
            for summary in summaries
        )
    )

    assert artifact.name == "tescia_diagnostic_reduce_summary"
    assert artifact.partial_count == 2
    assert artifact.payload["case_count"] == 2
    assert artifact.payload["actionable_count"] == 2
    assert artifact.payload["case_ids"] == ["cluster_share_sshfs", "pipeline_dag_stale_preview"]
    assert "mount_scheduler_share_with_sshfs" in artifact.payload["selected_fix_ids"]


def test_tescia_manager_seeds_sample_and_builds_distribution(monkeypatch, tmp_path) -> None:
    monkeypatch.syspath_prepend(str(APP_SRC))

    from tescia_diagnostic import TesciaDiagnostic

    env = _FakeEnv(tmp_path)
    app = TesciaDiagnostic(env)

    seeded = env.share_root_path() / "tescia_diagnostic" / "cases" / "tescia_diagnostic_cases.json"
    assert seeded.is_file()
    work_plan, metadata, label_key, size_key, size_unit = app.build_distribution({"127.0.0.1": 1})
    assert work_plan == [[[str(seeded)]]]
    assert metadata[0][0]["diagnostic_file"] == "tescia_diagnostic_cases.json"
    assert (label_key, size_key, size_unit) == ("diagnostic_file", "size_kb", "KB")


def test_tescia_worker_exports_json_csv_and_reduce_artifacts(monkeypatch, tmp_path) -> None:
    monkeypatch.syspath_prepend(str(APP_SRC))

    from tescia_diagnostic_worker import TesciaDiagnosticWorker

    env = _FakeEnv(tmp_path)
    input_dir = env.share_root_path() / "tescia_diagnostic" / "cases"
    input_dir.mkdir(parents=True, exist_ok=True)
    case_file = input_dir / "cases.json"
    case_file.write_text(SAMPLE_CASES.read_text(encoding="utf-8"), encoding="utf-8")

    worker = TesciaDiagnosticWorker()
    worker.env = env
    worker.args = SimpleNamespace(
        data_in=input_dir,
        data_out=env.share_root_path() / "tescia_diagnostic" / "reports",
        minimum_evidence_confidence=0.65,
        minimum_regression_coverage=0.6,
        reset_target=True,
    )
    worker._worker_id = 0
    worker.start()

    df = worker.work_pool(case_file)
    worker.work_done(df)

    output_root = Path(worker.data_out)
    assert (output_root / "tescia_diagnostic_summary.csv").is_file()
    assert (output_root / "reduce_summary_worker_0.json").is_file()
    assert (
        output_root
        / "cluster_share_sshfs"
        / "cluster_share_sshfs_diagnostic_report.json"
    ).is_file()
    export_root = env.AGILAB_EXPORT_ABS / env.target / "tescia_diagnostic"
    assert (export_root / "pipeline_dag_stale_preview" / "pipeline_dag_stale_preview_diagnostic_summary.csv").is_file()


def test_tescia_generator_validates_local_gpt_oss_payload(monkeypatch, tmp_path) -> None:
    monkeypatch.syspath_prepend(str(APP_SRC))

    from tescia_diagnostic.generator import generate_case_file

    generated_payload = {
        "schema": "agilab.tescia_diagnostic.cases.v1",
        "cases": [
            {
                "case_id": "generated_case",
                "symptom": "A generated diagnostic symptom.",
                "proposed_diagnosis": "An initial diagnosis to challenge.",
                "root_cause": "A stronger evidence-backed root cause.",
                "plain_repro": "run the first discriminator",
                "weak_assumptions": ["The first signal is sufficient."],
                "evidence": [
                    {"id": "e1", "description": "first signal", "confidence": 0.9, "relevance": 0.9},
                    {"id": "e2", "description": "second signal", "confidence": 0.8, "relevance": 0.85},
                ],
                "candidate_fixes": [
                    {
                        "id": "strong_fix",
                        "summary": "Apply the evidence-backed fix.",
                        "expected_impact": 0.9,
                        "blast_radius": 0.25,
                        "reversibility": 0.8,
                    },
                    {
                        "id": "weak_fix",
                        "summary": "Patch only the visible symptom.",
                        "expected_impact": 0.4,
                        "blast_radius": 0.7,
                        "reversibility": 0.5,
                    },
                ],
                "regression_tests": [
                    {"id": "r1", "description": "first discriminator", "automated": True, "discriminator": True},
                    {"id": "r2", "description": "second discriminator", "automated": False, "discriminator": True},
                ],
            }
        ],
    }

    def fake_post_json(url, payload, timeout_s):
        assert url == "http://127.0.0.1:8000/v1/responses"
        assert payload["model"] == "gpt-oss-120b"
        assert timeout_s == 120.0
        return {"output_text": json.dumps(generated_payload)}

    output_path = generate_case_file(
        tmp_path,
        filename="generated_cases.json",
        provider="gpt-oss",
        endpoint="",
        model="gpt-oss-120b",
        topic="AGILAB install diagnostics",
        case_count=1,
        temperature=0.2,
        timeout_s=120.0,
        post_json=fake_post_json,
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["schema"] == "agilab.tescia_diagnostic.cases.v1"
    assert payload["cases"][0]["case_id"] == "generated_case"


def test_tescia_generator_rejects_bad_numeric_scores(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(APP_SRC))

    from tescia_diagnostic.generator import DiagnosticCaseGenerationError, validate_generated_cases

    payload = json.loads(SAMPLE_CASES.read_text(encoding="utf-8"))
    payload["cases"][0]["evidence"][0]["confidence"] = 1.5

    try:
        validate_generated_cases(payload)
    except DiagnosticCaseGenerationError as exc:
        assert "must be between 0.0 and 1.0" in str(exc)
    else:
        raise AssertionError("invalid generated confidence score was accepted")
