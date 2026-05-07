from __future__ import annotations

import json
from pathlib import Path
import tomllib
from types import SimpleNamespace

import pytest


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
        self.app_settings_file = tmp_path / "app_settings.toml"
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


def _generated_cases_payload(case_id: str = "ai_generated_cluster_share") -> dict:
    return {
        "schema": "agilab.tescia_diagnostic.cases.v1",
        "cases": [
            {
                "case_id": case_id,
                "symptom": "A generated diagnostic case reports stale cluster-share evidence after a worker reinstall.",
                "proposed_diagnosis": "The generated diagnosis blames SSH authentication only.",
                "root_cause": "The generated case identifies the stale shared-storage mount as the stronger root cause.",
                "plain_repro": "agilab doctor --cluster --share-check-only",
                "weak_assumptions": [
                    "Successful SSH proves the mounted share is current.",
                    "A worker reinstall cannot leave stale mount metadata behind.",
                ],
                "evidence": [
                    {
                        "id": "ssh_ok",
                        "description": "Non-interactive SSH succeeds.",
                        "confidence": 0.9,
                        "relevance": 0.75,
                    },
                    {
                        "id": "share_stale",
                        "description": "The mounted share does not contain the scheduler sentinel.",
                        "confidence": 0.94,
                        "relevance": 0.96,
                    },
                ],
                "candidate_fixes": [
                    {
                        "id": "remount_share_with_sentinel_check",
                        "summary": "Unmount stale SSHFS state, remount the scheduler share, and verify a sentinel.",
                        "expected_impact": 0.91,
                        "blast_radius": 0.28,
                        "reversibility": 0.86,
                    },
                    {
                        "id": "rerun_ssh_copy_id",
                        "summary": "Refresh SSH keys only.",
                        "expected_impact": 0.35,
                        "blast_radius": 0.52,
                        "reversibility": 0.7,
                    },
                ],
                "regression_tests": [
                    {
                        "id": "sentinel_roundtrip",
                        "description": "Write scheduler sentinel and read it from the worker mount.",
                        "automated": True,
                        "discriminator": True,
                    },
                    {
                        "id": "stale_mount_recovery",
                        "description": "Verify stale mount is detected and remounted.",
                        "automated": True,
                        "discriminator": True,
                    },
                ],
            }
        ],
    }


def test_tescia_ai_generator_uses_fake_gpt_oss_and_validates_schema(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(APP_SRC))

    from tescia_diagnostic import generate_cases_with_engine

    calls: list[tuple[str, dict, float]] = []

    def fake_post_json(url, payload, timeout_s):
        calls.append((url, dict(payload), timeout_s))
        return {"output_text": json.dumps(_generated_cases_payload())}

    generated = generate_cases_with_engine(
        provider="gpt-oss",
        endpoint="http://127.0.0.1:8000/v1/responses",
        model="gpt-oss-test",
        topic="cluster share diagnostics",
        case_count=1,
        temperature=0.1,
        timeout_s=12.0,
        post_json=fake_post_json,
    )

    assert generated["schema"] == "agilab.tescia_diagnostic.cases.v1"
    assert generated["cases"][0]["case_id"] == "ai_generated_cluster_share"
    assert calls[0][0] == "http://127.0.0.1:8000/v1/responses"
    assert calls[0][1]["model"] == "gpt-oss-test"
    assert "cluster share diagnostics" in calls[0][1]["input"]
    assert calls[0][2] == 12.0


def test_tescia_ai_generator_rejects_weak_json(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(APP_SRC))

    from tescia_diagnostic import DiagnosticCaseGenerationError, validate_generated_cases

    payload = _generated_cases_payload()
    payload["cases"][0]["evidence"] = payload["cases"][0]["evidence"][:1]

    with pytest.raises(DiagnosticCaseGenerationError, match="at least two evidence"):
        validate_generated_cases(payload, expected_case_count=1)


def test_tescia_generator_validates_local_gpt_oss_payload(monkeypatch, tmp_path) -> None:
    monkeypatch.syspath_prepend(str(APP_SRC))

    from tescia_diagnostic.generator import generate_case_file

    generated_payload = _generated_cases_payload(case_id="generated_case")

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

    with pytest.raises(DiagnosticCaseGenerationError, match="must be between 0.0 and 1.0"):
        validate_generated_cases(payload)


def test_tescia_diagnostic_selects_evidence_backed_fix(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(APP_SRC))

    from tescia_diagnostic import diagnose_case

    report = diagnose_case(_load_cases()[0])

    assert report["status"] == "actionable"
    assert report["case_id"] == "cluster_share_sshfs"
    assert report["selected_fix"]["id"] == "mount_scheduler_share_with_sshfs"
    assert report["evidence_quality"] >= 0.85
    assert report["regression_coverage"] >= 0.75
    assert 85.0 <= report["student_score"] <= 100.0
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
    assert 85.0 <= artifact.payload["student_score_mean"] <= 100.0


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


def test_tescia_manager_can_seed_generated_cases_from_injected_ai_engine(monkeypatch, tmp_path) -> None:
    monkeypatch.syspath_prepend(str(APP_SRC))

    from tescia_diagnostic import TesciaDiagnostic

    generated_calls: list[dict] = []

    def fake_generate_case_file(output_dir, **kwargs):
        generated_calls.append(dict(kwargs))
        output_path = Path(output_dir) / kwargs["filename"]
        output_path.write_text(json.dumps(_generated_cases_payload()) + "\n", encoding="utf-8")
        return output_path

    env = _FakeEnv(tmp_path)
    app = TesciaDiagnostic(
        env,
        case_source="standalone_ai",
        generated_cases_filename="ai_cases.json",
        _generate_case_file_fn=fake_generate_case_file,
    )

    seeded = env.share_root_path() / "tescia_diagnostic" / "cases" / "ai_cases.json"
    assert seeded.is_file()
    assert generated_calls[0]["provider"] == "gpt-oss"
    work_plan, metadata, *_ = app.build_distribution({"127.0.0.1": 1})
    assert work_plan == [[[str(seeded)]]]
    assert metadata[0][0]["diagnostic_file"] == "ai_cases.json"


def test_tescia_app_args_form_exposes_standalone_ai_controls(monkeypatch, tmp_path) -> None:
    monkeypatch.syspath_prepend(str(APP_SRC))

    from streamlit.testing.v1 import AppTest
    from tescia_diagnostic import DEFAULT_GPT_OSS_ENDPOINT, DEFAULT_GPT_OSS_MODEL

    env = _FakeEnv(tmp_path)
    at = AppTest.from_file(str(APP_ROOT / "src" / "app_args_form.py"), default_timeout=20)
    at.session_state["env"] = env

    at.run()

    assert not at.exception
    source = at.selectbox(key="tescia_diagnostic_project:app_args_form:case_source")
    assert source.options == ["Bundled deterministic sample", "Generate with standalone AI"]
    assert source.value == "bundled"
    assert not any(text_input.label == "AI endpoint" for text_input in at.text_input)

    source.set_value("standalone_ai").run()

    assert not at.exception
    assert at.selectbox(key="tescia_diagnostic_project:app_args_form:ai_provider").value == "gpt-oss"
    assert at.text_input(key="tescia_diagnostic_project:app_args_form:ai_endpoint").value == DEFAULT_GPT_OSS_ENDPOINT
    assert at.text_input(key="tescia_diagnostic_project:app_args_form:ai_model").value == DEFAULT_GPT_OSS_MODEL
    with Path(env.app_settings_file).open("rb") as f:
        payload = tomllib.load(f)
    assert payload["args"]["case_source"] == "standalone_ai"
    assert payload["args"]["ai_endpoint"] == DEFAULT_GPT_OSS_ENDPOINT


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
    summary_payload = (output_root / "tescia_diagnostic_summary.csv").read_text(encoding="utf-8")
    assert "student_score" in summary_payload
    assert (output_root / "reduce_summary_worker_0.json").is_file()
    assert (
        output_root
        / "cluster_share_sshfs"
        / "cluster_share_sshfs_diagnostic_report.json"
    ).is_file()
    export_root = env.AGILAB_EXPORT_ABS / env.target / "tescia_diagnostic"
    assert (export_root / "pipeline_dag_stale_preview" / "pipeline_dag_stale_preview_diagnostic_summary.csv").is_file()
