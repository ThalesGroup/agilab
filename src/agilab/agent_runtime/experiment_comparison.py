"""Compare verified agent experiments on the same frozen acceptance cohort."""

from pathlib import Path
from hashlib import sha256

from agilab.agent_runtime.experiment import (
    confined,
    load_plan,
    read_json,
    seal,
    verify_experiment,
)
from agilab.agent_runtime.usage import parse_codex_jsonl
from agilab.evidence.evidence_contract import sha256_payload


def _row(root, receipt_path, usage_output):
    verify_experiment(root, receipt_path)
    receipt = read_json(confined(root, receipt_path))
    plan = load_plan(root)
    cohort = {
        "files": [f for f in plan["files"] if f["path"] != plan["entrypoint"]],
        "grader": plan["grader"],
        "checks": plan["checks"],
        "outputs": plan["outputs"],
    }
    usage = {"status": "not_observed", "usage": None}
    if usage_output is not None:
        if usage_output not in plan["outputs"]:
            raise ValueError(
                "Usage must be an output registered in the verified experiment"
            )
        path = f"attempts/{receipt['attempt_id']}/workspace/{usage_output}"
        descriptor = next((r for r in receipt["outputs"] if r["path"] == path), None)
        if descriptor is None:
            raise ValueError("Registered usage output is missing")
        with confined(root, path).open("rb") as stream:
            raw = stream.read(8 * 1024 * 1024 + 1)
        if (
            len(raw) != descriptor["size_bytes"]
            or sha256(raw).hexdigest() != descriptor["sha256"]
        ):
            raise ValueError("Usage bytes changed after receipt verification")
        usage = parse_codex_jsonl(raw.decode("utf-8"))
        usage["source"] = descriptor
        usage["basis"] = (
            "Single terminal provider report observed in a verified local artifact; not billing attestation"
        )
    accepted = int(receipt["status"] == "passed")
    tokens = usage["usage"]["total_tokens"] if usage.get("usage") else None
    row = {
        "receipt_sha256": receipt["sha256"],
        "status": receipt["status"],
        "process_status": receipt["runs"]["entrypoint"]["status"],
        "acceptance": receipt["acceptance"],
        "attempts": 1,
        "accepted_runs": accepted,
        "duration_seconds": sum(
            run["duration_seconds"] for run in receipt["runs"].values()
        ),
        "usage": usage,
        "tokens_per_accepted_run": tokens if accepted else None,
    }
    return row, sha256_payload(cohort), receipt["runtime"]["executable_sha256"]


def compare_experiments(
    *,
    baseline_root: Path,
    baseline_receipt: str,
    candidate_root: Path,
    candidate_receipt: str,
    baseline_usage_output: str | None = None,
    candidate_usage_output: str | None = None,
) -> dict:
    baseline, cohort, runtime = _row(
        baseline_root.resolve(), baseline_receipt, baseline_usage_output
    )
    candidate, other_cohort, other_runtime = _row(
        candidate_root.resolve(), candidate_receipt, candidate_usage_output
    )
    if baseline["receipt_sha256"] == candidate["receipt_sha256"]:
        raise ValueError(
            "Comparison requires distinct observations, not copies of one receipt"
        )
    if cohort != other_cohort or runtime != other_runtime:
        raise ValueError(
            "Comparison requires the same frozen cohort, grader, checks and interpreter"
        )
    return seal(
        {
            "schema": "agilab.agent_experiment_comparison.v1",
            "producer": "agilab.agent_runtime.experiment_comparison.compare_experiments",
            "cohort_sha256": cohort,
            "baseline": baseline,
            "candidate": candidate,
            "accepted_runs": baseline["accepted_runs"] + candidate["accepted_runs"],
            "attempts": 2,
            "improved_acceptance": candidate["accepted_runs"]
            > baseline["accepted_runs"],
            "claim_scope": "Paired local observations on one declared cohort, not a model-quality benchmark or population estimate.",
        }
    )
