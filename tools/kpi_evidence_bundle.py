#!/usr/bin/env python3
"""Emit cross-KPI public evidence for AGILAB review/adoption scoring."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from decimal import Decimal, ROUND_HALF_UP
import importlib.util
import json
from pathlib import Path
import re
import sys
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_REVIEW_SCORE = "3.2 / 5"
KPI_COMPONENT_SCORES = {
    "Ease of adoption": Decimal("3.5"),
    "Research experimentation": Decimal("4.0"),
    "Engineering prototyping": Decimal("4.0"),
    "Production readiness": Decimal("3.0"),
}
OVERALL_SCORE_RAW = sum(KPI_COMPONENT_SCORES.values(), Decimal("0")) / Decimal(len(KPI_COMPONENT_SCORES))
SUPPORTED_OVERALL_SCORE = f"{OVERALL_SCORE_RAW.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)} / 5"
TEMPLATE_ONLY_BUILTIN_APPS = {
    "mycode_project": "starter template with placeholder worker hooks and no concrete merge output",
}


def _load_tool_module(repo_root: Path, name: str) -> Any:
    module_path = repo_root / "tools" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"{name}_for_kpi_bundle", module_path)
    if not spec or not spec.loader:
        raise RuntimeError(f"unable to load tool module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _check_result(
    check_id: str,
    label: str,
    passed: bool,
    summary: str,
    *,
    evidence: Sequence[str] = (),
    details: dict[str, Any] | None = None,
    executed: bool = False,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "label": label,
        "status": "pass" if passed else "fail",
        "summary": summary,
        "executed": executed,
        "evidence": list(evidence),
        "details": details or {},
    }


def _check_workflow_compatibility_report(repo_root: Path) -> dict[str, Any]:
    try:
        compatibility_report = _load_tool_module(repo_root, "compatibility_report")
        report = compatibility_report.build_report(repo_root=repo_root)
        check_ids = [check.get("id") for check in report.get("checks", [])]
        status_check = next(
            (
                check
                for check in report.get("checks", [])
                if check.get("id") == "required_public_statuses"
            ),
            {},
        )
        ok = report.get("status") == "pass" and "workflow_evidence_commands" in check_ids
        details = {
            "status": report.get("status"),
            "summary": report.get("summary"),
            "check_ids": check_ids,
            "required_public_statuses": status_check.get("details", {}),
        }
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    return _check_result(
        "workflow_compatibility_report",
        "Workflow-backed compatibility report",
        ok,
        (
            "compatibility report validates public path statuses and proof commands"
            if ok
            else "compatibility report is failing or disconnected from the KPI bundle"
        ),
        evidence=[
            "tools/compatibility_report.py",
            "docs/source/data/compatibility_matrix.toml",
        ],
        details=details,
    )


def _check_newcomer_first_proof_contract(repo_root: Path) -> dict[str, Any]:
    try:
        newcomer_first_proof = _load_tool_module(repo_root, "newcomer_first_proof")
        active_app = newcomer_first_proof.DEFAULT_ACTIVE_APP
        commands = newcomer_first_proof.build_proof_commands(active_app, with_install=False)
        labels = [command.label for command in commands]
        ok = (
            labels == ["preinit smoke", "source ui smoke"]
            and float(newcomer_first_proof.DEFAULT_MAX_SECONDS) == 600.0
            and active_app.name == "flight_project"
        )
        details = {
            "active_app": str(active_app),
            "labels": labels,
            "target_seconds": newcomer_first_proof.DEFAULT_MAX_SECONDS,
            "command_count": len(commands),
        }
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    return _check_result(
        "newcomer_first_proof_contract",
        "Newcomer first-proof contract",
        ok,
        (
            "source-checkout newcomer proof is executable and targets the public flight_project"
            if ok
            else "source-checkout newcomer proof contract is incomplete"
        ),
        evidence=["tools/newcomer_first_proof.py", "README.md"],
        details=details,
    )


def _check_reduce_contract_benchmark(repo_root: Path) -> dict[str, Any]:
    try:
        reduce_contract_benchmark = _load_tool_module(repo_root, "reduce_contract_benchmark")
        summary = reduce_contract_benchmark.run_benchmark()
        ok = (
            bool(summary.success)
            and bool(summary.within_target)
            and summary.partial_count == reduce_contract_benchmark.DEFAULT_PARTIALS
            and summary.total_items
            == reduce_contract_benchmark.DEFAULT_PARTIALS
            * reduce_contract_benchmark.DEFAULT_ITEMS_PER_PARTIAL
            and summary.artifact["name"] == "public_reduce_benchmark_summary"
        )
        details = asdict(summary)
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    return _check_result(
        "reduce_contract_benchmark",
        "Reduce contract benchmark",
        ok,
        (
            "public reduce-contract benchmark passes within target"
            if ok
            else "public reduce-contract benchmark is failing or incomplete"
        ),
        evidence=["tools/reduce_contract_benchmark.py", "README.md"],
        details=details,
        executed=True,
    )


def _builtin_project_dirs(repo_root: Path) -> list[Path]:
    builtin_root = repo_root / "src" / "agilab" / "apps" / "builtin"
    return sorted(
        path
        for path in builtin_root.glob("*_project")
        if (path / "pyproject.toml").is_file()
    )


def _manager_package_dir(project_dir: Path) -> Path:
    packages = sorted(
        child
        for child in (project_dir / "src").iterdir()
        if child.is_dir()
        and (child / "__init__.py").is_file()
        and not child.name.endswith("_worker")
    )
    if len(packages) != 1:
        raise ValueError(f"{project_dir.name} should expose one manager package")
    return packages[0]


def _reduce_contract_adoption_details(repo_root: Path) -> dict[str, Any]:
    checked_apps: list[str] = []
    failures: list[str] = []

    for project_dir in _builtin_project_dirs(repo_root):
        if project_dir.name in TEMPLATE_ONLY_BUILTIN_APPS:
            continue

        checked_apps.append(project_dir.name)
        try:
            package_dir = _manager_package_dir(project_dir)
            init_path = package_dir / "__init__.py"
            reduction_path = package_dir / "reduction.py"
            if not reduction_path.is_file():
                failures.append(f"{project_dir.name}: missing {reduction_path.relative_to(repo_root)}")
                continue

            init_text = init_path.read_text(encoding="utf-8")
            reduction_text = reduction_path.read_text(encoding="utf-8")
            if "from .reduction import" not in init_text:
                failures.append(f"{project_dir.name}: manager package does not export reduction contract")
            if not re.search(r"\b[A-Z0-9_]+_REDUCE_CONTRACT\b", init_text):
                failures.append(f"{project_dir.name}: no exported *_REDUCE_CONTRACT symbol")
            if "REDUCE_ARTIFACT_FILENAME_TEMPLATE" not in reduction_text:
                failures.append(f"{project_dir.name}: reducer does not declare artifact filename template")
            if "reduce_summary_worker_{worker_id}.json" not in reduction_text:
                failures.append(f"{project_dir.name}: reducer does not use worker-scoped reduce summary name")
            if "write_reduce_artifact" not in reduction_text:
                failures.append(f"{project_dir.name}: reducer does not expose write_reduce_artifact")
        except Exception as exc:
            failures.append(f"{project_dir.name}: {exc}")

    mycode_docs = repo_root / "docs" / "source" / "mycode-project.rst"
    try:
        mycode_text = mycode_docs.read_text(encoding="utf-8")
        normalized_docs = re.sub(r"\s+", " ", mycode_text.lower())
        if "template-only" not in normalized_docs:
            failures.append("mycode_project docs do not mark the project as template-only")
        if "no concrete merge output" not in normalized_docs:
            failures.append("mycode_project docs do not explain the reducer exemption")
        if "reduce_summary_worker_<id>.json" not in mycode_text:
            failures.append("mycode_project docs do not name the reducer artifact contract")
    except Exception as exc:
        failures.append(f"mycode_project docs: {exc}")

    return {
        "checked_apps": checked_apps,
        "checked_app_count": len(checked_apps),
        "template_only_exemptions": TEMPLATE_ONLY_BUILTIN_APPS,
        "failures": failures,
    }


def _check_reduce_contract_adoption_guardrail(repo_root: Path) -> dict[str, Any]:
    try:
        details = _reduce_contract_adoption_details(repo_root)
        ok = not details["failures"] and details["checked_app_count"] > 0
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    return _check_result(
        "reduce_contract_adoption_guardrail",
        "Reduce contract adoption guardrail",
        ok,
        (
            "every non-template built-in app exposes a worker-scoped reducer contract"
            if ok
            else "one or more non-template built-in apps lack reducer contract adoption"
        ),
        evidence=[
            "src/agilab/apps/builtin",
            "test/test_reduce_contract_adoption.py",
            "docs/source/mycode-project.rst",
        ],
        details=details,
    )


def _check_hf_space_smoke_contract(repo_root: Path) -> dict[str, Any]:
    try:
        hf_space_smoke = _load_tool_module(repo_root, "hf_space_smoke")
        specs = hf_space_smoke.route_specs()
        labels = [spec.label for spec in specs]
        required_labels = {
            "streamlit health",
            "base app",
            "flight project",
            "flight view_maps",
            "flight view_maps_network",
        }
        ok = (
            required_labels.issubset(labels)
            and hf_space_smoke.DEFAULT_SPACE_ID == "jpmorard/agilab"
            and callable(hf_space_smoke.check_public_app_tree)
        )
        details = {
            "space_id": hf_space_smoke.DEFAULT_SPACE_ID,
            "space_url": hf_space_smoke.DEFAULT_SPACE_URL,
            "labels": labels,
            "required_labels": sorted(required_labels),
        }
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    return _check_result(
        "hf_space_smoke_contract",
        "Hugging Face Space smoke contract",
        ok,
        (
            "HF smoke covers public routes and guards against non-public app entries"
            if ok
            else "HF smoke contract is incomplete"
        ),
        evidence=["tools/hf_space_smoke.py", "README.md"],
        details=details,
    )


def _check_web_robot_contract(repo_root: Path) -> dict[str, Any]:
    try:
        web_robot = _load_tool_module(repo_root, "agilab_web_robot")
        remote_view = web_robot.resolve_analysis_view_path("view_maps", remote=True)
        analysis_url = web_robot.build_page_url(
            "https://jpmorard-agilab.hf.space",
            "ANALYSIS",
            active_app="flight_project",
            current_page=remote_view,
        )
        ok = (
            web_robot.DEFAULT_TARGET_SECONDS == 120.0
            and "view_maps" in web_robot.ANALYSIS_VIEW_PATHS
            and remote_view == "/app/src/agilab/apps-pages/view_maps/src/view_maps/view_maps.py"
            and "current_page=%2Fapp%2Fsrc%2Fagilab%2Fapps-pages%2Fview_maps" in analysis_url
            and "could not determine the active app" in web_robot.DEFAULT_REJECT_PATTERNS
        )
        details = {
            "target_seconds": web_robot.DEFAULT_TARGET_SECONDS,
            "remote_view": remote_view,
            "analysis_url": analysis_url,
            "route": ["landing", "ORCHESTRATE", "ANALYSIS", "view_maps"],
        }
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    return _check_result(
        "web_ui_robot_contract",
        "Browser-level web UI robot contract",
        ok,
        (
            "Playwright robot covers the real AGILAB web routes and analysis deep link"
            if ok
            else "browser-level web UI robot contract is incomplete"
        ),
        evidence=["tools/agilab_web_robot.py", "README.md"],
        details=details,
    )


def _run_hf_space_smoke(repo_root: Path) -> dict[str, Any]:
    try:
        hf_space_smoke = _load_tool_module(repo_root, "hf_space_smoke")
        summary = hf_space_smoke.run_smoke()
        details = asdict(summary)
        ok = bool(summary.success)
        summary_text = (
            "public HF Space smoke passed"
            if ok
            else "public HF Space smoke failed"
        )
    except Exception as exc:
        ok = False
        summary_text = str(exc)
        details = {"error": str(exc)}
    return _check_result(
        "hf_space_smoke_run",
        "Hugging Face Space smoke run",
        ok,
        summary_text,
        evidence=["tools/hf_space_smoke.py", "https://huggingface.co/spaces/jpmorard/agilab"],
        details=details,
        executed=True,
    )


def _check_production_readiness_report(repo_root: Path) -> dict[str, Any]:
    try:
        production_readiness_report = _load_tool_module(repo_root, "production_readiness_report")
        report = production_readiness_report.build_report(repo_root=repo_root, run_docs_profile=False)
        ok = report.get("status") == "pass" and report.get("supported_score") == "3.0 / 5"
        details = {
            "status": report.get("status"),
            "supported_score": report.get("supported_score"),
            "summary": report.get("summary"),
            "check_ids": [check.get("id") for check in report.get("checks", [])],
        }
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    return _check_result(
        "production_readiness_report_contract",
        "Production-readiness report contract",
        ok,
        (
            "production-readiness evidence report passes and preserves the 3.0 / 5 scope limit"
            if ok
            else "production-readiness evidence report is failing or overclaiming"
        ),
        evidence=["tools/production_readiness_report.py"],
        details=details,
    )


def _check_docs_mirror_stamp(repo_root: Path) -> dict[str, Any]:
    try:
        sync_docs_source = _load_tool_module(repo_root, "sync_docs_source")
        ok, message = sync_docs_source.verify_mirror_stamp(repo_root / "docs" / "source")
    except Exception as exc:
        ok, message = False, str(exc)
    return _check_result(
        "docs_mirror_stamp",
        "Docs mirror stamp",
        ok,
        message,
        evidence=["docs/.docs_source_mirror_stamp.json", "tools/sync_docs_source.py"],
    )


def _check_public_docs_links(repo_root: Path) -> dict[str, Any]:
    paths = [
        repo_root / "README.md",
        repo_root / "docs" / "source" / "compatibility-matrix.rst",
        repo_root / "docs" / "source" / "demos.rst",
        repo_root / "docs" / "source" / "quick-start.rst",
    ]
    required = {
        "README.md": [
            "tools/newcomer_first_proof.py --json",
            "tools/reduce_contract_benchmark.py --json",
            "Overall public evaluation",
            "compatibility matrix",
        ],
        "docs/source/compatibility-matrix.rst": [
            "AGILAB Hugging Face demo",
            "validated",
            "tools/compatibility_report.py",
            "tools/hf_space_smoke.py --json",
            "tools/agilab_web_robot.py",
            "tools/production_readiness_report.py",
            "tools/kpi_evidence_bundle.py",
        ],
        "docs/source/demos.rst": ["https://huggingface.co/spaces/jpmorard/agilab"],
        "docs/source/quick-start.rst": ["tools/newcomer_first_proof.py"],
    }
    missing: dict[str, list[str]] = {}
    try:
        for path in paths:
            rel = str(path.relative_to(repo_root))
            text = _read_text(path)
            missing_for_path = [needle for needle in required[rel] if needle not in text]
            if missing_for_path:
                missing[rel] = missing_for_path
        ok = not missing
        details = {"missing": missing}
    except Exception as exc:
        ok = False
        details = {"error": str(exc), "missing": missing}
    return _check_result(
        "public_docs_evidence_links",
        "Public docs evidence links",
        ok,
        (
            "README and public docs expose the machine-readable evidence reports"
            if ok
            else "README or public docs are missing evidence report references"
        ),
        evidence=[str(path.relative_to(repo_root)) for path in paths],
        details=details,
    )


def _score_formula() -> str:
    terms = " + ".join(f"{score:.1f}" for score in KPI_COMPONENT_SCORES.values())
    return f"({terms}) / {len(KPI_COMPONENT_SCORES)} = {OVERALL_SCORE_RAW}"


def build_bundle(
    *,
    repo_root: Path = REPO_ROOT,
    run_hf_smoke: bool = False,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    checks = [
        _check_workflow_compatibility_report(repo_root),
        _check_newcomer_first_proof_contract(repo_root),
        _check_reduce_contract_adoption_guardrail(repo_root),
        _check_reduce_contract_benchmark(repo_root),
        _check_hf_space_smoke_contract(repo_root),
        _check_web_robot_contract(repo_root),
        _check_production_readiness_report(repo_root),
        _check_docs_mirror_stamp(repo_root),
        _check_public_docs_links(repo_root),
    ]
    if run_hf_smoke:
        checks.append(_run_hf_space_smoke(repo_root))

    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = sum(1 for check in checks if check["status"] == "fail")
    return {
        "kpi": "Overall public evaluation",
        "supported_score": SUPPORTED_OVERALL_SCORE,
        "baseline_review_score": BASELINE_REVIEW_SCORE,
        "status": "pass" if failed == 0 else "fail",
        "summary": {
            "passed": passed,
            "failed": failed,
            "total": len(checks),
            "hf_smoke_executed": run_hf_smoke,
            "score_components": {
                name: f"{score:.1f} / 5"
                for name, score in KPI_COMPONENT_SCORES.items()
            },
            "score_formula": _score_formula(),
            "score_rounding": "one decimal, half up",
        },
        "rationale": (
            "Supports an overall public evaluation of 3.6 / 5 as the one-decimal "
            "mean of the four scored public KPIs: adoption, research "
            "experimentation, engineering prototyping, and bounded "
            "production-readiness evidence. It does not change the alpha status "
            "or claim production MLOps coverage."
        ),
        "checks": checks,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit machine-readable evidence for AGILAB's overall public evaluation KPI."
    )
    parser.add_argument(
        "--run-hf-smoke",
        action="store_true",
        help="Also execute the public Hugging Face Space smoke test. Default only checks the smoke contract.",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Emit compact JSON without indentation.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    bundle = build_bundle(run_hf_smoke=args.run_hf_smoke)
    if args.compact:
        print(json.dumps(bundle, sort_keys=True, separators=(",", ":")))
    else:
        print(json.dumps(bundle, indent=2, sort_keys=True))
    return 0 if bundle["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
