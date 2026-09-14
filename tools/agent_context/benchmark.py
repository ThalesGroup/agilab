"""Repeat a fixed source-context benchmark using verified AGILAB experiments.

Compares full-owner reads with explicit excerpts from the SAME source checkout.
This measures retrieval packets and their acceptance, not completion of coding
work, model quality, prompt cache behavior, billed usage or end-to-end latency.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
from importlib.metadata import version

from tools.agent_context.materialize import materialize_context, reference_counter
from tools.agent_context_router import load_skill_index, recommend_context
from agilab.agent_runtime.experiment import execute_experiment, prepare_experiment
from agilab.agent_runtime.experiment_comparison import compare_experiments

FIXTURE = Path(__file__).with_name("benchmark_fixture")
CHECKS = [
    "exact_tasks",
    "context_intact",
    "mandatory_policy_intact",
    "selected_sources_complete",
    "within_context_budget",
]
TASKS = (
    (
        "builtin-return",
        "Adjust a return value in the minimal worker",
        (
            "src/agilab/apps/builtin/minimal_app_project/src/minimal_app_worker/minimal_app_worker.py::MinimalAppWorker",
        ),
    ),
    (
        "validator-integrity",
        "Check terminal agent evidence integrity",
        ("src/agilab/agent_runtime/verification.py::validate_agent_run",),
    ),
    (
        "workflow-cancellation",
        "Fix workflow cleanup after cancellation",
        (
            "src/agilab/pipeline/pipeline_execution.py",
            "src/agilab/pipeline/pipeline_run_state.py",
        ),
    ),
    (
        "notebook-export",
        "Verify notebook export artifact hashes",
        (
            "src/agilab/notebooks/notebook_export_support.py::verify_notebook_export_manifest",
        ),
    ),
    (
        "editor-state",
        "Preserve unsaved workflow editor values",
        (
            "src/agilab/pipeline/pipeline_page_state.py::prepare_pipeline_editor_updates",
            "src/agilab/pipeline/pipeline_page_state.py::hydrate_pipeline_editor_values",
        ),
    ),
)


def collect_contexts(root: Path, *, context_budget: int = 24000) -> dict:
    root = root.resolve()
    count = reference_counter()
    skills = load_skill_index(root / "agilab-capabilities.json")
    cases = []
    for task, prompt, selectors in TASKS:
        owners = list(dict.fromkeys(selector.split("::")[0] for selector in selectors))
        recommendation = recommend_context(
            files=owners,
            prompt=prompt,
            rules_path=root / "agent-context-rules.json",
            skills=skills,
            profile="agilab",
        )
        packets = {}
        for variant, selection in [("baseline", owners), ("candidate", selectors)]:
            packets[variant] = materialize_context(
                recommendation,
                root=root,
                count_tokens=count,
                selectors=selection,
                max_tokens=1_000_000,
                reserve_tokens=0,
                counter_name="o200k_base",
            )
            if not packets[variant]["complete"]:
                raise ValueError(
                    f"{task}/{variant}: source or mandatory context incomplete"
                )
        source_hashes = [
            {item["path"]: item["sha256"] for item in packets[variant]["selected"]}
            for variant in ("baseline", "candidate")
        ]
        if source_hashes[0] != source_hashes[1]:
            raise ValueError(f"{task}: source changed between paired reads")
        policy = {
            item["selector"]: item["sha256"]
            for item in packets["baseline"]["selected"]
            if item["required"]
        }
        cases.append(
            {"task": task, "prompt": prompt, "required_policy": policy, **packets}
        )
    revision = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain=v1", "--untracked-files=all"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return {
        "measurement": "fixed_source_retrieval_context",
        "encoding": "o200k_base",
        "tiktoken_version": version("tiktoken"),
        "source_revision": revision,
        "source_dirty": bool(dirty),
        "context_budget": context_budget,
        "cases": cases,
        "claim_scope": __doc__,
    }


def run_benchmark(
    root: Path, output: Path, *, repeats: int = 3, context_budget: int = 24000
) -> dict:
    if not 1 <= repeats <= 10 or context_budget <= 0:
        raise ValueError("Use 1-10 repeats and a positive context budget")
    corpus = collect_contexts(root, context_budget=context_budget)
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    source = output / "frozen-context-source"
    shutil.copytree(FIXTURE, source, ignore=shutil.ignore_patterns("__pycache__"))
    (source / "contexts.json").write_text(
        json.dumps(corpus, indent=2) + "\n", encoding="utf-8"
    )
    for variant in ("baseline", "candidate"):
        prepare_experiment(
            source_root=source,
            output_dir=output / variant,
            files=[f"{variant}.py", "measure.py", "grader.py", "contexts.json"],
            entrypoint=f"{variant}.py",
            grader="grader.py",
            outputs=["measurements.json"],
            checks=CHECKS,
        )
    comparisons = []
    for repeat in range(repeats):
        attempt = f"sample-{repeat + 1}"
        for variant in ("baseline", "candidate"):
            execute_experiment(output / variant, attempt_id=attempt)
        comparison = compare_experiments(
            baseline_root=output / "baseline",
            baseline_receipt=f"attempts/{attempt}/receipt.json",
            candidate_root=output / "candidate",
            candidate_receipt=f"attempts/{attempt}/receipt.json",
        )
        (output / f"comparison-{repeat + 1}.json").write_text(
            json.dumps(comparison, indent=2) + "\n"
        )
        comparisons.append(comparison)
    rows = []
    for case in corpus["cases"]:
        rows.append(
            {
                "task": case["task"],
                "full_owner_reference_tokens": case["baseline"]["actual_tokens"],
                "selected_reference_tokens": case["candidate"]["actual_tokens"],
                "mandatory_policy_files": len(case["required_policy"]),
            }
        )
    result = {
        "measurement": corpus["measurement"],
        "source_revision": corpus["source_revision"],
        "source_dirty": corpus["source_dirty"],
        "encoding": corpus["encoding"],
        "tiktoken_version": corpus["tiktoken_version"],
        "context_budget": context_budget,
        "repeats": repeats,
        "rows": rows,
        "comparisons": comparisons,
        "model_usage": "not observed",
        "billed_token_savings": None,
        "model_task_completion": "not evaluated",
        "cache_state": "no model calls; local tokenizer cache unmanaged",
        "claim_scope": __doc__,
    }
    (output / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--context-budget", type=int, default=24000)
    args = parser.parse_args(argv)
    result = run_benchmark(
        args.root, args.output, repeats=args.repeats, context_budget=args.context_budget
    )
    print(
        json.dumps(
            {k: result[k] for k in ("measurement", "rows", "model_usage")}, indent=2
        )
    )
    return (
        0
        if all(row["candidate"]["status"] == "passed" for row in result["comparisons"])
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
