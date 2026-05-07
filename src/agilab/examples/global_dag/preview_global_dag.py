from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence


_EXAMPLES_ROOT = Path(__file__).resolve().parents[1]
_INTER_PROJECT_DAG_DIR = _EXAMPLES_ROOT / "inter_project_dag"
if str(_INTER_PROJECT_DAG_DIR) not in sys.path:
    sys.path.insert(0, str(_INTER_PROJECT_DAG_DIR))

from preview_inter_project_dag import build_preview as _build_inter_project_preview
from preview_inter_project_dag import planning_repo_root


DAG_PATH = Path(__file__).with_name("flight_to_meteo_global_dag.json")
DEFAULT_OUTPUT_PATH = Path.home() / "log" / "execute" / "global_dag" / "runner_state.json"


def build_preview(
    *,
    repo_root: Path,
    dag_path: Path = DAG_PATH,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    now: str = "2026-04-29T00:00:00Z",
) -> dict[str, Any]:
    summary = _build_inter_project_preview(
        repo_root=repo_root,
        dag_path=dag_path,
        output_path=output_path,
        now=now,
    )
    summary["example"] = "global_dag"
    summary["alias_of"] = "inter_project_dag"
    summary["goal"] = "Preview a global DAG that coordinates multiple AGILAB apps through artifact contracts."
    return summary


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preview a two-project AGILAB global DAG without executing either app."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Optional source checkout root. If omitted, the example uses the local source layout or AGILAB marker.",
    )
    parser.add_argument(
        "--dag-path",
        type=Path,
        default=DAG_PATH,
        help="Path to an agilab.multi_app_dag.v1 JSON contract.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Where to write the read-only runner-state preview JSON.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> dict[str, Any]:
    args = _parse_args(argv)
    summary = build_preview(
        repo_root=planning_repo_root(args.repo_root),
        dag_path=args.dag_path.expanduser(),
        output_path=args.output.expanduser(),
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return summary


if __name__ == "__main__":
    main()
