"""Run the deterministic baseline/candidate experiment pilot without model services."""

import argparse
from importlib.resources import files
import json
from pathlib import Path

from agilab.agent_runtime.experiment import execute_experiment, prepare_experiment
from agilab.agent_runtime.experiment_comparison import compare_experiments
from agilab.evidence.skill_evaluation import persist_evaluation


def run_demo(output: Path) -> dict:
    source = Path(str(files("agilab").joinpath("resources/agent_experiment")))
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    for variant in ("baseline", "candidate"):
        prepare_experiment(
            source_root=source,
            output_dir=output / variant,
            files=[f"{variant}.py", "grader.py", "inputs.json"],
            entrypoint=f"{variant}.py",
            grader="grader.py",
            outputs=["result.json"],
            checks=["finite_mean", "missing_values_excluded"],
        )
        execute_experiment(output / variant, attempt_id="pilot")
    comparison = compare_experiments(
        baseline_root=output / "baseline",
        baseline_receipt="attempts/pilot/receipt.json",
        candidate_root=output / "candidate",
        candidate_receipt="attempts/pilot/receipt.json",
    )
    persist_evaluation(output, "comparison.json", comparison)
    return comparison


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    comparison = run_demo(args.output)
    print(
        json.dumps(
            {
                "comparison": str(args.output.resolve() / "comparison.json"),
                "baseline": comparison["baseline"]["status"],
                "candidate": comparison["candidate"]["status"],
                "model_usage": "not observed; deterministic fixture",
            },
            indent=2,
        )
    )
    return 0 if comparison["improved_acceptance"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
