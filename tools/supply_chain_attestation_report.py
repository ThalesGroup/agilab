#!/usr/bin/env python3
"""Emit AGILAB static supply-chain attestation evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DOC_RELATIVE_PATH = Path("docs/source/features.rst")


def _ensure_repo_on_path(repo_root: Path) -> None:
    src_root = repo_root / "src"
    for entry in (str(src_root), str(repo_root)):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    package = sys.modules.get("agilab")
    package_path = str(src_root / "agilab")
    package_paths = getattr(package, "__path__", None)
    if package_paths is not None:
        existing_paths = [str(path) for path in package_paths if str(path) != package_path]
        package.__path__ = [package_path, *existing_paths]
    submodule = sys.modules.get("agilab.supply_chain_attestation")
    local_submodule = (src_root / "agilab/supply_chain_attestation.py").resolve()
    submodule_file = getattr(submodule, "__file__", None)
    if submodule_file and Path(submodule_file).resolve() != local_submodule:
        sys.modules.pop("agilab.supply_chain_attestation", None)


_ensure_repo_on_path(REPO_ROOT)

from agilab.supply_chain_attestation import (  # noqa: E402
    SCHEMA,
    persist_supply_chain_attestation,
)


def _check_result(
    check_id: str,
    label: str,
    passed: bool,
    summary: str,
    *,
    evidence: Sequence[str] = (),
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "label": label,
        "status": "pass" if passed else "fail",
        "summary": summary,
        "evidence": list(evidence),
        "details": details or {},
    }


def _docs_check(repo_root: Path) -> dict[str, Any]:
    required = [
        "supply-chain attestation report",
        "tools/supply_chain_attestation_report.py --compact",
        "agilab.supply_chain_attestation.v1",
        "supply_chain_static_attestation",
        "package payload inventory",
        "budgets without formal",
    ]
    doc_path = repo_root / DOC_RELATIVE_PATH
    try:
        text = doc_path.read_text(encoding="utf-8")
        missing = [needle for needle in required if needle not in text]
        ok = not missing
        details = {"missing": missing}
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    return _check_result(
        "supply_chain_attestation_docs_reference",
        "Supply-chain attestation docs reference",
        ok,
        (
            "features docs expose the supply-chain attestation command"
            if ok
            else "features docs do not expose the supply-chain attestation command"
        ),
        evidence=[str(DOC_RELATIVE_PATH)],
        details=details,
    )


def build_report(
    *,
    repo_root: Path = REPO_ROOT,
    output_path: Path | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    if output_path is None:
        with tempfile.TemporaryDirectory(prefix="agilab-supply-chain-attestation-") as tmp_dir:
            return _build_report_with_path(
                repo_root=repo_root,
                output_path=Path(tmp_dir) / "supply_chain_attestation.json",
            )
    return _build_report_with_path(repo_root=repo_root, output_path=output_path)


def _build_report_with_path(*, repo_root: Path, output_path: Path) -> dict[str, Any]:
    proof = persist_supply_chain_attestation(repo_root=repo_root, output_path=output_path)
    state = proof["state"]
    summary = state.get("summary", {})
    checks = [
        _check_result(
            "supply_chain_attestation_schema",
            "Supply-chain attestation schema",
            proof["ok"]
            and state.get("schema") == SCHEMA
            and state.get("execution_mode") == "supply_chain_static_attestation",
            "supply-chain attestation uses the supported schema",
            evidence=["src/agilab/supply_chain_attestation.py"],
            details={
                "schema": state.get("schema"),
                "run_status": state.get("run_status"),
                "execution_mode": state.get("execution_mode"),
                "issues": state.get("issues", []),
            },
        ),
        _check_result(
            "supply_chain_attestation_package_metadata",
            "Supply-chain attestation package metadata",
            summary.get("package_name") == "agilab"
            and bool(summary.get("package_version"))
            and summary.get("lockfile_present") is True
            and summary.get("license_present") is True,
            "root package metadata, lockfile, and license are fingerprinted",
            evidence=["pyproject.toml", "uv.lock", "LICENSE"],
            details={"summary": summary},
        ),
        _check_result(
            "supply_chain_attestation_core_alignment",
            "Supply-chain attestation core alignment",
            summary.get("core_component_count") == 4
            and summary.get("core_release_graph_aligned") is True
            and summary.get("pinned_core_dependency_count", 0) >= 1,
            "bundled AGI core components are covered by exact bundle pins",
            evidence=[row.get("path", "") for row in state.get("core_components", [])],
            details={
                "core_versions": summary.get("core_versions", {}),
                "aligned_core_versions": summary.get("aligned_core_versions"),
                "core_release_graph_aligned": summary.get("core_release_graph_aligned"),
                "pinned_core_dependencies": summary.get("pinned_core_dependencies", []),
            },
        ),
        _check_result(
            "supply_chain_attestation_page_lib_alignment",
            "Supply-chain attestation page library alignment",
            summary.get("page_lib_component_count") == 2
            and summary.get("page_lib_release_graph_aligned") is True
            and summary.get("pinned_page_lib_dependency_count", 0) >= 1,
            "published AGILAB page libraries are covered by exact bundle pins",
            evidence=[row.get("path", "") for row in state.get("page_lib_components", [])],
            details={
                "page_lib_versions": summary.get("page_lib_versions", {}),
                "aligned_page_lib_versions": summary.get("aligned_page_lib_versions"),
                "page_lib_release_graph_aligned": summary.get("page_lib_release_graph_aligned"),
                "pinned_page_lib_dependencies": summary.get("pinned_page_lib_dependencies", []),
            },
        ),
        _check_result(
            "supply_chain_attestation_app_lib_alignment",
            "Supply-chain attestation app library alignment",
            summary.get("app_lib_component_count") == 1
            and summary.get("app_lib_release_graph_aligned") is True
            and summary.get("pinned_app_lib_dependency_count", 0) >= 1,
            "published AGILAB app libraries are covered by exact bundle pins",
            evidence=[row.get("path", "") for row in state.get("app_lib_components", [])],
            details={
                "app_lib_versions": summary.get("app_lib_versions", {}),
                "aligned_app_lib_versions": summary.get("aligned_app_lib_versions"),
                "app_lib_release_graph_aligned": summary.get("app_lib_release_graph_aligned"),
                "pinned_app_lib_dependencies": summary.get("pinned_app_lib_dependencies", []),
            },
        ),
        _check_result(
            "supply_chain_attestation_internal_dependency_pins",
            "Supply-chain attestation internal dependency pins",
            summary.get("aligned_internal_dependency_pins") is True
            and summary.get("internal_dependency_pin_count", 0) >= 1
            and summary.get("mismatched_internal_dependency_pin_count") == 0,
            "bundle exact dependency pins match the corresponding package versions",
            evidence=["pyproject.toml"]
            + [row.get("path", "") for row in state.get("core_components", [])]
            + [row.get("path", "") for row in state.get("page_lib_components", [])]
            + [row.get("path", "") for row in state.get("app_lib_components", [])],
            details={
                "internal_dependency_pins": summary.get("internal_dependency_pins", []),
                "mismatched_internal_dependency_pins": summary.get(
                    "mismatched_internal_dependency_pins",
                    [],
                ),
            },
        ),
        _check_result(
            "supply_chain_attestation_app_manifests",
            "Supply-chain attestation app manifests",
            summary.get("builtin_app_pyproject_count") == len(state.get("builtin_app_pyprojects", []))
            and all(row.get("sha256") for row in state.get("builtin_app_pyprojects", [])),
            "built-in app pyproject manifests are included in the attestation",
            evidence=["src/agilab/apps/builtin"],
            details={"builtin_app_pyprojects": state.get("builtin_app_pyprojects", [])},
        ),
        _check_result(
            "supply_chain_attestation_builtin_app_alignment",
            "Supply-chain attestation built-in app alignment",
            summary.get("builtin_app_pyproject_count") == len(state.get("builtin_app_pyprojects", []))
            and summary.get("aligned_builtin_app_versions") is True
            and summary.get("mismatched_builtin_app_version_count") == 0
            and summary.get("aligned_builtin_app_internal_dependency_bounds") is True
            and summary.get("mismatched_builtin_app_internal_dependency_bound_count") == 0,
            "built-in app payload versions and runtime dependency lower bounds match their package metadata",
            evidence=["src/agilab/apps/builtin"],
            details={
                "mismatched_builtin_app_versions": summary.get(
                    "mismatched_builtin_app_versions",
                    [],
                ),
                "builtin_app_internal_dependency_bounds": summary.get(
                    "builtin_app_internal_dependency_bounds",
                    [],
                ),
                "mismatched_builtin_app_internal_dependency_bounds": summary.get(
                    "mismatched_builtin_app_internal_dependency_bounds",
                    [],
                ),
            },
        ),
        _check_result(
            "supply_chain_attestation_payload_inventory",
            "Supply-chain attestation payload inventory",
            summary.get("package_data_pattern_count", 0) >= 1
            and summary.get("builtin_payload_file_count", 0) >= 1
            and isinstance(summary.get("builtin_payload_extension_counts"), dict),
            "package-data patterns and built-in app payload files are inventoried",
            evidence=["pyproject.toml", "src/agilab/apps/builtin"],
            details={
                "package_data_pattern_count": summary.get(
                    "package_data_pattern_count",
                    0,
                ),
                "builtin_payload_file_count": summary.get(
                    "builtin_payload_file_count",
                    0,
                ),
                "builtin_payload_bytes": summary.get("builtin_payload_bytes", 0),
                "builtin_payload_extension_counts": summary.get(
                    "builtin_payload_extension_counts",
                    {},
                ),
                "builtin_archive_file_count": summary.get(
                    "builtin_archive_file_count",
                    0,
                ),
                "builtin_notebook_file_count": summary.get(
                    "builtin_notebook_file_count",
                    0,
                ),
                "largest_builtin_payload_files": summary.get(
                    "largest_builtin_payload_files",
                    [],
                ),
            },
        ),
        _check_result(
            "supply_chain_attestation_payload_budget",
            "Supply-chain attestation payload budget",
            summary.get("builtin_payload_within_budget") is True,
            (
                "built-in app package payload stays within the public wheel budget"
                if summary.get("builtin_payload_within_budget") is True
                else "built-in app package payload exceeds the public wheel budget"
            ),
            evidence=["pyproject.toml", "src/agilab/apps/builtin"],
            details={"budget": summary.get("builtin_payload_budget", {})},
        ),
        _check_result(
            "supply_chain_attestation_no_execution",
            "Supply-chain attestation no execution",
            summary.get("command_execution_count") == 0
            and summary.get("network_probe_count") == 0
            and summary.get("formal_supply_chain_attestation") is False,
            "attestation reads local files without commands, network probes, or formal claims",
            evidence=["src/agilab/supply_chain_attestation.py"],
            details={"summary": summary, "provenance": state.get("provenance", {})},
        ),
        _check_result(
            "supply_chain_attestation_persistence",
            "Supply-chain attestation persistence",
            proof["round_trip_ok"] and Path(proof["path"]).is_file(),
            "supply-chain attestation is unchanged after JSON write/read",
            evidence=[proof["path"]],
            details={"path": proof["path"], "round_trip_ok": proof["round_trip_ok"]},
        ),
        _docs_check(repo_root),
    ]
    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = sum(1 for check in checks if check["status"] == "fail")
    return {
        "report": "Supply-chain attestation report",
        "status": "pass" if failed == 0 else "fail",
        "scope": (
            "Fingerprints package metadata, lockfile, license, bundled AGI core "
            "versions, page/app library versions, exact bundle dependency pins, "
            "app payload package versions, built-in app payload versions, runtime "
            "dependency lower bounds, and built-in app manifests plus package "
            "payload inventory without formal attestation claims."
        ),
        "summary": {
            "passed": passed,
            "failed": failed,
            "total": len(checks),
            "schema": state.get("schema"),
            "run_status": state.get("run_status"),
            "execution_mode": state.get("execution_mode"),
            "package_name": summary.get("package_name"),
            "package_version": summary.get("package_version"),
            "dependency_count": summary.get("dependency_count"),
            "pinned_core_dependency_count": summary.get("pinned_core_dependency_count"),
            "aligned_internal_dependency_pins": summary.get(
                "aligned_internal_dependency_pins"
            ),
            "internal_dependency_pin_count": summary.get(
                "internal_dependency_pin_count"
            ),
            "mismatched_internal_dependency_pin_count": summary.get(
                "mismatched_internal_dependency_pin_count"
            ),
            "lockfile_present": summary.get("lockfile_present"),
            "license_present": summary.get("license_present"),
            "core_component_count": summary.get("core_component_count"),
            "aligned_core_versions": summary.get("aligned_core_versions"),
            "core_release_graph_aligned": summary.get("core_release_graph_aligned"),
            "page_lib_component_count": summary.get("page_lib_component_count"),
            "aligned_page_lib_versions": summary.get("aligned_page_lib_versions"),
            "page_lib_release_graph_aligned": summary.get("page_lib_release_graph_aligned"),
            "app_lib_component_count": summary.get("app_lib_component_count"),
            "aligned_app_lib_versions": summary.get("aligned_app_lib_versions"),
            "app_lib_release_graph_aligned": summary.get("app_lib_release_graph_aligned"),
            "app_project_package_component_count": summary.get(
                "app_project_package_component_count"
            ),
            "builtin_app_pyproject_count": summary.get("builtin_app_pyproject_count"),
            "package_data_pattern_count": summary.get("package_data_pattern_count"),
            "builtin_payload_file_count": summary.get("builtin_payload_file_count"),
            "builtin_payload_bytes": summary.get("builtin_payload_bytes"),
            "builtin_payload_budget": summary.get("builtin_payload_budget"),
            "builtin_payload_within_budget": summary.get(
                "builtin_payload_within_budget"
            ),
            "builtin_payload_extension_counts": summary.get(
                "builtin_payload_extension_counts"
            ),
            "builtin_archive_file_count": summary.get("builtin_archive_file_count"),
            "builtin_notebook_file_count": summary.get(
                "builtin_notebook_file_count"
            ),
            "aligned_builtin_app_versions": summary.get(
                "aligned_builtin_app_versions"
            ),
            "mismatched_builtin_app_version_count": summary.get(
                "mismatched_builtin_app_version_count"
            ),
            "builtin_app_internal_dependency_bound_count": summary.get(
                "builtin_app_internal_dependency_bound_count"
            ),
            "aligned_builtin_app_internal_dependency_bounds": summary.get(
                "aligned_builtin_app_internal_dependency_bounds"
            ),
            "mismatched_builtin_app_internal_dependency_bound_count": summary.get(
                "mismatched_builtin_app_internal_dependency_bound_count"
            ),
            "command_execution_count": summary.get("command_execution_count"),
            "network_probe_count": summary.get("network_probe_count"),
            "formal_supply_chain_attestation": summary.get(
                "formal_supply_chain_attestation"
            ),
            "round_trip_ok": proof["round_trip_ok"],
            "path": proof["path"],
        },
        "checks": checks,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit AGILAB static supply-chain attestation evidence."
    )
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--compact", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    report = build_report(output_path=args.output)
    if args.compact:
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
