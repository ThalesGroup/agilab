#!/usr/bin/env python3
"""Emit AGILAB static supply-chain integrity inventory evidence.

This is the canonical operator entry point. The older
``supply_chain_attestation_report.py`` command remains as a compatibility alias
for existing automation and schema-v1 consumers.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Sequence

CANONICAL_SCHEMA = "agilab.supply_chain_integrity_snapshot.v1"


def _load_legacy_build_report():
    module_path = Path(__file__).with_name("supply_chain_attestation_report.py")
    spec = importlib.util.spec_from_file_location(
        "agilab_supply_chain_attestation_report_compat", module_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load compatibility report: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.build_report


def build_report(
    *,
    repo_root: Path | None = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"output_path": output_path}
    if repo_root is not None:
        kwargs["repo_root"] = repo_root
    report = _load_legacy_build_report()(**kwargs)
    summary = report.setdefault("summary", {})
    summary["canonical_schema"] = CANONICAL_SCHEMA
    summary["legacy_schema"] = summary.get("schema")
    summary["evidence_kind"] = "inventory_snapshot"
    summary["formal_supply_chain_attestation"] = False
    report["report"] = "Supply-chain integrity snapshot report"
    report["scope"] = (
        "Fingerprints local package, dependency, license, lockfile, and payload "
        "metadata without producing a signed provenance attestation."
    )
    return report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit AGILAB static supply-chain integrity inventory evidence."
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
