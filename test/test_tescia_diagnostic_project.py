from __future__ import annotations

import builtins
import json
import importlib.util
import runpy
import sys
from pathlib import Path
import tomllib
from types import SimpleNamespace

import pytest


APP_ROOT = Path("src/agilab/apps/builtin/tescia_diagnostic_project").resolve()
APP_SRC = APP_ROOT / "src"
SAMPLE_CASES = APP_SRC / "tescia_diagnostic" / "sample_data" / "tescia_diagnostic_cases.json"
SAMPLE_CLASSROOM = APP_SRC / "tescia_diagnostic" / "sample_data" / "tescia_classroom_submissions.json"
APP_SURFACE = APP_SRC / "tescia_diagnostic" / "app_surface.py"


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


class _FakeStreamlit:
    def __init__(self, env: _FakeEnv) -> None:
        self.session_state = {"env": env}
        self.expanders: list[tuple[str, bool]] = []
        self.latex_calls: list[str] = []
        self.buttons: list[str] = []
        self.dataframes: list[object] = []
        self.downloads: list[str] = []
        self.metrics: list[tuple[str, object]] = []
        self.rerun_called = False

        def cache_data(*_args, **_kwargs):
            def decorator(func):
                return func

            return decorator

        cache_data.clear = lambda: None
        self.cache_data = cache_data

    def __enter__(self):
        return self

    def __exit__(self, *_exc_info) -> None:
        return None

    def caption(self, *_args, **_kwargs) -> None:
        return None

    def warning(self, *_args, **_kwargs) -> None:
        return None

    def error(self, *_args, **_kwargs) -> None:
        return None

    def info(self, *_args, **_kwargs) -> None:
        return None

    def success(self, *_args, **_kwargs) -> None:
        return None

    def title(self, *_args, **_kwargs) -> None:
        return None

    def subheader(self, *_args, **_kwargs) -> None:
        return None

    def markdown(self, *_args, **_kwargs) -> None:
        return None

    def code(self, *_args, **_kwargs) -> None:
        return None

    def latex(self, formula: str, *_args, **_kwargs) -> None:
        self.latex_calls.append(formula)

    def expander(self, label: str, *, expanded: bool = False, **_kwargs):
        self.expanders.append((label, expanded))
        return self

    def columns(self, spec, **_kwargs):
        count = spec if isinstance(spec, int) else len(spec)
        return [self for _ in range(count)]

    def tabs(self, labels, **_kwargs):
        return [self for _ in labels]

    def dataframe(self, data, *_args, **_kwargs) -> None:
        self.dataframes.append(data)

    def metric(self, label, value, *_args, **_kwargs) -> None:
        self.metrics.append((label, value))

    def button(self, label, *_args, **_kwargs) -> bool:
        self.buttons.append(label)
        return False

    def download_button(self, label, *_args, **_kwargs) -> bool:
        self.downloads.append(label)
        return False

    def text_input(self, *_args, **kwargs):
        return kwargs.get("value", "")

    def number_input(self, *_args, **kwargs):
        return kwargs.get("value", 0)

    def checkbox(self, *_args, **kwargs) -> bool:
        return bool(kwargs.get("value", False))

    def selectbox(self, _label, options, *_args, **_kwargs):
        return options[0] if options else ""

    def multiselect(self, *_args, **_kwargs):
        return []

    def slider(self, *_args, **kwargs):
        return kwargs.get("value", 0.0)

    def write(self, *_args, **_kwargs) -> None:
        return None

    def text_area(self, *_args, **kwargs):
        return kwargs.get("value", "")

    def stop(self) -> None:
        raise AssertionError("st.stop() should not be called in this test")

    def rerun(self) -> None:
        self.rerun_called = True


def _load_cases() -> list[dict]:
    payload = json.loads(SAMPLE_CASES.read_text(encoding="utf-8"))
    return payload["cases"]


def _load_classroom_payload() -> dict:
    return json.loads(SAMPLE_CLASSROOM.read_text(encoding="utf-8"))


def _load_app_surface_module():
    spec = importlib.util.spec_from_file_location("tescia_app_surface_test_module", APP_SURFACE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_tescia_args_form_renders_scoring_model_as_latex(monkeypatch, tmp_path) -> None:
    fake_env = _FakeEnv(tmp_path)
    fake_env.app_settings_file = str(tmp_path / "app_settings.toml")
    fake_streamlit = _FakeStreamlit(fake_env)
    monkeypatch.setitem(sys.modules, "streamlit", fake_streamlit)
    monkeypatch.syspath_prepend(str(APP_SRC))

    runpy.run_path(str(APP_SRC / "app_args_form.py"), run_name="__main__")

    assert ("Scoring model", False) in fake_streamlit.expanders
    assert ("Student self-evaluation contract", False) in fake_streamlit.expanders
    assert ("2026 mathematics coverage", False) in fake_streamlit.expanders
    assert ("Classroom batch mode", False) in fake_streamlit.expanders
    assert len(fake_streamlit.latex_calls) == 4
    assert fake_streamlit.latex_calls[-1] == (
        r"student\_score = 100 \cdot (0.35E + 0.30R + 0.25F + 0.10 \cdot gate)"
    )


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
    assert "student_prompt" in calls[0][1]["input"]
    assert "Do not include student_answer" in calls[0][1]["input"]
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


def test_tescia_generator_extracts_provider_payloads_and_rejects_bad_responses(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(APP_SRC))

    from tescia_diagnostic import DiagnosticCaseGenerationError
    from tescia_diagnostic import generator

    nested_response = {
        "output": [
            {"content": [{"text": "prefix " + json.dumps(_generated_cases_payload()) + " suffix"}]},
            {"content": [{"text": ""}]},
            "ignored",
        ]
    }
    assert "prefix" in generator._gpt_oss_text(nested_response)
    assert generator._ollama_text({"response": json.dumps(_generated_cases_payload())}).startswith("{")
    wrapped = generator._extract_json_object("```json\n" + json.dumps(_generated_cases_payload()) + "\n```")
    assert wrapped["schema"] == "agilab.tescia_diagnostic.cases.v1"
    assert generator._ollama_generate_url("http://localhost:11434") == "http://localhost:11434/api/generate"
    assert generator._ollama_generate_url("http://localhost:11434/api/generate") == "http://localhost:11434/api/generate"

    with pytest.raises(DiagnosticCaseGenerationError, match="did not contain text"):
        generator._gpt_oss_text({"output": [{"content": [{"not_text": "x"}]}]})
    with pytest.raises(DiagnosticCaseGenerationError, match="response string"):
        generator._ollama_text({"response": 123})
    with pytest.raises(DiagnosticCaseGenerationError, match="empty text"):
        generator._extract_json_object("  ")
    with pytest.raises(DiagnosticCaseGenerationError, match="did not return a JSON object"):
        generator._extract_json_object("no json here")
    with pytest.raises(DiagnosticCaseGenerationError, match="malformed JSON"):
        generator._extract_json_object("prefix {bad json} suffix")
    with pytest.raises(DiagnosticCaseGenerationError, match="JSON must be an object"):
        generator._extract_json_object("[1, 2, 3]")


def test_tescia_generator_ollama_and_error_paths(monkeypatch, tmp_path) -> None:
    monkeypatch.syspath_prepend(str(APP_SRC))

    from tescia_diagnostic import DiagnosticCaseGenerationError
    from tescia_diagnostic import generator

    calls: list[tuple[str, dict, float]] = []

    def fake_post_json(url, payload, timeout_s):
        calls.append((url, dict(payload), timeout_s))
        return {"response": json.dumps(_generated_cases_payload("ollama_case"))}

    generated = generator.generate_cases_with_engine(
        provider="ollama",
        endpoint="http://127.0.0.1:11434",
        model="local-model",
        topic="classroom diagnostics",
        case_count=1,
        post_json=fake_post_json,
    )

    assert generated["cases"][0]["case_id"] == "ollama_case"
    assert calls[0][0] == "http://127.0.0.1:11434/api/generate"
    assert calls[0][1]["options"]["temperature"] == 0.2

    with pytest.raises(DiagnosticCaseGenerationError, match="Unsupported standalone AI provider"):
        generator.generate_cases_with_engine(
            provider="bad",
            endpoint="",
            model="local-model",
            topic="classroom diagnostics",
            case_count=1,
            post_json=fake_post_json,
        )

    output_path = generator.generate_case_file(
        tmp_path / "nested",
        filename="cases.json",
        provider="ollama",
        endpoint="http://127.0.0.1:11434/api/generate",
        model="local-model",
        topic="classroom diagnostics",
        case_count=1,
        temperature=0.2,
        timeout_s=3.0,
        post_json=fake_post_json,
    )
    assert output_path.is_file()


def test_tescia_generator_post_json_rejects_endpoint_failures(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(APP_SRC))

    from urllib.error import URLError
    from tescia_diagnostic import DiagnosticCaseGenerationError
    from tescia_diagnostic import generator

    def failing_urlopen(*_args, **_kwargs):
        raise URLError("offline")

    monkeypatch.setattr(generator, "urlopen", failing_urlopen)

    with pytest.raises(DiagnosticCaseGenerationError, match="Unable to reach standalone AI endpoint"):
        generator._post_json("http://127.0.0.1:1", {"x": 1}, 0.01)


def test_tescia_generator_post_json_rejects_bad_endpoint_payloads(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(APP_SRC))

    from tescia_diagnostic import DiagnosticCaseGenerationError
    from tescia_diagnostic import generator

    class FakeResponse:
        def __init__(self, body: str) -> None:
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *_exc_info) -> None:
            return None

        def read(self) -> bytes:
            return self.body.encode("utf-8")

    monkeypatch.setattr(generator, "urlopen", lambda *_args, **_kwargs: FakeResponse("not json"))
    with pytest.raises(DiagnosticCaseGenerationError, match="returned invalid JSON"):
        generator._post_json("http://local.invalid", {"x": 1}, 1.0)

    monkeypatch.setattr(generator, "urlopen", lambda *_args, **_kwargs: FakeResponse("[1, 2]"))
    with pytest.raises(DiagnosticCaseGenerationError, match="returned a non-object response"):
        generator._post_json("http://local.invalid", {"x": 1}, 1.0)


def test_tescia_app_args_reject_invalid_generation_config(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(APP_SRC))

    from tescia_diagnostic import TesciaDiagnosticArgs, ensure_defaults, merge_args

    with pytest.raises(ValueError, match="files must select JSON"):
        TesciaDiagnosticArgs(files="*.txt")
    with pytest.raises(ValueError, match="generated_cases_filename"):
        TesciaDiagnosticArgs(generated_cases_filename="../bad.json")
    with pytest.raises(ValueError, match="ai_endpoint is required"):
        TesciaDiagnosticArgs(case_source="standalone_ai", ai_endpoint="")
    with pytest.raises(ValueError, match="ai_model is required"):
        TesciaDiagnosticArgs(case_source="standalone_ai", ai_model="")
    with pytest.raises(ValueError, match="ai_topic is required"):
        TesciaDiagnosticArgs(case_source="standalone_ai", ai_topic="")
    args = TesciaDiagnosticArgs()
    assert ensure_defaults(args) is args
    assert merge_args(args, {"nfile": 2}).nfile == 2


def test_tescia_diagnostic_selects_evidence_backed_fix(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(APP_SRC))

    from tescia_diagnostic import diagnose_case

    report = diagnose_case(_load_cases()[0])

    assert report["status"] == "actionable"
    assert report["case_id"] == "cluster_share_sshfs"
    assert report["catalog"]["title"] == "Diagnose a remote cluster-share failure"
    assert report["catalog"]["difficulty"] == "intermediate"
    assert "regression-plan" in report["catalog"]["topic_tags"]
    assert report["selected_fix"]["id"] == "mount_scheduler_share_with_sshfs"
    assert report["evidence_quality"] >= 0.85
    assert report["regression_coverage"] >= 0.75
    assert report["case_quality_score"] >= 85.0
    assert 85.0 <= report["student_score"] <= 100.0
    assert report["self_evaluation"]["status"] == "submitted"
    assert report["self_evaluation"]["score_band"] == "excellent"
    assert report["self_evaluation"]["expected"]["selected_fix_id"] == "mount_scheduler_share_with_sshfs"
    assert report["self_evaluation"]["student"]["selected_fix_id"] == "mount_scheduler_share_with_sshfs"
    assert report["self_evaluation"]["feedback"] == ["Answer is aligned with the reference diagnostic contract."]
    assert "SSH login success proves the shared data path is usable." in report["weak_assumptions"]


def test_tescia_classroom_metadata_anonymizes_student_ids(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(APP_SRC))

    from tescia_diagnostic import diagnose_case

    case = {
        **_load_cases()[0],
        "case_id": "submitted_cluster_share",
        "exercise_id": "cluster_share_sshfs",
        "class_id": "math_2026_demo_class",
        "session_id": "live_session_001",
        "student_id": "student-001",
        "anonymize_student": True,
    }
    report = diagnose_case(case)

    assert report["classroom"]["exercise_id"] == "cluster_share_sshfs"
    assert report["classroom"]["class_id"] == "math_2026_demo_class"
    assert report["classroom"]["student_ref"].startswith("student_")
    assert "student_id" not in report["classroom"]
    summary = __import__("tescia_diagnostic").summarize_report(report)
    assert summary["student_ref"] == report["classroom"]["student_ref"]
    assert summary["exercise_id"] == "cluster_share_sshfs"


def test_tescia_rejects_student_answer_unknown_ids(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(APP_SRC))

    from tescia_diagnostic import validate_case_payload

    payload = json.loads(SAMPLE_CASES.read_text(encoding="utf-8"))
    payload["cases"][0]["student_answer"]["evidence_ids"].append("missing_evidence")

    with pytest.raises(ValueError, match="unknown evidence ids: missing_evidence"):
        validate_case_payload(payload)


def test_tescia_case_payload_rejects_invalid_schema_edges(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(APP_SRC))

    from tescia_diagnostic import validate_case_payload

    def sample_payload() -> dict:
        return json.loads(SAMPLE_CASES.read_text(encoding="utf-8"))

    def expect_error(mutator, match: str) -> None:
        payload = sample_payload()
        mutator(payload)
        with pytest.raises(ValueError, match=match):
            validate_case_payload(payload, expected_case_count=1 if match == "expected 1" else None)

    expect_error(lambda payload: payload.update(schema="bad"), "Diagnostic cases must declare schema")
    expect_error(lambda payload: payload.update(cases=[]), "non-empty cases list")
    expect_error(lambda payload: payload["cases"].pop(), "expected 1")
    expect_error(lambda payload: payload["cases"].__setitem__(0, "bad"), "Case #1 must be an object")
    expect_error(lambda payload: payload["cases"][0].pop("symptom"), "is missing fields")
    expect_error(lambda payload: payload["cases"][0].update(evidence="bad"), "at least two evidence")
    expect_error(lambda payload: payload["cases"][0].update(candidate_fixes=[]), "at least two candidate")
    expect_error(lambda payload: payload["cases"][0].update(regression_tests=[]), "at least two regression")
    expect_error(lambda payload: payload["cases"][0].update(curriculum_ids=[""]), "curriculum_ids")
    expect_error(lambda payload: payload["cases"][0].update(topic_tags=[1]), "topic_tags")
    expect_error(lambda payload: payload["cases"][0].update(class_id=""), "class_id")
    expect_error(lambda payload: payload["cases"][0].update(anonymize_student="yes"), "anonymize_student")
    expect_error(lambda payload: payload["cases"][0].update(difficulty="expert"), "difficulty")
    expect_error(lambda payload: payload["cases"][0].update(estimated_minutes=0), "estimated_minutes")
    expect_error(lambda payload: payload["cases"][0]["evidence"].__setitem__(0, "bad"), "invalid evidence")
    expect_error(lambda payload: payload["cases"][0]["evidence"][0].update(confidence="bad"), "must be numeric")
    expect_error(lambda payload: payload["cases"][0]["candidate_fixes"].__setitem__(0, "bad"), "invalid candidate fix")
    expect_error(lambda payload: payload["cases"][0].update(student_answer="bad"), "student_answer")
    expect_error(lambda payload: payload["cases"][0]["student_answer"].update(diagnosis=""), "student_answer.diagnosis")
    expect_error(lambda payload: payload["cases"][0]["student_answer"].update(evidence_ids="bad"), "student_answer.evidence_ids")
    expect_error(lambda payload: payload["cases"][0]["student_answer"].update(selected_fix_id="missing"), "selected_fix_id")
    expect_error(lambda payload: payload["cases"][0]["student_answer"].update(regression_test_ids=["missing"]), "regression test ids")


def test_tescia_diagnostic_scores_unsubmitted_and_partial_answers(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(APP_SRC))

    from tescia_diagnostic import (
        classroom_metadata,
        diagnose_case,
        evaluate_student_answer,
        evidence_quality,
        rank_candidate_fixes,
        regression_coverage,
        summarize_report,
    )

    case = dict(_load_cases()[0])
    case.pop("student_answer", None)
    report = diagnose_case(case, minimum_evidence_confidence=0.99, minimum_regression_coverage=0.99)
    assert report["status"] == "needs_more_evidence"
    assert report["self_evaluation"]["status"] == "not_submitted"
    assert "Submit a student_answer" in report["self_evaluation"]["feedback"][0]

    no_rows_case = {
        "root_cause": "",
        "evidence": [],
        "candidate_fixes": [],
        "regression_tests": [],
        "student_answer": {"root_cause": "wrong", "evidence_ids": [], "selected_fix_id": "", "regression_test_ids": []},
    }
    assert evidence_quality(no_rows_case) == 0.0
    assert regression_coverage(no_rows_case) == 0.0
    assert rank_candidate_fixes(no_rows_case, evidence_score=0.0, regression_score=0.0) == []
    partial = evaluate_student_answer(no_rows_case, ranked_fixes=[], evidence_score=0.0, regression_score=0.0)
    assert partial["score_band"] == "needs_work"
    assert "Root cause explanation" in partial["feedback"][0]

    metadata = classroom_metadata(
        {
            "case_id": "exercise",
            "class_id": "class",
            "session_id": "session",
            "student_id": "Alice Smith",
            "display_name": "Alice",
            "anonymize_student": False,
        }
    )
    assert metadata["student_ref"] == "Alice_Smith"
    assert metadata["student_id"] == "Alice Smith"
    assert metadata["display_name"] == "Alice"

    summary = summarize_report(
        {
            "case_id": "x",
            "catalog": "bad",
            "self_evaluation": "bad",
            "classroom": "bad",
            "selected_fix": "bad",
            "weak_assumptions": "bad",
            "regression_plan": "bad",
        }
    )
    assert summary["selected_fix_id"] == ""
    assert summary["feedback_count"] == 0


def test_tescia_math_program_2026_curriculum_contract_is_complete(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(APP_SRC))

    from tescia_diagnostic import (
        build_math_program_2026_coverage_report,
        load_math_program_2026,
        require_complete_math_program_2026_coverage,
    )

    cases = _load_cases()
    curriculum = load_math_program_2026()
    report = require_complete_math_program_2026_coverage(cases, curriculum)

    assert report["schema"] == "agilab.tescia_diagnostic.math_program_coverage_report.v1"
    assert report["coverage_scope"] == "france_math_program_2026_rollout_top_level_domains"
    assert report["required_count"] == 28
    assert report["required_min_cases_per_id"] == 2
    assert report["covered_count"] == report["required_count"]
    assert report["coverage_ratio"] == 1.0
    assert report["quality_passed"] is True
    assert report["missing_curriculum_ids"] == []
    assert report["undercovered_curriculum_ids"] == []
    assert all(count >= 2 for count in report["curriculum_id_counts"].values())
    assert "seconde_gt_fonctions" in report["covered_curriculum_ids"]
    assert "premiere_generale_specialite_analyse" in report["covered_curriculum_ids"]
    assert any(source["id"] == "eduscol_math_2026" for source in report["sources"])

    partial = build_math_program_2026_coverage_report(cases[:2], curriculum)
    assert partial["coverage_ratio"] == 0.0
    assert len(partial["missing_curriculum_ids"]) == 28
    assert partial["quality_passed"] is False

    undercovered = build_math_program_2026_coverage_report(cases[:7], curriculum)
    assert undercovered["missing_curriculum_ids"] == []
    assert len(undercovered["undercovered_curriculum_ids"]) == 28
    with pytest.raises(ValueError, match="Undercovered 2026 math curriculum ids"):
        require_complete_math_program_2026_coverage(cases[:7], curriculum)


def test_tescia_math_program_2026_rejects_unknown_curriculum_id(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(APP_SRC))

    from tescia_diagnostic import build_math_program_2026_coverage_report, load_math_program_2026

    cases = _load_cases()
    cases[0] = {**cases[0], "curriculum_ids": ["unknown_2026_path"]}

    with pytest.raises(ValueError, match="unknown 2026 math curriculum ids"):
        build_math_program_2026_coverage_report(cases, load_math_program_2026())


def test_tescia_math_program_2026_rejects_invalid_curriculum_contracts(monkeypatch, tmp_path) -> None:
    monkeypatch.syspath_prepend(str(APP_SRC))

    from tescia_diagnostic.curriculum import (
        CURRICULUM_SCHEMA,
        case_curriculum_ids,
        curriculum_id_counts,
        load_math_program_2026,
        required_min_cases_per_id,
        validate_math_program_2026,
    )

    valid = {
        "schema": CURRICULUM_SCHEMA,
        "sources": [{"id": "official"}],
        "required_min_cases_per_id": 2,
        "required_program_ids": [
            {
                "id": "prog",
                "source_id": "official",
                "track": "track",
                "level": "level",
                "domain": "domain",
                "effective_school_year": "2026",
            }
        ],
    }

    def expect_error(mutator, match: str) -> None:
        payload = json.loads(json.dumps(valid))
        mutator(payload)
        with pytest.raises(ValueError, match=match):
            validate_math_program_2026(payload)

    expect_error(lambda payload: payload.update(schema="bad"), "must declare schema")
    expect_error(lambda payload: payload.update(sources=[]), "non-empty sources")
    expect_error(lambda payload: payload.update(required_program_ids=[]), "required_program_ids")
    expect_error(lambda payload: payload["required_program_ids"].__setitem__(0, "bad"), "must be an object")
    expect_error(lambda payload: payload["required_program_ids"][0].update(id=""), "must have an id")
    expect_error(lambda payload: payload["required_program_ids"].append(dict(payload["required_program_ids"][0])), "Duplicate")
    expect_error(lambda payload: payload["required_program_ids"][0].update(source_id="unknown"), "unknown source_id")
    expect_error(lambda payload: payload["required_program_ids"][0].update(domain=""), "missing domain")

    assert required_min_cases_per_id({"required_min_cases_per_id": "bad"}) == 1
    assert case_curriculum_ids({"curriculum_ids": "prog"}) == []
    assert curriculum_id_counts([{"curriculum_ids": ["prog", "prog"]}]) == {"prog": 1}

    invalid_file = tmp_path / "math_program.json"
    invalid_file.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="must contain a JSON object"):
        load_math_program_2026(invalid_file)


def test_tescia_app_surface_catalog_answer_and_authoring_helpers(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(APP_SRC))
    module = _load_app_surface_module()

    cases = module.load_cases()
    rows = module.catalog_rows(cases)
    filters = module.available_filters(cases)

    assert any(row["case_id"] == "math_2026_seconde_gt_coverage" for row in rows)
    assert "seconde student" in filters["learner_level"]
    assert "seconde_gt_fonctions" in filters["curriculum_id"]
    filtered = module.filter_cases(cases, curriculum_id="seconde_gt_fonctions")
    assert {case["case_id"] for case in filtered} == {
        "math_2026_seconde_gt_coverage",
        "math_2026_seconde_gt_practice_round",
    }

    answer = module.build_student_answer(
        diagnosis="Not enough domains",
        root_cause="The 2026 seconde GT catalog needs a second case covering logic and sets, algorithmic programming, automatisms, numbers and algebra, geometry, functions, and statistics and probabilities.",
        evidence_ids="seconde_min_count_contract,seconde_second_round_ids",
        selected_fix_id="keep_seconde_full_second_round",
        regression_test_ids="seconde_min_counts,seconde_no_undercovered_ids",
        confidence=0.9,
    )
    report = module.score_student_submission(filtered[1], answer)
    assert report["self_evaluation"]["status"] == "submitted"
    assert report["student_score"] >= 85.0

    classroom_report = module.classroom_preview_report(cases)
    assert classroom_report["submission_count"] == 4
    assert classroom_report["unique_student_count"] == 4
    assert classroom_report["needs_attention_count"] == 1
    assert module.classroom_progress_rows(classroom_report)[0]["student_ref"].startswith("student_")
    assert module.classroom_heatmap_rows(classroom_report)[0]["exercise_id"]
    template = module.classroom_submission_template(cases)
    assert template["schema"] == "agilab.tescia_diagnostic.classroom.v1"
    assert template["submission_count"] == 4

    draft = module.build_teacher_draft(
        case_id="teacher_case",
        title="Teacher case",
        curriculum_ids=["seconde_gt_fonctions"],
        prompt="Solve and justify.",
        root_cause="The answer must justify the function behavior.",
        selected_fix_id="complete_function_reasoning",
    )
    assert draft["case_id"] == "teacher_case"
    assert draft["curriculum_ids"] == ["seconde_gt_fonctions"]
    with pytest.raises(ValueError, match="At least one curriculum id"):
        module.build_teacher_draft(
            case_id="teacher_case",
            title="Teacher case",
            curriculum_ids=[],
            prompt="Solve and justify.",
            root_cause="The answer must justify the function behavior.",
            selected_fix_id="complete_function_reasoning",
        )
    with pytest.raises(ValueError, match="case_id is required"):
        module.build_teacher_draft(
            case_id="",
            title="Teacher case",
            curriculum_ids=["seconde_gt_fonctions"],
            prompt="Solve and justify.",
            root_cause="The answer must justify the function behavior.",
            selected_fix_id="complete_function_reasoning",
        )


def test_tescia_app_surface_cache_and_artifact_edge_paths(monkeypatch, tmp_path) -> None:
    monkeypatch.syspath_prepend(str(APP_SRC))
    module = _load_app_surface_module()

    assert module._file_mtime_ns(None) == 0
    assert module._file_mtime_ns(tmp_path / "missing.json") == 0
    assert module.latest_classroom_report_path([tmp_path / "empty"]) is None
    assert module._resolve_active_app_path(tmp_path / "missing_app") is None
    assert module._resolve_active_app_path(tmp_path) == tmp_path.resolve()
    assert module.classroom_progress_rows({"progress_rows": "bad"}) == []
    assert module.classroom_heatmap_rows({"heatmap_rows": "bad"}) == []

    bad_payload = tmp_path / "bad_classroom_report.json"
    bad_payload.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="must be a JSON object"):
        module.cached_load_classroom_run_report(str(bad_payload), module._file_mtime_ns(bad_payload))

    bad_payload.write_text(json.dumps({"schema": "bad"}), encoding="utf-8")
    with pytest.raises(ValueError, match="Unexpected classroom run report schema"):
        module.cached_load_classroom_run_report(str(bad_payload), module._file_mtime_ns(bad_payload))

    env = _FakeEnv(tmp_path)
    active_app = tmp_path / "tescia_diagnostic_project"
    active_app.mkdir()
    paths = module.classroom_artifact_dirs(
        active_app,
        env=env,
        args_model=SimpleNamespace(data_out=Path("tescia_diagnostic/reports")),
    )
    assert env.AGILAB_EXPORT_ABS / env.target / "tescia_diagnostic" / "classroom" in paths
    assert env.share_root_path() / "tescia_diagnostic" / "reports" / "classroom" in paths
    report, source = module.classroom_display_report(cases=None, active_app=None, env=env, args_model=SimpleNamespace(data_out=tmp_path / "missing"))
    assert source["source"] == "sample"
    assert report["submission_count"] == 4


def test_tescia_app_surface_runtime_loader_and_filter_edges(monkeypatch, tmp_path) -> None:
    monkeypatch.syspath_prepend(str(APP_SRC))
    module = _load_app_surface_module()

    fake_env = _FakeEnv(tmp_path)
    fake_env.app_settings_file = str(tmp_path / "settings.toml")

    class FakeAgiEnv:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    created_env = FakeAgiEnv(apps_path=tmp_path, app="tescia_diagnostic_project", verbose=0)
    monkeypatch.setitem(sys.modules, "agi_env", SimpleNamespace(AgiEnv=lambda **_kwargs: created_env))

    import tescia_diagnostic.app_args as app_args

    args = app_args.TesciaDiagnosticArgs(data_out=Path("custom_reports"))
    monkeypatch.setattr(app_args, "load_args", lambda _path: args)
    monkeypatch.setattr(app_args, "ensure_defaults", lambda loaded_args, **_kwargs: loaded_args)
    env, loaded_args = module._load_runtime_env_and_args(tmp_path / "tescia_diagnostic_project")
    assert env is created_env
    assert loaded_args is args

    cases = module.load_cases()
    assert module.filter_cases(cases, difficulty="advanced-only") == []
    assert module.filter_cases(cases, learner_level="missing-level") == []
    assert module.filter_cases(cases, curriculum_id="missing_id") == []
    answer = module.build_student_answer(
        diagnosis="diagnosis",
        root_cause="root",
        evidence_ids=["a", "b"],
        selected_fix_id="fix",
        regression_test_ids=["r"],
        confidence=0.4,
    )
    assert answer["evidence_ids"] == ["a", "b"]


def test_tescia_app_surface_cache_decorator_fallbacks(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(APP_SRC))

    original_import = builtins.__import__

    def blocked_import(name, *args, **kwargs):
        if name == "streamlit":
            raise ImportError("streamlit hidden")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)
    module = _load_app_surface_module()
    assert module.cached_load_cases(str(SAMPLE_CASES), module._file_mtime_ns(SAMPLE_CASES))[0]["case_id"]

    class BrokenCacheStreamlit:
        def cache_data(self, *_args, **_kwargs):
            raise RuntimeError("cache unavailable")

    monkeypatch.setattr(builtins, "__import__", original_import)
    monkeypatch.setitem(sys.modules, "streamlit", BrokenCacheStreamlit())
    module = _load_app_surface_module()
    assert module.cached_load_cases(str(SAMPLE_CASES), module._file_mtime_ns(SAMPLE_CASES))[0]["case_id"]


def test_tescia_app_surface_configure_mode_delegates_to_args_form(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(APP_SRC))
    module = _load_app_surface_module()
    calls: list[tuple[str, str]] = []

    def fake_run_path(path: str, *, run_name: str) -> None:
        calls.append((path, run_name))

    monkeypatch.setattr(module.runpy, "run_path", fake_run_path)

    module.render(mode="configure")

    assert calls == [(str(APP_SRC / "app_args_form.py"), "__main__")]
    with pytest.raises(ValueError, match="Unsupported TeSciA app surface mode"):
        module.render(mode="sidecar")


def test_tescia_app_surface_render_covers_classroom_tabs(monkeypatch, tmp_path) -> None:
    fake_env = _FakeEnv(tmp_path)
    class InteractiveStreamlit(_FakeStreamlit):
        def __init__(self, env: _FakeEnv) -> None:
            super().__init__(env)
            self.button_labels_to_click = {"Evaluate answer"}

        def button(self, label, *_args, **_kwargs) -> bool:
            self.buttons.append(label)
            return label in self.button_labels_to_click

        def set_page_config(self, *_args, **_kwargs) -> None:
            return None

    fake_streamlit = InteractiveStreamlit(fake_env)
    monkeypatch.setitem(sys.modules, "streamlit", fake_streamlit)
    monkeypatch.syspath_prepend(str(APP_SRC))
    module = _load_app_surface_module()

    module.render(mode="full")

    assert ("Submissions", 4) in fake_streamlit.metrics
    assert any(label == "Student score" for label, _value in fake_streamlit.metrics)
    assert "Download correction sheet" in fake_streamlit.downloads
    assert "Download teacher summary" in fake_streamlit.downloads
    assert "Download classroom batch JSON" in fake_streamlit.downloads
    assert "Refresh classroom artifacts" in fake_streamlit.buttons
    assert len(fake_streamlit.dataframes) >= 4


def test_tescia_app_surface_live_refresh_branch(monkeypatch, tmp_path) -> None:
    fake_env = _FakeEnv(tmp_path)

    class RefreshingStreamlit(_FakeStreamlit):
        def checkbox(self, *_args, **kwargs) -> bool:
            return True

        def number_input(self, *_args, **kwargs):
            return 2

    fake_streamlit = RefreshingStreamlit(fake_env)
    monkeypatch.setitem(sys.modules, "streamlit", fake_streamlit)
    monkeypatch.syspath_prepend(str(APP_SRC))
    module = _load_app_surface_module()
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)

    module.render(mode="analysis")

    assert fake_streamlit.rerun_called is True


def test_tescia_printable_correction_sheet_export(monkeypatch, tmp_path) -> None:
    monkeypatch.syspath_prepend(str(APP_SRC))

    from tescia_diagnostic import diagnose_case, diagnostic_report_to_markdown, write_correction_sheet

    report = diagnose_case(_load_cases()[2])
    markdown = diagnostic_report_to_markdown(report)

    assert markdown.startswith("# Audit a 5e diagnostic exercise")
    assert "## Student Answer" in markdown
    assert "## Reference" in markdown
    assert "Answer is aligned" in markdown
    output_path = write_correction_sheet(report, tmp_path)
    assert output_path.name == "math_2026_cycle4_5e_coverage_correction.md"
    assert "Student score" in output_path.read_text(encoding="utf-8")


def test_tescia_printable_exports_handle_missing_optional_sections(monkeypatch, tmp_path) -> None:
    monkeypatch.syspath_prepend(str(APP_SRC))

    from tescia_diagnostic.exports import diagnostic_report_to_markdown, write_correction_index, write_correction_sheet

    report = {
        "case_id": "messy case/id",
        "catalog": "bad",
        "self_evaluation": "bad",
        "selected_fix": "bad",
        "weak_assumptions": "bad",
        "regression_plan": "bad",
    }
    markdown = diagnostic_report_to_markdown(report)
    assert markdown.startswith("# messy case/id")
    assert "No feedback." in markdown
    assert "No weak assumptions recorded." in markdown
    assert "No regression plan recorded." in markdown
    assert write_correction_sheet(report, tmp_path).name == "messy_case_id_correction.md"
    assert write_correction_index([], tmp_path).read_text(encoding="utf-8").startswith("# TeSciA Correction Sheets")


def test_tescia_classroom_batch_scores_and_exports_teacher_artifacts(monkeypatch, tmp_path) -> None:
    monkeypatch.syspath_prepend(str(APP_SRC))

    from tescia_diagnostic import (
        build_classroom_run_report,
        classroom_report_to_markdown,
        expand_classroom_submissions,
        load_case_bank,
        score_classroom_submissions,
        validate_classroom_payload,
        write_classroom_artifacts,
    )
    from tescia_diagnostic import diagnose_case

    payload = validate_classroom_payload(_load_classroom_payload())
    expanded = expand_classroom_submissions(payload, case_bank=load_case_bank())

    assert len(expanded) == 4
    assert expanded[0]["case_id"] == "live_001_cluster_share_sshfs"
    assert expanded[0]["exercise_id"] == "cluster_share_sshfs"
    assert expanded[0]["student_ref"].startswith("student_")
    assert "student_id" not in expanded[0]

    classroom_report = score_classroom_submissions(payload, case_bank=load_case_bank())
    assert classroom_report["schema"] == "agilab.tescia_diagnostic.classroom_run_report.v1"
    assert classroom_report["submission_count"] == 4
    assert classroom_report["unique_student_count"] == 4
    assert classroom_report["needs_attention_count"] == 1
    assert classroom_report["cluster_execution"]["parallel_unit"] == "classroom submission"
    assert classroom_report["cluster_execution"]["recommended_worker_count"] == 4
    assert any(row["exercise_id"] == "pipeline_dag_stale_preview" for row in classroom_report["needs_attention_rows"])
    markdown = classroom_report_to_markdown(classroom_report)
    assert markdown.startswith("# TeSciA Classroom Teacher Summary")
    assert "## Weakest Curriculum Areas" in markdown
    assert "## Suggested Next Exercise Ids" in markdown

    reports = [diagnose_case(case) for case in expanded]
    rebuilt = build_classroom_run_report(reports)
    paths = write_classroom_artifacts(rebuilt, tmp_path)
    assert json.loads(paths["report"].read_text(encoding="utf-8"))["submission_count"] == 4
    assert paths["teacher_summary"].name == "classroom_teacher_summary.md"
    assert "student_score" in paths["progress"].read_text(encoding="utf-8")
    assert "pipeline_dag_stale_preview" in paths["heatmap"].read_text(encoding="utf-8")
    assert "classroom_curriculum.csv" == paths["curriculum"].name


def test_tescia_classroom_rejects_invalid_batches_and_supports_named_students(monkeypatch, tmp_path) -> None:
    monkeypatch.syspath_prepend(str(APP_SRC))

    from tescia_diagnostic import diagnose_case
    from tescia_diagnostic.classroom import (
        CLASSROOM_SCHEMA,
        build_classroom_run_report,
        classroom_report_to_markdown,
        expand_classroom_submissions,
        load_case_bank,
        load_classroom_payload,
        validate_classroom_payload,
        write_classroom_artifacts,
    )

    def classroom_payload() -> dict:
        return json.loads(SAMPLE_CLASSROOM.read_text(encoding="utf-8"))

    def expect_error(mutator, match: str) -> None:
        payload = classroom_payload()
        mutator(payload)
        with pytest.raises(ValueError, match=match):
            validate_classroom_payload(payload)

    expect_error(lambda payload: payload.update(schema="bad"), "must declare schema")
    expect_error(lambda payload: payload["classroom"].update(class_id=""), "classroom.class_id")
    expect_error(lambda payload: payload["classroom"].update(session_id=""), "classroom.session_id")
    expect_error(lambda payload: payload.update(submissions=[]), "non-empty submissions")
    expect_error(lambda payload: payload["submissions"].__setitem__(0, "bad"), "must be an object")
    expect_error(lambda payload: payload["submissions"][0].update(student_id=""), "student_id")
    expect_error(lambda payload: payload["submissions"][0].update(case_id=""), "case_id")
    expect_error(lambda payload: payload["submissions"][0].update(answer="bad"), "answer as an object")
    expect_error(
        lambda payload: payload["submissions"].append(dict(payload["submissions"][0])),
        "Duplicate classroom submission_id",
    )

    payload = classroom_payload()
    payload["schema"] = CLASSROOM_SCHEMA
    payload["classroom"]["anonymize_student"] = "false"
    payload["submissions"] = [payload["submissions"][0]]
    payload["submissions"][0]["student_id"] = "Alice Smith"
    payload["submissions"][0]["display_name"] = "Alice"
    payload["submissions"][0]["submission_id"] = "Alice case"
    payload["submissions"][0]["anonymize_student"] = "no"
    expanded = expand_classroom_submissions(payload, case_bank=load_case_bank())
    assert expanded[0]["student_ref"] == "Alice_Smith"
    assert expanded[0]["student_id"] == "Alice Smith"
    assert expanded[0]["display_name"] == "Alice"
    report = diagnose_case(expanded[0])
    paths = write_classroom_artifacts(report, tmp_path)
    assert paths["report"].is_file()

    embedded = classroom_payload()
    embedded["case_bank"] = json.loads(SAMPLE_CASES.read_text(encoding="utf-8"))
    assert len(expand_classroom_submissions(embedded)) == 4
    embedded["submissions"][0]["case_id"] = "missing"
    with pytest.raises(ValueError, match="unknown case_id"):
        expand_classroom_submissions(embedded)

    bad_file = tmp_path / "bad.json"
    bad_file.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="case bank must be a JSON object"):
        load_case_bank(bad_file)
    with pytest.raises(ValueError, match="classroom submissions must be a JSON object"):
        load_classroom_payload(bad_file)

    empty_report = build_classroom_run_report([])
    assert empty_report["submission_count"] == 0
    empty_markdown = classroom_report_to_markdown(empty_report)
    assert "No submitted answers." in empty_markdown
    assert "No exercise evidence yet." in empty_markdown


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
    assert artifact.partial_count == len(summaries)
    assert artifact.payload["case_count"] == len(summaries)
    assert artifact.payload["actionable_count"] == len(summaries)
    assert "cluster_share_sshfs" in artifact.payload["case_ids"]
    assert "math_2026_seconde_gt_coverage" in artifact.payload["case_ids"]
    assert "mount_scheduler_share_with_sshfs" in artifact.payload["selected_fix_ids"]
    assert 85.0 <= artifact.payload["student_score_mean"] <= 100.0


def test_tescia_reduce_contract_counts_duplicate_case_runs(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(APP_SRC))

    from tescia_diagnostic import build_reduce_artifact, partial_from_diagnostic_summary

    first = {
        "case_id": "duplicate_case",
        "status": "actionable",
        "root_cause": "root cause",
        "selected_fix_id": "strong_fix",
        "evidence_quality": 0.9,
        "regression_coverage": 0.8,
        "student_score": 90.0,
        "weak_assumption_count": 1,
        "regression_step_count": 2,
    }
    second = {**first, "status": "needs_more_evidence", "student_score": 50.0}

    artifact = build_reduce_artifact(
        (
            partial_from_diagnostic_summary(first, partial_id="first"),
            partial_from_diagnostic_summary(second, partial_id="second"),
        )
    )

    assert artifact.payload["case_count"] == 2
    assert artifact.payload["unique_case_count"] == 1
    assert artifact.payload["case_ids"] == ["duplicate_case"]
    assert artifact.payload["student_score_mean"] == 70.0


def test_tescia_reduce_contract_rejects_missing_or_empty_payloads(monkeypatch, tmp_path) -> None:
    monkeypatch.syspath_prepend(str(APP_SRC))

    from tescia_diagnostic import (
        TESCIA_DIAGNOSTIC_REDUCE_CONTRACT,
        partial_from_diagnostic_summary,
        reduce_artifact_path,
        write_reduce_artifact,
    )

    with pytest.raises(ValueError, match="missing columns"):
        partial_from_diagnostic_summary({"case_id": "only"}, partial_id="bad")
    with pytest.raises(ValueError, match="produced no cases"):
        TESCIA_DIAGNOSTIC_REDUCE_CONTRACT.build_artifact([])
    assert reduce_artifact_path(tmp_path, "abc").name == "reduce_summary_worker_abc.json"

    summary = {
        "case_id": "needs_more",
        "status": "needs_more_evidence",
        "root_cause": "root",
        "selected_fix_id": "",
        "evidence_quality": 0.1,
        "regression_coverage": 0.2,
        "student_score": 30.0,
        "weak_assumption_count": 1,
        "regression_step_count": 1,
    }
    path = write_reduce_artifact([summary], tmp_path, worker_id=7)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["payload"]["needs_more_evidence_count"] == 1
    assert payload["payload"]["selected_fix_ids"] == []


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


def test_tescia_manager_handles_config_and_dataset_edge_paths(monkeypatch, tmp_path) -> None:
    monkeypatch.syspath_prepend(str(APP_SRC))

    from tescia_diagnostic import (
        DiagnosticCaseGenerationError,
        TesciaDiagnostic,
        TesciaDiagnosticArgs,
        dump_args,
        load_args,
    )

    env = _FakeEnv(tmp_path)
    with pytest.raises(ValueError, match="Invalid TeSciA diagnostic arguments"):
        TesciaDiagnostic(env, files="*.txt")

    app = TesciaDiagnostic(env, reset_target=True)
    old_file = Path(app.data_out) / "old.txt"
    old_file.write_text("old", encoding="utf-8")
    app = TesciaDiagnostic(env, reset_target=True)
    assert not old_file.exists()

    settings = tmp_path / "settings.toml"
    app.to_toml(settings)
    loaded = TesciaDiagnostic.from_toml(env, settings)
    assert loaded.as_dict()["case_source"] == "bundled"
    dump_args(TesciaDiagnosticArgs(nfile=3), settings)
    assert load_args(settings).nfile == 3

    missing_env = _FakeEnv(tmp_path / "missing")
    monkeypatch.setattr(TesciaDiagnostic, "_sample_dataset_source", lambda self: tmp_path / "missing_cases.json")
    with pytest.raises(FileNotFoundError, match="Bundled TeSciA diagnostic cases missing"):
        TesciaDiagnostic(missing_env)

    missing_classroom_env = _FakeEnv(tmp_path / "missing_classroom")
    monkeypatch.setattr(
        TesciaDiagnostic,
        "_classroom_dataset_source",
        lambda self: tmp_path / "missing_classroom.json",
    )
    with pytest.raises(FileNotFoundError, match="Bundled TeSciA classroom submissions missing"):
        TesciaDiagnostic(missing_classroom_env, case_source="bundled_classroom")

    def failing_generate(*_args, **_kwargs):
        raise DiagnosticCaseGenerationError("offline")

    generated_env = _FakeEnv(tmp_path / "generated")
    with pytest.raises(RuntimeError, match="Standalone AI case generation failed"):
        TesciaDiagnostic(generated_env, case_source="standalone_ai", _generate_case_file_fn=failing_generate)


def test_tescia_manager_distribution_multiple_files_and_empty_pattern(monkeypatch, tmp_path) -> None:
    monkeypatch.syspath_prepend(str(APP_SRC))

    from tescia_diagnostic import TesciaDiagnostic

    env = _FakeEnv(tmp_path)
    data_in = env.share_root_path() / "custom_cases"
    data_in.mkdir(parents=True)
    for index in range(2):
        payload = _generated_cases_payload(case_id=f"generated_{index}")
        (data_in / f"case_{index}.json").write_text(json.dumps(payload), encoding="utf-8")
    app = TesciaDiagnostic(env, data_in=Path("custom_cases"), nfile=2)

    work_plan, metadata, *_ = app.build_distribution({"127.0.0.1": 2})
    assert len(work_plan) >= 1
    assert sum(len(batch[0]) for batch in work_plan) == 2
    assert metadata[0][0]["size_kb"] >= 1

    for path in data_in.glob("*.json"):
        path.unlink()
    with pytest.raises(FileNotFoundError, match="No diagnostic case file found"):
        app.build_distribution({"127.0.0.1": 1})


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


def test_tescia_manager_can_seed_bundled_classroom_sample(monkeypatch, tmp_path) -> None:
    monkeypatch.syspath_prepend(str(APP_SRC))

    from tescia_diagnostic import TesciaDiagnostic

    env = _FakeEnv(tmp_path)
    app = TesciaDiagnostic(env, case_source="bundled_classroom")

    seeded = env.share_root_path() / "tescia_diagnostic" / "cases" / "tescia_classroom_submissions.json"
    assert seeded.is_file()
    work_plan, metadata, label_key, size_key, size_unit = app.build_distribution({"127.0.0.1": 2})
    assert work_plan == [[[str(seeded)]]]
    assert metadata[0][0]["diagnostic_file"] == "tescia_classroom_submissions.json"
    assert (label_key, size_key, size_unit) == ("diagnostic_file", "size_kb", "KB")


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
    assert source.options == [
        "Bundled deterministic sample",
        "Bundled classroom sample",
        "Generate with standalone AI",
    ]
    assert source.value == "bundled"
    assert not any(text_input.label == "AI endpoint" for text_input in at.text_input)

    source.set_value("bundled_classroom").run()

    assert not at.exception
    assert at.selectbox(key="tescia_diagnostic_project:app_args_form:case_source").value == "bundled_classroom"
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
    assert "case_quality_score" in summary_payload
    assert "self_evaluation_status" in summary_payload
    assert "curriculum_ids" in summary_payload
    assert "excellent" in summary_payload
    coverage_path = output_root / "math_program_2026_coverage.json"
    assert coverage_path.is_file()
    coverage_payload = json.loads(coverage_path.read_text(encoding="utf-8"))
    assert coverage_payload["coverage_ratio"] == 1.0
    assert coverage_payload["missing_curriculum_ids"] == []
    assert (output_root / "reduce_summary_worker_0.json").is_file()
    assert (
        output_root
        / "cluster_share_sshfs"
        / "cluster_share_sshfs_diagnostic_report.json"
    ).is_file()
    export_root = env.AGILAB_EXPORT_ABS / env.target / "tescia_diagnostic"
    assert (export_root / "pipeline_dag_stale_preview" / "pipeline_dag_stale_preview_diagnostic_summary.csv").is_file()


def test_tescia_worker_accepts_classroom_submission_batches(monkeypatch, tmp_path) -> None:
    monkeypatch.syspath_prepend(str(APP_SRC))

    from tescia_diagnostic_worker import TesciaDiagnosticWorker

    env = _FakeEnv(tmp_path)
    input_dir = env.share_root_path() / "tescia_diagnostic" / "cases"
    input_dir.mkdir(parents=True, exist_ok=True)
    classroom_file = input_dir / "classroom_submissions.json"
    classroom_file.write_text(SAMPLE_CLASSROOM.read_text(encoding="utf-8"), encoding="utf-8")

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

    df = worker.work_pool(classroom_file)
    assert len(df) == 4
    assert set(df["exercise_id"]) >= {"cluster_share_sshfs", "pipeline_dag_stale_preview"}
    assert all(str(value).startswith("student_") for value in df["student_ref"])

    worker.work_done(df)

    output_root = Path(worker.data_out)
    classroom_root = output_root / "classroom"
    assert (classroom_root / "classroom_run_report.json").is_file()
    assert (classroom_root / "classroom_progress.csv").is_file()
    assert (classroom_root / "classroom_heatmap.csv").is_file()
    report = json.loads((classroom_root / "classroom_run_report.json").read_text(encoding="utf-8"))
    assert report["submission_count"] == 4
    assert report["needs_attention_count"] == 1
    export_root = env.AGILAB_EXPORT_ABS / env.target / "tescia_diagnostic" / "classroom"
    assert (export_root / "classroom_needs_attention.csv").is_file()
    assert (export_root / "classroom_teacher_summary.md").is_file()


def test_tescia_worker_helper_and_empty_paths(monkeypatch, tmp_path) -> None:
    monkeypatch.syspath_prepend(str(APP_SRC))

    import pandas as pd
    from tescia_diagnostic_worker.tescia_diagnostic_worker import TesciaDiagnosticWorker, _artifact_dir, _sanitize_slug

    env_without_export = SimpleNamespace(
        target="target",
        resolve_share_path=lambda value: tmp_path / "share" / value,
    )
    assert _artifact_dir(env_without_export, "leaf") == tmp_path / "share" / "target" / "leaf"
    assert _artifact_dir(SimpleNamespace(target=""), "leaf").parts[-2:] == ("export", "leaf")
    assert _sanitize_slug("  ") == "tescia_case"

    worker = TesciaDiagnosticWorker()
    worker.args = {"data_in": tmp_path / "in", "data_out": tmp_path / "out", "reset_target": False}
    worker.env = _FakeEnv(tmp_path)
    worker._worker_id = 0
    worker.start()
    assert worker._current_args().data_in == tmp_path / "in"
    worker.pool_init({"args": {"minimum_evidence_confidence": 0.1}})
    assert worker._current_args().minimum_evidence_confidence == 0.1
    assert worker.work_init() is None
    assert worker.work_done(None) is None
    assert worker.work_done(pd.DataFrame()) is None


def test_tescia_worker_rejects_invalid_json_and_classroom_batches(monkeypatch, tmp_path) -> None:
    monkeypatch.syspath_prepend(str(APP_SRC))

    from tescia_diagnostic_worker import TesciaDiagnosticWorker

    worker = TesciaDiagnosticWorker()
    non_object = tmp_path / "non_object.json"
    non_object.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="must contain a JSON object"):
        worker._load_cases(non_object)

    classroom = _load_classroom_payload()
    classroom["submissions"][0]["case_id"] = "missing_case"
    bad_classroom = tmp_path / "bad_classroom.json"
    bad_classroom.write_text(json.dumps(classroom), encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid TeSciA classroom submission file"):
        worker._load_cases(bad_classroom)


def test_tescia_app_surface_prefers_latest_classroom_run_artifact(monkeypatch, tmp_path) -> None:
    monkeypatch.syspath_prepend(str(APP_SRC))
    module = _load_app_surface_module()

    cases = module.load_cases()
    sample_report = module.classroom_preview_report(cases)
    old_root = tmp_path / "old" / "classroom"
    new_root = tmp_path / "new" / "classroom"
    old_root.mkdir(parents=True)
    new_root.mkdir(parents=True)
    old_report = {**sample_report, "submission_count": 1}
    new_report = {**sample_report, "submission_count": 9}
    (old_root / "classroom_run_report.json").write_text(json.dumps(old_report), encoding="utf-8")
    new_path = new_root / "classroom_run_report.json"
    new_path.write_text(json.dumps(new_report), encoding="utf-8")
    old_time = 1_700_000_000
    new_time = 1_700_000_100
    import os

    os.utime(old_root / "classroom_run_report.json", (old_time, old_time))
    os.utime(new_path, (new_time, new_time))

    latest = module.latest_classroom_report_path([old_root, new_root])
    assert latest == new_path
    report, source = module.classroom_display_report(
        cases,
        active_app=None,
        env=SimpleNamespace(AGILAB_EXPORT_ABS=tmp_path / "export", target="demo", app="demo"),
        args_model=SimpleNamespace(data_out=tmp_path / "new"),
    )
    assert source["source"] == "last_run"
    assert source["path"] == str(new_path)
    assert report["submission_count"] == 9
    loaded = module.cached_load_classroom_run_report(str(new_path), module._file_mtime_ns(new_path))
    assert loaded["submission_count"] == 9


def test_tescia_app_surface_resolves_active_app_from_argv(monkeypatch, tmp_path) -> None:
    monkeypatch.syspath_prepend(str(APP_SRC))
    module = _load_app_surface_module()
    app_path = tmp_path / "tescia_diagnostic_project"
    app_path.mkdir()

    monkeypatch.setattr(sys, "argv", ["app_surface.py", "--active-app", str(app_path)])
    assert module._resolve_active_app_path() == app_path.resolve()
    monkeypatch.setattr(sys, "argv", ["app_surface.py", f"--active-app={app_path}"])
    assert module._resolve_active_app_path() == app_path.resolve()


def test_tescia_worker_rejects_invalid_case_file(monkeypatch, tmp_path) -> None:
    monkeypatch.syspath_prepend(str(APP_SRC))

    from tescia_diagnostic_worker import TesciaDiagnosticWorker

    payload = json.loads(SAMPLE_CASES.read_text(encoding="utf-8"))
    payload["cases"][0]["candidate_fixes"][0]["expected_impact"] = 1.5
    case_file = tmp_path / "bad_cases.json"
    case_file.write_text(json.dumps(payload), encoding="utf-8")

    worker = TesciaDiagnosticWorker()

    with pytest.raises(ValueError, match="Invalid TeSciA diagnostic file.*between 0.0 and 1.0"):
        worker._load_cases(case_file)
