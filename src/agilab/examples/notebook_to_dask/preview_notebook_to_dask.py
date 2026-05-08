from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path
from typing import Any, Mapping, Sequence


_PACKAGE_ROOT = Path(__file__).resolve().parents[2]
_SOURCE_ROOT = _PACKAGE_ROOT.parent
if _PACKAGE_ROOT.name == "agilab" and str(_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SOURCE_ROOT))
_agilab_pkg = sys.modules.get("agilab")
if _agilab_pkg is not None:
    package_paths = list(getattr(_agilab_pkg, "__path__", []) or [])
    package_path = str(_PACKAGE_ROOT)
    if package_path not in package_paths:
        _agilab_pkg.__path__ = [*package_paths, package_path]

from agilab.notebook_pipeline_import import build_lab_stages_preview, build_notebook_pipeline_import


EXAMPLE_DIR = Path(__file__).resolve().parent
NOTEBOOK_PATH = EXAMPLE_DIR / "notebook_to_dask_sample.ipynb"
LAB_STAGES_PATH = EXAMPLE_DIR / "lab_stages.toml"
PIPELINE_VIEW_PATH = EXAMPLE_DIR / "pipeline_view.json"
DEFAULT_OUTPUT_PATH = Path.home() / "log" / "execute" / "notebook_to_dask" / "migration_preview.json"
PROJECT_NAME = "notebook_to_dask_project"


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def load_lab_stages(path: Path) -> dict[str, Any]:
    with path.expanduser().open("rb") as stream:
        payload = tomllib.load(stream)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a TOML table")
    return payload


def _artifact_paths(notebook_import: Mapping[str, Any]) -> list[str]:
    references = notebook_import.get("artifact_references", [])
    if not isinstance(references, list):
        return []
    paths: list[str] = []
    for reference in references:
        if not isinstance(reference, Mapping):
            continue
        path = str(reference.get("path", "") or "").strip()
        if path and path not in paths:
            paths.append(path)
    return paths


def artifact_contract_from_import(
    notebook_import: Mapping[str, Any],
    pipeline_view: Mapping[str, Any],
) -> dict[str, list[str]]:
    declared = pipeline_view.get("artifact_contract", {})
    declared_inputs = declared.get("inputs", []) if isinstance(declared, Mapping) else []
    declared_outputs = declared.get("outputs", []) if isinstance(declared, Mapping) else []
    discovered = _artifact_paths(notebook_import)

    inputs = [str(path) for path in declared_inputs if str(path)]
    outputs = [str(path) for path in declared_outputs if str(path)]
    for path in discovered:
        target = inputs if path.startswith("data/") else outputs
        if path not in target:
            target.append(path)
    return {
        "inputs": sorted(inputs),
        "outputs": sorted(outputs),
        "analysis_consumes": sorted(
            str(path)
            for path in declared.get("analysis_consumes", [])  # type: ignore[union-attr]
            if str(path)
        )
        if isinstance(declared, Mapping)
        else [],
    }


def dask_solution_from_import(notebook_import: Mapping[str, Any]) -> dict[str, Any]:
    stages = notebook_import.get("pipeline_stages", [])
    dask_stages: list[dict[str, Any]] = []
    if isinstance(stages, list):
        for stage in stages:
            if not isinstance(stage, Mapping):
                continue
            hints = [str(item) for item in stage.get("env_hints", []) if str(item)]
            if "dask" in hints:
                dask_stages.append(
                    {
                        "id": str(stage.get("id", "")),
                        "order": int(stage.get("order", 0) or 0),
                        "env_hints": hints,
                        "artifacts": [
                            str(reference.get("path", ""))
                            for reference in stage.get("artifact_references", [])
                            if isinstance(reference, Mapping) and str(reference.get("path", ""))
                        ],
                    }
                )
    return {
        "engine": "dask.dataframe",
        "stage_ids": [stage["id"] for stage in dask_stages],
        "stage_count": len(dask_stages),
        "real_execution": False,
        "migration_note": "The preview identifies Dask cells and artifact boundaries without running the notebook.",
    }


def _sample_matches_generated(sample: Mapping[str, Any], generated: Mapping[str, Any]) -> bool:
    sample_stages = sample.get(PROJECT_NAME, [])
    generated_stages = generated.get(PROJECT_NAME, [])
    if not isinstance(sample_stages, list) or not isinstance(generated_stages, list):
        return False
    if len(sample_stages) != len(generated_stages):
        return False
    for sample_stage, generated_stage in zip(sample_stages, generated_stages):
        if not isinstance(sample_stage, Mapping) or not isinstance(generated_stage, Mapping):
            return False
        for key in ("D", "Q", "C", "NB_CELL_ID", "NB_CONTEXT_IDS", "NB_ENV_HINTS", "NB_ARTIFACT_REFERENCES"):
            if sample_stage.get(key) != generated_stage.get(key):
                return False
    return True


def build_preview(
    *,
    notebook_path: Path = NOTEBOOK_PATH,
    lab_stages_path: Path = LAB_STAGES_PATH,
    pipeline_view_path: Path = PIPELINE_VIEW_PATH,
    output_path: Path | None = DEFAULT_OUTPUT_PATH,
) -> dict[str, Any]:
    notebook = load_json(notebook_path)
    pipeline_view = load_json(pipeline_view_path)
    notebook_import = build_notebook_pipeline_import(
        notebook=notebook,
        source_notebook=notebook_path.name,
    )
    generated_lab_stages = build_lab_stages_preview(notebook_import, module_name=PROJECT_NAME)
    sample_lab_stages = load_lab_stages(lab_stages_path)
    contract = artifact_contract_from_import(notebook_import, pipeline_view)
    dask_solution = dask_solution_from_import(notebook_import)

    preview = {
        "example": "notebook_to_dask",
        "goal": "Preview how a notebook becomes a Dask-backed AGILAB pipeline with explicit artifacts.",
        "source_notebook": str(notebook_path),
        "pipeline_view": {
            "path": str(pipeline_view_path),
            "schema": str(pipeline_view.get("schema", "")),
            "node_count": len(pipeline_view.get("nodes", [])) if isinstance(pipeline_view.get("nodes", []), list) else 0,
            "edge_count": len(pipeline_view.get("edges", [])) if isinstance(pipeline_view.get("edges", []), list) else 0,
        },
        "notebook_import": {
            "schema": str(notebook_import.get("schema", "")),
            "execution_mode": str(notebook_import.get("execution_mode", "")),
            "summary": notebook_import.get("summary", {}),
            "env_hints": notebook_import.get("env_hints", []),
        },
        "artifact_contract": contract,
        "dask_solution": dask_solution,
        "lab_stages_preview": {
            "path": str(lab_stages_path),
            "generated_stage_count": len(generated_lab_stages.get(PROJECT_NAME, [])),
            "matches_generated": _sample_matches_generated(sample_lab_stages, generated_lab_stages),
        },
        "real_notebook_execution": False,
    }
    if output_path is not None:
        output_path = output_path.expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(preview, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return preview


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preview a notebook-to-Dask AGILAB migration without executing the notebook."
    )
    parser.add_argument("--notebook", type=Path, default=NOTEBOOK_PATH)
    parser.add_argument("--lab-stages", type=Path, default=LAB_STAGES_PATH)
    parser.add_argument("--pipeline-view", type=Path, default=PIPELINE_VIEW_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--no-output", action="store_true", help="Print only; do not write a preview JSON file.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> dict[str, Any]:
    args = _parse_args(argv)
    preview = build_preview(
        notebook_path=args.notebook.expanduser(),
        lab_stages_path=args.lab_stages.expanduser(),
        pipeline_view_path=args.pipeline_view.expanduser(),
        output_path=None if args.no_output else args.output,
    )
    print(json.dumps(preview, indent=2, sort_keys=True))
    return preview


if __name__ == "__main__":
    main()
