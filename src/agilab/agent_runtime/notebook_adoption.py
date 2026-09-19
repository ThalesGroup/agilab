"""Local notebook-build counts and voluntary, content-free completion receipts.

No network requests are made here. Counts describe local workspaces or submitted
receipts, never all visitors or verified unique people.
"""
from __future__ import annotations

import argparse
from importlib.metadata import version
import json
from pathlib import Path
from uuid import UUID, uuid4
from urllib.parse import urlencode

from agilab.agent_runtime.agent_run import _atomic_write_text

SCHEMA = "agilab.notebook_adoption.v1"
FIELDS = {"schema", "receipt_id", "workspace_id", "status", "source_kind",
          "verification_scope", "duration_bucket", "agilab_version"}
SCOPES = {"iris_model_acceptance", "execution_and_interface"}


def _workspace_id(output: Path) -> str:
    path = output / ".notebook-adoption-id"
    candidate = output / f".adoption-{uuid4()}.tmp"
    candidate.write_text(str(uuid4()))
    try:
        path.hardlink_to(candidate)
    except FileExistsError:
        pass
    finally:
        candidate.unlink()
    return str(UUID(path.read_text().strip()))


def write_completion_receipt(root: Path, report: dict) -> None:
    if report.get("status") not in {"passed", "failed"}:
        return
    path = root / "completion_receipt.json"
    existing = json.loads(path.read_text()) if path.exists() else {}
    seconds = float(report.get("seconds", 0))
    receipt = {
        "schema": SCHEMA,
        "receipt_id": existing.get("receipt_id", str(uuid4())),
        "workspace_id": _workspace_id(root.parent),
        "status": report["status"],
        "source_kind": report.get("source", {}).get("source_kind", "curated"),
        "verification_scope": report.get("verification_scope", "iris_model_acceptance"),
        "duration_bucket": "under_5m" if seconds < 300 else "5_to_15m" if seconds < 900 else "15m_or_more",
        "agilab_version": version("agilab"),
    }
    validate_receipt(receipt)
    _atomic_write_text(path, json.dumps(receipt, indent=2) + "\n")


def validate_receipt(receipt: dict) -> None:
    if not isinstance(receipt, dict) or set(receipt) != FIELDS or receipt["schema"] != SCHEMA:
        raise ValueError("Unsupported completion receipt")
    for field in ("receipt_id", "workspace_id"):
        if str(UUID(receipt[field])) != receipt[field]:
            raise ValueError("Invalid anonymous receipt identifier")
    if receipt["status"] not in {"passed", "failed"}:
        raise ValueError("Receipt must describe a terminal build")
    if receipt["source_kind"] not in {"curated", "local", "github"}:
        raise ValueError("Unknown source kind")
    if receipt["verification_scope"] not in SCOPES:
        raise ValueError("Unknown verification scope")
    if receipt["duration_bucket"] not in {"under_5m", "5_to_15m", "15m_or_more"}:
        raise ValueError("Unknown duration bucket")
    release = receipt["agilab_version"]
    if not isinstance(release, str) or not release or len(release) > 40 or not all(c.isalnum() or c in ".+-" for c in release):
        raise ValueError("Invalid release identifier")


def summarize(receipts: list[dict]) -> dict:
    unique = {}
    for receipt in receipts:
        validate_receipt(receipt)
        key = receipt["receipt_id"]
        if key in unique and unique[key] != receipt:
            raise ValueError("Conflicting duplicate receipt")
        unique[key] = receipt
    completed = [r for r in unique.values() if r["status"] == "passed"]
    return {
        "schema": "agilab.notebook_adoption_summary.v1",
        "reported_builds": len(unique),
        "reported_completed_builds": len(completed),
        "reported_first_builds": len({r["workspace_id"] for r in completed}),
        "visitor_count": None,
        "visitor_conversion_rate": None,
        "basis": "Voluntarily supplied receipts; first builds count distinct local workspaces, not people. Receipts are self-reported, not authenticated attestations.",
    }


def github_report_url(receipt: dict) -> str:
    """Prepare a draft URL; only the visitor can submit the public issue."""
    validate_receipt(receipt)
    return "https://github.com/ThalesGroup/agilab/issues/new?" + urlencode({
        "title": "[Notebook first build] Completion receipt",
        "body": "I voluntarily share this build receipt.\n\n```json\n" + json.dumps(receipt, indent=2) + "\n```\n",
    })


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, default=Path.home() / "agilab-demo-runs")
    parser.add_argument("--receipts", type=Path, help="Directory containing voluntarily submitted JSON receipts")
    parser.add_argument("--github-issues", type=Path, help="JSON from gh issue list --json body for voluntary first-build reports")
    args = parser.parse_args()
    paths = sorted(args.receipts.glob("*.json") if args.receipts else args.runs.expanduser().glob("*/completion_receipt.json"))
    try:
        if args.github_issues:
            import re

            receipts = []
            for issue in json.loads(args.github_issues.read_text()):
                blocks = re.findall(r"```json\s*\n(.*?)\n```", issue.get("body", ""), flags=re.S)
                for block in blocks:
                    receipts.append(json.loads(block))
        else:
            receipts = [json.loads(path.read_text()) for path in paths]
        report = summarize(receipts)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
