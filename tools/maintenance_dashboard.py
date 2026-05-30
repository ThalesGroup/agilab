#!/usr/bin/env python3
"""Report AGILAB long-term maintenance signals from local repository evidence."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import tomllib
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "agilab.maintenance_dashboard.v1"
REQUIRED_ADRS = (
    "0001-package-split.rst",
    "0002-evidence-core.rst",
    "0003-notebook-bridge.rst",
    "0004-extension-contracts.rst",
    "0005-shared-core-boundary.rst",
)
REQUIRED_EXTENSION_TYPES = (
    "app",
    "page_bundle",
    "notebook_bridge",
    "proof_evidence",
    "connector",
    "shared_core",
)
MATURITY_LABELS = (
    "Live product path",
    "Local proof",
    "Contract proof",
    "Operator-triggered live check",
    "Roadmap boundary",
)


@dataclass(frozen=True)
class Check:
    id: str
    label: str
    status: str
    summary: str
    evidence: tuple[str, ...] = ()
    details: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "status": self.status,
            "summary": self.summary,
            "evidence": list(self.evidence),
            "details": self.details or {},
        }


def _check(
    check_id: str,
    label: str,
    passed: bool,
    summary: str,
    *,
    status: str | None = None,
    evidence: Sequence[str] = (),
    details: dict[str, Any] | None = None,
) -> Check:
    return Check(
        id=check_id,
        label=label,
        status=status or ("pass" if passed else "fail"),
        summary=summary,
        evidence=tuple(evidence),
        details=details or {},
    )


def _load_tool(repo_root: Path, relative_path: str, module_name: str):
    module_path = repo_root / relative_path
    for import_root in (repo_root / "tools", repo_root):
        import_root_str = str(import_root)
        if import_root_str not in sys.path:
            sys.path.insert(0, import_root_str)
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _existing(paths: Sequence[Path]) -> list[str]:
    return [path.as_posix() for path in paths if path.exists()]


def check_extension_contract_kit(repo_root: Path) -> Check:
    contract_path = repo_root / "docs/source/data/extension_contracts.toml"
    docs_path = repo_root / "docs/source/extension-contracts.rst"
    missing = [path.as_posix() for path in (contract_path, docs_path) if not path.is_file()]
    type_ids: list[str] = []
    malformed: list[str] = []
    if not missing:
        payload = tomllib.loads(_read(contract_path))
        if payload.get("schema") != "agilab.extension_contracts.v1":
            malformed.append("schema")
        for item in payload.get("extension_types", []):
            type_id = str(item.get("id", ""))
            type_ids.append(type_id)
            for key in ("description", "required_metadata", "required_evidence", "guardrails"):
                if not item.get(key):
                    malformed.append(f"{type_id}:{key}")
        docs = _read(docs_path)
        capability_map = _read(repo_root / "docs/source/capability-map.rst")
        if ":doc:`capability-map`" not in docs:
            malformed.append("docs:capability-map-reference")
        for label in MATURITY_LABELS:
            if label not in capability_map:
                malformed.append(f"capability-map:{label}")
    missing_types = [item for item in REQUIRED_EXTENSION_TYPES if item not in set(type_ids)]
    ok = not missing and not missing_types and not malformed
    return _check(
        "extension_contract_kit",
        "Extension contract kit",
        ok,
        "extension types declare metadata, evidence, maturity, and guardrails",
        evidence=_existing((contract_path, docs_path)),
        details={
            "missing_files": missing,
            "type_ids": type_ids,
            "missing_types": missing_types,
            "malformed": malformed,
        },
    )


def check_adrs(repo_root: Path) -> Check:
    adr_root = repo_root / "docs/source/adr"
    index = adr_root / "index.rst"
    missing = [item for item in REQUIRED_ADRS if not (adr_root / item).is_file()]
    malformed: list[str] = []
    if not index.is_file():
        malformed.append("index.rst")
    else:
        index_text = _read(index)
        for item in REQUIRED_ADRS:
            if item.removesuffix(".rst") not in index_text:
                malformed.append(f"index:{item}")
    for item in REQUIRED_ADRS:
        path = adr_root / item
        if not path.is_file():
            continue
        text = _read(path)
        for heading in ("Status", "Decision", "Consequences"):
            if heading not in text:
                malformed.append(f"{item}:{heading}")
    return _check(
        "architecture_decision_records",
        "Architecture decision records",
        not missing and not malformed,
        "core maintenance decisions are captured as short ADRs",
        evidence=_existing((index, *(adr_root / item for item in REQUIRED_ADRS))),
        details={"missing": missing, "malformed": malformed},
    )


def check_docs_mirror(repo_root: Path) -> Check:
    sync_docs = _load_tool(repo_root, "tools/sync_docs_source.py", "maintenance_sync_docs_source")
    source = (repo_root.parent / "thales_agilab" / "docs" / "source").resolve()
    target = repo_root / "docs/source"
    if not source.is_dir():
        return _check(
            "docs_mirror",
            "Docs mirror",
            False,
            "canonical docs source is unavailable; mirror drift was not checked",
            status="warn",
            evidence=(target.as_posix(),),
            details={"source": source.as_posix()},
        )
    plan = sync_docs.make_sync_plan(source, target, delete_extra=True)
    stamp_ok, stamp_message = sync_docs.verify_mirror_stamp(target)
    ok = not plan.has_changes() and stamp_ok
    return _check(
        "docs_mirror",
        "Docs mirror",
        ok,
        "canonical docs and public mirror are aligned",
        evidence=(source.as_posix(), target.as_posix(), "docs/.docs_source_mirror_stamp.json"),
        details={
            "create": len(plan.created),
            "update": len(plan.updated),
            "delete": len(plan.deleted),
            "stamp_ok": stamp_ok,
            "stamp_message": stamp_message,
        },
    )


def check_app_contracts(repo_root: Path) -> Check:
    app_contract_matrix = _load_tool(
        repo_root,
        "tools/app_contract_matrix.py",
        "maintenance_app_contract_matrix",
    )
    report = app_contract_matrix.build_report(repo_root=repo_root)
    summary = report.get("summary", {})
    return _check(
        "app_contract_matrix",
        "App and package contracts",
        report.get("status") == "pass",
        "built-in apps, package metadata, reducer contracts, and public catalog align",
        evidence=("tools/app_contract_matrix.py", "docs/source/public-app-catalog.rst"),
        details={
            "project_count": summary.get("project_count"),
            "check_count": summary.get("check_count"),
            "failed": summary.get("failed"),
            "failed_projects": summary.get("failed_projects", {}),
        },
    )


def check_package_split(repo_root: Path) -> Check:
    package_split = _load_tool(
        repo_root,
        "tools/package_split_contract.py",
        "maintenance_package_split_contract",
    )
    packages = list(package_split.PACKAGE_CONTRACTS)
    names = [package.name for package in packages]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    missing_pyprojects = [
        package.pyproject
        for package in packages
        if not (repo_root / package.pyproject).is_file()
    ]
    role_counts: dict[str, int] = {}
    for package in packages:
        role_counts[package.role] = role_counts.get(package.role, 0) + 1
    ok = not duplicates and not missing_pyprojects and bool(role_counts.get("top-level-bundle"))
    return _check(
        "package_split_contract",
        "Package split contract",
        ok,
        "package split has unique names, existing pyprojects, and one top-level bundle",
        evidence=("tools/package_split_contract.py",),
        details={
            "package_count": len(packages),
            "role_counts": role_counts,
            "duplicates": duplicates,
            "missing_pyprojects": missing_pyprojects,
        },
    )


def check_release_friction(repo_root: Path) -> Check:
    release_plan = _load_tool(repo_root, "tools/release_plan.py", "maintenance_release_plan")
    payload = release_plan.release_plan(
        repo_root=repo_root,
        skip_existing_pypi=True,
        pypi_artifacts_exist=lambda _entry, _root: True,
    )
    ok = (
        payload.get("pypi_selection_mode") == "missing-artifacts"
        and payload.get("pypi_publish_selected") == "false"
        and bool(payload.get("pypi_existing_packages"))
    )
    return _check(
        "release_skip_existing_packages",
        "Release skip-existing package mode",
        ok,
        "release plan can avoid rebuilding and reuploading packages whose artifacts already exist",
        evidence=("tools/release_plan.py", ".github/workflows/pypi-publish.yaml"),
        details={
            "pypi_selection_mode": payload.get("pypi_selection_mode"),
            "pypi_publish_selected": payload.get("pypi_publish_selected"),
            "existing_count": len(payload.get("pypi_existing_packages", [])),
        },
    )


def check_evidence_core_docs(repo_root: Path) -> Check:
    required = {
        "docs/source/capability-map.rst": (
            "Evidence Core reading order",
            "``run_manifest.json``",
            "``.agipack``",
        ),
        "docs/source/proof-capsule.rst": (
            "agilab prove",
            "promotion-dossier",
            "Replay is safe",
        ),
        "docs/source/evidence-taxonomy.rst": (
            "run_manifest_event",
            "artifact_event",
            "policy_check_event",
        ),
    }
    missing: dict[str, list[str]] = {}
    for rel_path, phrases in required.items():
        text = _read(repo_root / rel_path) if (repo_root / rel_path).is_file() else ""
        misses = [phrase for phrase in phrases if phrase not in text]
        if misses:
            missing[rel_path] = misses
    return _check(
        "evidence_core_docs",
        "Evidence Core docs",
        not missing,
        "evidence, proof capsule, and taxonomy docs expose the maintenance backbone",
        evidence=tuple(required),
        details={"missing": missing},
    )


def check_product_tiers(repo_root: Path) -> Check:
    files = (
        repo_root / "docs/source/capability-map.rst",
        repo_root / "docs/source/data-connectors.rst",
    )
    missing: dict[str, list[str]] = {}
    for path in files:
        text = _read(path) if path.is_file() else ""
        misses = [label for label in MATURITY_LABELS if label not in text]
        if path.name == "data-connectors.rst":
            misses = [
                label
                for label in ("Local proof", "Contract proof", "Operator-triggered live check")
                if label not in text
            ]
        if misses:
            missing[path.as_posix()] = misses
    return _check(
        "product_tier_labels",
        "Product maturity labels",
        not missing,
        "public docs separate live paths, local proofs, contract proofs, live checks, and roadmap",
        evidence=tuple(path.as_posix() for path in files if path.exists()),
        details={"missing": missing},
    )


def check_shared_core_guardrails(repo_root: Path) -> Check:
    required = {
        "AGENTS.md": ("Shared core approval gate", "shared-core-typing"),
        "tools/impact_validate.py": ("shared-core", "shared-core-approval"),
        "tools/workflow_parity.py": ("shared-core-typing", "ty-typing"),
    }
    missing: dict[str, list[str]] = {}
    for rel_path, phrases in required.items():
        text = _read(repo_root / rel_path) if (repo_root / rel_path).is_file() else ""
        misses = [phrase for phrase in phrases if phrase not in text]
        if misses:
            missing[rel_path] = misses
    return _check(
        "shared_core_guardrails",
        "Shared-core guardrails",
        not missing,
        "shared-core changes have approval, impact, and typing gates",
        evidence=tuple(required),
        details={"missing": missing},
    )


def _git_ls_files(repo_root: Path, pathspec: str) -> list[str]:
    completed = subprocess.run(
        ["git", "ls-files", pathspec],
        cwd=repo_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode:
        return []
    return [line for line in completed.stdout.splitlines() if line.strip()]


def check_generated_artifact_hygiene(repo_root: Path) -> Check:
    tracked_docs_html = _git_ls_files(repo_root, "docs/html")
    generated_dirs = [
        path.relative_to(repo_root).as_posix()
        for path in repo_root.glob("src/agilab/lib/*/build/lib")
        if path.is_dir()
    ]
    status = "pass" if not tracked_docs_html else "fail"
    return _check(
        "generated_artifact_hygiene",
        "Generated artifact hygiene",
        not tracked_docs_html,
        "generated docs are not tracked; build/lib duplicates are visible for cleanup review",
        evidence=("docs/html", "src/agilab/lib/*/build/lib"),
        details={
            "tracked_docs_html": tracked_docs_html,
            "build_lib_duplicate_count": len(generated_dirs),
            "build_lib_duplicates": generated_dirs[:20],
        },
        status=status,
    )


def check_todo_hotspots(repo_root: Path, *, max_hotspots: int = 25) -> Check:
    roots = ("src/agilab", "tools", "test", "docs/source")
    pattern = re.compile(r"\b(TODO|FIXME|XXX)\b", re.IGNORECASE)
    counts: dict[str, int] = {}
    for root_name in roots:
        root = repo_root / root_name
        if not root.exists():
            continue
        for path in root.rglob("*"):
            rel = path.relative_to(repo_root).as_posix()
            if not path.is_file() or any(part in rel for part in ("/.venv/", "/__pycache__/", "/build/")):
                continue
            if path.suffix not in {".py", ".md", ".rst", ".toml", ".yaml", ".yml", ".json"}:
                continue
            try:
                count = len(pattern.findall(_read(path)))
            except UnicodeDecodeError:
                continue
            if count:
                counts[rel] = count
    total = sum(counts.values())
    top = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:max_hotspots]
    return _check(
        "todo_hotspots",
        "TODO/FIXME hotspots",
        True,
        "TODO/FIXME/XXX hotspots are reported for maintenance triage",
        status="warn" if total else "pass",
        evidence=roots,
        details={"total": total, "top": top},
    )


def _coverage_percent(svg_text: str) -> int | None:
    match = re.search(r"coverage:\s*(\d+)%", svg_text)
    return int(match.group(1)) if match else None


def check_coverage_badges(repo_root: Path) -> Check:
    badge = repo_root / "badges/coverage-agilab.svg"
    percent = _coverage_percent(_read(badge)) if badge.is_file() else None
    if percent is None:
        return _check(
            "coverage_badge_signal",
            "Coverage badge signal",
            False,
            "global coverage badge is missing or unreadable",
            evidence=(badge.as_posix(),),
            details={"percent": percent},
        )
    status = "pass" if percent >= 99 else "warn"
    return _check(
        "coverage_badge_signal",
        "Coverage badge signal",
        True,
        "global coverage badge is readable; below-99 coverage is a maintenance warning",
        status=status,
        evidence=(badge.as_posix(),),
        details={"percent": percent, "target": 99},
    )


def build_report(
    *,
    repo_root: Path = ROOT,
    include_app_contracts: bool = True,
    include_hotspots: bool = True,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    checks = [
        check_extension_contract_kit(repo_root),
        check_adrs(repo_root),
        check_docs_mirror(repo_root),
        check_package_split(repo_root),
        check_release_friction(repo_root),
        check_evidence_core_docs(repo_root),
        check_product_tiers(repo_root),
        check_shared_core_guardrails(repo_root),
        check_generated_artifact_hygiene(repo_root),
        check_coverage_badges(repo_root),
    ]
    if include_app_contracts:
        checks.insert(4, check_app_contracts(repo_root))
    if include_hotspots:
        checks.append(check_todo_hotspots(repo_root))

    failed = [check for check in checks if check.status == "fail"]
    warned = [check for check in checks if check.status == "warn"]
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo_root": repo_root.as_posix(),
        "status": "fail" if failed else "pass",
        "summary": {
            "check_count": len(checks),
            "passed": len([check for check in checks if check.status == "pass"]),
            "warned": len(warned),
            "failed": len(failed),
        },
        "checks": [check.as_dict() for check in checks],
    }


def render_text(report: dict[str, Any]) -> str:
    lines = [
        "AGILAB maintenance dashboard",
        f"status: {report['status']}",
        (
            "summary: "
            f"{report['summary']['passed']} pass, "
            f"{report['summary']['warned']} warn, "
            f"{report['summary']['failed']} fail"
        ),
        "",
    ]
    for check in report["checks"]:
        lines.append(f"[{check['status'].upper()}] {check['id']}: {check['summary']}")
    return "\n".join(lines)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--compact", action="store_true")
    parser.add_argument("--strict", action="store_true", help="Return non-zero on warnings as well as failures.")
    parser.add_argument("--skip-app-contracts", action="store_true")
    parser.add_argument("--skip-hotspots", action="store_true")
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(
        repo_root=args.repo_root,
        include_app_contracts=not args.skip_app_contracts,
        include_hotspots=not args.skip_hotspots,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json or args.compact:
        if args.compact:
            print(json.dumps(report, sort_keys=True, separators=(",", ":")))
        else:
            print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(render_text(report))
    if report["status"] == "fail":
        return 1
    if args.strict and report["summary"]["warned"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
