#!/usr/bin/env python3
"""Verify persisted notebook-derived stages against a fresh notebook result.

Copied outside the generated project before provider execution. This checks
local trusted generated code, not hostile code, scientific validity, cluster
execution or equivalence with the upstream notebook before adaptation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import tomllib


def result_digest(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def verify(
    project: Path, *, module: str, result_file: str, expected_sha256: str
) -> dict:
    project = project.resolve()
    if result_file not in {"results.json", "metrics.json"}:
        raise ValueError("Unsupported notebook result artifact")
    stages_path = project / "lab_stages.toml"
    if stages_path.is_symlink() or not stages_path.is_file():
        raise ValueError("Missing regular lab_stages.toml")
    stages_bytes = stages_path.read_bytes()
    stages_sha256 = hashlib.sha256(stages_bytes).hexdigest()
    contract = tomllib.loads(stages_bytes.decode("utf-8"))
    stages = contract.get(module)
    if not isinstance(stages, list) or not stages:
        raise ValueError("Imported workflow must contain executable stages")
    if contract.get("__meta__"):
        raise ValueError(
            "Workflow automation metadata requires the full AGILAB runtime verifier"
        )
    old_cwd, old_path = Path.cwd(), sys.path[:]
    try:
        sys.path.insert(0, str(project))
        with tempfile.TemporaryDirectory(prefix="agilab-workflow-check-") as scratch:
            os.chdir(scratch)
            for index, stage in enumerate(stages, 1):
                if (
                    not isinstance(stage, dict)
                    or not isinstance(stage.get("C"), str)
                    or not stage["C"].strip()
                ):
                    raise ValueError(f"Workflow stage {index} has no Python source")
                if stage.get("R", "runpy") != "runpy":
                    raise ValueError(
                        "Notebook workflow verification supports local runpy stages only"
                    )
                if any(
                    stage.get(key)
                    for key in ("E", "deps", "depends_on", "dependencies")
                ) or any(
                    key in stage
                    for key in (
                        "automation",
                        "enabled",
                        "skip",
                        "skip_if_outputs_exist",
                        "skip_if_outputs_current",
                        "profiles",
                        "pipeline_profiles",
                        "automation_profiles",
                    )
                ):
                    raise ValueError(
                        "Workflow execution controls require the full AGILAB runtime verifier"
                    )
                # Each workflow stage receives fresh globals, exactly where the
                # legacy cell projection lost notebook state. Cells within a
                # compiled stage share globals via that stage's generated code.
                namespace = {"__name__": "__main__", "PROJECT_ROOT": project}
                exec(
                    compile(
                        stage["C"],
                        f"lab_stages.toml:stage-{index}",
                        "exec",
                        dont_inherit=True,
                    ),
                    namespace,
                )
            output = Path(result_file)
            if output.is_symlink() or not output.is_file():
                raise ValueError(f"Imported workflow must write fresh {result_file}")
            actual_sha256 = result_digest(
                json.loads(output.read_text(encoding="utf-8"))
            )
            if actual_sha256 != expected_sha256:
                raise ValueError(
                    "Imported workflow result differs from the verified notebook result. "
                    "Check state transfer, random seeds and external inputs."
                )
    finally:
        os.chdir(old_cwd)
        sys.path[:] = old_path
    if stages_path.is_symlink() or stages_path.read_bytes() != stages_bytes:
        raise ValueError("lab_stages.toml changed during workflow verification")
    return {
        "schema": "agilab.notebook_workflow_verification.v1",
        "status": "passed",
        "verification_scope": "local_workflow_result_agreement",
        "checks": [
            "fresh_workflow_execution",
            "fresh_result_artifact",
            "notebook_result_agreement",
        ],
        "stages_sha256": stages_sha256,
        "stage_count": len(stages),
        "result_file": result_file,
        "result_sha256": actual_sha256,
        "scientific_correctness_verified": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module", required=True)
    parser.add_argument(
        "--result-file", choices=("results.json", "metrics.json"), required=True
    )
    parser.add_argument("--expected-sha256", required=True)
    args = parser.parse_args()
    try:
        report = verify(
            Path.cwd(),
            module=args.module,
            result_file=args.result_file,
            expected_sha256=args.expected_sha256,
        )
    except Exception as exc:
        report = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
