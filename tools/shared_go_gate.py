#!/usr/bin/env python3
"""Write the hardened shared-use go/no-go artifact for AGILAB."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from tools.profile_supply_chain_scan import DEFAULT_PROFILES, first_party_sources
    from tools.security_hygiene_report import (
        EditableRequirement,
        ScanRequirementsInventory,
        _regular_file_stat,
        _scan_requirements_inventory,
        _validate_pip_audit_payload,
        _validate_sbom_payload,
    )
except ModuleNotFoundError as exc:  # Direct execution via ``python tools/...``.
    if exc.name != "tools":
        raise
    from profile_supply_chain_scan import DEFAULT_PROFILES, first_party_sources
    from security_hygiene_report import (
        EditableRequirement,
        ScanRequirementsInventory,
        _regular_file_stat,
        _scan_requirements_inventory,
        _validate_pip_audit_payload,
        _validate_sbom_payload,
    )

SCHEMA = "agilab.shared_go_gate.v1"
DEFAULT_SECURITY_CHECK = Path("test-results/security-check.json")
DEFAULT_SUPPLY_CHAIN_DIR = Path("test-results/supply-chain")
DEFAULT_OUTPUT = Path("test-results/shared_go_gate.json")
DEFAULT_MAX_AGE_DAYS = 30
INSTALL_PROFILES = DEFAULT_PROFILES


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _read_json(path: Path) -> tuple[dict[str, Any] | list[Any] | None, str | None]:
    _metadata, error = _regular_file_stat(path)
    if error is not None:
        return None, error
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, "artifact could not be read as JSON"
    if isinstance(payload, (dict, list)):
        return payload, None
    return None, "JSON root must be an object or list"


def _file_state(path: Path, *, now: datetime, max_age_days: int) -> dict[str, Any]:
    state: dict[str, Any] = {
        "path": str(path),
        "exists": False,
        "fresh": False,
        "status": "fail",
    }
    metadata, error = _regular_file_stat(path)
    if metadata is None:
        state["error"] = error
        return state
    try:
        state["exists"] = True
        mtime = datetime.fromtimestamp(metadata.st_mtime, timezone.utc)
        age_days = (now - mtime).total_seconds() / 86400
    except (OSError, ValueError, OverflowError):
        state["error"] = "artifact freshness could not be determined"
        return state
    state["age_days"] = round(age_days, 3)
    state["fresh"] = 0 <= age_days <= max_age_days
    state["status"] = "pass" if state["fresh"] else "fail"
    state["error"] = (
        None if state["fresh"] else "artifact timestamp is stale or in the future"
    )
    return state


def _artifact_state(
    path: Path,
    *,
    now: datetime,
    max_age_days: int,
    artifact_kind: str,
    expected_inventory: Mapping[str, str] | None,
    expected_editables: Sequence[EditableRequirement] = (),
    expected_sources: Mapping[str, Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    state = _file_state(path, now=now, max_age_days=max_age_days)
    payload, read_error = _read_json(path)
    if artifact_kind == "pip_audit":
        count, validation_error = _validate_pip_audit_payload(
            payload, require_inventory=True, expected_inventory=expected_inventory
        )
        count_key = "vulnerability_count"
        acceptable_count = count == 0
    elif artifact_kind == "sbom":
        count, validation_error = _validate_sbom_payload(
            payload,
            require_inventory=True,
            expected_inventory=expected_inventory,
            expected_editables=expected_editables,
            expected_sources=expected_sources,
        )
        # The requirements-based producer emits no vulnerability findings.
        if isinstance(payload, dict) and payload.get("vulnerabilities", []) != []:
            validation_error = (
                "SBOM contains vulnerability findings or invalid vulnerability data"
            )
        count_key = "component_count"
        acceptable_count = count is not None
    else:
        raise ValueError("unsupported artifact kind")
    valid = read_error is None and validation_error is None and acceptable_count
    error = read_error
    if validation_error is not None or count is None:
        # Validator errors can include untrusted package names or requirements.
        error = error or "artifact schema or requirements inventory is invalid"
    elif not acceptable_count:
        error = error or "artifact reports known vulnerabilities"
    state.update(
        valid_json=payload is not None and read_error is None,
        valid_evidence=valid,
        status="pass" if state["fresh"] and valid else "fail",
        error=state.get("error") or error,
    )
    state[count_key] = count
    return state


def _requirements_state(
    path: Path,
    *,
    now: datetime,
    max_age_days: int,
    registered_sources: Mapping[str, Mapping[str, str]] | None = None,
    source_inventory: dict[str, Mapping[str, str]] | None = None,
) -> tuple[dict[str, Any], ScanRequirementsInventory | None]:
    state = _file_state(path, now=now, max_age_days=max_age_days)
    try:
        inventory, error = _scan_requirements_inventory(
            path,
            registered_sources=registered_sources,
            source_inventory=source_inventory,
        )
    except (OSError, ValueError):
        inventory, error = None, "invalid requirements"
    valid = inventory is not None and error is None
    state.update(
        valid_inventory=valid,
        status="pass" if state["fresh"] and valid else "fail",
        error=state.get("error")
        or (None if valid else "scan requirements are invalid or missing"),
    )
    return state, inventory


def _expand_profiles(values: Sequence[str] | None) -> tuple[str, ...]:
    if not values:
        return ("base",)
    expanded: list[str] = []
    for value in values:
        if value == "all":
            expanded.extend(INSTALL_PROFILES)
        else:
            expanded.append(value)
    return tuple(dict.fromkeys(expanded))


def _security_check_state(
    path: Path, *, now: datetime, max_age_days: int
) -> dict[str, Any]:
    file_state = _file_state(path, now=now, max_age_days=max_age_days)
    payload, error = _read_json(path)
    if not isinstance(payload, dict):
        return {
            "path": str(path),
            "exists": file_state["exists"],
            "status": "fail",
            "profile": None,
            "check_status": None,
            "error": error or "security-check artifact is not a JSON object",
        }
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    checks = payload.get("checks")
    check_count = summary.get("check_count")
    warnings = summary.get("warnings")
    failures = summary.get("failures")
    profile = summary.get("profile")
    check_status = payload.get("status")
    generated_at = payload.get("generated_at")
    age_days = None
    try:
        timestamp = (
            datetime.fromisoformat(generated_at)
            if isinstance(generated_at, str)
            else None
        )
        if timestamp is not None and timestamp.utcoffset() is not None:
            age_days = (now - timestamp).total_seconds() / 86400
    except (ValueError, OverflowError):
        pass
    fresh = age_days is not None and 0 <= age_days <= max_age_days
    passing_checks = (
        isinstance(checks, list)
        and bool(checks)
        and all(
            isinstance(check, dict) and check.get("status") == "pass"
            for check in checks
        )
    )
    conditions = [
        (
            payload.get("schema") == "agilab.security_check.v1"
            and type(payload.get("schema_version")) is int
            and payload["schema_version"] == 1
            and payload.get("kind") == "agilab.security_check",
            "security-check schema is invalid",
        ),
        (check_status == "pass", "security-check did not pass"),
        (
            profile in ("shared", "cluster", "public-ui"),
            "security-check requires a hardened profile",
        ),
        (
            type(summary.get("advisory")) is bool,
            "security-check advisory metadata is invalid",
        ),
        (
            passing_checks and type(check_count) is int and check_count == len(checks),
            "security-check counts or checks are invalid or inconsistent",
        ),
        (
            type(warnings) is int
            and warnings == 0
            and type(failures) is int
            and failures == 0,
            "security-check warning or failure counts are invalid or nonzero",
        ),
        (fresh, "security-check timestamp must be aware, fresh and not in the future"),
    ]
    error = next((message for valid, message in conditions if not valid), None)
    return {
        "path": str(path),
        "exists": True,
        "status": "pass" if error is None else "fail",
        "profile": profile
        if profile in ("local", "shared", "cluster", "public-ui")
        else None,
        "check_status": check_status
        if check_status in ("pass", "warn", "fail")
        else "unknown",
        "warnings": warnings if type(warnings) is int else None,
        "failures": failures if type(failures) is int else None,
        "schema": "agilab.security_check.v1" if conditions[0][0] else None,
        "fresh": fresh,
        "age_days": round(age_days, 3) if age_days is not None else None,
        "error": error,
    }


def _supply_chain_state(
    output_root: Path,
    *,
    profiles: Sequence[str],
    now: datetime,
    max_age_days: int,
) -> dict[str, Any]:
    try:
        sources = first_party_sources()
    except (OSError, ValueError):
        sources = None
    profile_states: dict[str, Any] = {}
    for profile in profiles:
        profile_dir = output_root / profile.replace("/", "-")
        source_inventory: dict[str, Mapping[str, str]] = {}
        requirements_state, requirements = _requirements_state(
            profile_dir / "requirements.txt",
            now=now,
            max_age_days=max_age_days,
            registered_sources=sources,
            source_inventory=source_inventory,
        )
        audit_requirements_state, audit_requirements = _requirements_state(
            profile_dir / "requirements-audit.txt", now=now, max_age_days=max_age_days
        )
        inventories_match = (
            requirements is not None
            and audit_requirements is not None
            and requirements[0] == audit_requirements[0]
            and {
                name: version
                for name, version in requirements[1].items()
                if name not in source_inventory
            }
            == audit_requirements[1]
            and not audit_requirements[2]
        )
        pip_state = _artifact_state(
            profile_dir / "pip-audit.json",
            now=now,
            max_age_days=max_age_days,
            artifact_kind="pip_audit",
            expected_inventory=audit_requirements[0]
            if audit_requirements is not None
            else None,
        )
        sbom_state = _artifact_state(
            profile_dir / "sbom-cyclonedx.json",
            now=now,
            max_age_days=max_age_days,
            artifact_kind="sbom",
            expected_inventory=requirements[1] if requirements is not None else None,
            expected_editables=requirements[2] if requirements is not None else (),
            expected_sources=source_inventory,
        )
        valid = inventories_match and all(
            state["status"] == "pass"
            for state in (
                requirements_state,
                audit_requirements_state,
                pip_state,
                sbom_state,
            )
        )
        profile_states[profile] = {
            "status": "pass" if valid else "fail",
            "pip_audit": pip_state,
            "sbom": sbom_state,
            "requirements": requirements_state,
            "audit_requirements": audit_requirements_state,
            "inventories_match": inventories_match,
        }
    failures = [
        profile
        for profile, state in profile_states.items()
        if isinstance(state, Mapping) and state.get("status") != "pass"
    ]
    return {
        "status": "pass" if not failures else "fail",
        "output_root": str(output_root),
        "profiles": profile_states,
        "failed_profiles": failures,
        "max_age_days": max_age_days,
    }


def build_gate(
    *,
    security_check_json: Path,
    supply_chain_dir: Path,
    install_profiles: Sequence[str],
    now: datetime | None = None,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
) -> dict[str, Any]:
    if type(max_age_days) is not int or max_age_days <= 0:
        raise ValueError("max_age_days must be a positive integer")
    if not install_profiles or any(
        profile not in INSTALL_PROFILES for profile in install_profiles
    ):
        raise ValueError("install_profiles must contain known install profiles")
    generated_at = now or _utc_now()
    if not isinstance(generated_at, datetime) or generated_at.utcoffset() is None:
        raise ValueError("now must have an explicit timezone")
    security = _security_check_state(
        security_check_json, now=generated_at, max_age_days=max_age_days
    )
    supply_chain = _supply_chain_state(
        supply_chain_dir,
        profiles=install_profiles,
        now=generated_at,
        max_age_days=max_age_days,
    )
    checks = {
        "security_check": security,
        "supply_chain": supply_chain,
    }
    failed = [
        name
        for name, state in checks.items()
        if isinstance(state, Mapping) and state.get("status") != "pass"
    ]
    decision = "go" if not failed else "blocked"
    return {
        "schema": SCHEMA,
        "generated_at": generated_at.isoformat(),
        "kind": "agilab.shared_go_gate",
        "decision": decision,
        "summary": {
            "failed_checks": failed,
            "install_profiles": list(install_profiles),
            "go_gate": "clean strict security-check plus fresh profile-specific SBOM and pip-audit evidence",
        },
        "checks": checks,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Persist AGILAB's hardened shared/team use decision from security-check "
            "and profile-specific supply-chain evidence."
        )
    )
    parser.add_argument(
        "--security-check-json", type=Path, default=DEFAULT_SECURITY_CHECK
    )
    parser.add_argument(
        "--supply-chain-dir", type=Path, default=DEFAULT_SUPPLY_CHAIN_DIR
    )
    parser.add_argument(
        "--install-profile",
        action="append",
        choices=[*INSTALL_PROFILES, "all"],
        help="Deployed install profile to require. Repeatable. Defaults to base.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--artifact-max-age-days", type=int, default=DEFAULT_MAX_AGE_DAYS
    )
    parser.add_argument(
        "--strict", action="store_true", help="Exit non-zero when the gate is blocked."
    )
    parser.add_argument(
        "--json", action="store_true", help="Print the full gate artifact to stdout."
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.artifact_max_age_days <= 0:
        parser.error("--artifact-max-age-days must be a positive integer")
    install_profiles = _expand_profiles(args.install_profile)
    gate = build_gate(
        security_check_json=args.security_check_json,
        supply_chain_dir=args.supply_chain_dir,
        install_profiles=install_profiles,
        max_age_days=args.artifact_max_age_days,
    )
    output = args.output.expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(gate, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if args.json:
        print(json.dumps(gate, indent=2, sort_keys=True))
    else:
        mode = "strict" if args.strict else "advisory"
        failed = ",".join(gate["summary"]["failed_checks"]) or "none"
        print(
            f"shared go gate artifact: {output} decision={gate['decision']} "
            f"profiles={','.join(install_profiles)} failed={failed} mode={mode}"
        )
    return 1 if args.strict and gate["decision"] != "go" else 0


if __name__ == "__main__":
    raise SystemExit(main())
