from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Sequence


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

from agilab.global_pipeline_execution_plan import build_execution_plan
from agilab.global_pipeline_runner_state import dispatch_next_runnable, persist_runner_state


DAG_PATH = (
    _PACKAGE_ROOT
    / "apps"
    / "builtin"
    / "global_dag_project"
    / "dag_templates"
    / "flight_to_weather_global_dag.json"
)
DEFAULT_OUTPUT_PATH = Path.home() / "log" / "execute" / "inter_project_dag" / "runner_state.json"
RUN_ID = "inter-project-dag-preview"


def agilab_package_path() -> Path:
    marker = Path.home() / ".local/share/agilab/.agilab-path"
    if not marker.is_file():
        raise SystemExit(
            "AGILAB is not initialized. Run the AGILAB installer or "
            "`agilab first-proof --json` before this example."
        )
    path = Path(marker.read_text(encoding="utf-8").strip()).expanduser()
    if not path.is_dir():
        raise SystemExit(f"AGILAB package path from {marker} does not exist: {path}")
    return path


def _source_checkout_root_from_file() -> Path | None:
    repo_root = Path(__file__).resolve().parents[4]
    if (repo_root / "src" / "agilab" / "apps" / "builtin").is_dir():
        return repo_root
    return None


def _source_checkout_root_from_package(package_path: Path) -> Path | None:
    parents = package_path.parents
    if len(parents) < 2:
        return None
    repo_root = parents[1]
    if (repo_root / "src" / "agilab" / "apps" / "builtin").is_dir():
        return repo_root
    return None


def _ensure_packaged_layout_adapter(package_path: Path) -> Path:
    apps_path = package_path / "apps"
    if not (apps_path / "builtin").is_dir():
        raise SystemExit(f"AGILAB built-in apps are not available under {apps_path}")

    repo_root = Path.home() / ".cache" / "agilab" / "inter_project_dag_layout"
    adapter_package = repo_root / "src" / "agilab"
    adapter_apps = adapter_package / "apps"
    adapter_package.mkdir(parents=True, exist_ok=True)

    if adapter_apps.is_symlink() and adapter_apps.resolve() != apps_path.resolve():
        adapter_apps.unlink()
    if not adapter_apps.exists():
        try:
            adapter_apps.symlink_to(apps_path, target_is_directory=True)
        except OSError:
            shutil.copytree(apps_path, adapter_apps, dirs_exist_ok=True)
    if not (repo_root / "src" / "agilab" / "apps" / "builtin").is_dir():
        raise SystemExit(f"Could not prepare a planning layout under {repo_root}")
    return repo_root


def planning_repo_root(explicit_repo_root: Path | None = None) -> Path:
    if explicit_repo_root is not None:
        return explicit_repo_root.expanduser().resolve()

    source_root = _source_checkout_root_from_file()
    if source_root is not None:
        return source_root.resolve()

    package_path = agilab_package_path()
    source_root = _source_checkout_root_from_package(package_path)
    if source_root is not None:
        return source_root.resolve()
    return _ensure_packaged_layout_adapter(package_path).resolve()


def _unit_preview(unit: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": unit["id"],
        "app": unit["app"],
        "dispatch_status": "runnable" if unit.get("ready") is True else "blocked",
        "depends_on": list(unit.get("depends_on", [])),
        "produces": [
            artifact["artifact"]
            for artifact in unit.get("produces", [])
            if isinstance(artifact, dict) and artifact.get("artifact")
        ],
    }


def _artifact_handoffs(units: Sequence[dict[str, Any]]) -> list[dict[str, str]]:
    handoffs: list[dict[str, str]] = []
    units_by_id = {str(unit.get("id", "")): unit for unit in units}
    for unit in units:
        for dependency in unit.get("artifact_dependencies", []):
            if not isinstance(dependency, dict):
                continue
            source_id = str(dependency.get("from", ""))
            source_unit = units_by_id.get(source_id, {})
            handoffs.append(
                {
                    "artifact": str(dependency.get("artifact", "")),
                    "from": source_id,
                    "from_app": str(dependency.get("from_app", "")),
                    "source_path": str(dependency.get("source_path", "")),
                    "to": str(unit.get("id", "")),
                    "to_app": str(unit.get("app", "")),
                    "handoff": str(dependency.get("handoff", "")),
                    "producer_status": "runnable" if source_unit.get("ready") is True else "blocked",
                }
            )
    return handoffs


def build_preview(
    *,
    repo_root: Path,
    dag_path: Path = DAG_PATH,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    now: str = "2026-04-29T00:00:00Z",
) -> dict[str, Any]:
    plan = build_execution_plan(repo_root=repo_root, dag_path=dag_path)
    proof = persist_runner_state(
        repo_root=repo_root,
        dag_path=dag_path,
        output_path=output_path,
        run_id=RUN_ID,
        now=now,
    )
    dispatch = dispatch_next_runnable(proof.runner_state, now=now)
    units = list(plan.runnable_units)

    return {
        "example": "inter_project_dag",
        "goal": "Plan a cross-project AGILAB DAG from artifact contracts before executing apps.",
        "dag": {
            "path": plan.dag_path,
            "ok": plan.ok,
            "issues": [issue.as_dict() for issue in plan.issues],
            "execution_order": list(plan.execution_order),
        },
        "units": [_unit_preview(unit) for unit in units],
        "artifact_handoffs": _artifact_handoffs(units),
        "runner_state": {
            "path": proof.path,
            "round_trip_ok": proof.round_trip_ok,
            "run_status": proof.runner_state["run_status"],
            "summary": proof.runner_state["summary"],
        },
        "after_first_dispatch": {
            "ok": dispatch.ok,
            "dispatched_unit_id": dispatch.dispatched_unit_id,
            "run_status": dispatch.state["run_status"],
            "summary": dispatch.state["summary"],
        },
        "real_app_execution": False,
    }


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preview a two-project AGILAB DAG without executing either app."
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
