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
    if package_paths is not None and package_path not in list(package_paths):
        try:
            package_paths.append(package_path)
        except AttributeError:
            package.__path__ = [*package_paths, package_path]


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
            and summary.get("aligned_core_versions") is True
            and summary.get("pinned_core_dependency_count", 0) >= 1,
            "bundled AGI core package versions align with the root package",
            evidence=[row.get("path", "") for row in state.get("core_components", [])],
            details={
                "core_versions": summary.get("core_versions", {}),
                "pinned_core_dependencies": summary.get("pinned_core_dependencies", []),
            },
        ),
        _check_result(
            "supply_chain_attestation_page_lib_alignment",
            "Supply-chain attestation page library alignment",
            summary.get("page_lib_component_count") == 1
            and summary.get("aligned_page_lib_versions") is True
            and summary.get("pinned_page_lib_dependency_count", 0) >= 1,
            "published AGILAB page libraries align with the root package",
            evidence=[row.get("path", "") for row in state.get("page_lib_components", [])],
            details={
                "page_lib_versions": summary.get("page_lib_versions", {}),
                "pinned_page_lib_dependencies": summary.get("pinned_page_lib_dependencies", []),
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
            "versions, and built-in app manifests without formal attestation claims."
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
            "lockfile_present": summary.get("lockfile_present"),
            "license_present": summary.get("license_present"),
            "core_component_count": summary.get("core_component_count"),
            "aligned_core_versions": summary.get("aligned_core_versions"),
            "page_lib_component_count": summary.get("page_lib_component_count"),
            "aligned_page_lib_versions": summary.get("aligned_page_lib_versions"),
            "builtin_app_pyproject_count": summary.get("builtin_app_pyproject_count"),
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
