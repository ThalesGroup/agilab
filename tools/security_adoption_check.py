#!/usr/bin/env python3
"""Write an advisory AGILAB security-check artifact for adoption gates."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Sequence

from agilab import security_check


DEFAULT_OUTPUT = Path("test-results/security-check.json")
STRICT_ENV_VAR = "AGILAB_SECURITY_CHECK_STRICT"


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run AGILAB's advisory security-check and persist a JSON artifact. "
            "Warnings are non-blocking unless --strict or AGILAB_SECURITY_CHECK_STRICT=1 is set."
        )
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="JSON artifact path to write.",
    )
    parser.add_argument(
        "--profile",
        choices=security_check.PROFILES,
        default="shared",
        help="Security adoption profile to evaluate.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return non-zero when security-check reports advisory warnings.",
    )
    parser.add_argument("--env-file", type=Path, default=None, help="AGILAB .env file to inspect.")
    parser.add_argument("--pip-audit-json", type=Path, default=None)
    parser.add_argument("--sbom-json", type=Path, default=None)
    parser.add_argument(
        "--artifact-max-age-days",
        type=int,
        default=security_check.DEFAULT_ARTIFACT_MAX_AGE_DAYS,
        help="Maximum accepted age for pip-audit/SBOM artifacts.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Also print the full JSON report to stdout.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    strict = args.strict or _truthy(os.environ.get(STRICT_ENV_VAR))
    report = security_check.build_report(
        profile=args.profile,
        env_file=args.env_file,
        now=datetime.now(timezone.utc),
        pip_audit_json=args.pip_audit_json,
        sbom_json=args.sbom_json,
        artifact_max_age_days=args.artifact_max_age_days,
    )

    output = args.output.expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        warnings = report["summary"]["warnings"]
        mode = "strict" if strict else "advisory"
        print(
            f"security-check artifact: {output} "
            f"profile={args.profile} status={report['status']} warnings={warnings} mode={mode}"
        )

    return 1 if strict and report["status"] != "pass" else 0


if __name__ == "__main__":
    raise SystemExit(main())
