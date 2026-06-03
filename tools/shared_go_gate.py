#!/usr/bin/env python3
"""Write the hardened shared-use go/no-go artifact for AGILAB."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA = "agilab.shared_go_gate.v1"
DEFAULT_SECURITY_CHECK = Path("test-results/security-check.json")
DEFAULT_SUPPLY_CHAIN_DIR = Path("test-results/supply-chain")
DEFAULT_OUTPUT = Path("test-results/shared_go_gate.json")
DEFAULT_MAX_AGE_DAYS = 30
INSTALL_PROFILES = (
    "base",
    "ui",
    "pages",
    "ai",
    "agents",
    "examples",
    "mlflow",
    "local-llm",
    "offline",
    "dev",
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _read_json(path: Path) -> tuple[dict[str, Any] | list[Any] | None, str | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, str(exc)
    if isinstance(payload, (dict, list)):
        return payload, None
    return None, f"JSON root is {type(payload).__name__}, expected object or list"


def _artifact_state(path: Path, *, now: datetime, max_age_days: int) -> dict[str, Any]:
    if not path.is_file():
        return {
            "path": str(path),
            "exists": False,
            "fresh": False,
            "valid_json": False,
            "status": "fail",
        }
    mtime = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    age_days = (now - mtime).total_seconds() / 86400
    payload, error = _read_json(path)
    valid_json = payload is not None and error is None
    fresh = age_days <= max_age_days
    return {
        "path": str(path),
        "exists": True,
        "age_days": round(age_days, 3),
        "fresh": fresh,
        "valid_json": valid_json,
        "status": "pass" if fresh and valid_json else "fail",
        "error": error,
    }


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


def _security_check_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {
            "path": str(path),
            "exists": False,
            "status": "fail",
            "profile": None,
            "check_status": None,
            "error": "security-check artifact is missing",
        }
    payload, error = _read_json(path)
    if not isinstance(payload, dict):
        return {
            "path": str(path),
            "exists": True,
            "status": "fail",
            "profile": None,
            "check_status": None,
            "error": error or "security-check artifact is not a JSON object",
        }
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    check_status = str(payload.get("status") or "unknown")
    return {
        "path": str(path),
        "exists": True,
        "status": "pass" if check_status == "pass" else "fail",
        "profile": summary.get("profile"),
        "check_status": check_status,
        "warnings": summary.get("warnings"),
        "failures": summary.get("failures"),
        "schema": payload.get("schema"),
    }


def _supply_chain_state(
    output_root: Path,
    *,
    profiles: Sequence[str],
    now: datetime,
    max_age_days: int,
) -> dict[str, Any]:
    profile_states: dict[str, Any] = {}
    for profile in profiles:
        profile_dir = output_root / profile.replace("/", "-")
        pip_state = _artifact_state(
            profile_dir / "pip-audit.json",
            now=now,
            max_age_days=max_age_days,
        )
        sbom_state = _artifact_state(
            profile_dir / "sbom-cyclonedx.json",
            now=now,
            max_age_days=max_age_days,
        )
        profile_states[profile] = {
            "status": "pass" if pip_state["status"] == "pass" and sbom_state["status"] == "pass" else "fail",
            "pip_audit": pip_state,
            "sbom": sbom_state,
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
    generated_at = now or _utc_now()
    security = _security_check_state(security_check_json)
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
    parser.add_argument("--security-check-json", type=Path, default=DEFAULT_SECURITY_CHECK)
    parser.add_argument("--supply-chain-dir", type=Path, default=DEFAULT_SUPPLY_CHAIN_DIR)
    parser.add_argument(
        "--install-profile",
        action="append",
        choices=[*INSTALL_PROFILES, "all"],
        help="Deployed install profile to require. Repeatable. Defaults to base.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--artifact-max-age-days", type=int, default=DEFAULT_MAX_AGE_DAYS)
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when the gate is blocked.")
    parser.add_argument("--json", action="store_true", help="Print the full gate artifact to stdout.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    install_profiles = _expand_profiles(args.install_profile)
    gate = build_gate(
        security_check_json=args.security_check_json,
        supply_chain_dir=args.supply_chain_dir,
        install_profiles=install_profiles,
        max_age_days=args.artifact_max_age_days,
    )
    output = args.output.expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(gate, indent=2, sort_keys=True) + "\n", encoding="utf-8")
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
