"""Student-facing TeSciA analysis surface."""

from __future__ import annotations

import json
import runpy
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

_APP_SRC = Path(__file__).resolve().parents[1]
if str(_APP_SRC) not in sys.path:
    sys.path.insert(0, str(_APP_SRC))

from tescia_diagnostic.curriculum import build_math_program_2026_coverage_report
from tescia_diagnostic.classroom import (
    CLASSROOM_RUN_REPORT_SCHEMA,
    classroom_report_to_markdown,
    default_classroom_payload_path,
    expand_classroom_submissions,
    load_classroom_payload,
    merge_classroom_run_reports,
    score_classroom_submissions,
    validate_classroom_payload,
)
from tescia_diagnostic.diagnostic import diagnose_case, validate_case_payload
from tescia_diagnostic.exports import diagnostic_report_to_markdown


def _cache_data(func):
    try:
        import streamlit as st
    except Exception:
        return func
    try:
        return st.cache_data(show_spinner=False)(func)
    except Exception:
        return func


def bundled_cases_path() -> Path:
    return Path(__file__).resolve().parent / "sample_data" / "tescia_diagnostic_cases.json"


def bundled_classroom_payload_path() -> Path:
    return default_classroom_payload_path()


def load_case_payload(path: str | Path | None = None) -> dict[str, Any]:
    source = Path(path) if path is not None else bundled_cases_path()
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"TeSciA cases must be a JSON object: {source}")
    return validate_case_payload(payload)


def load_cases(path: str | Path | None = None) -> list[dict[str, Any]]:
    return list(load_case_payload(path)["cases"])


def _file_mtime_ns(path: str | Path | None) -> int:
    if path is None:
        return 0
    try:
        return Path(path).stat().st_mtime_ns
    except OSError:
        return 0


@_cache_data
def cached_load_cases(path: str = "", mtime_ns: int = 0) -> list[dict[str, Any]]:
    _ = mtime_ns
    return load_cases(path or None)


@_cache_data
def cached_classroom_preview_report(case_bank_path: str = "", case_bank_mtime_ns: int = 0) -> dict[str, Any]:
    _ = case_bank_mtime_ns
    return score_classroom_submissions(load_classroom_preview_payload(), case_bank=load_cases(case_bank_path or None))


def load_classroom_preview_payload(path: str | Path | None = None) -> dict[str, Any]:
    return load_classroom_payload(path or bundled_classroom_payload_path())


def classroom_preview_report(cases: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    case_bank = [dict(case) for case in cases] if cases is not None else load_cases()
    return score_classroom_submissions(load_classroom_preview_payload(), case_bank=case_bank)


def _resolve_active_app_path(active_app: Path | None = None) -> Path | None:
    if active_app is not None:
        candidate = Path(active_app).expanduser()
        return candidate.resolve() if candidate.exists() else None

    for index, arg in enumerate(sys.argv):
        if arg == "--active-app" and index + 1 < len(sys.argv):
            candidate = Path(sys.argv[index + 1]).expanduser()
            return candidate.resolve() if candidate.exists() else None
        if arg.startswith("--active-app="):
            candidate = Path(arg.split("=", 1)[1]).expanduser()
            return candidate.resolve() if candidate.exists() else None
    return None


def _load_runtime_env_and_args(active_app_path: Path):
    from agi_env import AgiEnv
    from tescia_diagnostic import app_args

    env = AgiEnv(apps_path=active_app_path.parent, app=active_app_path.name, verbose=0)
    args_model = app_args.ensure_defaults(app_args.load_args(env.app_settings_file), env=env)
    return env, args_model


def _runtime_context(active_app_path: Path | None) -> tuple[Any | None, Any | None]:
    if active_app_path is None:
        return None, None
    try:
        return _load_runtime_env_and_args(active_app_path)
    except Exception:
        return None, None


def _append_unique_path(paths: list[Path], path: Path) -> None:
    try:
        resolved = path.expanduser().resolve()
    except (OSError, RuntimeError, TypeError, ValueError):
        resolved = path.expanduser()
    if resolved not in paths:
        paths.append(resolved)


def classroom_artifact_dirs(
    active_app: Path | None = None,
    *,
    env: Any | None = None,
    args_model: Any | None = None,
) -> list[Path]:
    active_app_path = _resolve_active_app_path(active_app)
    paths: list[Path] = []
    runtime_env = env
    runtime_args = args_model
    if active_app_path is not None and (runtime_env is None or runtime_args is None):
        try:
            runtime_env, runtime_args = _load_runtime_env_and_args(active_app_path)
        except Exception:
            runtime_env = env
            runtime_args = args_model

    if runtime_env is not None:
        export_root = Path(getattr(runtime_env, "AGILAB_EXPORT_ABS", Path.home() / "export"))
        for target in (
            str(getattr(runtime_env, "target", "") or ""),
            str(getattr(runtime_env, "app", "") or ""),
            active_app_path.name if active_app_path is not None else "",
        ):
            if target:
                _append_unique_path(paths, export_root / target / "tescia_diagnostic" / "classroom")

        data_out = Path(str(getattr(runtime_args, "data_out", "tescia_diagnostic/reports")))
        if not data_out.is_absolute():
            resolve_share_path = getattr(runtime_env, "resolve_share_path", None)
            if callable(resolve_share_path):
                data_out = Path(resolve_share_path(data_out))
        _append_unique_path(paths, data_out / "classroom")

    if active_app_path is not None:
        for target in (active_app_path.name, active_app_path.name.removesuffix("_project"), "tescia_diagnostic"):
            _append_unique_path(paths, Path.home() / "export" / target / "tescia_diagnostic" / "classroom")
        _append_unique_path(paths, active_app_path / "tescia_diagnostic" / "reports" / "classroom")
    return paths


def latest_classroom_report_path(paths: Sequence[Path]) -> Path | None:
    candidates = [
        path / "classroom_run_report.json"
        for path in paths
        if (path / "classroom_run_report.json").is_file()
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime_ns)


def latest_classroom_partial_report_paths(paths: Sequence[Path]) -> list[Path]:
    candidates: list[Path] = []
    for path in paths:
        partial_root = path / "partials"
        if not partial_root.is_dir():
            continue
        candidates.extend(sorted(partial_root.glob("classroom_partial_worker_*.json")))
    return sorted(candidates, key=lambda path: (path.stat().st_mtime_ns, str(path)))


def _load_classroom_run_report_payload(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"Classroom run report must be a JSON object: {path}")
    if payload.get("schema") != CLASSROOM_RUN_REPORT_SCHEMA:
        raise ValueError(f"Unexpected classroom run report schema: {path}")
    return dict(payload)


@_cache_data
def cached_load_classroom_run_report(path: str, mtime_ns: int) -> dict[str, Any]:
    _ = mtime_ns
    return _load_classroom_run_report_payload(path)


def classroom_display_report(
    cases: Sequence[Mapping[str, Any]] | None = None,
    *,
    active_app: Path | None = None,
    env: Any | None = None,
    args_model: Any | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    artifact_dirs = classroom_artifact_dirs(active_app, env=env, args_model=args_model)
    report_path = latest_classroom_report_path(artifact_dirs)
    if report_path is not None:
        return (
            cached_load_classroom_run_report(str(report_path), _file_mtime_ns(report_path)),
            {"source": "last_run", "path": str(report_path)},
        )
    partial_paths = latest_classroom_partial_report_paths(artifact_dirs)
    if partial_paths:
        partial_reports: list[dict[str, Any]] = []
        seen_partials: set[tuple[str, str]] = set()
        for path in partial_paths:
            partial_report = _load_classroom_run_report_payload(path)
            partial_meta = partial_report.get("partial")
            if isinstance(partial_meta, Mapping):
                partial_key = (
                    str(partial_meta.get("worker_id", "")),
                    str(partial_meta.get("source_file", "")),
                )
            else:
                partial_key = (str(path), "")
            if partial_key in seen_partials:
                continue
            seen_partials.add(partial_key)
            partial_reports.append(partial_report)
        return (
            merge_classroom_run_reports(partial_reports),
            {
                "source": "partial",
                "path": str(partial_paths[-1]),
                "partial_count": len(partial_reports),
            },
        )
    if cases is None:
        report = cached_classroom_preview_report(str(bundled_cases_path()), _file_mtime_ns(bundled_cases_path()))
    else:
        report = classroom_preview_report(cases)
    return report, {"source": "sample", "path": str(bundled_classroom_payload_path())}


def classroom_submission_inbox_dir(
    active_app: Path | None = None,
    *,
    env: Any | None = None,
    args_model: Any | None = None,
) -> Path | None:
    active_app_path = _resolve_active_app_path(active_app)
    runtime_env = env
    runtime_args = args_model
    if active_app_path is not None and (runtime_env is None or runtime_args is None):
        runtime_env, runtime_args = _runtime_context(active_app_path)
    if runtime_env is None or runtime_args is None:
        return None
    inbox = Path(str(getattr(runtime_args, "submission_inbox", "tescia_diagnostic/submissions")))
    if inbox.is_absolute():
        return inbox
    resolve_share_path = getattr(runtime_env, "resolve_share_path", None)
    if callable(resolve_share_path):
        return Path(resolve_share_path(inbox))
    return Path(inbox).expanduser().resolve()


def _upload_bytes(upload: Any) -> bytes:
    getvalue = getattr(upload, "getvalue", None)
    if callable(getvalue):
        data = getvalue()
    else:
        read = getattr(upload, "read", None)
        data = read() if callable(read) else b""
    if isinstance(data, str):
        return data.encode("utf-8")
    return bytes(data or b"")


def _safe_upload_stem(name: str) -> str:
    raw_stem = Path(name or "classroom_submissions").stem
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in raw_stem.strip())
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    return cleaned or "classroom_submissions"


def save_classroom_uploads(uploaded_files: Sequence[Any], inbox_dir: Path) -> list[Path]:
    inbox_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    for upload in uploaded_files:
        raw = _upload_bytes(upload)
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError("Classroom upload must be a JSON object.")
        validated = validate_classroom_payload(payload)
        name = str(getattr(upload, "name", "") or "classroom_submissions.json")
        destination = inbox_dir / f"{_safe_upload_stem(name)}.json"
        destination.write_text(json.dumps(validated, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        saved.append(destination)
    return saved


def classroom_progress_rows(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = report.get("progress_rows")
    return [dict(row) for row in rows] if isinstance(rows, list) else []


def classroom_heatmap_rows(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = report.get("heatmap_rows")
    return [dict(row) for row in rows] if isinstance(rows, list) else []


def classroom_intervention_rows(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = report.get("intervention_rows")
    return [dict(row) for row in rows] if isinstance(rows, list) else []


def classroom_submission_template(cases: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    case_bank = [dict(case) for case in cases] if cases is not None else load_cases()
    submissions = load_classroom_preview_payload()
    return {
        "schema": submissions["schema"],
        "classroom": submissions["classroom"],
        "submissions": submissions["submissions"],
        "submission_count": len(expand_classroom_submissions(submissions, case_bank=case_bank)),
    }


def catalog_rows(cases: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in cases:
        report = diagnose_case(case)
        catalog = report.get("catalog", {})
        if not isinstance(catalog, Mapping):
            catalog = {}
        curriculum_ids = catalog.get("curriculum_ids", [])
        if not isinstance(curriculum_ids, list):
            curriculum_ids = []
        rows.append(
            {
                "case_id": str(case.get("case_id", "")),
                "title": str(catalog.get("title", "")),
                "difficulty": str(catalog.get("difficulty", "")),
                "learner_level": str(catalog.get("learner_level", "")),
                "estimated_minutes": int(catalog.get("estimated_minutes", 0) or 0),
                "curriculum_count": len(curriculum_ids),
                "curriculum_ids": ", ".join(str(item) for item in curriculum_ids),
                "score": float(report.get("student_score", 0.0)),
            }
        )
    return rows


def available_filters(cases: Sequence[Mapping[str, Any]]) -> dict[str, list[str]]:
    rows = catalog_rows(cases)
    return {
        "difficulty": sorted({row["difficulty"] for row in rows if row["difficulty"]}),
        "learner_level": sorted({row["learner_level"] for row in rows if row["learner_level"]}),
        "curriculum_id": sorted(
            {
                item.strip()
                for row in rows
                for item in str(row["curriculum_ids"]).split(",")
                if item.strip()
            }
        ),
    }


def filter_cases(
    cases: Sequence[Mapping[str, Any]],
    *,
    difficulty: str = "",
    learner_level: str = "",
    curriculum_id: str = "",
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for case in cases:
        report = diagnose_case(case)
        catalog = report.get("catalog", {})
        if not isinstance(catalog, Mapping):
            continue
        curriculum_ids = catalog.get("curriculum_ids", [])
        if not isinstance(curriculum_ids, list):
            curriculum_ids = []
        if difficulty and catalog.get("difficulty") != difficulty:
            continue
        if learner_level and catalog.get("learner_level") != learner_level:
            continue
        if curriculum_id and curriculum_id not in curriculum_ids:
            continue
        filtered.append(dict(case))
    return filtered


def build_student_answer(
    *,
    diagnosis: str,
    root_cause: str,
    evidence_ids: str | Sequence[str],
    selected_fix_id: str,
    regression_test_ids: str | Sequence[str],
    confidence: float,
) -> dict[str, Any]:
    def _ids(value: str | Sequence[str]) -> list[str]:
        if isinstance(value, str):
            parts = value.replace("\n", ",").split(",")
        else:
            parts = [str(item) for item in value]
        return [part.strip() for part in parts if part.strip()]

    return {
        "diagnosis": diagnosis.strip(),
        "root_cause": root_cause.strip(),
        "evidence_ids": _ids(evidence_ids),
        "selected_fix_id": selected_fix_id.strip(),
        "regression_test_ids": _ids(regression_test_ids),
        "confidence": float(confidence),
    }


def score_student_submission(case: Mapping[str, Any], answer: Mapping[str, Any]) -> dict[str, Any]:
    payload = {"schema": "agilab.tescia_diagnostic.cases.v1", "cases": [{**dict(case), "student_answer": dict(answer)}]}
    validated = validate_case_payload(payload)["cases"][0]
    return diagnose_case(validated)


def build_teacher_draft(
    *,
    case_id: str,
    title: str,
    curriculum_ids: Sequence[str],
    prompt: str,
    root_cause: str,
    selected_fix_id: str,
) -> dict[str, Any]:
    clean_case_id = case_id.strip()
    if not clean_case_id:
        raise ValueError("case_id is required")
    clean_curriculum_ids = [item.strip() for item in curriculum_ids if item.strip()]
    if not clean_curriculum_ids:
        raise ValueError("At least one curriculum id is required")
    return {
        "case_id": clean_case_id,
        "title": title.strip() or clean_case_id,
        "difficulty": "intermediate",
        "topic_tags": ["math-2026", "teacher-draft"],
        "curriculum_ids": clean_curriculum_ids,
        "estimated_minutes": 25,
        "learner_level": "student",
        "student_prompt": prompt.strip(),
        "symptom": prompt.strip(),
        "proposed_diagnosis": "Draft diagnosis to challenge.",
        "root_cause": root_cause.strip(),
        "plain_repro": "Compare the student answer with the teacher draft rubric.",
        "weak_assumptions": ["The exercise is complete without checking the rubric."],
        "evidence": [
            {"id": "rubric_match", "description": "The answer matches the rubric.", "confidence": 0.9, "relevance": 0.9},
            {"id": "curriculum_alignment", "description": "The exercise maps to declared curriculum ids.", "confidence": 0.9, "relevance": 0.9},
        ],
        "candidate_fixes": [
            {
                "id": selected_fix_id.strip() or "complete_rubric_answer",
                "summary": "Use the reference rubric and declared curriculum coverage.",
                "expected_impact": 0.9,
                "blast_radius": 0.2,
                "reversibility": 0.8,
            },
            {
                "id": "accept_unchecked_answer",
                "summary": "Accept the answer without curriculum or rubric checks.",
                "expected_impact": 0.3,
                "blast_radius": 0.6,
                "reversibility": 0.7,
            },
        ],
        "regression_tests": [
            {"id": "rubric_ids_valid", "description": "Validate rubric ids.", "automated": True, "discriminator": True},
            {
                "id": "curriculum_ids_valid",
                "description": "Validate curriculum ids against the 2026 contract.",
                "automated": True,
                "discriminator": True,
            },
        ],
    }


def _select_options(values: Sequence[str]) -> list[str]:
    return [""] + list(values)


def _safe_page_config() -> None:
    import streamlit as st

    try:
        st.set_page_config(page_title="TeSciA", layout="wide")
    except Exception:
        pass


def _render_configure_surface() -> None:
    runpy.run_path(str(_APP_SRC / "app_args_form.py"), run_name="__main__")


def render(*, mode: str = "analysis", active_app: Path | None = None, **_kwargs: Any) -> None:
    surface_mode = str(mode or "analysis").lower()
    if surface_mode == "configure":
        _render_configure_surface()
        return
    if surface_mode not in {"analysis", "full"}:
        raise ValueError(f"Unsupported TeSciA app surface mode: {mode}")

    import streamlit as st

    if surface_mode == "full":
        _safe_page_config()
    st.title("TeSciA")

    active_app_path = _resolve_active_app_path(active_app)
    runtime_env, runtime_args = _runtime_context(active_app_path)
    cases = cached_load_cases(str(bundled_cases_path()), _file_mtime_ns(bundled_cases_path()))
    coverage = build_math_program_2026_coverage_report(cases)
    filters = available_filters(cases)

    classroom_report, classroom_source = classroom_display_report(
        cases,
        active_app=active_app_path,
        env=runtime_env,
        args_model=runtime_args,
    )
    classroom_inbox_dir = classroom_submission_inbox_dir(
        active_app_path,
        env=runtime_env,
        args_model=runtime_args,
    )

    catalog_tab, answer_tab, classroom_tab, authoring_tab, coverage_tab = st.tabs(
        ["Catalog", "Self-evaluation", "Classroom live", "Teacher authoring", "Coverage"]
    )

    with catalog_tab:
        c1, c2, c3 = st.columns([1, 1, 2])
        difficulty = c1.selectbox("Difficulty", _select_options(filters["difficulty"]), key="tescia_catalog_difficulty")
        learner_level = c2.selectbox("Level", _select_options(filters["learner_level"]), key="tescia_catalog_level")
        curriculum_id = c3.selectbox("Curriculum id", _select_options(filters["curriculum_id"]), key="tescia_catalog_curriculum")
        filtered = filter_cases(
            cases,
            difficulty=difficulty,
            learner_level=learner_level,
            curriculum_id=curriculum_id,
        )
        st.dataframe(catalog_rows(filtered), use_container_width=True, hide_index=True)

    with answer_tab:
        case_ids = [str(case["case_id"]) for case in cases]
        selected_id = st.selectbox("Exercise", case_ids, key="tescia_answer_case")
        case = next(case for case in cases if case["case_id"] == selected_id)
        report = diagnose_case(case)
        catalog = report["catalog"]
        st.markdown(f"**{catalog['title']}**")
        st.caption(catalog["student_prompt"])
        answer = build_student_answer(
            diagnosis=st.text_area("Diagnosis", value=str(case.get("student_answer", {}).get("diagnosis", ""))),
            root_cause=st.text_area("Root cause", value=str(case.get("student_answer", {}).get("root_cause", ""))),
            evidence_ids=st.text_input("Evidence ids", value=",".join(case.get("student_answer", {}).get("evidence_ids", []))),
            selected_fix_id=st.text_input("Selected fix id", value=str(case.get("student_answer", {}).get("selected_fix_id", ""))),
            regression_test_ids=st.text_input(
                "Regression test ids",
                value=",".join(case.get("student_answer", {}).get("regression_test_ids", [])),
            ),
            confidence=st.slider("Confidence", 0.0, 1.0, float(case.get("student_answer", {}).get("confidence", 0.75))),
        )
        if st.button("Evaluate answer", type="primary", use_container_width=True):
            try:
                scored = score_student_submission(case, answer)
            except ValueError as exc:
                st.error(str(exc))
            else:
                evaluation = scored["self_evaluation"]
                st.metric("Student score", scored["student_score"])
                st.write(evaluation["feedback"])
                st.download_button(
                    "Download correction sheet",
                    diagnostic_report_to_markdown(scored),
                    file_name=f"{selected_id}_correction.md",
                    mime="text/markdown",
                    use_container_width=True,
                )

    with classroom_tab:
        actions, refresh_options = st.columns([1.2, 2.0])
        with actions:
            if st.button("Refresh classroom artifacts", key="tescia_classroom_refresh", use_container_width=True):
                try:
                    st.cache_data.clear()
                except Exception:
                    pass
                st.rerun()
        with refresh_options:
            live_refresh = st.checkbox("Live refresh", key="tescia_classroom_live_refresh")
            refresh_seconds = st.number_input(
                "Refresh seconds",
                min_value=2,
                max_value=120,
                value=10,
                step=1,
                key="tescia_classroom_refresh_seconds",
                disabled=not live_refresh,
            )
        with st.expander("Submission inbox", expanded=False):
            if classroom_inbox_dir is None:
                st.caption("Open TeSciA from an active project to enable classroom JSON intake.")
            else:
                st.caption(f"RUN reads uploaded classroom batches from `{classroom_inbox_dir}`.")
                uploads = st.file_uploader(
                    "Add classroom batch JSON",
                    type=["json"],
                    accept_multiple_files=True,
                    key="tescia_classroom_uploads",
                )
                if st.button("Save classroom uploads", key="tescia_save_classroom_uploads", use_container_width=True):
                    try:
                        saved_paths = save_classroom_uploads(list(uploads or []), classroom_inbox_dir)
                    except Exception as exc:
                        st.error(f"Unable to save classroom upload: {exc}")
                    else:
                        if saved_paths:
                            st.success(f"Saved {len(saved_paths)} classroom batch file(s). Run AGILAB to score them.")
                        else:
                            st.info("Select at least one classroom JSON file before saving.")

        if classroom_source["source"] == "last_run":
            st.caption(f"Showing latest classroom run artifact: `{classroom_source['path']}`")
        elif classroom_source["source"] == "partial":
            st.caption(
                "Showing partial classroom progress from "
                f"{classroom_source.get('partial_count', 0)} worker artifact(s); "
                f"latest `{classroom_source['path']}`."
            )
        else:
            st.caption("No classroom run artifact found yet; showing the bundled classroom sample preview.")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Submissions", classroom_report["submission_count"])
        m2.metric("Students", classroom_report["unique_student_count"])
        m3.metric("Average score", classroom_report["average_score"])
        m4.metric("Needs attention", classroom_report["needs_attention_count"])
        st.dataframe(classroom_progress_rows(classroom_report), use_container_width=True, hide_index=True)
        st.dataframe(classroom_heatmap_rows(classroom_report), use_container_width=True, hide_index=True)
        st.dataframe(classroom_intervention_rows(classroom_report), use_container_width=True, hide_index=True)
        st.download_button(
            "Download teacher summary",
            classroom_report_to_markdown(classroom_report),
            file_name="classroom_teacher_summary.md",
            mime="text/markdown",
            use_container_width=True,
        )
        st.download_button(
            "Download classroom batch JSON",
            json.dumps(classroom_submission_template(cases), indent=2, sort_keys=True),
            file_name="tescia_classroom_submissions.json",
            mime="application/json",
            use_container_width=True,
        )
        if live_refresh:
            time.sleep(float(refresh_seconds))
            st.rerun()

    with authoring_tab:
        curriculum_options = filters["curriculum_id"]
        selected_curriculum = st.multiselect("Curriculum ids", curriculum_options, key="tescia_author_curriculum")
        try:
            draft = build_teacher_draft(
                case_id=st.text_input("Case id", key="tescia_author_case_id"),
                title=st.text_input("Title", key="tescia_author_title"),
                curriculum_ids=selected_curriculum,
                prompt=st.text_area("Student prompt", key="tescia_author_prompt"),
                root_cause=st.text_area("Reference root cause", key="tescia_author_root_cause"),
                selected_fix_id=st.text_input("Reference fix id", key="tescia_author_fix"),
            )
        except ValueError as exc:
            st.info(str(exc))
        else:
            st.code(json.dumps(draft, indent=2, sort_keys=True), language="json")

    with coverage_tab:
        st.metric("Coverage ratio", coverage["coverage_ratio"])
        st.metric("Required ids", coverage["required_count"])
        st.metric("Minimum exercises per id", coverage["required_min_cases_per_id"])
        if coverage["quality_passed"]:
            st.success("2026 mathematics coverage quality threshold passed.")
        else:
            st.warning("2026 mathematics coverage needs more exercises.")
        st.dataframe(
            [
                {"curriculum_id": key, "exercise_count": value}
                for key, value in coverage["curriculum_id_counts"].items()
            ],
            use_container_width=True,
            hide_index=True,
        )


def main() -> None:
    render(mode="full")


if __name__ == "__main__":
    main()
